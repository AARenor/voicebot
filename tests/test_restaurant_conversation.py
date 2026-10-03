"""Restaurant-specific dialogue and the reused call ownership/consent policy."""

import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.booking.restaurant import RestaurantAdapter
from app.booking_response import trusted_booking_response
from app.business import restaurant_dispatcher
from app.languages import AFFIRMATIONS_ET, CONSENT, select_language
from app.restaurant_call import COPY, parse_restaurant_request, restaurant_spoken_date
from app.restaurant_data import load_restaurant_data
from app.call_factory import make_call_tools


@pytest.fixture
def make_state(tmp_path):
    data = load_restaurant_data()
    adapter = RestaurantAdapter(
        str(tmp_path / "restaurant.db"), data=data, allow_writes=True
    )

    def create(language="et"):
        return make_call_tools(restaurant_dispatcher(adapter, data), language=language)

    return create


def tomorrow():
    return (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=1)
    ).isoformat()


async def prepare(state, party=4, time="14:00"):
    state.observe_user_text("Prepare a table.", language=state.language)
    result = await state.dispatch(
        "plan_restaurant_reservation",
        {"date": tomorrow(), "start_time": time, "party_size": party},
    )
    assert result.get("ok"), result
    return result


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_restaurant_only_prompt_tools_greeting_and_recap(make_state, language):
    async def run():
        state = make_state(language)
        assert state.greeting == COPY[language]["greeting"]
        assert "RESTAURANT" in state.conversation_instructions
        advertised = {tool["function"]["name"] for tool in state.conversation_tools()}
        assert advertised == {
            "get_restaurant_information",
            "plan_restaurant_reservation",
            "confirm_slot_booking",
            "cancel_slot_booking",
        }
        assert "plan_demo_stay" not in advertised
        result = await prepare(state)
        assert result["recap"]["party_size"] == 4
        assert result["recap"]["duration_minutes"] == 90
        assert CONSENT[language] in state.render_recap()
        assert "Meretuule Demo Restaurant" in state.render_recap()
        assert "spa" not in state.render_recap().casefold()

    asyncio.run(run())


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_booking_requires_later_exact_consent_after_delivered_recap(
    make_state, language
):
    async def run():
        state = make_state(language)
        result = await prepare(state)
        state.observe_user_text(CONSENT[language], language=language)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": result["hold_id"]})
        )["error"] == "consent_required"
        result = await state.dispatch(
            "prepare_demo_booking", {"hold_id": result["hold_id"]}
        )
        assert state.mark_recap_delivered(result["hold_id"])
        state.observe_user_text(CONSENT[language], language=language)
        response = trusted_booking_response(state)
        assert response["name"] == "confirm_slot_booking"
        confirmed = await state.dispatch(response["name"], response["arguments"])
        assert confirmed["ok"] is True
        assert (
            state.guard_reply("anything invented", state.results)
            == COPY[language]["confirmed"]
        )

    asyncio.run(run())


def test_call_ownership_blocks_foreign_hold_and_cancellation(make_state):
    async def run():
        first, second = make_state(), make_state()
        result = await prepare(first)
        assert (
            await second.dispatch(
                "prepare_demo_booking", {"hold_id": result["hold_id"]}
            )
        )["error"] == "not_owned"
        assert (
            await second.dispatch(
                "confirm_slot_booking", {"hold_id": result["hold_id"]}
            )
        )["error"] == "not_owned"
        assert first.mark_recap_delivered(result["hold_id"])
        first.observe_user_text(CONSENT["et"], language="et")
        confirmed = await first.dispatch(
            "confirm_slot_booking", {"hold_id": result["hold_id"]}
        )
        identifier = str(confirmed["booking"]["id"])
        assert (
            await second.dispatch("cancel_slot_booking", {"booking_id": identifier})
        )["error"] == "not_owned"

    asyncio.run(run())


@pytest.mark.parametrize(
    "utterance",
    [
        "yes",
        "okay",
        "thanks",
        "yes but make it five",
        "Yes, confirm. And change the time.",
    ],
)
def test_ambiguous_or_changed_details_are_not_confirmation(make_state, utterance):
    async def run():
        state = make_state("en")
        result = await prepare(state)
        state.mark_recap_delivered(result["hold_id"])
        state.observe_user_text(utterance, language="en")
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": result["hold_id"]})
        )["error"] == "consent_required"

    asyncio.run(run())


def test_language_change_requires_new_recap_delivery(make_state):
    async def run():
        state = make_state("en")
        result = await prepare(state)
        state.mark_recap_delivered(result["hold_id"])
        state.observe_user_text("Palun räägi eesti keeles.", language="et")
        assert state.pending and state.pending["delivery"] is False
        state.observe_user_text(CONSENT["et"], language="et")
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": result["hold_id"]})
        )["error"] == "consent_required"

    asyncio.run(run())


@pytest.mark.parametrize("utterance", sorted(AFFIRMATIONS_ET))
def test_estonian_natural_confirmation_and_known_asr_spellings(make_state, utterance):
    async def run():
        state = make_state("et")
        proposal = await prepare(state)
        assert state.mark_recap_delivered(proposal["hold_id"])
        # A short Estonian commitment outweighs incorrect provider metadata.
        assert select_language(utterance, "english", "et") == "et"
        state.observe_user_text(utterance, detected_language="english")
        action = trusted_booking_response(state)
        assert action["name"] == "confirm_slot_booking"
        result = await state.dispatch(action["name"], action["arguments"])
        assert result["ok"] and result["booking"]["party_size"] == 4
        assert (
            state.guard_reply("invented success", state.results)
            == COPY["et"]["confirmed"]
        )
        rows = await state.dispatcher._slot.get_operator_bookings(tomorrow())
        assert len(rows["items"]) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "utterance",
    [
        "jah",
        "ja",
        "ei kinnita",
        "ei, ja kinnitää",
        "ära kinnita",
        "jah kinnitää?",
        "kas ma ütlen ja kinnitää",
        '"ja kinnitää"',
        "ütle ja kinnitää",
        "ja kinnitää homme kell 18",
        "jah aga viiele",
        "ja kinnitää, aga muuda kellaaega",
        "ma ei öelnud ja kinnitää",
        "jah kinnitää või mitte",
        "kinnitää",
        "ja kinnitöö",
    ],
)
def test_confirmation_tolerance_never_accepts_negatives_questions_or_changes(
    make_state, utterance
):
    async def run():
        state = make_state("et")
        proposal = await prepare(state)
        assert state.mark_recap_delivered(proposal["hold_id"])
        state.observe_user_text(utterance, language="et")
        result = await state.dispatch(
            "confirm_slot_booking", {"hold_id": proposal["hold_id"]}
        )
        assert result["error"] == "consent_required"
        assert not state.bookings
        assert not (await state.dispatcher._slot.get_operator_bookings(tomorrow()))[
            "items"
        ]

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["undelivered", "expired", "language_change"])
def test_asr_confirmation_requires_current_delivered_recap(make_state, boundary):
    async def run():
        state = make_state("en" if boundary == "language_change" else "et")
        proposal = await prepare(state)
        if boundary != "undelivered":
            assert state.mark_recap_delivered(proposal["hold_id"])
        if boundary == "expired":
            state.pending["expires_at"] = 0
        state.observe_user_text("ja kinnitää")
        result = await state.dispatch(
            "confirm_slot_booking", {"hold_id": proposal["hold_id"]}
        )
        assert result["error"] == "consent_required"
        assert not state.bookings

    asyncio.run(run())


def test_partial_asr_confirmation_waits_for_final_user_turn(make_state):
    async def run():
        state = make_state("et")
        proposal = await prepare(state)
        assert state.mark_recap_delivered(proposal["hold_id"])
        state.observe_user_text("ja kinnitää", is_final=False)
        assert state.pending["delivery"] and not state.pending["approved"]
        state.observe_user_text("ei, ära kinnita", is_final=True, language="et")
        assert (
            await state.dispatch(
                "confirm_slot_booking", {"hold_id": proposal["hold_id"]}
            )
        )["error"] == "consent_required"
        assert not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,expected",
    [
        ("et", "4. oktoober 2026"),
        ("en", "Sunday, 4 October 2026"),
        ("ru", "4 октября 2026"),
    ],
)
def test_recap_speaks_month_names_from_the_trusted_date(language, expected):
    assert restaurant_spoken_date("2026-10-04", language) == expected


@pytest.mark.parametrize(
    "language,utterance",
    [
        ("et", "Soovin homme lauda neljale kell 14.00"),
        ("en", "I'd like a table for four tomorrow at 2 pm"),
        ("ru", "Забронируйте столик на четверых завтра в 14:00"),
    ],
)
def test_natural_booking_request_uses_one_trusted_plan(make_state, language, utterance):
    state = make_state(language)
    state.observe_user_text(utterance, language=language)
    assert state.booking_inquiry == {
        "date": tomorrow(),
        "start_time": "14:00",
        "party_size": 4,
    }
    response = trusted_booking_response(state)
    assert response == {
        "name": "plan_restaurant_reservation",
        "arguments": state.booking_inquiry,
    }


@pytest.mark.parametrize(
    "language,initial_request,date_reply,time_reply,party_reply",
    [
        ("et", "Soovin broneerida laua", "Homme", "Kell 14", "Neljale"),
        ("en", "I'd like to reserve a table", "Tomorrow", "At 2 pm", "Four"),
        ("ru", "Хочу забронировать столик", "Завтра", "В 14:00", "Четыре"),
    ],
)
def test_one_missing_detail_at_a_time_and_fields_survive_turns(
    make_state, language, initial_request, date_reply, time_reply, party_reply
):
    state = make_state(language)
    state.observe_user_text(initial_request, language=language)
    assert state.inquiry_reply() == COPY[language]["date"]
    state.observe_user_text(date_reply, language=language)
    assert state.inquiry_reply() == COPY[language]["time"]
    state.observe_user_text(time_reply, language=language)
    assert state.inquiry_reply() == COPY[language]["party"]
    state.observe_user_text(party_reply, language=language)
    assert state.booking_inquiry["party_size"] == 4
    assert trusted_booking_response(state)["name"] == "plan_restaurant_reservation"


@pytest.mark.parametrize(
    "language,question,topic",
    [
        ("et", "Milline on menüü?", "menu"),
        ("en", "What is on the menu?", "menu"),
        ("ru", "Что есть в меню?", "menu"),
        ("et", "Millal restoran avatud on?", "hours"),
        ("en", "What are your opening hours?", "hours"),
        ("ru", "Когда ресторан открыт?", "hours"),
        ("et", "Mul on raske pähkliallergia", "allergens"),
        ("en", "I have a severe peanut allergy", "allergens"),
        ("ru", "У меня сильная аллергия на орехи", "allergens"),
    ],
)
def test_grounded_restaurant_questions_need_no_model_or_mutation(
    make_state, language, question, topic
):
    state = make_state(language)
    state.observe_user_text(question, language=language)
    assert trusted_booking_response(state) == {
        "content": state.information_reply(topic)
    }
    assert state.pending is None and state.bookings == set()


@pytest.mark.parametrize(
    "language,question,absent",
    [
        ("en", "What vegan dishes are on the menu?", "Baked salmon"),
        ("et", "Milliseid vegan toite menüüs on?", "Ahjulõhe"),
        ("ru", "Есть ли веганское меню?", "Запечённый лосось"),
    ],
)
def test_vegan_answers_use_approved_diet_labels(make_state, language, question, absent):
    state = make_state(language)
    state.observe_user_text(question, language=language)
    reply = state.inquiry_reply()
    assert absent not in reply
    assert state.restaurant["menu"][0]["name"][language] in reply
    assert state.restaurant["allergy_notice"][language] not in reply


def test_specific_dish_allergens_and_kitchen_hours_are_grounded(make_state):
    state = make_state("en")
    state.observe_user_text("Does the salmon contain allergens?", language="en")
    assert "fish, milk" in state.inquiry_reply()
    assert "celery" not in state.inquiry_reply()
    assert "cannot guarantee" in state.inquiry_reply()
    state.observe_user_text("When does the kitchen close?", language="en")
    assert "20:30" in state.inquiry_reply()
    assert "22:30" in state.inquiry_reply()


@pytest.mark.parametrize(
    "language,question",
    [
        ("en", "Book me a hotel room"),
        ("et", "Soovin spaasse massaaži"),
        ("ru", "Хочу забронировать номер в отеле"),
    ],
)
def test_old_business_workflows_are_not_advertised_or_executed(
    make_state, language, question
):
    state = make_state(language)
    state.observe_user_text(question, language=language)
    assert trusted_booking_response(state) == {"content": COPY[language]["domain"]}
    assert "search_availability" not in state.names


def test_unknown_commit_remains_sticky_and_is_never_retried(make_state):
    async def run():
        state = make_state("en")
        result = await prepare(state)
        state.mark_recap_delivered(result["hold_id"])
        state.observe_user_text(CONSENT["en"], language="en")
        original = state.dispatcher.dispatch
        writes = []

        async def lost_response(name, arguments):
            if name == "confirm_slot_booking":
                writes.append(name)
                await original(name, arguments)
                raise TimeoutError("PRIVATE transport details")
            return await original(name, arguments)

        state.dispatcher.dispatch = lost_response
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": result["hold_id"]})
        )["error"] == "write_outcome_unknown"
        state.observe_user_text("Thanks", language="en")
        assert state.direct_reply == COPY["en"]["unknown"]
        state.observe_user_text(CONSENT["en"], language="en")
        await state.dispatch("confirm_slot_booking", {"hold_id": result["hold_id"]})
        assert len(writes) == 1
        assert (
            len(
                (await state.dispatcher._slot.get_operator_bookings(tomorrow()))[
                    "items"
                ]
            )
            == 1
        )

    asyncio.run(run())


def test_rejected_model_arguments_do_not_supply_contacts_or_consent(make_state):
    async def run():
        state = make_state("en")
        result = await prepare(state)
        state.mark_recap_delivered(result["hold_id"])
        state.observe_user_text(CONSENT["en"], language="en")
        assert (
            await state.dispatch(
                "confirm_slot_booking",
                {
                    "hold_id": result["hold_id"],
                    "guest": {"email": "real@example.com"},
                    "consent": True,
                },
            )
        )["error"] == "invalid_arguments"

    asyncio.run(run())


def test_no_booking_tool_when_restaurant_writes_disabled(tmp_path):
    data = load_restaurant_data()
    adapter = RestaurantAdapter(str(tmp_path / "readonly.db"), data=data)
    state = make_call_tools(restaurant_dispatcher(adapter, data))
    names = {tool["function"]["name"] for tool in state.conversation_tools()}
    assert names == {"get_restaurant_information"}
    assert asyncio.run(
        state.dispatch(
            "plan_restaurant_reservation",
            {"date": tomorrow(), "start_time": "14:00", "party_size": 4},
        )
    ) == {"error": "not_allowed"}


def test_parser_does_not_treat_contact_numbers_or_dates_as_party_size():
    now = datetime.now(ZoneInfo("Europe/Tallinn"))
    request = parse_restaurant_request("A table on 2026-10-10 at 19:30", now=now)
    assert "party_size" not in request
    assert request["start_time"] == "19:30"


def test_prompt_and_owned_inventory_do_not_include_fixture_contacts(make_state):
    state = make_state("en")
    assert "example.invalid" not in state.conversation_instructions
    assert "+120255501" not in state.conversation_instructions
    assert "restaurant" in json.dumps(state.restaurant).casefold()


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_provider_fallbacks_remain_available_in_restaurant_policy(make_state, language):
    from app.turn import REPEAT_PROMPT, STT_UNAVAILABLE, TURN_UNAVAILABLE

    state = make_state(language)
    for text in (
        REPEAT_PROMPT[language],
        STT_UNAVAILABLE[language],
        TURN_UNAVAILABLE[language],
        state.fallback,
    ):
        assert state.guard_reply(text, []) == text


@pytest.mark.parametrize(
    "language,text,repeat",
    [
        ("en", "What is on the menu?", "Could you repeat that?"),
        ("et", "Milline on menüü?", "Palun korda."),
        ("ru", "Что есть в меню?", "Повторите, пожалуйста."),
    ],
)
def test_repeat_uses_the_actual_approved_restaurant_reply(
    make_state, language, text, repeat
):
    state = make_state(language)
    state.observe_user_text(text, language=language)
    original = state.guard_reply("", [])
    state.observe_user_text(repeat, language=language)
    assert state.guard_reply("", []) == original


@pytest.mark.parametrize(
    "language,text", [("et", "Aitäh"), ("en", "Thank you"), ("ru", "Спасибо")]
)
def test_social_reply_is_reviewed_and_does_not_require_model_prose(
    make_state, language, text
):
    state = make_state(language)
    state.observe_user_text(text, language=language)
    assert trusted_booking_response(state)["content"] == state.conversation.reply
    assert (
        state.guard_reply("Your hotel room is confirmed", [])
        == state.conversation.reply
    )


@pytest.mark.parametrize(
    "text",
    [
        "A table tomorrow at 19:00 for 2 adults and 2 children",
        "Laud homme kell 19:00 kahele täiskasvanule ja kahele lapsele",
        "Столик завтра в 19:00 на два взрослых и два ребёнка",
    ],
)
def test_children_count_towards_table_capacity(text):
    assert parse_restaurant_request(text)["party_size"] == 4


def test_unspecified_children_require_total_party_size():
    assert "party_size" not in parse_restaurant_request(
        "A table tomorrow at 19:00 for two adults and children"
    )


@pytest.mark.parametrize("weekday", ["Monday", "esmaspäeval", "понедельник"])
def test_weekday_request_resolves_to_next_occurrence(weekday):
    now = datetime(2026, 10, 3, 12, tzinfo=ZoneInfo("Europe/Tallinn"))
    assert parse_restaurant_request("table " + weekday, now=now)["date"] == "2026-10-05"


def test_superseded_prepare_cannot_restore_an_old_recap(make_state):
    async def run():
        state = make_state("en")
        adapter = state.dispatcher._slot
        original = adapter.get_hold
        count = 0

        async def supersede(hold_id):
            nonlocal count
            count += 1
            hold = await original(hold_id)
            # The parent uses the owned slot snapshot. Supersede the additional
            # durable read that supplies the restaurant recap metadata.
            if count == 1:
                state.observe_user_text(
                    "Actually book a table tomorrow at 17:00 for two", language="en"
                )
            return hold

        adapter.get_hold = supersede
        state.observe_user_text("Prepare a table.", language="en")
        result = await state.dispatch(
            "plan_restaurant_reservation",
            {"date": tomorrow(), "start_time": "14:00", "party_size": 4},
        )
        assert result["error"] == "turn_superseded"
        assert state.pending is None
        assert state.render_recap() is None

    asyncio.run(run())
