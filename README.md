# Voice Latency Engineering Demo — Rime Hackathon

**Track:** Rime Hackathon Challenge — Hard Voice Problem: **Perceived Response Time**  
**Active Speech Provider:** Rime (`mistv3`, speaker: `astra`)  
**LLM & STT Provider:** Groq LPU (`openai/gpt-oss-20b`, `whisper-large-v3-turbo`)  

> **Note on Active Model:** `backend/config.py` defaults to `os.getenv("GROQ_LLM_MODEL", "llama-3.1-8b-instant")`, but the active runtime environment uses `openai/gpt-oss-20b` (configured via `.env`) because Groq returns 404 for `llama-3.1-8b-instant` on this account tier. All empirical benchmarks and evidence files reflect `openai/gpt-oss-20b`.

---

## 1. The One-Sentence Claim

> Streaming LLM tokens directly into Rime's WebSocket API cuts controlled TTS-stage first-audio latency by **73.6% at P50** and **76.5% at P95**.

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
  First audio from Rime ~ 1.5 - 3.5 s   First audio from Rime ~ 0.4 - 0.8 s │
  (Perceived Delay: HIGH)         (Perceived Delay: LOW)             │
```

> **Measured LLM Latency:** In the 2026-09-08 live benchmark, shared LLM generation time (`shared_llm_ms`) ranged from **830.8 ms to 3,143.0 ms**. The benchmark freezes each response before comparing the two TTS paths.

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
| **TTS First Audio Latency Median (P50)** | **1,702.0 ms** | **449.7 ms** | **1,252.4 ms** | **73.6% Reduction** ✅ |
| **TTS First Audio Latency P95 Tail** | **2,865.2 ms** | **672.1 ms** | **2,193.1 ms** | **76.5% Reduction** ✅ |

- **Isolated Delivery Mechanism:** LLM completions are generated and frozen once per query, feeding identical text to both TTS paths to eliminate sampling variance as a confound.
- **Scope:** This benchmark reports TTS dispatch-to-first-audio latency. It does not claim an end-to-end STT-to-audio measurement.
- **Visual Artifacts:** Generated chart saved to `benchmark_result.png`; raw data exported to `benchmark_results.csv`.

> **Note on measurement scope:** The current repeatable benchmark intentionally excludes STT and does not synthesize an end-to-end TTFA number. The reported values isolate the TTS delivery mechanism using identical frozen text.

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

- **Startup Configuration:** The FastAPI application validates `RIME_API_KEY` and `GROQ_API_KEY` during startup and fails loudly if either is missing. Lower-level clients retain defensive checks for direct script use.
- **Groq Rate Limiting (429):** In `backend/llm.py` and `backend/stt.py`, typed `RateLimitError` exceptions trigger exponential backoff retries (up to 3 attempts with wait intervals of $2^{\text{attempt}+1}$ seconds, i.e., 2s, 4s). If all retries fail or non-429 exceptions occur, the exception is raised.
- **Rime HTTP Failures (Naive Path):** In `backend/tts.py`, `synthesize_naive_sync()` issues `response.raise_for_status()`. Any non-200 HTTP response (such as 400 Bad Request or 500 Internal Server Error) raises `requests.exceptions.HTTPError`. In `backend/main.py`, this is caught by the pipeline handler and sent to the client as a WebSocket JSON message: `{"type": "error", "message": f"Pipeline error: {e}"}`.
- **Rime WebSocket Disconnects & Protocol Errors (Optimized Path):** In `backend/tts.py`, `synthesize_streaming()` raises if Rime returns an `error` event or closes before `done`; sender, receiver, and token tasks are cancelled and awaited on every exit path. In `backend/main.py`, this is caught and relayed as `{"type": "error", "message": f"Pipeline error: {e}"}`.
- **Duplicate Requests and Playback Errors:** The frontend blocks new submissions while a response is generating or playing, revokes audio blob URLs on success, error, interruption, and rejected playback, and attempts to play partial audio when the server reports a stream error after audio has arrived.
- **Client-Side UI & Network Recovery:** In `frontend/app.js`, error events hide the streaming indicator, log the error to `console.error`, and alert the user. If the client WebSocket drops (`onclose`), it automatically attempts reconnection every 2 seconds (`setTimeout(initWebSocket, 2000)`).

---

## 8. Credits
- **TTS:** [Rime AI](https://rime.ai) — Mist v3 model
- **LLM & STT Acceleration:** [Groq](https://groq.com) LPU Inference Engine
