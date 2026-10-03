"""Native restaurant probe must only inspect/clean its opaque call scope."""

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

pytest.importorskip("livekit.rtc")
ROOT = Path(__file__).resolve().parents[1]


def module():
    path = ROOT / "deploy/telephony/restaurant_probe.py"
    assert path.is_file(), "restaurant native probe not implemented"
    spec = importlib.util.spec_from_file_location("restaurant_probe_test", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_probe_requests_exact_table_time_and_headcount_in_supported_languages():
    from datetime import date

    probe = module()
    for language in ("et", "en", "ru"):
        data = probe.scenario(language, date(2026, 11, 2))
        assert data["voice"] and data["locale"]
        assert "spa" not in data["request"].casefold()
        assert data["expected_time"] == "18:00" and data["party_size"] == 4
        assert data["consent"] and data["cancel"]


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_probe_recognizes_actual_canonical_table_recap(language):
    from datetime import date
    from tests.test_table_policy import prepare_table, table_state

    state, _ = table_state(language=language)
    asyncio.run(prepare_table(state))
    assert (
        module().scenario(language, date(2026, 11, 2))["recap_marker"]
        in state.render_recap()
    )


@pytest.mark.parametrize("call_id", ["", "a' OR 1=1 --", "0" * 33, None])
def test_probe_rejects_invalid_scope_before_docker(call_id):
    probe = module()
    with patch.object(probe.subprocess, "run") as command:
        with pytest.raises(ValueError, match="scope"):
            probe.read_owned("fixture-worker", call_id)
        command.assert_not_called()


def test_probe_docker_failure_propagates_without_private_output():
    probe = module()
    with patch.object(
        probe.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            [], 7, stdout="PRIVATE", stderr="PRIVATE"
        ),
    ):
        with pytest.raises(RuntimeError, match="read failed") as error:
            probe.read_owned("fixture-worker", "a" * 32)
    assert "PRIVATE" not in str(error.value)


def test_probe_cleanup_is_call_scoped_not_baseline_or_global_deletion():
    probe = module()
    with patch.object(
        probe.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"items": []}), stderr=""
        ),
    ) as command:
        probe.read_owned("fixture-worker", "a" * 32, cleanup=True)
    code = command.call_args.args[0][-2]
    assert "mode=ro" in code
    assert "tel-" in code and "-" in code
    assert "table_writes" in code and "cancel(" in code
    assert "DELETE FROM" not in code and "DROP TABLE" not in code


def test_probe_failure_is_closed_and_never_echoes_transcripts():
    probe = module()
    assert "PRIVATE" not in probe.failure_message(AssertionError("PRIVATE speech"))
    assert "no unique consented booking" in probe.failure_message(
        AssertionError("no unique consented booking")
    )


def test_actual_sqlite_probe_only_cancels_its_scope(tmp_path):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from app.booking.demo_table import DemoTableAdapter
    from app.demo import load_demo_data, scoped_guest

    probe = module()
    path = str(tmp_path / "restaurant.db")
    adapter = DemoTableAdapter(path)
    scope, foreign = "a" * 32, "b" * 32
    day = (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=9)
    ).isoformat()

    async def book(call_id, key):
        offer = (await adapter.search_tables(day, "18:00", 2))[0]
        hold = await adapter.create_hold(offer["table_offer_id"])
        guest = scoped_guest(
            load_demo_data(business="restaurant"), "guest-001", call_id
        )
        result = await adapter.confirm(hold.hold_id, guest, key)
        assert result["ok"]
        return result["booking"]["id"]

    mine = asyncio.run(book(scope, "tel-" + scope + "-confirm"))
    other = asyncio.run(book(foreign, "tel-" + foreign + "-confirm"))
    baseline = asyncio.run(book(foreign, "baseline-confirm"))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            probe.OWNED_CODE,
            json.dumps({"call_id": scope, "cleanup": True}),
        ],
        env={"PATH": "/usr/bin:/bin", "RESTAURANT_STATE_DB": path},
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert [row["id"] for row in json.loads(result.stdout)["items"]] == [mine]
    rows = asyncio.run(adapter.get_operator_bookings(day))["items"]
    assert next(row["status"] for row in rows if row["id"] == mine) == "cancelled"
    assert all(
        row["status"] == "confirmed" for row in rows if row["id"] in {other, baseline}
    )
