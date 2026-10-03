"""Persistent session metadata for the operator dashboard.

Uses the existing CALLS_DB and lock. No audio, transcripts, provider payloads,
operator credentials, room names or guest details are accepted by this API.
Booking links come exclusively from successful server-owned receipts.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
import re
import sqlite3
import threading
from typing import Any

DB_LOCK = threading.RLock()

CHANNELS = {"browser", "telephone"}
INPUTS = {"typed", "recognized", "no_speech", "stt_unavailable"}
OUTCOMES = {
    "in_progress",
    "completed",
    "ok",
    "tools_ok",
    "fallback",
    "tools_failed",
    "tts_failed",
    "provider_error",
    "booking_unavailable",
    "unknown_outcome",
    "write_outcome_unknown",
    "hold_created",
    "booking_confirmed",
    "booking_cancelled",
    "interrupted",
    "expired",
}
ATTENTION = {
    "fallback",
    "tools_failed",
    "tts_failed",
    "provider_error",
    "booking_unavailable",
    "unknown_outcome",
    "write_outcome_unknown",
    "interrupted",
}
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS call_sessions (
        call_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        ended_at TEXT, channel TEXT NOT NULL, language TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        outcome TEXT NOT NULL DEFAULT 'in_progress',
        turns INTEGER NOT NULL DEFAULT 0, recognized_turns INTEGER NOT NULL DEFAULT 0,
        typed_turns INTEGER NOT NULL DEFAULT 0, empty_turns INTEGER NOT NULL DEFAULT 0,
        stt_errors INTEGER NOT NULL DEFAULT 0, tts_errors INTEGER NOT NULL DEFAULT 0,
        provider_errors INTEGER NOT NULL DEFAULT 0,
        vad_events INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS call_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL,
        at TEXT NOT NULL, kind TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(call_id) REFERENCES call_sessions(call_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS call_bookings (
        call_id TEXT NOT NULL, booking_id TEXT NOT NULL, action TEXT NOT NULL,
        date TEXT NOT NULL, start_local TEXT NOT NULL, timezone TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'slot', checkout TEXT,
        PRIMARY KEY(call_id, booking_id),
        FOREIGN KEY(call_id) REFERENCES call_sessions(call_id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS call_sessions_started "
    "ON call_sessions(started_at DESC)",
    "CREATE INDEX IF NOT EXISTS call_events_session ON call_events(call_id, id)",
)


def migrate(db: sqlite3.Connection) -> None:
    with DB_LOCK:
        for statement in SCHEMA:
            db.execute(statement)
        columns = {row[1] for row in db.execute("PRAGMA table_info(call_sessions)")}
        if "vad_events" not in columns:
            db.execute(
                "ALTER TABLE call_sessions ADD COLUMN vad_events "
                "INTEGER NOT NULL DEFAULT 0"
            )
        booking_columns = {
            row[1] for row in db.execute("PRAGMA table_info(call_bookings)")
        }
        if "kind" not in booking_columns:
            db.execute(
                "ALTER TABLE call_bookings ADD COLUMN kind TEXT NOT NULL DEFAULT 'slot'"
            )
        if "checkout" not in booking_columns:
            db.execute("ALTER TABLE call_bookings ADD COLUMN checkout TEXT")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_id(call_id: str) -> None:
    if not isinstance(call_id, str) or not re.fullmatch(r"[a-f0-9]{32}", call_id):
        raise ValueError("invalid call id")


def _event(
    db: sqlite3.Connection,
    call_id: str,
    kind: str,
    outcome: str = "",
    at: str | None = None,
) -> None:
    # A noisy call cannot grow an unbounded timeline. Counters still update.
    db.execute(
        "INSERT INTO call_events(call_id, at, kind, outcome) SELECT ?, ?, ?, ? "
        "WHERE (SELECT COUNT(*) FROM call_events WHERE call_id=?) < 200",
        (call_id, at or _now(), kind, outcome, call_id),
    )


def start(
    db: sqlite3.Connection, call_id: str, channel: str, language: str = "et"
) -> None:
    _validate_id(call_id)
    if channel not in CHANNELS or language not in {"et", "en", "ru"}:
        raise ValueError("invalid call metadata")
    now = _now()
    with DB_LOCK, db:
        inserted = db.execute(
            "INSERT OR IGNORE INTO call_sessions "
            "(call_id, started_at, updated_at, channel, language) "
            "VALUES (?, ?, ?, ?, ?)",
            (call_id, now, now, channel, language),
        )
        if inserted.rowcount:
            _event(db, call_id, "started", at=now)


def record_input(
    db: sqlite3.Connection,
    call_id: str,
    status: str,
    language: str = "et",
) -> None:
    _validate_id(call_id)
    if status not in INPUTS or language not in {"et", "en", "ru"}:
        raise ValueError("invalid recognition metadata")
    with DB_LOCK, db:
        changed = db.execute(
            "UPDATE call_sessions SET updated_at=?, language=?, turns=turns+1, "
            "recognized_turns=recognized_turns+?, typed_turns=typed_turns+?, "
            "empty_turns=empty_turns+?, stt_errors=stt_errors+? "
            "WHERE call_id=? AND status='active'",
            (
                _now(),
                language,
                int(status == "recognized"),
                int(status == "typed"),
                int(status == "no_speech"),
                int(status == "stt_unavailable"),
                call_id,
            ),
        )
        if changed.rowcount:
            _event(db, call_id, status)


def _receipt(
    change: dict[str, Any],
) -> tuple[str, str, str, str, str, str, str | None] | None:
    try:
        booking_id = str(change["id"])
        action = change["action"]
        day = date.fromisoformat(change["date"])
        kind = change.get("kind", "slot")
        checkout = None
        if kind in {"slot", "table"}:
            start = datetime.fromisoformat(change["start_local"])
            valid_id = (
                booking_id.isascii()
                and booking_id.isdigit()
                and 0 < int(booking_id) < 2**63
            )
            if start.date() != day or start.tzinfo is not None:
                return None
            if kind == "table":
                valid_id = re.fullmatch(r"table_[a-f0-9]{32}", booking_id) is not None
                if day.isoformat() != change["date"] or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:00", change["start_local"]
                ):
                    return None
            start_local = start.isoformat(sep=" ")
        elif kind == "stay":
            valid_id = re.fullmatch(r"stay_[a-f0-9]{32}", booking_id) is not None
            checkout_date = date.fromisoformat(change["checkout"])
            if not day < checkout_date:
                return None
            checkout = checkout_date.isoformat()
            start_local = ""  # The receipt contains dates, not an arrival time.
        else:
            return None
        if (
            not valid_id
            or action not in {"confirmed", "cancelled"}
            or change.get("timezone") != "Europe/Tallinn"
        ):
            return None
        return (
            booking_id,
            action,
            day.isoformat(),
            start_local,
            "Europe/Tallinn",
            kind,
            checkout,
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def record_result(
    db: sqlite3.Connection,
    call_id: str,
    outcome: str,
    *,
    tts_failed: bool = False,
    changes: Iterable[dict[str, Any]] = (),
) -> None:
    _validate_id(call_id)
    if outcome not in OUTCOMES:
        raise ValueError("invalid call outcome")
    with DB_LOCK, db:
        changed = db.execute(
            "UPDATE call_sessions SET updated_at=?, "
            "outcome=CASE WHEN outcome IN ('unknown_outcome', 'write_outcome_unknown') "
            "THEN outcome WHEN ?='completed' AND outcome!='in_progress' "
            "THEN outcome ELSE ? END, tts_errors=tts_errors+? "
            "WHERE call_id=? AND status='active'",
            (_now(), outcome, outcome, int(bool(tts_failed)), call_id),
        )
        if not changed.rowcount:
            return
        _event(db, call_id, "response", outcome)
        if tts_failed:
            _event(db, call_id, "tts_unavailable")
        for change in changes:
            receipt = _receipt(change) if isinstance(change, dict) else None
            if receipt is None:
                continue
            booking_id, action, day, start_local, zone, kind, checkout = receipt
            prior = db.execute(
                "SELECT action FROM call_bookings WHERE call_id=? AND booking_id=?",
                (call_id, booking_id),
            ).fetchone()
            if prior and (prior[0] == action or prior[0] == "cancelled"):
                continue
            # Cancellation needs a previously confirmed receipt from this call.
            if action == "cancelled" and not prior:
                continue
            db.execute(
                "INSERT INTO call_bookings "
                "(call_id, booking_id, action, date, start_local, timezone, "
                "kind, checkout) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(call_id, booking_id) DO UPDATE SET action=excluded.action",
                (call_id, booking_id, action, day, start_local, zone, kind, checkout),
            )
            _event(db, call_id, "booking_" + action)


def provider_error(db: sqlite3.Connection, call_id: str, kind: str) -> None:
    _validate_id(call_id)
    # SDK events never persist their exception, status body or credentials.
    kind = kind if kind in {"stt_error", "tts_error", "llm_error"} else "provider_error"
    with DB_LOCK, db:
        changed = db.execute(
            "UPDATE call_sessions SET updated_at=?, provider_errors=provider_errors+1, "
            "stt_errors=stt_errors+?, tts_errors=tts_errors+? "
            "WHERE call_id=? AND status='active'",
            (_now(), int(kind == "stt_error"), int(kind == "tts_error"), call_id),
        )
        if changed.rowcount:
            _event(db, call_id, kind)


def activity(db: sqlite3.Connection, call_id: str, kind: str) -> None:
    _validate_id(call_id)
    if kind not in {"speech_started", "interrupted", "greeting"}:
        raise ValueError("invalid call activity")
    with DB_LOCK, db:
        changed = db.execute(
            "UPDATE call_sessions SET updated_at=?, vad_events=vad_events+? "
            "WHERE call_id=? AND status='active'",
            (_now(), int(kind == "speech_started"), call_id),
        )
        if changed.rowcount:
            _event(db, call_id, kind)


def end(
    db: sqlite3.Connection,
    call_id: str,
    outcome: str = "completed",
    *,
    expired: bool = False,
) -> None:
    _validate_id(call_id)
    if outcome not in OUTCOMES:
        raise ValueError("invalid call outcome")
    now = _now()
    with DB_LOCK, db:
        changed = db.execute(
            "UPDATE call_sessions SET updated_at=?, ended_at=?, status=?, "
            "outcome=CASE WHEN outcome IN ('unknown_outcome', 'write_outcome_unknown') "
            "THEN outcome WHEN ?='completed' AND outcome!='in_progress' THEN outcome "
            "ELSE ? END WHERE call_id=? AND status='active'",
            (now, now, "expired" if expired else "ended", outcome, outcome, call_id),
        )
        if changed.rowcount:
            _event(db, call_id, "ended", "expired" if expired else outcome, at=now)


def prune(db: sqlite3.Connection, cutoff: str) -> None:
    with DB_LOCK:
        # Explicit child pruning also handles old connections without FK enabled.
        for table in ("call_events", "call_bookings"):
            db.execute(
                f"DELETE FROM {table} WHERE call_id IN "
                "(SELECT call_id FROM call_sessions WHERE started_at < ?)",
                (cutoff,),
            )
        db.execute("DELETE FROM call_sessions WHERE started_at < ?", (cutoff,))


def _bookings(db: sqlite3.Connection, call_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT booking_id, action, date, start_local, timezone, kind, checkout "
        "FROM call_bookings "
        "WHERE call_id=? ORDER BY date, start_local, booking_id",
        (call_id,),
    ).fetchall()
    return [
        dict(
            zip(
                ("id", "action", "date", "start_local", "timezone", "kind", "checkout"),
                row,
            )
        )
        for row in rows
    ]


def _session(db: sqlite3.Connection, row: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "id",
        "started_at",
        "updated_at",
        "ended_at",
        "channel",
        "language",
        "status",
        "outcome",
        "turns",
        "recognized_turns",
        "typed_turns",
        "empty_turns",
        "stt_errors",
        "tts_errors",
        "provider_errors",
        "vad_events",
    )
    item: dict[str, Any] = dict(zip(keys, row))
    started = datetime.fromisoformat(item["started_at"])
    ended = (
        datetime.fromisoformat(item["ended_at"])
        if item["ended_at"]
        else datetime.now(timezone.utc)
    )
    item["duration_s"] = max(0, int((ended - started).total_seconds()))
    item["bookings"] = _bookings(db, item["id"])
    item["needs_attention"] = bool(
        item["outcome"] in ATTENTION
        or item["stt_errors"]
        or item["tts_errors"]
        or item["provider_errors"]
        or item["empty_turns"] >= 3
        or (
            item["channel"] == "telephone"
            and item["vad_events"]
            and not item["recognized_turns"]
        )
    )
    item["data_mode"] = "synthetic"
    return item


def list_sessions(
    db: sqlite3.Connection,
    *,
    page: int = 1,
    length: int = 20,
    channel: str = "all",
    result: str = "all",
) -> dict[str, Any]:
    if (
        type(page) is not int
        or not 1 <= page <= 1000
        or type(length) is not int
        or not 1 <= length <= 50
        or channel not in CHANNELS | {"all"}
        or result not in {"all", "attention", "booked"}
    ):
        raise ValueError("invalid call history query")
    conditions, values = [], []
    if channel != "all":
        conditions.append("s.channel=?")
        values.append(channel)
    attention = (
        "(s.outcome IN (" + ",".join("?" for _ in ATTENTION) + ") "
        "OR s.stt_errors>0 OR s.tts_errors>0 OR s.provider_errors>0 "
        "OR s.empty_turns>=3 OR "
        "(s.channel='telephone' AND s.vad_events>0 AND s.recognized_turns=0))"
    )
    attention_values = sorted(ATTENTION)
    if result == "attention":
        conditions.append(attention)
        values.extend(attention_values)
    elif result == "booked":
        conditions.append(
            "EXISTS(SELECT 1 FROM call_bookings b WHERE b.call_id=s.call_id)"
        )
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with DB_LOCK:
        _maintain(db)
        totals = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(s.status='active'),0), "
            "COALESCE(SUM(EXISTS(SELECT 1 FROM call_bookings b "
            "WHERE b.call_id=s.call_id)),0), "
            f"COALESCE(SUM({attention}),0) FROM call_sessions s" + where,
            (*attention_values, *values),
        ).fetchone()
        rows = db.execute(
            "SELECT s.* FROM call_sessions s"
            + where
            + " ORDER BY s.started_at DESC, s.call_id DESC LIMIT ? OFFSET ?",
            (*values, length, (page - 1) * length),
        ).fetchall()
        items = [_session(db, row) for row in rows]
    return {
        "items": items,
        "page": page,
        "length": length,
        "has_more": page * length < totals[0],
        "summary": dict(
            zip(("total", "active", "with_booking", "needs_attention"), totals)
        ),
        "fetched_at": _now(),
        "data_mode": "synthetic",
    }


def detail(db: sqlite3.Connection, call_id: str) -> dict[str, Any] | None:
    _validate_id(call_id)
    with DB_LOCK:
        _maintain(db)
        row = db.execute(
            "SELECT * FROM call_sessions WHERE call_id=?", (call_id,)
        ).fetchone()
        if row is None:
            return None
        item = _session(db, row)
        events = db.execute(
            "SELECT id, at, kind, outcome FROM call_events WHERE call_id=? ORDER BY id",
            (call_id,),
        ).fetchall()
    return {
        "session": item,
        "events": [dict(zip(("id", "at", "kind", "outcome"), row)) for row in events],
    }


def _maintain(db: sqlite3.Connection) -> None:
    # Enforce retention in long-running workers without requiring a restart.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(
        timespec="seconds"
    )
    with db:
        prune(db, cutoff)
    _close_stale(db)


def _close_stale(db: sqlite3.Connection) -> None:
    # Both transports cap sessions at ten minutes. A terminated process cannot
    # run its cleanup; retain its last activity as the end estimate after 15m.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(
        timespec="seconds"
    )
    with db:
        rows = db.execute(
            "SELECT call_id, updated_at FROM call_sessions "
            "WHERE status='active' AND updated_at < ?",
            (cutoff,),
        ).fetchall()
        for call_id, at in rows:
            db.execute(
                "UPDATE call_sessions SET status='ended', ended_at=updated_at, "
                "outcome=CASE WHEN outcome IN "
                "('unknown_outcome','write_outcome_unknown') "
                "THEN outcome ELSE 'interrupted' END WHERE call_id=?",
                (call_id,),
            )
            _event(db, call_id, "ended", "interrupted", at=at)
