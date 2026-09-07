"""
Test script for LLM streaming (Phase 3).
Streams tokens from Groq Llama 3.1 8B Instant and logs per-token timing
and time-to-first-token (TTFT).
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
from backend.config import GROQ_LLM_MODEL

PROMPT = "Why is latency so critical for voice user interfaces? Answer in two sentences."


async def test_stream():
    print("=" * 60)
    print("Testing Groq LLM Streaming")
    print(f"Model:  {GROQ_LLM_MODEL}")
    print(f"Prompt: \"{PROMPT}\"")
    print("=" * 60)

    t_start = time.perf_counter()
    first_token_time = None
    token_count = 0
    full_text = []

    print("\n[Streaming Tokens]:")
    async for token in stream_completion(PROMPT):
        now = time.perf_counter()
        token_count += 1
        full_text.append(token)

        if first_token_time is None:
            first_token_time = now
            ttft_ms = (first_token_time - t_start) * 1000
            print(f"\n>>> Time to First Token (TTFT): {ttft_ms:.1f} ms <<<\n")

        # Print token immediately without buffering
        sys.stdout.write(token)
        sys.stdout.flush()

    t_end = time.perf_counter()
    total_ms = (t_end - t_start) * 1000

    print("\n\n" + "=" * 60)
    print(f"[OK] Stream completed successfully!")
    print(f"Total tokens:             {token_count}")
    if first_token_time:
        print(f"Time to first token (TTFT): {(first_token_time - t_start) * 1000:.1f} ms")
    print(f"Total generation time:    {total_ms:.1f} ms")
    if token_count > 0:
        tokens_per_sec = token_count / ((t_end - (first_token_time or t_start)) or 1e-6)
        print(f"Tokens/sec (generation):  {tokens_per_sec:.1f} tok/s")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_stream())
