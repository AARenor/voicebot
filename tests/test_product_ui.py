"""Native dashboard auth lifecycle without a frontend framework."""

import hashlib
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import override
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from app.server import create_app


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app/dashboard/static/dashboard.js"


def test_restaurant_operator_has_one_table_form_and_no_contact_collection() -> None:
    html = SCRIPT.with_name("index.html").read_text(encoding="utf-8")
    assert "Meretuule restoran" in html
    for control in (
        "new-table-date",
        "new-start-time",
        "new-party-size",
        "booking-recap-read",
    ):
        assert f'id="{control}"' in html, f"missing {control}"
    for retired in (
        "booking-kind-slot",
        "booking-kind-stay",
        "new-service",
        "new-checkin",
        "stays-section",
    ):
        assert f'id="{retired}"' not in html, f"active legacy control {retired}"
    assert "Europe/Tallinn" in html and "lapsed" in html
    assert 'type="email"' not in html and 'type="tel"' not in html
    assert "Fiktiivne külaline" in html


def test_public_restaurant_shows_menu_capacity_rules_and_only_operator_links() -> None:
    public = ROOT / "app/hotel/static"
    html = (public / "index.html").read_text(encoding="utf-8")
    js = (public / "hotel.js").read_text(encoding="utf-8")
    assert "Meretuule" in html and "Fiktiivne restoran" in html
    for target in ("menu", "tables", "table-grid", "reservation-rules", "phone-number"):
        assert f'id="{target}"' in html, f"missing {target}"
    assert "?book=table" in html
    assert "?book=stay" not in html and "?book=spa" not in html
    assert 'id="rooms"' not in html and 'id="spa"' not in html
    assert "/api/public/property" in js and "/api/public/catalogue" in js
    assert "/api/booking/" not in js and "Authorization" not in js
    assert 'book:"stay"' not in js and "room-grid" not in js
    assert "innerHTML" not in js and "+1202555" not in html + js


def test_dashboard_assets_use_content_versioned_urls(tmp_path) -> None:
    urls: list[str] = []

    class Parser(HTMLParser):
        @override
        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            values = dict(attrs)
            if tag == "script":
                url = values.get("src")
            elif tag == "link" and values.get("rel") == "stylesheet":
                url = values.get("href")
            else:
                return
            if url:
                urls.append(url)

    with (
        patch.dict(
            "os.environ",
            {"RESTAURANT_STATE_DB": str(tmp_path / "restaurant.db")},
            clear=True,
        ),
        TestClient(create_app()) as client,
    ):
        page = client.get("/")
        assert page.status_code == 200
        Parser().feed(page.text)
        assert {urlsplit(url).path for url in urls} == {
            "/dashboard.css",
            "/dashboard.js",
            "/call-history.js",
        }
        for url in urls:
            parts = urlsplit(url)
            content = (SCRIPT.parent / parts.path.lstrip("/")).read_bytes()
            version = hashlib.sha256(content).hexdigest()[:12]
            assert parse_qs(parts.query).get("v") == [version], url
            assert client.get(url).content == content


def test_restaurant_public_assets_keep_content_versioned_paths(tmp_path) -> None:
    public = ROOT / "app/hotel/static"
    urls: list[str] = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs) -> None:
            values = dict(attrs)
            if tag == "script" and values.get("src"):
                urls.append(values["src"])
            elif tag == "link" and values.get("rel") == "stylesheet":
                urls.append(values["href"])

    with (
        patch.dict(
            "os.environ",
            {"RESTAURANT_STATE_DB": str(tmp_path / "restaurant.db")},
            clear=True,
        ),
        TestClient(create_app()) as client,
    ):
        response = client.get("/hotel")
        assert response.status_code == 200
        Parser().feed(response.text)
        assert {urlsplit(url).path for url in urls} == {"/hotel.js", "/hotel.css"}
        for url in urls:
            parts = urlsplit(url)
            content = (public / parts.path.lstrip("/")).read_bytes()
            assert parse_qs(parts.query).get("v") == [
                hashlib.sha256(content).hexdigest()[:12]
            ]
            assert client.get(url).content == content


def test_form_inputs_have_names_and_explicit_autocomplete() -> None:
    inputs: list[dict[str, str | None]] = []

    class Parser(HTMLParser):
        @override
        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            if tag == "input":
                inputs.append(dict(attrs))

    html = SCRIPT.with_name("index.html").read_text(encoding="utf-8")
    Parser().feed(html)
    assert inputs
    for field in inputs:
        assert field.get("name"), field["id"]
        assert field.get("autocomplete"), field["id"]


def test_product_controls_and_no_persistent_credential() -> None:
    html = SCRIPT.with_name("index.html").read_text(encoding="utf-8")
    for control in (
        "connect",
        "logout",
        "bookings",
        "booking-date",
        "booking-prev",
        "booking-next",
        "demo-start",
        "demo-language",
        "demo-text",
        "demo-send",
        "demo-mic",
        "demo-audio",
        "demo-end",
    ):
        assert f'id="{control}"' in html, f"missing {control}"
    assert "HTTP" in html and "väljamõeldud" in html
    assert "Telefonikõne: kinnitamata" in html
    assert "„Jah, kinnitan.”" in html and "„Jah, tühista.”" in html
    assert 'rel="icon"' in html and "data:image/svg+xml" in html
    assert SCRIPT.exists(), "product dashboard controller missing"
    js = SCRIPT.read_text(encoding="utf-8")
    assert "sessionStorage.setItem" not in js
    assert "localStorage.setItem" not in js
    assert "audio/mpeg" in js
    assert "getUserMedia" in js and "getTracks" in js
    assert "quote_fidelity" not in js
    assert "LiveKit ühendatud" not in js
    assert "innerHTML" not in js


def test_auth_headers_logout_late_response_and_signed_out_poll() -> None:
    result = subprocess.run(
        [
            "node",
            str(ROOT / "tests/dashboard_ui_checks.cjs"),
            str(SCRIPT),
            str(SCRIPT.with_name("index.html")),
            str(SCRIPT.with_name("call-history.js")),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ui_checks_ok", "UI checks did not finish"
