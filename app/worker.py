"""Continuous, process-per-call LiveKit worker; run: python -m app.worker start."""

from __future__ import annotations

import asyncio
import logging
import inspect
import os
import uuid
import wave
from pathlib import Path

from livekit import api, rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.plugins import azure, groq, silero

from .booking.easyappointments import EasyAppointmentsAdapter
from .booking.tools import Dispatcher
from . import callslog
from .telephone import (
    CallTools,
    FALLBACK,
    GREETING,
    sdk_tools,
    validate_environment,
)


class PrivateLogs(logging.Filter):
    def filter(self, record):
        # SDK debug/errors may include transcripts, tool args and response bodies.
        # Worker readiness is exposed by SDK HTTP health; retain only our codes.
        return record.name == "voicebot.telephone"


def protect_logs():
    for handler in logging.getLogger().handlers:
        handler.addFilter(PrivateLogs())


class TelephoneAgent(Agent):
    def __init__(self, state):
        super().__init__(
            instructions=state.conversation_instructions,
            tools=sdk_tools(state, conversation=True),
        )
        self.state = state
        self._generated_recap = None

    async def on_user_turn_completed(self, turn_ctx, new_message):
        # SDK aggregates STT fragments here, before generating any tool call.
        # A provider-final fragment is not necessarily the complete user turn.
        self.state.observe_user_text(
            new_message.text_content if new_message.role == "user" else "",
            is_final=True,
        )

    async def checked_reply(self, text):
        # No partial sentence or invented price is spoken before validation.
        parts = []
        async for chunk in text:
            parts.append(chunk)
            if sum(map(len, parts)) > 3000:
                parts = [FALLBACK]
                self.state.invalidate_recap()
                break
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
        generated, self._generated_recap = self._generated_recap, None
        if getattr(event.item, "interrupted", False):
            self.state.invalidate_recap()
            logging.getLogger("voicebot.telephone").info("speech_interrupted")
        elif generated and self.state.pending is generated[0]:
            if getattr(event.item, "text_content", None) == generated[1]:
                self.state.mark_recap_delivered(generated[0]["hold_id"])
            else:
                self.state.invalidate_recap()

    async def tts_node(self, text, model_settings):
        self._generated_recap = None
        complete = False
        try:
            reply = await self.checked_reply(text)
            pending = self.state.pending
            canonical = self.state.render_recap()

            async def checked():
                yield reply

            frames = False
            async for frame in Agent.default.tts_node(self, checked(), model_settings):
                frames = True
                yield frame
            complete = frames
            if (
                complete
                and pending
                and self.state.pending is pending
                and reply == canonical
            ):
                self._generated_recap = (pending, reply)
        except Exception:
            self.state.invalidate_recap()
            if self.state.outcome != "write_outcome_unknown":
                self.state.outcome = "provider_error"
            async for frame in fallback_audio():
                yield frame
        finally:
            if not complete:
                self._generated_recap = None
                self.state.invalidate_recap()


async def fallback_audio():
    # Cached independent PCM, not another request to the failed provider.
    with wave.open(
        str(Path(__file__).parent / "audio" / "unavailable-et.wav"), "rb"
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


async def play_failure(room):
    # AgentSession may already have auto-closed on a nonrecoverable error.
    source = rtc.AudioSource(24000, 1, queue_size_ms=100)
    publication = None
    try:
        track = rtc.LocalAudioTrack.create_audio_track("voicebot-fallback", source)
        publication = await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        await asyncio.wait_for(publication.wait_for_subscription(), timeout=5)
        async for frame in fallback_audio():
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
    try:
        callslog.log_call(
            callslog.get_default(), "et", "", "Synthetic telephone demo", outcome
        )
    except Exception:
        logging.getLogger("voicebot.telephone").warning("call_summary_unavailable")


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
    drain_timeout=30,
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
    adapter = state = session = None
    failed = asyncio.Event()
    interruption_tasks = set()
    try:
        validate_environment()
        adapter = EasyAppointmentsAdapter(
            os.environ["EASY_BASE_URL"],
            os.environ["EASY_API_KEY"],
            auth_scheme=os.environ.get("EASY_AUTH_SCHEME", "Bearer "),
            api_prefix=os.environ.get("EASY_API_PREFIX", "/index.php/api/v1"),
            state_db=os.environ["EASY_STATE_DB"],
            allow_writes=True,
        )
        state = CallTools(Dispatcher(slot=adapter))
        session = AgentSession(
            stt=groq.STT(language="et", api_key=os.environ["GROQ_API_KEY"]),
            llm=groq.LLM(
                model="openai/gpt-oss-20b",
                api_key=os.environ["GROQ_API_KEY"],
                parallel_tool_calls=False,
                max_completion_tokens=512,
            ),
            tts=azure.TTS(
                voice="et-EE-AnuNeural",
                language="et-EE",
                speech_key=os.environ["AZURE_SPEECH_KEY"],
                speech_region=os.environ["AZURE_REGION"],
            ),
            vad=ctx.proc.userdata["vad"],
            turn_handling={
                "turn_detection": "vad",
                "endpointing": {"mode": "fixed", "min_delay": 1.2, "max_delay": 3.0},
                "interruption": {"mode": "vad", "enabled": True},
                "preemptive_generation": {"enabled": False},
            },
        )
        closed = asyncio.Event()
        agent = TelephoneAgent(state)
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
        session.on("error", lambda ev: on_provider_error(failed, ev, state=state))
        ctx.room.on("participant_disconnected", lambda p: closed.set())
        await session.start(agent=agent, room=ctx.room, record=False)
        await ctx.connect()
        await ctx.room.local_participant.set_attributes(
            {"voicebot.call_id": state.call_id}
        )
        await asyncio.wait_for(ctx.wait_for_participant(), timeout=30)
        session.say(GREETING)
        tasks = [asyncio.create_task(closed.wait()), asyncio.create_task(failed.wait())]
        try:
            done, _ = await asyncio.wait(
                tasks, timeout=600, return_when=asyncio.FIRST_COMPLETED
            )
            if failed.is_set():
                await close_session(session)
                await asyncio.wait_for(play_failure(ctx.room), timeout=20)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        failed.set()
        if session is not None:
            await close_session(session)
        try:
            await asyncio.wait_for(play_failure(ctx.room), timeout=20)
        except Exception:
            pass
    finally:
        for task in interruption_tasks:
            task.cancel()
        await asyncio.gather(*interruption_tasks, return_exceptions=True)
        await cleanup_call(ctx, session, adapter, state=state, failed=failed.is_set())


if __name__ == "__main__":
    validate_environment()
    cli.run_app(server)
