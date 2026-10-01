# Current website / pipeline diagram

Open `website-booking.html` locally. It is standalone and is **not** a new page
deployed at robot.arleserver.cfd. Sources are pinned to committed application/
deployment bytes at `5e1c10c868d8fdceeae2184b8503811ce9e6288e`, which match the
running implementation9a8d1d2 for those paths (intervening commits were docs).

```bash
node /path/to/archify/bin/archify.mjs finalize architecture \
  .archify/architecture-website-booking-20261001-213712/candidate.json \
  .archify/architecture-website-booking-20261001-213712/website-booking.html \
  --repo-root "$PWD" --quality showcase --json
```

Validated specification → delivery → strict artifact/provenance check → real
Chrome browser check all **PASS**. Specification SHA256
`bf10ebfe211bbecda9690b0ba9e0ce34ef5295cffeec2ab802edd3323c3d1477`,
HTML SHA256 `4820dc100abaac1cc54ba9ffa922a41bf85409d3b4fe08f25b6cb60b29eaf62c`.
Receipts are retained beside the candidate. Absolute paths in receipts describe
the verification host; regeneration on another host creates its own receipts.

`visual-check/` contains four artifact-bound desktop captures (light/dark,
1440×900 and2048×1320) plus its automated receipt/contact sheet. Automated
containment/readability/chrome/theme/capture checks passed. The light1440 and
dark2048 images were inspected: separated website reads and authenticated
turn path, no crossing routes or clipped nodes; source badges/labels present.
Zoom can help dense evidence labels. A small declared vertical page scroll is
accepted; this is not a promise of zero scrolling on every device.

Proposed private provider booking panel is described only in notes and the
[design](../../docs/research/website-booking-architecture/DESIGN.md), not drawn
as a current operational edge. No guest summaries or credentials in captures.
