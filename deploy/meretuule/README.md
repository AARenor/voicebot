# Meretuule public domain

`https://meretuule.arleserver.cfd/` serves the existing fictional hotel website.
`https://robot.arleserver.cfd/` remains the operator dashboard; booking and
voice-demo links explicitly use that management domain.

## Existing ingress

The current wildcard DNS and application tunnel already forward
`*.arleserver.cfd` to the Coolify HTTPS proxy. No additional DNS record,
tunnel, container, or provider credential is required.

[`traefik.yml`](traefik.yml) adds one hostname-specific router using the
application's stable Docker-provider service. It rewrites only `/` to `/hotel`;
CSS, JavaScript, fonts, illustrations, APIs, query strings and all other paths
remain unchanged. Existing operator authorization still applies to private APIs.
The route does not depend on a changing container name or IP address.

## Install on the existing host

From the repository root, inspect any existing destination before replacing it:

```bash
sudo install -o root -g root -m 0644 deploy/meretuule/traefik.yml \
  /data/coolify/proxy/dynamic/meretuule.yml
```

Traefik watches this directory and reloads dynamically. Do not edit generated
application Compose files or restart tunnel/proxy services: their startup
dependencies include unrelated workloads. GitHub deployment of the web app
retains the same service name, so the separate router survives redeployments.

## Verify

- Meretuule `/`, `/hotel`, versioned assets and `/api/public/*`: 200.
- Root browser title: `Meretuule — hotelli ja spaa demo`, with live synthetic
  room and spa catalogues. Follow each booking/demo link to the robot domain.
- Robot `/` and `/health` remain healthy; private `/api/bookings` without
  authorization returns 403 with `Cache-Control: no-store` on both domains.
- Run `tests/meretuule_browser_checks.js` through a Node.js Playwright browser-code
  runner for public HTTPS, asset hashes, catalogue and authorization checks.
- Run `tests/hotel_browser_checks.js` against the existing local browser fixture
  for selected-room links, mobile layout, unsafe provider text and API failures.
