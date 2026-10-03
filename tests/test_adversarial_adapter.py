"""Write receipts, waiting holds and malformed inventory; fake HTTP only."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.booking.base import HoldLedger
from app.booking.easyappointments import EasyAppointmentsAdapter

DAY = "2099-11-02"
GUEST = {
    "firstName": "Demo",
    "lastName": "Fixture",
    "email": "fixture@example.invalid",
    "phone": "+37200000001",
}


class Backend:
    def __init__(self):
        self.times = ["10:30:00"]
        self.duration = 45
        self.create_status, self.customer_status, self.delete_status = 201, 201, 204
        self.appointments, self.calls = [], []

    def __call__(self, request):
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))
        if path.endswith("/availabilities"):
            return httpx.Response(200, json=self.times if not self.appointments else [])
        if path.endswith("/services"):
            return httpx.Response(
                200, json=[{"id": 6, "name": "Fixture", "duration": self.duration}]
            )
        if path.endswith("/providers"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 2,
                        "firstName": "Fixture",
                        "lastName": "Therapist",
                        "services": [6],
                    }
                ],
            )
        if path.endswith("/services/6"):
            return httpx.Response(200, json={"id": 6, "duration": self.duration})
        if path.endswith("/customers") and method == "POST":
            return httpx.Response(self.customer_status, json={"id": 1})
        if path.endswith("/appointments") and method == "POST":
            record = {"id": 42 + self.posts, **body}
            if self.create_status == 201:
                self.appointments.append(record)
            return httpx.Response(self.create_status, json={"id": record["id"]})
        if path.endswith("/appointments") and method == "GET":
            return httpx.Response(200, json=copy.deepcopy(self.appointments))
        if method == "DELETE":
            if self.delete_status in {204, 404}:
                self.appointments = []
            return httpx.Response(self.delete_status)
        raise AssertionError((method, path))

    @property
    def posts(self):
        return sum(
            method == "POST" and path.endswith("/appointments")
            for method, path, _ in self.calls
        )

    @property
    def customers(self):
        return sum(
            method == "POST" and path.endswith("/customers")
            for method, path, _ in self.calls
        )


def adapter(backend, path):
    return EasyAppointmentsAdapter(
        "http://fixture.invalid",
        "fixture",
        transport=httpx.MockTransport(backend),
        state_db=str(path),
        allow_writes=True,
    )


async def hold(api, day=DAY):
    slot = (await api.search_slots("6", day, "2"))[0]
    return await api.create_hold(slot["slotId"])


@pytest.mark.parametrize("status", [200, 202, 302])
def test_uncompleted_creation_cannot_become_cached_success(tmp_path, status):
    async def run():
        backend = Backend()
        backend.create_status = status
        api = adapter(backend, tmp_path / "writes.db")
        try:
            selected = await hold(api)
            assert await api.confirm(selected.hold_id, GUEST, "create") == {
                "ok": False,
                "error": "write_outcome_unknown",
            }
            assert api._journal.get("create")["status"] == "pending_appointment"
            assert not backend.appointments
            assert not (await api.confirm(selected.hold_id, GUEST, "create"))["ok"]
            assert backend.posts == 1
        finally:
            await api.close()

    asyncio.run(run())


@pytest.mark.parametrize("status", [200, 202, 302])
def test_uncompleted_cancel_never_reports_success_or_repeats(tmp_path, status):
    async def run():
        backend = Backend()
        backend.appointments = [{"id": 42}]
        backend.delete_status = status
        api = adapter(backend, tmp_path / "writes.db")
        try:
            result = await api.cancel("42", "cancel")
            assert result == {"ok": False, "error": "write_outcome_unknown"}
            assert await api.cancel("42", "cancel") == result
            assert backend.appointments == [{"id": 42}]
            assert sum(method == "DELETE" for method, _, _ in backend.calls) == 1
        finally:
            await api.close()

    asyncio.run(run())


def test_uncompleted_customer_is_not_replayed_or_followed_by_appointment(tmp_path):
    async def run():
        backend = Backend()
        backend.customer_status = 202
        api = adapter(backend, tmp_path / "writes.db")
        try:
            selected = await hold(api)
            for _ in range(2):
                assert not (await api.confirm(selected.hold_id, GUEST, "create"))["ok"]
            assert backend.customers == 1 and backend.posts == 0
            assert api._journal.get("create")["status"] == "pending_customer"
        finally:
            await api.close()

    asyncio.run(run())


@pytest.mark.parametrize("reason", ["expired", "consumed"])
def test_waiting_new_key_cannot_reuse_invalidated_hold(tmp_path, reason):
    async def run():
        backend = Backend()
        api = adapter(backend, tmp_path / "writes.db")
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            selected = await hold(api)

            @asynccontextmanager
            async def gate():
                entered.set()
                await release.wait()
                yield

            with patch.object(api, "_write_lock", gate()):
                waiting = asyncio.create_task(
                    api.confirm(selected.hold_id, GUEST, "waiter")
                )
                await entered.wait()
                if reason == "expired":
                    api._holds._holds[selected.hold_id].expires_at = 0
                else:
                    api._holds.release(selected.hold_id)
                release.set()
                assert await waiting == {
                    "ok": False,
                    "error": "hold_expired_or_unknown",
                }
            assert backend.posts == 0
        finally:
            await api.close()

    asyncio.run(run())


def test_equivalent_availability_precision_still_confirms(tmp_path):
    async def run():
        backend = Backend()
        api = adapter(backend, tmp_path / "writes.db")
        try:
            selected = await hold(api)
            backend.times = ["10:30"]
            assert (await api.confirm(selected.hold_id, GUEST, "same-time"))["ok"]
            assert backend.posts == 1
        finally:
            await api.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "duration,day", [(10**30, DAY), (1441, DAY), (45, "9999-12-31")]
)
def test_invalid_end_range_has_no_customer_side_effect(tmp_path, duration, day):
    async def run():
        backend = Backend()
        backend.duration = duration
        if day.startswith("9999"):
            backend.times = ["23:59:00"]
        api = adapter(backend, tmp_path / "writes.db")
        try:
            selected = await hold(api, day)
            assert await api.confirm(selected.hold_id, GUEST, "bad-range") == {
                "ok": False,
                "error": "confirm_failed",
            }
            assert backend.posts == 0 and backend.customers == 0
        finally:
            await api.close()

    asyncio.run(run())


def test_new_holds_prune_abandoned_expired_holds_and_bound_live_entries():
    clock = SimpleNamespace(now=10.0)
    with patch("app.booking.base.CLOCK", lambda: clock.now):
        ledger = HoldLedger(ttl_seconds=1)
        ledger._BOUND = 3
        for _ in range(3):
            ledger.create("fixture", None, "", {})
        clock.now = 12
        fresh = ledger.create("fixture", None, "", {})
        assert list(ledger._holds) == [fresh.hold_id]
        for _ in range(10):
            newest = ledger.create("fixture", None, "", {})
        assert len(ledger._holds) == 3
        assert ledger.get(newest.hold_id) is newest
