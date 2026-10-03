import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_twilio_security import ENV

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/telephony/twilio-compose.yaml"


def probe_module():
    spec = importlib.util.spec_from_file_location(
        "twilio_operator_probe", ROOT / "deploy/telephony/twilio_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_source_container_inherits_private_media_not_stale_twilio(capsys):
    from unittest.mock import patch
    from deploy.telephony import manage

    module = probe_module()
    fresh = {k: v for k, v in ENV.items() if k.startswith("TWILIO_")}
    source = {
        **ENV,
        "TWILIO_AUTH_TOKEN": "stale-synthetic-never-reused",
        "LIVEKIT_API_KEY": "source-synthetic-key",
        "LIVEKIT_API_SECRET": "source-synthetic-media-secret",
        "EASY_DEMO_WRITES": "1",
        "EASY_STATE_DB": "/data/easy-booking.db",
    }
    for name in (
        "GROQ_API_KEY",
        "AZURE_SPEECH_KEY",
        "AZURE_REGION",
        "EASY_BASE_URL",
        "EASY_API_KEY",
    ):
        source[name] = "synthetic-only"
    inspected = [
        {
            "Config": {"Env": [f"{k}={v}" for k, v in source.items()]},
            "Mounts": [
                {"Type": "volume", "Destination": "/data", "Name": "synthetic-volume"}
            ],
        }
    ]

    async def check(config, *, media):
        assert config.auth == fresh["TWILIO_AUTH_TOKEN"]
        assert (
            config.account == fresh["TWILIO_ACCOUNT_SID"]
            and config.phone == fresh["TWILIO_PHONE_NUMBER"]
        )
        assert (
            config.livekit_key == source["LIVEKIT_API_KEY"]
            and config.livekit_secret == source["LIVEKIT_API_SECRET"]
        )
        assert config.livekit_url == "ws://livekit:7880" and media is False
        return False

    with (
        patch.dict("os.environ", fresh, clear=True),
        patch.object(
            manage.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(inspected).encode()
            ),
        ) as inspect,
        patch.object(module, "probe", side_effect=check),
    ):
        assert module.main(["--source-container", "synthetic-trusted-web"]) == 0
        assert inspect.call_args.args[0] == [
            "docker",
            "inspect",
            "synthetic-trusted-web",
        ]
        assert inspect.call_count == 1
    output = capsys.readouterr()
    assert (
        output.out.strip()
        == "PASS: signed_webhook_only (no paid agent or carrier call)"
        and output.err == ""
    )


@pytest.mark.parametrize(
    "missing", ["TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID", "TWILIO_PHONE_NUMBER"]
)
def test_probe_source_container_cannot_fill_missing_fresh_twilio(missing, capsys):
    from unittest.mock import patch
    from deploy.telephony import manage

    module = probe_module()
    fresh = {k: v for k, v in ENV.items() if k.startswith("TWILIO_") and k != missing}
    with (
        patch.dict("os.environ", fresh, clear=True),
        patch.object(manage, "environment") as inherited,
        patch.object(module, "probe") as network,
    ):
        assert module.main(["--source-container", "synthetic-trusted-web"]) == 1
        inherited.assert_not_called()
        network.assert_not_called()
    output = capsys.readouterr()
    assert (
        output.out == ""
        and output.err.strip() == "FAIL: twilio_probe_configuration_missing"
    )


def test_probe_source_container_inspect_failure_exits_one_without_leak(capsys):
    from unittest.mock import patch
    from deploy.telephony import manage

    module = probe_module()
    fresh = {k: v for k, v in ENV.items() if k.startswith("TWILIO_")}
    failure = subprocess.CalledProcessError(
        17,
        ["docker", "inspect"],
        output=b"PRIVATE synthetic inspect output",
        stderr=b"PRIVATE synthetic inspect error",
    )
    with (
        patch.dict("os.environ", fresh, clear=True),
        patch.object(manage.subprocess, "run", side_effect=failure),
        patch.object(module, "probe") as network,
    ):
        assert (
            module.main(["--source-container", "synthetic-trusted-web", "--media"]) == 1
        )
        network.assert_not_called()
    output = capsys.readouterr()
    assert output.out == "" and output.err.strip() == "FAIL: twilio_probe_failed"


def test_probe_without_source_uses_existing_fully_configured_environment(capsys):
    from unittest.mock import patch
    from deploy.telephony import manage
    from tests.test_twilio_security import security

    module = probe_module()

    async def check(config, *, media):
        assert config == security().Config.from_env(ENV) and media is False
        return False

    with (
        patch.dict("os.environ", ENV, clear=True),
        patch.object(manage, "environment") as inherited,
        patch.object(module, "probe", side_effect=check),
    ):
        assert module.main([]) == 0
        inherited.assert_not_called()
    output = capsys.readouterr()
    assert (
        output.out.strip()
        == "PASS: signed_webhook_only (no paid agent or carrier call)"
        and output.err == ""
    )


def test_compose_parser_keeps_bridge_separate_and_only_twilio_paths_public():
    assert COMPOSE.exists(), "separate bridge deployment missing"
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose parser unavailable")
    result = subprocess.run(
        [docker, "compose", "-f", str(COMPOSE), "config", "--format", "json"],
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", **ENV},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, "Compose parse failed (details withheld)"
    config = json.loads(result.stdout)
    assert set(config["services"]) == {"twilio-bridge"}
    service = config["services"]["twilio-bridge"]
    assert service["image"] == "voicebot-telephone:local"
    assert service["command"] == ["python", "-m", "app.twilio_bridge"]
    assert set(service["networks"]) == {"coolify"}
    assert all(p.get("host_ip") == "127.0.0.1" for p in service.get("ports", []))
    assert "volumes" not in service and "build" not in service
    labels = service["labels"]
    assert (
        labels["traefik.http.routers.voicebot-twilio.rule"]
        == "Host(`robot.arleserver.cfd`) && PathPrefix(`/api/twilio/`)"
    )
    assert int(labels["traefik.http.routers.voicebot-twilio.priority"]) >= 1000
    assert (
        labels["traefik.http.services.voicebot-twilio.loadbalancer.server.port"]
        == "8082"
    )
    assert labels["traefik.http.routers.voicebot-twilio.tls"] == "true"
    assert labels["traefik.http.routers.voicebot-twilio.entrypoints"] == "https"
    assert (
        labels["traefik.http.routers.voicebot-twilio.tls.certresolver"] == "letsencrypt"
    )
    assert labels["traefik.http.routers.voicebot-twilio-http.entrypoints"] == "http"
    assert int(labels["traefik.http.routers.voicebot-twilio-http.priority"]) >= 1000
    assert (
        labels["traefik.http.middlewares.voicebot-twilio-https.redirectscheme.scheme"]
        == "https"
    )
    assert "GROQ_API_KEY" not in service["environment"]
    assert "EASY_API_KEY" not in service["environment"]
    assert "AZURE_SPEECH_KEY" not in service["environment"]


@pytest.mark.parametrize(
    "arguments", [[], ["--source-container", "synthetic-trusted-web"]]
)
def test_probe_clean_environment_exits_closed_without_network_or_key_output(arguments):
    script = ROOT / "deploy/telephony/twilio_probe.py"
    assert script.exists(), "bounded carrier protocol probe missing"
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
    if os.name == "nt":
        # Windows needs its OS directory to initialize Python's async socket
        # runtime. No application/provider credentials enter this clean process.
        clean_env["SystemRoot"] = os.environ["SystemRoot"]
    result = subprocess.run(
        [os.sys.executable, str(script), *arguments],
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr.strip() == "FAIL: twilio_probe_configuration_missing"


def test_probe_transport_failure_is_nonzero_and_never_prints_private_error(capsys):
    script = ROOT / "deploy/telephony/twilio_probe.py"
    assert script.exists(), "bounded carrier protocol probe missing"
    spec = importlib.util.spec_from_file_location("twilio_probe", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from unittest.mock import patch

    with (
        patch.dict("os.environ", ENV, clear=True),
        patch.object(
            module, "probe", side_effect=RuntimeError("PRIVATE probe failure")
        ),
    ):
        assert module.main([]) == 1
    output = capsys.readouterr()
    assert output.out == "" and output.err.strip() == "FAIL: twilio_probe_failed"


def test_signed_probe_default_only_validates_webhook_and_never_opens_rtc(capsys):
    import asyncio
    import httpx
    from urllib.parse import parse_qs
    from unittest.mock import patch
    from tests.test_twilio_security import MEDIA_URL, VOICE_URL, sign, security

    script = ROOT / "deploy/telephony/twilio_probe.py"
    assert script.exists(), "bounded carrier protocol probe missing"
    spec = importlib.util.spec_from_file_location("twilio_probe", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requests = []

    def respond(request):
        assert str(request.url) == VOICE_URL
        fields = parse_qs(request.content.decode())
        assert set(fields) == {"AccountSid", "CallSid", "To"}
        requests.append(request)
        if "X-Twilio-Signature" not in request.headers:
            return httpx.Response(
                403, json={"detail": "forbidden"}, headers={"Cache-Control": "no-store"}
            )
        assert request.headers["X-Twilio-Signature"] == sign(VOICE_URL, fields)
        return httpx.Response(
            200,
            text=(
                f'<Response><Connect><Stream url="{MEDIA_URL}">'
                '<Parameter name="call_binding" '
                'value="synthetic_binding_never_printed"/>'
                "</Stream></Connect><Hangup/></Response>"
            ),
            headers={"Cache-Control": "no-store"},
        )

    original = httpx.AsyncClient

    def client(**kwargs):
        return original(transport=httpx.MockTransport(respond), **kwargs)

    with patch.object(module.httpx, "AsyncClient", side_effect=client):
        assert asyncio.run(module.probe(security().Config.from_env(ENV))) is False
    assert len(requests) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "native_flow",
    ["native", "start_failure", "unmarked_audio", "silent_mark", "wrong_mark"],
)
def test_opt_in_media_probe_checks_real_protocol_without_any_provider(
    capsys, native_flow
):
    import asyncio
    from unittest.mock import patch

    aiohttp = pytest.importorskip("aiohttp")
    import httpx
    from tests.test_twilio_client import TestClient
    from tests.test_twilio_bridge import bridge, NativeCall
    from tests.test_twilio_security import security

    script = ROOT / "deploy/telephony/twilio_probe.py"
    spec = importlib.util.spec_from_file_location("twilio_media_probe", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    b = bridge()
    NativeCall.opened = []

    class EmulatedNative(NativeCall):
        """Emulate trusted native output, not the adapter's cached failure path."""

        async def start(self):
            import struct

            self.opened.append(self)
            await self.sender.audio(struct.pack("<h", 1000) * 160, native=True)

    class Broken(NativeCall):
        async def start(self):
            self.opened.append(self)
            raise RuntimeError("PRIVATE native setup failure")

    class Unmarked(NativeCall):
        async def start(self):
            await super().start()
            self.ended.set()

    class SilentMark(NativeCall):
        async def start(self):
            import struct

            self.opened.append(self)
            await self.sender.audio(struct.pack("<h", 0) * 160)
            await self.sender.socket.send_json(
                {
                    "event": "mark",
                    "streamSid": self.sender.stream,
                    "mark": {"name": "voicebot-native-audio"},
                }
            )
            self.ended.set()

    class WrongMark(Unmarked):
        async def start(self):
            await super().start()
            await self.sender.socket.send_json(
                {
                    "event": "mark",
                    "streamSid": self.sender.stream,
                    "mark": {"name": "foreign-mark"},
                }
            )

    native = {
        "native": EmulatedNative,
        "start_failure": Broken,
        "unmarked_audio": Unmarked,
        "silent_mark": SilentMark,
        "wrong_mark": WrongMark,
    }[native_flow]
    original_http, original_ws = httpx.AsyncClient, aiohttp.ClientSession
    with (
        patch.dict("os.environ", ENV, clear=True),
        patch.object(b, "LiveKitCall", native),
        TestClient(b.create_app()) as server,
    ):

        class LocalHttp(httpx.AsyncBaseTransport):
            def __init__(self):
                self.transport = httpx.AsyncHTTPTransport()

            async def handle_async_request(self, request):
                mapped = httpx.Request(
                    request.method,
                    f"http://127.0.0.1:{server.port}" + request.url.path,
                    headers=request.headers,
                    stream=request.stream,
                )
                return await self.transport.handle_async_request(mapped)

            async def aclose(self):
                await self.transport.aclose()

        def http_client(**kwargs):
            return original_http(transport=LocalHttp(), **kwargs)

        class LocalSession:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                self.session = original_ws(**self.kwargs)
                return self

            async def __aexit__(self, *_):
                await self.session.close()

            def ws_connect(self, url, **kwargs):
                return self.session.ws_connect(
                    f"ws://127.0.0.1:{server.port}/api/twilio/media", **kwargs
                )

        with (
            patch.object(module.httpx, "AsyncClient", side_effect=http_client),
            patch.object(aiohttp, "ClientSession", LocalSession),
        ):
            if native_flow == "native":
                assert (
                    asyncio.run(
                        module.probe(security().Config.from_env(ENV), media=True)
                    )
                    is True
                )
            else:
                assert module.main(["--media"]) == 1
        assert len(NativeCall.opened) == 1, "replay dispatched another native call"
        assert server.app.state.bindings.active_count == 0
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.strip() == (
        "" if native_flow == "native" else "FAIL: twilio_probe_failed"
    )
