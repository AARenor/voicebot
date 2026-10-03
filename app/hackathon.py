"""Bounded, memory-only fictional HTTP sessions; native CallTools owns writes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi import HTTPException

from .telephone import GREETING, CallTools
from .booking_response import trusted_booking_response
from .providers.azure_tts import AzureTtsClient
from . import call_history, callslog
from .providers.errors import PROVIDER_FAILURE_REASONS, ProviderError

SESSION_TTL = 600
MAX_SESSIONS = 16
MAX_TURNS = 24
MAX_TURN_BODY_BYTES = 750_000  # accommodates the bounded base64 audio envelope


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

    def create(self, dispatcher, owner):
        with self.lock:
            self._prune()
            if len(self.sessions) >= MAX_SESSIONS:
                raise HTTPException(
                    503, "demo_sessions_full", headers={"Retry-After": "30"}
                )
            key = uuid.uuid4().hex
            try:
                session = DemoSession(
                    owner, CallTools(dispatcher), time.monotonic() + SESSION_TTL
                )
            except Exception:
                raise HTTPException(503, "demo_profile_unavailable") from None
            self.sessions[key] = session
            callslog.history_safe(call_history.start, session.tools.call_id, "browser")
            session.expiry = asyncio.get_running_loop().call_later(
                SESSION_TTL, self._expire, key
            )
            return {
                "session_id": key,
                "call_id": session.tools.call_id,
                "greeting": GREETING,
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
    }:
        raise HTTPException(400, "turn_arguments_invalid")
    audio_b64, text = body.get("audio_b64", ""), body.get("text", "")
    receipt = body.get("recap_delivery_id")
    if receipt is not None and (
        not isinstance(receipt, str) or not re.fullmatch(r"[a-f0-9]{32}", receipt)
    ):
        raise HTTPException(400, "recap_delivery_invalid")
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
    language = body.get("language", "auto")
    return audio, text, language if language in ("auto", "et", "en", "ru") else "auto"


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
            return {"content": None, "tool_calls": [{
                "id": "call_" + uuid.uuid4().hex, "type": "function",
                "function": {"name": response["name"], "arguments": json.dumps(response["arguments"])},
            }]}
        # Standalone greetings/FAQs use approved text, not model paraphrases
        # that the shared speech guard would reject. Mixed requests use tools.
        if messages and messages[-1].get("role") == "user":
            direct = state.direct_reply
            if direct is not None:
                return {"content": direct}
            question = messages[-1].get("content")
            if isinstance(question, str):
                question = " ".join(question.strip().rstrip("?!.").casefold().split())
                if state.language == "en" and question in {"hello", "hi", "hello there"}:
                    return {"content": "Hello! How can I help you?"}
                if state.language == "et" and question == "tere":
                    return {"content": "Tere! Kuidas saan aidata?"}
                if state.language == "ru" and question in {
                    "привет", "здравствуйте", "добрый день", "доброе утро", "добрый вечер",
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
    def __init__(self, provider, turn_tools):
        self.provider, self.tools, self.reply = provider, turn_tools, None
        self.recap_id = None
        self.latency_ms = 0.0

    def normalize(self, text):
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
                    self.recap_id = self.tools.session.tools.pending["hold_id"]
                    text = canonical
        normalized = self.tools.session.tools.guard_reply(text, self.tools.results)
        if normalized != text and self.tools.session.tools.pending:
            self.tools.session.tools.pending = None
        return normalized

    def synthesize(self, text):
        self.reply = self.normalize(text)
        started = time.perf_counter()
        try:
            return self.provider.synthesize(self.reply)
        finally:
            self.latency_ms += (time.perf_counter() - started) * 1000


async def run_demo_turn(
    session, stack, audio, text, language, *, recap_delivery_id=None
):
    from .turn import MAX_HISTORY_TURNS, recognize_audio, run_turn

    started = time.perf_counter()
    stt_started = started
    recognition_status = "typed"
    if audio:
        text, recognition_status = await recognize_audio(stack["stt"], audio, language)
    stt_failed = recognition_status == "stt_unavailable"
    stt_ms = (time.perf_counter() - stt_started) * 1000 if audio else 0.0
    if not isinstance(text, str) or len(text) > 500:
        session.tools.observe_user_text("", is_final=True)
        raise HTTPException(413, "transcript_too_large")
    # A trusted operator-client asserts playback or explicit reading, not TTS.
    # One-use and bound to this exact preparation, not merely a reusable hold.
    receipt, session.recap_delivery = session.recap_delivery, None
    if (
        receipt
        and receipt["id"] == recap_delivery_id
        and receipt["pending"] is session.tools.pending
    ):
        session.tools.mark_recap_delivered(receipt["pending"]["hold_id"])
    # The server observes the final transcript before any LLM-generated tool call.
    session.tools.observe_user_text(
        text, is_final=True, language=None if language == "auto" else language,
    )
    language = session.tools.language
    callslog.history_safe(
        call_history.record_input, session.tools.call_id, recognition_status, language
    )
    tools = _TurnTools(session)
    provider = stack["tts"]
    if isinstance(provider, AzureTtsClient):
        provider = provider.for_language(session.tools.language)
    speaker = _SafeSpeaker(provider, tools)
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
    if result["tts_failed"] or result["fallback_used"]:
        session.tools.pending = None
    elif speaker.recap_id and result_outcome(result) not in (
        "unknown_outcome",
        "tools_failed",
    ):
        pending = session.tools.pending
        if pending and pending["hold_id"] == speaker.recap_id:
            session.recap_delivery = {"id": uuid.uuid4().hex, "pending": pending}
    # run_turn's last-resort catch may discard its local tool list after a
    # failed model follow-up. Native execution truth still owns the outcome.
    result["tool_results"] = [{"result": value} for value in tools.results]
    result["mutation_uncertain"] = session.tools.mutation_uncertain
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
    return {
        "text_heard": result["text_heard"],
        "language": language,
        "reply": result["reply"],
        "audio_b64": base64.b64encode(result["audio"]).decode(),
        "audio_type": "audio/mpeg",
        "tools_used": len(result["tool_results"]),
        "fallback_used": result["fallback_used"],
        "tts_failed": result["tts_failed"],
        "input_status": result.get("input_status", recognition_status),
        "outcome": result_outcome(result),
        "turn_count": session.turn_count,
        "expires_in_s": max(0, int(session.expires_at - time.monotonic())),
        "booking_ids": sorted(session.tools.bookings),
        "booking_changes": tools.changes,
        "warnings": warnings,
        "timings_ms": timings,
        "recap_delivery_id": session.recap_delivery["id"]
        if session.recap_delivery
        else None,
    }
