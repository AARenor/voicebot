# Meretuule public domain

`https://meretuule.arleserver.cfd/` is the canonical guest address for the
fictional Meretuule restaurant website, including homepage links from local previews.
`https://robot.arleserver.cfd/` remains the operator dashboard; booking and
voice-demo links explicitly use that management domain.
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
service. The public-host router rewrites only `/` to the internal `/hotel`
renderer. A separate robot-only router redirects the exact old hotel paths;
do not redirect the shared renderer unconditionally, which would loop on the
public root. CSS, JavaScript, fonts, illustrations, APIs and all other paths
remain unchanged. Existing operator authorization still applies to private APIs.
The routes do not depend on a changing container name or IP address.
The `/hotel` handler remains available for this internal rewrite and local
previews; it is no longer a public guest entry point on the robot hostname.

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
- Root browser title: `Meretuule — restorani demo`, with fictional table,
  menu and restaurant-rule catalogues from `/api/public/restaurant`.
  Homepage links use the exact Meretuule root;
  booking/demo links use the robot domain.
- Robot `/` and `/health` remain healthy; private `/api/bookings` without
  authorization returns 403 with `Cache-Control: no-store` on both domains.
- Public robot `/hotel` and `/hotel/`: HTTP 301 with `Location` set to the exact
  canonical Meretuule root; original query strings are preserved. Direct app
  requests using the robot hostname: HTTP 410 with no `Location` header.
- Run `tests/meretuule_browser_checks.js` through a Node.js Playwright browser-code
  runner for public HTTPS, canonical links, retired paths, asset hashes,
  catalogue and authorization checks.
- Run `tests/restaurant_public_browser_checks.js` against the local restaurant
  fixture for responsive layout, safe provider text, menu/tables and API failures.
  The retained `/hotel` renderer and CSS filename are compatibility names only;
  explicit `hotel_spa` rollback mode still uses its separate archived page.
