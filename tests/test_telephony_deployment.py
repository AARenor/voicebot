import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "telephone_deploy", ROOT / "deploy/telephony/manage.py"
)
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


def test_native_call_log_uses_the_shared_persistent_data_mount():
    compose = (ROOT / "deploy/telephony/compose.yaml").read_text()
    assert "CALLS_DB: /data/calls.db" in compose
    assert "volumes: [booking_state:/data]" in compose


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
