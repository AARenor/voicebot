"""Release decisions use real reconciler code; only Docker/Git are doubled."""

import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from types import ModuleType, SimpleNamespace

import pytest

fcntl = pytest.importorskip("fcntl", reason="Linux host release controller")


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/telephony/release_sync.py"
SHA = "1234567890abcdef" * 2 + "12345678"
WEB = "a" * 64
WORKER = "livekit-worker-1"
BRIDGE = "voicebot-twilio-twilio-bridge-1"
PRIVATE = "SYNTHETIC_PRIVATE_OUTPUT_NEVER_PRINT"
ARTIFACT = "sha256:" + "9" * 64
SOURCE_LABELS = {
    "coolify.managed": "true",
    "coolify.type": "application",
    "coolify.applicationId": "13",
    "coolify.environmentName": "production",
    "coolify.pullRequestId": "0",
}
REQUIRED = (
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "GROQ_API_KEY",
    "AZURE_SPEECH_KEY",
    "AZURE_REGION",
    "EASY_BASE_URL",
    "EASY_API_KEY",
)
TWILIO = ("TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID", "TWILIO_PHONE_NUMBER")
PROFILES = {
    "GROQ_CHAT_MODEL": "fixture-model",
    "GROQ_STT_MODEL": "whisper-large-v3",
    "GROQ_MAX_COMPLETION_TOKENS": "2048",
    "AZURE_REGION": "synthetic-azure_region",
    "AZURE_VOICE": "et-EE-AnuNeural",
    "AZURE_LANG": "et-EE",
    "AZURE_EN_VOICE": "en-GB-SoniaNeural",
    "AZURE_EN_LANG": "en-GB",
    "AZURE_RU_VOICE": "ru-RU-SvetlanaNeural",
    "AZURE_RU_LANG": "ru-RU",
    "VOICEBOT_TELEPHONE_LANGUAGE": "en",
    "VOICEBOT_SPEAKING_STYLE": "neutral",
    "VOICEBOT_SPEECH_RATE": "1.0",
    "VOICEBOT_RECAP_RATE": "0.92",
    "VOICEBOT_AGENT_NAME": "kept-agent",
    "VOICEBOT_TELEPHONE_DEMO": "1",
}


def container(name, identity, image, labels, values, data=False):
    return {
        "Id": identity,
        "Image": "sha256:" + identity,
        "Name": "/" + name,
        "Config": {
            "Image": image,
            "Labels": labels,
            "Env": [f"{k}={v}" for k, v in values.items()],
        },
        "State": {
            "Running": True,
            "Status": "running",
            "Health": {"Status": "healthy"},
            "ExitCode": 0,
            "OOMKilled": False,
        },
        "Mounts": (
            [
                {
                    "Type": "volume",
                    "Destination": "/data",
                    "Name": "preserved-booking-state",
                }
            ]
            if data
            else []
        ),
    }


def archive(extra=None):
    contents = {
        f"deploy/telephony/{name}": (ROOT / "deploy/telephony" / name).read_bytes()
        for name in ("manage.py", "livekit.yaml", "compose.yaml", "twilio-compose.yaml")
    }
    contents.update(extra or {})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, body in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(body)
            tar.addfile(member, io.BytesIO(body))
    return stream.getvalue()


class ExternalCommands:
    def __init__(self, repository):
        self.repository = repository
        self.origin = "https://github.com/Parnuhakk/voicebot.git"
        self.master = SHA
        self.source_ids = [WEB]
        self.rooms = [0, 0]
        self.calls = []
        self.timeouts = []
        self.fail = None
        self.after_build = lambda: None
        self.after_up = lambda name: None
        self.after_stop = lambda: None
        self.after_probe = lambda: None
        self.payload = archive()
        self.artifact = ARTIFACT
        self.profiles = dict(PROFILES)
        source_env = {key: "synthetic-" + key.lower() for key in REQUIRED}
        source_env.update(
            EASY_DEMO_WRITES="1",
            EASY_STATE_DB="/data/easy-booking.db",
            LIVEKIT_URL="ws://livekit:7880",
            AZURE_EN_LANG="en-GB",
            AZURE_EN_VOICE="en-GB-SoniaNeural",
            VOICEBOT_TELEPHONE_LANGUAGE="en",
            GROQ_CHAT_MODEL="fixture-model",
            VOICEBOT_SPEECH_RATE="1.0",
            VOICEBOT_SPEAKING_STYLE="neutral",
            VOICEBOT_RECAP_RATE="0.92",
            **{key: "wrong-source-" + key.lower() for key in TWILIO},
        )
        media_env = {key: source_env[key] for key in REQUIRED[:2]}
        media_env.update(
            LIVEKIT_URL="ws://livekit:7880", VOICEBOT_AGENT_NAME="kept-agent"
        )
        bridge_labels = {
            "com.docker.compose.project": "voicebot-twilio",
            "com.docker.compose.service": "twilio-bridge",
            "traefik.http.routers.voicebot-twilio.entrypoints": "kept-https",
            "traefik.http.routers.voicebot-twilio.tls.certresolver": "kept-resolver",
        }
        self.containers = {
            "web": container(
                "zs7s830dsrlo4j81s0ohgpgc-web",
                WEB,
                "zs7s830dsrlo4j81s0ohgpgc:" + SHA,
                dict(SOURCE_LABELS),
                source_env,
                True,
            ),
            WORKER: container(
                WORKER,
                "b" * 64,
                "voicebot-telephone:local",
                {
                    "com.docker.compose.project": "livekit",
                    "com.docker.compose.service": "worker",
                },
                {**media_env, **PROFILES},
                True,
            ),
            BRIDGE: container(
                BRIDGE,
                "c" * 64,
                "voicebot-telephone:local",
                bridge_labels,
                {**media_env, **{key: "" for key in TWILIO}},
            ),
        }

    def __call__(self, argv, **kwargs):
        argv = list(map(str, argv))
        assert kwargs.get("capture_output") is True
        assert 0 < kwargs.get("timeout", 0) <= 1200
        self.calls.append((argv, dict(kwargs.get("env", {}))))
        self.timeouts.append(kwargs["timeout"])
        operation = argv[3] if argv[0] == "git" else argv[1]
        if operation == "compose":
            operation = argv[argv.index("-f") + 2]
            if operation == "up":
                operation = "up-" + argv[-1]
        if self.fail == "timeout-" + operation:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], PRIVATE, PRIVATE)
        if self.fail == operation:
            raise subprocess.CalledProcessError(17, argv, PRIVATE, PRIVATE)
        out = b""
        if argv[0] == "git":
            assert argv[1:3] == ["-C", str(self.repository)]
            if operation == "remote":
                out = (self.origin + "\n").encode()
            elif operation == "rev-parse":
                out = (
                    str(self.repository)
                    if argv[-1] == "--show-toplevel"
                    else self.master
                ).encode()
            elif operation == "archive":
                assert argv[-1] == SHA
                out = self.payload
            else:
                assert operation == "fetch"
        elif operation == "ps":
            assert "label=coolify.applicationId=13" in argv and "--no-trunc" in argv
            out = ("\n".join(self.source_ids) + "\n").encode()
        elif operation == "inspect":
            selected = [
                c for key, c in self.containers.items() if argv[-1] in (key, c["Id"])
            ]
            if not selected:
                raise subprocess.CalledProcessError(1, argv, PRIVATE, PRIVATE)
            out = json.dumps(copy.deepcopy(selected)).encode()
        elif operation == "exec":
            assert argv[2] == self.containers[WORKER]["Id"]
            assert argv[3:5] == ["python", "-c"] and len(argv) == 6
            out = (str(self.rooms.pop(0)) + "\n").encode()
            if not self.rooms:
                self.after_probe()
        elif operation == "image":
            assert argv[2:5] == ["inspect", "--format", "{{.Id}}"]
            assert argv[-1] == "voicebot-telephone:" + SHA
            out = (self.artifact + "\n").encode()
        elif operation == "run":
            assert "--rm" in argv and "--network" in argv
            assert argv[argv.index("--network") + 1] == "coolify"
            assert ARTIFACT in argv
            for key in REQUIRED[:2]:
                assert key in argv and not any(key + "=" in arg for arg in argv)
            out = (str(self.rooms.pop(0)) + "\n").encode()
        elif operation == "build":
            assert argv[-2:] == ["build", "worker"]
            self.after_build()
        elif operation == "stop":
            assert argv[2:4] == ["--time", "720"]
            target = self.containers[BRIDGE]
            assert argv[-1] == target["Id"]
            target["State"].update(Running=False, Status="exited")
            self.after_stop()
        elif operation == "start":
            target = self.containers[BRIDGE]
            assert argv[-1] == target["Id"]
            target["State"].update(Running=True, Status="running")
        elif operation.startswith("up-"):
            name = WORKER if argv[-1] == "worker" else BRIDGE
            target = self.containers[name]
            env = kwargs["env"]
            target["Id"] = ("d" if name == WORKER else "e") * 64
            target["Config"]["Image"] = env["VOICEBOT_MEDIA_IMAGE"]
            target["Image"] = ARTIFACT
            target["State"].update(Running=True, Status="running")
            target["State"]["Health"]["Status"] = "healthy"
            if name == WORKER:
                values = dict(item.split("=", 1) for item in target["Config"]["Env"])
                values.update(self.profiles)
                target["Config"]["Env"] = [f"{k}={v}" for k, v in values.items()]
            target["Config"]["Labels"].update(
                {
                    "voicebot.release": env["VOICEBOT_RELEASE_SHA"],
                    "voicebot.web-source": env["VOICEBOT_WEB_SOURCE"],
                }
            )
            self.after_up(name)
        else:
            assert operation == "config"
            if "--format" in argv:
                assert argv[-3:] == ["config", "--format", "json"]
                for key in REQUIRED[:2] + (
                    "GROQ_API_KEY",
                    "AZURE_SPEECH_KEY",
                    "EASY_API_KEY",
                ):
                    assert kwargs["env"][key] == "withheld"
                out = json.dumps(
                    {"services": {"worker": {"environment": self.profiles}}}
                ).encode()
            else:
                assert argv[-2:] == ["config", "-q"]
        return subprocess.CompletedProcess(argv, 0, out, b"")

    def mutations(self):
        return [
            cmd
            for cmd, _ in self.calls
            if "compose" in cmd and any(x in cmd for x in ("build", "up", "down"))
        ]


@pytest.fixture
def lane(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    state = tmp_path / "state"
    double = ExternalCommands(repository)

    def invoke():
        assert SCRIPT.is_file(), "release reconciler is not implemented"
        spec = importlib.util.spec_from_file_location("release_sync_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(module.subprocess, "run", double)
        monkeypatch.setattr(module.sys, "dont_write_bytecode", True)
        monkeypatch.setattr(
            module.os,
            "environ",
            {
                "PATH": "/synthetic-host-path",
                "LIVEKIT_API_SECRET": PRIVATE,
                "AZURE_LANG": "wrong-host-language",
                **{key: PRIVATE for key in TWILIO},
            },
        )
        return module.main(
            ["--repository", str(repository), "--state-directory", str(state)]
        )

    return SimpleNamespace(
        external=double,
        repository=repository,
        state=state,
        run=invoke,
    )


def test_success_replaces_only_worker_and_bridge_from_exact_archived_revision(
    lane, capsys
):
    assert lane.run() == 0
    assert capsys.readouterr().out.strip() == "PASS: release_synced"
    commands = lane.external.mutations()
    assert len(commands) == 3
    assert commands[0][-2:] == ["build", "worker"]
    for command, project, service in zip(
        commands[1:], ("livekit", "voicebot-twilio"), ("worker", "twilio-bridge")
    ):
        assert command[command.index("-p") + 1] == project
        assert command[-10:] == [
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            "120",
            service,
        ]
        release = Path(command[command.index("-f") + 1])
        assert release.is_relative_to(lane.state)
        assert not release.exists(), "temporary release must be removed"
    git_commands = [c for c, _ in lane.external.calls if c[0] == "git"]
    assert any("fetch" in c and "origin" in c for c in git_commands)
    assert any(c[-3:] == ["archive", "--format=tar", SHA] for c in git_commands)


@pytest.mark.parametrize(
    "change", ["multiple", "none", "unhealthy", "stopped", "untrusted"]
)
def test_source_discovery_rejects_ambiguous_or_untrusted_web_without_mutation(
    lane, change, capsys
):
    source = lane.external.containers["web"]
    if change == "multiple":
        lane.external.source_ids.append("f" * 64)
    elif change == "none":
        lane.external.source_ids = []
    elif change == "unhealthy":
        source["State"]["Health"]["Status"] = "unhealthy"
    elif change == "stopped":
        source["State"]["Running"] = False
    else:
        source["Config"]["Labels"]["coolify.environmentName"] = "preview"
    assert lane.run() == 1
    assert not lane.external.mutations()
    assert capsys.readouterr().err.strip() == "FAIL: release_sync_failed"


@pytest.mark.parametrize(
    "image",
    [
        "wrong:" + SHA,
        "zs7s830dsrlo4j81s0ohgpgc:master",
        "zs7s830dsrlo4j81s0ohgpgc:" + "a" * 39,
        "zs7s830dsrlo4j81s0ohgpgc:" + SHA + "@sha256:bad",
    ],
)
def test_malformed_published_revision_is_rejected_before_fetch_or_mutation(lane, image):
    lane.external.containers["web"]["Config"]["Image"] = image
    assert lane.run() == 1
    assert not lane.external.mutations()
    assert not any("fetch" in c for c, _ in lane.external.calls)


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/Parnuhakk/voicebot",
        "git@github.com:Parnuhakk/voicebot.git",
        "ssh://git@github.com/Parnuhakk/voicebot.git",
    ],
)
def test_canonical_https_and_ssh_origins_are_accepted(lane, origin):
    lane.external.origin = origin
    assert lane.run() == 0


@pytest.mark.parametrize(
    "origin",
    [
        "https://auth@github.com/Parnuhakk/voicebot.git",
        "https://github.com/attacker/voicebot.git",
        "https://github.com/Parnuhakk/voicebot.git?credential=x",
        "ssh://root@github.com/Parnuhakk/voicebot.git",
    ],
)
def test_auth_bearing_or_noncanonical_origins_never_fetch(lane, origin):
    lane.external.origin = origin
    assert lane.run() == 1
    assert not any("fetch" in c for c, _ in lane.external.calls)


def test_master_mismatch_defers_without_mutation(lane, capsys):
    lane.external.master = "f" * 40
    assert lane.run() == 0
    assert not lane.external.mutations()
    assert capsys.readouterr().out.strip() == "DEFER: release_master_mismatch"


@pytest.mark.parametrize(
    "target,change",
    [
        (WORKER, "mount"),
        (WORKER, "bind"),
        (WORKER, "project"),
        (BRIDGE, "service"),
    ],
)
def test_existing_target_project_health_and_persistent_mount_are_required(
    lane, target, change
):
    selected = lane.external.containers[target]
    if change == "mount":
        selected["Mounts"][0]["Name"] = "different-journal"
    elif change == "bind":
        selected["Mounts"][0]["Type"] = "bind"
    else:
        selected["Config"]["Labels"]["com.docker.compose." + change] = "wrong"
    assert lane.run() == 1
    assert not lane.external.mutations()


@pytest.mark.parametrize(
    "target,key",
    [
        (WORKER, "VOICEBOT_AGENT_NAME"),
        (BRIDGE, "LIVEKIT_API_KEY"),
        (BRIDGE, "LIVEKIT_API_SECRET"),
        (BRIDGE, "LIVEKIT_URL"),
    ],
)
def test_configuration_alignment_mismatch_fails_before_build(lane, target, key):
    env = lane.external.containers[target]["Config"]["Env"]
    env[:] = [item for item in env if not item.startswith(key + "=")] + [key + "=wrong"]
    assert lane.run() == 1
    assert not lane.external.mutations()


def test_public_web_media_address_does_not_rewire_private_telephone_transport(lane):
    values = lane.external.containers["web"]["Config"]["Env"]
    values[:] = [value for value in values if not value.startswith("LIVEKIT_URL=")]
    values.append("LIVEKIT_URL=wss://public-media.example.invalid")
    assert lane.run() == 0
    assert all(
        env["LIVEKIT_URL"] == "ws://livekit:7880"
        for command, env in lane.external.calls
        if "compose" in command
    )


def test_already_current_healthy_targets_need_no_build_replacement_or_room_query(
    lane, capsys
):
    for name in (WORKER, BRIDGE):
        config = lane.external.containers[name]["Config"]
        config["Image"] = "voicebot-telephone:" + SHA
        config["Labels"].update({"voicebot.release": SHA, "voicebot.web-source": WEB})
        lane.external.containers[name]["Image"] = ARTIFACT
    assert lane.run() == 0
    assert not lane.external.mutations()
    assert not any("exec" in c for c, _ in lane.external.calls)
    assert capsys.readouterr().out.strip() == "PASS: release_current"


@pytest.mark.parametrize("target", [WORKER, BRIDGE])
def test_a_failed_healthcheck_does_not_permanently_block_the_next_good_release(
    lane, target
):
    lane.external.containers[target]["State"]["Health"]["Status"] = "unhealthy"

    def recover(name):
        lane.external.containers[name]["State"]["Health"]["Status"] = "healthy"

    lane.external.after_up = recover
    assert lane.run() == 0
    assert any(
        "up" in c and c[-1] == ("worker" if target == WORKER else "twilio-bridge")
        for c in lane.external.mutations()
    )


def test_stopped_worker_is_recovered_using_a_private_count_only_probe(lane):
    worker = lane.external.containers[WORKER]
    worker["State"].update(Running=False, Status="exited")

    def recover(name):
        lane.external.containers[name]["State"].update(Running=True, Status="running")

    lane.external.after_up = recover
    assert lane.run() == 0
    assert any(c[1] == "run" for c, _ in lane.external.calls)
    assert not any(c[1] == "exec" for c, _ in lane.external.calls)


def test_matching_tags_with_different_actual_image_ids_are_not_current(lane, capsys):
    for name in (WORKER, BRIDGE):
        config = lane.external.containers[name]["Config"]
        config["Image"] = "voicebot-telephone:" + SHA
        config["Labels"].update({"voicebot.release": SHA, "voicebot.web-source": WEB})
    assert lane.run() == 0
    assert capsys.readouterr().out.strip() == "PASS: release_synced"
    assert (
        lane.external.containers[WORKER]["Image"]
        == lane.external.containers[BRIDGE]["Image"]
    )


def test_final_actual_image_mismatch_is_not_reported_as_success(lane, capsys):
    def mismatch(name):
        if name == BRIDGE:
            lane.external.containers[BRIDGE]["Image"] = "sha256:" + "8" * 64

    lane.external.after_up = mismatch
    assert lane.run() == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("after", [WORKER, BRIDGE])
def test_web_replacement_during_apply_does_not_claim_full_release_success(
    lane, capsys, after
):
    def replace(name):
        if name == after:
            lane.external.source_ids = ["f" * 64]
            lane.external.containers["web"]["Id"] = "f" * 64

    lane.external.after_up = replace
    assert lane.run() == 0
    assert capsys.readouterr().out.strip() == "DEFER: release_changed"


def test_bridge_rotation_during_worker_apply_is_not_overwritten(lane, capsys):
    def replace(name):
        if name == WORKER:
            lane.external.containers[BRIDGE]["Id"] = "f" * 64

    lane.external.after_up = replace
    assert lane.run() == 0
    assert capsys.readouterr().out.strip() == "DEFER: release_changed"
    assert not any(
        "up" in c and c[-1] == "twilio-bridge" for c in lane.external.mutations()
    )
    assert not any(c[1] == "start" for c, _ in lane.external.calls)


def test_failed_bridge_drain_is_not_hidden_by_a_healthy_new_container(lane, capsys):
    lane.external.containers[BRIDGE]["State"]["ExitCode"] = 1
    assert lane.run() == 1
    assert capsys.readouterr().out == ""
    assert not any(
        "up" in c and c[-1] == "twilio-bridge" for c in lane.external.mutations()
    )
    assert not any(c[1] == "start" for c, _ in lane.external.calls)


def test_web_change_during_bridge_drain_restores_the_unchanged_bridge_and_defers(
    lane, capsys
):
    def replace():
        lane.external.source_ids = ["f" * 64]
        lane.external.containers["web"]["Id"] = "f" * 64

    lane.external.after_stop = replace
    assert lane.run() == 0
    assert capsys.readouterr().out.strip() == "DEFER: release_changed"
    assert lane.external.containers[BRIDGE]["State"]["Running"] is True
    assert not any(
        "up" in c and c[-1] == "twilio-bridge" for c in lane.external.mutations()
    )


def test_bridge_rotation_during_drain_is_not_restarted_or_overwritten(lane, capsys):
    def replace():
        original = copy.deepcopy(lane.external.containers[BRIDGE])
        original["Name"] = "/retained-old-bridge"
        lane.external.containers["retained-old-bridge"] = original
        lane.external.containers[BRIDGE]["Id"] = "f" * 64
        lane.external.containers[BRIDGE]["State"].update(Running=True, Status="running")

    lane.external.after_stop = replace
    assert lane.run() == 0
    assert capsys.readouterr().out.strip() == "DEFER: release_changed"
    assert not any(c[1] == "start" for c, _ in lane.external.calls)
    assert not any(
        "up" in c and c[-1] == "twilio-bridge" for c in lane.external.mutations()
    )


def test_a_stopped_bridge_after_a_failed_drain_can_apply_the_next_good_release(lane):
    lane.external.containers[BRIDGE]["State"].update(
        Running=False, Status="exited", ExitCode=1
    )
    assert lane.run() == 0
    assert not any(c[1] == "stop" for c, _ in lane.external.calls)
    assert lane.external.containers[BRIDGE]["State"]["Running"] is True


def test_source_health_failure_after_clean_stop_restores_bridge_and_fails(lane, capsys):
    def unhealthy():
        lane.external.containers["web"]["State"]["Health"]["Status"] = "unhealthy"

    lane.external.after_stop = unhealthy
    assert lane.run() == 1
    assert lane.external.containers[BRIDGE]["State"]["Running"] is True
    assert not any(
        "up" in c and c[-1] == "twilio-bridge" for c in lane.external.mutations()
    )
    assert capsys.readouterr().out == ""


def test_worker_replacement_during_second_room_probe_is_not_overwritten(lane, capsys):
    lane.external.after_probe = lambda: lane.external.containers[WORKER].update(
        Id="f" * 64
    )
    assert lane.run() == 0
    assert capsys.readouterr().out.strip() == "DEFER: release_changed"
    assert not any("up" in c for c in lane.external.mutations())


def test_matching_release_labels_do_not_hide_language_model_drift(lane, capsys):
    for name in (WORKER, BRIDGE):
        config = lane.external.containers[name]["Config"]
        config["Image"] = "voicebot-telephone:" + SHA
        config["Labels"].update({"voicebot.release": SHA, "voicebot.web-source": WEB})
        lane.external.containers[name]["Image"] = ARTIFACT
    env = lane.external.containers[WORKER]["Config"]["Env"]
    env[:] = [v for v in env if not v.startswith("VOICEBOT_TELEPHONE_LANGUAGE=")]
    env.append("VOICEBOT_TELEPHONE_LANGUAGE=ru")
    assert lane.run() == 0
    assert capsys.readouterr().out.strip() == "PASS: release_synced"
    assert (
        "VOICEBOT_TELEPHONE_LANGUAGE=en"
        in lane.external.containers[WORKER]["Config"]["Env"]
    )


def test_final_language_model_drift_is_not_reported_as_success(lane, capsys):
    def wrong_language(name):
        if name == BRIDGE:
            env = lane.external.containers[WORKER]["Config"]["Env"]
            env[:] = [v for v in env if not v.startswith("GROQ_CHAT_MODEL=")]
            env.append("GROQ_CHAT_MODEL=wrong-model")

    lane.external.after_up = wrong_language
    assert lane.run() == 1
    assert capsys.readouterr().out == ""


def test_same_sha_new_web_identity_updates_config(lane):
    for name in (WORKER, BRIDGE):
        config = lane.external.containers[name]["Config"]
        config["Image"] = "voicebot-telephone:" + SHA
        config["Labels"].update(
            {"voicebot.release": SHA, "voicebot.web-source": "f" * 64}
        )
    assert lane.run() == 0
    assert len(lane.external.mutations()) == 3


def test_compose_subprocess_budget_outlasts_call_drain_and_health_wait(lane):
    assert lane.run() == 0
    for (command, _), timeout in zip(lane.external.calls, lane.external.timeouts):
        if "compose" in command and "up" in command:
            assert 1020 < timeout <= 1200


@pytest.mark.parametrize("rooms", [[1], [0, 1]])
def test_any_active_room_defers_before_replacement(lane, rooms, capsys):
    lane.external.rooms = rooms
    assert lane.run() == 0
    assert not any("up" in c for c in lane.external.mutations())
    assert capsys.readouterr().out.strip() == "DEFER: release_busy"


@pytest.mark.parametrize("identity", ["web", WORKER, BRIDGE])
def test_changed_source_or_target_identity_after_build_defers(lane, identity, capsys):
    def change():
        lane.external.containers[identity]["Id"] = "f" * 64
        if identity == "web":
            lane.external.source_ids = ["f" * 64]

    lane.external.after_build = change
    assert lane.run() == 0
    assert len(lane.external.mutations()) == 1
    assert capsys.readouterr().out.strip() == "DEFER: release_changed"


@pytest.mark.parametrize(
    "change", ["source-gone", "source-preview", "worker-unhealthy", "bridge-gone"]
)
def test_replacement_inventory_defers_before_validating_the_new_container(
    lane, change, capsys
):
    def change_inventory():
        if change == "source-gone":
            lane.external.source_ids = []
        elif change == "source-preview":
            web = lane.external.containers["web"]
            web["Id"] = "f" * 64
            web["Config"]["Labels"]["coolify.environmentName"] = "preview"
            lane.external.source_ids = [web["Id"]]
        elif change == "worker-unhealthy":
            worker = lane.external.containers[WORKER]
            worker["Id"] = "f" * 64
            worker["State"]["Health"]["Status"] = "unhealthy"
        else:
            del lane.external.containers[BRIDGE]

    lane.external.after_build = change_inventory
    assert lane.run() == 0
    assert len(lane.external.mutations()) == 1
    assert capsys.readouterr().out.strip() == "DEFER: release_changed"


@pytest.mark.parametrize(
    "bridge_values",
    [dict.fromkeys(TWILIO, ""), {k: "synthetic-current-" + k.lower() for k in TWILIO}],
)
def test_secure_environment_copy_keeps_bridge_configuration_not_host_or_web(
    lane, bridge_values, capsys
):
    bridge_env = lane.external.containers[BRIDGE]["Config"]["Env"]
    bridge_env[:] = [s for s in bridge_env if s.split("=", 1)[0] not in TWILIO]
    bridge_env.extend(f"{k}={v}" for k, v in bridge_values.items())
    assert lane.run() == 0
    for cmd, env in lane.external.calls:
        if "compose" not in cmd:
            continue
        masked = "--format" in cmd
        assert {k: env[k] for k in TWILIO} == (
            dict.fromkeys(TWILIO, "withheld") if masked else bridge_values
        )
        assert env["LIVEKIT_API_SECRET"] == (
            "withheld" if masked else "synthetic-livekit_api_secret"
        )
        if masked:
            assert env["LIVEKIT_KEYS"] == env["SIP_CONFIG_BODY"] == "withheld"
        assert env["VOICEBOT_AGENT_NAME"] == "kept-agent"
        assert env["TWILIO_TRAEFIK_ENTRYPOINT"] == "kept-https"
        assert env["TWILIO_TRAEFIK_CERTRESOLVER"] == "kept-resolver"
        assert env["VOICEBOT_WEB_SOURCE"] == WEB
        assert env["VOICEBOT_MEDIA_IMAGE"] == "voicebot-telephone:" + SHA
        assert env["AZURE_EN_LANG"] == "en-GB"
        assert env["VOICEBOT_SPEECH_RATE"] == "1.0"
        assert env["VOICEBOT_TELEPHONE_LANGUAGE"] == "en"
        assert "AZURE_LANG" not in env
        assert env["DOCKER_CONFIG"] == str(lane.state / "docker")
    output = capsys.readouterr()
    assert output.err == "" and PRIVATE not in output.out
    assert lane.state.stat().st_mode & 0o777 == 0o700
    for path in lane.state.rglob("*"):
        if path.is_file():
            assert PRIVATE.encode() not in path.read_bytes()


@pytest.mark.parametrize(
    "stage",
    [
        "fetch",
        "config",
        "build",
        "up-worker",
        "up-twilio-bridge",
        "stop",
        "timeout-inspect",
        "timeout-fetch",
        "timeout-exec",
        "timeout-build",
    ],
)
def test_external_failure_is_nonzero_and_prints_only_fixed_safe_code(
    lane, stage, capsys
):
    lane.external.fail = stage
    assert lane.run() == 1
    output = capsys.readouterr()
    assert output.out == "" and output.err.strip() == "FAIL: release_sync_failed"
    if stage == "up-worker":
        assert not any(
            c[-1] == "twilio-bridge" and "up" in c for c, _ in lane.external.calls
        )
    if stage in ("fetch", "config", "timeout-inspect", "timeout-fetch", "timeout-exec"):
        assert not lane.external.mutations()


@pytest.mark.parametrize("change", ["health", "image", "labels", "mount"])
def test_final_target_verification_failure_never_claims_success_or_rolls_back(
    lane, change, capsys
):
    def change_target(name):
        if name != BRIDGE:
            return
        target = lane.external.containers[WORKER]
        if change == "health":
            target["State"]["Health"]["Status"] = "unhealthy"
        elif change == "mount":
            target["Mounts"][0]["Name"] = "different-journal"
        elif change == "image":
            target["Config"]["Image"] = "wrong"
        else:
            target["Config"]["Labels"]["voicebot.web-source"] = "wrong"

    lane.external.after_up = change_target
    assert lane.run() == 1
    assert capsys.readouterr().err.strip() == "FAIL: release_sync_failed"
    assert len(lane.external.mutations()) == 3


def test_lock_contention_defers_without_even_discovering_containers(lane, capsys):
    lane.state.mkdir(mode=0o700)
    with (lane.state / "sync.lock").open("w") as held:
        held_path = lane.state / "sync.lock"
        held_path.chmod(0o600)
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert lane.run() == 0
    assert not lane.external.calls
    assert capsys.readouterr().out.strip() == "DEFER: release_locked"


def test_untrusted_world_readable_state_is_rejected(lane):
    lane.state.mkdir(mode=0o755)
    assert lane.run() == 1
    assert not lane.external.calls


def test_archive_traversal_is_rejected_without_compose_mutation(lane):
    lane.external.payload = archive({"../../escaped": b"not-secret"})
    assert lane.run() == 1
    assert not lane.external.mutations()
    assert not (lane.state.parent / "escaped").exists()


def test_archived_operator_prints_and_exceptions_are_also_withheld(lane, capsys):
    helper = (
        "import sys\n"
        f"print({PRIVATE!r})\n"
        "def environment(source):\n"
        f"    print({PRIVATE!r}, file=sys.stderr)\n"
        f"    raise ValueError({PRIVATE!r})\n"
    )
    lane.external.payload = archive({"deploy/telephony/manage.py": helper.encode()})
    assert lane.run() == 1
    assert not lane.external.mutations()
    output = capsys.readouterr()
    assert output.out == "" and output.err.strip() == "FAIL: release_sync_failed"


def test_room_probe_executes_count_only_and_always_closes_api(
    lane, monkeypatch, capsys
):
    assert lane.run() == 0
    script = next(c[-1] for c, _ in lane.external.calls if c[1] == "exec")
    api = ModuleType("livekit.api")
    closed = []

    class Client:
        def __init__(self):
            self.room = self

        async def list_rooms(self, request):
            assert isinstance(request, api.ListRoomsRequest)
            return SimpleNamespace(rooms=[PRIVATE, PRIVATE])

        async def aclose(self):
            closed.append(True)

    api.LiveKitAPI = Client
    api.ListRoomsRequest = type("ListRoomsRequest", (), {})
    monkeypatch.setitem(sys.modules, "livekit", SimpleNamespace(api=api))
    monkeypatch.setitem(sys.modules, "livekit.api", api)
    capsys.readouterr()
    exec(script, {"__name__": "__main__"})
    assert capsys.readouterr().out.strip() == "2"
    assert closed == [True]

    async def failed(self, request):
        raise ValueError(PRIVATE)

    monkeypatch.setattr(Client, "list_rooms", failed)
    with pytest.raises(ValueError):
        exec(script, {"__name__": "__main__"})
    assert closed == [True, True]


def test_cli_fails_closed_in_clean_environment_without_docker_or_output_leak(tmp_path):
    assert SCRIPT.is_file(), "release reconciler is not implemented"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(
        "#!/bin/sh\nprintf '%s\\n' SYNTHETIC_PRIVATE_OUTPUT_NEVER_PRINT >&2\nexit 19\n"
    )
    docker.chmod(0o700)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repository",
            str(ROOT),
            "--state-directory",
            str(tmp_path / "state"),
        ],
        env={"PATH": str(bindir), "HOME": "/nonexistent"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == "" and result.stderr.strip() == "FAIL: release_sync_failed"


def test_cli_invalid_arguments_are_fixed_safe_failure_not_argparse_echo(tmp_path):
    assert SCRIPT.is_file(), "release reconciler is not implemented"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--unexpected", PRIVATE],
        env={"PATH": "/nonexistent"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == "" and result.stderr.strip() == "FAIL: release_sync_failed"
