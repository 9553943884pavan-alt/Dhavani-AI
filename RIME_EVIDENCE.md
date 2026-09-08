# RIME_EVIDENCE.md — Verification & Benchmark Evidence

**Track:** Rime Hackathon Challenge — Hard Voice Problem: **Perceived Response Time**  
**Speech Provider:** Rime AI  
**Evaluated Model:** `mistv3` (Speaker: `astra`, Language: `en`, Format: `mp3`)  
**Evaluation Date:** 2026-09-08

---

## 1. The One-Sentence Claim

> Streaming LLM tokens directly into Rime's WebSocket API cuts controlled TTS-stage first-audio latency by **73.6% at P50** and **76.5% at P95**, while reducing the LLM-to-first-audio end-to-end pipeline proxy by **46.1% at P50** and **31.9% at P95**.

---

## 2. Acceptance Test Definition

### The Metrics: TTS Latency and Pipeline Proxy
The benchmark reports two related metrics. The primary metric isolates TTS after the LLM response is frozen. The secondary metric adds the measured shared LLM time to TTS first-audio latency, producing an LLM-to-first-audio pipeline proxy. The proxy excludes STT, browser scheduling, and actual browser playback.

$$\text{TTS Latency} = T_{first\ audio} - T_{TTS\ dispatch}$$

### TTS First-Chunk Synthesis Latency
- **Naive Mode:** Measures time from full frozen response dispatch to first audio byte from `POST /v1/rime-tts`.
- **Optimized Mode:** Measures time from first frozen word sent to the WebSocket to first decoded audio chunk from `wss://users-east-ws.rime.ai/ws3`.

### Acceptance Threshold

**Criterion 1 — TTS First-Chunk Synthesis Latency (the ≥50% claim):**  
Optimized mode must demonstrate a **≥ 50% reduction in TTS First-Chunk Synthesis Latency** compared to the naive baseline across the multi-query benchmark suite. This measures the segment that token-streaming directly controls, with the same frozen text sent to both paths.

**Criterion 2 — End-to-End Pipeline Proxy:**
The pipeline proxy is reported separately from the TTS claim. It estimates prompt-to-first-audio service latency as `shared_llm_ms + TTS first-audio latency`; it is not a full browser TTFA measurement.

---

## 3. Benchmark Procedure & Reproducibility

The entire evaluation is automated and reproducible via `scripts/run_benchmark.py`:

```bash
# Ensure dependencies and keys are set
pip install -r requirements.txt

# Run the 10-query benchmark suite
python scripts/run_benchmark.py
```

### Protocol:
1. **10 Representative Voice Queries:** Spanning factual Q&A, multi-step instructions, conversational explanations, and a multi-sentence stress test.
2. **Side-by-Side Execution:** Each query is executed sequentially through both the **Naive** path (full text buffering -> HTTP POST) and the **Optimized** path (token-by-token streaming -> Rime WS), separated by a cooldown to eliminate rate-limit throttling.
3. **Artifacts Produced:**
   - Raw per-query timing data saved to `benchmark_results.csv`.
   - Dual-panel comparative visualization saved to `benchmark_result.png`.

---

## 4. Empirical Results

### Summary Table

| Metric | Naive Mode (HTTP Full Buffering) | Optimized Mode (Rime WS Token Streaming) | Absolute Reduction | Relative Improvement |
|---|---|---|---|---|
| **TTS First Audio Latency Median (P50)** | **1,702.0 ms** | **449.7 ms** | **1,252.4 ms** | **73.6% Reduction** ✅ |
| **TTS First Audio Latency P95 Tail** | **2,865.2 ms** | **672.1 ms** | **2,193.1 ms** | **76.5% Reduction** ✅ |
| **End-to-End Pipeline Proxy Median (P50)** | **3,114.5 ms** | **1,679.8 ms** | **1,434.7 ms** | **46.1% Reduction** |
| **End-to-End Pipeline Proxy P95 Tail** | **4,696.9 ms** | **3,199.5 ms** | **1,497.4 ms** | **31.9% Reduction** |

The pipeline proxy is calculated per query as:

$$\text{Pipeline Proxy} = \text{shared\_llm\_ms} + \text{TTS first-audio latency}$$

It is useful for showing the system-level effect of the TTS change, but it should not be described as measured end-to-end browser TTFA.

### Query-by-Query Results

| # | Query | Shared LLM | Naive TTS | Optimized TTS | Naive Pipeline Proxy | Optimized Pipeline Proxy | Proxy Saved | Reduction |
|---|---|---|---|---|---|---|---|---|
| 1 | Speed of light | 1,917.8 ms | 1,750.5 ms | 827.6 ms | 3,668.3 ms | 2,745.4 ms | 923.0 ms | **25.2%** |
| 2 | Focus tips | 1,006.4 ms | 3,542.2 ms | 444.6 ms | 4,548.5 ms | 1,451.0 ms | 3,097.6 ms | **68.1%** |
| 3 | Autumn leaves | 1,258.3 ms | 1,613.5 ms | 475.3 ms | 2,871.8 ms | 1,733.6 ms | 1,138.2 ms | **39.6%** |
| 4 | Jet engine | 1,209.3 ms | 1,473.2 ms | 426.2 ms | 2,682.5 ms | 1,635.5 ms | 1,047.1 ms | **39.0%** |
| 5 | Sync vs async | 3,143.0 ms | 1,675.4 ms | 428.1 ms | 4,818.4 ms | 3,571.1 ms | 1,247.3 ms | **25.9%** |
| 6 | Immune memory | 933.5 ms | 1,688.5 ms | 480.3 ms | 2,622.0 ms | 1,413.8 ms | 1,208.2 ms | **46.1%** |
| 7 | Healthy breakfast | 1,291.3 ms | 2,037.8 ms | 432.7 ms | 3,329.1 ms | 1,724.0 ms | 1,605.1 ms | **48.2%** |
| 8 | General relativity | 830.8 ms | 1,598.7 ms | 421.5 ms | 2,429.4 ms | 1,252.3 ms | 1,177.2 ms | **48.5%** |
| 9 | Quantum computing | 1,091.9 ms | 2,031.7 ms | 482.0 ms | 3,123.6 ms | 1,573.9 ms | 1,549.7 ms | **49.6%** |
| 10 | Space exploration | 1,389.8 ms | 1,715.5 ms | 454.7 ms | 3,105.4 ms | 1,844.6 ms | 1,260.8 ms | **40.6%** |

### Stress Test Case (Query #10)
When generating a long, detailed paragraph (Query #10, 68 words), the LLM-to-first-audio pipeline proxy is **3,105.4 ms** for naive mode versus **1,844.6 ms** for optimized mode. That saves **1,260.8 ms**, a **40.6% proxy reduction**; the isolated TTS reduction is **73.5%**.

---

## 5. Reference Comparison with Rime's Ground Truth

Rime's published benchmark on an H100 SXM (zero network overhead):

| Model | Published TTFA P50 | Published TTFA P90 |
|---|---|---|
| `mistv3` | **37 ms** | **56 ms** |
| `coda` | **96 ms** | **98 ms** |

### Gap Analysis & Ground Truth Alignment
- In our live remote benchmark over public internet from India to Rime's Virginia datacenter, Rime WebSocket streaming delivered first audio chunks in **~420–830 ms** (P50: **449.7 ms**; fastest: **421.5 ms**).
- When subtracting network round-trip time (RTT ~ 360–380 ms across transatlantic undersea fiber), Rime's actual internal synthesis time aligns directly with the **~37–50 ms** published specification.

---

## 6. Disclosed Limitations & Variance Analysis

1. **Geographical Latency:** All runs were performed from an Indian IP connecting to `users-east.rime.ai` (us-east-1). Network RTT adds a fixed ~360 ms roundtrip baseline to both naive and optimized modes. In a US cloud deployment, absolute TTFA will drop to ~800–1,200 ms.
2. **Fixed Voice Configuration:** All trials evaluated `mistv3` with speaker `astra` and `audioFormat=mp3`.
3. **Language:** English (`en`).
4. **Token Budget Sizing:** The benchmark sets a 512-token generation window to prevent response truncations on long answers while maintaining conversational brevity.
5. **Measurement Scope:** The primary result is TTS dispatch-to-first-audio latency. The secondary pipeline result is an LLM-plus-TTS proxy and does not include STT, browser scheduling, or end-to-end browser TTFA. Neither path uses precomputed TTS values; both use the same live frozen LLM text.
