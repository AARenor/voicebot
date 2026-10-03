"""Hotel presentation stays local, public, and connected to server-owned data."""

import hashlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.server import create_app

STATIC = Path(__file__).resolve().parents[1] / "app/hotel/static"


def test_hotel_assets_are_local_and_content_versioned() -> None:
    assets: list[str] = []

    class Parser(HTMLParser):
        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
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
            assert parse_qs(parts.query).get("v") == [
                hashlib.sha256(content).hexdigest()[:12]
            ]
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
    assert 'href="https://robot.arleserver.cfd/?book=stay"' in html
    assert 'href="https://robot.arleserver.cfd/?book=spa"' in html
    assert "FIKTIIVNE HOTELL" in html
    assert "Päris külastuskohta pole" in html
    assert 'id="room-grid"></div>' in html
    assert 'id="phone-number" hidden' in html


def test_hotel_operator_links_keep_the_management_domain() -> None:
    links: list[str] = []

    class Parser(HTMLParser):
        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            if tag == "a":
                href = dict(attrs).get("href")
                if href:
                    links.append(href)

    with patch.dict("os.environ", {}, clear=True), TestClient(create_app()) as client:
        response = client.get("/hotel", headers={"Host": "meretuule.arleserver.cfd"})
        assert response.status_code == 200
        Parser().feed(response.text)
    assert not any(href == "/" or href.startswith(("/?", "/#")) for href in links)
    assert "https://meretuule.arleserver.cfd/" in links
    assert "/hotel" not in links
    assert {
        href for href in links if urlsplit(href).hostname == "robot.arleserver.cfd"
    } == {
        "https://robot.arleserver.cfd/",
        "https://robot.arleserver.cfd/?book=stay",
        "https://robot.arleserver.cfd/?book=spa",
        "https://robot.arleserver.cfd/#demo-section",
    }


@pytest.mark.parametrize(
    "host",
    [
        "robot.arleserver.cfd",
        "ROBOT.ARLESERVER.CFD",
        "robot.arleserver.cfd:443",
        "robot.arleserver.cfd.:443",
    ],
)
@pytest.mark.parametrize(
    "path", ["/hotel", "/hotel/", "/hotel?source=old", "/hotel/?source=old"]
)
def test_old_robot_hotel_page_is_gone_without_a_redirect(host, path) -> None:
    with patch.dict("os.environ", {}, clear=True), TestClient(create_app()) as client:
        response = client.get(path, headers={"Host": host}, follow_redirects=False)
    assert response.status_code == 410
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex"
    assert "Location" not in response.headers
    assert "<title>Meretuule" not in response.text


@pytest.mark.parametrize(
    "forwarded",
    [
        {"X-Forwarded-Host": "meretuule.arleserver.cfd"},
        {"Forwarded": "host=meretuule.arleserver.cfd;proto=https"},
        {
            "X-Forwarded-Host": "meretuule.arleserver.cfd",
            "Forwarded": "host=meretuule.arleserver.cfd;proto=https",
        },
    ],
)
def test_forwarded_headers_cannot_restore_the_old_hotel_page(forwarded) -> None:
    with patch.dict("os.environ", {}, clear=True), TestClient(create_app()) as client:
        response = client.get(
            "/hotel", headers={"Host": "robot.arleserver.cfd", **forwarded}
        )
    assert response.status_code == 410


def test_meretuule_and_local_routes_keep_the_hotel_page_and_assets() -> None:
    with patch.dict("os.environ", {}, clear=True), TestClient(create_app()) as client:
        for host in ("meretuule.arleserver.cfd", "localhost:8000", "testserver"):
            for path in ("/hotel", "/hotel/"):
                response = client.get(path, headers={"Host": host})
                assert response.status_code == 200
                assert "<title>Meretuule" in response.text
        headers = {
            "Host": "meretuule.arleserver.cfd",
            "X-Forwarded-Host": "robot.arleserver.cfd",
        }
        assert client.get("/hotel", headers=headers).status_code == 200
        for path in (
            "/hotel.css",
            "/hotel.js",
            "/hotel/coastal-hotel.svg",
            "/fonts/figtree-latin.woff2",
            "/api/public/property",
            "/api/public/catalogue",
        ):
            assert client.get(path, headers=headers).status_code == 200


def test_retiring_the_old_hotel_page_preserves_operator_root_health_and_auth() -> None:
    with (
        patch.dict("os.environ", {"OPERATOR_TOKEN": "fixture-operator"}, clear=True),
        TestClient(create_app()) as client,
    ):
        headers = {"Host": "robot.arleserver.cfd"}
        dashboard = client.get("/", headers=headers)
        assert dashboard.status_code == 200
        assert "<title>Vastuvõtulaud" in dashboard.text
        assert dashboard.text.count('href="https://meretuule.arleserver.cfd/"') >= 2
        assert 'href="/hotel"' not in dashboard.text
        health = client.get("/health", headers=headers)
        assert health.status_code == 200 and health.json() == {"ok": True}
        for host in ("robot.arleserver.cfd", "meretuule.arleserver.cfd"):
            for path in ("/api/bookings", "/api/rooms", "/api/stays"):
                denied = client.get(path, headers={"Host": host})
                assert denied.status_code == 403
                assert denied.headers["Cache-Control"] == "no-store"
        allowed = client.get(
            "/api/calls",
            headers={**headers, "Authorization": "Bearer fixture-operator"},
        )
        assert allowed.status_code == 200
        assert allowed.headers["Cache-Control"] == "no-store"


def test_hotel_home_and_dashboard_demo_links_use_public_root() -> None:
    hrefs: list[str] = []

    class Parser(HTMLParser):
        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            if tag == "a" and dict(attrs).get("href"):
                hrefs.append(dict(attrs)["href"])

    with patch.dict("os.environ", {}, clear=True), TestClient(create_app()) as client:
        for path in ("/", "/hotel"):
            hrefs.clear()
            response = client.get(path)
            assert response.status_code == 200
            Parser().feed(response.text)
            assert hrefs.count("https://meretuule.arleserver.cfd/") == 2
            assert "/hotel" not in hrefs
