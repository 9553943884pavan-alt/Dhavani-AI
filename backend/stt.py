"""
Speech-to-Text using Groq Whisper.
Includes automatic audio format detection and 429 retry/backoff.
"""

import io
import time
import asyncio
from groq import Groq, RateLimitError
from backend.config import GROQ_API_KEY, GROQ_STT_MODEL


def _get_client() -> Groq:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set in environment or .env file.")
    return Groq(api_key=GROQ_API_KEY)


def _detect_format(audio_bytes: bytes) -> tuple[str, str]:
    """Detect audio format from header bytes for Groq API."""
    if audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio.webm", "audio/webm"
    elif audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]:
        return "audio.wav", "audio/wav"
    elif audio_bytes.startswith(b"OggS"):
        return "audio.ogg", "audio/ogg"
    elif audio_bytes.startswith(b"ID3") or audio_bytes.startswith(b"\xff\xfb"):
        return "audio.mp3", "audio/mpeg"
    # Default to wav
    return "audio.wav", "audio/wav"


def transcribe(
    audio_bytes: bytes,
    filename: str | None = None,
    max_retries: int = 3,
) -> tuple[str, float]:
    """Transcribe audio bytes to text using Groq Whisper.

    Args:
        audio_bytes: Raw audio file bytes (WAV, WebM, MP3, etc.)
        filename: Optional filename hint. If not provided, auto-detected from magic bytes.
        max_retries: Number of retries on 429 rate limit.

    Returns:
        (transcript_text, elapsed_ms)
    """
    client = _get_client()

    if filename is None:
        fname, mime = _detect_format(audio_bytes)
    else:
        fname = filename
        mime = "audio/webm" if fname.endswith(".webm") else "audio/wav"

    audio_file = (fname, io.BytesIO(audio_bytes), mime)

    try:
        for attempt in range(max_retries):
            try:
                t0 = time.perf_counter()
                response = client.audio.transcriptions.create(
                    file=audio_file,
                    model=GROQ_STT_MODEL,
                    temperature=0.0,
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                return response.text.strip(), elapsed_ms

            except RateLimitError:
                if attempt >= max_retries - 1:
                    raise
                time.sleep(2 ** (attempt + 1))
                audio_file[1].seek(0)
    finally:
        client.close()


async def transcribe_async(
    audio_bytes: bytes,
    filename: str | None = None,
) -> tuple[str, float]:
    """Async wrapper around transcribe."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, transcribe, audio_bytes, filename)
