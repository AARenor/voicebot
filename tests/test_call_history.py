"""Session history is durable, bounded, private and grounded in receipts."""

from datetime import datetime, timedelta, timezone
import base64
import json
import sqlite3
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import pytest

from app import call_history as history, callslog
from app.server import create_app

CALL = "a" * 32
OTHER = "b" * 32
AUTH = {"Authorization": "Bearer fixture-operator"}
RECEIPT = {
    "id": "42",
    "action": "confirmed",
    "date": "2026-10-03",
    "start_local": "2026-10-03 11:00:00",
    "timezone": "Europe/Tallinn",
}


@pytest.fixture
def db():
    connection = callslog.open_log()
    yield connection
    connection.close()


def test_migration_preserves_legacy_calls_and_is_repeatable(tmp_path):
    path = tmp_path / "calls.db"
    with sqlite3.connect(path) as old:
        old.execute(
            "CREATE TABLE calls (id INTEGER PRIMARY KEY, at TEXT, lang TEXT, "
            "peer TEXT, summary TEXT, outcome TEXT)"
        )
        old.execute(
            "INSERT INTO calls VALUES "
            "(1, '2099-01-01 12:00', 'et', 'masked', 'legacy', 'ok')"
        )
    old.close()
    db = callslog.open_log(str(path))
    try:
        history.migrate(db)
        assert callslog.list_calls(db)[0]["summary"] == "legacy"
        history.start(db, CALL, "telephone")
        history.start(db, CALL, "telephone")
        assert len(history.detail(db, CALL)["events"]) == 1
    finally:
        db.close()


def test_turn_counters_and_events_do_not_store_utterances(db):
    history.start(db, CALL, "telephone")
    for status in ("recognized", "no_speech", "stt_unavailable"):
        history.record_input(db, CALL, status)
    history.activity(db, CALL, "speech_started")
    history.provider_error(db, CALL, "stt_error")
    history.record_result(db, CALL, "tts_failed", tts_failed=True)
    history.end(db, CALL, "provider_error")
    detail = history.detail(db, CALL)
    row = detail["session"]
    assert (row["turns"], row["recognized_turns"], row["empty_turns"]) == (3, 1, 1)
    assert (row["stt_errors"], row["tts_errors"], row["vad_events"]) == (2, 1, 1)
    assert row["status"] == "ended" and row["needs_attention"]
    assert row["duration_s"] >= 0
    assert "transcript" not in json.dumps(detail)
    with pytest.raises(ValueError):
        history.record_input(db, CALL, "private@example.test")


def test_booking_receipts_are_owned_idempotent_and_cancelled_once(db):
    history.start(db, CALL, "browser")
    history.start(db, OTHER, "browser")
    history.record_result(
        db, OTHER, "tools_ok", changes=[{**RECEIPT, "action": "cancelled"}]
    )
    assert history.detail(db, OTHER)["session"]["bookings"] == []
    history.record_result(db, CALL, "tools_ok", changes=[RECEIPT, RECEIPT])
    history.record_result(
        db, CALL, "tools_failed", changes=[{**RECEIPT, "action": "cancelled"}]
    )
    history.record_result(db, CALL, "tools_ok", changes=[RECEIPT])
    detail = history.detail(db, CALL)
    assert detail["session"]["bookings"][0]["action"] == "cancelled"
    assert [e["kind"] for e in detail["events"]].count("booking_confirmed") == 1
    assert [e["kind"] for e in detail["events"]].count("booking_cancelled") == 1


@pytest.mark.parametrize(
    "change",
    [
        {**RECEIPT, "id": "invented"},
        {**RECEIPT, "date": "bad"},
        {**RECEIPT, "timezone": "UTC"},
        {**RECEIPT, "action": "maybe"},
        {**RECEIPT, "start_local": "2026-10-04 11:00:00"},
    ],
)
def test_invalid_receipt_is_not_a_booking_link(db, change):
    history.start(db, CALL, "telephone")
    history.record_result(db, CALL, "tools_ok", changes=[change])
    assert history.detail(db, CALL)["session"]["bookings"] == []


def test_unknown_write_is_sticky_and_late_callbacks_do_not_reopen_session(db):
    history.start(db, CALL, "telephone")
    history.record_result(db, CALL, "write_outcome_unknown")
    history.record_result(db, CALL, "ok")
    history.end(db, CALL, "completed")
    history.record_input(db, CALL, "recognized")
    history.record_result(db, CALL, "booking_confirmed", changes=[RECEIPT])
    row = history.detail(db, CALL)["session"]
    assert row["outcome"] == "write_outcome_unknown"
    assert row["turns"] == 0 and row["bookings"] == []


def test_filters_summary_and_pagination(db):
    history.start(db, CALL, "telephone")
    history.start(db, OTHER, "browser")
    history.record_result(db, OTHER, "tools_ok", changes=[RECEIPT])
    for _ in range(3):
        history.record_input(db, CALL, "no_speech")
    page = history.list_sessions(db, length=1)
    assert page["has_more"]
    assert page["summary"] == {
        "total": 2,
        "active": 2,
        "with_booking": 1,
        "needs_attention": 1,
    }
    assert history.list_sessions(db, channel="telephone")["items"][0]["id"] == CALL
    assert history.list_sessions(db, result="attention")["items"][0]["id"] == CALL
    assert history.list_sessions(db, result="booked")["items"][0]["id"] == OTHER
    assert not history.list_sessions(db, page=2, length=1)["has_more"]


def test_process_loss_closes_stale_session_at_last_activity(db):
    history.start(db, CALL, "telephone")
    old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(
        timespec="seconds"
    )
    db.execute("UPDATE call_sessions SET started_at=?, updated_at=?", (old, old))
    db.commit()
    row = history.detail(db, CALL)["session"]
    assert row["status"] == "ended" and row["outcome"] == "interrupted"
    assert row["ended_at"] == old and row["duration_s"] == 0


def test_timeline_and_retention_are_bounded(db):
    history.start(db, CALL, "telephone")
    for _ in range(210):
        history.record_input(db, CALL, "recognized")
    assert len(history.detail(db, CALL)["events"]) == 200
    assert history.detail(db, CALL)["session"]["turns"] == 210
    db.execute("UPDATE call_sessions SET started_at='2000-01-01T00:00:00+00:00'")
    db.commit()
    callslog.prune(db)
    assert history.detail(db, CALL) is None
    assert db.execute("SELECT COUNT(*) FROM call_events").fetchone()[0] == 0


def test_read_enforces_retention_without_reopening_database(db):
    history.start(db, CALL, "browser")
    history.record_result(db, CALL, "tools_ok", changes=[RECEIPT])
    db.execute("UPDATE call_sessions SET started_at='2000-01-01T00:00:00+00:00'")
    db.commit()
    assert history.list_sessions(db)["summary"]["total"] == 0
    assert history.detail(db, CALL) is None
    for table in ("call_sessions", "call_events", "call_bookings"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.fixture
def client(db, monkeypatch):
    with patch.dict("os.environ", {"OPERATOR_TOKEN": "fixture-operator"}, clear=True):
        monkeypatch.setattr(callslog, "get_default", lambda: db)
        app = create_app()
        app.state.stack.update(llm_primary=Mock(), tts=Mock())
        app.state.stack["llm_primary"].chat.return_value = {"content": "Tere!"}
        app.state.stack["tts"].synthesize.return_value = b"audio"
        with TestClient(app) as result:
            yield result


def test_history_api_auth_validation_and_no_store(client, db):
    history.start(db, CALL, "telephone")
    for path in ("/api/call-history", f"/api/call-history/{CALL}"):
        forbidden = client.get(path)
        assert forbidden.status_code == 403
        assert forbidden.headers["Cache-Control"] == "no-store"
        allowed = client.get(path, headers=AUTH)
        assert allowed.status_code == 200
        assert allowed.headers["Cache-Control"] == "no-store"
    for query in (
        "page=0",
        "length=51",
        "channel=private",
        "result=invalid",
        "page=-1",
    ):
        assert client.get("/api/call-history?" + query, headers=AUTH).status_code == 400
    assert client.get("/api/call-history/not-a-call", headers=AUTH).status_code == 404


def test_http_turns_share_one_session_until_explicit_end(client, db):
    started = client.post("/api/demo/session", headers=AUTH).json()
    for _ in range(2):
        response = client.post(
            "/api/turn",
            headers=AUTH,
            json={
                "session_id": started["session_id"],
                "text": "private@example.test",
            },
        )
        assert response.status_code == 200
        assert response.json()["call_id"] == started["call_id"]
    assert history.detail(db, started["call_id"])["session"]["turns"] == 2
    assert (
        client.delete(
            "/api/demo/session/" + started["session_id"], headers=AUTH
        ).status_code
        == 200
    )
    detail = client.get("/api/call-history/" + started["call_id"], headers=AUTH).json()
    assert detail["session"]["status"] == "ended"
    assert "private@example" not in json.dumps(detail)


@pytest.mark.parametrize("user_text", ["Tere!", "Kas see on päris spaa?"])
@pytest.mark.parametrize("input_kind", ["typed", "recognized"])
def test_canonical_response_keeps_session_history_and_private_call_metadata(
    client, db, user_text, input_kind
):
    started = client.post("/api/demo/session", headers=AUTH).json()
    session = client.app.state.demo_sessions.sessions[started["session_id"]]
    expected = (
        "Tere! Kuidas saan aidata?"
        if user_text == "Tere!"
        else session.tools.demo["faq"][0]["answer_et"]
    )
    payload = {"session_id": started["session_id"]}
    if input_kind == "recognized":
        client.app.state.stack["stt"] = Mock()
        client.app.state.stack["stt"].transcribe.return_value = user_text
        payload["audio_b64"] = base64.b64encode(b"RIFF-fixture").decode()
    else:
        payload["text"] = user_text

    response = client.post("/api/turn", json=payload, headers=AUTH)
    assert response.status_code == 200
    result = response.json()
    assert result["reply"] == expected
    assert result["input_status"] == input_kind and result["outcome"] == "ok"
    assert result["warnings"] == []
    if input_kind == "recognized":
        client.app.state.stack["stt"].transcribe.assert_called_once_with(
            b"RIFF-fixture", language="et"
        )
    client.app.state.stack["llm_primary"].chat.assert_not_called()
    client.app.state.stack["tts"].synthesize.assert_called_once_with(expected)
    assert session.history[-1] == {"role": "assistant", "content": expected}

    detail = history.detail(db, started["call_id"])
    row = detail["session"]
    assert row["turns"] == 1 and row["outcome"] == "ok"
    assert row["typed_turns"] == (input_kind == "typed")
    assert row["recognized_turns"] == (input_kind == "recognized")
    assert row["bookings"] == [] and not row["needs_attention"]
    assert user_text not in json.dumps(detail, ensure_ascii=False)
    assert expected not in json.dumps(detail, ensure_ascii=False)


def test_isolated_turn_has_completed_history(client, db):
    response = client.post("/api/turn", json={"text": "Tere"}, headers=AUTH)
    assert response.status_code == 200
    row = history.detail(db, response.json()["call_id"])["session"]
    assert row["status"] == "ended" and row["typed_turns"] == 1


def test_history_id_cannot_authorize_conversation_state(client, db):
    started = client.post("/api/demo/session", headers=AUTH).json()
    assert started["call_id"] != started["session_id"]
    response = client.post(
        "/api/turn",
        headers=AUTH,
        json={"text": "Tere", "session_id": started["call_id"]},
    )
    assert response.status_code == 410
    assert history.detail(db, started["call_id"])["session"]["turns"] == 0


def test_room_receipt_has_dates_and_owned_cancellation_without_invented_time(db):
    receipt = {
        "id": "stay_" + "c" * 32,
        "kind": "stay",
        "action": "confirmed",
        "date": "2026-10-09",
        "checkout": "2026-10-11",
        "timezone": "Europe/Tallinn",
    }
    history.start(db, CALL, "telephone")
    history.record_result(db, CALL, "booking_confirmed", changes=[receipt])
    row = history.detail(db, CALL)["session"]["bookings"][0]
    assert row["kind"] == "stay" and row["start_local"] == ""
    assert row["date"] == "2026-10-09" and row["checkout"] == "2026-10-11"
    history.record_result(
        db,
        CALL,
        "booking_cancelled",
        changes=[{**receipt, "action": "cancelled"}],
    )
    assert history.detail(db, CALL)["session"]["bookings"][0]["action"] == "cancelled"


def test_native_room_write_persists_confirmed_receipt_immediately(
    db, tmp_path, monkeypatch
):
    import asyncio
    from app.booking.demo_stay import DemoStayAdapter
    from app.booking.tools import Dispatcher
    from app.telephone import CallTools, CONSENT_TEXT
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(callslog, "get_default", lambda: db)
    state = CallTools(Dispatcher(stay=DemoStayAdapter(str(tmp_path / "stay.db"))))
    state.history_enabled = True
    history.start(db, state.call_id, "telephone")

    async def run():
        day = (datetime.now(ZoneInfo("Europe/Tallinn")) + timedelta(days=10)).date()
        found = await state.dispatch(
            "search_availability",
            {
                "checkin": day.isoformat(),
                "checkout": (day + timedelta(days=2)).isoformat(),
                "adults": 2,
            },
        )
        hold = await state.dispatch(
            "hold_offer", {"price_quote_id": found["offers"][0]["price_quote_id"]}
        )
        await state.dispatch("prepare_demo_stay", {"hold_id": hold["hold_id"]})
        state.mark_recap_delivered(hold["hold_id"])
        state.observe_user_text(CONSENT_TEXT)
        result = await state.dispatch("confirm_booking", {"hold_id": hold["hold_id"]})
        assert result["ok"] is True
        row = history.detail(db, state.call_id)["session"]["bookings"][0]
        assert row["kind"] == "stay" and row["id"] == result["booking"]["id"]
        assert row["date"] == day.isoformat()

    asyncio.run(run())
