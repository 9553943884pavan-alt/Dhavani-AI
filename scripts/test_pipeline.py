"""
Test script for End-to-End Pipeline (Phase 5).
Runs one request in Naive mode and one request in Optimized mode,
and compares T0 -> T3 latency side-by-side.
"""

import sys
import os
import asyncio
import json
import time
import websockets

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_WAV = os.path.join(os.path.dirname(__file__), "..", "samples", "test.wav")
SERVER_URL = "ws://127.0.0.1:8000/ws/voice"


async def run_test_request(mode: str, test_text: str | None = None, audio_bytes: bytes | None = None):
    print(f"\n[{mode.upper()} MODE] Starting request...")
    url = f"{SERVER_URL}?mode={mode}"
    
    received_audio_bytes = 0
    first_chunk_received = False
    t_first_chunk = None
    timing_data = None
    transcript = None
    llm_text = []

    async with websockets.connect(url) as ws:
        t_send = time.perf_counter()

        if audio_bytes:
            await ws.send(audio_bytes)
        else:
            await ws.send(json.dumps({"action": "text", "text": test_text, "mode": mode}))

        async for message in ws:
            if isinstance(message, bytes):
                received_audio_bytes += len(message)
                if not first_chunk_received:
                    first_chunk_received = True
                    t_first_chunk = time.perf_counter()
            else:
                data = json.loads(message)
                mtype = data.get("type")

                if mtype == "transcript":
                    transcript = data.get("text")
                    print(f"  -> Transcript (T1): \"{transcript}\" ({data.get('t1_ms', 0):.1f} ms)")
                elif mtype == "t2":
                    print(f"  -> First LLM token (T2): {data.get('t2_ms', 0):.1f} ms")
                elif mtype == "llm_delta":
                    llm_text.append(data.get("delta", ""))
                elif mtype == "llm_text":
                    llm_text = [data.get("text", "")]
                    print(f"  -> Full LLM text (T2): \"{data.get('text')}\" ({data.get('t2_ms', 0):.1f} ms)")
                elif mtype == "t3":
                    print(f"  -> First Rime Audio (T3): {data.get('t3_ms', 0):.1f} ms  <-- TIME TO FIRST AUDIO")
                elif mtype == "timing":
                    timing_data = data
                elif mtype == "error":
                    print(f"  -> ERROR: {data.get('message')}")
                elif mtype == "done":
                    break

    return {
        "mode": mode,
        "timing": timing_data,
        "audio_bytes": received_audio_bytes,
        "transcript": transcript,
        "llm_text": "".join(llm_text),
    }


async def main():
    print("=" * 65)
    print("Verifying Phase 5 End-to-End Pipeline (Naive vs Optimized)")
    print("=" * 65)

    test_prompt = "What is the capital of France and why is it famous? Answer in one sentence."

    # 1. Run Naive Mode
    naive_res = await run_test_request("naive", test_text=test_prompt)

    # 2. Run Optimized Mode
    opt_res = await run_test_request("optimized", test_text=test_prompt)

    # 3. Test with Audio file (STT -> LLM -> TTS)
    if os.path.exists(SAMPLE_WAV):
        with open(SAMPLE_WAV, "rb") as f:
            sample_bytes = f.read()
        print("\n[AUDIO STT TEST] Running optimized pipeline with test.wav...")
        audio_opt_res = await run_test_request("optimized", audio_bytes=sample_bytes)
        print(f"Audio STT result: transcript='{audio_opt_res['transcript']}'")

    print("\n" + "=" * 65)
    print("SIDE-BY-SIDE LATENCY COMPARISON")
    print("=" * 65)
    naive_t3 = naive_res["timing"]["t3_ms"] if naive_res["timing"] else 0
    opt_t3 = opt_res["timing"]["t3_ms"] if opt_res["timing"] else 0
    diff_ms = naive_t3 - opt_t3
    pct_reduction = (diff_ms / naive_t3 * 100) if naive_t3 > 0 else 0

    print(f"Naive T3 (TTFA):      {naive_t3:.1f} ms")
    print(f"Optimized T3 (TTFA):  {opt_t3:.1f} ms")
    print(f"Latency Saved:        {diff_ms:.1f} ms ({pct_reduction:.1f}% reduction!)")
    print(f"Naive Total Time:     {naive_res['timing']['total_ms']:.1f} ms")
    print(f"Optimized Total Time: {opt_res['timing']['total_ms']:.1f} ms")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
