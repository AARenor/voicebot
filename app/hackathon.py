"""Bounded, memory-only fictional HTTP sessions; native CallTools owns writes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from inspect import getattr_static
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from .telephone import CallTools
from .languages import LANGUAGES
from .booking_response import trusted_booking_response
from . import call_history, callslog
from .providers.errors import PROVIDER_FAILURE_REASONS, ProviderError

SESSION_TTL = 600
MAX_SESSIONS = 16
MAX_TURNS = 24
MAX_TURN_BODY_BYTES = 750_000  # accommodates the bounded base64 audio envelope
VOICE_IDS = ("azure", "elevenlabs", "google", "cartesia")


@dataclass
class DemoSession:
    owner: str
    tools: CallTools
    expires_at: float
    history: list = field(default_factory=list)
    booking_details: dict = field(default_factory=dict)
    busy: bool = False
    turn_count: int = 0
    expiry: object = None
    recap_delivery: dict | None = None
    booking_recap_delivery: dict | None = None
    voice_id: str = "azure"

    def _recap_is_current(self, pending, text):
        state = self.tools
        if (
            pending is None
            or pending is not state.pending
            or state.mutation_uncertain
            or state.outcome == "write_outcome_unknown"
            or time.monotonic() >= self.expires_at
        ):
            return False
        held = {
            "slot": state.held_slots,
            "stay": state.held_stays,
            "table": state.held_tables,
        }.get(pending.get("kind"), {})
        hold_id = pending.get("hold_id")
        return (
            hold_id in state.holds
            and hold_id in held
            and hold_id not in state.confirmed_holds
            and isinstance(text, str)
            and bool(text)
            and state.render_recap(hold_id) == text
        )

    def consume_recap_delivery(self, delivery_id):
        # One receipt, one next input; not a remembered yes or a generic hold ID.
        delivery, self.recap_delivery = self.recap_delivery, None
        if delivery_id is None:
            return
        if (
            delivery is None
            or delivery_id != delivery["id"]
            or delivery["language"] != self.tools.language
            or not self._recap_is_current(delivery["pending"], delivery["text"])
            or not self.tools.mark_recap_delivered(delivery["pending"]["hold_id"])
        ):
            raise HTTPException(409, "recap_delivery_expired_or_unknown")


def operator_scope(authorization):
    return hashlib.sha256((authorization or "").encode()).hexdigest()


class DemoSessions:
    # ponytail: one worker, max 16 sessions; shared sessions only if replicas grow.
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()

    def _prune(self):
        now = time.monotonic()
        for key, session in list(self.sessions.items()):
            if now >= session.expires_at and not session.busy:
                self._remove(key, expired=True)

    def _remove(self, key, *, expired=False, interrupted=False):
        session = self.sessions.pop(key)
        if session.expiry is not None:
            session.expiry.cancel()
        callslog.history_safe(
            call_history.end,
            session.tools.call_id,
            "expired" if expired else "interrupted" if interrupted else "completed",
            expired=expired,
        )

    def _expire(self, key):
        with self.lock:
            session = self.sessions.get(key)
            if session is None:
                return
            if session.busy:
                # Never discard an in-flight write's ownership/recovery context.
                session.expiry = asyncio.get_running_loop().call_later(
                    5, self._expire, key
                )
            else:
                self._remove(key, expired=True)

    def create(
        self, dispatcher, owner, *, language: str = "et", voice_id: str = "azure"
    ):
        with self.lock:
            self._prune()
            if len(self.sessions) >= MAX_SESSIONS:
                raise HTTPException(
                    503, "demo_sessions_full", headers={"Retry-After": "30"}
                )
            key = uuid.uuid4().hex
            try:
                session = DemoSession(
                    owner,
                    CallTools(
                        dispatcher, language="et" if language == "auto" else language
                    ),
                    time.monotonic() + SESSION_TTL,
                    voice_id=voice_id,
                )
            except Exception:
                raise HTTPException(503, "demo_profile_unavailable") from None
            self.sessions[key] = session
            callslog.history_safe(
                call_history.start,
                session.tools.call_id,
                "browser",
                session.tools.language,
            )
            session.expiry = asyncio.get_running_loop().call_later(
                SESSION_TTL, self._expire, key
            )
            return {
                "session_id": key,
                "call_id": session.tools.call_id,
                "greeting": session.tools.greeting,
                "language": session.tools.language,
                "synthetic": True,
                "transport": "http_not_telephone",
                "expires_in_s": SESSION_TTL,
                "max_turns": MAX_TURNS,
            }

    def _owned(self, key, owner):
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key):
            raise HTTPException(404, "demo_session_unknown")
        session = self.sessions.get(key)
        if session is None:
            raise HTTPException(410, "demo_session_expired_or_unknown")
        if session.owner != owner:
            raise HTTPException(403, "forbidden")
        return session

    def acquire(self, key, owner):
        with self.lock:
            session = self._owned(key, owner)
            if session.busy:
                raise HTTPException(409, "demo_session_busy")
            if time.monotonic() >= session.expires_at:
                self._remove(key, expired=True)
                raise HTTPException(410, "demo_session_expired")
            if session.turn_count >= MAX_TURNS:
                callslog.history_safe(
                    call_history.end, session.tools.call_id, "expired", expired=True
                )
                raise HTTPException(410, "demo_session_expired")
            session.busy = True
            session.turn_count += 1
            return session

    def release(self, session):
        with self.lock:
            session.busy = False
            self._prune()

    def end(self, key, owner):
        with self.lock:
            session = self._owned(key, owner)
            if session.busy:
                raise HTTPException(409, "demo_session_busy")
            self._remove(key)
        return {"ok": True}

    def clear(self):
        with self.lock:
            for key in list(self.sessions):
                self._remove(key, interrupted=True)


async def read_session_settings(request: Request) -> tuple[str, str]:
    """Optional bounded session settings; routes authenticate before parsing."""
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 1024:
            raise HTTPException(413, "demo_session_arguments_too_large")
        body.extend(chunk)
    if not body:
        return "auto", "azure"  # Preserve clients that send no JSON body.
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "demo_session_arguments_invalid") from None
    if not isinstance(data, dict) or set(data) - {"language", "voice"}:
        raise HTTPException(400, "demo_session_arguments_invalid")
    language = data.get("language", "auto")
    if not isinstance(language, str) or language not in ("auto", *LANGUAGES):
        raise HTTPException(400, "demo_session_language_invalid")
    return language, validate_voice(data.get("voice", "azure"))


async def read_session_language(request: Request) -> str:
    language, _ = await read_session_settings(request)
    return language


def validate_voice(value):
    if not isinstance(value, str) or value not in VOICE_IDS:
        raise HTTPException(422, "voice_profile_invalid")
    return value


def choose_speaker(stack, voice_id="azure"):
    """Resolve against the current injected Azure client, never a captured one."""
    validate_voice(voice_id)
    registry = stack.get("voices")
    # Legacy injected Azure speakers may expose only synthesize(), not views.
    if (
        voice_id == "azure"
        and stack["tts"] is not None
        and not callable(getattr_static(stack["tts"], "for_language", None))
    ):
        return stack["tts"]
    if registry is None:
        if voice_id == "azure":
            return stack["tts"]
        raise HTTPException(503, "voice_profile_unavailable")
    try:
        return registry.choose(voice_id, azure=stack["tts"])
    except ValueError:
        raise HTTPException(503, "voice_profile_unavailable") from None


def voice_metadata(provider, language, voice_id="azure"):
    info = (
        getattr(provider, "voice_info", None)
        if getattr_static(provider, "voice_info", None) is not None
        else None
    )
    if callable(info):
        info = info()
    if not isinstance(info, dict):
        return {
            "requested": voice_id,
            "effective": voice_id,
            "language": language,
            "fallback": False,
            "reason": None,
            "streaming": getattr(provider, "streaming") is True
            if getattr_static(provider, "streaming", None) is not None
            else callable(getattr_static(provider, "stream", None)),
        }
    # Only closed metadata crosses the private API, never arbitrary config fields.
    reason = info.get("reason")
    return {
        "requested": info.get("requested")
        if info.get("requested") in VOICE_IDS
        else voice_id,
        "effective": info.get("effective")
        if info.get("effective") in VOICE_IDS
        else voice_id,
        "language": language,
        "fallback": info.get("fallback") is True,
        "reason": reason
        if reason in ("unsupported_language", "provider_failure")
        else None,
        "streaming": info.get("streaming") is True,
    }


async def read_turn_body(request):
    # Authenticate in the route BEFORE reading; never let framework validation
    # parse an unbounded body or echo an unauthenticated payload back to callers.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_TURN_BODY_BYTES:
            raise HTTPException(413, "turn_body_too_large")
        body.extend(chunk)
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "turn_arguments_invalid") from None
    if not isinstance(parsed, dict):
        raise HTTPException(400, "turn_arguments_invalid")
    return parsed


def validate_input(body, stack):
    if not isinstance(body, dict) or set(body) - {
        "audio_b64",
        "text",
        "language",
        "session_id",
        "recap_delivery_id",
        "voice",
    }:
        raise HTTPException(400, "turn_arguments_invalid")
    validate_voice(body.get("voice", "azure"))
    language = body.get("language", "auto")
    if not isinstance(language, str) or language not in ("auto", *LANGUAGES):
        raise HTTPException(400, "language_not_supported")
    if "recap_delivery_id" in body:
        receipt = body["recap_delivery_id"]
        if not isinstance(receipt, str) or not re.fullmatch(r"[a-f0-9]{32}", receipt):
            raise HTTPException(400, "recap_delivery_invalid")
        if body.get("session_id") is None:
            raise HTTPException(400, "recap_delivery_requires_session")
    audio_b64, text = body.get("audio_b64", ""), body.get("text", "")
    if not isinstance(audio_b64, str) or len(audio_b64) > 700_000:
        raise HTTPException(413, "audio_b64_too_large")
    if not isinstance(text, str) or len(text) > 500:
        raise HTTPException(413, "text_too_large")
    if bool(audio_b64) == bool(text.strip()):
        raise HTTPException(400, "one_audio_or_text_required")
    audio = b""
    if audio_b64:
        try:
            audio = base64.b64decode(audio_b64, validate=True)
        except (ValueError, TypeError):
            raise HTTPException(400, "audio_b64_invalid") from None
        if len(audio) > 524_288:
            raise HTTPException(413, "audio_too_large")
        if not audio:
            raise HTTPException(400, "audio_required")
        if stack["stt"] is None:
            raise HTTPException(503, "stt_not_configured")
    if stack["llm_primary"] is None or stack["tts"] is None:
        raise HTTPException(503, "voice_stack_not_configured")
    return audio, text, language


def result_outcome(result):
    results = [
        r.get("result") for r in result.get("tool_results", []) if isinstance(r, dict)
    ]
    errors = [
        r.get("error")
        for r in results
        if isinstance(r, dict) and (r.get("error") or r.get("ok") is False)
    ]
    if result.get("mutation_uncertain") or any(
        code
        in {
            "write_outcome_unknown",
            "cancel_outcome_unknown",
            "mutation_outcome_unknown",
        }
        for code in errors
        if isinstance(code, str)
    ):
        return "unknown_outcome"
    if errors:
        return "tools_failed"
    if result.get("tts_failed"):
        return "tts_failed"
    if result.get("fallback_used"):
        return "fallback"
    return "tools_ok" if results else "ok"


def table_receipt_metadata(booking):
    """Project an authoritative table receipt into contact-free local history."""
    booking_id = booking["id"]
    day = date.fromisoformat(booking["date"])
    start = datetime.fromisoformat(booking["start"])
    if not re.fullmatch(r"table_[a-f0-9]{32}", booking_id) or start.tzinfo is None:
        raise ValueError("table receipt metadata invalid")
    local = start.astimezone(ZoneInfo("Europe/Tallinn"))
    if local.date() != day:
        raise ValueError("table receipt date invalid")
    return {
        "id": booking_id,
        "kind": "table",
        "date": day.isoformat(),
        "start_local": local.replace(tzinfo=None).isoformat(sep=" "),
        "timezone": "Europe/Tallinn",
    }


class _TurnTools:
    def __init__(self, session):
        self.session = session
        self.results, self.changes = [], []
        self.mutation_attempted = False
        self.latency_ms = 0.0

    def available_tools(self):
        return self.session.tools.conversation_tools()

    async def dispatch(self, name, arguments):
        is_mutation = name in {
            "confirm_slot_booking",
            "cancel_slot_booking",
            "confirm_booking",
            "cancel_booking",
            "confirm_table_booking",
            "cancel_table_booking",
        }
        if is_mutation and self.mutation_attempted:
            result = {"error": "mutation_retry_forbidden"}
        else:
            if is_mutation:
                self.mutation_attempted = True
            started = time.perf_counter()
            try:
                result = await self.session.tools.dispatch(name, arguments)
            except Exception:
                result = {"error": "booking_unavailable"}
            finally:
                self.latency_ms += (time.perf_counter() - started) * 1000
        if not isinstance(result, dict):
            result = {"error": "booking_unavailable"}
        if is_mutation and result.get("error") == "booking_unavailable":
            # Native tools close exceptions without commit detail. Treat a
            # failed mutation conservatively as unknown, never safe-to-retry.
            result = {"error": "mutation_outcome_unknown"}
        self.results.append(result)
        if is_mutation and result.get("ok") is True and not result.get("error"):
            try:
                args = (
                    json.loads(arguments) if isinstance(arguments, str) else arguments
                )
                if name == "confirm_slot_booking":
                    booking_id = str(result["booking"]["id"])
                    slot = self.session.tools.held_slots[args["hold_id"]]
                    day = date.fromisoformat(slot["date"])
                    start = datetime.fromisoformat(slot["start"])
                    if (
                        not booking_id.isdigit()
                        or int(booking_id) <= 0
                        or start.date() != day
                    ):
                        raise ValueError()
                    self.session.booking_details[booking_id] = {
                        "id": booking_id,
                        "date": day.isoformat(),
                        "start_local": slot["start"],
                        "timezone": "Europe/Tallinn",
                    }
                    self.changes.append(
                        {
                            "action": "confirmed",
                            **self.session.booking_details[booking_id],
                        }
                    )
                elif name == "confirm_booking":
                    booking = result["booking"]
                    booking_id = str(booking["id"])
                    self.session.booking_details[booking_id] = {
                        "id": booking_id,
                        "kind": "stay",
                        "date": date.fromisoformat(booking["checkin"]).isoformat(),
                        "checkin": booking["checkin"],
                        "checkout": booking["checkout"],
                        "timezone": "Europe/Tallinn",
                    }
                    self.changes.append(
                        {
                            "action": "confirmed",
                            **self.session.booking_details[booking_id],
                        }
                    )
                elif name == "confirm_table_booking":
                    booking = result["booking"]
                    booking_id = str(booking["id"])
                    self.session.booking_details[booking_id] = table_receipt_metadata(
                        booking
                    )
                    self.changes.append(
                        {
                            "action": "confirmed",
                            **self.session.booking_details[booking_id],
                        }
                    )
                elif str(args["booking_id"]) in self.session.booking_details:
                    self.changes.append(
                        {
                            "action": "cancelled",
                            **self.session.booking_details[str(args["booking_id"])],
                        }
                    )
            except (KeyError, TypeError, ValueError, AttributeError):
                # No metadata is preferable to guessing a day from assistant prose.
                pass
        return result


class _TrustedLlm:
    def __init__(self, client, session):
        self.client, self.session = client, session
        self.latency_ms = 0.0
        self.failed = False
        self.failure = {}

    def chat(self, messages, tools=None):
        state = self.session.tools
        # These replies/actions are already decided by trusted call state. A
        # second provider request cannot improve the canonical recap/receipt,
        # and can exhaust the shared provider limit after a successful tool.
        response = trusted_booking_response(
            state, after_tool=bool(messages and messages[-1].get("role") == "tool")
        )
        if response is not None:
            if "content" in response:
                return response
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_" + uuid.uuid4().hex,
                        "type": "function",
                        "function": {
                            "name": response["name"],
                            "arguments": json.dumps(response["arguments"]),
                        },
                    }
                ],
            }
        # Standalone greetings/FAQs use approved text, not model paraphrases
        # that the shared speech guard would reject. Mixed requests use tools.
        if messages and messages[-1].get("role") == "user":
            direct = state.direct_reply
            if direct is not None:
                return {"content": direct}
            question = messages[-1].get("content")
            if isinstance(question, str):
                question = " ".join(question.strip().rstrip("?!.").casefold().split())
                if state.language == "en" and question in {
                    "hello",
                    "hi",
                    "hello there",
                }:
                    return {"content": "Hello! How can I help you?"}
                if state.language == "et" and question == "tere":
                    return {"content": "Tere! Kuidas saan aidata?"}
                if state.language == "ru" and question in {
                    "привет",
                    "здравствуйте",
                    "добрый день",
                    "доброе утро",
                    "добрый вечер",
                }:
                    return {"content": "Здравствуйте! Чем могу помочь?"}
                suffix = state.language
                for entry in state.demo["faq"]:
                    approved_question = entry.get("question_" + suffix)
                    approved_answer = entry.get("answer_" + suffix)
                    if not approved_question or not approved_answer:
                        continue
                    approved = " ".join(
                        approved_question.strip().rstrip("?!.").casefold().split()
                    )
                    if question == approved:
                        return {"content": approved_answer}
        context = {
            "pending": state.pending,
            "booking_ids": sorted(state.bookings)[-16:],
            "last_booking": state.last_booking,
            **state.inventory_context,
        }
        instructions = (
            state.conversation_instructions
            + "\nServer-owned state: "
            + json.dumps(context, ensure_ascii=False)
        )
        started = time.perf_counter()
        try:
            return self.client.chat(
                [{"role": "system", "content": instructions}] + messages, tools=tools
            )
        except Exception as error:
            self.failed = True
            if isinstance(error, ProviderError):
                reason = getattr(error, "reason", None)
                if reason in PROVIDER_FAILURE_REASONS:
                    self.failure["cause"] = reason
                code = getattr(error, "status_code", None)
                if type(code) is int and 100 <= code <= 599:
                    self.failure["http_status"] = code
            raise
        finally:
            self.latency_ms += (time.perf_counter() - started) * 1000


class _SafeSpeaker:
    def __init__(self, provider, turn_tools, emit=None):
        self.provider, self.tools, self.reply = provider, turn_tools, None
        self.recap_pending = None
        self.invalid_audio = False
        self.latency_ms = 0.0
        self.emit = emit

    def normalize(self, text):
        self.recap_pending = None
        outcome = result_outcome(
            {"tool_results": [{"result": r} for r in self.tools.results]}
        )
        if outcome == "unknown_outcome":
            return self.tools.session.tools.guard_reply(text, self.tools.results)
        elif outcome == "tools_failed":
            self.tools.session.tools.pending = None
            text = (
                "Toiming ei õnnestunud; edu ei ole kinnitatud. "
                "Palun kontrolli testbroneeringu ettevalmistust "
                "või proovi hiljem uuesti."
            )
        else:
            # Speak the actual preparation recap, not an optional model paraphrase.
            recap = next(
                (
                    r
                    for r in reversed(self.tools.results)
                    if r.get("ok") is True and isinstance(r.get("recap"), dict)
                ),
                None,
            )
            if recap and self.tools.session.tools.pending:
                canonical = self.tools.session.tools.render_recap()
                if canonical:
                    self.recap_pending = self.tools.session.tools.pending
                    text = canonical
        normalized = self.tools.session.tools.guard_reply(text, self.tools.results)
        if normalized != text and self.tools.session.tools.pending:
            self.tools.session.tools.pending = None
        pending = self.tools.session.tools.pending
        if pending and normalized == self.tools.session.tools.render_recap():
            # Repeats and language switches need a fresh receipt too; they do
            # not execute another preparation tool or acknowledge delivery.
            self.recap_pending = pending
        return normalized

    def synthesize(self, text):
        self.reply = self.normalize(text)
        if self.emit is not None:
            self.emit(
                {
                    "type": "reply",
                    "reply": self.reply,
                    "language": self.tools.session.tools.language,
                    "audio_type": "audio/mpeg",
                }
            )
        started = time.perf_counter()
        try:
            audio = self.provider.synthesize(self.reply)
            self.invalid_audio = not isinstance(audio, bytes)
            return audio
        finally:
            self.latency_ms += (time.perf_counter() - started) * 1000


async def run_demo_turn(
    session,
    stack,
    audio,
    text,
    language,
    *,
    recap_delivery_id=None,
    tts_override=None,
    emit=None,
):
    from .turn import MAX_HISTORY_TURNS, recognize_audio, run_turn

    started = time.perf_counter()
    # Receipt validation precedes paid recognition and observation of this input.
    session.consume_recap_delivery(recap_delivery_id)
    stt_started = started
    recognition_status = "typed"
    if audio:
        text, recognition_status = await recognize_audio(stack["stt"], audio, language)
    stt_failed = recognition_status == "stt_unavailable"
    stt_ms = (time.perf_counter() - stt_started) * 1000 if audio else 0.0
    if not isinstance(text, str) or len(text) > 500:
        session.tools.observe_user_text("", is_final=True)
        raise HTTPException(413, "transcript_too_large")
    # The server observes the final transcript before any LLM-generated tool call.
    session.tools.observe_user_text(
        text,
        is_final=True,
        language=None if language == "auto" else language,
    )
    language = session.tools.language
    callslog.history_safe(
        call_history.record_input, session.tools.call_id, recognition_status, language
    )
    tools = _TurnTools(session)
    provider = tts_override if tts_override is not None else stack["tts"]
    if callable(getattr_static(provider, "for_language", None)):
        provider = provider.for_language(session.tools.language)
    speaker = _SafeSpeaker(provider, tools, emit)
    primary = _TrustedLlm(stack["llm_primary"], session)
    secondary = (
        _TrustedLlm(stack["llm_secondary"], session)
        if stack["llm_secondary"] is not None
        else None
    )
    result = await run_turn(
        b"",
        None,
        primary,
        speaker,
        tools,
        llm_secondary=secondary,
        text=text,
        language=language,
        history=session.history,
        recognition_status=recognition_status,
    )
    result["reply"] = (
        speaker.reply
        if speaker.reply is not None
        else speaker.normalize(result["reply"])
    )
    result["tts_failed"] = not bool(result["audio"])
    result["fallback_used"] = result.get("fallback_used", False)
    # run_turn's last-resort catch may discard its local tool list after a
    # failed model follow-up. Native execution truth still owns the outcome.
    result["tool_results"] = [{"result": value} for value in tools.results]
    result["mutation_uncertain"] = session.tools.mutation_uncertain
    if (
        not result["fallback_used"]
        and not speaker.invalid_audio
        and (not result["tts_failed"] or emit is None)
        and result_outcome(result) not in ("unknown_outcome", "tools_failed")
        and session._recap_is_current(speaker.recap_pending, result["reply"])
    ):
        # Synthesis is not delivery. JSON's canonical text remains deliberately
        # readable if audio failed; incomplete NDJSON never grants a receipt.
        session.recap_delivery = {
            "id": uuid.uuid4().hex,
            "pending": speaker.recap_pending,
            "text": result["reply"],
            "language": session.tools.language,
        }
    elif speaker.invalid_audio or result["tts_failed"] or result["fallback_used"]:
        session.tools.pending = None
    callslog.history_safe(
        call_history.record_result,
        session.tools.call_id,
        result_outcome(result),
        tts_failed=result["tts_failed"],
        changes=tools.changes,
    )
    session.history = (
        session.history
        + [
            {"role": "user", "content": text},
            {"role": "assistant", "content": result["reply"]},
        ]
    )[-MAX_HISTORY_TURNS:]
    warnings = []
    if stt_failed:
        warnings.append({"stage": "stt", "code": "transcription_unavailable"})
    if primary.failed:
        failure = (
            secondary.failure
            if secondary is not None and secondary.failed
            else primary.failure
        )
        warnings.append(
            {
                "stage": "llm",
                "code": (
                    "reply_provider_unavailable"
                    if secondary is None or secondary.failed
                    else "reply_provider_fallback"
                ),
                **failure,
            }
        )
    if result["tts_failed"]:
        warnings.append({"stage": "tts", "code": "reply_audio_unavailable"})
    timings = {
        "stt": round(stt_ms, 1),
        "llm": round(
            primary.latency_ms + (secondary.latency_ms if secondary else 0), 1
        ),
        "tools": round(tools.latency_ms, 1),
        "tts": round(speaker.latency_ms, 1),
        "total": round((time.perf_counter() - started) * 1000, 1),
    }
    first_audio_ms = (
        getattr(provider, "first_audio_ms", None)
        if getattr_static(provider, "first_audio_ms", None) is not None
        else None
    )
    if type(first_audio_ms) in (int, float) and first_audio_ms >= 0:
        timings["tts_first_audio_ms"] = first_audio_ms
    return {
        "text_heard": result["text_heard"],
        "language": language,
        "reply": result["reply"],
        "audio_b64": base64.b64encode(result["audio"]).decode(),
        "audio_type": "audio/mpeg",
        "voice": voice_metadata(provider, language, session.voice_id),
        "tools_used": len(result["tool_results"]),
        "fallback_used": result["fallback_used"],
        "tts_failed": result["tts_failed"],
        "recap_delivery_id": (
            session.recap_delivery["id"] if session.recap_delivery else None
        ),
        "recap_expires_in_s": (
            max(
                0,
                min(session.expires_at, session.recap_delivery["pending"]["expires_at"])
                - time.monotonic(),
            )
            if session.recap_delivery
            else None
        ),
        "input_status": result.get("input_status", recognition_status),
        "outcome": result_outcome(result),
        "turn_count": session.turn_count,
        "expires_in_s": max(0, int(session.expires_at - time.monotonic())),
        "booking_ids": sorted(session.tools.bookings),
        "booking_changes": tools.changes,
        "warnings": warnings,
        "timings_ms": timings,
    }
