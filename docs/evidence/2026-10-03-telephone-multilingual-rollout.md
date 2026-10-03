# Native telephone multilingual rollout — 2026-10-03

Status: automatic ET/EN/RU telephone-worker dialogue acceptance verified on synchronized release `251500f`; full fixture suite passes. Legacy FAQ semantic coverage and real PSTN acceptance are not claimed.

## Initial release and scope

- Clean published source: `b1940070d94b88fed6c4a0c8d6e216e0ce5ba041`.
- Built image: `voicebot-telephone:b1940070d94b`, ID `sha256:c620a3de5cd33616f8ed27990d12187c952f9fcd7c85f42dbb5ce7599fa46757`.
- Existing native worker: `livekit-worker-1`; only this conversation process is in scope.
- LiveKit, SIP, Redis, the web/API application and the signed Twilio bridge remain separate services. Bridge protocol compatibility was checked; no bridge rebuild is needed for Russian language selection.
- The canonical checkout contains concurrent unpublished work. The release was built from a clean worktree, not those changes.

The new source supports `et`, `en` and `ru`, with automatic selection. Defaults are Estonian Anu, English Jenny and Russian Svetlana. The existing automatic mode and Estonian/English settings are retained.

## Preflight evidence

- The running worker's three-language assertion failed as expected: its language tuple was only `et,en`.
- Private worker status reported zero active jobs and load zero. The private LiveKit API returned zero rooms/participants. Activity was rechecked immediately before replacement.
- Existing shared `/data` volume: `f2349b476eddc16df2bad6d3ed0b5e46d20a77390fdfb78f7d8cd20e924e26db`. Read-only SQLite quick checks passed for `easy-booking.db`, `stay-booking.db` and `calls.db`.
- Media image build exited 0. Nine selected application-file SHA-256 digests match the clean source. `pip check` reports no broken requirements.
- An isolated image check passed ET/EN/RU defaults, automatic mode and invalid-language rejection.
- Quiet Compose validation and a worker-only dry run exited 0. No supporting service or carrier bridge appeared in the planned actions.
- Source/image hygiene checks found no protected runtime values in app/demo files or image environment metadata. Protected configuration was handled in memory, never rendered as expanded Compose output.

## Rollback prepared

Before the initial rollout, the old running image was no longer inspectable in the image store, so the mutable `voicebot-telephone:local` tag was not a safe rollback reference.

Published commit `0088edf5bd8377dfe8e84eeb29a073673ae5a759` matched all 54 tracked app/demo files inside the then-running worker byte-for-byte. A clean rollback image was rebuilt from that commit:

- Tag: `voicebot-telephone:rollback-0088edf5`.
- Image ID: `sha256:68204d55485c861f3f61a40a43a20ec53ce66370cef8b0212c4fb9fdabcd37f4`.
- All 55 app/demo/dependency-lock digests match the rollback source; protected runtime environment values are not baked into the image.

## Applied scoped operation

Reused `deploy/telephony/manage.py`'s trusted in-memory environment reader with the existing worker as its source. Supplied an in-memory Compose override containing only the immutable release image, revision label and `SOURCE_COMMIT`; validated with `config -q`, then executed:

```text
docker compose -p livekit -f deploy/telephony/compose.yaml -f - \
  up -d --no-deps --no-build --pull never --wait --wait-timeout 120 worker
```

The operation ran at **11:08:32–11:08:39 UTC**, returned 0 and became healthy with zero restarts. Immediate pre-replacement active job count was zero. The broad `manage.py up` command was not used.

- New worker ID: `0af5621a28fd6334544c0beacdd98b6b11df2b50181a03c4b1750fc35ed1d847`.
- Actual image and `SOURCE_COMMIT` match the tested release; all nine selected running source-file digests match.
- Existing `/data` volume and 16 runtime connection/settings values were preserved, verified by in-memory comparisons without printing values.
- LiveKit, SIP, Redis and bridge container IDs stayed unchanged and running. The bridge remained healthy.
- All three existing SQLite quick checks passed after replacement. The public web `/health` still returned `{"ok":true}`.
- Rollback was not used; its verified image tag remains available.

The initial `b194007` worker had a 30-second application drain and a 120-second Docker stop grace; a race with a new arriving call cannot be eliminated by a preflight idle check alone. The later synchronized release uses the published 900-second application drain and 1,000-second Docker grace instead.

## Concurrent release and recovery

An independent `abd5f38` release later replaced both the web application and telephone containers. That replacement worker restarted repeatedly with `ModuleNotFoundError` for `app.booking.easyappointments`. Image inspection established the cause: application subdirectories were owned by root with mode `0700`, while the image runs as `voicebot`.

The release controller extracts a Git archive using the safe `data` filter under systemd `UMask=0077`; directory permissions inherit that restrictive mask and are copied into the image. A narrow regression reproduced the unreadable application directories before the fix. The controller now sets public source directory permissions to `0755` after safe extraction, while retaining the outer private state directory at `0700`. No credential, application behavior, dependency or carrier-route change is involved.

At **12:05:09 UTC**, under the shared release lock and with zero private rooms, the operator restored the previously verified multilingual image to the failed worker. The recovery preserved all 30 current application/connection settings, the exact shared `/data` volume and every supporting-container ID present immediately before recovery. It did not overwrite the independently updated healthy bridge or web application.

- Recovered worker ID: `a9820cae83e25f6f8c58f2c7ec69804436176267d9e2023c1faf0be8ff3b8762`.
- Image/source during recovery were the tested `b194007` multilingual release.
- The synchronization timer was already inactive after the independent failure; recovery did not enable it or initiate another broad rollout.

The concurrent release owner subsequently published the canonical packaging fix as `479f76e` and the reviewed FAQ behavior as `251500f`. The locally tested duplicate packaging patch/regression were removed rather than overwrite or duplicate that work. This task's final repository change is deployment evidence plus one explicit-scope native test fixture. The installed controller contains the canonical implementation, not the temporary three-line local candidate reviewed during recovery; its bytes match the published `251500f` controller (SHA-256 `d6c7f8188eedf05deb24b4ea395e49714ddd2ab1b68a05ac5abaa7cc2393680f`).

At **12:22:15 UTC**, the automatically synchronized worker and healthy bridge both used image `sha256:74e10be71cb675819d46a1c998caf7db44b32661598264747450a7ad1599ea20`, tagged `voicebot-telephone:251500f587595715948f9597c0d67a6644e98fd4`. All **61** tracked app/demo source-file digests matched that published release. Worker ID `49a6c5a39ef52bee2871903095998f0120a86fa2a564e49dba6203c1b0fbfa58` was healthy with zero restarts, `auto` mode and Anu/Jenny/Svetlana voices. The shared volume remained the original one. The newer synchronization timer had been activated by its owner; this task did not modify it.

## Acceptance boundaries

The full fixture suite at the initial `b194007` snapshot returned 0: **1,249 passed, 36 subtests passed, 4 skipped**, no failures/xfails. The skips are the installed private-backend opt-ins at `tests/test_easyappointments_installed.py:43,123,242,367`; the two warnings are upstream `audioop` and Starlette/httpx deprecations. All 79 applicable pinned media dependencies matched, and provider/worker imports passed.

The suite used `/home/arle/.local/share/voicebot-reliability/media-venv/bin/python` (Python 3.12.3), a freshly constructed isolated environment with no inherited provider values, `EASY_LIVE_TESTS=0`, and:

```text
python -m pytest -q -ra -p no:cacheprovider \
  --basetemp=/tmp/opencode/telephone-multilingual-fixture-fgn44kc2/pytest
```

The initially prepared private audio probe passed 18 provider-free success/failure checks before live execution. Private SDK/room audio is not a real PSTN call or a physical microphone test. No carrier account, number, public SIP exposure or real-property booking release is part of this update.

The first live attempt failed at the ET case with `PCM_LIMIT` before EN/RU ran. No multilingual speech acceptance is claimed from that attempt; diagnostics were improved to expose the underlying pending acceptance stage without printing speech content.

Improved diagnostics established that continuous silence masked a pending reply mismatch. The probe was corrected to retain bounded voiced output and trailing silence, and its provider-free success/failure checks increased to 33. Additional provider-free checks verified caller voice/locale pairs and case setup.

The subsequent short, single-sentence FAQ test on `b194007` passed Estonian recognition, the exact approved answer and independent recognition of spoken answer PCM. Its English case recognized the question and produced audible English, but the content guard returned `ENGLISH_UNVERIFIED` instead of the exact FAQ answer. This historical semantic failure is not counted as a successful FAQ conversation; the newer published FAQ release was checked separately below.

The ET identity trial on `b194007` passed fresh caller STT, the exact approved reply and new voiced PCM, but failed independent-ASR word coverage (`SPOKEN_FAQ_MISMATCH`). EN/RU identity were not reached; no identity speech acceptance is claimed.

The supported deterministic **`dialogue` / `how_are_you`** case subsequently passed all three languages on the recovered image, without relaxing any acceptance threshold. Each isolated room completed both initial greeting segments before input, received exactly one fresh final caller STT and one fresh approved final reply, captured new voiced PCM after caller recognition, and independently recognized that reply in the expected language with at least 0.6 expected-word coverage. Legacy metric names containing `faq` in the temporary probe refer to its supplied expected reply; this case was a dialogue, not the FAQ case.

| Language | Caller STT receipt | Post-STT voiced PCM | Reply capture | Independent reply language |
| --- | ---: | ---: | ---: | --- |
| Estonian | 2,123 ms | 1,840 ms | 3,000 ms | `et` |
| English | 1,979 ms | 2,070 ms | 3,300 ms | `en` |
| Russian | 2,481 ms | 1,920 ms | 3,320 ms | `ru` |

No booking actions were requested; no audio or transcripts were saved. The additional FAQ probe on `251500f` was protected by the shared release lock and retained the same strict acceptance criteria. Private RTC is still not PSTN, within-call language switching or booking-flow acceptance.

That additional legacy FAQ smoke on `251500f` failed its exact-reply assertion in the ET case (`FAQ_REPLY_MISMATCH`, `OTHER_REPLY`); EN/RU were not reached. This negative result is retained, not treated as successful FAQ coverage. Final synchronized-release language acceptance uses the supported short dialogue case, not a claim that every FAQ utterance succeeds.

After the packaging regression fix, the complete fixture suite at `abd5f38` plus the narrow fix returned 0: **1,406 passed, 36 subtests passed, 4 private-backend opt-in skips**, with the same two upstream warnings. The release-controller subset returned 0 with **79 passed**. No provider values were inherited by either suite.

The first full suite at `251500f` returned 1: **2,618 passed**, one failure at `tests/test_native_booking_terminals.py::test_native_speech_normalizes_hours_after_guard_without_replacing_history`. Its generic “what are the hours?” fixture now enters the published FAQ clarification policy. A provider-free comparison confirmed that explicitly asking for **spa** hours restores the intended verified catalogue reply. The fixture was narrowed to spa hours without changing any normalization, canonical-history, PCM or no-pending-booking assertions; no production policy was changed.

The final full suite with that one-line fixture update returned 0: **2,619 passed, 36 subtests passed, 4 opt-in skips**, two unchanged upstream warnings, in 46.23 seconds:

```text
env -i PATH=/usr/bin:/bin HOME=/tmp/opencode LANG=C.UTF-8 \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 EASY_LIVE_TESTS=0 \
  /home/arle/.local/share/voicebot-reliability/media-venv/bin/python \
  -m pytest -q -ra -p no:cacheprovider \
  --basetemp=/tmp/opencode/telephone-multilingual-publish-pytest
```

## Final synchronized-release speech acceptance

Executed against the healthy `251500f` worker while holding the shared release lock:

```text
flock --nonblock /home/arle/.local/share/voicebot-release-sync/sync.lock \
  env -i PATH=/usr/bin:/bin HOME=/tmp/opencode LANG=C.UTF-8 \
  PYTHONDONTWRITEBYTECODE=1 \
  /home/arle/.local/share/voicebot-reliability/media-venv/bin/python \
  /tmp/opencode/telephone-multilingual-audio-probe.py \
  --run-live --case dialogue --source-container livekit-worker-1
```

The command returned 0 and all three cases passed. Each case had one fresh final caller STT, one new exact approved reply, audible post-STT PCM and independent expected-language recognition; **expected-word coverage was 1.0 for all three**, above the unchanged 0.6 threshold.

| Language | Caller STT receipt | Post-STT voiced PCM | Reply capture | Independent language / word coverage |
| --- | ---: | ---: | ---: | --- |
| Estonian | 2,568 ms | 1,840 ms | 3,000 ms | `et` / 1.0 |
| English | 1,937 ms | 2,070 ms | 3,300 ms | `en` / 1.0 |
| Russian | 2,436 ms | 1,910 ms | 3,290 ms | `ru` / 1.0 |

Re-read executed JSON output to create the metrics record; no speech content was written. The probe cleaned its own rooms: zero probe rooms remained. Post-test read-only SQLite integrity checks passed for all three shared databases. The actual deployed worker's `pip check` returned 0 with no broken requirements. Public `/health` returned `{"ok":true}` through the fetch tool; a plain urllib request was refused with HTTP 403 and is not counted as application failure or successful verification.

Remaining boundaries: no real carrier/PSTN call, no within-call switching or booking-flow acceptance, and the recorded legacy FAQ reply mismatches are not hidden by the language-dialogue success. The intended publication target for evidence and the one-line native fixture change is a separate ops branch, not `master`, to avoid triggering another web/telephone rollout.

Russian provider-failure playback retains the documented cached Estonian apology; this release does not invent a Russian cached recording.
