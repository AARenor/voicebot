"""Every short-lived journal connection closes, including exceptional reads."""

import sqlite3
from unittest.mock import patch

import pytest

from app.booking.easyappointments import _Journal


def test_journal_connections_close_after_transactions_and_errors(tmp_path):
    opened = []
    connect = sqlite3.connect

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    path = str(tmp_path / "journal.db")
    with patch("app.booking.easyappointments.sqlite3.connect", tracked_connect):
        journal = _Journal(path)
        journal.put_pending("key", "opaque-marker")
        assert journal.get("key")["status"] == "pending_appointment"
        assert journal.pending_appointments("other") == [("key", "opaque-marker")]
        journal.put_result("key", "opaque-marker", "confirmed", "42", {"ok": True})
        assert journal.get("key")["result"] == {"ok": True}
        for connection in opened:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
        with connect(path) as connection:
            connection.execute("DROP TABLE easy_writes")
        connection.close()
        with pytest.raises(sqlite3.OperationalError):
            journal.get("key")
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened[-1].execute("SELECT 1")
    # Windows also verifies no hidden SQLite handle prevents file removal.
    (tmp_path / "journal.db").unlink()
