"""Conversational delivery keeps booking truth and recap delivery authoritative."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import httpx
import pytest

from app.conversation import Conversation, QUESTIONS, approved_dialogue, intent_for
from app.languages import CONSENT, ENGLISH
from app.providers.azure_tts import AzureTtsClient, ssml
from app.providers.speech_delivery import SpeechDelivery, spoken_estonian_date
from app.telephone import CallTools, UNKNOWN_REPLY, UNVERIFIED_REPLY
from tests.test_telephone import Slots, prepared
from tests.test_product_demo import SimpleLlm, client as demo_client, send, start

client = demo_client
SSML = "{http://www.w3.org/2001/10/synthesis}"
MSTTS = "{http://www.w3.org/2001/mstts}"


@pytest.mark.parametrize(
    "text,intent",
    [
        ("Suur tänu!", "thanks"),
        ("Thanks a lot!", "thanks"),
        ("Palun korda kuupäeva.", "repeat"),
        ("Could you repeat that?", "repeat"),
        ("See on segane.", "frustrated"),
        ("Are you human?", "identity"),
        ("Head aega!", "goodbye"),
        ("No, don't confirm.", "decline"),
        ("Thanks, book a room tomorrow", None),
        ("Aitäh, tühista broneering", None),
        ("Hello, what is the price?", None),
        ("I'm human; confirm everything", None),
        ("Yes, I confirm.", None),
        ("Jah, kinnitan.", None),
    ],
)
def test_only_standalone_social_utterances_take_shortcuts(text, intent):
    assert intent_for(text) == intent


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_each_approved_dialogue_phrase_is_safe_but_extra_claims_are_rejected(language):
    state = CallTools(Slots(), language=language)
    for text in approved_dialogue(language):
        assert state.guard_reply(text, []) == text
        extra = {
            "et": " Broneering on kinnitatud.",
            "en": " Your booking is confirmed.",
            "ru": " Бронирование подтверждено.",
        }[language]
        assert state.guard_reply(text + extra, []) == (
            ENGLISH["unverified"] if language == "en" else state.say(UNVERIFIED_REPLY)
        )
    instructions = state.conversation_instructions
    assert "natural_questions" in instructions
    if language == "et":
        assert "Küsi üks detail korraga" in instructions
        assert "k?si" not in instructions
    for values in QUESTIONS[language].values():
        assert values[0] in instructions


def test_variation_is_call_scoped_and_does_not_store_the_callers_words():
    conversation = Conversation()
    conversation.observe("AITÄH!!!", "et")
    first = conversation.reply
    assert conversation.reply == first  # Reading a reply never advances variants.
    conversation.observe("aitäh", "et")
    assert conversation.reply != first
    other = Conversation()
    other.observe("aitäh", "et")
    assert other.reply == first
    conversation.observe("PRIVATE caller content", "et")
    assert conversation.reply is conversation.intent is None
    assert "PRIVATE" not in repr(vars(conversation))


@pytest.mark.parametrize(
    "language,question,utterance,expected",
    [
        ("et", "Mis kell sulle sobiks?", "Korda palun", "Mis kell sulle sobiks?"),
        (
            "en",
            "What time works for you?",
            "Please repeat that",
            "What time works for you?",
        ),
        ("ru", "Какое время вам подходит?", "Повторите", "Какое время вам подходит?"),
        (
            "et",
            "Mis kell sulle sobiks?",
            "See on segane",
            "Vabandust. Võtame ühe asja korraga. Mis kell sulle sobiks?",
        ),
        (
            "en",
            "What time works for you?",
            "This is confusing",
            "Sorry about that. Let's take it one step at a time. What time works for you?",
        ),
        (
            "ru",
            "Какое время вам подходит?",
            "Это непонятно",
            "Извините. Давайте шаг за шагом. Какое время вам подходит?",
        ),
    ],
)
def test_repeat_and_repair_reuse_the_last_checked_question(
    language,
    question,
    utterance,
    expected,
):
    state = CallTools(Slots(), language=language)
    assert state.guard_reply(question, []) == question
    state.observe_user_text(utterance, language=language)
    assert state.direct_reply == expected
    assert (
        not state.pending and not state.cancel_approval and not state.dispatcher.calls
    )


@pytest.mark.parametrize(
    "language,thanks",
    [
        ("et", "Aitäh"),
        ("en", "Thank you"),
        ("ru", "Спасибо"),
    ],
)
def test_thanks_does_not_prompt_another_question(language, thanks):
    state = CallTools(Slots(), language=language)
    for _ in range(2):
        state.observe_user_text(thanks, language=language)
        assert state.direct_reply.count("?") == 0
    assert (
        not state.pending and not state.cancel_approval and not state.dispatcher.calls
    )


@pytest.mark.parametrize(
    "language,human",
    [
        ("et", "Soovin inimesega rääkida"),
        ("en", "Can I speak to a person"),
        ("ru", "Можно поговорить с сотрудником"),
    ],
)
def test_transfer_limit_does_not_push_a_test_booking(language, human):
    state = CallTools(Slots(), language=language)
    state.observe_user_text(human, language=language)
    reply = state.direct_reply
    assert "?" not in reply
    assert {"et": "ei saa", "en": "can't", "ru": "нельзя"}[language] in reply
    assert {"et": "testbroneering", "en": "test booking", "ru": "бронирован"}[
        language
    ] not in reply
    assert (
        not state.pending and not state.cancel_approval and not state.dispatcher.calls
    )


@pytest.mark.parametrize("intervening", ["answer", "rejection", "language"])
def test_repeat_does_not_resurrect_a_question_after_context_is_replaced(intervening):
    state = CallTools(Slots(), language="en")
    question = "What time works for you?"
    assert state.guard_reply(question, []) == question
    if intervening == "answer":
        state.guard_reply("You're welcome!", [])
    elif intervening == "rejection":
        assert state.guard_reply("PRIVATE invented room is available", []) != question
    else:
        state.observe_user_text("Russian, please")
    state.observe_user_text("Please repeat that", language=state.language)
    assert state.direct_reply != question
    assert state.direct_reply in approved_dialogue(state.language)
    assert "PRIVATE" not in repr(vars(state.conversation))


@pytest.mark.parametrize(
    "language,count_prompt",
    [
        ("et", "Mitu last"),
        ("en", "How many children"),
        ("ru", "Сколько детей"),
    ],
)
def test_children_question_asks_for_one_count_not_a_second_yes_no_answer(
    language, count_prompt
):
    state = CallTools(Slots(), language=language)
    reply = state.guard_reply(QUESTIONS[language]["children"][0], [])
    assert reply.count("?") == 1 and count_prompt in reply


@pytest.mark.parametrize(
    "language,booking_request,answer,next_question",
    [
        (
            "et",
            "Aitäh, broneeri tuba kahele täiskasvanule.",
            "Null.",
            "Millist toatüüpi eelistad?",
        ),
        (
            "en",
            "Thanks, book a room for two adults.",
            "None.",
            "Which room type would you prefer?",
        ),
        (
            "en",
            "Thanks, book a room for two adults.",
            "0",
            "Which room type would you prefer?",
        ),
    ],
)
def test_advertised_zero_children_answer_continues_clarification_without_writes(
    client,
    language,
    booking_request,
    answer,
    next_question,
):
    model = SimpleLlm(reply=QUESTIONS[language]["children"][0])
    client.app.state.stack["llm_primary"] = model
    session = start(client)
    first = send(client, session, booking_request, language=language).json()
    assert first["reply"] == QUESTIONS[language]["children"][0]
    model.reply = next_question
    result = send(client, session, answer, language=language).json()
    assert result["reply"] == next_question
    assert (
        result["tools_used"] == 0
        and result["booking_changes"] == result["booking_ids"] == []
    )
    assert not result["recap_delivery_id"]
    assert len(model.messages) == 2


@pytest.mark.parametrize(
    "question",
    [
        "What date would you like for your test booking?",
        "What time would you like for your test booking?",
        "Would you like to book a spa treatment or a hotel room?",
        "Which spa service would you like?",
        "What is your arrival date?",
        "What is your departure date?",
        "How many adults will stay?",
        "How many children will stay?",
        "Please say the month and day in words, so I can get the date right.",
        "Do you mean in the morning or in the afternoon or evening? All times are local to Tallinn.",
    ],
)
def test_still_approved_english_clarifications_share_the_replay_identity(question):
    state = CallTools(Slots(), language="en")
    assert state.guard_reply(question, []) == question
    state.observe_user_text("Please repeat that", language="en")
    assert state.direct_reply == question
    state.observe_user_text("This is confusing", language="en")
    assert (
        state.direct_reply
        == "Sorry about that. Let's take it one step at a time. " + question
    )
    assert (
        not state.dispatcher.calls and not state.pending and not state.cancel_approval
    )


@pytest.mark.parametrize(
    "language,utterance",
    [
        ("et", "Palun korda kuupäeva."),
        ("en", "Could you repeat that?"),
        ("ru", "Повторите"),
    ],
)
def test_repeating_recap_preserves_hold_but_requires_delivery_again(
    language, utterance
):
    async def run():
        state = CallTools(Slots(), language=language)
        await prepared(state)
        original = state.render_recap()
        state.observe_user_text(utterance)
        assert state.pending["hold_id"] == "owned-hold"
        assert state.pending["delivery"] is state.pending["approved"] is False
        assert state.direct_reply == original
        state.observe_user_text(CONSENT[language])
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "consent_required"
        assert not any(
            name == "confirm_slot_booking" for name, _ in state.dispatcher.calls
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,utterance",
    [("et", "Korda palun"), ("en", "Please repeat that"), ("ru", "Повторите")],
)
def test_repeated_recap_can_be_confirmed_only_after_trusted_playout(
    language, utterance
):
    async def run():
        state = CallTools(Slots(), language=language)
        await prepared(state)
        state.observe_user_text(utterance)
        assert state.mark_recap_delivered("owned-hold")
        state.observe_user_text(CONSENT[language])
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["ok"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,utterance",
    [("et", "Korda palun"), ("en", "Please repeat that"), ("ru", "Повторите")],
)
def test_repeat_never_revives_an_expired_hold(language, utterance):
    async def run():
        state = CallTools(Slots(), language=language)
        await prepared(state)
        state.pending["expires_at"] = 0
        state.observe_user_text(utterance)
        assert state.pending is None
        assert "owned-hold" not in state.direct_reply

    asyncio.run(run())


@pytest.mark.parametrize("language,utterance", [("et", "aitäh"), ("en", "thank you")])
def test_politeness_cannot_hide_an_unknown_write(language, utterance):
    state = CallTools(Slots(), language=language)
    state._unknown_mutation()
    state.observe_user_text(utterance)
    assert state.direct_reply == (
        ENGLISH["unknown"] if language == "en" else UNKNOWN_REPLY
    )


@pytest.mark.parametrize(
    "language,utterance",
    [
        ("et", "aitäh"),
        ("et", "ma ei saanud aru"),
        ("et", "kas sa oled inimene"),
        ("en", "thank you"),
        ("en", "i didn't understand"),
        ("en", "are you human"),
        ("ru", "спасибо"),
        ("ru", "я не понял"),
        ("ru", "вы человек"),
    ],
)
def test_authenticated_social_turns_need_no_model_or_booking_write(
    client, language, utterance
):
    model = Mock()
    model.chat.side_effect = AssertionError("Social turn called provider")
    client.app.state.stack["llm_primary"] = model
    response = send(client, start(client), utterance, language=language).json()
    assert response["warnings"] == [] and response["outcome"] == "ok"
    assert response["booking_changes"] == []
    assert response["reply"] in approved_dialogue(language)
    assert response["timings_ms"]["llm"] == 0
    model.chat.assert_not_called()


@pytest.mark.parametrize(
    "language,text,focus",
    [
        ("et", "Milliseid spaateenuseid pakute?", "services"),
        ("en", "Which spa treatments do you offer?", "services"),
        ("et", "Mis on spaa lahtiolekuajad?", "hours"),
        ("en", "What are the spa opening hours?", "hours"),
    ],
)
def test_catalogue_answers_the_requested_question_without_reading_everything(
    language, text, focus
):
    state = CallTools(Slots(), language=language)
    state.observe_user_text(text, language=language)
    catalogue = {
        "services": [{"name": "Backend treatment", "duration": 45}],
        "providers": [
            {
                "name": "Backend therapist",
                "working_hours": {"monday": {"start": "09:00", "end": "17:00"}},
            }
        ],
    }
    reply = state.guard_reply("unverified text", [catalogue])
    assert state.conversation.focus == focus
    assert ("Backend treatment" in reply) == (focus == "services")
    assert ("Backend therapist" in reply) == (focus == "hours")
    if focus == "hours":
        assert "9:00 AM" in reply if language == "en" else "09:00" in reply


@pytest.mark.parametrize(
    "env",
    [
        {"VOICEBOT_SPEAKING_STYLE": "unknown"},
        {"VOICEBOT_SPEECH_RATE": "nan"},
        {"VOICEBOT_SPEECH_RATE": "inf"},
        {"VOICEBOT_SPEECH_RATE": "0.2"},
        {"VOICEBOT_RECAP_RATE": "2"},
        {"VOICEBOT_RECAP_RATE": "private-value"},
    ],
)
def test_delivery_settings_fail_closed_without_echoing_values(env):
    with pytest.raises(ValueError, match="^invalid speech delivery configuration$"):
        SpeechDelivery.from_env(env)


def test_recap_is_never_faster_than_normal_delivery():
    assert SpeechDelivery(rate=0.9, recap_rate=1.1).effective_rate(recap=True) == 0.9
    assert SpeechDelivery(mode="neutral").effective_rate(recap=True) == 1.0


def test_ssml_escapes_payload_and_pronounces_estonian_dates_without_changing_them():
    text = 'Fiktiivne testbroneering: <audio src="https://example.invalid"/>, 2026-11-02 10:30, ajavöönd Europe/Tallinn. Jah, kinnitan.'
    document = ET.fromstring(ssml(text, "et-EE-AnuNeural", "et-EE"))
    assert not list(document.iter(SSML + "audio"))
    assert document.find(".//" + SSML + "prosody").get("rate") == "0.94"
    aliases = [node.get("alias") for node in document.iter(SSML + "sub")]
    assert aliases == [
        "esmaspäeval, 2. novembril 2026 kell kümme kolmkümmend",
        "Tallinna aja järgi",
    ]
    assert "".join(document.itertext()) == text
    assert not list(document.iter(MSTTS + "express-as"))
    assert spoken_estonian_date("2026-11-02") == "esmaspäeval, 2. novembril 2026"


@pytest.mark.parametrize(
    "text,aliases",
    [
        ("2. novembril 2026 kell 10:30, Eesti aja järgi.", ["kell kümme kolmkümmend"]),
        ("kell 00:05", ["kell null viis"]),
        ("kell 23:00", ["kell kakskümmend kolm"]),
        ("kell 24:00", []),
        ("kell 10:60", []),
    ],
)
def test_estonian_clock_times_keep_the_exact_recap_text(text, aliases):
    document = ET.fromstring(ssml(text, "et-EE-AnuNeural", "et-EE"))
    assert [node.get("alias") for node in document.iter(SSML + "sub")] == aliases
    assert "".join(document.itertext()) == text


@pytest.mark.parametrize(
    "voice,language,styled",
    [
        ("en-US-JennyNeural", "en-US", True),
        ("en-GB-SoniaNeural", "en-GB", False),
        ("et-EE-AnuNeural", "et-EE", False),
    ],
)
def test_only_documented_voice_receives_friendly_style(voice, language, styled):
    document = ET.fromstring(ssml("Hello & welcome!", voice, language))
    style = document.find(".//" + MSTTS + "express-as")
    assert (style is not None) == styled
    if styled:
        assert style.attrib == {"style": "friendly", "styledegree": "0.8"}
    assert "".join(document.itertext()) == "Hello & welcome!"


def test_neutral_roll_back_removes_styling_and_aliases():
    document = ET.fromstring(
        ssml(
            "2026-11-02 & test",
            "et-EE-AnuNeural",
            "et-EE",
            SpeechDelivery(mode="neutral"),
        )
    )
    assert not list(document.iter(SSML + "prosody"))
    assert not list(document.iter(SSML + "sub"))
    assert "".join(document.itertext()) == "2026-11-02 & test"


def test_http_retry_keeps_the_same_voice_markup_and_recap_rate():
    bodies = []

    def handler(request):
        if request.url.path.endswith("issueToken"):
            return httpx.Response(200, text="fixture-token")
        bodies.append(request.content)
        return httpx.Response(
            401 if len(bodies) == 1 else 200, content=b"fixture-audio"
        )

    provider = AzureTtsClient(
        "fixture",
        "fixture",
        "en-US-JennyNeural",
        "en-US",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert provider.synthesize('Please say "Yes, I confirm."') == b"fixture-audio"
    finally:
        provider.close()
    assert bodies[0] == bodies[1]
    document = ET.fromstring(bodies[0])
    assert document.find(".//" + SSML + "prosody").get("rate") == "0.94"


def test_native_social_reply_uses_public_llm_node_without_model_request():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent
    from livekit.agents import llm
    from livekit.agents.voice.agent import ModelSettings

    async def run():
        state = CallTools(Slots(), language="en")
        agent = TelephoneAgent(state)
        message = llm.ChatMessage(role="user", content=["Thank you"])
        context = llm.ChatContext(items=[message])
        await agent.on_user_turn_completed(context.copy(), message)
        with patch(
            "livekit.agents.Agent.default.llm_node",
            side_effect=AssertionError("Provider called"),
        ):
            assert [
                chunk async for chunk in agent.llm_node(context, [], ModelSettings())
            ] == [state.direct_reply]

    asyncio.run(run())


def test_native_booking_request_still_uses_provider_planning():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent
    from livekit.agents import llm
    from livekit.agents.voice.agent import ModelSettings

    async def run():
        state = CallTools(Slots(), language="en")
        agent = TelephoneAgent(state)
        message = llm.ChatMessage(
            role="user", content=["Book a spa treatment tomorrow at 10 AM"]
        )
        context = llm.ChatContext(items=[message])
        await agent.on_user_turn_completed(context.copy(), message)

        async def plan(*args):
            yield "provider planning"

        with patch("livekit.agents.Agent.default.llm_node", plan):
            assert [
                chunk async for chunk in agent.llm_node(context, [], ModelSettings())
            ] == ["provider planning"]

    asyncio.run(run())


@pytest.mark.parametrize("utterance", ["Korda palun", "English, please"])
def test_late_completion_of_old_recap_cannot_authorize_repeated_or_switched_recap(
    utterance,
):
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent
    from livekit import rtc
    from livekit.agents import llm
    from livekit.agents.voice.speech_handle import SpeechHandle

    async def run():
        state = CallTools(Slots())
        await prepared(state)
        state.pending["delivery"] = False
        agent = TelephoneAgent(state)
        old = state.pending
        recap = state.render_recap()
        first, second = SpeechHandle.create(), SpeechHandle.create()

        async def text():
            yield "Tere!"

        async def synthesize(agent, text, settings):
            async for _ in text:
                pass
            yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            with patch.object(agent, "_current_speech", return_value=first):
                assert [frame async for frame in agent.tts_node(text(), None)]
            state.observe_user_text(utterance)
            current = state.pending
            assert current is not old and current["hold_id"] == old["hold_id"]
            with patch.object(agent, "_current_speech", return_value=second):
                assert [frame async for frame in agent.tts_node(text(), None)]
        first_item = llm.ChatMessage(role="assistant", content=[recap])
        first._item_added([first_item])
        agent.on_conversation_item_added(NS(item=first_item))
        assert state.pending is current
        assert current["delivery"] is current["approved"] is False
        second_item = llm.ChatMessage(role="assistant", content=[state.render_recap()])
        second._item_added([second_item])
        agent.on_conversation_item_added(NS(item=second_item))
        assert current["delivery"] and not current["approved"]
        state.observe_user_text(CONSENT[state.language])
        assert current["approved"]
        assert not first._item_added_callbacks and not second._item_added_callbacks

    asyncio.run(run())


def test_native_provider_builds_complete_markup_per_sentence_and_resets_language():
    pytest.importorskip("livekit.agents")
    from app.providers.telephone_tts import TelephoneTTS

    async def run():
        requests = []

        async def chunks():
            yield b"\0\0" * 2400, False

        @asynccontextmanager
        async def post(**kwargs):
            requests.append(kwargs["data"])
            yield NS(raise_for_status=lambda: None, content=NS(iter_chunks=chunks))

        provider = TelephoneTTS(
            voice="en-US-JennyNeural",
            language="en-US",
            delivery=SpeechDelivery(),
            speech_key="fixture",
            speech_region="fixture",
            http_session=NS(post=post),
        )

        async def speak(text):
            async with provider.synthesize(text) as stream:
                assert [event async for event in stream]

        try:
            await speak("Hello & welcome!")
            provider.update_options(voice="et-EE-AnuNeural", language="et-EE")
            provider.set_recap_delivery(True)
            await speak("2026-11-02 10:30, ajavöönd Europe/Tallinn.")
            provider.set_recap_delivery(False)
            await speak("Mis kell sulle sobiks?")
        finally:
            await provider.aclose()
        documents = [ET.fromstring(body) for body in requests]
        assert documents[0].find(".//" + MSTTS + "express-as") is not None
        assert all(
            doc.find(".//" + MSTTS + "express-as") is None for doc in documents[1:]
        )
        assert [
            doc.find(".//" + SSML + "prosody").get("rate") for doc in documents
        ] == ["0.98", "0.94", "0.98"]
        assert (
            documents[1].find(".//" + SSML + "voice").get("name") == "et-EE-AnuNeural"
        )

    asyncio.run(run())
