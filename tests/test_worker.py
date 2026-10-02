import asyncio
import pytest

pytest.importorskip("livekit.agents")
from unittest.mock import patch

from app.telephone import CallTools
from app.worker import TelephoneAgent, fallback_audio, PrivateLogs
from app.booking.tools import Dispatcher
import logging


@pytest.mark.parametrize(
    "phrase",
    [
        "Hind on 999 eurot.",
        "See maksab sada kakskümmend eurot.",
        "Teenuse maksumus on sada.",
        "See on sada USD.",
    ],
)
def test_speech_is_fully_checked_before_synthesis(phrase):
    async def run():
        seen = []

        async def text():
            yield phrase[:8]
            yield phrase[8:]

        async def fake_default(agent, text, settings):
            async for part in text:
                seen.append(part)
            yield "frame"

        agent = TelephoneAgent(CallTools(Dispatcher()))
        with patch("livekit.agents.Agent.default.tts_node", fake_default):
            assert [frame async for frame in agent.tts_node(text(), None)] == ["frame"]
        assert seen == ["Ma ei saa praegu hinda kinnitada."]

    asyncio.run(run())


def test_cached_fallback_is_real_pcm_and_no_provider_call():
    async def run():
        frames = [frame async for frame in fallback_audio()]
        assert len(frames) > 200
        assert all(
            frame.sample_rate == 24000 and frame.num_channels == 1 for frame in frames
        )
        assert any(any(frame.data) for frame in frames)

    asyncio.run(run())


def test_tts_provider_failure_plays_independent_fallback():
    async def run():
        async def text():
            yield "Tere!"

        async def fail(*args):
            raise RuntimeError("provider failed")
            yield

        agent = TelephoneAgent(CallTools(Dispatcher()))
        with patch("livekit.agents.Agent.default.tts_node", fail):
            frames = [frame async for frame in agent.tts_node(text(), None)]
        assert len(frames) > 200

    asyncio.run(run())


def test_sdk_logs_are_not_transcript_storage():
    def record(name):
        return logging.LogRecord(
            name, logging.ERROR, "", 0, "private guest data", (), None
        )

    assert not PrivateLogs().filter(record("livekit.agents"))
    assert not PrivateLogs().filter(record("httpx"))


def test_two_simultaneous_job_reservations_fit_capacity():
    from app.worker import server

    # SDK initial reservation cost = load_threshold / num_idle_processes.
    assert server._num_idle_processes == 2


def test_cleanup_ends_sip_room_even_if_session_teardown_fails():
    from unittest.mock import AsyncMock, Mock
    from types import SimpleNamespace
    from app.worker import cleanup_call

    session = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("fixture")))
    adapter = SimpleNamespace(close=AsyncMock())
    delete = AsyncMock()
    ctx = SimpleNamespace(
        api=SimpleNamespace(room=SimpleNamespace(delete_room=delete)),
        room=SimpleNamespace(name="synthetic-fixture"),
        shutdown=Mock(),
    )
    asyncio.run(cleanup_call(ctx, session, adapter))
    adapter.close.assert_awaited_once()
    delete.assert_awaited_once()
    ctx.shutdown.assert_called_once()


def test_vad_speaking_interrupts_current_audio_immediately():
    from unittest.mock import Mock
    from types import SimpleNamespace
    from app.worker import on_user_state

    session = Mock()
    on_user_state(session, SimpleNamespace(new_state="listening"))
    session.interrupt.assert_not_called()
    on_user_state(session, SimpleNamespace(new_state="speaking"))
    session.interrupt.assert_called_once_with()


def test_cancelled_close_still_terminates_room_and_adapter():
    from unittest.mock import AsyncMock, Mock
    from types import SimpleNamespace
    from app.worker import cleanup_call

    session = SimpleNamespace(aclose=AsyncMock(side_effect=asyncio.CancelledError))
    adapter = SimpleNamespace(close=AsyncMock())
    delete = AsyncMock()
    ctx = SimpleNamespace(
        api=SimpleNamespace(room=SimpleNamespace(delete_room=delete)),
        room=SimpleNamespace(name="fixture"),
        shutdown=Mock(),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cleanup_call(ctx, session, adapter))
    adapter.close.assert_awaited_once()
    delete.assert_awaited_once()
    ctx.shutdown.assert_called_once()


def test_pre_fallback_close_is_bounded():
    from types import SimpleNamespace
    from app.worker import close_session

    async def run():
        async def stall():
            await asyncio.Event().wait()

        await asyncio.wait_for(
            close_session(SimpleNamespace(aclose=stall), timeout=0.01), 0.1
        )

    asyncio.run(run())
