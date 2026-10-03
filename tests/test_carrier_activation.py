import importlib.util
import os
import sys
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location(
        "carrier_activation", ROOT / "deploy/telephony/activate.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_candidate_edge_is_not_a_public_or_carrier_proof():
    activate = module()
    env = {"SIP_PUBLIC_HOST": "8.8.8.8"}
    result = activate.readiness(env, runtime_ready=True)
    assert result["private_runtime_ready"]
    assert result["public_edge_declared"]
    assert not result["public_edge_verified"]
    assert not result["carrier_verified"]
    assert not result["inbound_configuration_ready"]
    assert "ready_for_activation" not in result
    assert "SIP_AUTH_PASSWORD" in result["missing_environment"]


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "192.168.18.24",
        "100.76.78.100",
        "::1",
        "https://example.com",
        "robot.arleserver.cfd",
    ],
)
def test_edge_rejects_private_addresses_and_http_website(host):
    activate = module()
    assert not activate.edge_declared(host)


def test_dns_requires_all_addresses_public():
    activate = module()
    with patch.object(
        activate.socket,
        "getaddrinfo",
        return_value=[
            (0, 0, 0, "", ("8.8.8.8", 5060)),
            (0, 0, 0, "", ("127.0.0.1", 5060)),
        ],
    ):
        assert not activate.edge_declared("sip.example.invalid")


def test_missing_configuration_cannot_provision_or_leak_errors(capsys):
    activate = module()
    with (
        patch.object(activate, "environment", return_value={}),
        patch.object(activate, "runtime_health", return_value=True),
        patch.object(activate, "configure") as configure,
    ):
        assert activate.main(["provision", "--source-container", "fixture"]) == 2
        configure.assert_not_called()
    output = capsys.readouterr()
    assert '"carrier_verified": false' in output.out


def test_docker_failure_is_closed_and_nonzero(capsys):
    activate = module()
    with patch.object(
        activate, "environment", side_effect=RuntimeError("sensitive-value")
    ):
        assert activate.main(["check", "--source-container", "fixture"]) == 1
    assert "sensitive-value" not in capsys.readouterr().err


def test_clean_environment_failure_is_nonzero():
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
    if os.name == "nt":
        clean_env["SystemRoot"] = os.environ["SystemRoot"]
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "deploy/telephony/activate.py"),
            "check",
            "--source-container",
            "voicebot-nonexistent-fixture",
        ],
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_valid_provisioning_still_cannot_claim_carrier_verification(capsys):
    pytest.importorskip("livekit.api")
    from unittest.mock import AsyncMock

    activate = module()
    env = {
        "SIP_NUMBER": "+15555550100",
        "SIP_ALLOWED_CIDRS": "192.0.2.1/32",
        "SIP_AUTH_USER": "fixture-user",
        "SIP_AUTH_PASSWORD": "fixture-only",
        "SIP_PUBLIC_HOST": "8.8.8.8",
    }
    with (
        patch.object(activate, "environment", return_value=env),
        patch.object(activate, "runtime_health", return_value=True),
        patch.object(activate, "configure", new_callable=AsyncMock) as configure,
    ):
        assert activate.main(["provision", "--source-container", "fixture"]) == 0
        configure.assert_awaited_once_with(env)
    output = capsys.readouterr().out
    assert '"carrier_verified": false' in output
    assert "fixture-only" not in output
