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


def test_sip_dispatch_targets_the_configured_worker_name():
    _, rule = specifications({**ENV, "VOICEBOT_AGENT_NAME": "fixture-alternate"})
    assert rule.room_config.agents[0].agent_name == "fixture-alternate"


@pytest.mark.parametrize("name", ["", "bad name", "x" * 49, None])
def test_invalid_sip_worker_name_fails_before_provisioning(name):
    with pytest.raises(ValueError, match="worker name"):
        specifications({**ENV, "VOICEBOT_AGENT_NAME": name})


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


def test_matching_trunk_and_rule_are_reused_without_creating_objects():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.sip_setup import provision

    trunk, rule = specifications(ENV)
    trunk.sip_trunk_id = "fixture-trunk"
    rule.sip_dispatch_rule_id = "fixture-rule"
    rule.trunk_ids.append(trunk.sip_trunk_id)
    sip = SimpleNamespace(
        list_sip_inbound_trunk=AsyncMock(return_value=SimpleNamespace(items=[trunk])),
        list_sip_dispatch_rule=AsyncMock(return_value=SimpleNamespace(items=[rule])),
        create_sip_inbound_trunk=AsyncMock(),
        create_sip_dispatch_rule=AsyncMock(),
    )
    assert asyncio.run(provision(SimpleNamespace(sip=sip), ENV)) == (
        "fixture-trunk",
        "fixture-rule",
    )
    sip.create_sip_inbound_trunk.assert_not_awaited()
    sip.create_sip_dispatch_rule.assert_not_awaited()


def test_matching_trunk_does_not_overwrite_mismatched_dispatch():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.sip_setup import provision

    trunk, rule = specifications(ENV)
    trunk.sip_trunk_id = "fixture-trunk"
    rule.trunk_ids.append(trunk.sip_trunk_id)
    rule.hide_phone_number = False
    sip = SimpleNamespace(
        list_sip_inbound_trunk=AsyncMock(return_value=SimpleNamespace(items=[trunk])),
        list_sip_dispatch_rule=AsyncMock(return_value=SimpleNamespace(items=[rule])),
        create_sip_dispatch_rule=AsyncMock(),
    )
    with pytest.raises(ValueError, match="existing dispatch differs"):
        asyncio.run(provision(SimpleNamespace(sip=sip), ENV))
    sip.create_sip_dispatch_rule.assert_not_awaited()


def test_orphaned_managed_dispatch_cannot_create_partial_new_trunk():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.sip_setup import provision

    trunk, rule = specifications(ENV)
    trunk.sip_trunk_id = "fixture-new-trunk"
    rule.trunk_ids.append("fixture-foreign-trunk")
    sip = SimpleNamespace(
        list_sip_inbound_trunk=AsyncMock(return_value=SimpleNamespace(items=[])),
        list_sip_dispatch_rule=AsyncMock(return_value=SimpleNamespace(items=[rule])),
        create_sip_inbound_trunk=AsyncMock(return_value=trunk),
    )
    with pytest.raises(ValueError):
        asyncio.run(provision(SimpleNamespace(sip=sip), ENV))
    sip.create_sip_inbound_trunk.assert_not_awaited()
