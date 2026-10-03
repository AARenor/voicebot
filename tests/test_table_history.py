"""Table history contains validated receipt/date/time metadata, not guest data."""

import asyncio
import json

import pytest

from app import call_history, callslog
from app.languages import CONSENT
from tests.test_table_policy import prepare_table, table_state

CALL = "a" * 32
RECEIPT = {
    "id": "table_" + "c" * 32,
    "kind": "table",
    "action": "confirmed",
    "date": "2026-10-10",
    "start_local": "2026-10-10 18:30:00",
    "timezone": "Europe/Tallinn",
}


def test_table_history_preserves_kind_and_owned_cancellation_without_private_fields():
    db = callslog.open_log()
    try:
        call_history.start(db, CALL, "telephone")
        call_history.record_result(
            db,
            CALL,
            "booking_confirmed",
            changes=[
                {
                    **RECEIPT,
                    "guest_name": "PRIVATE",
                    "email": "private@example.invalid",
                    "transcript": "PRIVATE",
                }
            ],
        )
        bookings = call_history.detail(db, CALL)["session"]["bookings"]
        assert len(bookings) == 1 and bookings[0]["kind"] == "table"
        assert bookings[0]["start_local"] == RECEIPT["start_local"]
        assert "PRIVATE" not in json.dumps(call_history.detail(db, CALL))
        call_history.record_result(
            db, CALL, "booking_cancelled", changes=[{**RECEIPT, "action": "cancelled"}]
        )
        assert (
            call_history.detail(db, CALL)["session"]["bookings"][0]["action"]
            == "cancelled"
        )
    finally:
        db.close()


@pytest.mark.parametrize(
    "change",
    [
        {"id": "stay_" + "c" * 32},
        {"id": "42"},
        {"id": "table_wrong"},
        {"date": "2026-1-1"},
        {"start_local": "2026-10-11 18:30:00"},
        {"start_local": "2026-10-10T18:30:00+03:00"},
        {"start_local": "2026-10-10 18:30:01"},
        {"timezone": "UTC"},
    ],
)
def test_invalid_table_history_receipt_is_not_a_booking_link(change):
    db = callslog.open_log()
    try:
        call_history.start(db, CALL, "telephone")
        call_history.record_result(
            db, CALL, "booking_confirmed", changes=[{**RECEIPT, **change}]
        )
        assert call_history.detail(db, CALL)["session"]["bookings"] == []
    finally:
        db.close()


def test_table_policy_records_private_free_history_immediately_after_write(monkeypatch):
    db = callslog.open_log()
    monkeypatch.setattr(callslog, "get_default", lambda: db)
    try:

        async def run():
            state, _ = table_state()
            state.history_enabled = True
            call_history.start(db, state.call_id, "telephone")
            ready = await prepare_table(state)
            state.mark_recap_delivered(ready["hold_id"])
            state.observe_user_text(CONSENT["et"])
            confirmed = await state.dispatch(
                "confirm_table_booking", {"hold_id": ready["hold_id"]}
            )
            bookings = call_history.detail(db, state.call_id)["session"]["bookings"]
            assert (
                bookings[0]["id"] == confirmed["booking_id"]
                and bookings[0]["kind"] == "table"
            )
            assert bookings[0]["date"] == ready["recap"]["date"]
            assert bookings[0]["start_local"].endswith("18:30:00")
            assert not any(
                word in json.dumps(bookings)
                for word in (
                    "Demo Esimene",
                    "example.invalid",
                    "guest_name",
                    "transcript",
                )
            )

        asyncio.run(run())
    finally:
        db.close()
