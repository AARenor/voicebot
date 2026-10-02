import pytest

pytest.importorskip("livekit.api")
from app.sip_setup import specifications


ENV = {
    "SIP_NUMBER": "+15555550100",
    "SIP_ALLOWED_CIDRS": "192.0.2.1/32",
    "SIP_AUTH_USER": "fixture-user",
    "SIP_AUTH_PASSWORD": "fixture-only",
}


def test_sip_never_creates_public_wildcard():
    for key in ENV:
        with pytest.raises(ValueError):
            specifications({k: v for k, v in ENV.items() if k != key})
    for cidr in ("0.0.0.0/0", "::/0", "invalid", "0.0.0.0/1"):
        with pytest.raises(ValueError):
            specifications({**ENV, "SIP_ALLOWED_CIDRS": cidr})


def test_trunk_and_random_individual_dispatch():
    trunk, rule = specifications(ENV)
    assert list(trunk.numbers) == [ENV["SIP_NUMBER"]]
    assert trunk.auth_username and trunk.auth_password and trunk.allowed_addresses
    assert rule.hide_phone_number
    assert list(rule.numbers) == [ENV["SIP_NUMBER"]]
    assert rule.rule.dispatch_rule_individual.room_prefix == "voicebot-"
    assert not rule.rule.dispatch_rule_individual.no_randomness
    assert rule.room_config.agents[0].agent_name == "voicebot"


def test_existing_trunk_without_duration_limits_fails_closed():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.sip_setup import provision

    trunk, _ = specifications(ENV)
    trunk.ClearField("ringing_timeout")
    trunk.ClearField("max_call_duration")
    client = SimpleNamespace(
        sip=SimpleNamespace(
            list_sip_inbound_trunk=AsyncMock(
                return_value=SimpleNamespace(items=[trunk])
            )
        )
    )
    with pytest.raises(ValueError, match="existing trunk differs"):
        asyncio.run(provision(client, ENV))
