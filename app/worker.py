"""Continuous, process-per-call LiveKit worker; run: python -m app.worker start."""

from __future__ import annotations

import asyncio
import logging
import os
import wave
from pathlib import Path

from livekit import api, rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.plugins import azure, groq, silero

from .booking.easyappointments import EasyAppointmentsAdapter
from .booking.tools import Dispatcher
from .telephone import (
    CallTools,
    FALLBACK,
    GREETING,
    INSTRUCTIONS,
    safe_speech,
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
        super().__init__(instructions=INSTRUCTIONS, tools=sdk_tools(state))
        self.state = state

    async def tts_node(self, text, model_settings):
        # No partial sentence or invented price is spoken before validation.
        parts = []
        async for chunk in text:
            parts.append(chunk)
            if sum(map(len, parts)) > 3000:
                parts = [FALLBACK]
                break
        reply = safe_speech("".join(parts), self.state.results)

        async def checked():
            yield reply

        try:
            async for frame in Agent.default.tts_node(self, checked(), model_settings):
                yield frame
        except Exception:
            async for frame in fallback_audio():
                yield frame


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
    track = rtc.LocalAudioTrack.create_audio_track("service-unavailable", source)
    publication = await room.local_participant.publish_track(track)
    try:
        async for frame in fallback_audio():
            await source.capture_frame(frame)
        await source.wait_for_playout()
    finally:
        await room.local_participant.unpublish_track(publication.sid)
        await source.aclose()


async def cleanup_call(ctx, session, adapter):
    # A disconnected agent is NOT a disconnected SIP caller. Terminate its
    # individual room, even when earlier teardown fails; each wait is bounded.
    cancelled = False
    try:
        for close in (
            session.aclose,
            adapter.close,
            lambda: ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name)),
        ):
            try:
                await asyncio.wait_for(close(), timeout=5)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                pass
    finally:
        ctx.shutdown(reason="telephone session ended")
    if cancelled:
        raise asyncio.CancelledError


async def close_session(session, timeout=5):
    try:
        await asyncio.wait_for(session.aclose(), timeout=timeout)
    except Exception:
        pass


def on_user_state(session, event):
    if event.new_state == "speaking":
        # Stop queued speech on the VAD state edge, not only after batch STT.
        session.interrupt()
        logging.getLogger("voicebot.telephone").info("user_speaking")


server = AgentServer(
    num_idle_processes=2,
    drain_timeout=30,
    session_end_timeout=10,
    shutdown_process_timeout=10,
    setup_fnc=prewarm,
    load_fnc=lambda s: len(s.active_jobs) / 2,
    load_threshold=1,
    host="0.0.0.0",
    port=8081,
)


@server.rtc_session(agent_name=os.environ.get("VOICEBOT_AGENT_NAME", "voicebot"))
async def entrypoint(ctx: JobContext):
    protect_logs()
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
            "interruption": {"mode": "vad", "enabled": True},
            "preemptive_generation": {"enabled": False},
        },
    )
    closed = asyncio.Event()
    failed = asyncio.Event()
    session.on("close", lambda ev: closed.set())
    session.on(
        "user_state_changed",
        lambda ev: on_user_state(session, ev),
    )
    session.on(
        "conversation_item_added",
        lambda ev: (
            logging.getLogger("voicebot.telephone").info("speech_interrupted")
            if getattr(ev.item, "interrupted", False)
            else None
        ),
    )
    session.on("error", lambda ev: failed.set() if not ev.error.recoverable else None)
    session.on(
        "user_input_transcribed",
        lambda ev: state.results.clear() if ev.is_final else None,
    )
    ctx.room.on("participant_disconnected", lambda p: closed.set())
    try:
        await session.start(agent=TelephoneAgent(state), room=ctx.room, record=False)
        await ctx.connect()
        await asyncio.wait_for(ctx.wait_for_participant(), timeout=30)
        session.say(GREETING)
        tasks = [asyncio.create_task(closed.wait()), asyncio.create_task(failed.wait())]
        try:
            done, _ = await asyncio.wait(
                tasks, timeout=600, return_when=asyncio.FIRST_COMPLETED
            )
            if failed.is_set():
                await close_session(session)
                await asyncio.wait_for(play_failure(ctx.room), timeout=10)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await cleanup_call(ctx, session, adapter)


if __name__ == "__main__":
    validate_environment()
    cli.run_app(server)
