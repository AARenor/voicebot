import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.telephone import CallTools, CONSENT_TEXT, validate_environment, safe_speech
from app.booking.tools import (
    TOOL_SEARCH_SLOTS,
    TOOL_HOLD_SLOT,
    TOOL_CONFIRM_SLOT,
    TOOL_CANCEL_SLOT,
    TOOL_CATALOGUE,
    TOOL_FAQ,
)


class Slots:
    def __init__(self):
        self.calls = []

    def available_tools(self):
        return [
            TOOL_SEARCH_SLOTS,
            TOOL_HOLD_SLOT,
            TOOL_CONFIRM_SLOT,
            TOOL_CANCEL_SLOT,
            TOOL_CATALOGUE,
            TOOL_FAQ,
        ]

    async def dispatch(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if name == "get_slot_catalogue":
            return {
                "services": [{"id": 1, "name": "Live consultation", "duration": 45}],
                "providers": [{"id": 2, "name": "Live therapist", "services": [1]}],
            }
        if name == "search_slots":
            return {
                "slots": [
                    {
                        "slotId": "actual-slot",
                        "serviceId": "1",
                        "providerId": "2",
                        "date": "2026-11-02",
                        "start": "2026-11-02 10:30",
                    }
                ]
            }
        if name == "hold_slot":
            return {"hold_id": "owned-hold"}
        if name == "confirm_slot_booking":
            return {"ok": True, "booking": {"id": "owned-booking"}}
        return {"ok": True}


CONSENT = "Jah, kinnitan selle testbroneeringu."
CANCEL = "Palun tühista broneering, mille just selles kõnes tegime."


async def held(state):
    slots = await state.dispatch(
        "search_slots", {"service": "1", "provider": "2", "date": "2026-11-02"}
    )
    return await state.dispatch("hold_slot", {"slot_id": slots["slots"][0]["slotId"]})


async def prepared(state, fixture="guest-001"):
    hold = await held(state)
    result = await state.dispatch(
        "prepare_demo_booking",
        {"hold_id": hold["hold_id"], "guest_fixture_id": fixture},
    )
    # These policy tests simulate a trusted reader receiving the full recap.
    if result.get("ok"):
        assert state.render_recap(hold["hold_id"])
        assert state.mark_recap_delivered(hold["hold_id"])
    return result


async def booked(state):
    result = await prepared(state)
    assert result.get("ok"), result
    state.observe_user_text(CONSENT)
    result = await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
    assert result.get("ok"), result
    return result


def test_unknown_write_is_not_logged_as_a_successful_hold_or_booking():
    async def run():
        dispatcher = Slots()
        original = dispatcher.dispatch

        async def dispatch(name, args):
            if name == "confirm_slot_booking":
                return {"ok": False, "error": "write_outcome_unknown"}
            return await original(name, args)

        dispatcher.dispatch = dispatch
        state = CallTools(dispatcher)
        await prepared(state)
        state.observe_user_text(CONSENT)
        result = await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        assert result["error"] == "write_outcome_unknown"
        assert state.outcome == "write_outcome_unknown"
        assert not state.bookings

    asyncio.run(run())


ENV = {
    k: "fixture"
    for k in (
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "GROQ_API_KEY",
        "AZURE_SPEECH_KEY",
        "AZURE_REGION",
    )
}
ENV.update(
    VOICEBOT_BUSINESS_TYPE="hotel_spa",
    LIVEKIT_URL="ws://localhost:7880",
    VOICEBOT_TELEPHONE_DEMO="1",
    EASY_DEMO_WRITES="1",
    EASY_BASE_URL="http://localhost",
    EASY_API_KEY="fixture",
    EASY_STATE_DB=str(Path("/data/journal.db").resolve()),
)


def test_settings_fail_closed():
    validate_environment(ENV)
    for k in (key for key in ENV if key != "VOICEBOT_BUSINESS_TYPE"):
        with pytest.raises(ValueError):
            validate_environment({n: v for n, v in ENV.items() if n != k})
    with pytest.raises(ValueError):
        validate_environment({**ENV, "VOICEBOT_TELEPHONE_DEMO": "0"})


def test_call_ownership_and_server_write_keys():
    async def run():
        d = Slots()
        a, b = CallTools(d), CallTools(d)
        assert "answer_faq" not in a.names
        assert (await a.dispatch("confirm_slot_booking", {"hold_id": "foreign"}))[
            "error"
        ] == "not_owned"
        assert not d.calls
        assert (await a.dispatch("confirm_slot_booking", {"hold_id": []}))[
            "error"
        ] == "not_owned"
        assert (await a.dispatch("cancel_slot_booking", {"booking_id": []}))[
            "error"
        ] == "not_owned"
        await a.dispatch(
            "search_slots", {"service": "1", "provider": "2", "date": "2026-11-02"}
        )
        await a.dispatch(
            "hold_slot", {"slot_id": "actual-slot", "idempotency_key": "untrusted"}
        )
        assert (await b.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"}))[
            "error"
        ] == "not_owned"
        assert (
            await a.dispatch(
                "confirm_slot_booking",
                {"hold_id": "owned-hold", "guest": {"customerId": 1}},
            )
        )["error"] == "invalid_arguments"
        ready = await a.dispatch("prepare_demo_booking", {"hold_id": "owned-hold"})
        assert ready.get("ok"), ready
        assert a.mark_recap_delivered("owned-hold")
        a.observe_user_text(CONSENT)
        args = {"hold_id": "owned-hold", "idempotency_key": "untrusted"}
        first = await a.dispatch("confirm_slot_booking", args)
        key = d.calls[-1][1]["idempotency_key"]
        before = len(d.calls)
        assert await a.dispatch("confirm_slot_booking", args) == first
        assert len(d.calls) == before
        assert d.calls[-1][1]["idempotency_key"] == key
        assert d.calls[-1][1]["idempotency_key"] != "untrusted"
        assert (
            await b.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["error"] == "not_owned"
        assert (
            await a.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["error"] == "cancellation_required"
        a.observe_user_text(CANCEL)
        assert (
            await a.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["ok"]

    asyncio.run(run())


def test_tool_errors_are_closed():
    async def run():
        d = Slots()

        async def fail(*args):
            raise RuntimeError("PII or credentials")

        d.dispatch = fail
        result = await CallTools(d).dispatch(
            "search_slots", {"service": "1", "provider": "2", "date": "2026-11-02"}
        )
        assert result == {"error": "booking_unavailable"}

    asyncio.run(run())


def test_price_guard_runs_before_audio():
    assert "120" not in safe_speech("See maksab 120 eurot.", [])
    assert safe_speech("Tere!", []) == "Tere!"
    assert "120" not in safe_speech("Hind on 120 EUR.", [{"quoted_total": "120"}])
    assert "kakskümmend" not in safe_speech("See maksab sada kakskümmend eurot.", [])


def test_sdk_tools_delegate_without_new_business_logic():
    pytest.importorskip("livekit.agents")
    from app.telephone import sdk_tools

    d = Slots()
    state = CallTools(d)
    search = next(s for s in state.schemas if s["name"] == "search_slots")
    assert "provider" in search["parameters"]["required"]
    tools = sdk_tools(state)
    assert len(tools) == 8
    asyncio.run(tools[0]({"service": "1", "provider": "2", "date": "2026-10-05"}))
    assert d.calls[0][0] == "search_slots"


def test_local_profile_never_dispatches_backend_faq():
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        result = await state.dispatch("get_demo_profile", {})
        assert result.get("synthetic") is True, result
        assert result["profile"]["name"] == "Meretuule Demo Spa"
        assert result["faq"][0]["answer_et"].startswith("Ei. Meretuule Demo Spa")
        assert result["guest_fixtures"][0]["fixture_id"] == "guest-001"
        assert result["call_id"] == state.call_id
        assert (
            result["guest_fixtures"][0]["guest"]["email"]
            == f"demo.esimene+{state.call_id}@example.invalid"
        )
        assert not dispatcher.calls
        assert "answer_faq" not in state.names

    asyncio.run(run())


@pytest.mark.parametrize("slot_id", ["invented-slot", "foreign-slot", [], None])
def test_hold_requires_slot_returned_in_this_call(slot_id):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        assert await state.dispatch("hold_slot", {"slot_id": slot_id}) == {
            "error": "not_owned"
        }
        assert not dispatcher.calls

    asyncio.run(run())


def test_shared_dispatcher_does_not_share_slot_ownership():
    async def run():
        dispatcher = Slots()
        a, b = CallTools(dispatcher), CallTools(dispatcher)
        await held(a)
        before = len(dispatcher.calls)
        assert await b.dispatch("hold_slot", {"slot_id": "actual-slot"}) == {
            "error": "not_owned"
        }
        assert len(dispatcher.calls) == before

    asyncio.run(run())


def test_prepare_binds_fixture_and_recaps_backend_not_saved_examples():
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        result = await prepared(state, "guest-002")
        assert result.get("ok"), result
        assert result["guest_fixture_id"] == "guest-002"
        assert result["recap"] == {
            "serviceId": "1",
            "service_name": "Live consultation",
            "providerId": "2",
            "provider_name": "Live therapist",
            "date": "2026-11-02",
            "start": "2026-11-02 10:30",
            "timezone": "Europe/Tallinn",
            "guest_name": "Demo Teine",
        }
        assert CONSENT_TEXT in result["consent_prompt_et"]
        assert not any(name == "confirm_slot_booking" for name, _ in dispatcher.calls)
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["ok"]
        payload = dispatcher.calls[-1][1]
        assert result["call_id"] == state.call_id
        assert (
            payload["guest"]["email"] == f"demo.teine+{state.call_id}@example.invalid"
        )
        assert payload["guest"]["phone"] == "+12025550102"
        assert "guest_fixture_id" not in payload

    asyncio.run(run())


@pytest.mark.parametrize("fixture", ["guest-unknown", "example-booking-001", [], None])
def test_fake_guest_fixture_cannot_prepare(fixture):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        await held(state)
        result = await state.dispatch(
            "prepare_demo_booking",
            {"hold_id": "owned-hold", "guest_fixture_id": fixture},
        )
        assert result.get("error") == "unknown_guest_fixture", result
        assert not any(name == "confirm_slot_booking" for name, _ in dispatcher.calls)

    asyncio.run(run())


def test_foreign_hold_cannot_prepare():
    async def run():
        dispatcher = Slots()
        a, b = CallTools(dispatcher), CallTools(dispatcher)
        await held(a)
        assert await b.dispatch("prepare_demo_booking", {"hold_id": "owned-hold"}) == {
            "error": "not_owned"
        }

    asyncio.run(run())


def test_confirmation_requires_preparation_not_only_owned_hold():
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        await held(state)
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"error": "consent_required"}
        assert not any(name == "confirm_slot_booking" for name, _ in dispatcher.calls)

    asyncio.run(run())


@pytest.mark.parametrize(
    "extra",
    [
        {"consent": True},
        {"approved": True},
        {"user_confirmed": True},
        {"guest_fixture_id": "guest-001"},
        {
            "guest": {
                "firstName": "Real",
                "lastName": "Person",
                "email": "real@example.com",
                "phone": "+37255555555",
            }
        },
        {"guest": {"customerId": 1}},
    ],
)
def test_model_cannot_supply_consent_or_real_guest(extra):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        result = await prepared(state)
        assert result.get("ok"), result
        # Even a genuine approval cannot authorize model-chosen guest data.
        state.observe_user_text(CONSENT)
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold", **extra}
        ) == {"error": "invalid_arguments"}
        assert not any(name == "confirm_slot_booking" for name, _ in dispatcher.calls)

    asyncio.run(run())


def test_consent_before_preparation_or_interim_transcript_is_not_approval():
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        assert callable(
            getattr(state, "observe_user_text", None)
        ), "trusted transcript observation is missing"
        state.observe_user_text(CONSENT)
        assert (await prepared(state)).get("ok")
        state.observe_user_text(CONSENT, is_final=False)
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"error": "consent_required"}
        state.observe_user_text(CONSENT, is_final=True)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["ok"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "Ei, ära kinnita broneeringut.",
        "Jah, aga mitte veel.",
        "Jah.",
        "",
        'Ütle: "Jah, kinnitan selle testbroneeringu."',
        "Jah, kinnitan selle testbroneeringu. Ei, ära tee seda.",
        "Jah, kinnitan selle testbroneeringu?",
    ],
)
def test_decline_or_ambiguous_final_transcript_invalidates_approval(text):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        assert (await prepared(state)).get("ok")
        state.observe_user_text(CONSENT)
        state.observe_user_text(text)
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"error": "consent_required"}
        # An old recap cannot become approved by a later replayed affirmative.
        state.observe_user_text(CONSENT)
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"error": "consent_required"}
        assert not any(name == "confirm_slot_booking" for name, _ in dispatcher.calls)

    asyncio.run(run())


@pytest.mark.parametrize(
    "proposal", ["search_slots", "hold_slot", "prepare_demo_booking"]
)
def test_new_proposal_invalidates_approval(proposal):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        assert (await prepared(state)).get("ok")
        state.observe_user_text(CONSENT)
        args = {
            "search_slots": {"service": "1", "provider": "2", "date": "2026-11-02"},
            "hold_slot": {"slot_id": "actual-slot"},
            "prepare_demo_booking": {"hold_id": "owned-hold"},
        }[proposal]
        await state.dispatch(proposal, args)
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"error": "consent_required"}

    asyncio.run(run())


@pytest.mark.parametrize("expired_before_transcript", [True, False])
def test_preparation_and_approval_expire(expired_before_transcript):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        with patch("app.telephone.time.monotonic", return_value=100):
            assert (await prepared(state)).get("ok")
        with patch(
            "app.telephone.time.monotonic",
            return_value=161 if expired_before_transcript else 101,
        ):
            state.observe_user_text(CONSENT)
        with patch("app.telephone.time.monotonic", return_value=162):
            assert await state.dispatch(
                "confirm_slot_booking", {"hold_id": "owned-hold"}
            ) == {"error": "consent_required"}
        assert not any(name == "confirm_slot_booking" for name, _ in dispatcher.calls)

    asyncio.run(run())


def test_success_retries_replay_without_a_new_write_or_transcript():
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        result = await booked(state)
        count = len(dispatcher.calls)
        state.observe_user_text("Ei, ära tee uut broneeringut.")
        assert (
            await state.dispatch(
                "confirm_slot_booking",
                {"hold_id": "owned-hold", "idempotency_key": "model-key"},
            )
            == result
        )
        assert len(dispatcher.calls) == count
        state.observe_user_text(CANCEL)
        cancellation = await state.dispatch(
            "cancel_slot_booking", {"booking_id": "owned-booking"}
        )
        assert cancellation["ok"]
        count = len(dispatcher.calls)
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
            == cancellation
        )
        assert len(dispatcher.calls) == count

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        CONSENT,
        "Ära tühista testbroneeringut.",
        "Kas sa saad broneeringu tühistada?",
        'Ütle "palun tühista minu testbroneering"',
        "Palun tühista minu testbroneering?",
    ],
)
def test_cancellation_requires_explicit_user_intent_not_model_flags(text):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        await booked(state)
        state.observe_user_text(text)
        assert await state.dispatch(
            "cancel_slot_booking", {"booking_id": "owned-booking"}
        ) == {"error": "cancellation_required"}
        assert await state.dispatch(
            "cancel_slot_booking", {"booking_id": "owned-booking", "consent": True}
        ) == {"error": "invalid_arguments"}
        assert not any(name == "cancel_slot_booking" for name, _ in dispatcher.calls)

    asyncio.run(run())


def test_cancellation_interim_and_stale_intent_do_not_authorize_write():
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        await booked(state)
        state.observe_user_text(CANCEL, is_final=False)
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["error"] == "cancellation_required"
        state.observe_user_text(CANCEL)
        state.observe_user_text("Ei, jäta broneering alles.")
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["error"] == "cancellation_required"
        with patch("app.telephone.time.monotonic", return_value=100):
            state.observe_user_text(CANCEL)
        with patch("app.telephone.time.monotonic", return_value=161):
            assert (
                await state.dispatch(
                    "cancel_slot_booking", {"booking_id": "owned-booking"}
                )
            )["error"] == "cancellation_required"

    asyncio.run(run())


def test_arbitrary_backend_hold_fields_do_not_grant_ownership():
    async def run():
        dispatcher = Slots()

        async def stray(*args):
            return {"hold_id": "foreign"}

        dispatcher.dispatch = stray
        state = CallTools(dispatcher)
        await state.dispatch("get_slot_catalogue", {})
        assert await state.dispatch("confirm_slot_booking", {"hold_id": "foreign"}) == {
            "error": "not_owned"
        }

    asyncio.run(run())


def test_preparation_fails_closed_when_live_catalogue_is_unavailable():
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        await held(state)
        original = dispatcher.dispatch

        async def fail(name, args):
            if name == "get_slot_catalogue":
                raise RuntimeError("backend body with private data")
            return await original(name, args)

        dispatcher.dispatch = fail
        result = await state.dispatch("prepare_demo_booking", {"hold_id": "owned-hold"})
        assert result == {"error": "booking_unavailable"}
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


def test_tool_schemas_do_not_advertise_guest_or_model_consent():
    schemas = {s["name"]: s for s in CallTools(Slots()).schemas}
    assert "prepare_demo_booking" in schemas
    assert "get_demo_profile" in schemas
    confirm = schemas["confirm_slot_booking"]["parameters"]
    assert confirm["required"] == ["hold_id"]
    assert set(confirm["properties"]) == {"hold_id"}
    assert confirm["additionalProperties"] is False


def test_server_call_scope_is_unique_across_parallel_calls():
    async def run():
        dispatcher = Slots()
        a, b = CallTools(dispatcher), CallTools(dispatcher)
        assert a.call_id != b.call_id
        first = await a.dispatch("get_demo_profile", {})
        second = await b.dispatch("get_demo_profile", {})
        assert "guest_fixtures" in first, first
        assert (
            first["guest_fixtures"][0]["guest"]["email"]
            != second["guest_fixtures"][0]["guest"]["email"]
        )
        await booked(a)
        assert (
            dispatcher.calls[-1][1]["guest"]["email"]
            == first["guest_fixtures"][0]["guest"]["email"]
        )

    asyncio.run(run())


def test_server_can_supply_opaque_scope_but_model_cannot_replace_it():
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher, call_id="web-demo-0123456789abcdef")
        assert state.call_id == "web-demo-0123456789abcdef"
        profile = await state.dispatch("get_demo_profile", {})
        assert (
            profile["guest_fixtures"][0]["guest"]["email"]
            == "demo.esimene+web-demo-0123456789abcdef@example.invalid"
        )
        assert await state.dispatch(
            "get_demo_profile", {"call_id": "model-controlled"}
        ) == {"error": "invalid_arguments"}

    asyncio.run(run())


@pytest.mark.parametrize(
    "call_id",
    ["", "real@example.com", "has spaces", "../relative-path", "x" * 49, [], 1],
)
def test_supplied_call_scope_is_validated(call_id):
    with pytest.raises(ValueError, match="invalid call scope"):
        CallTools(Slots(), call_id=call_id)


def test_openai_tool_wrappers_are_copies_of_native_schemas():
    state = CallTools(Slots())
    assert callable(
        getattr(state, "available_tools", None)
    ), "HTTP tool wrapper is missing"
    tools = state.available_tools()
    assert tools == [
        {"type": "function", "function": schema} for schema in state.schemas
    ]
    tools[0]["function"]["parameters"]["required"].clear()
    assert state.schemas[0]["parameters"]["required"]


def test_http_wire_json_arguments_follow_the_same_consent_gate():
    async def run():
        state = CallTools(Slots())
        result = await state.dispatch("get_demo_profile", "{}")
        assert result.get("synthetic") is True, result
        await prepared(state)
        args = json.dumps({"hold_id": "owned-hold"})
        assert await state.dispatch("confirm_slot_booking", args) == {
            "error": "consent_required"
        }
        state.observe_user_text(CONSENT)
        assert (await state.dispatch("confirm_slot_booking", args))["ok"]

    asyncio.run(run())


@pytest.mark.parametrize("args", ["{", "[]", "null", "123", [], None])
def test_malformed_or_non_object_arguments_fail_closed(args):
    async def run():
        dispatcher = Slots()
        assert await CallTools(dispatcher).dispatch("get_demo_profile", args) == {
            "error": "invalid_arguments"
        }
        assert not dispatcher.calls

    asyncio.run(run())


@pytest.mark.parametrize("name", [[], None, 1, "observe_user_text"])
def test_model_cannot_invoke_observer_or_non_string_tools(name):
    async def run():
        assert await CallTools(Slots()).dispatch(name, {}) == {"error": "not_allowed"}

    asyncio.run(run())


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"service": "1", "date": "2026-11-02"},
        {"service": "1", "provider": [], "date": "2026-11-02"},
    ],
)
def test_provider_is_required_at_runtime_not_only_in_schema(args):
    async def run():
        dispatcher = Slots()
        assert await CallTools(dispatcher).dispatch("search_slots", args) == {
            "error": "invalid_arguments"
        }
        assert not dispatcher.calls

    asyncio.run(run())


def test_final_user_text_is_not_retained_in_state():
    state = CallTools(Slots())
    text = "Private guest real@example.com +37255555555 decline"
    state.results.append({"old": "tool result"})
    state.observe_user_text(text)
    assert not state.results
    assert text not in repr(state.__dict__)


@pytest.mark.parametrize(
    "booking", [None, {}, {"id": []}, {"id": [1]}, {"id": True}, {"id": 0}]
)
def test_malformed_success_never_claims_booking_or_ownership(booking):
    async def run():
        dispatcher = Slots()
        original = dispatcher.dispatch

        async def malformed(name, args):
            if name == "confirm_slot_booking":
                return {"ok": True, "booking": booking}
            return await original(name, args)

        dispatcher.dispatch = malformed
        state = CallTools(dispatcher)
        assert (await prepared(state)).get("ok")
        state.observe_user_text(CONSENT)
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"error": "write_outcome_unknown"}
        assert not state.bookings
        assert state.last_booking is None
        assert state.mutation_uncertain

    asyncio.run(run())


def test_ambiguous_result_does_not_grant_booking_ownership():
    async def run():
        dispatcher = Slots()
        original = dispatcher.dispatch

        async def ambiguous(name, args):
            if name == "confirm_slot_booking":
                return {
                    "ok": True,
                    "error": "write_outcome_unknown",
                    "booking": {"id": "claimed"},
                }
            return await original(name, args)

        dispatcher.dispatch = ambiguous
        state = CallTools(dispatcher)
        assert (await prepared(state)).get("ok")
        state.observe_user_text(CONSENT)
        await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        assert not state.bookings

    asyncio.run(run())


def test_successful_hold_cannot_be_prepared_as_a_new_booking():
    async def run():
        state = CallTools(Slots())
        await booked(state)
        assert await state.dispatch(
            "prepare_demo_booking", {"hold_id": "owned-hold"}
        ) == {"error": "already_confirmed"}

    asyncio.run(run())


def test_unknown_write_blocks_retries_and_new_guests_until_operator_readback():
    async def run():
        dispatcher = Slots()
        original = dispatcher.dispatch
        confirmations = []

        async def uncertain(name, args):
            if name == "confirm_slot_booking":
                confirmations.append(copy.deepcopy(args))
                return {"error": "write_outcome_unknown"}
            return await original(name, args)

        dispatcher.dispatch = uncertain
        state = CallTools(dispatcher)
        assert (await prepared(state)).get("ok")
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "write_outcome_unknown"
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "write_outcome_unknown"
        assert len(confirmations) == 1
        assert (
            await state.dispatch(
                "prepare_demo_booking",
                {"hold_id": "owned-hold", "guest_fixture_id": "guest-002"},
            )
        )["error"] == "mutation_outcome_unknown"
        assert (
            await state.dispatch("prepare_demo_booking", {"hold_id": "owned-hold"})
        )["error"] == "mutation_outcome_unknown"
        assert not state.mark_recap_delivered("owned-hold")
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "write_outcome_unknown"
        assert len(confirmations) == 1

    asyncio.run(run())


def test_backend_recap_timezone_is_not_a_currency_word():
    text = (
        "Fiktiivne testbroneering: Live consultation, Demo Provider, "
        "2026-11-02 10:30, ajavöönd Europe/Tallinn, külaline Demo "
        "Esimene. " + CONSENT
    )
    assert safe_speech(text, []) == text
    assert (
        safe_speech("Hind on 120 eurot, ajavöönd Europe/Tallinn.", [])
        == "Ma ei saa praegu hinda kinnitada."
    )


def test_ui_explicit_cancellation_phrase_authorizes_latest_owned_booking():
    async def run():
        state = CallTools(Slots())
        await booked(state)
        state.observe_user_text("Jah, tühista see testbroneering.")
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        ).get("ok") is True

    asyncio.run(run())
