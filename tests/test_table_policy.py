"""Restaurant calls use the shared policy, never an accidentally wired legacy track."""

import asyncio
import copy
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.booking.tools import Dispatcher
from app.booking.base import Hold
from app.telephone import CallTools
from tests.test_demo_plan import LiveSlots

DAY = (datetime.now(ZoneInfo("Europe/Tallinn")) + timedelta(days=7)).date().isoformat()
REQUEST = {"date": DAY, "start_time": "18:30", "party_size": 4}


class Tables:
    """Synthetic adapter boundary; CallTools and Dispatcher remain real."""

    operational = True

    def __init__(self):
        self.calls = []
        self.catalogue = {
            "kind": "table",
            "synthetic": True,
            "venue": {"name": "Meretuule restoran", "timezone": "Europe/Tallinn"},
            "tables": [{"id": "table-03", "name": "Laud 3", "capacity": 4}],
            "rules": {
                "opening_time": "12:00",
                "closing_time": "22:00",
                "duration_minutes": 120,
                "max_party_size": 6,
                "horizon_days": 90,
            },
        }
        self.offers = [
            {
                "table_offer_id": "table_offer_" + "a" * 32,
                **REQUEST,
                "start": DAY + "T18:30:00+03:00",
                "end": DAY + "T20:30:00+03:00",
                "duration_minutes": 120,
                "capacity": 4,
                "table_id": "table-03",
                "table_name": "Laud 3",
                "venue_name": "Meretuule restoran",
                "timezone": "Europe/Tallinn",
            }
        ]
        # Respect the actual requested day's Tallinn offset in winter as well.
        for key, hour in (("start", 18), ("end", 20)):
            self.offers[0][key] = (
                datetime.fromisoformat(DAY)
                .replace(hour=hour, minute=30, tzinfo=ZoneInfo("Europe/Tallinn"))
                .isoformat()
            )
        self.hold = Hold(
            "hold_" + "b" * 32,
            self.offers[0]["table_offer_id"],
            None,
            "EUR",
            time.monotonic() + 600,
            {
                "synthetic": True,
                "kind": "table",
                "recap": copy.deepcopy(self.offers[0]),
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=600)
                ).isoformat(),
            },
        )
        self.confirm_result = {
            "ok": True,
            "booking_id": "table_" + "c" * 32,
            "booking": {
                **copy.deepcopy(self.offers[0]),
                "id": "table_" + "c" * 32,
                "kind": "table",
                "status": "confirmed",
            },
        }
        self.cancel_result = {
            "ok": True,
            "kind": "table",
            "booking_id": "table_" + "c" * 32,
            "status": "cancelled",
        }

    async def get_table_catalogue(self):
        self.calls.append(("catalogue", {}))
        return copy.deepcopy(self.catalogue)

    async def search_tables(self, date, start_time, party_size):
        self.calls.append(
            (
                "search",
                {"date": date, "start_time": start_time, "party_size": party_size},
            )
        )
        return copy.deepcopy(self.offers)

    async def create_hold(self, table_offer_id):
        self.calls.append(("hold", {"table_offer_id": table_offer_id}))
        return copy.deepcopy(self.hold)

    async def get_hold(self, hold_id):
        self.calls.append(("hold_read", {"hold_id": hold_id}))
        return (
            copy.deepcopy(self.hold)
            if self.hold and self.hold.hold_id == hold_id
            else None
        )

    async def confirm(self, hold_id, guest, key):
        self.calls.append(
            ("confirm", {"hold_id": hold_id, "guest": copy.deepcopy(guest), "key": key})
        )
        result = copy.deepcopy(self.confirm_result)
        if isinstance(result.get("booking"), dict):
            result["booking"].setdefault(
                "guest_name", f"{guest['firstName']} {guest['lastName']}"
            )
        return result

    async def cancel(self, booking_id, key):
        self.calls.append(("cancel", {"booking_id": booking_id, "key": key}))
        return copy.deepcopy(self.cancel_result)


def table_state(*, language="et"):
    backend = Tables()
    state = CallTools(
        Dispatcher(table=backend, business="restaurant"), language=language
    )
    return state, backend


async def prepare_table(state, **overrides):
    return await state.dispatch("plan_demo_table", {**REQUEST, **overrides})


def test_restaurant_selector_excludes_accidentally_wired_legacy_tools():
    dispatcher = Dispatcher(slot=LiveSlots())
    dispatcher.business = "restaurant"
    state = CallTools(dispatcher)
    assert state.business == "restaurant"
    assert state.names == {"get_demo_profile"}
    assert {t["function"]["name"] for t in state.conversation_tools()} == {
        "get_demo_profile"
    }


def test_restaurant_selector_denies_legacy_dispatch_even_with_live_slot_adapter():
    async def run():
        backend = LiveSlots()
        dispatcher = Dispatcher(slot=backend)
        dispatcher.business = "restaurant"
        state = CallTools(dispatcher)
        assert await state.dispatch("get_slot_catalogue", {}) == {
            "error": "not_allowed"
        }
        assert not backend.calls

    asyncio.run(run())


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_restaurant_profile_and_instructions_never_leak_legacy_domain(language):
    state = CallTools(Dispatcher(), business="restaurant", language=language)
    assert state.demo["profile"]["name"] == "Meretuule restoran"
    instructions = state.conversation_instructions
    assert "plan_demo_table" in instructions and "party_size" in instructions
    assert "Europe/Tallinn" in instructions and "current_date" in instructions
    assert "Demo Esimene" in instructions and "Demo Teine" in instructions
    assert "example.invalid" not in instructions and state.call_id not in instructions
    for text in (instructions, state.instructions, state.greeting):
        assert not any(
            word in text.casefold()
            for word in ("spa", "spaa", "hotel", "hotell", "спа", "отел")
        )
    state.observe_user_text(
        {"et": "Kes sa oled?", "en": "Who are you?", "ru": "Кто вы?"}[language],
        language=language,
    )
    assert "Meretuule" in state.direct_reply
    assert not any(
        word in state.direct_reply.casefold() for word in ("spa", "hotell", "отел")
    )


@pytest.mark.parametrize(
    "language,utterance",
    [
        ("et", "Soovin lauda broneerida."),
        ("en", "I'd like to book a table."),
        ("ru", "Хочу забронировать столик."),
    ],
)
def test_restaurant_inquiry_asks_only_missing_date_time_and_headcount(
    language, utterance
):
    from app.booking_response import trusted_booking_response
    from app.conversation import TABLE_QUESTIONS

    state = CallTools(Dispatcher(), business="restaurant", language=language)
    state.observe_user_text(utterance, language=language)
    assert state.booking_inquiry == {"kind": "table"}
    assert trusted_booking_response(state) == {
        "content": TABLE_QUESTIONS[language]["date"][0]
    }
    state.observe_user_text(DAY, language=language)
    assert state.booking_inquiry == {"kind": "table", "date": DAY}
    assert state.inquiry_reply() == TABLE_QUESTIONS[language]["time"][0]
    state.observe_user_text("18:30", language=language)
    assert state.inquiry_reply() == TABLE_QUESTIONS[language]["party_size"][0]
    state.observe_user_text("4", language=language)
    assert state.booking_inquiry == {"kind": "table", **REQUEST}
    assert state.inquiry_reply() is None
    assert state.pending is None and not state.bookings


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_restaurant_guard_rejects_legacy_questions_and_unverified_question_claims(
    language,
):
    from app.conversation import QUESTIONS

    state = CallTools(Dispatcher(), business="restaurant", language=language)
    forbidden = [
        QUESTIONS[language][key][0]
        for key in ("booking_kind", "spa_service", "room", "arrival")
    ]
    forbidden += [
        {
            "et": "Sinu laud on juba kinnitatud. Mis kell sa tuled?",
            "en": "Your table is confirmed. What time are you coming?",
            "ru": "Ваш столик подтверждён. Когда вы придёте?",
        }[language]
    ]
    for text in forbidden:
        assert state.guard_reply(text, []) != text
    assert state.pending is None


def test_table_plan_owns_exact_backend_offer_and_hold_but_never_confirms():
    async def run():
        state, backend = table_state()
        result = await prepare_table(state, guest_fixture_id="guest-002")
        assert result.get("ok"), result
        assert result["kind"] == "table" and state.pending["kind"] == "table"
        assert [name for name, _ in backend.calls] == [
            "catalogue",
            "search",
            "hold",
            "hold_read",
        ]
        assert backend.calls[1][1] == REQUEST
        assert backend.calls[2][1] == {
            "table_offer_id": backend.offers[0]["table_offer_id"]
        }
        assert result["recap"]["guest_name"] == "Demo Teine"
        assert result["recap"]["party_size"] == 4
        assert result["recap"]["table_name"] == "Laud 3"
        assert state.holds == {result["hold_id"]} and not state.bookings
        assert state.pending["delivery"] is state.pending["approved"] is False
        assert state.pending["expires_at"] <= backend.hold.expires_at
        assert await state.dispatch(
            "confirm_table_booking", {"hold_id": result["hold_id"]}
        ) == {"error": "consent_required"}

    asyncio.run(run())


def test_table_conversation_schemas_are_only_the_approved_five_tools():
    state, _ = table_state()
    assert {t["function"]["name"] for t in state.conversation_tools()} == {
        "get_demo_profile",
        "get_table_catalogue",
        "plan_demo_table",
        "confirm_table_booking",
        "cancel_table_booking",
    }
    assert {"search_tables", "hold_table", "prepare_demo_table"} <= state.names
    for tool in state.available_tools():
        parameters = tool["function"]["parameters"]
        assert parameters["additionalProperties"] is False
        assert (
            not {"guest", "consent", "idempotency_key"}
            & parameters["properties"].keys()
        )
    plan = next(
        t
        for t in state.conversation_tools()
        if t["function"]["name"] == "plan_demo_table"
    )["function"]
    assert set(plan["parameters"]["required"]) == {"date", "start_time", "party_size"}


@pytest.mark.parametrize(
    "change",
    [
        {"party_size": True},
        {"party_size": 4.0},
        {"party_size": "4"},
        {"party_size": 0},
        {"party_size": 7},
        {"date": "2026-2-3"},
        {"date": "2026-02-30"},
        {"start_time": "18:5"},
        {"start_time": "24:00"},
        {"guest": {"email": "private@example.invalid"}},
        {"consent": True},
    ],
)
def test_table_plan_invalid_arguments_never_reach_adapter(change):
    async def run():
        state, backend = table_state()
        assert await prepare_table(state, **change) == {"error": "invalid_arguments"}
        assert not backend.calls and state.pending is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"party_size": 3},
        {"start_time": "19:00"},
        {"date": "2099-01-01"},
        {"start": DAY + "T19:00:00+03:00"},
        {"end": DAY + "T18:00:00+03:00"},
    ],
)
def test_table_plan_cannot_hold_an_inexact_or_malformed_backend_offer(change):
    async def run():
        state, backend = table_state()
        backend.offers[0].update(change)
        result = await prepare_table(state)
        assert result.get("error") in {"table_unavailable", "booking_unavailable"}
        assert not any(name == "hold" for name, _ in backend.calls)
        assert state.pending is None

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["catalogue", "search", "hold", "hold_read"])
def test_superseded_table_plan_stops_after_every_adapter_await(phase):
    async def run():
        state, backend = table_state()
        started, release = asyncio.Event(), asyncio.Event()
        method = {
            "catalogue": "get_table_catalogue",
            "search": "search_tables",
            "hold": "create_hold",
            "hold_read": "get_hold",
        }[phase]
        original = getattr(backend, method)

        async def delayed(*args):
            started.set()
            await release.wait()
            return await original(*args)

        setattr(backend, method, delayed)
        older = asyncio.create_task(prepare_table(state))
        await asyncio.wait_for(started.wait(), 2)
        state.observe_user_text("Ei, ära kinnita.")
        await state.dispatch("get_demo_profile", {})
        owned, results, outcome = (
            set(state.holds),
            copy.deepcopy(state.results),
            state.outcome,
        )
        release.set()
        assert await asyncio.wait_for(older, 2) == {"error": "turn_superseded"}
        assert state.pending is None and state.holds == owned
        assert state.results == results and state.outcome == outcome

    asyncio.run(run())


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_table_catalogue_and_availability_render_only_verified_restaurant_facts(
    language,
):
    async def run():
        state, backend = table_state(language=language)
        state.observe_user_text(
            {
                "et": "Millal restoran on avatud?",
                "en": "What are the restaurant opening hours?",
                "ru": "Какие часы работы ресторана?",
            }[language],
            language=language,
        )
        catalogue = await state.dispatch("get_table_catalogue", {})
        spoken = state.guard_reply("untrusted availability claim", [catalogue])
        assert "12:00" in spoken and "22:00" in spoken
        assert "Meretuule restoran" in spoken
        assert not any(word in spoken.casefold() for word in ("spa", "hotell", "цена"))
        state.observe_user_text("18:30", language=language)
        found = await state.dispatch("search_tables", REQUEST)
        spoken = state.guard_reply("untrusted availability claim", [found])
        for field in ("18:30", DAY, "Laud 3"):
            assert field in spoken
        assert "example.invalid" not in spoken
        backend.offers = []
        empty = await state.dispatch("search_tables", REQUEST)
        assert "Laud 3" not in state.guard_reply(
            "untrusted availability claim", [empty]
        )
        assert not state.bookings and state.pending is None

    asyncio.run(run())


def test_table_offer_hold_and_booking_are_call_owned_and_cancel_replay_cannot_reconfirm():
    from app.languages import CONSENT

    async def run():
        state, backend = table_state()
        other = CallTools(state.dispatcher)
        searched = await state.dispatch("search_tables", REQUEST)
        offer_id = searched["offers"][0]["table_offer_id"]
        assert await other.dispatch("hold_table", {"table_offer_id": offer_id}) == {
            "error": "not_owned"
        }
        held = await state.dispatch("hold_table", {"table_offer_id": offer_id})
        assert await other.dispatch(
            "prepare_demo_table", {"hold_id": held["hold_id"]}
        ) == {"error": "not_owned"}
        assert (
            await state.dispatch("prepare_demo_table", {"hold_id": held["hold_id"]})
        )["ok"]
        state.mark_recap_delivered(held["hold_id"])
        state.observe_user_text(CONSENT["et"])
        assert await other.dispatch(
            "confirm_table_booking", {"hold_id": held["hold_id"]}
        ) == {"error": "not_owned"}
        confirmed = await state.dispatch(
            "confirm_table_booking", {"hold_id": held["hold_id"]}
        )
        booking_id = confirmed["booking_id"]
        assert await other.dispatch(
            "cancel_table_booking", {"booking_id": booking_id}
        ) == {"error": "not_owned"}
        assert await state.dispatch(
            "cancel_table_booking", {"booking_id": booking_id}
        ) == {"error": "cancellation_required"}
        assert not other.authorize_cancellation(booking_id)
        assert state.authorize_cancellation(booking_id)
        cancelled = await state.dispatch(
            "cancel_table_booking", {"booking_id": booking_id}
        )
        assert cancelled["ok"]
        assert (
            await state.dispatch("cancel_table_booking", {"booking_id": booking_id})
            == cancelled
        )
        assert await state.dispatch(
            "confirm_table_booking", {"hold_id": held["hold_id"]}
        ) == {"error": "already_cancelled"}
        assert [name for name, _ in backend.calls if name in {"confirm", "cancel"}] == [
            "confirm",
            "cancel",
        ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,args",
    [
        ("search_tables", {"date": "bad", "start_time": "18:30", "party_size": 4}),
        ("hold_table", {"table_offer_id": "foreign"}),
        ("prepare_demo_table", {"hold_id": "foreign"}),
        ("plan_demo_table", []),
    ],
)
def test_every_new_table_proposal_attempt_invalidates_previous_delivery_and_consent(
    name, args
):
    from app.languages import CONSENT

    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        assert (await state.dispatch(name, args)).get("error")
        assert state.pending is None
        assert (
            await state.dispatch("confirm_table_booking", {"hold_id": ready["hold_id"]})
        )["error"] == "consent_required"
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


def test_actual_allocated_table_from_hold_overrides_search_preview(tmp_path):
    from app.booking.demo_table import DemoTableAdapter
    from app.languages import CONSENT

    async def run():
        adapter = DemoTableAdapter(str(tmp_path / "tables.db"))
        state = CallTools(Dispatcher(table=adapter, business="restaurant"))
        found = await state.dispatch("search_tables", REQUEST)
        assert found["offers"][0]["table_name"] == "Laud 3"
        # Another independent session legitimately allocates the first table.
        other = CallTools(state.dispatcher)
        assert (await prepare_table(other))["recap"]["table_name"] == "Laud 3"
        held = await state.dispatch(
            "hold_table", {"table_offer_id": found["offers"][0]["table_offer_id"]}
        )
        ready = await state.dispatch("prepare_demo_table", {"hold_id": held["hold_id"]})
        assert ready.get("ok"), ready
        assert ready["recap"]["table_name"] == "Laud 4"
        assert "Laud 4" in state.render_recap() and "Laud 3" not in state.render_recap()
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        confirmed = await state.dispatch(
            "confirm_table_booking", {"hold_id": ready["hold_id"]}
        )
        assert confirmed.get("ok"), confirmed
        assert confirmed["booking"]["table_name"] == "Laud 4"
        readback = await adapter.get_operator_bookings(DAY)
        assert readback["items"][0]["id"] == confirmed["booking_id"]
        assert readback["items"][0]["table_name"] == "Laud 4"

    asyncio.run(run())


@pytest.mark.parametrize(
    "utterance",
    [
        "Please book a table tomorrow for 4 adults and 2 children.",
        "Soovin lauda homme, broneering on 4 täiskasvanule ja 2 lapsele.",
        "Хочу забронировать столик завтра для 4 взрослых и 2 детей.",
    ],
)
def test_restaurant_never_treats_adult_count_as_total_diners(utterance):
    state, _ = table_state()
    state.observe_user_text(utterance)
    assert not state.booking_inquiry or "party_size" not in state.booking_inquiry


@pytest.mark.parametrize(
    "utterance",
    [
        "Please book a table on November 5 at 18:30 for 4 people.",
        "Please book a table tomorrow at six PM for four people.",
        "Soovin lauda broneerida homme kell kaheksateist neljale inimesele.",
    ],
)
def test_unparsed_but_supplied_dates_or_times_defer_to_planning_instead_of_false_missing_question(
    utterance,
):
    state, _ = table_state()
    state.observe_user_text(utterance)
    assert state.inquiry_reply() is None


def test_restaurant_approved_english_date_time_clarifications_are_not_unverified_claims():
    from app.languages import ENGLISH

    state, _ = table_state(language="en")
    for key in ("ambiguous_date", "ambiguous_time"):
        assert state.guard_reply(ENGLISH[key], []) == ENGLISH[key]


def test_restaurant_catalogue_from_wrong_venue_fails_closed():
    async def run():
        state, backend = table_state()
        backend.catalogue["venue"]["name"] = "Legacy Hotel and Spa"
        assert await state.dispatch("get_table_catalogue", {}) == {
            "error": "booking_unavailable"
        }
        assert "Legacy" not in state.guard_reply("untrusted", [])

    asyncio.run(run())
