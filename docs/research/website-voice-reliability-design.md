# Website and native speech reliability repair

2026-10-03. Integrate with upstream through `f541da6`; retain fictional spa/room
booking, call history, model configuration, native HTML/JavaScript and the
existing inbound telephone route. No new application dependencies, continuous
background listening, outbound calls or real-customer writes.

## Delivery and consent

- Session creation supplies greeting audio with a 25-second synthesis bound;
  a failure retains the text session and actionable guidance.
- A completed HTTP synthesis issues `recap_delivery_id`, not booking approval.
  The receipt is random, session-owned, one-use and tied to the exact pending
  preparation object. The server consumes it before observing the next final
  transcript; expiry and explicit consent remain authoritative in CallTools.
- The operator browser acknowledges only audio completion or an explicit
  “Olen kokkuvõtte läbi lugenud” action. Interrupted/blocked playback does not
  acknowledge automatically. Foreign/stale/malformed receipts cannot write.
- A playback/read acknowledgement is an **authenticated operator-client
  assertion**, not cryptographic evidence that a person heard every word.
  It cannot substitute for subsequent “Jah, kinnitan.” or cancellation consent.
- Preserve upstream's trusted HTTP terminal actions: only approved pending
  state or owned explicit cancellation can choose a write without the model;
  canonical recaps and mutation outcomes avoid redundant provider follow-ups.
- Unknown writes remain sticky; capture/playback/provider failures never
  automatically repeat booking or cancellation.

## Browser capture

Keep upstream's filtered OfflineAudioContext resampling to 16 kHz mono PCM,
microphone-level feedback and preparation serialization. Pause assistant
playback on the gesture and again when permission actually resolves. Block
text/example/audio turns during permission/encoding. Capture stops after a
1.5-second energy pause following at least 0.2 seconds of voiced energy,
manual stop or the existing 15-second cap. Empty/digital-flat capture never
reaches paid ASR. This is bounded energy endpointing, not semantic VAD.

Playback rejection preserves native controls and explains manual playback or
text reading. Decode failure retains the response and unknown-write warning.
Media callbacks are generation/session/URL-scoped; logout closes tracks,
revokes audio URLs and cannot revive a stale receipt.
Local microphone cancellation additionally retires pending permission and
encoding with a capture epoch. Ending a conversation or hiding the page must
stop capture even if the session-delete request fails; late grant/results and
cleanup cannot resume recording or clear a newer operation's preparation flag.

## Native recovery

A successful LLM stream without text/tools previously never entered speech
guards. Seed ASK_DATE_TIME only after successful exhaustion and let the
existing authoritative guard render the outcome. Forward normal chunks;
never execute length-truncated tools, retry mutations or swallow exceptions/
cancellation. A TTS stream producing zero frames now plays the cached apology.
Preserve concurrent upstream language recognition and Azure voice selection;
the empty-stream seed and cached-apology metadata use the generation's language.
English and bilingual fallback audio remain available without reverting to
shared apology/history flags.

Per-generation private TimedString metadata on PCM keeps completed history
consistent with actual checked speech or cached apology, even if shared
booking state changes later. The pinned SDK's originating SpeechHandle item
callback records recap delivery, with captured preparation identity, exact
text, completion and interruption checks. `say()` and generated replies emit
session events in opposite orders; delivery must not depend on that ordering.
The callback is consumed once and removed when speech finishes.

These narrow private SDK hooks are regression-tested against Agents 1.8.4;
re-run generated/say/cancellation/history tests before an SDK upgrade. Public
web, synthetic microphone graphs and private RTC audio remain distinct from
physical microphone and actual PSTN acceptance.
