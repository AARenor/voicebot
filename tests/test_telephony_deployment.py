import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "telephone_deploy", ROOT / "deploy/telephony/manage.py"
)
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


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
    result = subprocess.run(
        [
            "/usr/bin/python3",
            str(ROOT / "deploy/telephony/manage.py"),
            "validate",
            "--source-container",
            "voicebot-nonexistent-fixture",
        ],
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "no credentials printed" in result.stderr
