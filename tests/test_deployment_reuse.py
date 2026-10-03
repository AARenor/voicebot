"""Deployment keeps trusted runtime settings without restarting unrelated media."""

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "repair_deployment", ROOT / "deploy/telephony/manage.py"
)
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


def web_container():
    settings = {
        "LIVEKIT_API_KEY": "fixture-media",
        "LIVEKIT_API_SECRET": "fixture-media-auth",
        "GROQ_API_KEY": "fixture-groq",
        "AZURE_SPEECH_KEY": "fixture-azure",
        "AZURE_REGION": "northeurope",
        "EASY_BASE_URL": "http://fixture.invalid",
        "EASY_API_KEY": "fixture-booking",
        "EASY_DEMO_WRITES": "1",
        "EASY_STATE_DB": "/data/easy-booking.db",
        "VOICEBOT_AGENT_NAME": "fixture-alternate",
        "GROQ_CHAT_MODEL": "openai/gpt-oss-120b",
        "GROQ_STT_MODEL": "whisper-large-v3",
    }
    return {
        "Config": {"Env": [f"{k}={v}" for k, v in settings.items()]},
        "Mounts": [{"Type": "volume", "Destination": "/data", "Name": "fixture-state"}],
    }


def bridge_container():
    settings = {
        "TWILIO_AUTH_TOKEN": "fixture-bridge-auth",
        "TWILIO_ACCOUNT_SID": "AC" + "1" * 32,
        "TWILIO_PHONE_NUMBER": "+15555550100",
        "LIVEKIT_URL": "ws://livekit:7880",
        "LIVEKIT_API_KEY": "fixture-media",
        "LIVEKIT_API_SECRET": "fixture-media-auth",
        "VOICEBOT_AGENT_NAME": "fixture-alternate",
    }
    return {
        "Config": {
            "Env": [f"{k}={v}" for k, v in settings.items()],
            "Labels": {
                "com.docker.compose.project": "voicebot-twilio",
                "com.docker.compose.service": "twilio-bridge",
                "traefik.http.routers.voicebot-twilio.entrypoints": "https",
                "traefik.http.routers.voicebot-twilio.tls.certresolver": "letsencrypt",
            },
        }
    }


def inspected(command, **kwargs):
    container = (
        bridge_container() if command[-1] == "fixture-bridge" else web_container()
    )
    return subprocess.CompletedProcess(command, 0, json.dumps([container]).encode())


def test_worker_agent_selection_survives_environment_copy():
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(manage.subprocess, "run", inspected),
    ):
        env = manage.environment("fixture-web")
    assert env.get("VOICEBOT_AGENT_NAME") == "fixture-alternate"
    assert env["VOICEBOT_DATA_VOLUME"] == "fixture-state"
    assert env["GROQ_CHAT_MODEL"] == "openai/gpt-oss-120b"


@pytest.mark.parametrize(
    "field,value",
    [
        ("AZURE_RU_VOICE", "ru-RU-SvetlanaNeural"),
        ("AZURE_RU_LANG", "ru-RU"),
        ("VOICEBOT_TELEPHONE_LANGUAGE", "auto"),
        ("VOICEBOT_SPEAKING_STYLE", "natural"),
        ("VOICEBOT_SPEECH_RATE", "0.98"),
        ("VOICEBOT_RECAP_RATE", "0.94"),
    ],
)
def test_published_speech_settings_survive_web_to_worker_copy(field, value):
    container = web_container()
    container["Config"]["Env"].append(field + "=" + value)

    def inspect(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps([container]).encode())

    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(manage.subprocess, "run", inspect),
    ):
        env = manage.environment("fixture-web")
    assert env.get(field) == value


def test_bridge_redeployment_preserves_existing_inbound_configuration(capsys):
    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(manage.subprocess, "run", inspected),
    ):
        env = manage.environment("fixture-web", bridge_source="fixture-bridge")
    assert env["TWILIO_AUTH_TOKEN"] == "fixture-bridge-auth"
    assert env["TWILIO_ACCOUNT_SID"] == "AC" + "1" * 32
    assert env["TWILIO_PHONE_NUMBER"] == "+15555550100"
    assert env["VOICEBOT_AGENT_NAME"] == "fixture-alternate"
    assert env["LIVEKIT_URL"] == "ws://livekit:7880"
    assert capsys.readouterr().out == ""


def test_worker_only_deployment_does_not_restart_livekit_sip_or_redis():
    with (
        patch(
            "sys.argv",
            ["manage", "up", "--source-container", "fixture-web", "--worker-only"],
        ),
        patch.object(manage, "environment", return_value={}),
        patch.object(
            manage.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run,
    ):
        assert manage.main() == 0
    command = run.call_args_list[-1].args[0]
    assert command[-1] == "worker"
    assert "--no-deps" in command


def test_unrelated_container_cannot_supply_bridge_configuration():
    untrusted = bridge_container()
    untrusted["Config"]["Labels"]["com.docker.compose.project"] = "other-project"

    def inspect(command, **kwargs):
        container = untrusted if command[-1] == "fixture-bridge" else web_container()
        return subprocess.CompletedProcess(command, 0, json.dumps([container]).encode())

    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(manage.subprocess, "run", inspect),
        pytest.raises(ValueError, match="bridge source"),
    ):
        manage.environment("fixture-web", bridge_source="fixture-bridge")


def test_worker_only_can_reuse_the_existing_bridge_agent_name():
    with (
        patch(
            "sys.argv",
            [
                "manage",
                "up",
                "--source-container",
                "fixture-web",
                "--worker-only",
                "--bridge-source-container",
                "fixture-bridge",
            ],
        ),
        patch.object(
            manage,
            "environment",
            return_value={"VOICEBOT_AGENT_NAME": "fixture-alternate"},
        ) as environment,
        patch.object(
            manage.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ),
    ):
        assert manage.main() == 0
    assert environment.call_args.kwargs["bridge_source"] == "fixture-bridge"


def test_mismatched_web_and_bridge_agent_names_fail_before_replacement():
    bridge = bridge_container()
    bridge["Config"]["Env"] = [
        "VOICEBOT_AGENT_NAME=other-agent" if s.startswith("VOICEBOT_AGENT_NAME=") else s
        for s in bridge["Config"]["Env"]
    ]

    def inspect(command, **kwargs):
        container = bridge if command[-1] == "fixture-bridge" else web_container()
        return subprocess.CompletedProcess(command, 0, json.dumps([container]).encode())

    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(manage.subprocess, "run", inspect),
        pytest.raises(ValueError, match="agent"),
    ):
        manage.environment("fixture-web", bridge_source="fixture-bridge")
