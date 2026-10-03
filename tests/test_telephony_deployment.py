import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "telephone_deploy", ROOT / "deploy/telephony/manage.py"
)
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


def test_native_call_log_uses_the_shared_persistent_data_mount():
    compose = (ROOT / "deploy/telephony/compose.yaml").read_text()
    assert "CALLS_DB: ${CALLS_DB:-/data/calls.db}" in compose
    assert "volumes: [booking_state:/data]" in compose


def source_configuration(**overrides):
    values = {
        key: "fixture"
        for key in (
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "GROQ_API_KEY",
            "AZURE_SPEECH_KEY",
            "AZURE_REGION",
            "EASY_BASE_URL",
            "EASY_API_KEY",
        )
    }
    values.update(EASY_DEMO_WRITES="1", EASY_STATE_DB="/data/easy-booking.db")
    values.update(overrides)
    inspected = [
        {
            "Config": {"Env": [key + "=" + value for key, value in values.items()]},
            "Mounts": [
                {
                    "Type": "volume",
                    "Destination": "/data",
                    "Name": "existing-booking-volume",
                }
            ],
        }
    ]
    return subprocess.CompletedProcess([], 0, stdout=json.dumps(inspected).encode())


def test_restaurant_deploy_requires_no_legacy_credentials_or_writer_flag():
    result = source_configuration(
        EASY_BASE_URL="",
        EASY_API_KEY="",
        EASY_DEMO_WRITES="0",
        RESTAURANT_STATE_DB="/data/custom-tables.sqlite",
    )
    with (
        patch.dict(
            "os.environ", {"RESTAURANT_STATE_DB": "/unrelated/tables.db"}, clear=True
        ),
        patch.object(manage.subprocess, "run", return_value=result),
    ):
        env = manage.environment("trusted-web-fixture")
    assert env["VOICEBOT_BUSINESS"] == "restaurant"
    assert env["RESTAURANT_STATE_DB"] == "/data/custom-tables.sqlite"
    assert env["VOICEBOT_DATA_VOLUME"] == "existing-booking-volume"
    compose = (ROOT / "deploy/telephony/compose.yaml").read_text()
    assert (
        "RESTAURANT_STATE_DB: ${RESTAURANT_STATE_DB:-/data/restaurant-booking.db}"
        in compose
    )
    assert "VOICEBOT_BUSINESS: ${VOICEBOT_BUSINESS:-restaurant}" in compose


@pytest.mark.parametrize(
    "path", [":memory:", "/tmp/tables.db", "/data/../tmp/tables.db", ""]
)
def test_restaurant_deploy_rejects_nonshared_or_ephemeral_database(path):
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(
            manage.subprocess,
            "run",
            return_value=source_configuration(RESTAURANT_STATE_DB=path),
        ),
    ):
        with pytest.raises(ValueError, match="shared database path"):
            manage.environment("trusted-web-fixture")


@pytest.mark.parametrize(
    "paths,expected",
    [
        ({}, {"STAY_STATE_DB": "/data/stay-booking.db", "CALLS_DB": "/data/calls.db"}),
        (
            {"STAY_STATE_DB": ""},
            {"STAY_STATE_DB": "/data/stay-booking.db", "CALLS_DB": "/data/calls.db"},
        ),
        (
            {
                "STAY_STATE_DB": "/data/custom-rooms.sqlite",
                "CALLS_DB": "/data/custom-history.sqlite",
            },
            {
                "STAY_STATE_DB": "/data/custom-rooms.sqlite",
                "CALLS_DB": "/data/custom-history.sqlite",
            },
        ),
        (
            {
                "STAY_STATE_DB": "/data/room-state/rooms",
                "CALLS_DB": "/data/history/../calls",
            },
            {
                "STAY_STATE_DB": "/data/room-state/rooms",
                "CALLS_DB": "/data/history/../calls",
            },
        ),
    ],
)
def test_source_database_paths_and_defaults_override_unrelated_caller_paths(
    paths, expected
):
    with (
        patch.dict(
            "os.environ",
            {
                "EASY_STATE_DB": "/unrelated/spa.db",
                "STAY_STATE_DB": "/unrelated/rooms.db",
                "CALLS_DB": "/unrelated/calls.db",
            },
            clear=True,
        ),
        patch.object(
            manage.subprocess, "run", return_value=source_configuration(**paths)
        ),
    ):
        env = manage.environment("trusted-web-fixture")
    assert {key: env[key] for key in expected} == expected
    assert env["EASY_STATE_DB"] == "/data/easy-booking.db"
    assert env["VOICEBOT_DATA_VOLUME"] == "existing-booking-volume"
    compose = (ROOT / "deploy/telephony/compose.yaml").read_text()
    assert "STAY_STATE_DB: ${STAY_STATE_DB:-/data/stay-booking.db}" in compose
    assert "CALLS_DB: ${CALLS_DB:-/data/calls.db}" in compose


@pytest.mark.parametrize(
    "source_flags,caller_flag,expected",
    [
        ({}, "0", "1"),
        ({"STAY_DEMO_WRITES": ""}, "1", ""),
        ({"STAY_DEMO_WRITES": "0"}, "1", "0"),
        ({"STAY_DEMO_WRITES": "1"}, "0", "1"),
    ],
)
def test_source_effective_room_write_flag_overrides_caller_and_preserves_empty(
    source_flags, caller_flag, expected
):
    with (
        patch.dict("os.environ", {"STAY_DEMO_WRITES": caller_flag}, clear=True),
        patch.object(
            manage.subprocess, "run", return_value=source_configuration(**source_flags)
        ),
    ):
        env = manage.environment("trusted-web-fixture")
    assert env["STAY_DEMO_WRITES"] == expected
    compose = (ROOT / "deploy/telephony/compose.yaml").read_text()
    assert "STAY_DEMO_WRITES: ${STAY_DEMO_WRITES-1}" in compose


@pytest.mark.parametrize("key", ["STAY_STATE_DB", "CALLS_DB"])
@pytest.mark.parametrize(
    "path",
    [
        ":memory:",
        "relative.db",
        "/tmp/other.db",
        "/data-other/db",
        "/data/../tmp/db",
        "/data",
    ],
)
def test_database_paths_outside_shared_mount_fail_before_compose(key, path, capsys):
    with (
        patch.dict("os.environ", {}, clear=True),
        patch(
            "sys.argv",
            ["manage", "validate", "--source-container", "trusted-web-fixture"],
        ),
        patch.object(
            manage.subprocess, "run", return_value=source_configuration(**{key: path})
        ) as run,
    ):
        assert manage.main() == 1
    assert run.call_count == 1  # Only captured source inspection, no Compose/write.
    output = capsys.readouterr()
    assert not output.out
    assert "shared database path" not in output.err
    assert "no credentials printed" in output.err


def test_explicit_empty_call_database_is_not_silently_replaced_with_persistent_file():
    # SQLite's empty filename is a private temporary database, not the shared log.
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(
            manage.subprocess, "run", return_value=source_configuration(CALLS_DB="")
        ),
    ):
        with pytest.raises(ValueError, match="^shared database path not identified$"):
            manage.environment("trusted-web-fixture")


def test_english_voice_and_mode_survive_trusted_environment_copy():
    values = {
        key: "fixture"
        for key in (
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "GROQ_API_KEY",
            "AZURE_SPEECH_KEY",
            "AZURE_REGION",
            "EASY_BASE_URL",
            "EASY_API_KEY",
        )
    }
    values.update(
        EASY_DEMO_WRITES="1",
        EASY_STATE_DB="/data/easy-booking.db",
        VOICEBOT_TELEPHONE_LANGUAGE="en",
        AZURE_EN_VOICE="en-GB-SoniaNeural",
        AZURE_EN_LANG="en-GB",
        VOICEBOT_SPEAKING_STYLE="neutral",
        VOICEBOT_SPEECH_RATE="1.0",
        VOICEBOT_RECAP_RATE="0.92",
    )
    inspected = [
        {
            "Config": {"Env": [key + "=" + value for key, value in values.items()]},
            "Mounts": [
                {
                    "Type": "volume",
                    "Destination": "/data",
                    "Name": "existing-booking-volume",
                }
            ],
        }
    ]
    result = subprocess.CompletedProcess([], 0, stdout=json.dumps(inspected).encode())
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(manage.subprocess, "run", return_value=result),
    ):
        env = manage.environment("trusted-web-fixture")
    assert env["AZURE_EN_VOICE"] == "en-GB-SoniaNeural"
    assert env["AZURE_EN_LANG"] == "en-GB"
    assert env["VOICEBOT_TELEPHONE_LANGUAGE"] == "en"
    assert env["VOICEBOT_SPEAKING_STYLE"] == "neutral"
    assert env["VOICEBOT_SPEECH_RATE"] == "1.0"
    assert env["VOICEBOT_RECAP_RATE"] == "0.92"
    assert env["VOICEBOT_DATA_VOLUME"] == "existing-booking-volume"
    compose = (ROOT / "deploy/telephony/compose.yaml").read_text()
    for key in (
        "AZURE_EN_VOICE",
        "AZURE_EN_LANG",
        "VOICEBOT_TELEPHONE_LANGUAGE",
        "VOICEBOT_SPEAKING_STYLE",
        "VOICEBOT_SPEECH_RATE",
        "VOICEBOT_RECAP_RATE",
    ):
        assert key + ": ${" + key in compose


def test_docker_failure_is_nonzero_without_sensitive_output(capsys):
    with (
        patch("sys.argv", ["manage", "up", "--source-container", "fixture"]),
        patch.object(
            manage, "environment", side_effect=RuntimeError("sensitive internal data")
        ),
    ):
        assert manage.main() == 1
    output = capsys.readouterr()
    assert "sensitive internal data" not in output.err


def test_compose_failure_never_proceeds_to_deployment(capsys):
    with (
        patch("sys.argv", ["manage", "up", "--source-container", "fixture"]),
        patch.object(manage, "environment", return_value={}),
        patch.object(
            manage.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 9, stdout="sensitive", stderr="sensitive"
            ),
        ) as run,
    ):
        assert manage.main() == 1
        assert run.call_count == 1
    assert "sensitive" not in capsys.readouterr().err


def test_up_propagates_docker_failure():
    with (
        patch("sys.argv", ["manage", "up", "--source-container", "fixture"]),
        patch.object(manage, "environment", return_value={}),
        patch.object(
            manage.subprocess,
            "run",
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 17),
            ],
        ),
    ):
        assert manage.main() == 17


def test_missing_source_fails_in_clean_environment():
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
    if os.name == "nt":
        clean_env["SystemRoot"] = os.environ["SystemRoot"]
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "deploy/telephony/manage.py"),
            "validate",
            "--source-container",
            "voicebot-nonexistent-fixture",
        ],
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "no credentials printed" in result.stderr


def test_twilio_uses_separate_project_without_changing_private_media(capsys):
    with (
        patch(
            "sys.argv", ["manage", "up", "--twilio", "--source-container", "fixture"]
        ),
        patch.object(manage, "environment", return_value={}),
        patch.object(
            manage.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ) as run,
    ):
        assert manage.main() == 0
    for invocation in run.call_args_list:
        command = invocation.args[0]
        assert command[command.index("-p") + 1] == "voicebot-twilio"
        assert command[command.index("-f") + 1] == str(
            ROOT / "deploy/telephony/twilio-compose.yaml"
        )
    assert run.call_args_list[-1].args[0][-3:] == ["up", "-d", "--no-build"]


def test_twilio_compose_failure_does_not_launch_or_leak(capsys):
    with (
        patch(
            "sys.argv", ["manage", "up", "--twilio", "--source-container", "fixture"]
        ),
        patch.object(manage, "environment", return_value={}),
        patch.object(
            manage.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, stderr="PRIVATE"),
        ) as run,
    ):
        assert manage.main() == 1
        assert run.call_count == 1
    assert "PRIVATE" not in capsys.readouterr().err
