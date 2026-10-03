"""Continuous, process-per-call LiveKit worker; run: python -m app.worker start."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
import uuid
import wave
from collections import defaultdict, deque
from pathlib import Path

from livekit import api, rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli, llm, stt
from livekit.agents.types import TimedString, USERDATA_TIMED_TRANSCRIPT
from livekit.plugins import groq, silero

from .booking.easyappointments import EasyAppointmentsAdapter
from .booking.demo_stay import DemoStayAdapter
from .booking.tools import Dispatcher
from .booking_response import trusted_booking_response
from . import callslog, call_history
from .providers.voice_config import SpeechConfig, VoiceConfig
from .providers.telephone_stt import TelephoneSTT
from .providers.telephone_tts import TelephoneTTS
from .providers.speech_delivery import SpeechDelivery
from .providers.speech_text import normalize_estonian_speech
from .languages import ENGLISH, ENGLISH_INVITATION, LANGUAGES
from .russian import localize
from .telephone import (
    ASK_DATE_TIME,
    CallTools,
    FALLBACK,
    UNVERIFIED_REPLY,
    sdk_tools,
    validate_environment,
)
from .call_factory import make_call_tools


class PrivateLogs(logging.Filter):
    def filter(self, record):
        # SDK debug/errors may include transcripts, tool args and response bodies.
        # Worker readiness is exposed by SDK HTTP health; retain only our codes.
        return record.name in {"voicebot.telephone", "voicebot.twilio"}


def protect_logs():
    for handler in logging.getLogger().handlers:
        handler.addFilter(PrivateLogs())


class _SpokenText(TimedString):
    """Private per-generation audio decision, never model/provider text."""


class TelephoneAgent(Agent):
    def __init__(self, state, *, speech_config=None, speech_provider=None):
        super().__init__(
            instructions=state.conversation_instructions,
            tools=sdk_tools(state, conversation=True),
            use_tts_aligned_transcript=True,
        )
        self.state = state
        self.speech_config = speech_config or SpeechConfig()
        self.speech_provider = speech_provider
        self._detected_language = None
        self._unsupported_language = False
        self._final_user_turn = None
        self._tool_call_ids = set()
        self._tts_voice_lock = asyncio.Lock()

    async def stt_node(self, audio, model_settings):
        async for event in Agent.default.stt_node(self, audio, model_settings):
            if (
                event.type == stt.SpeechEventType.FINAL_TRANSCRIPT
                and event.alternatives
            ):
                data = event.alternatives[0]
                if data.text.strip():
                    self._detected_language = str(data.language)
                    self._unsupported_language = bool(
                        (data.metadata or {}).get("unsupported_language")
                    )
            yield event

    async def on_user_turn_completed(self, turn_ctx, new_message):
        # SDK aggregates STT fragments here, before generating any tool call.
        # A provider-final fragment is not necessarily the complete user turn.
        self.state.observe_user_text(
            new_message.text_content if new_message.role == "user" else "",
            is_final=True,
            detected_language=self._detected_language,
            language=(
                self.speech_config.mode if self.speech_config.mode != "auto" else None
            ),
            unsupported=self._unsupported_language,
        )
        self._detected_language = None
        self._unsupported_language = False
        message_id = getattr(new_message, "id", None)
        self._final_user_turn = (
            (message_id, self.state._turn_serial)
            if new_message.role == "user" and message_id
            else None
        )
        self._tool_call_ids.clear()
        await self.update_instructions(self.state.conversation_instructions)
        if self.state.history_enabled and new_message.role == "user":
            status = (
                "recognized"
                if (new_message.text_content or "").strip()
                else "no_speech"
            )
            callslog.history_safe(
                call_history.record_input,
                self.state.call_id,
                status,
                self.state.language,
            )

    async def llm_node(self, chat_ctx, tools, model_settings):
        # Only finalized user turns can authorize an action. SDK history may
        # include older tools that finished after a newer turn started.
        turn = self._final_user_turn
        user = next(
            (
                item
                for item in reversed(chat_ctx.items)
                if getattr(item, "role", None) == "user"
            ),
            None,
        )
        current = turn is not None and turn == (
            getattr(user, "id", None),
            self.state._turn_serial,
        )
        # SDK instruction refreshes append configuration metadata after the
        # user's item. That metadata does not change which turn is answered.
        tail = next(
            (
                item
                for item in reversed(chat_ctx.items)
                if not isinstance(item, llm.AgentConfigUpdate)
            ),
            None,
        )
        initial = current and tail is user
        after_tool = (
            current
            and isinstance(tail, llm.FunctionCallOutput)
            and tail.call_id in self._tool_call_ids
        )
        if initial:
            # Reviewed social turns and repeat requests answer only this
            # finalized user turn, never a superseded tool followup.
            reply = self.state.direct_reply
            if reply is not None:
                yield reply
                return
        if initial or after_tool:
            response = trusted_booking_response(
                self.state,
                after_tool=after_tool,
                allow_actions=(
                    initial and getattr(model_settings, "tool_choice", None) != "none"
                ),
            )
            if response and "content" in response:
                yield response["content"]
                return
            if response and response["name"] in {tool.id for tool in tools}:
                call_id = uuid.uuid4().hex
                self._tool_call_ids.add(call_id)
                # The ordinary SDK executor still runs CallTools.dispatch and
                # checks ownership, expiry and delivered later consent.
                yield llm.ChatChunk(
                    id=uuid.uuid4().hex,
                    delta=llm.ChoiceDelta(
                        role="assistant",
                        tool_calls=[
                            llm.FunctionToolCall(
                                name=response["name"],
                                arguments=json.dumps(response["arguments"]),
                                call_id=call_id,
                            )
                        ],
                    ),
                )
                return
        if initial and self.state.booking_inquiry:
            # Current parsed caller preferences must reach the provider even
            # though the SDK's original instructions predate this turn.
            inquiry = llm.ChatMessage(
                role="system",
                content=[
                    "Server-owned booking inquiry (requested date/time only, "
                    "not availability or consent): "
                    + json.dumps(self.state.booking_inquiry, ensure_ascii=False)
                ],
            )
            items = list(chat_ctx.items)
            items.insert(items.index(tail), inquiry)
            chat_ctx = llm.ChatContext(items=items)
        responded = False
        async for chunk in Agent.default.llm_node(
            self, chat_ctx, tools, model_settings
        ):
            if (
                current
                and (initial or after_tool)
                and (
                    turn != self._final_user_turn or turn[1] != self.state._turn_serial
                )
            ):
                # SDK tool execution consumes emitted chunks directly. Withhold
                # late calls as well as IDs after a newer final user turn.
                return
            if (
                current
                and (initial or after_tool)
                and turn == self._final_user_turn
                and turn[1] == self.state._turn_serial
            ):
                if isinstance(chunk, llm.ChatChunk) and chunk.delta:
                    self._tool_call_ids.update(
                        call.call_id for call in chunk.delta.tool_calls
                    )
            if isinstance(chunk, str):
                responded |= bool(chunk.strip())
            elif isinstance(chunk, llm.ChatChunk):
                responded |= chunk.has_response()
            yield chunk
        if (
            current
            and (initial or after_tool)
            and (turn != self._final_user_turn or turn[1] != self.state._turn_serial)
        ):
            return
        if not responded:
            # Successful empty/length exhaustion never enters SDK speech nodes.
            # Seed the existing guard; never retry tools or execute partial JSON.
            yield (
                ENGLISH["ask_date_time"]
                if self.state.language == "en"
                else localize(ASK_DATE_TIME, self.state.language)
            )

    async def checked_reply(self, text):
        # No partial sentence or invented price is spoken before validation.
        parts = []
        spoken = None
        async for chunk in text:
            if isinstance(chunk, _SpokenText):
                spoken = str(chunk)
            if spoken is not None:
                continue
            parts.append(chunk)
            if sum(map(len, parts)) > 3000:
                parts = [self.state.fallback]
                self.state.invalidate_recap()
                break
        if spoken is not None:
            # Timed PCM metadata belongs to this generation. A later booking
            # state or cached apology must not relabel the original speech.
            return spoken
        canonical = (
            self.state.render_recap()
            if self.state.pending and not self.state.pending["delivery"]
            else None
        )
        return self.state.guard_reply(canonical or "".join(parts), self.state.results)

    async def transcription_node(self, text, model_settings):
        # The completed SDK assistant item must describe the actual checked audio.
        yield await self.checked_reply(text)

    def on_conversation_item_added(self, event):
        if getattr(event.item, "role", None) != "assistant":
            return
        if self.state.history_enabled:
            outcome = (
                "fallback"
                if event.item.text_content
                in {
                    UNVERIFIED_REPLY,
                    ENGLISH["unverified"],
                    localize(UNVERIFIED_REPLY, "ru"),
                }
                else self.state.outcome
            )
            callslog.history_safe(
                call_history.record_result, self.state.call_id, outcome
            )
        if getattr(event.item, "interrupted", False):
            logging.getLogger("voicebot.telephone").info("speech_interrupted")
            if self.state.history_enabled:
                callslog.history_safe(
                    call_history.activity, self.state.call_id, "interrupted"
                )

    def _current_speech(self):
        # A background node may belong to a different handle than the session's
        # foreground speech. This narrow accessor is pinned/tested with SDK 1.8.4.
        from livekit.agents.voice.agent_activity import _SpeechHandleContextVar

        if speech := _SpeechHandleContextVar.get(None):
            return speech
        try:
            return self.session.current_speech
        except RuntimeError:
            # A standalone agent has no session before AgentSession.start.
            return None

    async def tts_node(self, text, model_settings):
        complete = False
        pending = None
        speech = self._current_speech()
        language = self.state.language
        try:
            reply = await self.checked_reply(text)
            language = "en" if reply == ENGLISH_INVITATION else self.state.language
            pending = self.state.pending
            canonical = self.state.render_recap()

            async def checked():
                yield normalize_estonian_speech(reply, language)

            frames = voiced = False
            # Azure snapshots options per sentence. Keep every sentence in an
            # interrupted stream on its voice until cancellation completes.
            async with self._tts_voice_lock:
                if isinstance(self.speech_provider, TelephoneTTS):
                    self.speech_provider.set_recap_delivery(
                        bool(pending and reply == canonical)
                    )
                if self.speech_provider is not None:
                    voice, locale = self.speech_config.voice_for(language)
                    self.speech_provider.update_options(voice=voice, language=locale)
                async for frame in Agent.default.tts_node(
                    self, checked(), model_settings
                ):
                    if not frames:
                        frame.userdata[USERDATA_TIMED_TRANSCRIPT] = [_SpokenText(reply)]
                    frames = True
                    voiced = voiced or any(frame.data)
                    yield frame
            if not voiced:
                raise RuntimeError("speech_audio_empty")
            complete = True
            if (
                complete
                and pending
                and self.state.pending is pending
                and reply == canonical
                and speech is not None
            ):
                # SDK 1.8.4 emits the session event before attaching generated
                # items, but after attaching say() items. Use the originating
                # handle's item callback, independent of that event ordering.
                def delivered(item):
                    if getattr(item, "role", None) != "assistant":
                        return
                    speech._remove_item_added_callback(delivered)
                    if self.state.pending is not pending:
                        return
                    if (
                        getattr(item, "interrupted", False)
                        or item.text_content != reply
                    ):
                        self.state.invalidate_recap()
                    else:
                        self.state.mark_recap_delivered(pending["hold_id"])

                speech._add_item_added_callback(delivered)
                speech.add_done_callback(
                    lambda done: done._remove_item_added_callback(delivered)
                )
        except Exception as error:
            if pending is None or self.state.pending is pending:
                self.state.invalidate_recap()
            if self.state.outcome != "write_outcome_unknown":
                self.state.outcome = "provider_error"
            log_failure("tts_fallback", error)
            # No Russian cached PCM exists; actual failure audio/history is ET.
            cached_language = "en" if language == "en" else "et"
            if self.state.history_enabled:
                callslog.history_safe(
                    call_history.provider_error, self.state.call_id, "tts_error"
                )
            first_cached = True
            async for frame in fallback_audio(cached_language):
                if first_cached:
                    frame.userdata[USERDATA_TIMED_TRANSCRIPT] = [
                        _SpokenText(
                            ENGLISH["fallback"] if cached_language == "en" else FALLBACK
                        )
                    ]
                    first_cached = False
                yield frame
        finally:
            if not complete:
                if pending is None or self.state.pending is pending:
                    self.state.invalidate_recap()


def log_failure(stage, error):
    """Closed diagnostic fields only; provider bodies never enter worker logs."""
    if stage not in {
        "configuration",
        "providers",
        "session_start",
        "media_connect",
        "participant_wait",
        "greeting",
        "call_runtime",
        "tts_fallback",
    }:
        stage = "call_runtime"
    status = getattr(error, "status_code", 0)
    if type(status) is not int or not 100 <= status <= 599:
        status = 0
    kind = "timeout" if isinstance(error, TimeoutError) else "error"
    logging.getLogger("voicebot.telephone").warning(
        "call_failure stage=%s kind=%s status=%d", stage, kind, status
    )


class VoiceMetrics:
    """Bounded per-call timing samples; no provider labels or message IDs."""

    FIELDS = {
        "stt_metrics": {"stt": "duration"},
        "llm_metrics": {"llm_first_token": "ttft", "llm": "duration"},
        "tts_metrics": {"tts_first_audio": "ttfb", "tts": "duration"},
        "eou_metrics": {
            "endpointing": "end_of_utterance_delay",
            "transcription": "transcription_delay",
        },
    }

    def __init__(self):
        self.samples = defaultdict(lambda: deque(maxlen=60))

    def observe(self, event):
        metrics = getattr(event, "metrics", None)
        for stage, field in self.FIELDS.get(getattr(metrics, "type", None), {}).items():
            self._add(stage, getattr(metrics, field, None))

    def observe_playback(self, event):
        item = getattr(event, "item", None)
        metrics = getattr(item, "metrics", None)
        if getattr(item, "role", None) == "assistant" and isinstance(metrics, dict):
            self._add("reply_first_audio", metrics.get("e2e_latency"))

    def _add(self, stage, value):
        if type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 600:
            self.samples[stage].append(value)

    def log_summary(self):
        logger = logging.getLogger("voicebot.telephone")
        for stage, values in sorted(self.samples.items()):
            ordered = sorted(values)
            if not ordered:
                continue
            logger.info(
                "voice_metrics stage=%s samples=%d p50_ms=%d p95_ms=%d",
                stage,
                len(ordered),
                round(ordered[(len(ordered) - 1) // 2] * 1000),
                round(ordered[math.ceil(len(ordered) * 0.95) - 1] * 1000),
            )


async def fallback_audio(language="et"):
    # Cached independent PCM, not another request to the failed provider.
    with wave.open(
        str(
            Path(__file__).parent
            / "audio"
            / f"unavailable-{'en' if language == 'en' else 'et'}.wav"
        ),
        "rb",
    ) as wav:
        rate = wav.getframerate()
        while data := wav.readframes(rate // 50):
            yield rtc.AudioFrame(
                data=data,
                sample_rate=rate,
                num_channels=1,
                samples_per_channel=len(data) // 2,
            )


def prewarm(proc):
    protect_logs()
    proc.userdata["vad"] = silero.VAD.load()


async def play_failure(room, language="et"):
    # AgentSession may already have auto-closed on a nonrecoverable error.
    source = rtc.AudioSource(24000, 1, queue_size_ms=100)
    publication = None
    try:
        track = rtc.LocalAudioTrack.create_audio_track("voicebot-fallback", source)
        publication = await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        await asyncio.wait_for(publication.wait_for_subscription(), timeout=5)
        async for frame in fallback_audio(language):
            await source.capture_frame(frame)
        await source.wait_for_playout()
    finally:
        try:
            if publication is not None:
                await asyncio.wait_for(
                    room.local_participant.unpublish_track(publication.sid), timeout=5
                )
        finally:
            await asyncio.wait_for(source.aclose(), timeout=5)


def log_call_summary(state, *, failed=False):
    """One static lifecycle record, never peer, room, arguments or transcript."""
    if getattr(state, "_summary_logged", False):
        return
    state._summary_logged = True
    outcome = getattr(state, "outcome", "completed")
    if failed and outcome != "write_outcome_unknown":
        outcome = "provider_error"
    if outcome not in {
        "completed",
        "provider_error",
        "booking_unavailable",
        "write_outcome_unknown",
        "hold_created",
        "booking_confirmed",
        "booking_cancelled",
    }:
        outcome = "completed"
    language = getattr(state, "language", "et")
    if language not in LANGUAGES:
        language = "et"
    try:
        callslog.log_call(
            callslog.get_default(), language, "", "Synthetic telephone demo", outcome
        )
    except Exception:
        logging.getLogger("voicebot.telephone").warning("call_summary_unavailable")
    if getattr(state, "history_enabled", False):
        callslog.history_safe(
            call_history.record_result,
            state.call_id,
            outcome,
            changes=getattr(state, "booking_receipts", ()),
        )
        callslog.history_safe(call_history.end, state.call_id, outcome)


async def cleanup_call(ctx, session, adapter, *, state=None, failed=False):
    # A disconnected agent is NOT a disconnected SIP caller. Terminate its
    # individual room, even when earlier teardown fails; each wait is bounded.
    cancelled = False
    try:
        for close in (
            session.aclose if session is not None else None,
            adapter.close if adapter is not None else None,
            lambda: ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name)),
        ):
            if close is None:
                continue
            try:
                await asyncio.wait_for(close(), timeout=5)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                pass
    finally:
        if state is not None:
            log_call_summary(state, failed=failed)
        ctx.shutdown(reason="telephone session ended")
    if cancelled:
        raise asyncio.CancelledError


async def close_session(session, timeout=5):
    try:
        await asyncio.wait_for(session.aclose(), timeout=timeout)
    except Exception:
        pass


async def publish_interruption(room, interrupted):
    generation = uuid.uuid4().hex.encode()
    try:
        await asyncio.wait_for(
            room.local_participant.publish_data(
                b"clear:" + generation, topic="voicebot.interruption", reliable=True
            ),
            timeout=5,
        )
        # Clearing carrier playback does not prove old native PCM has stopped.
        # A matching resume is sent only after the SDK's interruption completes.
        if not inspect.isawaitable(interrupted):
            return
        await asyncio.wait_for(asyncio.shield(interrupted), timeout=5)
        await asyncio.wait_for(
            room.local_participant.publish_data(
                b"resume:" + generation, topic="voicebot.interruption", reliable=True
            ),
            timeout=5,
        )
    except (Exception, asyncio.CancelledError) as error:
        # No remote failure body, caller identity or transcript is logged.
        if (
            isinstance(error, asyncio.CancelledError)
            and asyncio.current_task().cancelling()
        ):
            raise
        try:
            await asyncio.wait_for(
                room.local_participant.publish_data(
                    b"failed:" + generation,
                    topic="voicebot.interruption",
                    reliable=True,
                ),
                timeout=5,
            )
        except Exception:
            pass


def on_user_state(session, event, *, state=None, room=None, pending_tasks=None):
    if event.new_state == "speaking":
        if state is not None and getattr(state, "history_enabled", False):
            callslog.history_safe(
                call_history.activity, state.call_id, "speech_started"
            )
        # Stop queued speech on the VAD state edge, not only after batch STT.
        speech = getattr(session, "current_speech", None)
        interrupted = session.interrupt()
        if (
            state is not None
            and state.pending
            and (
                not state.pending["delivery"]
                or (speech is not None and not speech.done())
            )
        ):
            state.invalidate_recap()
        logging.getLogger("voicebot.telephone").info("user_speaking")
        if room is not None:
            task = asyncio.create_task(publish_interruption(room, interrupted))
            if pending_tasks is not None:
                pending_tasks.add(task)
                task.add_done_callback(pending_tasks.discard)
            return task


def on_provider_error(failed, event, *, state=None):
    if state is not None:
        state.invalidate_recap()
        if getattr(state, "history_enabled", False):
            callslog.history_safe(
                call_history.provider_error,
                state.call_id,
                getattr(event.error, "type", "unknown"),
            )
    if event.error.recoverable:
        return
    kind = getattr(event.error, "type", "unknown")
    if kind not in {"llm_error", "stt_error", "tts_error", "realtime_model_error"}:
        kind = "unknown"
    status = getattr(event.error.error, "status_code", 0)
    if type(status) is not int or not 100 <= status <= 599:
        status = 0
    logging.getLogger("voicebot.telephone").warning(
        "provider_failure kind=%s status=%d", kind, status
    )
    failed.set()


server = AgentServer(
    num_idle_processes=2,
    # Cover setup, the bounded ten-minute call and independent resource cleanup.
    drain_timeout=900,
    session_end_timeout=10,
    shutdown_process_timeout=40,
    setup_fnc=prewarm,
    load_fnc=lambda s: len(s.active_jobs) / 2,
    load_threshold=1,
    host="0.0.0.0",
    port=8081,
)


@server.rtc_session(agent_name=os.environ.get("VOICEBOT_AGENT_NAME", "voicebot"))
async def entrypoint(ctx: JobContext):
    protect_logs()
    adapter = state = session = recognizer = None
    failed = asyncio.Event()
    interruption_tasks = set()
    metrics = VoiceMetrics()
    stage = "configuration"
    try:
        validate_environment()
        config = VoiceConfig.from_env()
        speech_config = SpeechConfig.from_env()
        delivery = SpeechDelivery.from_env()
        from .business import business_type, restaurant_database, restaurant_dispatcher

        if business_type() == "restaurant":
            from .booking.restaurant import RestaurantAdapter
            from .restaurant_data import load_restaurant_data

            restaurant_data = load_restaurant_data()
            adapter = RestaurantAdapter(
                restaurant_database(), data=restaurant_data, allow_writes=True
            )
            state = make_call_tools(
                restaurant_dispatcher(adapter, restaurant_data),
                language=speech_config.initial_language,
            )
        else:
            state = None
        if state is None:
            adapter = EasyAppointmentsAdapter(
                os.environ["EASY_BASE_URL"],
                os.environ["EASY_API_KEY"],
                auth_scheme=os.environ.get("EASY_AUTH_SCHEME", "Bearer "),
                api_prefix=os.environ.get("EASY_API_PREFIX", "/index.php/api/v1"),
                state_db=os.environ["EASY_STATE_DB"],
                allow_writes=True,
            )
            stay = None
            if (
                os.environ.get("STAY_DEMO_WRITES", os.environ.get("EASY_DEMO_WRITES"))
                == "1"
            ):
                stay = DemoStayAdapter(
                    os.environ.get("STAY_STATE_DB")
                    or os.path.join(
                        os.path.dirname(os.environ["EASY_STATE_DB"]), "stay-booking.db"
                    )
                )
            state = CallTools(
                Dispatcher(slot=adapter, stay=stay),
                language=speech_config.initial_language,
            )
        callslog.history_safe(
            call_history.start, state.call_id, "telephone", state.language
        )
        state.history_enabled = True
        stage = "providers"
        chat_options = config.chat_options()
        # The Groq plugin does not expose include_reasoning. It forwards only
        # delta.content/tool calls; reasoning never reaches its speech output.
        chat_options.pop("include_reasoning", None)
        voice, language = speech_config.voice_for(state.language)
        recognizer = TelephoneSTT(
            model=config.stt_model,
            mode=speech_config.mode,
            api_key=os.environ["GROQ_API_KEY"],
        )
        speech_provider = TelephoneTTS(
            voice=voice,
            language=language,
            delivery=delivery,
            speech_key=os.environ["AZURE_SPEECH_KEY"],
            speech_region=os.environ["AZURE_REGION"],
        )
        session = AgentSession(
            stt=recognizer,
            llm=groq.LLM(
                model=config.chat_model,
                api_key=os.environ["GROQ_API_KEY"],
                parallel_tool_calls=False,
                **chat_options,
            ),
            tts=speech_provider,
            vad=ctx.proc.userdata["vad"],
            turn_handling={
                "turn_detection": "vad",
                "endpointing": {"mode": "fixed", "min_delay": 1.2, "max_delay": 3.0},
                "interruption": {"mode": "vad", "enabled": True},
                "preemptive_generation": {"enabled": False},
            },
        )
        closed = asyncio.Event()
        agent = TelephoneAgent(
            state, speech_config=speech_config, speech_provider=speech_provider
        )
        session.on("close", lambda ev: closed.set())
        session.on(
            "user_state_changed",
            lambda ev: on_user_state(
                session,
                ev,
                state=state,
                room=ctx.room,
                pending_tasks=interruption_tasks,
            ),
        )
        session.on("conversation_item_added", agent.on_conversation_item_added)
        session.on("conversation_item_added", metrics.observe_playback)
        session.on("metrics_collected", metrics.observe)
        session.on("error", lambda ev: on_provider_error(failed, ev, state=state))
        ctx.room.on("participant_disconnected", lambda p: closed.set())
        stage = "session_start"
        await asyncio.wait_for(
            session.start(agent=agent, room=ctx.room, record=False), timeout=20
        )
        stage = "media_connect"
        await asyncio.wait_for(ctx.connect(), timeout=10)
        await asyncio.wait_for(
            ctx.room.local_participant.set_attributes(
                {"voicebot.call_id": state.call_id}
            ),
            timeout=5,
        )
        stage = "participant_wait"
        await asyncio.wait_for(ctx.wait_for_participant(), timeout=20)
        stage = "greeting"
        greeting = session.say(state.greeting)
        if inspect.isawaitable(greeting):
            await asyncio.wait_for(greeting, timeout=20)
        if speech_config.mode == "auto" and state.language == "et":
            invitation = session.say(ENGLISH_INVITATION)
            if inspect.isawaitable(invitation):
                await asyncio.wait_for(invitation, timeout=20)
        stage = "call_runtime"
        callslog.history_safe(call_history.activity, state.call_id, "greeting")
        tasks = [asyncio.create_task(closed.wait()), asyncio.create_task(failed.wait())]
        try:
            done, _ = await asyncio.wait(
                tasks, timeout=600, return_when=asyncio.FIRST_COMPLETED
            )
            if failed.is_set():
                await close_session(session)
                await asyncio.wait_for(
                    play_failure(ctx.room, state.language), timeout=20
                )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as error:
        log_failure(stage, error)
        failed.set()
        if session is not None:
            await close_session(session)
        try:
            await asyncio.wait_for(
                play_failure(ctx.room, state.language if state else "et"), timeout=20
            )
        except Exception:
            pass
    finally:
        for task in interruption_tasks:
            task.cancel()
        await asyncio.gather(*interruption_tasks, return_exceptions=True)
        metrics.log_summary()
        try:
            await cleanup_call(
                ctx, session, adapter, state=state, failed=failed.is_set()
            )
        finally:
            if recognizer is not None:
                await recognizer.aclose()


if __name__ == "__main__":
    validate_environment()
    cli.run_app(server)
