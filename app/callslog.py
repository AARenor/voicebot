"""Turn/call log: SQLite append-only log feeding the dashboard.

Thread-safe (one RLock around all DB access; double-checked singleton
init). Parameterized writes/reads only. Demo rows carry source='demo'
and are visually marked; real rows are source='real'. Caller numbers
are masked at write, but summaries may still carry caller PII. The
30-day prune is a technical default, not an approved retention policy
(ARCHITECTURE.md section 10, R-018). File DBs are created 0600 with
parent dirs made as needed.
"""

from __future__ import annotations

import os
import logging
import sqlite3
import time

from . import call_history

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS calls ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
    "lang TEXT NOT NULL, peer TEXT NOT NULL, summary TEXT NOT NULL, "
    "outcome TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'real')"
)

DEMO_ROWS = [
    (
        "2026-09-30 08:12",
        "et",
        "+372 5••• ••21",
        "Küsis broneeringu muutmist → hold_demo_mer34 (demo)",
        "hold_created",
    ),
    (
        "2026-09-30 08:40",
        "et",
        "+372 5••• ••87",
        "Massaažiaegade küsimine → hold_demo_sea12 (demo)",
        "hold_created",
    ),
    (
        "2026-09-30 09:02",
        "ru",
        "+372 5••• ••44",
        "Hinna küsimine ilma pakkumiseta → operaatorile (demo)",
        "handoff",
    ),
]

_LOCK = call_history.DB_LOCK
_default: sqlite3.Connection | None = None


def mask_peer(peer: str) -> str:
    """Mask a caller number: first 4 chars + last 2, rest hidden."""
    peer = (peer or "").strip()
    if len(peer) <= 4:
        return "••••"
    return f"{peer[:4]}•••{peer[-2:]}"


def open_log(path: str = ":memory:") -> sqlite3.Connection:
    if path != ":memory:":
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        # Create owner-only from the first byte (no umask window), then
        # tighten pre-existing files we own.
        fd = os.open(os.path.abspath(path), os.O_CREAT | os.O_RDONLY, 0o600)
        os.close(fd)
        try:
            if os.stat(path).st_mode & 0o077:
                os.chmod(path, 0o600)
        except OSError:
            pass
        db = sqlite3.connect(path, check_same_thread=False)
    else:
        db = sqlite3.connect(path, check_same_thread=False)
    with _LOCK:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(SCHEMA)
        try:
            db.execute(
                "ALTER TABLE calls ADD COLUMN source TEXT NOT NULL DEFAULT 'real'"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise  # real error (e.g. locked), not a rerun migration
        call_history.migrate(db)
        prune(db)
        db.commit()
    return db


def prune(db: sqlite3.Connection, retention_days: int = 30) -> int:
    """Delete rows older than retention_days (technical default; see R-018).

    `at` is zero-padded "%Y-%m-%d %H:%M", so lexicographic compare works.
    Returns rows deleted.
    """
    cutoff = time.strftime(
        "%Y-%m-%d %H:%M", time.localtime(time.time() - retention_days * 86400)
    )
    with _LOCK:
        from datetime import datetime, timezone

        history_cutoff = datetime.fromtimestamp(
            time.time() - retention_days * 86400, timezone.utc
        ).isoformat(timespec="seconds")
        call_history.prune(db, history_cutoff)
        cursor = db.execute("DELETE FROM calls WHERE at < ?", (cutoff,))
        db.commit()
        return cursor.rowcount


def seed_demo(db: sqlite3.Connection) -> int:
    """Insert demo rows once (empty log only). Returns rows added."""
    with _LOCK:
        count = db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        if count:
            return 0
        db.executemany(
            "INSERT INTO calls (at, lang, peer, summary, outcome, source) "
            "VALUES (?, ?, ?, ?, ?, 'demo')",
            DEMO_ROWS,
        )
        db.commit()
        return len(DEMO_ROWS)


def log_call(
    db: sqlite3.Connection, lang: str, peer: str, summary: str, outcome: str
) -> int:
    """Append one call record (peer masked). Returns row id."""
    at = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    with _LOCK:
        cursor = db.execute(
            "INSERT INTO calls (at, lang, peer, summary, outcome, source) "
            "VALUES (?, ?, ?, ?, ?, 'real')",
            (at, lang[:8], mask_peer(peer), summary[:500], outcome[:32]),
        )
        db.commit()
        return int(cursor.lastrowid)


def list_calls(db: sqlite3.Connection, limit: int = 50) -> list[dict]:
    if isinstance(limit, bool):
        limit = 50
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 50
    with _LOCK:
        cursor = db.execute(
            "SELECT at, lang, peer, summary, outcome, source FROM calls "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
    return [
        {
            "at": row[0],
            "lang": row[1],
            "from": row[2],
            "summary": row[3],
            "outcome": row[4],
            "source": row[5],
        }
        for row in rows
    ]


def get_default() -> sqlite3.Connection:
    """Process-wide log (CALLS_DB path or memory). Never seeds: callers
    seed explicitly (server seeds demo rows only in demo mode)."""
    global _default
    if _default is None:
        with _LOCK:
            if _default is None:
                _default = open_log(os.environ.get("CALLS_DB", ":memory:"))
    return _default


def history_safe(operation, *args, **kwargs) -> None:
    """History failure never interrupts speech or an authoritative booking."""
    try:
        operation(get_default(), *args, **kwargs)
    except Exception:
        logging.getLogger("voicebot.telephone").warning("call_history_unavailable")


def reset_default() -> None:
    """TESTS ONLY — never call from request paths (drops shared handle)."""
    if os.environ.get("VOICEBOT_PROD"):
        raise RuntimeError("reset_default is blocked in production")
    global _default
    with _LOCK:
        if _default is not None:
            try:
                _default.close()
            except Exception:
                pass
        _default = None
