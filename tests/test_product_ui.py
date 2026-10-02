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


def test_dashboard_assets_use_content_versioned_urls() -> None:
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

    with patch.dict("os.environ", {}, clear=True), TestClient(create_app()) as client:
        page = client.get("/")
        assert page.status_code == 200
        Parser().feed(page.text)
        assert {urlsplit(url).path for url in urls} == {
            "/dashboard.css",
            "/dashboard.js",
        }
        for url in urls:
            parts = urlsplit(url)
            content = (SCRIPT.parent / parts.path.lstrip("/")).read_bytes()
            version = hashlib.sha256(content).hexdigest()[:12]
            assert parse_qs(parts.query).get("v") == [version], url
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
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ui_checks_ok", "UI checks did not finish"
