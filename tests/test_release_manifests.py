"""Parse deployment boundaries with public fixtures, never the live environment."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "manifest,service",
    [("compose.yaml", "worker"), ("twilio-compose.yaml", "twilio-bridge")],
)
@pytest.mark.parametrize("release", [None, "a" * 40])
def test_published_image_and_source_identity_reach_only_the_voice_service(
    manifest, service, release
):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose parser unavailable")
    env = {
        name: "public-fixture"
        for name in (
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "GROQ_API_KEY",
            "AZURE_SPEECH_KEY",
            "AZURE_REGION",
            "EASY_BASE_URL",
            "EASY_API_KEY",
            "MEDIA_CONFIG_SHA",
            "LIVEKIT_KEYS",
            "SIP_CONFIG_BODY",
        )
    }
    env.update(
        PATH="/usr/bin:/bin",
        HOME="/nonexistent",
        VOICEBOT_DATA_VOLUME="existing-booking-volume",
    )
    if release:
        env.update(
            VOICEBOT_MEDIA_IMAGE="voicebot-telephone:" + release,
            VOICEBOT_RELEASE_SHA=release,
            VOICEBOT_WEB_SOURCE="existing-web-fixture",
        )
    parsed = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(ROOT / "deploy/telephony" / manifest),
            "config",
            "--format",
            "json",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert parsed.returncode == 0, "synthetic Compose validation failed"
    config = json.loads(parsed.stdout)
    target = config["services"][service]
    assert target["image"] == (
        "voicebot-telephone:" + release if release else "voicebot-telephone:local"
    )
    assert target.get("labels", {}).get("voicebot.release") == (release or "manual")
    assert target.get("labels", {}).get("voicebot.web-source") == (
        "existing-web-fixture" if release else "manual"
    )
    for name, other in config["services"].items():
        if name != service:
            assert "voicebot.release" not in other.get("labels", {})
    if service == "worker":
        assert config["volumes"]["booking_state"] == {
            "name": "existing-booking-volume",
            "external": True,
        }
        assert any(mount["target"] == "/data" for mount in target["volumes"])
