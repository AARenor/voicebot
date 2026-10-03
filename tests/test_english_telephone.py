"""English outcomes and failure handling across the actual shared call policy."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.languages import (
    CONSENT,
    ENGLISH,
    ENGLISH_INVITATION,
    english_clarification,
    requested_language,
    select_language,
    spoken_date,
    spoken_time,
)
from app.providers.azure_tts import AzureTtsClient
from app.providers.voice_config import SpeechConfig
from app.telephone import CallTools, safe_speech
from tests.test_telephone import Slots, prepared
from tests.test_product_demo import (
    BookingLlm,
    SimpleLlm,
    client as demo_client,
    install_backend,
    send,
    start,
)

client = demo_client


@pytest.mark.parametrize(
    "text,expected",
    [
        ("English, please.", "en"),
        ("Can you speak English?", "en"),
        ("Please use English", "en"),
        ("Palun inglise keeles.", "en"),
        ("Can we speak in Estonian?", "et"),
        ("Estonian please", "et"),
        ("Palun eesti keeles", "et"),
        ("Do you serve English breakfast?", None),
    ],
)
def test_language_requests_are_explicit(text, expected):
    assert requested_language(text) == expected


@pytest.mark.parametrize("text", ["yes", "no", "okay", "10:30", "2", "jah"])
def test_short_weak_language_evidence_keeps_current_voice(text):
    assert select_language(text, "english", "et") == "et"
    assert select_language(text, "estonian", "en") == "en"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Book a spa appointment on 10/11/2026 at 2 PM", "ambiguous_date"),
        ("Reserve a room from 05.06 to 07.06", "ambiguous_date"),
        ("Book a massage tomorrow at ten", "ambiguous_time"),
        ("Book a spa appointment tomorrow at 2", "ambiguous_time"),
        ("Book a spa appointment tomorrow at 2 PM", None),
        ("Book a massage tomorrow at ten in the morning", None),
        ("Book a spa appointment tomorrow at 14:00", None),
        ("Book a room from 2026-11-02 to 2026-11-04", None),
        ("Do you have room 2?", None),
    ],
)
def test_english_ambiguity_is_detected_without_guessing(text, expected):
    assert english_clarification(text) == expected


def test_ambiguous_request_cannot_reach_booking_backend():
    async def run():
        state = CallTools(Slots(), language="en")
        state.observe_user_text("Book a massage tomorrow at ten")
        assert (
            await state.dispatch(
                "plan_demo_booking", {"date": "2026-11-02", "start_time": "10:00"}
            )
        )["error"] == "clarification_required"
        assert not state.dispatcher.calls
        assert (
            state.guard_reply("Your booking is confirmed.", [])
            == ENGLISH["ambiguous_time"]
        )
        state.observe_user_text("Ten in the morning, please.")
        assert state.clarification is None

    asyncio.run(run())


def test_english_spa_recap_confirmation_cancellation_and_replay():
    async def run():
        state = CallTools(Slots(), language="en")
        ready = await prepared(state)
        recap = state.render_recap()
        assert "Live consultation" in recap and "Live therapist" in recap
        assert "Monday, 2 November 2026 at 10:30 AM" in recap
        assert "Tallinn local time" in recap and "Demo Esimene" in recap
        assert CONSENT["en"] in recap and CONSENT["en"] in ready["consent_prompt_en"]
        state.observe_user_text(CONSENT["en"])
        booked = await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        assert booked["ok"] is True
        assert (
            state.guard_reply("I booked another room too", []) == ENGLISH["confirmed"]
        )
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
            == booked
        )
        state.observe_user_text("Please cancel my booking.")
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["ok"] is True
        assert state.guard_reply("Another room was booked", []) == ENGLISH["cancelled"]
        await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        assert (
            sum(name == "confirm_slot_booking" for name, _ in state.dispatcher.calls)
            == 1
        )
        assert (
            sum(name == "cancel_slot_booking" for name, _ in state.dispatcher.calls)
            == 1
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "Yes",
        "Yes?",
        "Yes, I confirm?",
        "Yes, I confirm. No, don't book it.",
        "Please cancel it instead",
        "Yes, I confirm the other caller's booking",
    ],
)
def test_uncertain_english_answers_never_confirm(text):
    async def run():
        state = CallTools(Slots(), language="en")
        await prepared(state)
        state.observe_user_text(text)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "consent_required"
        assert not any(
            name == "confirm_slot_booking" for name, _ in state.dispatcher.calls
        )

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["undelivered", "expired", "foreign", "interim"])
def test_english_consent_obeys_delivery_expiry_and_ownership(boundary):
    async def run():
        state = CallTools(Slots(), language="en")
        await prepared(state)
        if boundary == "undelivered":
            state.pending["delivery"] = False
        if boundary == "expired":
            state.pending["expires_at"] = 0
        state.observe_user_text(CONSENT["en"], is_final=boundary != "interim")
        assert "error" in await state.dispatch(
            "confirm_slot_booking",
            {"hold_id": "foreign" if boundary == "foreign" else "owned-hold"},
        )
        assert not any(
            name == "confirm_slot_booking" for name, _ in state.dispatcher.calls
        )

    asyncio.run(run())


def test_switching_language_requires_the_new_recap_to_finish():
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        state.observe_user_text("English, please.", detected_language="english")
        assert state.language == "en"
        assert state.pending is not None and state.pending["delivery"] is False
        recap = state.guard_reply("Hello!", [])
        assert "Fictional test booking" in recap
        assert "Yes, I confirm." in recap
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "consent_required"
        assert state.mark_recap_delivered("owned-hold")
        state.observe_user_text(CONSENT["en"])
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["ok"]

    asyncio.run(run())


def test_english_commitment_cannot_approve_an_estonian_recap():
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        state.observe_user_text(CONSENT["en"], detected_language="en")
        assert state.language == "en"
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


def test_english_room_lifecycle_uses_durable_inventory_and_exact_quote(tmp_path):
    async def run():
        adapter = DemoStayAdapter(str(tmp_path / "rooms.db"))
        state = CallTools(Dispatcher(stay=adapter), language="en")
        day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=15)
        search = {
            "checkin": day.isoformat(),
            "checkout": (day + timedelta(days=2)).isoformat(),
            "adults": 2,
        }
        offers = await state.dispatch("search_availability", search)
        quote = offers["offers"][0]
        held = await state.dispatch(
            "hold_offer", {"price_quote_id": quote["price_quote_id"]}
        )
        ready = await state.dispatch("prepare_demo_stay", {"hold_id": held["hold_id"]})
        recap = state.guard_reply("Hello!", [])
        assert (
            f"{quote['quoted_total']} EUR" in recap
            and "No payment is collected" in recap
        )
        assert "2 nights, 2 adults and 0 children" in recap
        assert state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["en"])
        confirmed = await state.dispatch(
            "confirm_booking", {"hold_id": held["hold_id"]}
        )
        assert (
            confirmed["ok"]
            and state.guard_reply("wrong status", []) == ENGLISH["confirmed"]
        )
        assert len((await adapter.get_operator_bookings())["items"]) == 1
        state.observe_user_text("Please cancel this test booking.")
        assert (
            await state.dispatch(
                "cancel_booking", {"booking_id": str(confirmed["booking"]["id"])}
            )
        )["ok"]
        assert state.guard_reply("wrong status", []) == ENGLISH["cancelled"]
        assert (await adapter.get_operator_bookings())["items"][0][
            "status"
        ] == "cancelled"

    asyncio.run(run())


@pytest.mark.parametrize(
    "claim",
    [
        "Your test booking is confirmed.",
        "Your test booking is cancelled.",
        "I transferred you to reception.",
        "The hotel is definitely available.",
    ],
)
def test_fluent_english_cannot_invent_execution_truth(claim):
    state = CallTools(Slots(), language="en")
    assert state.guard_reply(claim, []) == ENGLISH["unverified"]


@pytest.mark.parametrize("error", ["confirmed", "cancelled", "existing"])
def test_backend_error_cannot_select_a_success_phrase(error):
    state = CallTools(Slots(), language="en")
    assert state.guard_reply("Hello!", [{"error": error}]) == ENGLISH["failed"]


def test_saved_estonian_guest_name_keeps_english_conversation_language():
    state = CallTools(Slots(), language="en")
    state.observe_user_text("Demo Teine", detected_language="et", unsupported=True)
    assert state.language == "en" and not state.unsupported_language


@pytest.mark.parametrize(
    "claim",
    [
        "The price is 999 EUR.",
        "It costs one hundred euros.",
        "The cost is one hundred.",
    ],
)
def test_english_price_guard_precedes_speech(claim):
    assert safe_speech(claim, [], "en") == ENGLISH["price_unknown"]


def test_english_faq_is_approved_and_estonian_answers_are_preserved():
    state = CallTools(Slots(), language="en")
    for entry in state.demo["faq"]:
        assert state.guard_reply(entry["answer_en"], []) == entry["answer_en"]
        assert entry["answer_et"]
    prompt = state.conversation_instructions
    assert "current_date" in prompt and "Europe/Tallinn" in prompt
    assert "guest-001" in prompt and "Yes, I confirm." in prompt
    assert "example.invalid" not in prompt and "+120255501" not in prompt


def test_english_readbacks_use_backend_hours_and_availability():
    state = CallTools(Slots(), language="en")
    catalogue = {
        "services": [{"name": "Live consultation", "duration": 45}],
        "providers": [
            {
                "name": "Actual therapist",
                "working_hours": {
                    "monday": {
                        "start": "09:00",
                        "end": "17:00",
                        "breaks": [{"start": "12:00", "end": "13:00"}],
                    },
                    "sunday": None,
                },
            }
        ],
    }
    reply = state.guard_reply("invented text", [catalogue])
    assert "45 minutes" in reply and "9:00 AM to 5:00 PM" in reply
    assert "break 12:00 PM to 1:00 PM" in reply and "Sunday: closed" in reply
    slots = {"slots": [{"start": "2026-11-02 14:30"}]}
    assert "Monday, 2 November 2026: 2:30 PM" in state.guard_reply("invented", [slots])
    assert "No demo spa appointments" in state.guard_reply("invented", [{"slots": []}])
    assert "No demo rooms" in state.guard_reply("invented", [{"offers": []}])


def test_english_unknown_write_is_locked_and_never_retried():
    async def run():
        state = CallTools(Slots(), language="en")
        await prepared(state)
        original = state.dispatcher.dispatch
        writes = []

        async def fail(name, args):
            if name == "confirm_slot_booking":
                writes.append(args)
                return {"error": "write_outcome_unknown"}
            return await original(name, args)

        state.dispatcher.dispatch = fail
        state.observe_user_text(CONSENT["en"])
        await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        assert state.guard_reply("Booked!", []) == ENGLISH["unknown"]
        state.observe_user_text(CONSENT["en"])
        await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        assert len(writes) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "env",
    [
        {"VOICEBOT_TELEPHONE_LANGUAGE": "de"},
        {"AZURE_EN_VOICE": "et-EE-AnuNeural"},
        {"AZURE_EN_LANG": "en-GB"},
        {"AZURE_LANG": "en-US"},
        {"AZURE_EN_VOICE": "bad' voice"},
    ],
)
def test_invalid_language_voice_pairs_fail_before_requests(env):
    with pytest.raises(ValueError, match="invalid telephone speech"):
        SpeechConfig.from_env(env)


def test_english_mode_and_british_voice_are_configurable():
    speech = SpeechConfig.from_env(
        {
            "VOICEBOT_TELEPHONE_LANGUAGE": "en",
            "AZURE_EN_LANG": "en-GB",
            "AZURE_EN_VOICE": "en-GB-SoniaNeural",
        }
    )
    assert speech.initial_language == "en"
    assert speech.voice_for("en") == ("en-GB-SoniaNeural", "en-GB")
    assert speech.voice_for("et") == ("et-EE-AnuNeural", "et-EE")
    assert spoken_date("2026-11-02") == "Monday, 2 November 2026"
    assert spoken_time("00:30") == "12:30 AM"


def test_http_speech_views_do_not_mix_concurrent_call_voices():
    bodies = []

    def respond(request):
        if request.url.path.endswith("issueToken"):
            return httpx.Response(200, text="fixture-token")
        bodies.append(request.content.decode())
        return httpx.Response(200, content=request.content)

    tts = AzureTtsClient(
        "fixture",
        "fixture",
        "et-EE-AnuNeural",
        "et-EE",
        transport=httpx.MockTransport(respond),
        languages={
            "en": ("en-US-JennyNeural", "en-US"),
            "et": ("et-EE-AnuNeural", "et-EE"),
        },
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            english = pool.submit(tts.for_language("en").synthesize, "Hello!")
            estonian = pool.submit(tts.for_language("et").synthesize, "Tere!")
            assert b"en-US-JennyNeural" in english.result()
            assert b"et-EE-AnuNeural" in estonian.result()
        assert len(bodies) == 2
    finally:
        tts.close()


def test_authenticated_http_english_booking_uses_same_policy(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    session = start(client)
    recap = send(client, session, "I would like a test booking", language="en").json()
    assert (
        "Fictional test booking" in recap["reply"]
        and "Yes, I confirm." in recap["reply"]
    )
    result = send(client, session, CONSENT["en"], language="en").json()
    assert result["reply"] == ENGLISH["confirmed"] and result["booking_ids"] == ["42"]
    cancelled = send(
        client, session, "Please cancel this test booking.", language="en"
    ).json()
    assert cancelled["reply"] == ENGLISH["cancelled"] and not records
    assert (
        sum(r.method == "POST" and r.url.path.endswith("appointments") for r in writes)
        == 1
    )


def test_authenticated_http_english_faq_and_failure_speech(client):
    answer = CallTools(Slots(), language="en").demo["faq"][0]["answer_en"]
    client.app.state.stack["llm_primary"] = SimpleLlm(answer)
    response = send(client, start(client), "Is this a real spa?", language="en").json()
    assert response["reply"] == answer
    client.app.state.stack["llm_primary"] = SimpleLlm(error=RuntimeError("PRIVATE"))
    response = send(
        client, start(client), "Please find a spa appointment", language="en"
    ).json()
    assert "unavailable" in response["reply"] and "PRIVATE" not in str(response)


@pytest.mark.parametrize("question_index", [None, 0, 1, 2, 3])
def test_http_english_greetings_and_faq_need_no_model_request(client, question_index):
    model = NS(chat=NS())
    model.chat = lambda *args, **kwargs: pytest.fail("Approved reply called the model")
    client.app.state.stack["llm_primary"] = model
    if question_index is None:
        question, answer = "Hello!", "Hello! How can I help you?"
    else:
        entry = CallTools(Slots(), language="en").demo["faq"][question_index]
        question, answer = entry["question_en"], entry["answer_en"]
    result = send(client, start(client), question, language="en").json()
    assert result["reply"] == answer and result["warnings"] == []
    assert result["timings_ms"]["llm"] == 0


def test_trusted_unknown_outcome_reply_is_english():
    from app.booking_response import trusted_booking_response

    state = CallTools(Slots(), language="en")
    state._unknown_mutation()
    assert trusted_booking_response(state) == {"content": ENGLISH["unknown"]}


def test_native_language_event_updates_instructions_and_tts_voice():
    pytest.importorskip("livekit.agents")
    from livekit.agents import stt
    from app.worker import TelephoneAgent
    from livekit import rtc

    async def run():
        provider = NS(update_options=AsyncMock())
        # Azure update_options is synchronous in the pinned SDK.
        updates = []
        provider.update_options = lambda **opts: updates.append(opts)
        state = CallTools(Slots())
        agent = TelephoneAgent(state, speech_provider=provider)

        async def events(*args):
            yield stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[stt.SpeechData(text="Hello there", language="en")],
            )

        async def text():
            yield "Hello!"

        frame = rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        async def synthesize(*args):
            yield frame

        with patch("livekit.agents.Agent.default.stt_node", events):
            assert len([ev async for ev in agent.stt_node(None, None)]) == 1
        await agent.on_user_turn_completed(
            None, NS(role="user", text_content="Hello there")
        )
        assert state.language == "en" and "English-speaking" in agent.instructions
        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            assert [f async for f in agent.tts_node(text(), None)] == [frame]
        assert updates[-1] == {"voice": "en-US-JennyNeural", "language": "en-US"}

    asyncio.run(run())


def test_native_english_fallback_audio_and_history_agree():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent, fallback_audio
    from livekit.agents.types import USERDATA_TIMED_TRANSCRIPT

    async def run():
        async def text():
            yield "Hello!"

        async def fail(*args):
            raise RuntimeError("PRIVATE")
            yield

        state = CallTools(Slots(), language="en")
        agent = TelephoneAgent(state)
        with patch("livekit.agents.Agent.default.tts_node", fail):
            frames = [frame async for frame in agent.tts_node(text(), None)]
        assert len(frames) > 100 and all(f.sample_rate == 24000 for f in frames)
        assert any(any(f.data) for f in frames)
        item = NS(
            role="assistant",
            text_content="Hello!",
            content=["Hello!"],
            interrupted=False,
        )

        async def actual_speech():
            for frame in frames:
                for part in frame.userdata.get(USERDATA_TIMED_TRANSCRIPT, []):
                    yield part

        assert [
            part async for part in agent.transcription_node(actual_speech(), None)
        ] == [ENGLISH["fallback"]]
        # An unrelated old assistant event cannot relabel the actual generation.
        agent.on_conversation_item_added(NS(item=item))
        assert item.content == ["Hello!"]
        assert [f.samples_per_channel async for f in fallback_audio("en")] == [
            f.samples_per_channel for f in frames
        ]

    asyncio.run(run())


def test_native_bilingual_invitation_uses_english_voice_without_changing_booking_language():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent
    from livekit import rtc

    async def run():
        updates = []
        state = CallTools(Slots())
        agent = TelephoneAgent(
            state,
            speech_provider=NS(update_options=lambda **opts: updates.append(opts)),
        )

        async def text():
            yield ENGLISH_INVITATION

        frame = rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        async def synthesize(*args):
            yield frame

        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            assert [f async for f in agent.tts_node(text(), None)] == [frame]
        assert updates[-1]["voice"] == "en-US-JennyNeural" and state.language == "et"

    asyncio.run(run())
