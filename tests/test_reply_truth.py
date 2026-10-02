"""Only current server execution truth may reach shared demo speech."""

import asyncio
import base64
import json
from unittest.mock import patch

import httpx
import pytest

from app.booking.easyappointments import EasyAppointmentsAdapter
from app.booking.tools import Dispatcher
from app.telephone import CallTools, FALLBACK, GREETING
from tests.test_product_demo import (
    BookingLlm,
    SimpleLlm,
    call,
    client,
    install_backend,
    send,
    start,
)
from tests.test_telephone import CANCEL, CONSENT, Slots, booked, prepared


CONFIRMED = "Testbroneering on kinnitatud."
CANCELLED = "Testbroneering on tühistatud."
EXISTING = "See testbroneering on juba kinnitatud. Uut broneeringut ei loodud."
UNVERIFIED = (
    "Edu ei ole kinnitatud. Kontrolli testbroneeringu tulemust taustsüsteemist."
)
UNKNOWN = (
    "Toimingu tulemus on ebaselge. Edu ei ole kinnitatud. "
    "Ära korda toimingut; kontrolli taustsüsteemi."
)
ASK_DATE_TIME = "Mis kuupäevaks ja kellaajaks soovid testbroneeringut?"


@pytest.mark.parametrize(
    "prose",
    [
        "Sinu testbroneering on edukalt loodud.",
        "Panin sulle aja kirja.",
        "Broneerisin sulle uue aja reedeks kell 11:00.",
        "Your appointment has been successfully created.",
        "Spaa asub Tallinnas ja ootab sind homme.",
        "Suunasin sind päris klienditeenindajale.",
    ],
)
def test_unapproved_prose_without_tools_is_never_execution_truth(prose):
    state = CallTools(Slots())
    assert state.guard_reply(prose, []) == UNVERIFIED
    assert not state.bookings and not state.dispatcher.calls


def test_http_zero_tool_paraphrase_is_guarded_before_tts(client):
    prose = "Sinu testbroneering on edukalt loodud."
    client.app.state.stack["llm_primary"] = SimpleLlm(prose)
    result = send(client, start(client), "Soovin testbroneeringut").json()
    assert result["reply"] == UNVERIFIED
    assert result["tools_used"] == 0
    assert result["booking_ids"] == result["booking_changes"] == []
    assert client.app.state.stack["tts"].spoken[-1] == result["reply"]
    assert base64.b64decode(result["audio_b64"]).decode() == result["reply"]


def test_http_old_booking_does_not_license_a_zero_tool_new_booking_claim(
    client, tmp_path
):
    day, records, writes = install_backend(client, tmp_path)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    session = start(client)
    assert send(client, session, "Soovin testbroneeringut").status_code == 200
    assert send(client, session, CONSENT).json()["booking_ids"] == ["42"]
    client.app.state.stack["llm_primary"] = SimpleLlm(
        "Broneerisin sulle uue aja reedeks kell 11:00."
    )
    result = send(client, session, "Soovin teist aega.").json()
    assert result["reply"] == UNVERIFIED
    assert result["tools_used"] == 0 and result["booking_changes"] == []
    assert len(records) == 1
    assert (
        sum(r.method == "POST" and r.url.path.endswith("/appointments") for r in writes)
        == 1
    )


def test_native_reply_and_transcription_share_zero_tool_truth_guard():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent

    async def run():
        agent = TelephoneAgent(CallTools(Slots()))

        async def text():
            yield "Sinu testbroneering on "
            yield "edukalt loodud."

        assert await agent.checked_reply(text()) == UNVERIFIED
        assert [part async for part in agent.transcription_node(text(), None)] == [
            UNVERIFIED
        ]
        spoken = []

        async def synthesize(agent, stream, settings):
            async for part in stream:
                spoken.append(part)
            yield "fixture-frame"

        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            assert [frame async for frame in agent.tts_node(text(), None)] == [
                "fixture-frame"
            ]
        assert spoken == [UNVERIFIED]

    asyncio.run(run())


def test_historical_booking_and_supplied_old_result_do_not_license_new_prose():
    async def run():
        state = CallTools(Slots())
        old = await booked(state)
        state.observe_user_text("Soovin teist aega reedeks kell üksteist.")
        for results in ([], [old], [{"result": old}]):
            assert (
                state.guard_reply(
                    "Broneerisin sulle uue aja reedeks kell 11:00.", results
                )
                == UNVERIFIED
            )
        assert (
            sum(name == "confirm_slot_booking" for name, _ in state.dispatcher.calls)
            == 1
        )

    asyncio.run(run())


def test_current_receipt_ignores_model_mutation_prose_and_resets_only_on_final_turn():
    async def run():
        state = CallTools(Slots())
        await booked(state)
        prose = "Broneerisin sulle uue aja reedeks kell 11:00."
        assert state.guard_reply(prose, []) == CONFIRMED
        assert state.guard_reply("Tere!", []) == CONFIRMED
        state.observe_user_text("Uus osaline transkriptsioon", is_final=False)
        assert state.guard_reply(prose, []) == CONFIRMED
        state.observe_user_text("Uus lõpetatud kasutajavoor", is_final=True)
        assert state.guard_reply(prose, []) == UNVERIFIED

    asyncio.run(run())


def test_previous_turn_late_completion_cannot_create_a_current_turn_receipt():
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        state.observe_user_text(CONSENT)
        started, finish = asyncio.Event(), asyncio.Event()
        original = state.dispatcher.dispatch

        async def delayed(name, args):
            started.set()
            await finish.wait()
            return await original(name, args)

        state.dispatcher.dispatch = delayed
        task = asyncio.create_task(
            state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )
        await started.wait()
        state.observe_user_text("Soovin uut aega reedeks kell üksteist.")
        finish.set()
        assert (await task)["ok"] is True
        assert state.bookings == {"owned-booking"}
        assert (
            state.guard_reply("Broneerisin sulle uue aja reedeks kell 11:00.", [])
            == UNVERIFIED
        )

    asyncio.run(run())


def test_cancelled_inflight_mutation_preserves_sdk_cancellation_and_marks_unknown():
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        state.observe_user_text(CONSENT)
        attempts = []

        async def cancelled(name, args):
            attempts.append(name)
            raise asyncio.CancelledError

        state.dispatcher.dispatch = cancelled
        with pytest.raises(asyncio.CancelledError):
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        assert state.outcome == "write_outcome_unknown"
        state.observe_user_text("Kas kõik õnnestus?")
        assert state.guard_reply(CONFIRMED, []) == UNKNOWN
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "write_outcome_unknown"
        assert attempts == ["confirm_slot_booking"]

    asyncio.run(run())


def test_cached_active_confirmation_reports_existing_not_a_new_write():
    async def run():
        state = CallTools(Slots())
        original = await booked(state)
        state.observe_user_text("Ei, ära tee uut broneeringut.")
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
            == original
        )
        assert (
            state.guard_reply("Broneerisin sulle uue aja.", state.results) == EXISTING
        )
        assert (
            sum(name == "confirm_slot_booking" for name, _ in state.dispatcher.calls)
            == 1
        )

    asyncio.run(run())


def test_actual_cancel_receipt_cannot_be_rendered_as_model_confirmation():
    async def run():
        state = CallTools(Slots())
        await booked(state)
        state.observe_user_text(CANCEL)
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["ok"]
        assert (
            state.guard_reply("Broneerisin sulle uue aja.", state.results) == CANCELLED
        )
        state.observe_user_text("Kas tegid veel midagi?")
        assert state.guard_reply(CANCELLED, []) == UNVERIFIED
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"error": "already_cancelled"}

    asyncio.run(run())


@pytest.mark.parametrize("name", ["confirm_slot_booking", "cancel_slot_booking"])
def test_dispatch_exception_is_typed_sticky_unknown_and_blocks_every_later_write(name):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        if name == "confirm_slot_booking":
            await prepared(state)
            state.observe_user_text(CONSENT)
            args, error = {"hold_id": "owned-hold"}, "write_outcome_unknown"
        else:
            await booked(state)
            state.observe_user_text(CANCEL)
            args, error = {"booking_id": "owned-booking"}, "cancel_outcome_unknown"
        attempts = []
        original = dispatcher.dispatch

        async def uncertain(tool, arguments):
            if tool == name:
                attempts.append(tool)
                raise httpx.ReadTimeout("fixture transport lost after commit")
            return await original(tool, arguments)

        dispatcher.dispatch = uncertain
        assert await state.dispatch(name, args) == {"error": error}
        assert state.guard_reply(CONFIRMED, []) == UNKNOWN
        state.observe_user_text(CONSENT)
        assert (await state.dispatch("get_demo_profile", {}))["synthetic"] is True
        assert (await state.dispatch("get_demo_profile", {"extra": True}))[
            "error"
        ] == "invalid_arguments"
        assert state.outcome == "write_outcome_unknown"
        assert state.guard_reply("Tere!", []) == UNKNOWN
        assert await state.dispatch(name, args) == {"error": error}
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "write_outcome_unknown"
        assert (
            await state.dispatch("prepare_demo_booking", {"hold_id": "owned-hold"})
        )["error"] == "mutation_outcome_unknown"
        assert (
            await state.dispatch(
                "plan_demo_booking", {"date": "2099-11-02", "start_time": "10:30"}
            )
        )["error"] == "mutation_outcome_unknown"
        assert attempts == [name]
        assert state.pending is None

    asyncio.run(run())


@pytest.mark.parametrize("name", ["confirm_slot_booking", "cancel_slot_booking"])
def test_backend_unavailable_mutation_result_is_conservatively_unknown(name):
    async def run():
        state = CallTools(Slots())
        if name == "confirm_slot_booking":
            await prepared(state)
            state.observe_user_text(CONSENT)
            args, error = {"hold_id": "owned-hold"}, "write_outcome_unknown"
        else:
            await booked(state)
            state.observe_user_text(CANCEL)
            args, error = {"booking_id": "owned-booking"}, "cancel_outcome_unknown"

        async def unavailable(tool, arguments):
            return {"error": "booking_unavailable"}

        state.dispatcher.dispatch = unavailable
        assert await state.dispatch(name, args) == {"error": error}
        state.observe_user_text("Kas kõik õnnestus?")
        assert state.guard_reply(CONFIRMED, []) == UNKNOWN

    asyncio.run(run())


def test_known_rejection_is_not_mistaken_for_an_uncertain_committed_write():
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        state.observe_user_text(CONSENT)

        async def stale(tool, arguments):
            return {"ok": False, "error": "slot_stale"}

        state.dispatcher.dispatch = stale
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"ok": False, "error": "slot_stale"}
        assert (
            state.guard_reply(CONFIRMED, [])
            == "Toiming ei õnnestunud; edu ei ole kinnitatud."
        )
        state.observe_user_text("Kas see on päris spaa?")
        faq = state.demo["faq"][0]["answer_et"]
        assert state.guard_reply(faq, []) == faq
        assert state.outcome == "booking_unavailable"

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,result",
    [
        ("confirm_slot_booking", None),
        ("confirm_slot_booking", {}),
        ("confirm_slot_booking", {"ok": True}),
        ("confirm_slot_booking", {"ok": True, "booking": {"id": True}}),
        ("confirm_slot_booking", {"ok": False}),
        ("confirm_slot_booking", {"ok": True, "error": "slot_stale"}),
        ("cancel_slot_booking", None),
        ("cancel_slot_booking", {}),
        ("cancel_slot_booking", {"ok": False}),
        ("cancel_slot_booking", {"ok": True, "booking_id": "foreign"}),
    ],
)
def test_malformed_mutation_response_is_unknown_not_safe_to_retry(name, result):
    async def run():
        dispatcher = Slots()
        state = CallTools(dispatcher)
        if name == "confirm_slot_booking":
            await prepared(state)
            state.observe_user_text(CONSENT)
            args, error = {"hold_id": "owned-hold"}, "write_outcome_unknown"
        else:
            await booked(state)
            state.observe_user_text(CANCEL)
            args, error = {"booking_id": "owned-booking"}, "cancel_outcome_unknown"
        original = dispatcher.dispatch

        async def malformed(tool, arguments):
            return result if tool == name else await original(tool, arguments)

        dispatcher.dispatch = malformed
        assert await state.dispatch(name, args) == {"error": error}
        state.observe_user_text("Jah, kinnitan selle testbroneeringu.")
        assert state.guard_reply(CONFIRMED, []) == UNKNOWN
        assert state.outcome == "write_outcome_unknown"
        assert await state.dispatch(name, args) == {"error": error}

    asyncio.run(run())


def test_every_exact_approved_faq_and_static_greeting_remains_usable():
    state = CallTools(Slots())
    for text in [GREETING, FALLBACK, "Tere!", ASK_DATE_TIME] + [
        entry["answer_et"] for entry in state.demo["faq"]
    ]:
        assert state.guard_reply(text, []) == text
    faq = state.demo["faq"][0]["answer_et"]
    assert state.guard_reply(faq + " Panin sulle aja kirja.", []) == UNVERIFIED


@pytest.mark.parametrize("delivered", [False, True])
def test_pending_always_uses_canonical_recap_not_model_success_prose(delivered):
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        state.pending["delivery"] = delivered
        canonical = state.render_recap()
        assert (
            state.guard_reply("Sinu testbroneering on edukalt loodud.", []) == canonical
        )
        assert state.pending is not None
        assert state.pending["delivery"] is delivered

    asyncio.run(run())


def test_money_guard_still_blocks_model_and_canonical_recap_prices():
    async def run():
        state = CallTools(Slots())
        assert (
            state.guard_reply("See maksab sada eurot.", [])
            == "Ma ei saa praegu hinda kinnitada."
        )
        await prepared(state)
        state.pending["recap"]["service_name"] = "Konsultatsioon 120 EUR"
        assert state.guard_reply("Tere!", []) == "Ma ei saa praegu hinda kinnitada."
        assert state.pending is None
        assert state.mark_recap_delivered("owned-hold") is False
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


def test_http_committed_delete_timeout_stays_unknown_next_turn_and_blocks_retry(
    client, tmp_path
):
    day, records, mutations = "2099-11-02", [], []

    def handler(request):
        path = request.url.path
        if request.method in {"POST", "DELETE"}:
            mutations.append(request.method + " " + path)
        if path.endswith("/services"):
            return httpx.Response(
                200, json=[{"id": 6, "name": "Fixture consultation", "duration": 60}]
            )
        if path.endswith("/providers"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 2,
                        "firstName": "Demo",
                        "lastName": "Provider",
                        "services": [6],
                        "timezone": "Europe/Tallinn",
                    }
                ],
            )
        if path.endswith("/availabilities"):
            return httpx.Response(200, json=["10:00"] if not records else [])
        if path.endswith("/services/6"):
            return httpx.Response(200, json={"duration": 60})
        if path.endswith("/customers"):
            return httpx.Response(201, json={"id": 9})
        if path.endswith("/appointments"):
            if request.method == "POST":
                records.append({"id": 42, **json.loads(request.content)})
                return httpx.Response(201, json={"id": 42})
            return httpx.Response(200, json=records)
        if path.endswith("/appointments/42") and request.method == "DELETE":
            records.clear()
            raise httpx.ReadTimeout("fixture reply lost after deletion")
        raise AssertionError("unexpected fixture operation")

    adapter = EasyAppointmentsAdapter(
        "https://fixture.invalid",
        "fixture",
        transport=httpx.MockTransport(handler),
        state_db=str(tmp_path / "writer.db"),
        allow_writes=True,
    )
    client.app.state.stack.update(
        slot=adapter, booking_reader=adapter, dispatcher=Dispatcher(slot=adapter)
    )
    model = BookingLlm(day)
    client.app.state.stack["llm_primary"] = model
    session = start(client)
    assert send(client, session, "Soovin testbroneeringut").status_code == 200
    assert send(client, session, CONSENT).json()["booking_ids"] == ["42"]
    assert records

    class CancelLlm:
        def chat(self, messages, tools=None):
            if messages[-1]["role"] != "tool":
                return call("cancel_slot_booking", {"booking_id": "42"})
            return {"content": CONFIRMED}

    client.app.state.stack["llm_primary"] = CancelLlm()
    with patch("app.callslog.log_call") as log:
        cancelled = send(client, session, CANCEL).json()
    assert not records
    assert cancelled["outcome"] == "unknown_outcome"
    assert cancelled["booking_changes"] == []
    assert log.call_args.args[4] == "unknown_outcome"
    state = client.app.state.demo_sessions.sessions[session].tools
    assert state.outcome == "write_outcome_unknown"
    client.app.state.stack["llm_primary"] = SimpleLlm(CONFIRMED)
    with patch("app.callslog.log_call") as log:
        followup = send(client, session, "Kas broneering on alles?").json()
    assert followup["reply"] == UNKNOWN
    assert followup["outcome"] == "unknown_outcome"
    assert followup["booking_changes"] == []
    assert log.call_args.args[4] == "unknown_outcome"
    assert client.app.state.stack["tts"].spoken[-1] == UNKNOWN
    client.app.state.stack["llm_primary"] = CancelLlm()
    assert send(client, session, CANCEL).json()["outcome"] == "unknown_outcome"
    assert sum(m.startswith("DELETE ") for m in mutations) == 1
    assert (
        sum(m.startswith("POST ") and m.endswith("/appointments") for m in mutations)
        == 1
    )
