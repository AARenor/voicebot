import copy
import importlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data/demo/telephone-demo.json"


def demo_module():
    assert (
        importlib.util.find_spec("app.demo") is not None
    ), "fictional demo loader is missing"
    return importlib.import_module("app.demo")


def test_saved_profile_faq_and_guests_are_loaded_without_booking_examples():
    demo = demo_module()
    loaded = demo.load_demo_data()
    assert loaded["profile"]["name"] == "Meretuule Demo Spa"
    assert loaded["faq"][0]["answer_et"].startswith("Ei. Meretuule Demo Spa")
    assert loaded["guests"]["guest-001"]["email"] == "demo.esimene@example.invalid"
    assert set(loaded) == {"synthetic", "profile", "faq", "guests"}
    assert "2026-10-05" not in json.dumps(loaded)
    assert "working_hours" not in json.dumps(loaded)
    assert "existing_backend_reference" not in loaded


def test_loader_ignores_poisoned_example_dates_hours_and_ids(tmp_path):
    demo = demo_module()
    source = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    source["reference_date"] = "1900-01-01"
    source["example_bookings"] = [{"start": "1900-01-01", "status": "confirmed"}]
    source["existing_backend_reference"] = {
        "service": {"id": "foreign"},
        "working_hours": "open always",
    }
    source["tool_example"] = {"search": "invent availability"}
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    assert demo.load_demo_data(path) == demo.load_demo_data()


@pytest.mark.parametrize(
    "mutation",
    [
        "non_synthetic",
        "automatic_import",
        "real_email",
        "real_phone",
        "customer_id",
        "real_location",
        "notifications",
        "spoken_prices",
    ],
)
def test_loader_rejects_real_guest_or_unsafe_fixture_configuration(tmp_path, mutation):
    demo = demo_module()
    source = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if mutation == "non_synthetic":
        source["synthetic"] = False
    elif mutation == "automatic_import":
        source["automatic_import"] = True
    elif mutation == "real_email":
        source["guests"][0]["guest"]["email"] = "person@example.com"
    elif mutation == "real_phone":
        source["guests"][0]["guest"]["phone"] = "+37255555555"
    elif mutation == "customer_id":
        source["guests"][0]["guest"]["customerId"] = 1
    elif mutation == "real_location":
        source["fictional_property"]["address"] = "A real address"
    elif mutation == "notifications":
        source["safety"]["send_notifications"] = True
    else:
        source["safety"]["speak_prices"] = True
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid synthetic demo data"):
        demo.load_demo_data(path)


def test_profile_uses_current_tallinn_date_and_no_real_contacts():
    demo = demo_module()
    result = demo.get_demo_profile(
        demo.load_demo_data(),
        call_id="a" * 32,
        now=datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc),
    )
    assert result["current_date"] == "2026-11-02"
    assert result["timezone"] == "Europe/Tallinn"
    assert result["synthetic"] is True
    assert result["call_id"] == "a" * 32
    assert (
        result["guest_fixtures"][0]["guest"]["email"]
        == "demo.esimene+" + "a" * 32 + "@example.invalid"
    )
    assert all(
        g["guest"]["phone"].startswith("+120255501") for g in result["guest_fixtures"]
    )
    assert "example_bookings" not in result
    assert "backend" in result["availability_source"]


def test_data_path_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    demo = demo_module()
    monkeypatch.chdir(tmp_path)
    assert demo.load_demo_data()["synthetic"] is True


def test_readers_cannot_mutate_fixture_guests_or_faq():
    demo = demo_module()
    first = demo.load_demo_data()
    original = copy.deepcopy(first)
    first["guests"]["guest-001"]["email"] = "real@example.com"
    first["faq"][0]["answer_et"] = "not fiction"
    assert demo.load_demo_data() == original
    result = demo.get_demo_profile(original, call_id="a" * 32)
    result["faq"][0]["answer_et"] = "changed"
    assert original["faq"][0]["answer_et"] != "changed"


def test_telephony_image_copies_approved_demo_fixtures():
    assert (
        "COPY data/demo/ ./data/demo/"
        in (ROOT / "deploy/telephony/Dockerfile").read_text(encoding="utf-8")
    )
