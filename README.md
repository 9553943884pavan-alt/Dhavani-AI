# Voice Latency Engineering Demo — Rime Hackathon

**Track:** Rime Hackathon Challenge — Hard Voice Problem: **Perceived Response Time**  
**Active Speech Provider:** Rime (`mistv3`, speaker: `astra`)  
**LLM & STT Provider:** Groq LPU (`openai/gpt-oss-20b`, `whisper-large-v3-turbo`)  

> **Note on Active Model:** `backend/config.py` defaults to `os.getenv("GROQ_LLM_MODEL", "llama-3.1-8b-instant")`, but the active runtime environment uses `openai/gpt-oss-20b` (configured via `.env`) because Groq returns 404 for `llama-3.1-8b-instant` on this account tier. All empirical benchmarks and evidence files reflect `openai/gpt-oss-20b`.

---

## 1. The One-Sentence Claim

> Streaming LLM tokens directly into Rime's WebSocket API cuts TTS-stage first-audio latency by ≥50% (measured: **71.6% reduction**), and reduces overall end-to-end perceived response time by approximately **33–43%** (42.6% median reduction).

---

## 2. Target User & The Voice Latency Problem

### Target User
Emergency dispatch operators, hands-free field medical personnel, and real-time interactive voice agents where a human expects immediate conversational feedback.

### Why Voice is Essential
In mission-critical, eyes-busy, or hands-occupied situations (e.g. driving, surgical assistance, emergency triaging), visual screens are impractical or dangerous. Speech is the sole high-bandwidth interaction channel.

### Why Latency Breaks the Experience
Human conversational turn-taking happens naturally within **200–500 ms**. When a voice assistant pauses for 3–5 seconds before uttering the first syllable:
1. **False interruptions:** The user assumes the system failed to hear them and starts repeating themselves, colliding with the delayed response.
2. **Cognitive friction:** Natural flow is replaced with the anxiety of a stalled connection.
3. Traditional architectures buffer the full LLM response before initiating TTS, multiplying model generation latency with audio synthesis latency.

---

## 3. Architecture & Pipeline

### Pipeline Architecture

```
[User Speech] 
      │ (WebM Audio / Push-to-Talk)
      ▼
[Phase 1: STT] Groq Whisper Large v3 Turbo (T0 → T1)
      │
      ├───────────────────────────────┬──────────────────────────────┐
      │                               │                              │
      ▼ (Naive Baseline)              ▼ (Optimized Streaming)        │
[Phase 2: LLM Full Response]    [Phase 3: LLM Token Stream]          │
  Waits for full paragraph        Streams tokens via Groq LPU        │
  Measured: ~1,228 - 1,468 ms     Token stream begins                │
  (mean ~1,291 ms via benchmark)  T2 dispatch: 1,228 - 1,468 ms      │
      │                               │                              │
      ▼                               ▼ (Concurrent WebSocket pipe) │
[Phase 2: Rime HTTP TTS]        [Phase 4: Rime WS incremental]       │
  POST /v1/rime-tts               wss://users-east-ws.rime.ai/ws3    │
  Full audio generated            First audio chunk at T3            │
      │                               │                              │
      ▼                               ▼                              │
  T3 (Audible) ~ 2.5 - 3.3 s      T3 (Audible) ~ 1.6 - 2.3 s         │
  (Perceived Delay: HIGH)         (Perceived Delay: LOW)             │
```

> **Measured LLM Latency:** In live benchmarking across the 10 representative queries, total LLM generation time (`shared_llm_ms`) was empirically measured via `scripts/run_benchmark.py` at **1,227.7 ms – 1,467.7 ms** (mean **1,291.1 ms**). This measured range replaces earlier theoretical estimates.

### Exact Rime Configuration

| Parameter | Value |
|---|---|
| **Speech Provider** | **Rime AI** (`rime.ai`) |
| **Model ID** | `mistv3` (*explicitly specified on every request*) |
| **Speaker Voice** | `astra` |
| **Language** | `en` (English) |
| **Audio Format** | `mp3` |
| **HTTP Endpoint (Naive)** | `https://users-east.rime.ai/v1/rime-tts` |
| **WebSocket Endpoint (Optimized)** | `wss://users-east-ws.rime.ai/ws3?speaker=astra&modelId=mistv3&audioFormat=mp3` |
| **Transport** | HTTP streaming (`stream=True`) vs. Persistent WebSocket (`ws3` JSON protocol) |

---

## 4. Empirical Benchmark Results

Full repeatable benchmark methodology, CSV datasets, and query-by-query traces are documented in [RIME_EVIDENCE.md](RIME_EVIDENCE.md).

### Controlled Side-by-Side Results (10 Representative Queries)

| Metric | Naive Mode (HTTP Full Buffering) | Optimized Mode (Rime WS Token Streaming) | Absolute Reduction | Relative Improvement |
|---|---|---|---|---|
| **TTS First Audio Latency Median (P50)** | **1,688.6 ms** | **480.3 ms** | **1,208.3 ms** | **71.6% Reduction** ✅ |
| **TTS First Audio Latency P95 Tail** | **1,873.3 ms** | **746.9 ms** | **1,126.4 ms** | **60.1% Reduction** ✅ |
| **End-to-End TTFA Median (P50)** | **3,012.7 ms** | **1,730.3 ms** | **1,282.4 ms** | **42.6% Reduction** ✅ |
| **End-to-End TTFA P95 Tail** | **3,212.4 ms** | **2,144.7 ms** | **1,067.7 ms** | **33.2% Reduction** ✅ |

- **Isolated Delivery Mechanism:** LLM completions are generated and frozen once per query, feeding identical text to both TTS paths to eliminate sampling variance as a confound.
- **Visual Artifacts:** Generated chart saved to `benchmark_result.png`; raw data exported to `benchmark_results.csv`.

> **Note on End-to-End Metric Variance:** Across multiple live benchmark runs, the core lever—TTS-stage first-audio latency reduction—remains rock-solid at **~71.6%–71.7%**. In contrast, the composite end-to-end TTFA reduction naturally fluctuates between **38.5% and 42.6%**. This variation is driven by: (1) transatlantic public internet TCP/TLS handshake jitter on the un-warmed Naive HTTP POST connection (1,650–1,900 ms) versus persistent WebSocket stability (472–480 ms), and (2) LLM generation speed fluctuations shifting the ratio's denominator. Neither run uses precomputed or cached values.

---

## 5. Setup & Running Locally

### Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Rime API Key (`RIME_API_KEY`)
- Groq API Key (`GROQ_API_KEY`)

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd Claude_code
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and enter your actual RIME_API_KEY and GROQ_API_KEY
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Start the FastAPI application:**
   ```bash
   uvicorn backend.main:app --host 127.0.0.1 --port 8000
   ```

5. **Open the browser UI:**
   Navigate to `http://127.0.0.1:8000` to interact with the push-to-talk interface and view live latency telemetry.

---

## 6. Verification & Benchmark Scripts

Run each phase test script sequentially to verify individual components:

- **STT Verification (Phase 1):**
  ```bash
  python scripts/test_stt.py
  ```
- **Naive Rime TTS (Phase 2):**
  ```bash
  python scripts/test_tts_naive.py
  ```
- **LLM Streaming (Phase 3):**
  ```bash
  python scripts/test_llm_stream.py
  ```
- **Optimized Rime Streaming (Phase 4):**
  ```bash
  python scripts/test_tts_streaming.py
  ```
- **End-to-End WebSocket Pipeline (Phase 5):**
  ```bash
  python scripts/test_pipeline.py
  ```
- **Repeatable 10-Query Benchmark Suite (Phase 7):**
  ```bash
  python scripts/run_benchmark.py
  ```

---

## 7. Disclosed Limitations & Failure Behavior

### Disclosed Limitations
1. **Geographic Network RTT:** Testing was performed from India against Rime's `users-east` (us-east-1, Virginia) endpoint. Absolute latency includes ~180-250 ms TCP round-trip propagation times. In a US-deployed instance, absolute TTFA is significantly lower.
2. **Single Speaker Tested:** Benchmarks were standardized on `astra` with `mistv3` for rigorous comparison.
3. **Language Scope:** English (`en`).

### Failure Behavior & Error Handling
The codebase implements explicit handling for upstream API, transport, and client-level failures:

- **Groq Rate Limiting (429):** In `backend/llm.py`, `stream_completion()` detects 429 rate limit exceptions and performs exponential backoff retries (up to 3 attempts with wait intervals of $2^{\text{attempt}+1}$ seconds, i.e., 2s, 4s). If all retries fail or non-429 exceptions occur, the exception is raised.
- **Rime HTTP Failures (Naive Path):** In `backend/tts.py`, `synthesize_naive_sync()` issues `response.raise_for_status()`. Any non-200 HTTP response (such as 400 Bad Request or 500 Internal Server Error) raises `requests.exceptions.HTTPError`. In `backend/main.py`, this is caught by the pipeline handler and sent to the client as a WebSocket JSON message: `{"type": "error", "message": f"Pipeline error: {e}"}`.
- **Rime WebSocket Disconnects & Protocol Errors (Optimized Path):** In `backend/tts.py`, `synthesize_streaming()` raises a `RuntimeError` if Rime returns an `error` event, and catches network or connection drop exceptions in background sender and receiver tasks, forwarding the exception onto the audio queue. In `backend/main.py`, this is caught and relayed as `{"type": "error", "message": f"Pipeline error: {e}"}`.
- **Client-Side UI & Network Recovery:** In `frontend/app.js`, error events hide the streaming indicator, log the error to `console.error`, and alert the user. If the client WebSocket drops (`onclose`), it automatically attempts reconnection every 2 seconds (`setTimeout(initWebSocket, 2000)`).

---

## 8. Credits
- **TTS:** [Rime AI](https://rime.ai) — Mist v3 model
- **LLM & STT Acceleration:** [Groq](https://groq.com) LPU Inference Engine
