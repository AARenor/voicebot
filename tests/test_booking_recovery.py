"""Cancellation and known-failure recovery through the real booking stack.

Breaks caught: retaining a consumed hold's replay after cancellation; treating
pre-write reads or a durable failed receipt as an uncertain mutation. Only the
external HTTP transport is replaced; ownership, consent, holds and SQLite run.
"""

import asyncio
import json
import sqlite3

import httpx
import pytest

from app.booking.tools import Dispatcher
from app.telephone import CONSENT_TEXT, UNKNOWN_REPLY, CallTools
from tests.test_adversarial_adapter import GUEST, Backend, adapter, hold

DAY = "2099-11-02"
SEARCH = {"service": "6", "provider": "2", "date": DAY}
CANCEL = "Jah, tühista."


class FailingHTTP(Backend):
    """One external endpoint can reject, time out or return malformed data."""

    def __init__(self):
        super().__init__()
        self.times = ["10:30:00", "11:30:00"]
        self.failures = {}

    def __call__(self, request):
        for (method, suffix), failure in self.failures.items():
            if request.method == method and request.url.path.endswith(suffix):
                body = json.loads(request.content) if request.content else None
                self.calls.append((method, request.url.path, body))
                if failure == "timeout":
                    raise httpx.ReadTimeout("fixture timeout", request=request)
                if failure == "malformed":
                    return httpx.Response(200, content=b"not-json")
                if failure == "invalid_duration":
                    return httpx.Response(200, json={"id": 6, "duration": 0})
                if failure == "invalid_times":
                    return httpx.Response(200, json=["not-a-time"])
                if failure == "malformed_write":
                    return httpx.Response(201, json={"id": "not-an-id"})
                if failure == "committed_timeout":
                    self.appointments.append({"id": 43, **body})
                    raise httpx.ReadTimeout("fixture timeout", request=request)
                return httpx.Response(failure, text="PRIVATE-FIXTURE-BODY")
        return super().__call__(request)


class UniqueEmailHTTP(FailingHTTP):
    """Keep customers after cancellation; duplicate email creation returns 500."""

    def __init__(self):
        super().__init__()
        self.created_customers = {}

    def __call__(self, request):
        if (
            request.method == "POST"
            and request.url.path.endswith("/customers")
            and ("POST", "/customers") not in self.failures
        ):
            body = json.loads(request.content)
            self.calls.append((request.method, request.url.path, body))
            if body["email"] in self.created_customers:
                return httpx.Response(500, text="fixture duplicate email")
            customer = {"id": len(self.created_customers) + 1, **body}
            self.created_customers[body["email"]] = customer
            return httpx.Response(201, json={"id": customer["id"]})
        return super().__call__(request)


async def owned_hold(state, index=0):
    slots = await state.dispatch("search_slots", SEARCH)
    assert "error" not in slots, slots
    return (
        await state.dispatch("hold_slot", {"slot_id": slots["slots"][index]["slotId"]})
    )["hold_id"]


async def prepare(state, hold_id, fixture="guest-001"):
    result = await state.dispatch(
        "prepare_demo_booking", {"hold_id": hold_id, "guest_fixture_id": fixture}
    )
    assert result.get("ok") is True, result
    return result


async def approve_and_confirm(state, hold_id):
    assert state.mark_recap_delivered(hold_id)
    state.observe_user_text(CONSENT_TEXT)
    return await state.dispatch("confirm_slot_booking", {"hold_id": hold_id})


def failed_row(path):
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT idempotency_key, status, result FROM easy_writes"
        ).fetchall()
    connection.close()
    assert len(rows) == 1
    key, status, result = rows[0]
    assert status == "failed"
    return key, json.loads(result)


def test_same_call_cancel_allows_same_slot_rebooking_with_a_fresh_hold(tmp_path):
    async def run():
        backend = FailingHTTP()
        api = adapter(backend, tmp_path / "writes.db")
        dispatcher = Dispatcher(slot=api)
        state, foreign = CallTools(dispatcher), CallTools(dispatcher)
        try:
            original = await owned_hold(state)
            assert await owned_hold(state) == original  # ordinary hold replay
            other = await owned_hold(state, index=1)
            await prepare(state, original)
            assert await approve_and_confirm(state, original) == {
                "ok": True,
                "booking": {"id": 43},
            }
            state.observe_user_text(CANCEL)
            assert await state.dispatch(
                "cancel_slot_booking", {"booking_id": "43"}
            ) == {
                "ok": True,
                "booking_id": "43",
            }
            assert not backend.appointments

            state.observe_user_text("Soovin sama aega uuesti broneerida.")
            assert await owned_hold(state, index=1) == other
            fresh = await owned_hold(state)
            assert fresh != original, "cancelled booking replayed its consumed hold"
            assert await api.confirm(original, {"customerId": 1}, "new-server-key") == {
                "ok": False,
                "error": "hold_expired_or_unknown",
            }
            assert await state.dispatch(
                "prepare_demo_booking", {"hold_id": original}
            ) == {"error": "already_confirmed"}
            assert await state.dispatch(
                "confirm_slot_booking", {"hold_id": original}
            ) == {"error": "already_cancelled"}
            # Replaying the old cancellation cannot evict the new hold.
            assert (await state.dispatch("cancel_slot_booking", {"booking_id": "43"}))[
                "ok"
            ]
            assert await owned_hold(state) == fresh
            before = len(backend.calls)
            for name, args in [
                ("hold_slot", {"slot_id": next(iter(state.slots))}),
                ("prepare_demo_booking", {"hold_id": fresh}),
                ("confirm_slot_booking", {"hold_id": original}),
                ("confirm_slot_booking", {"hold_id": fresh}),
                ("cancel_slot_booking", {"booking_id": "43"}),
            ]:
                assert await foreign.dispatch(name, args) == {"error": "not_owned"}
            assert len(backend.calls) == before

            await prepare(state, fresh, "guest-002")
            # Cancellation consent and the old delivered recap authorize nothing new.
            state.observe_user_text(CONSENT_TEXT)  # the new recap is not delivered
            assert await state.dispatch("confirm_slot_booking", {"hold_id": fresh}) == {
                "error": "consent_required"
            }
            assert backend.posts == 1
            await prepare(state, fresh, "guest-002")
            assert state.mark_recap_delivered(fresh)
            assert await state.dispatch("confirm_slot_booking", {"hold_id": fresh}) == {
                "error": "consent_required"
            }
            assert await approve_and_confirm(state, fresh) == {
                "ok": True,
                "booking": {"id": 44},
            }
            assert [record["id"] for record in backend.appointments] == [44]
            assert backend.posts == 2
            assert sum(method == "DELETE" for method, _, _ in backend.calls) == 1
            assert [receipt["action"] for receipt in state.booking_receipts] == [
                "confirmed",
                "cancelled",
                "confirmed",
            ]
        finally:
            await api.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "endpoint,failure",
    [
        ("/services/6", 401),
        ("/services/6", 429),
        ("/services/6", 503),
        ("/services/6", "timeout"),
        ("/services/6", "malformed"),
        ("/services/6", "invalid_duration"),
        ("/availabilities", 401),
        ("/availabilities", 429),
        ("/availabilities", 503),
        ("/availabilities", "timeout"),
        ("/availabilities", "malformed"),
        ("/availabilities", "invalid_times"),
    ],
)
def test_failed_prewrite_read_is_known_durable_and_does_not_lock_call(
    tmp_path, endpoint, failure
):
    async def run():
        backend = FailingHTTP()
        path = tmp_path / "writes.db"
        api = adapter(backend, path)
        state = CallTools(Dispatcher(slot=api))
        try:
            held = await owned_hold(state)
            await prepare(state, held)
            backend.failures[("GET", endpoint)] = failure
            result = await approve_and_confirm(state, held)
            assert result == {"ok": False, "error": "confirm_failed"}
            assert state.mutation_uncertain is False
            assert state.pending is None
            assert state.guard_reply("Testbroneering on kinnitatud.", [result]) == (
                "Toiming ei õnnestunud; edu ei ole kinnitatud."
            )
            assert backend.customers == backend.posts == 0
            key, receipt = failed_row(path)
            assert receipt == result
            assert "PRIVATE-FIXTURE-BODY" not in path.read_bytes().decode(
                "utf-8", "ignore"
            )

            before = len(backend.calls)
            assert await state.dispatch("confirm_slot_booking", {"hold_id": held}) == {
                "error": "consent_required"
            }
            assert len(backend.calls) == before  # no automatic retry
            backend.failures.clear()
            assert await state.dispatch(
                "prepare_demo_booking",
                {"hold_id": held, "guest_fixture_id": "guest-002"},
            ) == {"error": "guest_fixture_locked"}
            await prepare(state, held)
            before = len(backend.calls)
            assert await approve_and_confirm(state, held) == result
            assert len(backend.calls) == before  # even renewed consent replays failure
            assert state.mutation_uncertain is False

            restarted = adapter(backend, path)
            try:
                assert await restarted.confirm("lost-hold", {}, key) == result
                assert len(backend.calls) == before
            finally:
                await restarted.close()

            # A new, independently prepared owned slot can still be confirmed.
            state.observe_user_text("Soovin teist aega.")
            fresh = await owned_hold(state, index=1)
            assert fresh != held
            await prepare(state, fresh)
            assert await approve_and_confirm(state, fresh) == {
                "ok": True,
                "booking": {"id": 43},
            }
            assert backend.customers == backend.posts == 1
        finally:
            await api.close()

    asyncio.run(run())


@pytest.mark.parametrize("endpoint", ["/customers", "/appointments"])
def test_known_rejected_write_replays_the_same_closed_failure(tmp_path, endpoint):
    async def run():
        backend = FailingHTTP()
        path = tmp_path / "writes.db"
        api = adapter(backend, path)
        state = CallTools(Dispatcher(slot=api))
        try:
            held = await owned_hold(state)
            await prepare(state, held)
            backend.failures[("POST", endpoint)] = 401
            result = await approve_and_confirm(state, held)
            assert result == {"ok": False, "error": "confirm_failed"}
            assert not state.mutation_uncertain
            key, receipt = failed_row(path)
            assert receipt == result
            before = len(backend.calls)
            assert await api.confirm(held, {}, key) == result
            restarted = adapter(backend, path)
            try:
                assert await restarted.confirm("lost-hold", {}, key) == result
            finally:
                await restarted.close()
            assert len(backend.calls) == before
            assert backend.customers == 1
            assert backend.posts == (endpoint == "/appointments")
            assert not backend.appointments
        finally:
            await api.close()

    asyncio.run(run())


def test_stale_slot_failure_replays_without_becoming_uncertain(tmp_path):
    async def run():
        backend = FailingHTTP()
        path = tmp_path / "writes.db"
        api = adapter(backend, path)
        state = CallTools(Dispatcher(slot=api))
        try:
            held = await owned_hold(state)
            await prepare(state, held)
            backend.times = []
            assert await approve_and_confirm(state, held) == {
                "ok": False,
                "error": "slot_stale",
            }
            await prepare(state, held)
            before = len(backend.calls)
            assert await approve_and_confirm(state, held) == {
                "ok": False,
                "error": "slot_stale",
            }
            assert not state.mutation_uncertain
            assert len(backend.calls) == before
            assert backend.customers == backend.posts == 0
        finally:
            await api.close()

    asyncio.run(run())


def test_legacy_failed_journal_replay_is_closed_and_never_retries(tmp_path):
    async def run():
        backend = FailingHTTP()
        path = tmp_path / "writes.db"
        api = adapter(backend, path)
        state = CallTools(Dispatcher(slot=api))
        try:
            held = await owned_hold(state)
            await prepare(state, held)
            backend.times = []
            assert (await approve_and_confirm(state, held))["error"] == "slot_stale"
            key, _ = failed_row(path)
            # Previously persisted failure details are not public result codes.
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE easy_writes SET result=? WHERE idempotency_key=?",
                    (json.dumps({"ok": False, "error": "easy.service: HTTP 401"}), key),
                )
            connection.close()
            await prepare(state, held)
            before = len(backend.calls)
            assert await approve_and_confirm(state, held) == {
                "ok": False,
                "error": "confirm_failed",
            }
            assert not state.mutation_uncertain
            restarted = adapter(backend, path)
            try:
                assert await restarted.confirm("lost-hold", {}, key) == {
                    "ok": False,
                    "error": "confirm_failed",
                }
            finally:
                await restarted.close()
            assert len(backend.calls) == before
            assert backend.customers == backend.posts == 0
        finally:
            await api.close()

    asyncio.run(run())


def test_same_key_waiter_replays_failed_receipt_under_the_real_file_lock(tmp_path):
    async def run():
        backend = FailingHTTP()
        read_started, release_read, waiter_started = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        async def external_http(request):
            if request.method == "GET" and request.url.path.endswith("/services/6"):
                backend.calls.append((request.method, request.url.path, None))
                read_started.set()
                await release_read.wait()
                return httpx.Response(401, text="PRIVATE-FIXTURE-BODY")
            return backend(request)

        path = tmp_path / "writes.db"
        first, second = adapter(external_http, path), adapter(external_http, path)
        try:
            first_slot = (await first.search_slots("6", DAY, "2"))[0]
            second_slot = (await second.search_slots("6", DAY, "2"))[0]
            first_hold = await first.create_hold(first_slot["slotId"])
            second_hold = await second.create_hold(second_slot["slotId"])
            writer = asyncio.create_task(
                first.confirm(first_hold.hold_id, {"customerId": 1}, "same-key")
            )
            await read_started.wait()

            async def wait_for_writer():
                waiter_started.set()
                # No await before confirm's journal read and lock acquisition:
                # both attempts see no receipt until the first read is released.
                return await second.confirm(
                    second_hold.hold_id, {"customerId": 1}, "same-key"
                )

            waiter = asyncio.create_task(wait_for_writer())
            await waiter_started.wait()
            release_read.set()
            assert await asyncio.gather(writer, waiter) == [
                {"ok": False, "error": "confirm_failed"},
                {"ok": False, "error": "confirm_failed"},
            ]
            assert failed_row(path) == (
                "same-key",
                {"ok": False, "error": "confirm_failed"},
            )
            assert (
                sum(path.endswith("/services/6") for _, path, _ in backend.calls) == 1
            )
            assert backend.customers == backend.posts == 0
        finally:
            release_read.set()
            await first.close()
            await second.close()

    asyncio.run(run())


@pytest.mark.parametrize("endpoint", ["/customers", "/appointments"])
@pytest.mark.parametrize("failure", [429, 503, "timeout", "malformed_write", 202])
def test_unknown_post_stays_locked_across_call_retries_and_adapter_restart(
    tmp_path, endpoint, failure
):
    async def run():
        backend = FailingHTTP()
        path = tmp_path / "writes.db"
        api = adapter(backend, path)
        state = CallTools(Dispatcher(slot=api))
        try:
            held = await owned_hold(state)
            await prepare(state, held)
            backend.failures[("POST", endpoint)] = failure
            result = await approve_and_confirm(state, held)
            assert result == {"ok": False, "error": "write_outcome_unknown"}
            assert state.mutation_uncertain
            assert (
                state.guard_reply("Testbroneering on kinnitatud.", [result])
                == UNKNOWN_REPLY
            )
            assert not state.bookings
            before = len(backend.calls)
            state.observe_user_text(CONSENT_TEXT)
            for name, args, error in [
                ("confirm_slot_booking", {"hold_id": held}, "write_outcome_unknown"),
                (
                    "hold_slot",
                    {"slot_id": next(iter(state.slots))},
                    "mutation_outcome_unknown",
                ),
                (
                    "prepare_demo_booking",
                    {"hold_id": held, "guest_fixture_id": "guest-002"},
                    "mutation_outcome_unknown",
                ),
                (
                    "plan_demo_booking",
                    {"date": DAY, "start_time": "11:30"},
                    "mutation_outcome_unknown",
                ),
                ("cancel_slot_booking", {"booking_id": "43"}, "cancel_outcome_unknown"),
            ]:
                assert await state.dispatch(name, args) == {"error": error}
            assert len(backend.calls) == before

            with sqlite3.connect(path) as connection:
                rows = connection.execute(
                    "SELECT idempotency_key, status FROM easy_writes"
                ).fetchall()
            connection.close()
            assert len(rows) == 1
            key, status = rows[0]
            assert status == (
                "pending_customer"
                if endpoint == "/customers"
                else "pending_appointment"
            )
            restarted = adapter(backend, path)
            try:
                assert await restarted.confirm("lost-hold", {}, key) == result
                slots = await restarted.search_slots("6", DAY, "2")
                fresh = await restarted.create_hold(slots[1]["slotId"])
                assert (
                    await restarted.confirm(
                        fresh.hold_id, {"customerId": 1}, "fresh-key"
                    )
                    == result
                )
            finally:
                await restarted.close()
            assert backend.customers == 1
            assert backend.posts == (endpoint == "/appointments")
            assert not backend.appointments
        finally:
            await api.close()

    asyncio.run(run())


def test_uncertain_committed_appointment_reconciles_read_only_but_call_stays_locked(
    tmp_path,
):
    async def run():
        backend = FailingHTTP()
        path = tmp_path / "writes.db"
        api = adapter(backend, path)
        state = CallTools(Dispatcher(slot=api))
        try:
            held = await owned_hold(state)
            await prepare(state, held)
            backend.failures[("POST", "/appointments")] = "committed_timeout"
            assert (await approve_and_confirm(state, held))[
                "error"
            ] == "write_outcome_unknown"
            assert state.mutation_uncertain
            with sqlite3.connect(path) as connection:
                key, status = connection.execute(
                    "SELECT idempotency_key, status FROM easy_writes"
                ).fetchone()
            connection.close()
            assert status == "pending_appointment"
            restarted = adapter(backend, path)
            try:
                assert await restarted.confirm("lost-hold", {}, key) == {
                    "ok": True,
                    "booking": {"id": 43},
                }
                assert await restarted.confirm("lost-hold", {}, key) == {
                    "ok": True,
                    "booking": {"id": 43},
                }
            finally:
                await restarted.close()
            assert backend.customers == backend.posts == 1
            assert [record["id"] for record in backend.appointments] == [43]
            assert state.mutation_uncertain
            assert await state.dispatch("confirm_slot_booking", {"hold_id": held}) == {
                "error": "write_outcome_unknown"
            }
        finally:
            await api.close()

    asyncio.run(run())


@pytest.mark.parametrize("fixture", ["guest-001", "guest-002"])
def test_unique_email_same_call_rebooking_reuses_only_the_exact_guest(
    tmp_path, fixture
):
    async def run():
        backend = UniqueEmailHTTP()
        api = adapter(backend, tmp_path / "writes.db")
        state = CallTools(Dispatcher(slot=api))
        try:
            original = await owned_hold(state)
            await prepare(state, original)
            assert (await approve_and_confirm(state, original))["ok"]
            state.observe_user_text(CANCEL)
            assert (await state.dispatch("cancel_slot_booking", {"booking_id": "43"}))[
                "ok"
            ]
            assert not backend.appointments and len(backend.created_customers) == 1

            state.observe_user_text("Soovin sama aega uuesti broneerida.")
            fresh = await owned_hold(state)
            assert fresh != original
            await prepare(state, fresh, fixture)
            assert await state.dispatch("confirm_slot_booking", {"hold_id": fresh}) == {
                "error": "consent_required"
            }
            assert backend.customers == backend.posts == 1
            result = await approve_and_confirm(state, fresh)
            assert result == {"ok": True, "booking": {"id": 44}}
            assert not state.mutation_uncertain
            assert backend.posts == 2
            expected_customers = 1 if fixture == "guest-001" else 2
            assert (
                backend.customers
                == len(backend.created_customers)
                == expected_customers
            )
            assert backend.appointments[0]["customerId"] == expected_customers
            assert [item["action"] for item in state.booking_receipts] == [
                "confirmed",
                "cancelled",
                "confirmed",
            ]
        finally:
            await api.close()

    asyncio.run(run())


@pytest.mark.parametrize("field", ["clean", "firstName", "lastName", "email", "phone"])
def test_customer_reuse_requires_all_four_clean_guest_fields(tmp_path, field):
    async def run():
        backend = UniqueEmailHTTP()
        api = adapter(backend, tmp_path / "writes.db")
        try:
            original = await hold(api)
            assert (await api.confirm(original.hold_id, GUEST, "first"))["ok"]
            assert (await api.cancel("43", "cancel"))["ok"]
            changed = {key: " " + value + " " for key, value in GUEST.items()}
            if field != "clean":
                changed = {
                    **GUEST,
                    field: {
                        "firstName": "Other",
                        "lastName": "Other",
                        "email": "other@example.invalid",
                        "phone": "+37200000002",
                    }[field],
                }
            fresh = await hold(api)
            result = await api.confirm(fresh.hold_id, changed, "second")
            if field in {"clean", "email"}:
                assert result["ok"] and backend.posts == 2
                assert backend.customers == (1 if field == "clean" else 2)
                assert backend.appointments[0]["customerId"] == backend.customers
            else:
                assert result == {"ok": False, "error": "write_outcome_unknown"}
                assert backend.customers == 2 and backend.posts == 1
        finally:
            await api.close()

    asyncio.run(run())


def test_customer_reuse_is_not_shared_between_calls(tmp_path):
    async def run():
        backend = UniqueEmailHTTP()
        api = adapter(backend, tmp_path / "writes.db")
        first, second = CallTools(Dispatcher(slot=api)), CallTools(Dispatcher(slot=api))
        try:
            for state in (first, second):
                selected = await owned_hold(state)
                await prepare(state, selected)
                result = await approve_and_confirm(state, selected)
                assert result["ok"]
                state.observe_user_text(CANCEL)
                assert (
                    await state.dispatch(
                        "cancel_slot_booking",
                        {"booking_id": str(result["booking"]["id"])},
                    )
                )["ok"]
            assert backend.customers == backend.posts == 2
            assert len(backend.created_customers) == 2
            assert {record["id"] for record in backend.created_customers.values()} == {
                1,
                2,
            }
        finally:
            await api.close()

    asyncio.run(run())


def test_explicit_customer_id_does_not_seed_exact_guest_reuse(tmp_path):
    async def run():
        backend = UniqueEmailHTTP()
        api = adapter(backend, tmp_path / "writes.db")
        try:
            original = await hold(api)
            assert (
                await api.confirm(
                    original.hold_id, {**GUEST, "customerId": 99}, "first"
                )
            )["ok"]
            assert backend.customers == 0
            assert (await api.cancel("43", "cancel"))["ok"]
            fresh = await hold(api)
            assert (await api.confirm(fresh.hold_id, GUEST, "second"))["ok"]
            assert backend.customers == 1
            assert backend.appointments[0]["customerId"] == 1
        finally:
            await api.close()

    asyncio.run(run())


def test_proven_customer_reuse_does_not_retry_a_known_failed_booking_key(tmp_path):
    async def run():
        backend = UniqueEmailHTTP()
        api = adapter(backend, tmp_path / "writes.db")
        try:
            original = await hold(api)
            backend.failures[("POST", "/appointments")] = 401
            failure = await api.confirm(original.hold_id, GUEST, "failed")
            assert failure == {"ok": False, "error": "confirm_failed"}
            assert backend.customers == backend.posts == 1
            backend.failures.clear()
            before = len(backend.calls)
            assert await api.confirm(original.hold_id, GUEST, "failed") == failure
            assert len(backend.calls) == before
            fresh = await hold(api)
            assert (await api.confirm(fresh.hold_id, GUEST, "fresh"))["ok"]
            assert backend.customers == 1 and backend.posts == 2
            assert backend.appointments[0]["customerId"] == 1
        finally:
            await api.close()

    asyncio.run(run())


def test_cached_customer_cannot_bypass_a_later_unknown_customer_write(tmp_path):
    async def run():
        backend = UniqueEmailHTTP()
        api = adapter(backend, tmp_path / "writes.db")
        try:
            original = await hold(api)
            assert (await api.confirm(original.hold_id, GUEST, "first"))["ok"]
            assert (await api.cancel("43", "cancel"))["ok"]
            fresh = await hold(api)
            backend.failures[("POST", "/customers")] = 500
            failure = await api.confirm(
                fresh.hold_id, {**GUEST, "email": "other@example.invalid"}, "unknown"
            )
            assert failure == {"ok": False, "error": "write_outcome_unknown"}
            backend.failures.clear()
            before = len(backend.calls)
            assert await api.confirm(fresh.hold_id, GUEST, "new-key") == failure
            assert await api.confirm(fresh.hold_id, GUEST, "unknown") == failure
            assert len(backend.calls) == before
            assert backend.customers == 2 and backend.posts == 1
        finally:
            await api.close()

    asyncio.run(run())


def test_exact_guest_customer_proof_is_adapter_local(tmp_path):
    async def run():
        backends = [UniqueEmailHTTP(), UniqueEmailHTTP()]
        apis = [
            adapter(backend, tmp_path / f"writes-{index}.db")
            for index, backend in enumerate(backends)
        ]
        try:
            for api, backend in zip(apis, backends):
                selected = await hold(api)
                assert (await api.confirm(selected.hold_id, GUEST, "first"))["ok"]
                assert backend.customers == 1
                assert len(backend.created_customers) == 1
            assert backends[0].created_customers == backends[1].created_customers
        finally:
            for api in apis:
                await api.close()

    asyncio.run(run())
