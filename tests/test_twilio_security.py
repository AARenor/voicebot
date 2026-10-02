"""Synthetic boundary checks: no carrier, keys, caller identities, or providers."""

import base64
import hashlib
import hmac
import importlib
import importlib.util
from copy import deepcopy

import pytest

ACCOUNT = "AC" + "a" * 32
CALL = "CA" + "b" * 32
STREAM = "MZ" + "c" * 32
VOICE_URL = "https://robot.arleserver.cfd/api/twilio/voice"
MEDIA_URL = "wss://robot.arleserver.cfd/api/twilio/media"
# Public, deliberately non-credential test fixtures. Never use live environment.
ENV = {
    "TWILIO_AUTH_TOKEN": "synthetic-test-only-credential",
    "TWILIO_ACCOUNT_SID": ACCOUNT,
    "TWILIO_PHONE_NUMBER": "+12025550123",
    "LIVEKIT_URL": "ws://livekit:7880",
    "LIVEKIT_API_KEY": "synthetic-test-key",
    "LIVEKIT_API_SECRET": "synthetic-test-only-media-key-not-real",
}


def security():
    assert importlib.util.find_spec("app.twilio_security"), (
        "carrier security module missing"
    )
    return importlib.import_module("app.twilio_security")


def sign(url, fields=None):
    fields = fields or {}
    data = url + "".join(k + v for k in sorted(fields) for v in sorted(set(fields[k])))
    return base64.b64encode(
        hmac.new(
            ENV["TWILIO_AUTH_TOKEN"].encode(), data.encode(), hashlib.sha1
        ).digest()
    ).decode()


def start(binding, call=CALL, stream=STREAM):
    return {
        "event": "start",
        "sequenceNumber": "1",
        "streamSid": stream,
        "start": {
            "accountSid": ACCOUNT,
            "callSid": call,
            "streamSid": stream,
            "tracks": ["inbound"],
            "mediaFormat": {
                "encoding": "audio/x-mulaw",
                "sampleRate": 8000,
                "channels": 1,
            },
            "customParameters": {"call_binding": binding},
        },
    }


def test_fixed_url_signature_includes_all_untrimmed_duplicate_values():
    s = security()
    cfg = s.Config.from_env(ENV)
    params = {
        "Z": [" last ", "a", "a"],
        "AccountSid": [ACCOUNT],
        "To": [ENV["TWILIO_PHONE_NUMBER"]],
        "CallSid": [CALL],
    }
    sig = sign(VOICE_URL, params)
    assert s.valid_signature(cfg, VOICE_URL, params, sig)
    assert not s.valid_signature(cfg, VOICE_URL + "/", params, sig)
    assert not s.valid_signature(
        cfg, "http://robot.arleserver.cfd/api/twilio/voice", params, sig
    )
    changed = deepcopy(params)
    changed["Z"][0] = "last"
    assert not s.valid_signature(cfg, VOICE_URL, changed, sig)
    assert not s.valid_signature(cfg, VOICE_URL, params, ""), (
        "empty signatures accepted"
    )


@pytest.mark.parametrize("url", [MEDIA_URL, MEDIA_URL + "/"])
def test_ws_signature_uses_only_fixed_wss_and_documented_slash(url):
    s = security()
    cfg = s.Config.from_env(ENV)
    assert s.valid_media_signature(cfg, sign(url))


@pytest.mark.parametrize(
    "url",
    [
        "https://robot.arleserver.cfd/api/twilio/media",
        MEDIA_URL + "?x=1",
        "wss://foreign.invalid/api/twilio/media",
        MEDIA_URL + "/foreign",
    ],
)
def test_foreign_ws_signature_urls_are_rejected(url):
    s = security()
    assert not s.valid_media_signature(s.Config.from_env(ENV), sign(url))


@pytest.mark.parametrize(
    "field,value",
    [
        ("TWILIO_AUTH_TOKEN", ""),
        ("TWILIO_ACCOUNT_SID", "ACnot-valid"),
        ("TWILIO_PHONE_NUMBER", "12025550123"),
        ("TWILIO_PHONE_NUMBER", "+01234"),
        ("LIVEKIT_API_KEY", ""),
        ("LIVEKIT_API_SECRET", ""),
        ("LIVEKIT_URL", "https://user:password@livekit:7880"),
        ("LIVEKIT_URL", "wss://public.example:7880"),
        ("LIVEKIT_URL", "ws://1.1.1.1:7880"),
        ("LIVEKIT_URL", "http://livekit:7880"),
    ],
)
def test_missing_or_malformed_environment_fails_closed_without_leaking(field, value):
    s = security()
    values = {**ENV, field: value}
    assert s.Config.from_env(values) is None
    cfg = s.Config.from_env(ENV)
    assert ENV["TWILIO_AUTH_TOKEN"] not in repr(cfg)
    assert ENV["LIVEKIT_API_SECRET"] not in repr(cfg)
    assert ENV["TWILIO_PHONE_NUMBER"] not in repr(cfg)


@pytest.mark.parametrize(
    "field,value",
    [
        ("AccountSid", ["AC" + "d" * 32]),
        ("To", ["+12025550999"]),
        ("CallSid", ["CAforeign"]),
        ("CallSid", [CALL, CALL]),
        ("To", [ENV["TWILIO_PHONE_NUMBER"], "+12025550999"]),
    ],
)
def test_signed_foreign_or_ambiguous_webhooks_cannot_authorize(field, value):
    s = security()
    fields = {
        "AccountSid": [ACCOUNT],
        "To": [ENV["TWILIO_PHONE_NUMBER"]],
        "CallSid": [CALL],
    }
    fields[field] = value
    with pytest.raises(s.BridgeError):
        s.authorized_call(s.Config.from_env(ENV), fields)


def test_pending_retry_reuses_nonce_but_consumption_and_expiry_prevent_replay():
    s = security()
    now = [0.0]
    store = s.Bindings(clock=lambda: now[0])
    binding = store.reserve(CALL)
    assert len(binding) >= 32
    assert store.reserve(CALL) == binding
    store.consume(CALL, binding)
    with pytest.raises(s.BridgeError):
        store.consume(CALL, binding)
    store.release(CALL)
    with pytest.raises(s.BridgeError):
        store.reserve(CALL)
    other = "CA" + "d" * 32
    expired = store.reserve(other)
    now[0] = 30.01
    with pytest.raises(s.BridgeError):
        store.consume(other, expired)
    with pytest.raises(s.BridgeError):
        store.reserve(other)


def test_pending_and_active_capacity_and_foreign_binding():
    s = security()
    store = s.Bindings(clock=lambda: 0)
    calls = ["CA" + f"{n:032x}" for n in range(18)]
    bindings = [store.reserve(call) for call in calls[:16]]
    assert store.reserve(calls[16]) is None
    with pytest.raises(s.BridgeError):
        store.consume(calls[1], bindings[0])
    store.consume(calls[0], bindings[0])
    store.consume(calls[1], bindings[1])
    with pytest.raises(s.BridgeError) as caught:
        store.consume(calls[2], bindings[2])
    assert caught.value.code == "capacity"
    store.release(calls[0])
    with pytest.raises(s.BridgeError):
        store.consume(calls[2], bindings[2])
    store.consume(calls[3], bindings[3])
    assert store.active_count == 2


@pytest.mark.parametrize(
    "path,value",
    [
        (("start", "accountSid"), "AC" + "f" * 32),
        (("start", "callSid"), "CAinvalid"),
        (("start", "streamSid"), "MZ" + "d" * 32),
        (("streamSid",), "MZinvalid"),
        (("start", "tracks"), ["outbound"]),
        (("start", "mediaFormat", "encoding"), "audio/pcm"),
        (("start", "mediaFormat", "sampleRate"), "8000"),
        (("start", "mediaFormat", "channels"), True),
        (("start", "customParameters", "call_binding"), "foreign"),
    ],
)
def test_invalid_start_is_rejected_without_consuming_own_binding(path, value):
    s = security()
    cfg, store = s.Config.from_env(ENV), s.Bindings(clock=lambda: 0)
    binding = store.reserve(CALL)
    message = start(binding)
    target = message
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(s.BridgeError):
        s.authorize_start(cfg, store, message)
    assert store.active_count == 0
    assert s.authorize_start(cfg, store, start(binding)) == (CALL, STREAM)


def test_replay_ledger_saturates_closed_instead_of_evicting_live_used_calls():
    s = security()
    now = [0]
    store = s.Bindings(clock=lambda: now[0])
    first = None
    for n in range(1024):
        call = "CA" + f"{n:032x}"
        binding = store.reserve(call)
        assert binding
        first = first or call
        store.consume(call, binding)
        store.release(call)
    assert store.reserve("CA" + f"{1025:032x}") is None
    with pytest.raises(s.BridgeError):
        store.reserve(first)
    now[0] = 86401
    assert store.reserve("CA" + f"{1025:032x}")
