# Meretuule restaurant demo domain

`https://meretuule.arleserver.cfd/` is the canonical guest address for the
fictional Meretuule Demo Restaurant. The existing authored restaurant reception
UI is served at the application root, not through the retired hotel renderer.
`https://robot.arleserver.cfd/` remains the restaurant-management entry point;
its primary demo links open the canonical Meretuule root directly. Both domains
use the same business backend and operator authorization.
The former guest addresses `https://robot.arleserver.cfd/hotel` and
`https://robot.arleserver.cfd/hotel/` are retired. Public ingress permanently
redirects them with HTTP 301 to `https://meretuule.arleserver.cfd/`, preserving
query strings. The application's direct robot-host handler returns HTTP 410
with no `Location` header if the ingress redirect is not used.

## Existing ingress

The current wildcard DNS and application tunnel already forward
`*.arleserver.cfd` to the Coolify HTTPS proxy. No additional DNS record,
tunnel, container, or provider credential is required.

[`traefik.yml`](traefik.yml) uses the application's stable Docker-provider
service. The public-host router forwards `/` unchanged to the authored restaurant
renderer. Remove the old root-to-`/hotel` rewrite: restaurant mode returns 410
for that retired renderer. A separate robot-only router still redirects exact
old hotel paths. Restaurant assets and APIs pass through unchanged, and existing
operator authorization still applies to private APIs.
The routes do not depend on a changing container name or IP address.
No hotel demo is published by restaurant mode. Do not restore hotel/spa HTML
against the restaurant backend or erase old booking/history databases.

## Runtime boundaries

- `VOICEBOT_BUSINESS_TYPE` defaults to `restaurant`; do not set `hotel_spa`
  on this restaurant deployment.
- Preserve the original shared `/data` volume. Restaurant state defaults to
  `/data/restaurant-booking.db` via `RESTAURANT_STATE_DB`.
- `RESTAURANT_DEMO_WRITES` inherits the existing `EASY_DEMO_WRITES` synthetic
  opt-in when unset; explicit `0` disables restaurant writes. Publication
  acceptance is read-only and does not require an operator sign-in or booking.
- Keep telephone release synchronization and existing media settings intact;
  verify matching release/source/configuration metadata rather than claiming
  telephone readiness from a healthy website.

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

- Meretuule `/`, versioned assets and `/api/public/*`: 200.
- The authored restaurant reception UI loads its menu, opening hours, venue
  name and policies from `/api/public/restaurant`; the disclosed venue is
  `Meretuule Demo Restaurant`. Language selection remains ET/EN/RU.
- Both canonical restaurant-demo links on robot open Meretuule in a real
  browser click. Restaurant assets match the selected committed release.
- Robot `/` and `/health` remain healthy; private `/api/bookings` without
  authorization returns 403 with `Cache-Control: no-store` on both domains.
- Public robot `/hotel` and `/hotel/`: HTTP 301 with `Location` set to the exact
  canonical Meretuule root; original query strings are preserved. Direct app
  requests using the robot hostname: HTTP 410 with no `Location` header.
- Run `tests/meretuule_browser_checks.js` through a Node.js Playwright browser-code
  runner for public HTTPS, canonical links, retired paths, asset hashes,
  catalogue and authorization checks.
- Run `tests/restaurant_browser_checks.js` through `tests/run_browser_checks.cjs`
  for the real restaurant fixture's language, reservation, voice, receipt,
  microphone and desktop/mobile checks. Other legacy fixture checks remain
  regressions only; they do not publish a second hotel demo.
