"""Non-operational voice-routing candidate descriptors.

The provisional runtime is LiveKit Agents (ARCHITECTURE.md section 4 and
ADR-0001). Pipecat is fallback option 2 only if the measured LiveKit spike
fails. Nothing in this module constructs media, provider, or agent objects.

Turn shape: Silero VAD gates barge-in; STT finals via VAD chunks;
LLM tokens stream into sentence-chunked TTS; filler
("Uks hetk, kontrollin...") covers PMS tool latency; endpointing
550ms finished / 1300ms dangling + backchannel filter + 8s cap.
Price utterances require a live price_quote_id from the booking adapter.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("et", "en", "ru")

# PHASE2_CANDIDATES_NOT_WIRED: ET -> managed neural + local fallbacks.
# ET entries MUST resolve to et-EE voices (fail closed otherwise).
TTS_ROUTE = {
    "et": ("azure-anu-kert", "google-et-EE-Standard-A", "pockettts-et", "piper-et"),
    "en": ("azure-en", "elevenlabs-turbo", "google-standard"),
    "ru": ("azure-ru", "elevenlabs-turbo", "chatterbox-selfhost"),
}

# Voices allowed on the ET chain. Anything else fails closed (P1-4).
ET_VOICE_ALLOW = ("azure-anu-kert", "google-et-EE", "pockettts-et", "piper-et")

# PHASE2_CANDIDATES_NOT_WIRED: STT research options.
STT_ROUTE = {
    "live": "deepgram-or-assemblyai-streaming",
    "et_final": "taltech-whisper-large-v3-turbo-et-verbatim-2604-ct2",
    "fallback": "groq-whisper-large-v3-turbo",
}

# PHASE2_CANDIDATES_NOT_WIRED: historical LLM research options.
LLM_ROUTE = {
    "primary": "groq-llama-8b",
    "secondary": "gemini-flash-lite",
    "tertiary": "openrouter-free",
    "et_tuned_phase2": ("estllm-8b", "eurollm-9b"),
}


def detect_language(partial_transcript: str, default: str = "et") -> str:
    """Placeholder language ID. Real impl: STT lang tag or tiny classifier."""
    return default if default in SUPPORTED_LANGUAGES else "et"


def build_pipeline(language: str = "et") -> dict:
    """Return non-operational research descriptors for tests/documentation.

    This does not assemble Pipecat or LiveKit. Replace it only after the
    provisional LiveKit Agents spike selects and pins the real runtime.
    """
    lang = language if language in SUPPORTED_LANGUAGES else "et"
    chain = TTS_ROUTE[lang]
    if lang == "et" and not all(v.startswith(ET_VOICE_ALLOW) for v in chain):
        raise ValueError(f"non-ET voice in ET chain: {chain!r}")
    return {
        "vad": "silero",
        "stt": STT_ROUTE,
        "llm": LLM_ROUTE,
        "tts": TTS_ROUTE[lang],
        "endpointing_ms": {"finished": 550, "dangling": 1300, "cap": 8000},
        "tracing": {"enable_tracing": True, "enable_metrics": True},
    }
