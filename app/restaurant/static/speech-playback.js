"use strict";
// Derived from the reviewed dashboard playback: bounded NDJSON, contiguous audio, exact recap receipts.
function clearRecap() {
  clearTimeout(state.recap?.timer);
  state.recap = null;
  state.recapDeliveryId = null;
  $("demo-recap-read").hidden = true;
}
function currentRecap(recap) {
  return (
    !!recap &&
    state.recap === recap &&
    state.connected &&
    recap.generation === state.generation &&
    recap.sessionId === state.sessionId &&
    Date.now() < recap.expiresAt &&
    $("demo-messages").contains(recap.message) &&
    recap.message.querySelector("span")?.textContent === recap.reply
  );
}
function acknowledgeRecap(recap, heard = false) {
  if (!currentRecap(recap) || state.turnBusy || recap.acknowledged) return;
  recap.acknowledged = true;
  state.recapDeliveryId = recap.id;
  $("demo-recap-read").hidden = true;
  status("demo-status", recapPlayedMessage(heard));
}
function renderRecap(data, message, receivedAt = Date.now()) {
  if (
    typeof data.recap_delivery_id !== "string" ||
    !/^[a-f0-9]{32}$/.test(data.recap_delivery_id) ||
    !Number.isFinite(data.recap_expires_in_s) ||
    data.recap_expires_in_s <= 0 ||
    typeof data.reply !== "string" ||
    !data.reply.trim() ||
    ["fallback", "tools_failed", "unknown_outcome"].includes(data.outcome)
  )
    return null;
  const expiresAt = receivedAt + data.recap_expires_in_s * 1000;
  if (expiresAt <= Date.now()) return null;
  const recap = {
    id: data.recap_delivery_id,
    sessionId: state.sessionId,
    generation: state.generation,
    expiresAt,
    message,
    reply: data.reply,
    acknowledged: false,
  };
  state.recap = recap;
  recap.timer = setTimeout(() => {
    if (state.recap === recap) clearRecap();
  }, expiresAt - Date.now());
  $("demo-recap-read").hidden = false;
  return recap;
}
function fullPlayback(audio) {
  // An ended event also follows seeking; only contiguous played ranges deliver a recap.
  if (
    !audio.ended ||
    !Number.isFinite(audio.duration) ||
    audio.duration <= 0 ||
    !audio.played.length
  )
    return false;
  let through = 0;
  for (let i = 0; i < audio.played.length; i++) {
    if (audio.played.start(i) > through + 0.001) return false;
    through = Math.max(through, audio.played.end(i));
  }
  return through >= audio.duration - 0.001;
}
function releaseAudio(playback) {
  if (playback) {
    playback.queue.length = playback.chunks.length = 0;
    if (playback.source) {
      playback.source.onsourceopen = playback.source.onsourceclose = null;
      if (playback.buffer) {
        playback.buffer.onupdateend =
          playback.buffer.onerror =
          playback.buffer.onabort =
            null;
        try {
          playback.buffer.abort();
          playback.source.removeSourceBuffer(playback.buffer);
        } catch (_) {}
      }
      try {
        if (playback.source.readyState === "open")
          playback.source.endOfStream();
      } catch (_) {}
    }
    playback.source = playback.buffer = null;
    playback.url = null;
  }
  $("demo-audio").onended =
    $("demo-audio").onpause =
    $("demo-audio").onerror =
    $("demo-audio").onplaying =
    $("demo-audio").onseeking =
    $("demo-audio").onwaiting =
    $("demo-audio").onstalled =
      null;
  $("demo-audio").pause();
  $("demo-audio").removeAttribute("src");
  $("demo-audio").load();
  $("demo-audio").hidden = true;
  if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
  state.audioUrl = null;
}
function stopAudio(preserveDelivered = false) {
  // Starting capture may retain a completed/read receipt, never a partial recap.
  if (
    !preserveDelivered ||
    !state.recapDeliveryId ||
    !currentRecap(state.recap)
  )
    clearRecap();
  state.audioEpoch++;
  const playback = state.playback;
  state.playback = null;
  state.turnController?.abort();
  state.turnController = null;
  playback?.reader?.cancel().catch(() => {});
  releaseAudio(playback);
}
const MAX_REPLY_AUDIO = 8 * 1024 * 1024;
const MAX_REPLY_WIRE = 12 * 1024 * 1024; // Base64 expansion plus bounded event metadata.
function audioBytes(value, limit = MAX_REPLY_AUDIO) {
  if (
    typeof value !== "string" ||
    !value.length ||
    value.length % 4 ||
    value.length > Math.ceil(limit / 3) * 4 ||
    !/^[A-Za-z0-9+/]*={0,2}$/.test(value)
  )
    throw new Error(demoCopy().audioInvalid);
  const raw = atob(value);
  if (!raw.length || raw.length > limit || btoa(raw) !== value)
    throw new Error(demoCopy().audioInvalid);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}
function currentPlayback(playback) {
  return (
    !!playback &&
    state.connected &&
    playback === state.playback &&
    playback.generation === state.generation &&
    playback.session === state.sessionId &&
    playback.epoch === state.audioEpoch &&
    (!playback.url ||
      (playback.url === state.audioUrl && playback.url === $("demo-audio").src))
  );
}
function newPlayback(recap = null) {
  const playback = {
    generation: state.generation,
    session: state.sessionId,
    epoch: state.audioEpoch,
    queue: [],
    chunks: [],
    reader: null,
    source: null,
    buffer: null,
    complete: false,
    eof: false,
    appended: false,
    started: false,
    seeked: false,
    interrupted: false,
    earlyEnd: false,
    failed: false,
    recap,
    resultStatus: $("demo-status").textContent,
    resultError: false,
  };
  state.playback = playback;
  return playback;
}
function failPlayback(playback) {
  if (!currentPlayback(playback)) return;
  playback.failed = true;
  // A media failure retires audio, not a successfully validated canonical text recap.
  // Continue bounded stream parsing so only an exact terminal done can permit reading.
  releaseAudio(playback);
  status(
    "demo-status",
    playback.resultStatus + " " + demoCopy().audioError,
    "error",
  );
  controls();
}
function bindPlayback(playback, source) {
  const audio = $("demo-audio");
  state.audioUrl = playback.url = URL.createObjectURL(source);
  audio.src = state.audioUrl;
  audio.hidden = false;
  audio.onplaying = () => {
    if (currentPlayback(playback)) playback.started = true;
  };
  audio.onseeking = () => {
    if (currentPlayback(playback)) playback.seeked = true;
  };
  audio.onpause = () => {
    if (currentPlayback(playback) && playback.started && !audio.ended)
      playback.interrupted = true;
  };
  audio.onwaiting = audio.onstalled = () => {
    if (currentPlayback(playback) && playback.started && audio.currentTime > 0)
      playback.interrupted = true;
  };
  audio.onended = () => {
    if (
      !currentPlayback(playback) ||
      !playback.url ||
      audio.currentSrc !== playback.url ||
      !audio.ended
    )
      return;
    if (!playback.complete || !playback.eof || !playback.appended) {
      playback.earlyEnd = true;
      return;
    }
    if (
      playback.failed ||
      playback.seeked ||
      playback.interrupted ||
      playback.earlyEnd ||
      !playback.started ||
      (playback.source && playback.source.readyState !== "ended") ||
      !fullPlayback(audio)
    )
      return;
    if (playback.recap) acknowledgeRecap(playback.recap, true);
    else
      status(
        "demo-status",
        playback.resultStatus + " " + demoCopy().replyPlayed,
        playback.resultError ? "error" : "",
      );
  };
  audio.onerror = () => failPlayback(playback);
}
function startPlayback(playback) {
  try {
    $("demo-audio")
      .play()
      .catch(() => {
        if (currentPlayback(playback)) {
          playback.started = false;
          status(
            "demo-status",
            playback.resultStatus + " " + demoCopy().autoplay,
            "error",
          );
        }
      });
  } catch (_) {
    if (currentPlayback(playback))
      status(
        "demo-status",
        playback.resultStatus + " " + demoCopy().autoplay,
        "error",
      );
  }
}
function playbackResult(data, playback) {
  playback.resultStatus = $("demo-status").textContent;
  playback.resultError = [
    "unknown_outcome",
    "tools_failed",
    "tts_failed",
  ].includes(data.outcome);
}
function playReply(data, recap = null) {
  const playback = newPlayback(recap);
  playback.complete = playback.eof = playback.appended = true;
  playbackResult(data, playback);
  if (!data.audio_b64) return;
  try {
    bindPlayback(
      playback,
      new Blob([audioBytes(data.audio_b64)], {
        type: data.audio_type === "audio/wav" ? "audio/wav" : "audio/mpeg",
      }),
    );
    startPlayback(playback);
  } catch (_) {
    failPlayback(playback);
  }
}
function appendStreamAudio(playback, bytes) {
  if (!currentPlayback(playback))
    throw new DOMException("Playback retired", "AbortError");
  if (playback.failed) return;
  const Media = window.MediaSource;
  if (!Media || !Media.isTypeSupported("audio/mpeg")) {
    playback.chunks.push(bytes);
    return;
  }
  playback.queue.push(bytes);
  if (!playback.source) {
    playback.source = new Media();
    bindPlayback(playback, playback.source);
    playback.source.onsourceopen = () => {
      if (!currentPlayback(playback)) return;
      try {
        playback.buffer = playback.source.addSourceBuffer("audio/mpeg");
        playback.buffer.onupdateend = () => pumpStreamAudio(playback);
        playback.buffer.onerror = playback.buffer.onabort = () =>
          failPlayback(playback);
        pumpStreamAudio(playback);
      } catch (_) {
        failPlayback(playback);
      }
    };
    playback.source.onsourceclose = () => {
      if (!playback.appended) failPlayback(playback);
    };
  } else pumpStreamAudio(playback);
}
function pumpStreamAudio(playback) {
  if (
    !currentPlayback(playback) ||
    !playback.buffer ||
    playback.buffer.updating ||
    playback.failed
  )
    return;
  try {
    if (playback.queue.length) {
      playback.buffer.appendBuffer(playback.queue.shift());
      if (!playback.playAttempted) {
        playback.playAttempted = true;
        startPlayback(playback);
      }
    } else if (playback.eof && !playback.appended) {
      playback.source.endOfStream();
      playback.appended = true;
    }
  } catch (_) {
    failPlayback(playback);
  }
}
async function readTurnStream(response, controller) {
  if (!response.body) throw new Error(demoCopy().audioInvalid);
  const playback = newPlayback(),
    reader = response.body.getReader(),
    decoder = new TextDecoder("utf-8", { fatal: true });
  playback.reader = reader;
  let pending = "",
    wireBytes = 0,
    totalAudio = 0,
    seq = 0,
    lines = 0,
    reply = null,
    done = null,
    replyNode = null,
    receivedAt = null;
  const invalid = () => {
    throw new Error(demoCopy().audioInvalid);
  };
  const consume = (line) => {
    if (!line.trim()) return;
    if (line.length > 256 * 1024 || ++lines > 8192 || done) invalid();
    let event;
    try {
      event = JSON.parse(line);
    } catch (_) {
      invalid();
    }
    if (
      !event ||
      Array.isArray(event) ||
      typeof event !== "object" ||
      typeof event.type !== "string" ||
      (event.type !== "done" && Object.hasOwn(event, "recap_delivery_id"))
    )
      invalid();
    if (event.type === "reply") {
      if (
        reply ||
        seq ||
        Object.keys(event).some(
          (key) => !["type", "reply", "language", "audio_type"].includes(key),
        ) ||
        typeof event.reply !== "string" ||
        !event.reply.length ||
        event.reply.length > 32768 ||
        !["et", "en", "ru"].includes(event.language) ||
        event.audio_type !== "audio/mpeg"
      )
        invalid();
      reply = event;
      state.replyLanguage = event.language;
      replyNode = addMessage(demoCopy().assistant, event.reply);
    } else if (event.type === "audio") {
      if (
        !reply ||
        event.seq !== seq ||
        Object.keys(event).some(
          (key) => !["type", "seq", "audio_b64"].includes(key),
        )
      )
        invalid();
      const bytes = audioBytes(event.audio_b64, 128 * 1024);
      totalAudio += bytes.length;
      if (totalAudio > MAX_REPLY_AUDIO) invalid();
      seq++;
      appendStreamAudio(playback, bytes);
    } else if (event.type === "done") {
      if (
        !reply ||
        event.reply !== reply.reply ||
        event.language !== reply.language ||
        event.audio_type !== "audio/mpeg" ||
        event.audio_b64 !== "" ||
        ![
          "ok",
          "tools_ok",
          "tools_failed",
          "unknown_outcome",
          "fallback",
          "tts_failed",
        ].includes(event.outcome) ||
        (event.booking_changes !== undefined &&
          !Array.isArray(event.booking_changes)) ||
        (event.tts_failed !== undefined &&
          typeof event.tts_failed !== "boolean") ||
        (event.recap_delivery_id != null &&
          (!/^[a-f0-9]{32}$/.test(event.recap_delivery_id) ||
            !seq ||
            event.tts_failed ||
            event.outcome === "tts_failed"))
      )
        invalid();
      done = event;
      receivedAt = Date.now();
    } else invalid();
  };
  const abort = () => reader.cancel().catch(() => {});
  controller.signal.addEventListener("abort", abort, { once: true });
  try {
    while (true) {
      const part = await reader.read();
      if (controller.signal.aborted || !currentPlayback(playback))
        throw new DOMException("Playback retired", "AbortError");
      if (part.done) break;
      wireBytes += part.value.byteLength;
      if (wireBytes > MAX_REPLY_WIRE) invalid();
      pending += decoder.decode(part.value, { stream: true });
      let newline;
      while ((newline = pending.indexOf("\n")) !== -1) {
        consume(pending.slice(0, newline));
        pending = pending.slice(newline + 1);
      }
      if (pending.length > 256 * 1024) invalid();
    }
    pending += decoder.decode();
    if (pending.length || !reply || !done) invalid();
    playback.reader = null;
    playback.complete = playback.eof = true;
    if (done.tts_failed || done.outcome === "tts_failed" || !seq) {
      playback.failed = true;
      releaseAudio(playback);
    } else pumpStreamAudio(playback);
    return { ...done, _stream: { playback, replyNode, receivedAt } };
  } catch (error) {
    if (currentPlayback(playback)) stopAudio();
    throw error;
  } finally {
    controller.signal.removeEventListener("abort", abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
function finishStreamPlayback(data, recap) {
  const playback = data._stream.playback;
  if (!currentPlayback(playback)) return;
  playback.recap = recap;
  playbackResult(data, playback);
  if (playback.failed) {
    status(
      "demo-status",
      playback.resultStatus + " " + demoCopy().audioError,
      "error",
    );
    return;
  }
  if (!playback.source && playback.chunks.length) {
    playback.appended = true;
    bindPlayback(playback, new Blob(playback.chunks, { type: "audio/mpeg" }));
    playback.chunks.length = 0;
    startPlayback(playback);
  }
}
