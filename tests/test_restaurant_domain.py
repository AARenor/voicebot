"""Canonical ingress and real reception HTML must publish the restaurant."""

import re
from html.parser import HTMLParser
from pathlib import Path

import yaml

from tests.test_restaurant_http import client  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "https://meretuule.arleserver.cfd/"


class DemoLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.destinations = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "a" and "demo-website-link" in attributes.get("class", "").split():
            self.destinations.append(attributes.get("href"))


def test_canonical_ingress_root_reaches_the_restaurant_not_the_retired_hotel(client):
    config = yaml.safe_load((ROOT / "deploy/meretuule/traefik.yml").read_text())
    path = "/"
    for name in config["http"]["routers"]["meretuule"].get("middlewares", []):
        rewrite = config["http"]["middlewares"][name].get("replacePathRegex")
        if rewrite:
            path = re.sub(rewrite["regex"], rewrite["replacement"], path)
    response = client.get(path, headers={"Host": "meretuule.arleserver.cfd"})
    assert response.status_code == 200, "Ingress still selects the retired hotel"
    assert 'id="reservation-prepare"' in response.text
    assert 'id="restaurant-name"' in response.text
    assert client.get("/hotel").status_code == 410


def test_robot_reception_has_two_canonical_restaurant_demo_links(client):
    response = client.get("/", headers={"Host": "robot.arleserver.cfd"})
    assert response.status_code == 200
    links = DemoLinks()
    links.feed(response.text)
    assert links.destinations == [CANONICAL, CANONICAL]
    assert 'id="operator-token"' in response.text
    assert 'id="reservation-prepare"' in response.text
