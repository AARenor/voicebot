"""Named-host publication reuses the current restaurant backend, never old rooms."""

import hashlib
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_restaurant_http import client


@pytest.mark.parametrize("path", ["/hotel", "/hotel/"])
def test_public_host_internal_renderer_serves_restaurant_not_operator_shell(
    client, path
):
    response = client.get(path, headers={"Host": "meretuule.arleserver.cfd"})
    assert response.status_code == 200
    assert "<title>Meretuule — restorani demo</title>" in response.text
    assert 'id="table-grid"' in response.text and 'id="menu-list"' in response.text
    assert 'id="operator-token"' not in response.text
    assert 'href="https://robot.arleserver.cfd/?book=table"' in response.text
    assert 'href="https://robot.arleserver.cfd/#demo-section"' in response.text
    assert "hotelli ja spaa" not in response.text


def test_robot_renderer_stays_retired_and_dashboard_has_canonical_demo_links(client):
    retired = client.get("/hotel?via=old", headers={"Host": "robot.arleserver.cfd"})
    assert retired.status_code == 410 and "location" not in retired.headers
    assert retired.headers["cache-control"] == "no-store"
    page = client.get("/")
    assert page.status_code == 200
    assert page.text.count('href="https://meretuule.arleserver.cfd/"') == 2
    assert 'id="reservation-party"' in page.text and 'id="operator-token"' in page.text


def test_public_assets_are_content_versioned_and_legacy_mode_remains_separate(client):
    urls = []

    class Assets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "script":
                urls.append(values["src"])
            if tag == "link" and values.get("rel") == "stylesheet":
                urls.append(values["href"])

    Assets().feed(
        client.get("/hotel", headers={"Host": "meretuule.arleserver.cfd"}).text
    )
    assert len(urls) == 2
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        assert parse_qs(urlsplit(url).query)["v"] == [
            hashlib.sha256(response.content).hexdigest()[:12]
        ]
    assert client.get("/api/config").status_code == 404
    assert client.get("/api/public/property").json()["business_type"] == "restaurant"
