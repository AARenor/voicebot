"""Run INSIDE the worker with its shared journal; creates then cleans synthetic data.

docker exec -i livekit-worker-1 python - < deploy/telephony/booking_probe.py
"""

import asyncio
from datetime import date, timedelta
import os

import httpx
from app.booking.easyappointments import EasyAppointmentsAdapter
from app.booking.tools import Dispatcher
from app.telephone import CallTools, sdk_tools, validate_environment


async def main():
    validate_environment()
    base = os.environ["EASY_BASE_URL"].rstrip("/") + os.environ.get(
        "EASY_API_PREFIX", "/index.php/api/v1"
    )
    headers = {
        "Authorization": os.environ.get("EASY_AUTH_SCHEME", "Bearer ")
        + os.environ["EASY_API_KEY"]
    }
    adapter = EasyAppointmentsAdapter(
        os.environ["EASY_BASE_URL"],
        os.environ["EASY_API_KEY"],
        state_db=os.environ["EASY_STATE_DB"],
        auth_scheme=os.environ.get("EASY_AUTH_SCHEME", "Bearer "),
        api_prefix=os.environ.get("EASY_API_PREFIX", "/index.php/api/v1"),
        allow_writes=True,
    )
    state = CallTools(Dispatcher(slot=adapter))
    tools = dict(zip((s["name"] for s in state.schemas), sdk_tools(state)))
    profile = await tools["get_demo_profile"]({})
    day = date.fromisoformat(profile["current_date"]) + timedelta(days=14)
    while day.weekday() > 4:
        day += timedelta(days=1)
    booking = None
    guest_email = next(
        g["guest"]["email"]
        for g in profile["guest_fixtures"]
        if g["fixture_id"] == "guest-001"
    )
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=20) as client:
        try:
            services = (await client.get("/services")).json()
            service = next(s for s in services if s["name"] == "Demo spa consultation")
            catalogue = await tools["get_slot_catalogue"]({})
            provider = next(
                p for p in catalogue["providers"] if service["id"] in p["services"]
            )
            slots = await tools["search_slots"](
                {
                    "service": str(service["id"]),
                    "date": day.isoformat(),
                    "provider": str(provider["id"]),
                }
            )
            assert slots.get("slots"), "no synthetic slots"
            hold = await tools["hold_slot"]({"slot_id": slots["slots"][0]["slotId"]})
            assert hold.get("hold_id"), "hold failed"
            args = {"hold_id": hold["hold_id"]}
            ready = await tools["prepare_demo_booking"](args)
            assert ready.get("ok") and ready["guest"]["email"] == guest_email, (
                "preparation failed"
            )
            assert ready["recap"]["start"] == slots["slots"][0]["start"], (
                "recap mismatch"
            )
            assert (await tools["confirm_slot_booking"](args))[
                "error"
            ] == "consent_required"
            state.observe_user_text("Ei, ära kinnita broneeringut.")
            assert (await tools["confirm_slot_booking"](args))[
                "error"
            ] == "consent_required"
            assert (await tools["prepare_demo_booking"](args)).get("ok"), (
                "repeat preparation failed"
            )
            # Direct SDK synthetic delivery boundary, not a spoken playout proof.
            assert state.render_recap(hold["hold_id"]), "canonical recap missing"
            assert state.mark_recap_delivered(hold["hold_id"]), "recap delivery failed"
            state.observe_user_text("Jah, kinnitan selle testbroneeringu.")
            result = await tools["confirm_slot_booking"](args)
            if isinstance(result.get("booking"), dict) and result["booking"].get("id"):
                booking = str(result["booking"]["id"])
            assert result.get("ok") and booking, "confirmation failed"
            stored = await client.get("/appointments/" + booking)
            assert (
                stored.status_code == 200
                and stored.json()["serviceId"] == service["id"]
            )
            other = CallTools(Dispatcher(slot=adapter))
            assert (
                await other.dispatch("cancel_slot_booking", {"booking_id": booking})
            )["error"] == "not_owned"
            assert (await tools["cancel_slot_booking"]({"booking_id": booking}))[
                "error"
            ] == "cancellation_required"
            state.observe_user_text(
                "Palun tühista broneering, mille just selles kõnes tegime."
            )
            cancel = await tools["cancel_slot_booking"]({"booking_id": booking})
            assert cancel.get("ok"), "owned cancellation failed"
            assert (await client.get("/appointments/" + booking)).status_code == 404
            print(
                "PASS native SDK tools -> shared-journal Easy API prepare/consent/booking/read/cancel; premature writes, decline and foreign-call cancellation rejected"
            )
        finally:
            try:
                if booking:
                    assert (
                        await client.delete("/appointments/" + booking)
                    ).status_code in (204, 404)
            finally:
                try:
                    # Only our unique synthetic email is an ownership proof.
                    response = await client.get("/customers")
                    response.raise_for_status()
                    own = [
                        c["id"]
                        for c in response.json()
                        if c.get("email") == guest_email
                    ]
                    for cid in own:
                        response = await client.get("/appointments")
                        response.raise_for_status()
                        for appointment in response.json():
                            if appointment.get("customerId") == cid:
                                assert (
                                    await client.delete(
                                        "/appointments/" + str(appointment["id"])
                                    )
                                ).status_code in (204, 404)
                        assert (
                            await client.delete("/customers/" + str(cid))
                        ).status_code in (204, 404)
                finally:
                    await adapter.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        raise SystemExit(
            "FAIL synthetic booking probe: "
            + type(exc).__name__
            + " (details withheld)"
        ) from None
