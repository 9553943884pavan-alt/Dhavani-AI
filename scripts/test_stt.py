"""
Test script for STT (Phase 1).
Generates a synthetic WAV test file if none exists, then transcribes it.
"""

import sys
import os
import wave
import struct
import math
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "samples")
SAMPLE_WAV = os.path.join(SAMPLES_DIR, "test.wav")


def generate_test_wav(filepath: str):
    """Generate a short WAV file with a spoken-word-like tone
    (440 Hz sine wave, 2 seconds). This is just to have a valid WAV
    for testing the STT pipeline — Whisper will return empty or
    gibberish for a pure tone, but it proves the API call works.
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    sample_rate = 16000
    duration = 2.0
    frequency = 440.0
    n_samples = int(sample_rate * duration)

    with wave.open(filepath, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            sample = int(32767 * 0.5 * math.sin(2 * math.pi * frequency * t))
            wf.writeframes(struct.pack("<h", sample))

    print(f"Generated test WAV: {filepath} ({duration}s, {sample_rate}Hz)")


def main():
    # Generate sample if needed
    if not os.path.exists(SAMPLE_WAV):
        print("No test.wav found — generating synthetic sample...")
        generate_test_wav(SAMPLE_WAV)
    else:
        print(f"Using existing sample: {SAMPLE_WAV}")

    # Read the file
    with open(SAMPLE_WAV, "rb") as f:
        audio_bytes = f.read()

    print(f"Audio file size: {len(audio_bytes)} bytes")
    print(f"STT model: whisper-large-v3-turbo")
    print("-" * 50)

    # Import and run transcription
    from backend.stt import transcribe

    try:
        transcript, elapsed_ms = transcribe(audio_bytes)
        print(f"Transcript: '{transcript}'")
        print(f"Latency: {elapsed_ms:.1f} ms")
        print("-" * 50)
        print("[OK] STT integration working!")
    except Exception as e:
        print(f"[FAIL] STT failed: {e}")
        raise


if __name__ == "__main__":
    main()
