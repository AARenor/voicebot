"""Restaurant recovery keeps durable ownership and requires fresh consent."""

import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest

from app.booking import demo_table
from app.booking.demo_table import DemoTableAdapter
from app.booking.tools import Dispatcher
from app.languages import CONSENT
from app.telephone import CallTools
from tests.test_table_policy import REQUEST, prepare_table


def test_expired_table_hold_renews_owned_offer_and_concurrent_retries_share_one_hold(
    tmp_path, monkeypatch
):
    epoch = [time.time()]
    # Freeze only this adapter's wall clock; policy/event-loop monotonic time
    # stays real, including the durable hold's expiry conversion.
    monkeypatch.setattr(
        demo_table,
        "time",
        SimpleNamespace(time=lambda: epoch[0], monotonic=time.monotonic),
    )
    database = str(tmp_path / "tables.db")

    async def run():
        backend = DemoTableAdapter(database, hold_ttl_seconds=1, offer_ttl_seconds=600)
        state = CallTools(Dispatcher(table=backend, business="restaurant"))
        found = await state.dispatch("search_tables", REQUEST)
        offer_id = found["offers"][0]["table_offer_id"]
        args = {"table_offer_id": offer_id}
        first = await state.dispatch("hold_table", args)
        assert "error" not in first, first
        old_hold = first["hold_id"]
        assert await backend.get_hold(old_hold) is not None

        epoch[0] += 2
        assert await backend.get_hold(old_hold) is None
        with sqlite3.connect(database) as db:
            offer_expiry = db.execute(
                "SELECT expires_at FROM table_offers WHERE id=?", (offer_id,)
            ).fetchone()[0]
        assert offer_expiry > epoch[0]

        renewed = await asyncio.gather(
            *(state.dispatch("hold_table", args) for _ in range(4))
        )
        assert all("error" not in result for result in renewed), renewed
        renewed_ids = {result["hold_id"] for result in renewed}
        assert len(renewed_ids) == 1
        new_hold = renewed_ids.pop()
        assert new_hold != old_hold
        assert new_hold in state.holds and new_hold in state.held_tables
        assert state.held_tables[new_hold]["table_offer_id"] == offer_id
        with sqlite3.connect(database) as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM table_holds WHERE offer_id=?", (offer_id,)
                ).fetchone()[0]
                == 2
            )
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM table_holds WHERE offer_id=?"
                    " AND status='held' AND expires_at>?",
                    (offer_id, epoch[0]),
                ).fetchone()[0]
                == 1
            )

        other = CallTools(state.dispatcher)
        assert await other.dispatch("hold_table", args) == {"error": "not_owned"}
        assert await other.dispatch("prepare_demo_table", {"hold_id": new_hold}) == {
            "error": "not_owned"
        }
        ready = await state.dispatch("prepare_demo_table", {"hold_id": new_hold})
        assert ready.get("ok"), ready
        assert ready["recap"]["table_offer_id"] == offer_id
        assert state.pending["delivery"] is state.pending["approved"] is False
        assert time.monotonic() < state.pending["expires_at"]
        assert state.pending["expires_at"] <= time.monotonic() + 1
        assert await state.dispatch("confirm_table_booking", {"hold_id": new_hold}) == {
            "error": "consent_required"
        }
        assert not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize("recovery", ["hold", "plan"])
def test_cancelled_table_rebooks_same_request_only_with_new_hold_and_fresh_consent(
    tmp_path, recovery
):
    database = str(tmp_path / "tables.db")

    async def run():
        backend = DemoTableAdapter(database)
        state = CallTools(Dispatcher(table=backend, business="restaurant"))
        first = await prepare_table(state)
        assert first.get("ok"), first
        old_hold = first["hold_id"]
        assert state.mark_recap_delivered(old_hold)
        state.observe_user_text(CONSENT["et"])
        confirmed = await state.dispatch("confirm_table_booking", {"hold_id": old_hold})
        assert confirmed.get("ok"), confirmed
        old_booking = confirmed["booking_id"]
        state.observe_user_text("Palun tühista see testbroneering.")
        cancelled = await state.dispatch(
            "cancel_table_booking", {"booking_id": old_booking}
        )
        assert cancelled.get("ok"), cancelled
        assert not any(
            result.get("hold_id") == old_hold for result in state.actions.values()
        )
        assert state.booking_holds[old_booking] == old_hold
        assert old_hold in state.confirmed_holds
        assert old_booking in state.cancelled_bookings
        assert await state.dispatch("confirm_table_booking", {"hold_id": old_hold}) == {
            "error": "already_cancelled"
        }
        assert await state.dispatch("prepare_demo_table", {"hold_id": old_hold}) == {
            "error": "already_confirmed"
        }

        state.observe_user_text("Soovin lauda broneerida.")
        if recovery == "plan":
            ready = await prepare_table(state)
        else:
            found = await state.dispatch("search_tables", REQUEST)
            held = await state.dispatch(
                "hold_table",
                {"table_offer_id": found["offers"][0]["table_offer_id"]},
            )
            ready = await state.dispatch(
                "prepare_demo_table", {"hold_id": held["hold_id"]}
            )
        assert ready.get("ok"), ready
        new_hold = ready["hold_id"]
        assert new_hold != old_hold and new_hold in state.held_tables
        assert ready["recap"]["table_name"] == first["recap"]["table_name"]
        assert all(ready["recap"][key] == value for key, value in REQUEST.items())
        assert state.pending["delivery"] is state.pending["approved"] is False
        state.observe_user_text(CONSENT["et"])
        assert await state.dispatch("confirm_table_booking", {"hold_id": new_hold}) == {
            "error": "consent_required"
        }
        assert state.bookings == {old_booking}

        ready = await state.dispatch("prepare_demo_table", {"hold_id": new_hold})
        assert ready.get("ok"), ready
        assert state.mark_recap_delivered(new_hold)
        for language, utterance in (
            ("et", "Palun korda."),
            ("en", "Please speak in English."),
            ("ru", "Говорите по-русски."),
        ):
            previous = state.pending
            state.observe_user_text(utterance)
            assert state.language == language
            assert state.pending is not previous
            assert state.pending is not None, (language, utterance)
            assert state.pending["hold_id"] == new_hold
            assert state.pending["delivery"] is state.pending["approved"] is False
            assert state.direct_reply == state.render_recap(new_hold)
            assert state.mark_recap_delivered(new_hold)
        assert await state.dispatch("confirm_table_booking", {"hold_id": new_hold}) == {
            "error": "consent_required"
        }
        state.observe_user_text(CONSENT["ru"])
        rebooked = await state.dispatch("confirm_table_booking", {"hold_id": new_hold})
        assert rebooked.get("ok"), rebooked
        assert rebooked["booking_id"] != old_booking
        assert state.booking_holds[rebooked["booking_id"]] == new_hold
        readback = await DemoTableAdapter(database).get_operator_bookings(
            REQUEST["date"]
        )
        assert {item["id"]: item["status"] for item in readback["items"]} == {
            old_booking: "cancelled",
            rebooked["booking_id"]: "confirmed",
        }
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT COUNT(*) FROM table_writes").fetchone()[0] == 3

    asyncio.run(run())
