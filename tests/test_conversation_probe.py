import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import httpx

pytest.importorskip("livekit.rtc")
spec = importlib.util.spec_from_file_location(
    "conversation_probe",
    Path(__file__).resolve().parents[1] / "deploy/telephony/conversation_probe.py",
)


def module():
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def response(rows):
    return httpx.Response(
        200, json=rows, request=httpx.Request("GET", "http://fixture.invalid")
    )


def test_cleanup_never_deletes_baseline_appointments_or_customers():
    probe = module()
    client = SimpleNamespace(
        get=AsyncMock(
            side_effect=[
                response(
                    [
                        {"id": 1, "customerId": 1},
                        {"id": 2, "customerId": 2},
                    ]
                ),
                response(
                    [
                        {"id": 1, "email": "demo.esimene@example.invalid"},
                        {"id": 2, "email": "demo.esimene@example.invalid"},
                    ]
                ),
            ]
        ),
        delete=AsyncMock(return_value=SimpleNamespace(status_code=204)),
    )
    asyncio.run(probe.cleanup_new(client, {1}, {1}, "demo.esimene@example.invalid"))
    assert [call.args[0] for call in client.delete.await_args_list] == [
        "/appointments/2",
        "/customers/2",
    ]


def test_cleanup_failure_is_not_masked():
    probe = module()
    client = SimpleNamespace(
        get=AsyncMock(
            side_effect=[
                response([{"id": 2, "customerId": 2}]),
                response([{"id": 2, "email": "demo.esimene@example.invalid"}]),
            ]
        ),
        delete=AsyncMock(return_value=SimpleNamespace(status_code=500)),
    )
    with pytest.raises(AssertionError):
        asyncio.run(
            probe.cleanup_new(client, set(), set(), "demo.esimene@example.invalid")
        )


def test_failed_read_cannot_authorize_cleanup():
    probe = module()
    failed = httpx.Response(
        500, json=[], request=httpx.Request("GET", "http://fixture.invalid")
    )
    client = SimpleNamespace(get=AsyncMock(return_value=failed), delete=AsyncMock())
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            probe.cleanup_new(client, set(), set(), "demo.esimene@example.invalid")
        )
    client.delete.assert_not_awaited()


def test_probe_failure_reports_only_allowlisted_assertions():
    probe = module()
    assert "no unique consented booking" in probe.failure_message(
        AssertionError("no unique consented booking")
    )
    assert "private-value" not in probe.failure_message(AssertionError("private-value"))
    assert "no spoken canonical recap" in probe.failure_message(
        AssertionError("no spoken canonical recap")
    )


def test_probe_diagnostics_are_counts_and_boolean_not_transcripts():
    probe = module()
    result = probe.diagnostic_counts(
        ["PRIVATE caller", "Jah, kinnitan selle testbroneeringu."],
        [
            "Fiktiivne testbroneering: PRIVATE",
            "Toiming ei õnnestunud; edu ei ole kinnitatud.",
        ],
    )
    assert result == {
        "final_input_turns": 2,
        "final_reply_count": 2,
        "affirmative_observed": True,
        "cancellation_observed": False,
        "recap_count": 1,
        "failed_action_reply_count": 1,
    }
    assert "PRIVATE" not in repr(result)


def test_synthetic_caller_uses_kert_while_native_reply_remains_anu():
    probe = module()

    class Selected(Exception):
        pass

    env = {
        name: "fixture"
        for name in (
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "AZURE_SPEECH_KEY",
            "AZURE_REGION",
        )
    }
    with (
        patch.object(probe.api, "LiveKitAPI"),
        patch.object(probe.rtc, "Room"),
        patch.object(probe, "AzureTtsClient", side_effect=Selected) as caller,
        pytest.raises(Selected),
    ):
        asyncio.run(probe.run(env))
    assert caller.call_args.args[2:4] == ("et-EE-KertNeural", "et-EE")


def test_english_probe_uses_explicit_date_time_and_english_commitments():
    from datetime import date
    probe = module()
    phrases = probe.scenario("en", date(2026, 11, 2))
    assert phrases["voice"] == "en-US-GuyNeural"
    assert "Monday, 2 November 2026" in phrases["request"]
    assert "nine in the morning" in phrases["request"]
    assert phrases["consent"] == "Yes, I confirm."
    assert phrases["cancel"] == "Please cancel this test booking."
    assert phrases["recap_marker"] == "Fictional test booking:"


def test_english_probe_diagnostics_are_counts_only():
    probe = module()
    result = probe.diagnostic_counts(
        ["PRIVATE caller", "Yes, I confirm.", "Please cancel this test booking."],
        ["Fictional test booking: PRIVATE", "The request failed."],
    )
    assert result["affirmative_observed"] and result["cancellation_observed"]
    assert result["recap_count"] == result["failed_action_reply_count"] == 1
    assert "PRIVATE" not in repr(result)
