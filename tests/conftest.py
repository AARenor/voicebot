"""Historical fixtures keep their original domain; restaurant tests use defaults."""

import pytest


@pytest.fixture(autouse=True)
def explicit_fixture_business(request, monkeypatch):
    # The legacy booking/voice regressions still protect the reused safeguards.
    # New restaurant tests explicitly exercise the restaurant default and wiring.
    if not request.node.path.stem.startswith("test_restaurant"):
        monkeypatch.setenv("VOICEBOT_BUSINESS_TYPE", "hotel_spa")
