"""Exercise the actual operating-system lock used by the booking journal."""

import pytest

from app.booking.easyappointments import _acquire_lock


def test_journal_lock_excludes_other_handles_and_releases_on_close(tmp_path):
    path = str(tmp_path / "booking.lock")
    first = _acquire_lock(path, 0.1)
    try:
        with pytest.raises(TimeoutError, match="lock busy"):
            _acquire_lock(path, 0.05)
    finally:
        first.close()
    second = _acquire_lock(path, 0.1)
    second.close()
