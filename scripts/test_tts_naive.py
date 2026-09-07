"""
Test script for Naive Rime TTS (Phase 2).
Sends a hardcoded test sentence via HTTP streaming,
measures time to first byte and full clip, and saves output_naive.mp3.
"""

import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.tts import synthesize_naive_sync
from backend.config import RIME_HTTP_URL, RIME_MODEL_ID, RIME_SPEAKER

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "samples", "output_naive.mp3")
TEST_SENTENCE = "Hello! This is a test of Rime's naive text-to-speech HTTP endpoint."


def main():
    print("=" * 60)
    print("Testing Naive Rime TTS (HTTP Streaming)")
    print(f"Endpoint: {RIME_HTTP_URL}")
    print(f"Model ID: {RIME_MODEL_ID}")
    print(f"Speaker:  {RIME_SPEAKER}")
    print(f"Input text: \"{TEST_SENTENCE}\"")
    print("=" * 60)

    try:
        audio_bytes, timing = synthesize_naive_sync(TEST_SENTENCE)

        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, "wb") as f:
            f.write(audio_bytes)

        print(f"[OK] Synthesis successful!")
        print(f"Audio size:          {len(audio_bytes)} bytes")
        print(f"Saved to:            {OUTPUT_FILE}")
        print(f"Time to first chunk: {timing['ttfb_ms']:.1f} ms")
        print(f"Total time to clip:  {timing['total_ms']:.1f} ms")
        print("=" * 60)

    except Exception as e:
        print(f"[FAIL] Naive TTS failed: {e}")
        raise


if __name__ == "__main__":
    main()
