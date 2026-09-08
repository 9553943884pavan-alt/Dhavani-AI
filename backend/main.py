"""
FastAPI application — voice latency demo.
Wires STT -> LLM -> Rime TTS (Naive or Optimized) into an end-to-end pipeline
with precise per-stage timestamp logging (T0, T1, T2, T3).
"""

import time
import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import (
    RIME_REGION,
    RIME_SPEAKER,
    RIME_MODEL_ID,
    RIME_HTTP_URL,
    RIME_WS_FULL_URL,
    GROQ_STT_MODEL,
    GROQ_LLM_MODEL,
    validate_configuration,
)
from backend.stt import transcribe_async
from backend.llm import stream_completion, get_full_completion
from backend.tts import synthesize_naive, synthesize_streaming

app = FastAPI(title="Rime Voice Latency Demo", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.on_event("startup")
async def validate_startup_configuration():
    validate_configuration()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": "Rime",
        "modelId": RIME_MODEL_ID,
        "speaker": RIME_SPEAKER,
        "region": RIME_REGION,
    }


@app.get("/api/config")
async def get_config():
    return {
        "rime": {
            "modelId": RIME_MODEL_ID,
            "speaker": RIME_SPEAKER,
            "region": RIME_REGION,
            "http_url": RIME_HTTP_URL,
            "ws_url": RIME_WS_FULL_URL,
        },
        "groq": {
            "stt_model": GROQ_STT_MODEL,
            "llm_model": GROQ_LLM_MODEL,
        },
    }


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


async def _process_pipeline(
    websocket: WebSocket,
    prompt_text: str | None,
    audio_bytes: bytes | None,
    mode: str,
):
    """Core end-to-end pipeline execution with T0 -> T3 timestamp logging."""
    t0 = time.perf_counter()

    # --- Phase 1: STT (if audio provided) ---
    if audio_bytes is not None:
        try:
            transcript, stt_ms = await transcribe_async(audio_bytes)
        except Exception as e:
            await websocket.send_json({"type": "error", "message": f"STT failed: {e}"})
            return
        t1 = time.perf_counter()
        await websocket.send_json({
            "type": "transcript",
            "text": transcript,
            "t1_ms": (t1 - t0) * 1000,
        })
    else:
        transcript = prompt_text or ""
        t1 = time.perf_counter()
        await websocket.send_json({
            "type": "transcript",
            "text": transcript,
            "t1_ms": 0.0,
        })

    if not transcript.strip():
        await websocket.send_json({
            "type": "error",
            "message": "No audible speech or empty text detected.",
        })
        return

    # --- Mode Branching: Naive vs Optimized ---
    if mode == "naive":
        # NAIVE: Wait for full LLM completion before calling TTS
        try:
            full_text, llm_ms = await get_full_completion(transcript)
            t2 = time.perf_counter()
            await websocket.send_json({
                "type": "llm_text",
                "text": full_text,
                "t2_ms": (t2 - t0) * 1000,
            })

            # Call Rime HTTP TTS (full clip)
            tts_audio, tts_timing = await synthesize_naive(full_text)
            t3 = time.perf_counter()

            # Send timing summary before audio
            timing_data = {
                "type": "timing",
                "mode": "naive",
                "t0": t0,
                "t1": t1,
                "t2": t2,
                "t3": t3,
                "t1_ms": (t1 - t0) * 1000,
                "t2_ms": (t2 - t0) * 1000,
                "t3_ms": (t3 - t0) * 1000,
                "total_ms": (t3 - t0) * 1000,
                "audio_bytes": len(tts_audio),
            }
            await websocket.send_json(timing_data)

            # Send full audio as binary message
            await websocket.send_bytes(tts_audio)
            await websocket.send_json({"type": "done"})

        except Exception as e:
            await websocket.send_json({"type": "error", "message": f"Pipeline error: {e}"})

    else:
        # OPTIMIZED: Stream LLM tokens directly into Rime WebSocket
        t2_holder = [None]
        t3_holder = [None]
        full_tokens = []
        tts_metrics = {}

        async def _token_pipe():
            try:
                async for token in stream_completion(transcript):
                    if t2_holder[0] is None:
                        t2_holder[0] = time.perf_counter()
                        await websocket.send_json({
                            "type": "t2",
                            "t2_ms": (t2_holder[0] - t0) * 1000,
                        })
                    full_tokens.append(token)
                    # Stream token delta to client UI
                    await websocket.send_json({"type": "llm_delta", "delta": token})
                    yield token
            except Exception as e:
                raise RuntimeError(f"LLM error: {e}") from e

        try:
            async for audio_chunk in synthesize_streaming(_token_pipe(), metrics=tts_metrics):
                if t3_holder[0] is None:
                    t3_holder[0] = time.perf_counter()
                    await websocket.send_json({
                        "type": "t3",
                        "t3_ms": (t3_holder[0] - t0) * 1000,
                        "ttfa_ms": (t3_holder[0] - t0) * 1000,
                    })

                # Stream audio chunk to client immediately for real-time playback
                await websocket.send_bytes(audio_chunk)

            t_end = time.perf_counter()
            t2 = t2_holder[0] or t1
            t3 = t3_holder[0] or t_end

            timing_data = {
                "type": "timing",
                "mode": "optimized",
                "t0": t0,
                "t1": t1,
                "t2": t2,
                "t3": t3,
                "t1_ms": (t1 - t0) * 1000,
                "t2_ms": (t2 - t0) * 1000,
                "t3_ms": (t3 - t0) * 1000,
                "total_ms": (t_end - t0) * 1000,
                "audio_bytes": tts_metrics.get("total_audio_bytes", 0),
                "full_text": "".join(full_tokens),
            }
            await websocket.send_json(timing_data)
            await websocket.send_json({"type": "done"})

        except Exception as e:
            await websocket.send_json({"type": "error", "message": f"Pipeline error: {e}"})


@app.websocket("/ws/voice")
async def voice_ws(websocket: WebSocket, mode: str = Query("optimized")):
    await websocket.accept()
    current_mode = mode

    try:
        while True:
            message = await websocket.receive()

            if "text" in message:
                data = json.loads(message["text"])
                msg_mode = data.get("mode", current_mode)

                if data.get("action") == "text":
                    await _process_pipeline(
                        websocket,
                        prompt_text=data.get("text"),
                        audio_bytes=None,
                        mode=msg_mode,
                    )
                elif data.get("action") == "set_mode":
                    current_mode = msg_mode
                    await websocket.send_json({"type": "mode_updated", "mode": current_mode})

            elif "bytes" in message:
                audio_bytes = message["bytes"]
                await _process_pipeline(
                    websocket,
                    prompt_text=None,
                    audio_bytes=audio_bytes,
                    mode=current_mode,
                )

    except (WebSocketDisconnect, RuntimeError):
        pass
