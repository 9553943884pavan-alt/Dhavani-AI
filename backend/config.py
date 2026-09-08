"""
Centralized configuration — all tunables in one place.
Swap RIME_REGION between "east" and "west" to change endpoint globally.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys (loaded from .env) ---
RIME_API_KEY = os.getenv("RIME_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- Rime TTS Configuration ---
RIME_REGION = "east"  # Change to "west" if speedtest shows lower RTT

RIME_SPEAKER = "astra"
RIME_MODEL_ID = "mistv3"  # Always explicit — never rely on Rime's default
RIME_LANG = "en"
RIME_AUDIO_FORMAT = "mp3"

# Derived endpoints — change RIME_REGION above, these update automatically
_RIME_ENDPOINTS = {
    "east": {
        "http": "https://users-east.rime.ai/v1/rime-tts",
        "ws": "wss://users-east-ws.rime.ai/ws3",
    },
    "west": {
        "http": "https://users-west.rime.ai/v1/rime-tts",
        "ws": "wss://users-ws.rime.ai/ws3",
    },
}

RIME_HTTP_URL = _RIME_ENDPOINTS[RIME_REGION]["http"]
RIME_WS_URL = _RIME_ENDPOINTS[RIME_REGION]["ws"]

# Full WebSocket URL with query params
RIME_WS_FULL_URL = (
    f"{RIME_WS_URL}?speaker={RIME_SPEAKER}"
    f"&modelId={RIME_MODEL_ID}"
    f"&audioFormat={RIME_AUDIO_FORMAT}"
)

# --- Groq Configuration ---
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "llama-3.1-8b-instant")

# --- Server ---
HOST = "0.0.0.0"
PORT = 8000


def validate_configuration() -> None:
    """Fail during application startup when required provider keys are absent."""
    missing = [
        name
        for name, value in (
            ("RIME_API_KEY", RIME_API_KEY),
            ("GROQ_API_KEY", GROQ_API_KEY),
        )
        if not value.strip()
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )
