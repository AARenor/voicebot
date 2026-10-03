"""Local operator: copy runtime environment in memory, never render secrets.

python deploy/telephony/manage.py validate|build|up --source-container NAME
Add --twilio for the separate HTTPS bridge (validate/up; reuse media image).
Use --worker-only for an existing media stack, and --bridge-source-container
to preserve the existing bridge's inbound configuration when replacing it.
Source must be the existing trusted voicebot container; never use untrusted images.
"""

import argparse
import hashlib
import json
import os
import posixpath
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def environment(source, *, bridge_source=None):
    inspected = subprocess.run(
        ["docker", "inspect", source], capture_output=True, check=True
    )
    container = json.loads(inspected.stdout)[0]
    source_env = dict(v.split("=", 1) for v in container["Config"]["Env"] if "=" in v)
    required = (
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "GROQ_API_KEY",
        "AZURE_SPEECH_KEY",
        "AZURE_REGION",
        "EASY_BASE_URL",
        "EASY_API_KEY",
    )
    if (
        any(not source_env.get(k) for k in required)
        or source_env.get("EASY_DEMO_WRITES") != "1"
    ):
        raise ValueError("source runtime configuration incomplete")
    volumes = [
        m["Name"]
        for m in container["Mounts"]
        if m["Type"] == "volume" and m["Destination"] == "/data"
    ]
    if len(volumes) != 1 or source_env.get("EASY_STATE_DB") != "/data/easy-booking.db":
        raise ValueError("shared booking journal not identified")
    env = dict(os.environ)
    env.update({k: source_env[k] for k in required})
    for k in (
        "EASY_AUTH_SCHEME",
        "EASY_API_PREFIX",
        "GROQ_CHAT_MODEL",
        "GROQ_STT_MODEL",
        "GROQ_MAX_COMPLETION_TOKENS",
        "AZURE_VOICE",
        "AZURE_LANG",
        "AZURE_EN_VOICE",
        "AZURE_EN_LANG",
        "AZURE_RU_VOICE",
        "AZURE_RU_LANG",
        "VOICEBOT_TELEPHONE_LANGUAGE",
        "VOICEBOT_SPEAKING_STYLE",
        "VOICEBOT_SPEECH_RATE",
        "VOICEBOT_RECAP_RATE",
        "VOICEBOT_AGENT_NAME",
    ):
        if k in source_env:
            env[k] = source_env[k]
    env["STAY_DEMO_WRITES"] = source_env.get(
        "STAY_DEMO_WRITES", source_env["EASY_DEMO_WRITES"]
    )
    database_paths = {
        "EASY_STATE_DB": source_env["EASY_STATE_DB"],
        "STAY_STATE_DB": source_env.get("STAY_STATE_DB")
        or posixpath.join(
            posixpath.dirname(source_env["EASY_STATE_DB"]), "stay-booking.db"
        ),
        "CALLS_DB": source_env.get("CALLS_DB", "/data/calls.db"),
    }
    for key, path in database_paths.items():
        # Containers use POSIX paths, even when deployment checks run on Windows.
        # Only /data is shared; an in-memory or other file path would split state.
        if not posixpath.isabs(path) or not posixpath.normpath(path).startswith(
            "/data/"
        ):
            raise ValueError("shared database path not identified")
        env[key] = path
    if bridge_source:
        inspected = subprocess.run(
            ["docker", "inspect", bridge_source], capture_output=True, check=True
        )
        bridge = json.loads(inspected.stdout)[0]
        labels = bridge["Config"].get("Labels") or {}
        if (
            labels.get("com.docker.compose.project") != "voicebot-twilio"
            or labels.get("com.docker.compose.service") != "twilio-bridge"
        ):
            raise ValueError("trusted bridge source required")
        bridge_env = dict(v.split("=", 1) for v in bridge["Config"]["Env"] if "=" in v)
        fields = (
            "TWILIO_AUTH_TOKEN",
            "TWILIO_ACCOUNT_SID",
            "TWILIO_PHONE_NUMBER",
            "LIVEKIT_URL",
        )
        if any(not bridge_env.get(k, "").strip() for k in fields):
            raise ValueError("bridge source configuration incomplete")
        if any(
            bridge_env.get(k) != env[k]
            for k in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
        ):
            raise ValueError("bridge source media configuration differs")
        env.update({k: bridge_env[k] for k in fields})
        bridge_agent = bridge_env.get("VOICEBOT_AGENT_NAME", "voicebot")
        if env.get("VOICEBOT_AGENT_NAME", bridge_agent) != bridge_agent:
            raise ValueError("bridge source agent configuration differs")
        env.setdefault("VOICEBOT_AGENT_NAME", bridge_agent)
        for field, label in (
            (
                "TWILIO_TRAEFIK_ENTRYPOINT",
                "traefik.http.routers.voicebot-twilio.entrypoints",
            ),
            (
                "TWILIO_TRAEFIK_CERTRESOLVER",
                "traefik.http.routers.voicebot-twilio.tls.certresolver",
            ),
        ):
            if labels.get(label):
                env[field] = labels[label]
    env["VOICEBOT_DATA_VOLUME"] = volumes[0]
    env["MEDIA_CONFIG_SHA"] = hashlib.sha256(
        (ROOT / "deploy/telephony/livekit.yaml").read_bytes()
    ).hexdigest()
    env["LIVEKIT_KEYS"] = env["LIVEKIT_API_KEY"] + ": " + env["LIVEKIT_API_SECRET"]
    # JSON is valid YAML. Credentials stay only in process/container environment.
    env["SIP_CONFIG_BODY"] = json.dumps(
        {
            "api_key": env["LIVEKIT_API_KEY"],
            "api_secret": env["LIVEKIT_API_SECRET"],
            "ws_url": "ws://livekit:7880",
            "redis": {"address": "voicebot-media-redis:6379"},
            "sip_port": 5060,
            "rtp_port": "10000-10100",
            "use_external_ip": False,
            "logging": {"level": "error"},
        }
    )
    return env


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["validate", "build", "up"])
    p.add_argument("--source-container", required=True)
    p.add_argument("--bridge-source-container")
    p.add_argument("--worker-only", action="store_true")
    p.add_argument(
        "--twilio",
        action="store_true",
        help="HTTPS bridge validate/up; build media image first",
    )
    args = p.parse_args()
    if args.twilio and args.action == "build":
        p.error("build the media worker image without --twilio first")
    if args.bridge_source_container and not (args.twilio or args.worker_only):
        p.error("bridge source requires --twilio or --worker-only")
    if args.worker_only and (args.twilio or args.action != "up"):
        p.error("worker-only requires native up")
    try:
        env = environment(
            args.source_container, bridge_source=args.bridge_source_container
        )
        compose = [
            "docker",
            "compose",
            "-p",
            "voicebot-twilio" if args.twilio else "livekit",
            "-f",
            str(
                ROOT
                / "deploy/telephony"
                / ("twilio-compose.yaml" if args.twilio else "compose.yaml")
            ),
        ]
        result = subprocess.run(
            compose + ["config", "-q"], env=env, capture_output=True
        )
        if result.returncode:
            raise ValueError(
                "Compose validation failed (details withheld to protect environment)"
            )
        if args.action == "validate":
            print(
                "PASS: HTTPS bridge configuration"
                if args.twilio
                else "PASS: private media configuration and shared persistent journal"
            )
            return 0
        cmd = (
            ["build", "worker"]
            if args.action == "build"
            else ["up", "-d", "--no-build"]
        )
        if args.worker_only:
            cmd += ["--no-deps", "worker"]
        return subprocess.run(compose + cmd, env=env, cwd=ROOT).returncode
    except Exception:
        print(
            "FAIL: telephone deployment prerequisite or Docker operation failed; no credentials printed",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
