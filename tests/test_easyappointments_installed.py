"""Opt-in real 1.6.0 contract checks; uses synthetic data, never prints credentials.

Run with EASY_LIVE_TESTS=1 plus EASY_BASE_URL and EASY_API_KEY in the environment.
The writable demo instance must be private and notifications disabled.
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("EASY_LIVE_TESTS") != "1",
    reason="private installed backend opt-in required",
)


@pytest.fixture
def api():
    base = os.environ["EASY_BASE_URL"].rstrip("/") + "/index.php/api/v1"
    with httpx.Client(
        base_url=base,
        headers={"Authorization": "Bearer " + os.environ["EASY_API_KEY"]},
        timeout=20,
    ) as client:
        yield client


def future_weekday():
    day = date.today() + timedelta(days=7)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


def test_real_api_auth_validation_and_lifecycle(api):
    assert (
        api.get(
            "/services", headers={"Authorization": "Bearer deliberately-invalid"}
        ).status_code
        == 401
    )
    services = api.get("/services").json()
    providers = api.get("/providers").json()
    service = next(s for s in services if s["name"] == "Demo spa consultation")
    provider = next(p for p in providers if service["id"] in p["services"])
    assert provider["timezone"] == "Europe/Tallinn"
    assert not provider["settings"]["notifications"]
    day = future_weekday()
    params = {"serviceId": service["id"], "providerId": provider["id"], "date": day}
    slots = api.get("/availabilities", params=params).json()
    assert len(slots) >= 2
    assert "12:00" not in slots
    before = api.get("/appointments").json()
    invalid = api.post(
        "/appointments", json={"start": "invalid", "serviceId": service["id"]}
    )
    assert invalid.status_code >= 400
    assert api.get("/appointments").json() == before
    customer = None
    appointment = None
    try:
        response = api.post(
            "/customers",
            json={
                "firstName": "Synthetic",
                "lastName": "Lifecycle",
                "email": "lifecycle-" + uuid.uuid4().hex + "@example.invalid",
                "phone": "+10000000000",
            },
        )
        assert response.status_code == 201
        customer = response.json()["id"]
        payload = {
            "start": day + " " + slots[0] + ":00",
            "serviceId": service["id"],
            "providerId": provider["id"],
            "customerId": customer,
            "notes": "Synthetic API lifecycle verification",
        }
        response = api.post("/appointments", json=payload)
        assert response.status_code == 201
        appointment = response.json()["id"]
        stored = api.get(f"/appointments/{appointment}").json()
        assert stored["serviceId"] == service["id"]
        assert stored["providerId"] == provider["id"]
        assert stored["start"] == payload["start"]
        assert slots[0] not in api.get("/availabilities", params=params).json()
        moved_start = datetime.fromisoformat(day + " " + slots[-1])
        update = api.put(
            f"/appointments/{appointment}",
            json={
                "start": day + " " + slots[-1] + ":00",
                "end": (moved_start + timedelta(minutes=service["duration"])).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "notes": "Synthetic update verification",
            },
        )
        assert update.status_code == 200
        assert (
            api.get(f"/appointments/{appointment}").json()["start"]
            == day + " " + slots[-1] + ":00"
        )
        assert api.delete(f"/appointments/{appointment}").status_code == 204
        assert api.get(f"/appointments/{appointment}").status_code == 404
        assert slots[-1] in api.get("/availabilities", params=params).json()
        appointment = None
    finally:
        if appointment is not None:
            assert api.delete(f"/appointments/{appointment}").status_code in (204, 404)
        if customer is not None:
            assert api.delete(f"/customers/{customer}").status_code in (204, 404)


def test_real_pipeline_catalogue_search_hold_confirm_cancel(api, monkeypatch, tmp_path):
    from app.server import build_stack
    from app.turn import run_turn

    monkeypatch.setenv("EASY_DEMO_WRITES", "1")
    monkeypatch.setenv("EASY_STATE_DB", str(tmp_path / "pipeline.db"))
    stack = build_stack()
    slot = stack["slot"]
    dispatcher = stack["dispatcher"]
    customer = api.post(
        "/customers",
        json={
            "firstName": "Synthetic",
            "lastName": "Pipeline",
            "email": "pipeline-" + uuid.uuid4().hex + "@example.invalid",
            "phone": "+10000000000",
        },
    ).json()["id"]
    booking = None
    key = uuid.uuid4().hex

    class Model:
        step = 0

        def chat(self, messages, tools=None):
            latest = (
                json.loads(messages[-1]["content"])
                if messages[-1]["role"] == "tool"
                else None
            )
            if self.step == 0:
                name, args = "get_slot_catalogue", {}
            elif self.step == 1:
                assert latest["services"] and latest["providers"]
                service = next(
                    s
                    for s in latest["services"]
                    if s["name"] == "Demo spa consultation"
                )
                provider = next(
                    p for p in latest["providers"] if service["id"] in p["services"]
                )
                name, args = (
                    "search_slots",
                    {
                        "service": str(service["id"]),
                        "provider": str(provider["id"]),
                        "date": future_weekday(),
                    },
                )
            elif self.step == 2:
                assert latest["slots"]
                name, args = "hold_slot", {"slot_id": latest["slots"][0]["slotId"]}
            elif self.step == 3:
                name, args = (
                    "confirm_slot_booking",
                    {
                        "hold_id": latest["hold_id"],
                        "guest": {"customerId": customer},
                        "idempotency_key": key,
                    },
                )
            else:
                assert latest["ok"] is True
                return {"content": "Demobroneering kinnitatud."}
            self.step += 1
            return {
                "tool_calls": [
                    {
                        "id": str(self.step),
                        "function": {"name": name, "arguments": args},
                    }
                ]
            }

    class Speaker:
        def synthesize(self, text):
            return b"SYNTHETIC-AUDIO"

    async def exercise():
        nonlocal booking
        result = await run_turn(
            b"",
            None,
            Model(),
            Speaker(),
            dispatcher,
            text="Kinnita sünteetiline konsultatsiooniaeg.",
        )
        assert len(result["tool_results"]) == 4
        assert result["audio"] == b"SYNTHETIC-AUDIO"
        assert not result["fallback_used"]
        outcome = result["tool_results"][-1]["result"]
        assert outcome["ok"] is True
        booking = outcome["booking"]["id"]
        stored = api.get(f"/appointments/{booking}").json()
        assert stored["customerId"] == customer
        assert stored["notes"].startswith("[voicebot vb-")
        cancelled = await dispatcher.dispatch(
            "cancel_slot_booking",
            {"booking_id": str(booking), "idempotency_key": uuid.uuid4().hex},
        )
        assert cancelled["ok"] is True
        assert api.get(f"/appointments/{booking}").status_code == 404

    async def run_and_close():
        try:
            await exercise()
        finally:
            await slot.close()

    try:
        asyncio.run(run_and_close())
    finally:
        if booking is not None:
            assert api.delete(f"/appointments/{booking}").status_code in (204, 404)
        assert api.delete(f"/customers/{customer}").status_code in (204, 404)


def test_real_same_slot_contention_and_commit_timeout_restart(api, tmp_path):
    from app.booking.easyappointments import EasyAppointmentsAdapter

    customer = api.post(
        "/customers",
        json={
            "firstName": "Synthetic",
            "lastName": "Safety",
            "email": "safety-" + uuid.uuid4().hex + "@example.invalid",
            "phone": "+10000000000",
        },
    ).json()["id"]
    created = []
    base = os.environ["EASY_BASE_URL"]
    credential = os.environ["EASY_API_KEY"]
    journal = str(tmp_path / "safety.db")
    adapters = []

    async def exercise():
        first = EasyAppointmentsAdapter(
            base, credential, state_db=journal, allow_writes=True
        )
        second = EasyAppointmentsAdapter(
            base, credential, state_db=journal, allow_writes=True
        )
        adapters.extend([first, second])
        slots = await first.search_slots("1", future_weekday(), "2")
        await second.search_slots("1", future_weekday(), "2")
        holds = [
            await first.create_hold(slots[0]["slotId"]),
            await second.create_hold(slots[0]["slotId"]),
        ]
        results = await asyncio.gather(
            first.confirm(holds[0].hold_id, {"customerId": customer}, uuid.uuid4().hex),
            second.confirm(
                holds[1].hold_id, {"customerId": customer}, uuid.uuid4().hex
            ),
        )
        successes = [r for r in results if r.get("ok")]
        created.extend(r["booking"]["id"] for r in successes)
        assert len(successes) == 1
        assert any(r.get("error") == "slot_stale" for r in results)
        assert (
            len(
                [
                    r
                    for r in api.get("/appointments").json()
                    if r["customerId"] == customer
                ]
            )
            == 1
        )
        hold = await first.create_hold(slots[1]["slotId"])
        key = uuid.uuid4().hex
        original_post = first._http.post

        async def commit_then_timeout(url, **kwargs):
            response = await original_post(url, **kwargs)
            assert response.status_code == 201
            created.append(response.json()["id"])
            raise httpx.ReadTimeout("synthetic committed-write timeout")

        first._http.post = commit_then_timeout
        unknown = await first.confirm(hold.hold_id, {"customerId": customer}, key)
        assert unknown == {"ok": False, "error": "write_outcome_unknown"}
        await first.close()
        restarted = EasyAppointmentsAdapter(
            base, credential, state_db=journal, allow_writes=True
        )
        adapters.append(restarted)
        replay = await restarted.confirm("no-local-hold-after-restart", {}, key)
        assert replay["ok"] is True
        assert replay["booking"]["id"] == created[-1]
        assert (
            len(
                [
                    r
                    for r in api.get("/appointments").json()
                    if r["customerId"] == customer
                ]
            )
            == 2
        )
        assert await restarted.confirm("", {}, key) == replay
        # A fresh interpreter, not merely another object, reads durable replay.
        script = """
import asyncio, os
from app.booking.easyappointments import EasyAppointmentsAdapter
async def main():
    adapter = EasyAppointmentsAdapter(os.environ['EASY_BASE_URL'], os.environ['EASY_API_KEY'], state_db=os.environ['EASY_STATE_DB'], allow_writes=True)
    try:
        result = await adapter.confirm('', {}, os.environ['EASY_REPLAY_KEY'])
        assert result['ok'] is True
        print(result['booking']['id'])
    finally:
        await adapter.close()
asyncio.run(main())
"""
        child_env = os.environ.copy()
        child_env.update(EASY_STATE_DB=journal, EASY_REPLAY_KEY=key)
        child = subprocess.run(
            [sys.executable, "-c", script],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert child.returncode == 0
        assert child.stdout.strip() == str(created[-1])

    async def run_and_close():
        try:
            await exercise()
        finally:
            for adapter in adapters:
                await adapter.close()

    try:
        asyncio.run(run_and_close())
    finally:
        for booking in created:
            assert api.delete(f"/appointments/{booking}").status_code in (204, 404)
        assert api.delete(f"/customers/{customer}").status_code in (204, 404)


def test_real_adapter_creates_customer_from_trusted_guest(api, tmp_path):
    from app.booking.easyappointments import EasyAppointmentsAdapter

    booking = customer = None
    email = "guest-" + uuid.uuid4().hex + "@example.invalid"

    async def exercise():
        nonlocal booking, customer
        adapter = EasyAppointmentsAdapter(
            os.environ["EASY_BASE_URL"],
            os.environ["EASY_API_KEY"],
            state_db=str(tmp_path / "guest.db"),
            allow_writes=True,
        )
        try:
            slots = await adapter.search_slots(
                "Demo spa consultation", future_weekday(), "Demo Therapist"
            )
            hold = await adapter.create_hold(slots[-1]["slotId"])
            result = await adapter.confirm(
                hold.hold_id,
                {"name": "Synthetic Customer", "email": email, "phone": "+10000000000"},
                uuid.uuid4().hex,
            )
            assert result["ok"] is True
            booking = result["booking"]["id"]
            customer = api.get(f"/appointments/{booking}").json()["customerId"]
            stored = api.get(f"/customers/{customer}").json()
            assert stored["firstName"] == "Synthetic"
            assert stored["lastName"] == "Customer"
            assert stored["email"] == email
            assert (await adapter.cancel(str(booking), uuid.uuid4().hex))["ok"] is True
        finally:
            await adapter.close()

    try:
        asyncio.run(exercise())
    finally:
        if booking is not None:
            assert api.delete(f"/appointments/{booking}").status_code in (204, 404)
        # Covers an assertion failure between customer creation and readback.
        customers = [c for c in api.get("/customers").json() if c["email"] == email]
        for item in customers:
            assert api.delete(f"/customers/{item['id']}").status_code in (204, 404)
