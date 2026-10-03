"""Reconcile only existing telephone services to the healthy published master."""

import argparse
import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace

TARGETS = (
    ("livekit", "worker", "compose.yaml"),
    ("voicebot-twilio", "twilio-bridge", "twilio-compose.yaml"),
)
UP = "up -d --no-build --no-deps --pull never --wait --wait-timeout 120".split()
SOURCE_LABELS = {
    "coolify.managed": "true",
    "coolify.type": "application",
    "coolify.applicationId": "13",
    "coolify.environmentName": "production",
    "coolify.pullRequestId": "0",
}
ROOM_COUNT = """import asyncio
from livekit import api
async def count():
    client = api.LiveKitAPI()
    try:
        response = await client.room.list_rooms(api.ListRoomsRequest())
        print(len(response.rooms))
    finally:
        await client.aclose()
asyncio.run(count())
"""


def require(condition):
    if not condition:
        raise ValueError


def run(command, env, timeout=30):
    return subprocess.run(
        command, env=env, capture_output=True, check=True, timeout=timeout
    )


def output(command, env, timeout=30):
    return run(command, env, timeout).stdout.decode().strip()


class Changed(Exception):
    pass


def healthy(item):
    state = item["State"]
    return (
        state.get("Running") is True
        and state.get("Status") == "running"
        and state.get("Health", {}).get("Status") == "healthy"
    )


def inspect(identity, env, expected=None, healthy_only=True):
    try:
        records = json.loads(run(["docker", "inspect", identity], env).stdout)
    except subprocess.CalledProcessError:
        if expected:
            raise Changed from None
        raise
    require(len(records) == 1)
    item = records[0]
    if expected and item.get("Id") != expected:
        raise Changed
    require(re.fullmatch(r"[0-9a-f]{64}", item["Id"]))
    if healthy_only:
        require(healthy(item))
    return item


def source(env, expected=None):
    command = ["docker", "ps", "--filter", "label=coolify.applicationId=13"]
    command += ["--filter", "status=running", "--no-trunc", "--format", "{{.ID}}"]
    ids = output(command, env).split()
    if expected and ids != [expected]:
        raise Changed
    require(len(ids) == 1 and re.fullmatch(r"[0-9a-f]{64}", ids[0]))
    web = inspect(ids[0], env, expected)
    require(web["Id"] == ids[0])
    config = web["Config"]
    require(all(config["Labels"].get(k) == v for k, v in SOURCE_LABELS.items()))
    sha = re.fullmatch(r"zs7s830dsrlo4j81s0ohgpgc:([0-9a-f]{40})", config["Image"])
    require(sha)
    return web, sha.group(1)


def targets(env, expected=(), healthy_only=False):
    result = []
    for index, (project, service, _) in enumerate(TARGETS):
        name = project + "-" + service + "-1"
        identity = expected[index]["Id"] if expected else None
        item = inspect(name, env, identity, healthy_only)
        labels = item["Config"]["Labels"]
        require(item["Name"] == "/" + name)
        require(labels.get("com.docker.compose.project") == project)
        require(labels.get("com.docker.compose.service") == service)
        result.append(item)
    return result


def values(container):
    return dict(v.split("=", 1) for v in container["Config"]["Env"] if "=" in v)


def volume(container):
    mounts = [m for m in container["Mounts"] if m["Destination"] == "/data"]
    require(len(mounts) == 1 and mounts[0]["Type"] == "volume")
    require(mounts[0]["Name"])
    return mounts[0]["Name"]


def settings(web, worker, bridge):
    require(volume(web) == volume(worker))
    se, we, be = map(values, (web, worker, bridge))
    for key in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        require(se.get(key) and se[key] == we.get(key) == be.get(key))
    agent = we.get("VOICEBOT_AGENT_NAME")
    require(agent and agent == be.get("VOICEBOT_AGENT_NAME"))
    url = we.get("LIVEKIT_URL")
    require(url == "ws://livekit:7880" and be.get("LIVEKIT_URL") == url)
    labels = bridge["Config"]["Labels"]
    twilio = "TWILIO_AUTH_TOKEN TWILIO_ACCOUNT_SID TWILIO_PHONE_NUMBER".split()
    env = {k: be.get(k, "") for k in twilio}
    env.update(VOICEBOT_AGENT_NAME=agent, LIVEKIT_URL=url)
    for variable, suffix in (
        ("TWILIO_TRAEFIK_ENTRYPOINT", "entrypoints"),
        ("TWILIO_TRAEFIK_CERTRESOLVER", "tls.certresolver"),
    ):
        value = labels.get("traefik.http.routers.voicebot-twilio." + suffix)
        require(value)
        env[variable] = value
    return env


def current(items, sha, web_id, profile, image=None):
    worker_env = values(items[0])
    return (
        all(worker_env.get(k) == v for k, v in profile.items())
        and items[0]["Image"] == items[1]["Image"]
        and all(
            healthy(c)
            and (image is None or c["Image"] == image)
            and c["Config"]["Image"] == "voicebot-telephone:" + sha
            and c["Config"]["Labels"].get("voicebot.release") == sha
            and c["Config"]["Labels"].get("voicebot.web-source") == web_id
            for c in items
        )
    )


def busy(worker, env, image=None):
    if healthy(worker):
        command = ["docker", "exec", worker["Id"], "python", "-c", ROOM_COUNT]
    else:
        require(image)
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "coolify",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "-e",
            "LIVEKIT_URL",
            "-e",
            "LIVEKIT_API_KEY",
            "-e",
            "LIVEKIT_API_SECRET",
            "--entrypoint",
            "python",
            image,
            "-c",
            ROOM_COUNT,
        ]
    count = output(command, env, timeout=20)
    require(re.fullmatch(r"[0-9]+", count))
    return int(count) > 0


def reconcile(repository, state, base):
    web, sha = source(base)
    git = ["git", "-C", str(repository)]
    root = output(git + ["rev-parse", "--show-toplevel"], base)
    require(root == str(repository.resolve()))
    origin = output(git + ["remote", "get-url", "--all", "origin"], base)
    require(
        re.fullmatch(
            r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
            r"Parnuhakk/voicebot(?:\.git)?",
            origin,
        )
    )
    ref = "refs/heads/master:refs/remotes/origin/master"
    run(git + ["fetch", "--no-tags", "origin", ref], base, timeout=120)
    master = output(git + ["rev-parse", "refs/remotes/origin/master"], base)
    if master != sha:
        return "DEFER: release_master_mismatch"
    old = targets(base)
    kept = settings(web, *old)
    with tempfile.TemporaryDirectory(prefix="release-", dir=state) as temporary:
        release = Path(temporary)
        payload = run(git + ["archive", "--format=tar", sha], base).stdout
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            archive.extractall(release, filter="data")
        # The data filter leaves directory modes to our private service umask.
        # COPY preserves those modes, but the image runs as a different user.
        for directory in release.rglob("*"):
            if directory.is_dir() and not directory.is_symlink():
                directory.chmod(0o755)
        spec = importlib.util.spec_from_file_location(
            "release_manage", release / "deploy/telephony/manage.py"
        )
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            manage = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(manage)
            # Bound the helper's inspect; do not inherit host application overrides.
            manage.subprocess = SimpleNamespace(run=lambda argv, **_: run(argv, base))
            manage.os = SimpleNamespace(environ=base)
            env = manage.environment(web["Id"])
        require(env["VOICEBOT_DATA_VOLUME"] == volume(old[0]))
        env.update(
            kept,
            VOICEBOT_MEDIA_IMAGE="voicebot-telephone:" + sha,
            VOICEBOT_RELEASE_SHA=sha,
            VOICEBOT_WEB_SOURCE=web["Id"],
        )
        commands = [
            [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(release / "deploy/telephony" / manifest),
            ]
            for project, _, manifest in TARGETS
        ]
        for command in commands:
            run(command + ["config", "-q"], env)
        masked = dict(env)
        for key in (
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "GROQ_API_KEY",
            "AZURE_SPEECH_KEY",
            "EASY_API_KEY",
            "LIVEKIT_KEYS",
            "SIP_CONFIG_BODY",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_ACCOUNT_SID",
            "TWILIO_PHONE_NUMBER",
        ):
            masked[key] = "withheld"
        resolved = json.loads(
            run(commands[0] + ["config", "--format", "json"], masked).stdout
        )["services"]["worker"]["environment"]
        profile = {
            k: v
            for k, v in resolved.items()
            if k.startswith(("AZURE_", "GROQ_", "VOICEBOT_"))
            and not k.endswith(("KEY", "SECRET", "TOKEN"))
        }
        require(profile)
        if current(old, sha, web["Id"], profile):
            return "PASS: release_current"
        if healthy(old[0]) and busy(old[0], base):
            return "DEFER: release_busy"
        run(commands[0] + ["build", "worker"], env, timeout=600)
        image = output(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                env["VOICEBOT_MEDIA_IMAGE"],
            ],
            base,
        )
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", image))
        run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--entrypoint",
                "python",
                image,
                "-c",
                "import app.worker; import app.twilio_bridge",
            ],
            base,
            timeout=60,
        )
        try:
            _, fresh_sha = source(base, web["Id"])
            existing = targets(base, old)
        except Changed:
            return "DEFER: release_changed"
        if fresh_sha != sha:
            return "DEFER: release_changed"
        if busy(existing[0], env, image):
            return "DEFER: release_busy"
        for index, (command, (_, service, _)) in enumerate(zip(commands, TARGETS)):
            stopped_id = None
            name = TARGETS[index][0] + "-" + service + "-1"
            try:
                source(base, web["Id"])
                inspect(name, base, old[index]["Id"], healthy_only=False)
                if index == 1:
                    bridge = inspect(name, base, old[1]["Id"], healthy_only=False)
                    if bridge["State"]["Running"]:
                        run(
                            ["docker", "stop", "--time", "720", bridge["Id"]],
                            base,
                            timeout=800,
                        )
                        stopped = inspect(name, base, bridge["Id"], healthy_only=False)
                        require(stopped["State"]["ExitCode"] == 0)
                        require(not stopped["State"].get("OOMKilled", False))
                        require(not stopped["State"]["Running"])
                        stopped_id = bridge["Id"]
                    source(base, web["Id"])
                    inspect(name, base, old[1]["Id"], healthy_only=False)
            except Exception as error:
                if stopped_id:
                    try:
                        inspect(name, base, stopped_id, healthy_only=False)
                    except Changed:
                        pass
                    else:
                        run(["docker", "start", stopped_id], base)
                if isinstance(error, Changed):
                    return "DEFER: release_changed"
                raise
            force = [] if healthy(existing[index]) else ["--force-recreate"]
            run(command + UP + force + [service], env, timeout=1200)
            try:
                source(base, web["Id"])
            except Changed:
                return "DEFER: release_changed"
        final = targets(base, healthy_only=True)
        require(current(final, sha, web["Id"], profile, image))
        require(settings(web, *final) == kept)
        require(volume(final[0]) == volume(old[0]))
        require(final[1]["Mounts"] == old[1]["Mounts"])
    return "PASS: release_synced"


def private_directory(path):
    require(path.is_absolute() and not path.is_symlink())
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid())
    require(info.st_mode & 0o077 == 0)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--repository", required=True)
        parser.add_argument("--state-directory", required=True)
        args = parser.parse_args(argv)
        repository, state = Path(args.repository), Path(args.state_directory)
        require(repository.is_absolute() and repository.is_dir())
        private_directory(state)
        with os.fdopen(
            os.open(state / "sync.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600),
            "r+",
        ) as lock:
            info = os.fstat(lock.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid())
            require(info.st_mode & 0o077 == 0)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("DEFER: release_locked")
                return 0
            private_directory(state / "docker")
            base = {
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": os.environ.get("HOME", str(state)),
                "DOCKER_CONFIG": str(state / "docker"),
                "COMPOSE_DISABLE_ENV_FILE": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_SSH_COMMAND": "ssh -oBatchMode=yes -oConnectTimeout=10",
            }
            if "SSH_AUTH_SOCK" in os.environ:
                base["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
            sys.dont_write_bytecode = True
            print(reconcile(repository, state, base))
        return 0
    except Exception:
        print("FAIL: release_sync_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
