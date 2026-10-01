# Pärnu booking-system evidence

Research snapshot: **2026-09-30**. This note is an evidence ledger for the
voicebot demo and future hotel sales work. It distinguishes current adoption
from vendor customer lists and stale indexed booking pages.

## Executive conclusion

- **BOUK is currently used by at least 10 accommodation properties in Pärnu
  city.** Each confirmed row below has both an official-property-site link to
  `bouk.io` and an active, non-demo property returned by BOUK's public booking
  API.
- **No major Pärnu spa hotel is currently confirmed to use BOUK for timed spa
  treatments.** BOUK supports rooms and hourly services in one product, but
  the major Pärnu spa hotels checked currently point to SALBOS instead.
- **SALBOS is the strongest production target for Pärnu spa hotels.** Hedon,
  ESTONIA Resort/Medical Spa, Wasa Resort, Tervise Paradiis, Tervis Medical
  Spa, and Viiking expose SALBOS-style hotel/spa booking shops or are listed by
  SALBOS as users.
- For the hackathon, BOUK is a locally relevant connector only if ED Hotels
  supplies free supported sandbox/API access. Its pricing page advertises
  “Try it free” and “Full access. No credit card required,” but does not state a
  trial duration; API access/support is confined to the Professional plan with
  a €250 monthly minimum. Do not buy that plan solely for the hackathon.
- No public Pärnu switchboard dataset reports actual missed calls. A transparent
  benchmark-transfer model estimates **3,581–7,163 missed booking-intent calls**
  across Pärnu city accommodation properties during June–August, with a 30%
  midpoint of **5,372**. This is a planning estimate, not an observed local
  statistic; assumptions and the broader all-call scenario are below.
- **No current Pärnu hotel or spa deployment of QloApps or Easy!Appointments
  was confirmed.** Exact-name and technical-fingerprint searches, followed by
  checks of the official booking links for the 10-property BOUK cohort and the
  major Pärnu spa hotels, produced no match. Both products remain suitable
  open-source demo backends, not locally validated production connectors.

## Summer missed-call demand model

### What is known and what is estimated

No public English- or Estonian-language source found in this research reports
answered versus missed calls for a Pärnu hotel, spa, or the city as a whole.
The figures below therefore combine high-confidence local capacity data with
non-local hospitality call benchmarks. They must always be introduced as an
**estimate**.

Summer means June–August 2025, the latest complete summer in the Statistics
Estonia table used here.

### Local capacity and seasonality inputs

Statistics Estonia table TU122 reports the following for Pärnu city:

| Month | Available rooms | Room occupancy |
| --- | ---: | ---: |
| June 2025 | 2,238 | 58% |
| July 2025 | 2,233 | 73% |
| August 2025 | 2,247 | 61% |

Direct table: [Statistics Estonia TU122](https://andmed.stat.ee/en/stat/majandus__turism-ja-majutus__majutus/TU122).
The [Pärnu city tourism dashboard](https://turismistatistika.ee/en/county/parnu-city/)
is a readable presentation of TU122/TU131 and reports 405,687 accommodated
guests and 752,800 nights in Pärnu city for all of 2025. A May 2026 Pärnu
tourism-market snapshot reports the same totals, 4,506 average bed places,
1.86 nights average stay, and 45.8% annual bed-place occupancy:
[source PDF](https://www.spaestonia.ee/medical/wp-content/uploads/2026/05/Annex-1.1_Parnu-Tourism-Market_EN.pdf).

### Call-volume benchmark

Revinate's [2026 North America hotel voice benchmark](https://www.revinate.com/hospitality-report/voice-channel-north-america/)
reports these calls per room per month:

| Month | All inbound calls | Booking-intent/lead calls |
| --- | ---: | ---: |
| June | 16 | 3 |
| July | 16 | 3 |
| August | 14 | 2 |

Applying those rates to Pärnu's actual monthly room counts gives:

- **102,994 total inbound calls** during the three-month summer;
- **17,907 booking-intent calls** during the same period.

This is an uncalibrated transfer from Revinate's North American customer base,
not Pärnu call-log data. It may overstate Pärnu because Revinate customers are
voice-channel users and the Pärnu room count includes smaller accommodation
businesses. Conversely, separate spa lines and calls outside accommodation
properties may be omitted.

### Miss-rate scenarios

Two hospitality vendor datasets put peak unanswered calls as high as 40%:

- [Hospitality Net / Canary Technologies, 14 August 2025](https://www.hospitalitynet.org/opinion/4128546/can-ai-voice-agents-fix-the-flaws-in-hotel-call-centers):
  up to 40% of hotel calls unanswered; one-third of those callers ready to book.
- [Alveni 2026 hotel call analysis](https://alveni.ai/en/missed-calls-hotel/):
  up to 40% at peak times, based on 13,200 calls across 15 German upscale hotels.

Because neither source measures Pärnu, the model uses 20% as a conservative
scenario, 30% as the midpoint, and 40% as the published peak-risk scenario:

| Miss rate | Missed all inbound calls | Missed booking-intent calls |
| --- | ---: | ---: |
| 20% low scenario | 20,599 | 3,581 |
| 30% midpoint | 30,898 | 5,372 |
| 40% peak-risk scenario | 41,198 | 7,163 |

The lead-call column assumes booking-intent calls are missed at the same rate
as the overall call stream. No Pärnu data verifies that assumption. It is more
conservative than applying Canary's statement that one-third of unanswered
hotel calls come from guests ready to book.

The booking-intent range is the more defensible sales number. The much larger
all-call range includes directions, restaurant, in-stay support, event, group,
housekeeping, and other operational calls and has higher transfer uncertainty.

**Safe summary:** a benchmark-transfer model suggests roughly **3,600–7,200
missed booking-intent calls per Pärnu summer**, midpoint **about 5,400**. It does
not prove how many calls Pärnu hotels actually missed.

### Confirmed BOUK cohort model

The ten confirmed current Pärnu-city BOUK properties in this report total 267
rooms in the 2026-09-30 API snapshot. Applying the same summer benchmark:

| Scope | Modelled summer calls | Missed at 20% | Missed at 30% | Missed at 40% |
| --- | ---: | ---: | ---: | ---: |
| All inbound calls | 12,282 | 2,456 | 3,685 | 4,913 |
| Booking-intent calls | 2,136 | 427 | 641 | 854 |

Property-level planning ranges:

| Property | Rooms | Modelled summer inbound | Missed inbound, 20–40% | Modelled lead calls | Missed leads, 20–40% |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pärnu Hotel | 31 | 1,426 | 285–570 | 248 | 50–99 |
| Rannahotell | 64 | 2,944 | 589–1,178 | 512 | 102–205 |
| Frost Boutique Hotel | 14 | 644 | 129–258 | 112 | 22–45 |
| Rosenplänter Boutique Hotel | 13 | 598 | 120–239 | 104 | 21–42 |
| Kurgo Villa Hotel | 28 | 1,288 | 258–515 | 224 | 45–90 |
| Hotel Hansalinn | 11 | 506 | 101–202 | 88 | 18–35 |
| Hommiku Hostel | 22 | 1,012 | 202–405 | 176 | 35–70 |
| Embrace Guestrooms & Apartments | 12 | 552 | 110–221 | 96 | 19–38 |
| Reldor Motel | 44 | 2,024 | 405–810 | 352 | 70–141 |
| Alice Backyard | 28 | 1,288 | 258–515 | 224 | 45–90 |

These rows are prospect-sizing scenarios, not claims about an individual
property's PBX performance.

### Spa scenario — not a city estimate

Visit Pärnu lists [nine Pärnu spas](https://visitparnu.com/en/spa-holidays/).
Zenoti's [2025 salon/spa benchmark article](https://www.zenoti.com/thecheckin/ai-receptionist-vs-call-bot)
states that 35% of calls to salons and spas go unanswered each month. No public
source gives Pärnu spa call volume, so only a sensitivity table is defensible:

| Assumed calls per spa/month | Nine spas: summer calls | Missed at 35% |
| --- | ---: | ---: |
| 100 | 2,700 | 945 |
| 200 | 5,400 | 1,890 |
| 300 | 8,100 | 2,835 |

This is **not** an estimate of actual Pärnu spa calls. Do not add it to the
hotel total: integrated spa hotels may use the same phone line, creating
double counting.

### Confidence and next measurement

- **High confidence:** Pärnu room counts and occupancy from Statistics Estonia.
- **Medium confidence:** the shape and seasonality of Revinate's hospitality
  call benchmark.
- **Low confidence:** transferring North American/German miss rates and call
  behavior directly to Pärnu.

A real pilot should replace the model with seven consecutive days of PBX call
detail records: inbound count, answered, abandoned/missed, after-hours,
concurrent overflow, wait time, and booking intent. Store only masked caller
identifiers and aggregate statistics. Scale the observed daily result to the
summer only after distinguishing normal weekdays, weekends, and events.

## Confirmation standard

A property is **confirmed current** only when all of these hold:

1. The property's official website currently links to a `bouk.io/booking/...`
   URL.
2. `GET https://api.bouk.io/hotels/{id}/load` returns the expected property.
3. The BOUK response reports `active: true` and `isDemo: false`.

Search-engine results and BOUK's customer page are discovery evidence only.
Where the current official property site points elsewhere, that current link
wins over an older indexed BOUK page.

## Confirmed current BOUK properties — Pärnu city

| Property | Type | BOUK ID | Snapshot inventory | Official-site evidence | BOUK evidence |
| --- | --- | ---: | ---: | --- | --- |
| Pärnu Hotel | Hotel | 505 | 31 rooms | [hotelparnu.com](https://www.hotelparnu.com/) links to BOUK | [booking engine](https://bouk.io/booking/parnu/505/rooms) |
| Rannahotell | Hotel | 191 | 64 rooms | [rannahotell.ee](https://rannahotell.ee/) links to BOUK | [booking engine](https://bouk.io/booking/rannahotell/191/rooms) |
| Frost Boutique Hotel | Hotel with sauna/relaxation area | 240 | 14 rooms | [frosthotel.ee](https://frosthotel.ee/) links to BOUK | [booking engine](https://bouk.io/booking/frost/240/rooms) |
| Rosenplänter Boutique Hotel | Hotel | 257 | 13 rooms | [rosenplanter.ee](https://rosenplanter.ee/) links to BOUK | [booking engine](https://bouk.io/booking/rosenplanter/257/rooms) |
| Kurgo Villa Hotel | Hotel | 355 | 28 rooms | [kurgovilla.ee](https://kurgovilla.ee/) links to BOUK | [booking engine](https://bouk.io/booking/kurgovilla/355/rooms) |
| Hotel Hansalinn | Hotel | 488 | 11 rooms | [hansalinn.ee](https://hansalinn.ee/) links to BOUK | [booking engine](https://bouk.io/booking/hansalinn/488/rooms) |
| Hommiku Hostel-Guesthouse | Hostel | 429 | 22 rooms | [hommikuhostel.ee](https://hommikuhostel.ee/) links to BOUK | [booking engine](https://bouk.io/booking/hommikuhostel/429/rooms) |
| Embrace Guestrooms & Apartments | Guestrooms/apartments | 280 | 12 rooms | [embrace.ee](https://embrace.ee/) links to BOUK | [booking engine](https://bouk.io/booking/embrace/280/rooms) |
| Reldor Motel | Motel/hotel | 509 | 44 rooms | [reldor.ee/motell](https://reldor.ee/motell/) links to BOUK | [booking engine](https://bouk.io/booking/reldor/509/rooms) |
| Alice Backyard | Apartments | 439 | 28 units in snapshot | [alicebackyard.ee](https://alicebackyard.ee/) links to BOUK | [booking engine](https://bouk.io/booking/alice-backyard/439/rooms) |

Inventory counts are a point-in-time API snapshot, not contractual property
capacity. They are useful for identifying a real, configured, non-demo account.

### Spa caveat

Frost is listed by Visit Pärnu as having a sauna/relaxation area, but its BOUK
`search/extra-services` response was empty on the research date. This confirms
BOUK for Frost's hotel rooms, **not** for public spa appointment scheduling.
The other confirmed Pärnu-city rows are primarily accommodation evidence.

## Pärnu County and adjacent candidates

| Property | Status | Evidence |
| --- | --- | --- |
| Viisnurga Holiday Home, Uulu | Confirmed current; active non-demo BOUK property and official site links to BOUK | [official site](https://www.viisnurgapuhkemajad.ee/) · [BOUK](https://bouk.io/booking/viisnurga/284/rooms) |
| Reiu Holiday Centre, Paikuse | Official site links to BOUK, but BOUK API reports `isDemo: true`; do not count as a production customer without re-checking | [official site](https://reiupuhkekeskus.ee/) · [BOUK](https://bouk.io/booking/reiupuhkekeskus/924/rooms) |
| Tõhela Lake Holiday Village | Active non-demo BOUK API property, but no current BOUK link was found on the official site; vendor-listed/unconfirmed | [official site](https://www.tohelajarvepk.ee/) · [BOUK](https://bouk.io/booking/tohela/442/rooms) |

## Stale or migrated BOUK evidence — do not cite as current

| Property | Old/indexed BOUK evidence | Current evidence and decision |
| --- | --- | --- |
| Hedon Spa & Hotel | Indexed BOUK property ID 189; API still says active but exposes zero room types | Current official hotel and treatment buttons point to `hotel.hedonspa.com` / `online.hedonspa.com`, both SALBOS-linked WordPress/WooCommerce shops. Treat BOUK as legacy. |
| Viiking Spa Hotel | Indexed BOUK property ID 154 | BOUK load response is empty; current official site points to `hotel.viiking.ee` and `spa.viiking.ee`, both SALBOS-linked. Stale. |
| Wasa Resort | Indexed BOUK property ID 492 | BOUK load response is empty; current official site points to `hotel.wasahotels.ee` and `spa.wasahotels.ee`, both SALBOS-linked. Stale. |

This table explains why search results alone overstate BOUK's Pärnu spa
footprint.

## Local production systems

### SALBOS

SALBOS's official customer list names multiple Pärnu hotel/spa operators,
including ESTONIA Medical Spa & Hotel, Tervis Medical Spa, Tervise Paradiis,
Hedon Spa & Hotel, ESTONIA Resort Hotel & Spa, Wasa Resort, and Viiking Spa
Hotel:

- [SALBOS customer list](https://salbos.com/en/)
- [Hotel module](https://salbos.com/en/hotel/)
- [Spa module](https://salbos.com/en/spa/)
- [Tervise Paradiis: transition to SALBOS](https://terviseparadiis.ee/en/transition-to-the-salbos-software/)

Checked SALBOS-linked shops expose standard WooCommerce REST namespaces
(`wc/v1`, `wc/v2`, `wc/v3`, `wc/store/v1`). Public product reads work, for
example:

- `https://spa.terviseparadiis.ee/wp-json/wc/store/v1/products`
- `https://spa.viiking.ee/wp-json/wc/store/v1/products`

That proves a standard catalogue/API layer, not authorization to create real
bookings. Room availability and booking writes may use private SALBOS logic.
Production work requires property/vendor credentials and documentation.

### D-EDGE

[Hestia Hotel Strand's official site](https://www.hestiahotels.com/strand/en/)
currently points its booking buttons to D-EDGE's
`secure-hotel-booking.com` engine (checked 2026-09-30). D-EDGE's official
[developer portal](https://docs.d-edge.com/overview/get-started/explore-our-apis)
provides a credential-free mock Booking Engine API; production access requires
a signed partnership.

## QloApps and Easy!Appointments deployment check

Re-checked **2026-10-01**. The question was whether either open-source product
has a demonstrable current user among Pärnu hotels or spas, not merely whether
the software can be used in hospitality.

### Method and confirmation threshold

The check combined:

1. Exact product-name searches in English and Estonian for `QloApps`,
   `Powered by QloApps`, `Easy!Appointments`, and `easyappointments` together
   with Pärnu/Parnu, Estonia/Eesti, hotel/hotell, and spa/spaa.
2. Technical-fingerprint searches for common QloApps and Easy!Appointments
   routes and identifiers.
3. Live inspection of the official property and booking pages for the ten
   confirmed Pärnu-city BOUK properties above and Visit Pärnu's nine named spa
   hotels.

A property would be confirmed only if its current official site linked to a
live deployment or the live booking page exposed an unambiguous product
attribution or technical fingerprint. Search-result text alone was not enough.

### Result

| Product | Confirmed current Pärnu hotel/spa users | Evidence-based decision |
| --- | ---: | --- |
| QloApps | **0 found** | No official property link, live booking page, exact-name result, or technical fingerprint identified a Pärnu deployment. Do not claim local adoption. |
| Easy!Appointments | **0 found** | No official property link, live appointment page, exact-name result, or technical fingerprint identified a Pärnu deployment. Do not claim local adoption. |

This is a bounded negative finding, not proof that an unindexed private install
cannot exist. Easy!Appointments is self-hosted and customizable, so branding
can be removed; a deployment used only by staff could also be invisible from
the public web.

### What the checked properties use instead

- The ten current accommodation properties in the BOUK cohort above link to
  **BOUK** from their official sites.
- Hedon's [hotel](https://hotel.hedonspa.com/et/) and
  [spa](https://online.hedonspa.com/et/) booking pages explicitly credit
  **SALBOS**.
- ESTONIA [Resort](https://resort.spaestonia.ee/et/) and
  [Medical](https://medical.spaestonia.ee/et/) hotel-booking pages explicitly
  credit **SALBOS**.
- Wasa's [hotel](https://hotel.wasahotels.ee/et/) and
  [spa](https://spa.wasahotels.ee/et/) booking pages explicitly credit
  **SALBOS**.
- Tervise Paradiis's [hotel](https://hotel.terviseparadiis.ee/et/) and
  [spa](https://spa.terviseparadiis.ee/) booking pages expose SALBOS identifiers
  and explicitly credit **SALBOS**.
- Tervis Medical Spa's [hotel](https://hotel.spatervis.ee/en/) and
  [treatment](https://spa.spatervis.ee/en/) booking pages explicitly credit
  **SALBOS**.
- Viiking's [hotel](https://hotel.viiking.ee/et/) and
  [spa](https://spa.viiking.ee/et/) booking pages explicitly credit
  **SALBOS**.
- Hestia Hotel Strand's official booking buttons link to D-EDGE's
  [`secure-hotel-booking.com`](https://www.secure-hotel-booking.com/Hestia-Hotel-Strand/JLY6/en-GB)
  engine.

The practical implication is that QloApps and Easy!Appointments are useful for
a free, writable hackathon environment, but neither gives the demo a verified
local-customer story. Use the provider-neutral adapters for the demo and retain
BOUK/SALBOS as the relevant Pärnu production connector targets.

## BOUK demo and API-cost implications

Official BOUK sources:

- [Features](https://bouk.io/product/features): one system for room or service
  inventory sold daily, hourly, or monthly; unified calendar; multi-service
  booking; property and spa positioning.
- [Pricing](https://bouk.io/pricing): “Try it free,” full access without a
  credit card, and cancel anytime. Public minimums are €25/month for Essential,
  €75/month for Standard, and €250/month for Professional; API access/support
  is listed only in Professional.
- [Customers](https://bouk.io/customers): broad Estonian adoption.
- [Terms](https://bouk.io/page/terms): service is operated by OpenHotels OÜ
  under Estonian law.

No current official page checked states a 14-day duration, and the public
website does not establish that API credentials are included in a free
self-service signup. Anonymous requests to the usual API documentation paths
(`api.bouk.io/docs`, `/swagger`, `/swagger/index.html`, and `/openapi.json`)
return HTTP 401. Request a free supported sandbox and API documentation from ED
Hotels before writing the BOUK adapter. Do not purchase Professional only for
the hackathon, and do not build against undocumented browser endpoints.

## Recommended claims

Safe:

> BOUK is used by multiple Pärnu hotels, including Pärnu Hotel, Rannahotell,
> Frost Boutique Hotel, Rosenplänter, Kurgo Villa, Hansalinn, Hommiku Hostel,
> Embrace, Reldor Motel, and Alice Backyard. BOUK supports both room and hourly
> service inventory in one platform. Major Pärnu spa hotels commonly use
> SALBOS, which is the next production connector target.

> No public source measures Pärnu hotel missed calls. A benchmark-transfer
> model using Statistics Estonia room capacity and hospitality voice benchmarks
> estimates 3,600–7,200 missed booking-intent calls during June–August, with a
> midpoint near 5,400. A pilot PBX export is required to replace this estimate
> with local observed data.

Unsafe — do not claim:

- “Pärnu's major spa hotels currently use BOUK.”
- “Hedon, Viiking, or Wasa currently use BOUK.”
- “SALBOS booking writes are available through its public WooCommerce API.”
- “Estonian hotels use QloApps.”
- “Pärnu hotels or spas use Easy!Appointments.”
- “BOUK currently promises a 14-day self-service API trial.”
- “Pärnu hotels miss 5,372 booking calls every summer.” The number is a model
  midpoint, not a measured fact.

## Re-verification checklist

Before using this evidence in a future pitch:

1. Re-open each official property site and confirm its booking link.
2. Re-check BOUK `active` / `isDemo` state.
3. Treat a current official-site link as stronger than search-index history.
4. Confirm official write API credentials and scope before promising booking,
   change, or cancellation support.
