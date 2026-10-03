# Estonian speech reliability — measured evidence, 2026-10-03

## Scope and integrity

Repair repeated website speech and independently reproduced native silence,
without weakening confirmation/ownership or changing the inbound telephone
route. No outbound calls, purchases or real-customer writes. HTTP/browser and
private RTC proofs are not successful PSTN calls.

The run began at `2026-10-02T20:17:52.534Z`. Work, research and spaced read-only
checks span the following morning. This is not a claim of eight continuous
hours of CPU execution or uninterrupted human-equivalent labor. A server
restart erased temporary artifacts and cancelled a watcher after six samples
(`20:31:14Z–21:46:14Z`, 4499.951 seconds); those samples were successful, not an
eight-hour soak. Durable evidence now lives outside `/tmp`.

Concurrent upstream delivery `976d4b4` (documentation `13c624a`) added spa/room
features and changed model defaults. This repair integrates above it; it does
not revert those features or make another speculative production model swap.
Later upstream through `92dcb01` includes call history, browser-filtered
resampling, recognition/failure diagnostics, static greeting/FAQ replies,
trusted HTTP booking terminals and sign-in/session-start voice controls. These
remain intact. Web and native rollout must be recorded separately: before this run's
native rollout, the old deployed worker still used GPT-OSS20B/512 and the older
STT default, while the newer shared source defaults are full Whisper,
GPT-OSS120B/2048. Retaining that source is not evidence of a native deployment.

## Research round 1 — discovery and deployed boundaries

Native ten-angle run `7f9fdca6-df88-4838-bea0-1d17558df973`, 2026-10-02:
39 ranked URLs, 12 extracted pages, four failures. Follow-up distinguished
file-upload ASR, VAD/batch segmentation, tool generation, guarded speech and
carrier transport. An actual incoming call's carrier completion does not prove
that a caller heard successful repeated speech or a booking recap.

First-party references retrieved 2026-10-02:

- [Groq models](https://console.groq.com/docs/models) and
  [speech-to-text](https://console.groq.com/docs/speech-to-text): model IDs,
  file-upload API and optional language setting; advertised throughput and
  multilingual WER are not local Estonian phone results.
- [OpenAI Whisper](https://github.com/openai/whisper): relative speed numbers
  are hardware/language-specific, not an Estonian caller benchmark.
- [TalTech fine-tuned turbo](https://huggingface.co/TalTechNLP/whisper-large-v3-turbo-et-verbatim-2604):
  manually labelled and pseudo-labelled training data; CT2/GGML layouts.

## Research round 2 — bounded ASR measurement

Native discovery run `a5f2c346-888b-479b-a1fa-abaf93a1b9b4`, 2026-10-02:
45 ranked URLs, ten extracted pages, four failures. Measurements used public
CC-BY-4.0 `google/fleurs` Estonian **test** read speech, not caller recordings.

- Dataset revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`; archive SHA256
  `cdece29c50357790dc87f034242d54066fcacbc694cd057e75a29f2f56c14cbf`.
- Select before inference by SHA256(`voicebot-20261003|filename`): 16 unique
  utterance IDs, 4–12 seconds each, 155.46 seconds in total. All 893 pinned TSV
  rows were labelled FEMALE; no balanced subset was available.
- Same clean inputs versus 300–3400 Hz filtering and an 8 kHz mu-law roundtrip.
  This simulates a bandwidth/codec constraint, not a real telephone network.
- NFC/casefold, punctuation replaced by spaces, whitespace normalized, digits
  retained; corpus-weighted word/character error rates. Unknown training overlap,
  small sample, read speech, gender labels and normalization limit inference.

| ASR | WER clean / simulated PSTN | CER clean / simulated PSTN | Median request/inference seconds clean / simulated PSTN |
| --- | --- | --- | --- |
| Groq Whisper turbo | 18.01% / 20.38% | 2.11% / 2.43% | 0.502 / 0.486 |
| Groq Whisper full v3 | 20.85% / 20.85% | 3.20% / 2.95% | 0.690 / 0.705 |
| Classic Azure short-audio `et-EE` | 17.06% / 15.64% | 5.06% / 5.12% | 2.186 / 2.063 |
| TalTech turbo et-2604, CT2 CPU int8, two threads | 9.00% / 9.48% | 3.84% / 4.10% | 12.228 / 12.053 |

Groq/Azure summaries above survive the prior recorded command output; their
temporary per-clip results were lost in the restart. Do not present them as
re-auditable raw experiments. TalTech was rerun successfully at
`2026-10-03T07:10:40Z` against the restored checksum-verified inputs; durable
manifest, per-clip JSONL and summary are under
`/home/arle/.local/share/voicebot-reliability/asr/`. Model revision
`310c550922fc1d1bebf3fad41f9b33ede6652bdc`, weights SHA256
`e3ebce23a10322e1401e4cafd4e6675811988c0890aff1885469b357a27388da`.
Cold load was 2.799 seconds; median real-time factor 1.19 / 1.20. The earlier
PyAV 19/faster-whisper file-decoder incompatibility was bypassed with validated
16 kHz mono PCM arrays in an isolated research environment, not production.

These results do not establish full Whisper as the better Estonian default,
nor local TalTech CPU inference as a low-latency production replacement.
Classic Azure measurements are **not** MAI or streaming measurements.

### Fictional tool-selection inference, 2026-10-03T07:25:31Z

Nine fixed single-decision cases per available configuration: missing dates/
times, exact slot, delivered/undelivered consent, contradictory consent, unknown
write and owned cancellation. No returned tool was executed. This used the
earlier spa-only HTTP state/prompt, not the new stay-inclusive prompt or native
full dialogue; it must not be represented as a benchmark of the current app.

| Groq configuration | Correct selection | Final mutation selected without authorization | Empty / length finishes | Median seconds |
| --- | --- | --- | --- | --- |
| GPT-OSS20B, 512 cap | 7/9 | 0 | 0 / 0 | 0.341 |
| GPT-OSS20B, 1024 cap | 7/9 | 0 | 0 / 0 | 0.338 |
| GPT-OSS120B, 1024 cap | 8/9 | 0 | 0 / 0 | 0.338 |
| Qwen3.8-27B, 1024 cap | Unavailable | Not measured | Not measured | HTTP 429 |

The smaller model tried planning again after undelivered consent and unknown
outcome; 120B also re-planned an undelivered recap. Execution guards, not model
selection scores, must remain authoritative. These simple short prompts did
**not** reproduce length exhaustion; installed-SDK SSE regression fixtures
independently reproduce that mechanism. No general accuracy or reliability
claim follows from nine probes. Qwen was not repeatedly hammered after 429.
Durable fictional per-case records/summary:
`/home/arle/.local/share/voicebot-reliability/tool-models.jsonl` and
`tool-models-summary.json` in the same directory.

## Installed SDK and review counter-evidence

Context7 primary LiveKit source documentation was queried 2026-10-03 for
custom TTS nodes, speech handles and conversation events; exact runtime
decisions use the installed pinned **LiveKit Agents 1.8.4** source and tests,
not assumptions about its latest branch.

An independent review disproved the initial speech-identity event lookup:
`say()` attaches its assistant item before the session event, whereas generated
replies emit the event **before** attaching the item. The new real
`AgentSession.generate_reply` regression failed on delivery while its `say()`
control passed. A callback on the originating speech handle, with exact
preparation identity, removes that event-order dependency; both now deliver
only after completed PCM and require a new consenting turn for one write.

The same review reproduced delayed microphone permission capturing a later
assistant reply. Serializing every conversational input during permission/
encoding and pausing again at capture start fixes the demonstrated race.
Neither corrected mechanism proves physical microphones or carrier dialogue.

## Integrated verification and rollout

The integrated snapshot before the English merge passed **912 media tests /
4 skipped / 36 subtests** and **745 core tests / 39 skipped / 36 subtests** in clean `env -i` Linux
environments. Skips are dependency/platform gates, not expected failures;
`audioop` and TestClient dependency deprecations remain visible. Five Chromium
suites cover dashboard/history, hotel, spa/stay booking, eight voice turns and
microphone races, with no JavaScript errors and layouts from 320 to 1440 px.

Review round 2 confirmed the earlier native and permission/send repairs, then
found a P2 failed-end/late-grant privacy race. A new real-browser regression
failed on that exact capture revival. Capture-epoch cancellation now passes,
including **genuinely advancing PCM playback** paused at the actual permission
grant. No third whole-diff review was requested for a P2; the bounded fix was
self-reviewed and the full merged checks rerun.

Real Groq/Azure microphone-graph proof at **2026-10-03T08:29:26Z** completed six
turns with recognized text, spoken nonempty replies and completed playback,
zero JavaScript errors. One turn was a safe provider fallback, not a successful
model inference. Median capture + endpointing + response: **4.0755 s**;
controller/provider processing: **1.3037 s**; ASR: **0.4961 s**. Playback time
is recorded separately. Durable artifact: `live-http-speech-summary.json` in
the external reliability directory. These are synthetic inputs, not physical
microphone measurements.

The earlier additional one-shot booking proof failed to prepare a recap; a
later multi-turn run confirmed but hit Groq429 before cancellation. Neither
failed run is relabeled as passed. After preserving upstream's trusted terminal
replies, the fresh isolated real-provider booking proof at
**2026-10-03T08:52:52Z** passes recap playback → new consent → exactly one
fictional confirmation → independent readback → owned cancellation. Confirmation
and cancellation used **zero model requests**, with controller totals
**419.3/340.0 ms**, including TTS. Backend data was completely isolated; no
real-customer writes occurred. Those booking/consent turns used typed browser
input, not physical or synthesized microphone consent; they are separate from
the six microphone dialogue turns. Durable artifact: `live-http-booking-summary.json`.

Before delivery, upstream additionally merged guarded English telephone work
(`f541da6`). It is preserved rather than reverted: language-aware recognition,
voice selection, consent and cached English/bilingual PCM coexist with the
generation-owned history and speech-handle delivery repair. A real SSE
disconfirming test failed when the original Estonian-only empty-stream seed
was used for an English call; the language-aware guarded seed passes. Real
generated/say recap completion and cached apology PCM/history now cover both
languages. The suites for this `0088edf` application snapshot supersede the earlier counts:
**1026 media tests / 4 skipped / 36 subtests**, **822 core tests / 43 skipped /
36 subtests**. This is compatibility verification, not an independent English
ASR benchmark or physical English telephone acceptance claim.

The narrow multilingual merge review found one P2: English recaps labelled
UTC slot starts as Tallinn time, including the wrong day across midnight.
Public search → hold → prepare → guard regressions reproduced both errors
before the repair. Timestamp conversion is now shared before the language
branch; the backend metadata is unchanged. All six Estonian/English date cases
pass. Prior HIGH/MEDIUM review findings remain closed; the remaining P2
correction was self-reviewed and followed by the full suites above.

### Deployed website and native boundaries

Application commits `86a4dd3` and merge `0088edf` were pushed to both the repair
branch and `master`. At the rollout check, public web commit `0088edf` was healthy; six changed source
files match the integration checkout. The served dashboard JavaScript has the
same SHA256 and cache version `1796afa1f928`. Only the idle native worker was
replaced, after confirming zero live rooms. Its five checked source hashes
match; image `5f812c12` is healthy with zero restarts and `pip check` passes.
The bridge and unrelated media services were not restarted.

The **deployed public website** completed six fresh read-only browser
microphone-graph turns at **2026-10-03T09:29:51Z**. All had nonempty recognized
input, reply PCM, advancing/completed playback, no booking changes and no
JavaScript errors. Outcomes: five `ok`, one `tools_ok`, no provider fallback.
Median capture + endpointing + HTTP response: **5.100 s**; controller/provider
processing: **1.6469 s**; ASR: **0.5151 s**. These small observations are not a
physical-microphone benchmark, a latency guarantee or a causal comparison with
the earlier local run. Durable proof: `live-http-public-speech-summary.json`.

Fresh deployed native **read-only RTC** dialogue at **2026-10-03T09:37:45Z**
completed three Estonian and three English post-input spoken replies, rather
than mistakenly counting the bilingual greeting as a reply. **Three of six
were generic unverified-result replies**, despite no generic provider outage
apology. This verifies continued audio delivery, not adequate conversation
quality. Durable proof: `native-readonly-dialogue-summary.json`.

The stricter real-provider native booking probes **failed in both languages
before a canonical recap**, with no confirmation/cancellation utterance or
booking write. English recognition contained the supplied date/time, followed
by the guarded unverified reply; that narrows the observed failure beyond
total microphone silence, but does not prove a particular model/tool root
cause. Do not label native booking/cancellation or PSTN acceptance successful.
After two failures the mutation acceptance probe was not retried blindly.

An isolated invalid-Azure-credential worker nevertheless delivered cached
Estonian apology PCM over RTC: **224640 received bytes**, independent ASR
similarity **0.932**, all three expected apology words observed. The normal
worker was not stopped. A signed synthetic HTTPS/WSS bridge assertion run
also exited 0 through 8 kHz mu-law media/native playback markers; its caller
wrapper did not print the returned label, so no frame count is claimed. This
is a protocol probe, not a real carrier call.

Preservation comparison at **2026-10-03T09:31:30Z** verifies all pre-rollout
configuration fields unchanged, no removed fields, identical original shared
volume, SQLite integrity and all baseline row hashes retained: journal **29**,
calls **88**, plus all six stay tables. Calls increased only in count; existing
baseline rows remain. Concurrent upstream added public phone display and the
worker's explicit shared model/language/stay settings. The new worker uses
shared-source **GPT-OSS120B/2048/full Whisper**, replacing the older image's
compiled defaults; this is upstream alignment, not an independently proven
model superiority claim. Credentials and incoming carrier configuration were
not changed. The aggregate environment hashes therefore differ legitimately;
do not call them byte-for-byte identical. Proofs: `before-final-deploy.json`,
`after-final-deploy.json`, `final-deployment-preservation-proof.json`.

The deployed browser's genuine **ten-minute session expiry** check passes at
**2026-10-03T09:53:37Z**: **602.164 seconds** of real lifetime, expired turn
HTTP **410**, microphone/audio closed, new voice-session control available,
logout clean and zero JavaScript errors. No mocked time/state or booking was
used. Final close-out at **09:56:51Z** has **49139.073 elapsed seconds** since
server-stamped creation, timestamped substantive work and distributed checks;
this is explicitly **not** an eight-hour continuous labor/soak assertion.
Health, incoming signed route and SQLite integrity remain true; journal **29**,
calls **96**, all baseline main rows retained. No owned failure clone or RTC
room remains. Proofs: `live-public-session-expiry.json`, `final-closeout-proof.json`.

### Concurrent releases preserved during evidence delivery

Before the documentation push, `master` advanced through `42c421a`, including
natural conversation, guarded Russian speech and higher-fidelity browser
audio, then `8d2a733` (direct spa-hours inquiries). The atomic documentation
push was rejected safely; no force push or rollback was attempted. Normal
merges retain those published changes. Relative to `8d2a733`, this close-out
adds only this evidence document and `tests/test_call_history.py`.

Two legacy history-fixture failures expected `language="et"` for requests
that omit language; the newer public contract intentionally defaults to
automatic recognition. The test now checks omitted/automatic and explicit
Estonian input separately, while requiring Estonian reply/history and private
metadata in both cases. No production language behavior was changed to make
the test pass. The scoped history check passes **27 tests**. On the preceding
`42c421a` integration, full suites pass **1195 media / 4 skipped / 36 subtests**
and **970 core / 49 skipped / 36 subtests**; all five browser suites also pass.
The final `8d2a733` integration then passes **1249 media / 4 skipped /
36 subtests** and **1024 core / 49 skipped / 36 subtests** in the same clean
environments. These overlapping suites are not added together as unique tests.

A fresh bounded public-origin check at **10:15:06Z** completed two microphone
turns with real providers, nonempty PCM, completed playback and zero JavaScript
errors. It is separate from the earlier six-turn measurements. At **10:20:08Z**
the served web commit is `8d2a733`; its six checked source hashes and served
dashboard asset `eeaac7942487` match that commit. The native worker still
matches `0088edf`, not the newer upstream native features. All three services,
public health and incoming route are healthy; existing configuration-field
hashes, shared volume and baseline main-row hashes are retained. Journal/call
counts are now **31/112**; extra rows do not establish their writer or convert
the earlier no-mutation public probes into booking acceptance. Durable proofs:
`live-http-public-latest-check-speech-summary.json`,
`latest-integration-preservation-proof.json`. Earlier native booking failures
and six-turn/expiry measurements remain dated to their tested source, not
silently promoted to acceptance for the newer release.

## Research round 3 — opposing evidence and privacy

Retrieved/corroborated 2026-10-03 through primary-source page fetching and
Microsoft Learn. A native research attempt aborted (`SIGABRT`, double-free);
bounded direct routes continued. SearXNG's exact queries returned no relevant
results or unrelated dictionary pages; those were excluded, not cited.

- [TalTech Voxtral card](https://huggingface.co/TalTechNLP/Voxtral-Mini-4B-Realtime-estonian-2609):
  genuine streaming architecture, mono 16 kHz input and Apache-2.0. Its **6.8%
  WER is self-reported internal validation**, not this corpus or a PSTN result.
  The card warns of noisy/far-field speech, dialects, names/numbers,
  hallucinations and broadcast/pseudo-label training bias. No local Voxtral
  inference was measured; do not infer feasibility from model availability.
- [Microsoft MAI streaming SDK](https://learn.microsoft.com/azure/ai-services/speech-service/mai-transcribe-2-streaming-speech-sdk):
  Estonian is listed, requires SDK 1.52.0; **public preview, no SLA, not
  recommended for production**. The page names Sweden Central/Central US as
  available and East US 2 as coming soon. Documentation/account-region
  availability must be verified before a deployment; no MAI inference here.
- [Groq data policy](https://console.groq.com/docs/your-data): inference is not
  retained by default, but reliability/abuse logs may retain inputs/outputs up
  to 30 days unless ZDR is enabled; retained customer data is in the US. ZDR is
  configurable. This run did not inspect or change the account's data controls.
- [Azure speech privacy](https://learn.microsoft.com/azure/foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security):
  real-time speech is processed in server memory without storage at rest;
  batch retention differs. Provider statements do not replace consent/legal
  assessment or establish current account configuration.

Recommendation: fix capture/playback and empty-generation recovery first;
retain execution-owned booking truth and strict consent. Evaluate future ASR
changes on opt-in spontaneous Estonian dates, negations and names, physical
microphones and actual inbound calls with concurrency and adverse audio. Do
not trade guarded writes or privacy for a small read-speech benchmark gain.
