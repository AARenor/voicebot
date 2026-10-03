"""Restaurant media deployment shares web configuration without spa credentials."""

from unittest.mock import patch

import pytest

from app.telephone import validate_environment
from tests.test_telephony_deployment import manage, source_configuration


def source(**values):
    return source_configuration(
        VOICEBOT_BUSINESS_TYPE="restaurant",
        RESTAURANT_DEMO_WRITES="1",
        RESTAURANT_STATE_DB="/data/restaurant-booking.db",
        EASY_BASE_URL="",
        EASY_API_KEY="",
        EASY_DEMO_WRITES="0",
        **values,
    )


def test_restaurant_worker_does_not_require_easyappointments_credentials(tmp_path):
    with patch.dict(
        "os.environ",
        {
            "RESTAURANT_CONFIG_PATH": "/unrelated/restaurant.json",
            "RESTAURANT_STATE_DB": "/unrelated/bookings.db",
        },
        clear=True,
    ), patch.object(manage.subprocess, "run", return_value=source()):
        env = manage.environment("trusted-restaurant-fixture")
    assert env["RESTAURANT_STATE_DB"] == "/data/restaurant-booking.db"
    assert env["RESTAURANT_CONFIG_PATH"] == ""
    assert env["RESTAURANT_DEMO_WRITES"] == "1"
    assert env["EASY_API_KEY"] == ""
    validate_environment(
        {
            **env,
            "LIVEKIT_URL": "ws://localhost:7880",
            "VOICEBOT_TELEPHONE_DEMO": "1",
            "RESTAURANT_STATE_DB": str(tmp_path / "restaurant.db"),
        }
    )


@pytest.mark.parametrize(
    "path", [":memory:", "/tmp/bookings.db", "/data/../tmp/bookings.db", "relative.db"]
)
def test_restaurant_journal_must_be_inside_shared_volume(path):
    with patch.dict("os.environ", {}, clear=True), patch.object(
        manage.subprocess,
        "run",
        return_value=source_configuration(
            VOICEBOT_BUSINESS_TYPE="restaurant",
            RESTAURANT_DEMO_WRITES="1",
            RESTAURANT_STATE_DB=path,
        ),
    ):
        with pytest.raises(ValueError, match="shared database path"):
            manage.environment("trusted-restaurant-fixture")


@pytest.mark.parametrize(
    "path,accepted",
    [
        ("/data/restaurant.json", True),
        ("/app/restaurant.json", False),
        ("/data/../tmp/restaurant.json", False),
        ("relative.json", False),
    ],
)
def test_custom_restaurant_knowledge_must_be_on_shared_volume(path, accepted):
    with patch.dict("os.environ", {}, clear=True), patch.object(
        manage.subprocess, "run", return_value=source(RESTAURANT_CONFIG_PATH=path)
    ):
        if accepted:
            assert (
                manage.environment("trusted-restaurant-fixture")[
                    "RESTAURANT_CONFIG_PATH"
                ]
                == path
            )
        else:
            with pytest.raises(ValueError, match="shared restaurant configuration"):
                manage.environment("trusted-restaurant-fixture")
