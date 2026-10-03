"use strict";
// Shared, verified capture behavior: bounded audio, stale-event guards and filtered resampling.
function stopMic() {
  // Local cancellation also retires permission/encoding still awaiting a result.
  state.micEpoch++;
  state.micStarting = false;
  const mic = state.mic;
  state.mic = null;
  if (!mic) {
    controls();
    return null;
  }
  clearTimeout(mic.timer);
  mic.stream.getTracks().forEach((track) => track.stop());
  mic.processor.disconnect();
  mic.source.disconnect();
  mic.gain.disconnect();
  mic.context.close().catch(() => {});
  $("demo-mic").textContent = demoCopy().micReady;
  controls();
  return mic;
}
function encodeWav(input, rate = 16000) {
  const frames = Math.min(240000, input.length),
    buffer = new ArrayBuffer(44 + frames * 2),
    view = new DataView(buffer);
  const text = (offset, s) => {
    for (let i = 0; i < s.length; i++)
      view.setUint8(offset + i, s.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + frames * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, frames * 2, true);
  for (let i = 0; i < frames; i++) {
    const sample = Math.max(-1, Math.min(1, input[i] || 0));
    view.setInt16(
      44 + i * 2,
      sample < 0 ? sample * 32768 : sample * 32767,
      true,
    );
  }
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 8192)
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(binary);
}
async function wav(mic) {
  const count = mic.chunks.reduce((sum, c) => sum + c.length, 0),
    input = new Float32Array(count);
  let at = 0;
  for (const chunk of mic.chunks) {
    input.set(chunk, at);
    at += chunk.length;
  }
  if (mic.context.sampleRate === 16000) return encodeWav(input);
  // Let the browser resample with its audio filter; dropping every third
  // sample aliases higher frequencies into the speech band at 48 kHz.
  const frames = Math.min(
    240000,
    Math.floor((count * 16000) / mic.context.sampleRate),
  );
  if (!frames) throw new Error(demoCopy().micEmpty);
  const Offline =
    window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const offline = new Offline(1, frames, 16000),
    buffer = offline.createBuffer(1, count, mic.context.sampleRate);
  buffer.copyToChannel(input, 0);
  const source = offline.createBufferSource();
  source.buffer = buffer;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  return encodeWav(rendered.getChannelData(0));
}
async function toggleMic() {
  if (state.mic) {
    const mic = stopMic(),
      generation = state.generation,
      session = state.sessionId,
      micEpoch = state.micEpoch;
    if (!mic.frames || mic.peak < 0.00001) {
      status("demo-status", demoCopy().micSilent, "error");
      return;
    }
    state.micStarting = true;
    controls();
    try {
      const audio = await wav(mic);
      if (
        generation === state.generation &&
        session === state.sessionId &&
        micEpoch === state.micEpoch &&
        state.connected
      ) {
        state.micStarting = false;
        await sendTurn({ audio_b64: audio });
      }
    } catch (error) {
      if (generation === state.generation && micEpoch === state.micEpoch)
        status(
          "demo-status",
          demoCopy().micEncoding + " " + error.message,
          "error",
        );
    } finally {
      if (generation === state.generation && micEpoch === state.micEpoch) {
        state.micStarting = false;
        controls();
      }
    }
    return;
  }
  if (state.turnBusy || state.micStarting || !requireDemoConnection()) return;
  const generation = state.generation,
    micEpoch = state.micEpoch;
  if (!state.sessionId) await startDemo();
  if (
    generation !== state.generation ||
    micEpoch !== state.micEpoch ||
    !state.connected ||
    !state.sessionId ||
    state.turnBusy ||
    state.micStarting ||
    document.hidden
  )
    return;
  const session = state.sessionId;
  let stream = null,
    context = null;
  state.micStarting = true;
  controls();
  stopAudio(true);
  status("demo-status", demoCopy().micPermission);
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    if (
      generation !== state.generation ||
      session !== state.sessionId ||
      micEpoch !== state.micEpoch ||
      state.mic ||
      state.turnBusy ||
      document.hidden
    ) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    $("demo-audio").pause();
    context = new (window.AudioContext || window.webkitAudioContext)();
    const source = context.createMediaStreamSource(stream),
      processor = context.createScriptProcessor(4096, 1, 1),
      gain = context.createGain();
    gain.gain.value = 0;
    const mic = {
      stream,
      context,
      source,
      processor,
      gain,
      chunks: [],
      frames: 0,
      peak: 0,
      speechFrames: 0,
      silenceFrames: 0,
    };
    state.mic = mic;
    // ponytail: energy endpointing, not semantic VAD; manual stop and 15s cap remain.
    processor.onaudioprocess = (event) => {
      if (state.mic !== mic) return;
      const chunk = event.inputBuffer.getChannelData(0),
        remaining = Math.max(
          0,
          Math.floor(context.sampleRate * 15) - mic.frames,
        ),
        kept = chunk.subarray(0, remaining);
      mic.chunks.push(new Float32Array(kept));
      mic.frames += kept.length;
      let energy = 0;
      for (const sample of kept) {
        energy += sample * sample;
        mic.peak = Math.max(mic.peak, Math.abs(sample));
      }
      const rms = Math.sqrt(energy / Math.max(1, kept.length)),
        level = Math.min(1, rms * 5);
      $("mic-level").value = level;
      $("mic-feedback-text").textContent =
        `${Math.floor(mic.frames / context.sampleRate)} / 15 s. ` +
        (level < 0.005 ? demoCopy().micQuiet : demoCopy().micSignal);
      if (rms >= 0.008) {
        mic.speechFrames += kept.length;
        mic.silenceFrames = 0;
      } else mic.silenceFrames += kept.length;
      if (
        mic.frames >= Math.floor(context.sampleRate * 15) ||
        (mic.speechFrames >= context.sampleRate * 0.2 &&
          mic.silenceFrames >=
            context.sampleRate * (state.endpointingMs / 1000))
      )
        toggleMic();
    };
    source.connect(processor);
    processor.connect(gain);
    gain.connect(context.destination);
    await context.resume();
    if (
      generation !== state.generation ||
      micEpoch !== state.micEpoch ||
      state.mic !== mic
    )
      return;
    mic.timer = setTimeout(() => {
      if (state.mic === mic) toggleMic();
    }, 15000);
    $("demo-mic").textContent = demoCopy().micStop;
    status("demo-status", demoCopy().micListening);
    presentation();
  } catch (_) {
    const current =
      generation === state.generation && micEpoch === state.micEpoch;
    if (state.mic?.stream === stream) stopMic();
    else {
      stream?.getTracks().forEach((track) => track.stop());
      context?.close().catch(() => {});
    }
    if (current) status("demo-status", demoCopy().micDenied, "error");
  } finally {
    if (
      generation === state.generation &&
      session === state.sessionId &&
      micEpoch === state.micEpoch
    ) {
      state.micStarting = false;
      controls();
    }
  }
}
