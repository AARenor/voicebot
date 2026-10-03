"""Non-root packaging must tolerate private git-archive directory modes."""

import io
import os
from pathlib import Path
import re
import subprocess
import tarfile
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]


def private_archive(tmp_path):
    stream = io.BytesIO()
    files = {
        "app/booking/packaging_probe.py": "VALUE = 42\n",
        "data/demo/packaging-probe.json": '{"fictional": true}\n',
    }
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, text in files.items():
            info = tarfile.TarInfo(name)
            value = text.encode()
            info.size = len(value)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(value))
    stream.seek(0)
    previous = os.umask(0o077)
    try:
        with tarfile.open(fileobj=stream) as archive:
            archive.extractall(tmp_path, filter="data")
    finally:
        os.umask(previous)
    return tmp_path


def copies():
    dockerfile = (ROOT / "deploy/telephony/Dockerfile").read_text()
    return [
        line
        for line in dockerfile.splitlines()
        if re.match(r"COPY\s+(?:--\S+\s+)*?(?:app/|data/demo/)", line)
    ]


def test_private_archive_keeps_parent_directories_private(tmp_path):
    source = private_archive(tmp_path)
    assert (source / "app/booking").stat().st_mode & 0o777 == 0o700
    assert (source / "data/demo").stat().st_mode & 0o777 == 0o700


def test_nonroot_runtime_owns_private_archive_source():
    lines = copies()
    assert len(lines) == 2
    assert all("--chown=voicebot:voicebot" in line for line in lines), lines


@pytest.mark.skipif(
    not os.environ.get("VOICEBOT_PACKAGING_BASE_IMAGE"),
    reason="explicit local Docker image required; no image pulls",
)
def test_actual_private_archive_image_imports_as_runtime_user(tmp_path):
    source = private_archive(tmp_path)
    base = os.environ["VOICEBOT_PACKAGING_BASE_IMAGE"]
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", base)
    tag = "voicebot-permission-probe:" + uuid.uuid4().hex
    base_tag = "voicebot-permission-base:" + uuid.uuid4().hex
    (source / "Dockerfile").write_text(
        "\n".join(
            [
                "FROM " + base_tag,
                "USER root",
                "WORKDIR /app",
                *copies(),
                "USER voicebot",
            ]
        )
        + "\n"
    )
    env = dict(os.environ)
    env["DOCKER_BUILDKIT"] = "0"  # Local image only, no registry resolution.
    probe = (
        "import os,json;from pathlib import Path;"
        "from app.booking.packaging_probe import VALUE;"
        "assert os.getuid()==10001;assert VALUE==42;"
        "assert json.loads(Path('/app/data/demo/packaging-probe.json').read_text())"
        "['fictional'] is True;print('PASS: nonroot private-archive import and fixture')"
    )
    try:
        subprocess.run(
            ["docker", "image", "tag", base, base_tag],
            env=env,
            capture_output=True,
            check=True,
            timeout=30,
        )
        built = subprocess.run(
            [
                "docker",
                "build",
                "--network=none",
                "--pull=false",
                "-t",
                tag,
                str(source),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert built.returncode == 0, "isolated permission image failed to build"
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--entrypoint",
                "python",
                tag,
                "-c",
                probe,
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert (
            result.stdout.strip() == "PASS: nonroot private-archive import and fixture"
        )
    finally:
        subprocess.run(
            ["docker", "image", "rm", tag, base_tag],
            env=env,
            capture_output=True,
            timeout=30,
        )
