"""Native process-lock checks without booking providers or credentials."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

import pytest

from app.booking.easyappointments import _acquire_lock


def test_lock_contends_and_releases_on_close(tmp_path):
    path = str(tmp_path / "journal.db.lock")
    first = _acquire_lock(path, 0.1)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            contender = executor.submit(_acquire_lock, path, 0.1)
            with pytest.raises(TimeoutError, match="lock busy"):
                contender.result(timeout=3)
    finally:
        first.close()
    # Neither a timed-out contender nor the previous owner keeps a lock.
    with _acquire_lock(path, 0.1):
        pass


def test_lock_excludes_another_process(tmp_path):
    path = str(tmp_path / "journal.db.lock")
    program = """
import sys
from app.booking.easyappointments import _acquire_lock
try:
    with _acquire_lock(sys.argv[1], 0.1):
        print("acquired")
except TimeoutError:
    print("busy")
"""
    command = [sys.executable, "-c", program, path]
    cwd = Path(__file__).resolve().parents[1]
    with _acquire_lock(path, 0.1):
        blocked = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=5, check=True
        )
        assert blocked.stdout.strip() == "busy"
    released = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=5, check=True
    )
    assert released.stdout.strip() == "acquired"


def test_lock_open_error_is_not_retried_as_contention(tmp_path):
    with pytest.raises(OSError):
        _acquire_lock(str(tmp_path), 10)
