"""
Test script for Optimized Rime Streaming TTS (Phase 4).
Feeds LLM stream directly token-by-token into Rime WebSocket,
measures:
  1. Time from first LLM token sent -> First Rime audio chunk received
  2. Total elapsed time
  3. Saves streaming audio to output_streaming.mp3
"""

import sys
import os
import asyncio
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.llm import stream_completion
from backend.tts import synthesize_streaming
from backend.config import RIME_WS_FULL_URL, RIME_MODEL_ID, RIME_SPEAKER, GROQ_LLM_MODEL

PROMPT = "Why is latency so critical for voice user interfaces? Answer in two sentences."
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "samples", "output_streaming.mp3")


async def main():
    print("=" * 65)
    print("Testing Optimized Rime Streaming TTS (LLM Tokens -> Rime WS)")
    print(f"WS URL:   {RIME_WS_FULL_URL}")
    print(f"Model ID: {RIME_MODEL_ID}")
    print(f"Speaker:  {RIME_SPEAKER}")
    print(f"LLM:      {GROQ_LLM_MODEL}")
    print(f"Prompt:   \"{PROMPT}\"")
    print("=" * 65)

    metrics = {}
    audio_chunks = []
    t_start = time.perf_counter()

    print("\nStarting streaming pipeline (Token-by-Token LLM -> Rime WS)...")
    llm_generator = stream_completion(PROMPT)

    async for chunk in synthesize_streaming(llm_generator, metrics=metrics):
        audio_chunks.append(chunk)

    t_end = time.perf_counter()
    total_audio = b"".join(audio_chunks)

    # Save output audio
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "wb") as f:
        f.write(total_audio)

    print("\n" + "=" * 65)
    print("[OK] Streaming synthesis completed!")
    print(f"Total audio bytes:            {len(total_audio):,} bytes ({metrics.get('total_chunks', len(audio_chunks))} chunks)")
    print(f"Saved audio to:               {OUTPUT_FILE}")
    print("-" * 65)
    print(f"WebSocket connect time:       {metrics.get('ws_connect_ms', 0):.1f} ms")
    if "tts_first_chunk_latency_ms" in metrics:
        print(f"First token sent -> First audio:  {metrics['tts_first_chunk_latency_ms']:.1f} ms  <-- TTS_FIRST_CHUNK_LATENCY (CORE LEVER)")
    
    t_first_chunk = metrics.get("t_first_chunk", t_start)
    ttfa_from_start = (t_first_chunk - t_start) * 1000
    print(f"Time to First Audio (TTFA):   {ttfa_from_start:.1f} ms (from user prompt dispatch)")
    print(f"Total pipeline time:          {(t_end - t_start) * 1000:.1f} ms")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
