"""Re-run the TTS benchmark for one existing query without changing benchmark files."""

import argparse
import asyncio
import csv
import os
import sys
from typing import Any

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from backend.config import RIME_MODEL_ID, RIME_REGION, RIME_SPEAKER
from scripts.run_benchmark import run_naive_tts, run_optimized_tts


CSV_FILE = os.path.join(PROJECT_ROOT, "benchmark_results.csv")


def load_query_record(query_idx: int) -> dict[str, Any]:
    """Load one benchmark record, including its exact frozen LLM text."""
    matches = []
    with open(CSV_FILE, "r", newline="", encoding="utf-8") as csv_file:
        for row in csv.reader(csv_file):
            if not row or row[0].startswith("#") or row[0] == "query_idx":
                continue
            if len(row) < 12:
                continue
            if int(row[0]) == query_idx:
                matches.append(row)

    if not matches:
        raise ValueError(f"Query index {query_idx} was not found in {CSV_FILE}.")
    if len(matches) > 1:
        raise ValueError(f"Query index {query_idx} appears more than once in {CSV_FILE}.")

    row = matches[0]
    frozen_text = row[11]
    if not frozen_text.strip():
        raise ValueError(f"Query index {query_idx} has no shared_llm_text in {CSV_FILE}.")

    return {
        "query_idx": int(row[0]),
        "query": row[1],
        "shared_llm_ms": float(row[2]),
        "shared_llm_text": frozen_text,
    }


async def rerun_query(record: dict[str, Any]) -> None:
    """Run only the two TTS paths using the recorded text."""
    query = record["query"]
    frozen_text = record["shared_llm_text"]
    llm_ms = record["shared_llm_ms"]

    print("=" * 72)
    print(f"RERUN TTS BENCHMARK - QUERY {record['query_idx']}")
    print(f"Rime: {RIME_REGION} / {RIME_MODEL_ID} / {RIME_SPEAKER}")
    print(f"Query: {query}")
    print(f"Frozen text: {len(frozen_text)} characters, {len(frozen_text.split())} words")
    print("LLM: skipped; shared_llm_text loaded from benchmark_results.csv")
    print("CSV/chart writes: disabled")
    print("=" * 72)

    print("Naive TTS (HTTP POST)...", end="", flush=True)
    naive_result = await run_naive_tts(query, frozen_text, llm_ms)
    print(" done")

    print("Optimized TTS (Rime WS streaming)...", end="", flush=True)
    optimized_result = await run_optimized_tts(query, frozen_text, llm_ms)
    print(" done")

    naive_first = naive_result["tts_first_chunk_ms"]
    optimized_first = optimized_result["tts_first_chunk_ms"]
    savings_ms = naive_first - optimized_first
    savings_pct = savings_ms / naive_first * 100 if naive_first else 0.0

    print("\nResults")
    print(f"  Naive TTS first chunk:      {naive_first:.2f} ms")
    print(f"  Optimized TTS first chunk:  {optimized_first:.2f} ms")
    print(f"  TTS reduction:              {savings_ms:.2f} ms ({savings_pct:.1f}%)")
    print(f"  Naive total TTS:            {naive_result['total_tts_ms']:.2f} ms")
    print(f"  Optimized total TTS:        {optimized_result['total_tts_ms']:.2f} ms")
    print(f"  Naive audio bytes:          {naive_result['audio_bytes']}")
    print(f"  Optimized audio bytes:      {optimized_result['audio_bytes']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-run one frozen query's naive and optimized TTS benchmark."
    )
    parser.add_argument("query_idx", type=int, choices=range(1, 11), help="Query index (1-10)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    record = load_query_record(args.query_idx)
    asyncio.run(rerun_query(record))


if __name__ == "__main__":
    main()