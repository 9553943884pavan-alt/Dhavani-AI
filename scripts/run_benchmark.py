"""
Repeatable benchmark script for Rime Hackathon (Phase 7).

DESIGN: Controlled TTS-only comparison (LLM variance eliminated)
-----------------------------------------------------------------
For each query the LLM completion is generated ONCE and the resulting text is
frozen.  The identical frozen text is then fed into BOTH the naive TTS path and
the optimized TTS path.  This makes the benchmark a pure comparison of TTS
delivery mechanism (HTTP POST vs. Rime WebSocket streaming) rather than a
comparison of two independent LLM calls that may produce different-length
responses and therefore inherently different TTS durations.

Measurement definitions (see backend/tts.py for full commentary):
  tts_first_chunk_latency_ms (headline metric)
    naive:     ttfb_ms          = t_first_chunk  - t_request_start
    optimized: tts_first_chunk_latency_ms = t_first_chunk - t_first_token_sent
  Both t_request_start / t_first_token_sent mark "the instant Rime receives its
  first real input"; both t_first_chunk marks "first decoded audio bytes available".

Outputs:
  benchmark_results.csv  — per-mode row; llm_text column is shared (same value for
                           both rows of the same query and is so labelled in the header)
  benchmark_result.png   — dual-panel comparison chart
"""

import sys
import os
import asyncio
import time
import csv
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Headless / no display required
import matplotlib.pyplot as plt

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.config import (
    RIME_REGION,
    RIME_MODEL_ID,
    RIME_SPEAKER,
    RIME_AUDIO_FORMAT,
    GROQ_LLM_MODEL,
)
from backend.llm import get_full_completion
from backend.tts import synthesize_naive_sync, synthesize_streaming

# ---------------------------------------------------------------------------
# Query set
# ---------------------------------------------------------------------------
QUERIES = [
    "What is the speed of light in vacuum?",
    "Give me two tips to stay focused while working from home.",
    "Why do leaves change color during autumn?",
    "Explain how a jet engine generates forward thrust.",
    "What is the difference between synchronous and asynchronous programming?",
    "How does the immune system remember viruses it has encountered?",
    "Recommend a healthy breakfast that takes less than ten minutes to prepare.",
    "Explain the theory of general relativity in simple terms.",
    "What makes quantum computing fundamentally different from classical computing?",
    # Stress case: longer response
    "Provide a detailed overview of the history of space exploration from Sputnik to the Mars rovers.",
]

CSV_FILE = os.path.join(os.path.dirname(__file__), "..", "benchmark_results.csv")
CHART_FILE = os.path.join(os.path.dirname(__file__), "..", "benchmark_result.png")


# ---------------------------------------------------------------------------
# Step 0: Generate LLM text ONCE per query
# ---------------------------------------------------------------------------

async def generate_llm_text(query: str) -> tuple[str, float]:
    """Call the LLM once and return (full_text, llm_ms).

    This is the only point where the LLM is invoked per query.  The returned
    text is then fed verbatim into both TTS paths so LLM sampling variance
    cannot influence the TTS latency comparison.
    """
    t0 = time.perf_counter()
    full_text, _ = await get_full_completion(query)
    llm_ms = (time.perf_counter() - t0) * 1000
    if not full_text or not full_text.strip():
        full_text = f"Here is a summary addressing your question regarding {query.lower()}."
    return full_text.strip(), llm_ms


# ---------------------------------------------------------------------------
# Step 1a: Naive TTS — HTTP POST with the frozen text
# ---------------------------------------------------------------------------

async def run_naive_tts(
    query: str,
    frozen_text: str,
    llm_ms: float,
) -> dict:
    """Naive TTS path: POST the complete frozen_text to Rime HTTP endpoint.

    t_tts_dispatch (= t_request_start) and t_first_chunk are as defined in
    synthesize_naive_sync.  llm_ms is carried in from the shared LLM call;
    t2_ms (LLM-done relative to pipeline-start) is reconstructed so that
    TTFA (t3_ms) remains comparable to the optimized path.
    """
    # t0: start of this sub-pipeline (after LLM already completed)
    t0 = time.perf_counter()

    loop = asyncio.get_event_loop()
    audio_bytes, tts_timing = await loop.run_in_executor(
        None, synthesize_naive_sync, frozen_text
    )

    # t_request_start from tts_timing is the absolute perf_counter value at
    # HTTP dispatch; t_first_chunk is absolute perf_counter at first audio byte.
    # Re-express both relative to t0 so t3_ms is "TTS-only elapsed from this
    # path's start" — useful for the TTS-isolated comparison.
    t_request_start = tts_timing["t_request_start"]
    t_first_chunk = tts_timing["t_first_chunk"]
    t_complete = tts_timing["t_complete"]

    return {
        "mode": "naive",
        "query": query,
        # shared_llm_text is logged once per query pair; this column is
        # identical between the naive and optimized rows for the same query.
        "shared_llm_text": frozen_text,
        "shared_llm_ms": llm_ms,
        # TTS-isolated timings (relative to t_request_start = t_tts_dispatch)
        "t3_ms": (t_first_chunk - t_request_start) * 1000,   # = ttfb_ms
        "tts_first_chunk_ms": tts_timing["ttfb_ms"],          # headline metric
        "total_tts_ms": (t_complete - t_request_start) * 1000,
        "audio_bytes": len(audio_bytes),
    }


# ---------------------------------------------------------------------------
# Step 1b: Optimized TTS — replay frozen text token-by-token into Rime WS
# ---------------------------------------------------------------------------

async def _replay_as_token_stream(text: str, delay_s: float = 0.0):
    """Async generator that yields each word of text as a separate token.

    Using word-level chunking faithfully mimics the token-by-token stream that
    the LLM would have produced — Rime's WS segment buffer handles re-joining.
    An optional inter-token delay can be added for future sensitivity testing
    but defaults to 0 so TTS latency is not inflated artificially.
    """
    words = text.split()
    for i, word in enumerate(words):
        # Preserve spacing: prepend a space before every word except the first,
        # matching how most tokenisers emit tokens.
        yield (word if i == 0 else " " + word)
        if delay_s:
            await asyncio.sleep(delay_s)


async def run_optimized_tts(
    query: str,
    frozen_text: str,
    llm_ms: float,
) -> dict:
    """Optimized TTS path: stream frozen_text word-by-word into Rime WebSocket.

    t_first_token_sent and t_first_chunk are as defined in synthesize_streaming.
    tts_first_chunk_latency_ms = t_first_chunk - t_first_token_sent  (headline metric).
    """
    metrics: dict = {}
    audio_chunks: list[bytes] = []

    async for chunk in synthesize_streaming(_replay_as_token_stream(frozen_text), metrics=metrics):
        audio_chunks.append(chunk)

    t_first_token_sent = metrics.get("t_first_token_sent")
    t_first_chunk = metrics.get("t_first_chunk")
    t_done = metrics.get("t_done")

    # tts_first_chunk_latency_ms is written directly by synthesize_streaming.
    tts_latency_ms = metrics.get("tts_first_chunk_latency_ms")

    # Fallback: if t_first_token_sent was never recorded (empty text edge case)
    # derive from t_connected so the metric is always defined.
    if tts_latency_ms is None and t_first_chunk is not None:
        t_dispatch = metrics.get("t_first_token_sent") or metrics.get("t_connected", t_first_chunk)
        tts_latency_ms = (t_first_chunk - t_dispatch) * 1000

    total_tts_ms = (
        (t_done - t_first_token_sent) * 1000
        if t_done and t_first_token_sent
        else 0.0
    )

    return {
        "mode": "optimized",
        "query": query,
        "shared_llm_text": frozen_text,
        "shared_llm_ms": llm_ms,
        # TTS-isolated timings (relative to t_first_token_sent = t_tts_dispatch)
        "t3_ms": tts_latency_ms or 0.0,      # headline metric doubles as t3 for opt path
        "tts_first_chunk_ms": tts_latency_ms or 0.0,
        "total_tts_ms": total_tts_ms,
        "audio_bytes": len(b"".join(audio_chunks)),
    }


# ---------------------------------------------------------------------------
# Benchmark loop
# ---------------------------------------------------------------------------

async def run_all_benchmarks():
    print("=" * 72)
    print("RIME HACKATHON BENCHMARK SUITE (LLM-variance-controlled)")
    print(f"Timestamp:    {datetime.now().isoformat()}")
    print(f"Rime Region:  {RIME_REGION} (users-{RIME_REGION}.rime.ai)")
    print(f"Rime Model:   {RIME_MODEL_ID} (Speaker: {RIME_SPEAKER})")
    print(f"Groq Model:   {GROQ_LLM_MODEL}")
    print(f"Queries:      {len(QUERIES)}")
    print(f"Method:       LLM generated ONCE per query; identical text fed to BOTH TTS paths.")
    print("=" * 72)

    results = []

    for idx, q in enumerate(QUERIES, 1):
        print(f"\n[{idx}/{len(QUERIES)}] Query: \"{q[:55]}...\"")

        # --- Step 0: Generate LLM text once ---
        print("  Generating LLM response (shared)...", end="", flush=True)
        frozen_text, llm_ms = await generate_llm_text(q)
        print(f" Done. {llm_ms:.0f} ms | {len(frozen_text.split())} words")
        print(f"  LLM text: \"{frozen_text[:70].rstrip()}{'...' if len(frozen_text) > 70 else ''}\"")

        await asyncio.sleep(0.5)  # brief cooldown before TTS calls

        # --- Step 1a: Naive TTS ---
        print("  Naive TTS (HTTP POST)...", end="", flush=True)
        naive_res = await run_naive_tts(q, frozen_text, llm_ms)
        print(
            f" Done. TTS TTFB: {naive_res['tts_first_chunk_ms']:.1f} ms"
            f" | Total TTS: {naive_res['total_tts_ms']:.1f} ms"
        )

        await asyncio.sleep(0.5)

        # --- Step 1b: Optimized TTS ---
        print("  Optimized TTS (Rime WS streaming)...", end="", flush=True)
        opt_res = await run_optimized_tts(q, frozen_text, llm_ms)
        print(
            f" Done. TTS_FIRST_CHUNK: {opt_res['tts_first_chunk_ms']:.1f} ms"
            f" | Total TTS: {opt_res['total_tts_ms']:.1f} ms"
        )

        # Per-query savings (TTS segment only — LLM already controlled out)
        tts_savings = naive_res["tts_first_chunk_ms"] - opt_res["tts_first_chunk_ms"]
        tts_pct = (tts_savings / naive_res["tts_first_chunk_ms"]) * 100 if naive_res["tts_first_chunk_ms"] else 0.0
        print(f"  --> TTS_FIRST_CHUNK_LATENCY reduction: {tts_savings:.1f} ms ({tts_pct:.1f}%)")

        # One record per query — pairing naive and optimized TTS on the identical frozen LLM text
        query_record = {
            "query_idx": idx,
            "query": q,
            "shared_llm_ms": llm_ms,
            "shared_llm_text": frozen_text,
            "naive_tts_first_chunk_ms": naive_res["tts_first_chunk_ms"],
            "opt_tts_first_chunk_ms": opt_res["tts_first_chunk_ms"],
            "tts_savings_ms": tts_savings,
            "tts_savings_pct": tts_pct,
            "naive_total_tts_ms": naive_res["total_tts_ms"],
            "opt_total_tts_ms": opt_res["total_tts_ms"],
            "naive_audio_bytes": naive_res["audio_bytes"],
            "opt_audio_bytes": opt_res["audio_bytes"],
        }
        results.append(query_record)

        await asyncio.sleep(1.0)  # rate-limit cooldown between queries

    save_csv(results)
    summarize_and_plot(results)


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def save_csv(records: list[dict]):
    """Write one row per query.
    shared_llm_text is logged once per query (not duplicated per mode).
    Both naive and optimized TTS measurements are recorded side-by-side.
    """
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["# Rime Hackathon Latency Benchmark (LLM-variance-controlled)"])
        writer.writerow([f"# Timestamp: {datetime.now().isoformat()}"])
        writer.writerow([f"# Rime Model: {RIME_MODEL_ID}, Speaker: {RIME_SPEAKER}, Region: {RIME_REGION}"])
        writer.writerow([f"# Groq Model: {GROQ_LLM_MODEL}"])
        writer.writerow([
            "# LLM text was generated ONCE per query and cached as plain text.",
            "# The identical frozen text was fed to both naive (HTTP) and optimized (WS) TTS paths.",
            "# tts_first_chunk_latency_ms isolates delivery mechanism (t_tts_dispatch -> t_first_chunk).",
            "# shared_llm_text is logged ONCE per query in the final column.",
        ])
        writer.writerow([])
        writer.writerow([
            "query_idx",
            "query",
            "shared_llm_ms",
            "naive_tts_first_chunk_ms",
            "opt_tts_first_chunk_ms",
            "tts_reduction_ms",
            "tts_reduction_pct",
            "naive_total_tts_ms",
            "opt_total_tts_ms",
            "naive_audio_bytes",
            "opt_audio_bytes",
            "shared_llm_text",
        ])
        for r in records:
            writer.writerow([
                r["query_idx"],
                r["query"],
                f"{r['shared_llm_ms']:.2f}",
                f"{r['naive_tts_first_chunk_ms']:.2f}",
                f"{r['opt_tts_first_chunk_ms']:.2f}",
                f"{r['tts_savings_ms']:.2f}",
                f"{r['tts_savings_pct']:.1f}%",
                f"{r['naive_total_tts_ms']:.2f}",
                f"{r['opt_total_tts_ms']:.2f}",
                r["naive_audio_bytes"],
                r["opt_audio_bytes"],
                r["shared_llm_text"].replace("\n", " "),
            ])
    print(f"\n[OK] Saved benchmark data to: {CSV_FILE}")


# ---------------------------------------------------------------------------
# Statistics + chart
# ---------------------------------------------------------------------------

def load_csv() -> list[dict]:
    """Load existing benchmark_results.csv records without re-running API calls."""
    records = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].startswith("#") or row[0] == "query_idx":
                continue
            records.append({
                "query_idx": int(row[0]),
                "query": row[1],
                "shared_llm_ms": float(row[2]),
                "naive_tts_first_chunk_ms": float(row[3]),
                "opt_tts_first_chunk_ms": float(row[4]),
                "tts_savings_ms": float(row[5]),
                "tts_savings_pct": float(row[6].rstrip("%")),
                "naive_total_tts_ms": float(row[7]),
                "opt_total_tts_ms": float(row[8]),
                "naive_audio_bytes": int(row[9]),
                "opt_audio_bytes": int(row[10]),
                "shared_llm_text": row[11],
            })
    return records


def summarize_and_plot(records: list[dict]):
    naive_tts = [r["naive_tts_first_chunk_ms"] for r in records]
    opt_tts   = [r["opt_tts_first_chunk_ms"] for r in records]

    naive_p50  = np.median(naive_tts)
    naive_p95  = np.percentile(naive_tts, 95)
    opt_p50    = np.median(opt_tts)
    opt_p95    = np.percentile(opt_tts, 95)
    p50_reduction = (naive_p50 - opt_p50) / naive_p50 * 100
    p95_reduction = (naive_p95 - opt_p95) / naive_p95 * 100

    print("\n" + "=" * 72)
    print("BENCHMARK SUMMARY — TTS_FIRST_CHUNK_LATENCY (LLM variance controlled)")
    print("=" * 72)
    print(f"  Metric:  t_tts_dispatch -> t_first_chunk  (delivery mechanism only)")
    print(f"  Naive HTTP POST:      P50 = {naive_p50:6.1f} ms | P95 = {naive_p95:6.1f} ms")
    print(f"  Rime WS Streaming:   P50 = {opt_p50:6.1f} ms | P95 = {opt_p95:6.1f} ms")
    print(f"  Reduction:           P50 = {p50_reduction:.1f}%    | P95 = {p95_reduction:.1f}%")
    print("=" * 72)

    # ---- Plot ----
    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor("#0b0f19")
    ax1.set_facecolor("#111827")
    ax2.set_facecolor("#111827")

    # Panel 1: P50 & P95 grouped bar
    categories = ["Median (P50)", "P95 Tail"]
    x = np.arange(len(categories))
    width = 0.35
    rects1 = ax1.bar(x - width/2, [naive_p50, naive_p95], width,
                     label="Naive (HTTP POST)", color="#ef4444", edgecolor="#fca5a5", alpha=0.9)
    rects2 = ax1.bar(x + width/2, [opt_p50, opt_p95], width,
                     label="Optimized (Rime WS Stream)", color="#38bdf8", edgecolor="#93c5fd", alpha=0.9)
    ax1.set_ylabel("TTS_FIRST_CHUNK_LATENCY (ms)", fontsize=11, color="#cbd5e1")
    ax1.set_title(
        "TTS First-Audio Latency (controlled: same LLM text)\n"
        "t_tts_dispatch → t_first_chunk  |  Lower is faster",
        fontsize=12, fontweight="bold", color="#f8fafc", pad=12,
    )
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories, fontsize=11, color="#cbd5e1")
    # Generous y-axis headroom prevents legend box from colliding with bar value labels
    ax1.set_ylim(0, max(naive_p95, opt_p95) * 1.35)
    ax1.legend(loc="upper right", framealpha=0.4, fontsize=9.5)
    ax1.grid(axis="y", linestyle="--", alpha=0.2)
    for rect, color in zip(list(rects1) + list(rects2), ["#fca5a5"]*2 + ["#93c5fd"]*2):
        h = rect.get_height()
        ax1.annotate(f"{h:.0f} ms",
                     xy=(rect.get_x() + rect.get_width() / 2, h),
                     xytext=(0, 4), textcoords="offset points",
                     ha="center", va="bottom", fontsize=10, fontweight="bold", color=color)

    # Panel 2: per-query line chart
    query_indices = np.arange(1, len(naive_tts) + 1)
    ax2.plot(query_indices, naive_tts, marker="o", linewidth=2.5,
             color="#ef4444", label="Naive HTTP POST")
    ax2.plot(query_indices, opt_tts, marker="s", linewidth=2.5,
             color="#38bdf8", label="Optimized Rime WS")
    ax2.set_xlabel("Query # (1–10)", fontsize=11, color="#cbd5e1")
    ax2.set_ylabel("TTS_FIRST_CHUNK_LATENCY (ms)", fontsize=11, color="#cbd5e1")
    ax2.set_title(
        "Per-Query Comparison (same LLM text, both paths)\n"
        "Shaded area = savings from Rime WS streaming",
        fontsize=12, fontweight="bold", color="#f8fafc", pad=12,
    )
    ax2.fill_between(query_indices, naive_tts, opt_tts,
                     where=[n > o for n, o in zip(naive_tts, opt_tts)],
                     alpha=0.15, color="#10b981", label="Savings")
    ax2.legend(framealpha=0.3)
    ax2.grid(True, linestyle="--", alpha=0.2)

    plt.suptitle(
        f"Rime TTS (mistv3, {RIME_SPEAKER}) — Controlled Latency Benchmark\n"
        f"LLM response generated once per query; identical text fed to both TTS paths.\n"
        f"P50 reduction: {p50_reduction:.1f}%   P95 reduction: {p95_reduction:.1f}%",
        fontsize=13, fontweight="bold", y=1.04, color="#f8fafc",
    )
    plt.tight_layout()
    plt.savefig(CHART_FILE, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"[OK] Generated benchmark chart at: {CHART_FILE}")


if __name__ == "__main__":
    if "--plot-only" in sys.argv:
        records = load_csv()
        summarize_and_plot(records)
    else:
        asyncio.run(run_all_benchmarks())
