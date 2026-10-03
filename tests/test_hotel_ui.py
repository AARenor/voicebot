"""Hotel presentation stays local, public, and connected to server-owned data."""

import hashlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.server import create_app

STATIC = Path(__file__).resolve().parents[1] / "app/hotel/static"


def test_hotel_assets_are_local_and_content_versioned() -> None:
    assets: list[str] = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = dict(attrs)
            if tag == "script":
                assets.append(values["src"])
            elif tag == "link" and values.get("rel") == "stylesheet":
                assets.append(values["href"])

    with patch.dict("os.environ", {}, clear=True), TestClient(create_app()) as client:
        response = client.get("/hotel")
        assert response.status_code == 200
        Parser().feed(response.text)
        assert {urlsplit(url).path for url in assets} == {"/hotel.css", "/hotel.js"}
        for url in assets:
            parts = urlsplit(url)
            content = (STATIC / parts.path.lstrip("/")).read_bytes()
            assert parse_qs(parts.query).get("v") == [hashlib.sha256(content).hexdigest()[:12]]
            assert client.get(url).content == content
        illustration = client.get("/hotel/coastal-hotel.svg")
        assert illustration.status_code == 200
        assert illustration.headers["content-type"].startswith("image/svg+xml")


def test_public_hotel_does_not_embed_credentials_inventory_or_phone() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "hotel.js").read_text(encoding="utf-8")
    assert "/api/public/property" in script
    assert "/api/public/catalogue" in script
    assert "Authorization" not in script
    assert "innerHTML" not in script
    assert "sessionStorage" not in script and "localStorage" not in script
    assert "+1202555" not in html + script
    assert 'href="/?book=stay"' in html and 'href="/?book=spa"' in html
    assert "FIKTIIVNE HOTELL" in html
    assert "Päris külastuskohta pole" in html
    assert 'id="room-grid"></div>' in html
    assert 'id="phone-number" hidden' in html
