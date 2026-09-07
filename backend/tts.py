"""
Text-to-Speech using Rime.
Two paths:
  - synthesize_naive: HTTP POST, full text upfront (baseline)
  - synthesize_streaming: WebSocket, incremental tokens (optimized)

Latency measurement convention (shared by both paths so comparisons are apples-to-apples):

  TTS_FIRST_CHUNK_LATENCY = t_first_chunk - t_tts_dispatch

  Where:
    t_tts_dispatch  = the instant the TTS system receives its first real input
                      (naive:     the moment requests.post() is called with the full text)
                      (streaming: the moment ws.send() returns after writing the FIRST token)
    t_first_chunk   = the instant the first decoded audio byte is received from Rime
                      (naive:     first iter_content chunk != b'')
                      (streaming: first "chunk" event decoded from the WebSocket)

  This isolates the Rime synthesis segment from LLM generation time, network connect
  time, and STT time — matching the definition used in RIME_EVIDENCE.md.
"""

import time
import json
import base64
import asyncio
from typing import AsyncGenerator, Optional
import requests
import websockets

from backend.config import (
    RIME_API_KEY,
    RIME_HTTP_URL,
    RIME_WS_FULL_URL,
    RIME_MODEL_ID,
    RIME_SPEAKER,
    RIME_LANG,
)


def synthesize_naive_sync(text: str) -> tuple[bytes, dict]:
    """Naive TTS: send full text via HTTP streaming, return (audio_bytes, timing_dict).

    LATENCY SEGMENT MEASURED (comparable to synthesize_streaming's t_tts_dispatch → t_first_chunk):
      ttfb_ms = t_first_chunk - t_request_start
      - t_request_start : captured immediately BEFORE requests.post() is called.
                          This is the moment the full LLM response text is dispatched to Rime's
                          HTTP endpoint. Equivalent to t_tts_dispatch in the streaming path.
      - t_first_chunk   : captured when the first non-empty bytes arrive from iter_content().
                          This is the moment Rime has synthesised enough audio for the first
                          network packet — the first audible data the client can play.

    timing_dict keys:
      - t_request_start : (float) perf_counter value at HTTP dispatch
      - t_first_chunk   : (float) perf_counter value at first audio bytes received
      - t_complete      : (float) perf_counter value when full stream has finished
      - ttfb_ms         : (float) TTS_FIRST_CHUNK_LATENCY in milliseconds  ← the headline metric
      - total_ms        : (float) total time from dispatch to full clip downloaded
    """
    if not RIME_API_KEY:
        raise ValueError("RIME_API_KEY is not set in environment or .env file.")

    headers = {
        "Authorization": f"Bearer {RIME_API_KEY}",
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text.strip() or "...",
        "modelId": RIME_MODEL_ID,
        "speaker": RIME_SPEAKER,
        "lang": RIME_LANG,
    }

    chunks = []

    # t_request_start — START of TTS_FIRST_CHUNK_LATENCY for naive mode.
    # Captured immediately before the HTTP request is dispatched, so any
    # connection setup overhead is included (matches the "dispatch" instant).
    t_start = time.perf_counter()  # t_tts_dispatch (naive)

    t_first_chunk = None

    with requests.post(
        RIME_HTTP_URL,
        headers=headers,
        json=payload,
        stream=True,
        timeout=30,
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=4096):
            if chunk:
                if t_first_chunk is None:
                    # t_first_chunk — END of TTS_FIRST_CHUNK_LATENCY for naive mode.
                    # First non-empty bytes from Rime: the earliest moment the client
                    # could begin audio playback. This is what we compare against
                    # synthesize_streaming's t_first_chunk.
                    t_first_chunk = time.perf_counter()
                chunks.append(chunk)

    t_end = time.perf_counter()  # Full clip downloaded; not used in the headline metric.
    if t_first_chunk is None:
        t_first_chunk = t_end  # Safeguard: should never happen on a successful call.

    timing = {
        "t_request_start": t_start,       # t_tts_dispatch (naive)
        "t_first_chunk": t_first_chunk,   # First audible bytes from Rime
        "t_complete": t_end,              # Full audio clip received
        # ttfb_ms is TTS_FIRST_CHUNK_LATENCY — the headline comparison metric.
        "ttfb_ms": (t_first_chunk - t_start) * 1000,
        "total_ms": (t_end - t_start) * 1000,
    }

    return b"".join(chunks), timing


async def synthesize_naive(text: str) -> tuple[bytes, dict]:
    """Async wrapper around synthesize_naive_sync."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, synthesize_naive_sync, text)


async def synthesize_streaming(
    text_generator: AsyncGenerator[str, None],
    metrics: Optional[dict] = None,
) -> AsyncGenerator[bytes, None]:
    """Streaming TTS: feed LLM tokens incrementally into Rime WebSocket, yield audio chunks.

    Starts pulling LLM tokens concurrently while the WebSocket connection is handshaking
    to ensure zero pipeline stall.

    LATENCY SEGMENT MEASURED (identical definition to synthesize_naive_sync's ttfb_ms):
      tts_first_chunk_latency_ms = t_first_chunk - t_first_token_sent

      - t_first_token_sent : captured immediately AFTER ws.send() returns for the FIRST token.
                             This is the moment Rime's server has received the first piece of
                             text to synthesise — the streaming equivalent of t_request_start
                             in the naive path (both mark "the instant Rime gets its first real
                             input"). EOS is NOT used as the start-event; doing so would conflate
                             LLM generation time with TTS synthesis time.
      - t_first_chunk      : captured when the first "chunk" WebSocket event is decoded and the
                             first audio bytes are available — identical in meaning to t_first_chunk
                             in the naive path.

    metrics dict keys populated (when metrics is not None):
      - t_connect_start              : perf_counter before websockets.connect() is called
      - t_connected                  : perf_counter after WebSocket handshake completes
      - ws_connect_ms                : handshake duration (not part of the headline metric)
      - t_first_token_sent           : perf_counter after ws.send() for the first token
                                       ← t_tts_dispatch (streaming) — START of headline metric
      - t_last_token_sent            : perf_counter after ws.send() for the last token
      - t_first_chunk                : perf_counter when first "chunk" event decoded
                                       ← END of headline metric
      - tts_first_chunk_latency_ms   : (t_first_chunk - t_first_token_sent) * 1000
                                       ← TTS_FIRST_CHUNK_LATENCY — the headline comparison metric
      - t_done                       : perf_counter when "done" event received
      - total_audio_bytes            : total decoded audio bytes received
      - total_chunks                 : number of "chunk" events received
    """
    if not RIME_API_KEY:
        raise ValueError("RIME_API_KEY is not set in environment or .env file.")

    headers = {"Authorization": f"Bearer {RIME_API_KEY}"}
    audio_queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()
    token_queue: asyncio.Queue[str | None] = asyncio.Queue()

    # t_connect_start — before WS handshake. Not part of TTS_FIRST_CHUNK_LATENCY;
    # recorded separately so ws_connect_ms can be reported as overhead context.
    t_connect_start = time.perf_counter()
    if metrics is not None:
        metrics["t_connect_start"] = t_connect_start

    # Concurrently pull LLM tokens into a buffer while WebSocket is connecting,
    # so the first token is ready to send the instant the handshake completes.
    async def _token_consumer():
        try:
            async for token in text_generator:
                if token:
                    await token_queue.put(token)
        finally:
            await token_queue.put(None)  # Sentinel — signals _sender to send EOS.

    token_pull_task = asyncio.create_task(_token_consumer())

    async with websockets.connect(
        RIME_WS_FULL_URL,
        additional_headers=headers,
        ping_interval=20,
        ping_timeout=20,
    ) as ws:
        # t_connected — after WS handshake. ws_connect_ms = t_connected - t_connect_start.
        # This is NOT t_tts_dispatch; Rime hasn't received any text yet.
        t_connected = time.perf_counter()
        if metrics is not None:
            metrics["t_connected"] = t_connected
            metrics["ws_connect_ms"] = (t_connected - t_connect_start) * 1000

        # _sender: drains token_queue and writes each token to the Rime WebSocket.
        # After all tokens are sent it fires the EOS signal.
        async def _sender():
            try:
                first_token = True
                while True:
                    token = await token_queue.get()
                    if token is None:
                        # All tokens consumed — send EOS to trigger final synthesis flush.
                        # NOTE: we do NOT record t_tts_dispatch here; EOS is the end of
                        # input, not the start. The start-event was already recorded after
                        # the first token was sent.
                        if metrics is not None:
                            metrics["t_last_token_sent"] = time.perf_counter()
                        await ws.send(json.dumps({"operation": "eos"}))
                        break

                    await ws.send(json.dumps({"text": token}))

                    if first_token:
                        # t_first_token_sent — START of TTS_FIRST_CHUNK_LATENCY (streaming).
                        # Captured AFTER ws.send() returns for the very first token, meaning
                        # Rime's server has now received its first piece of text to synthesise.
                        # This is the streaming equivalent of t_request_start in the naive path.
                        # Using post-send ensures the network write is included, matching how
                        # t_request_start captures the full dispatch instant in naive mode.
                        if metrics is not None:
                            metrics["t_first_token_sent"] = time.perf_counter()
                        first_token = False

            except Exception as exc:
                await audio_queue.put(exc)

        # _receiver: reads events from Rime WS, decodes audio chunks, pushes to audio_queue.
        async def _receiver():
            try:
                first_audio = True
                total_bytes = 0
                total_chunks = 0
                async for message in ws:
                    event = json.loads(message)
                    event_type = event.get("type")

                    if event_type == "chunk":
                        raw_data = event.get("data", "")
                        audio_bytes = base64.b64decode(raw_data)

                        # t_first_chunk — END of TTS_FIRST_CHUNK_LATENCY (streaming).
                        # Captured when the first "chunk" event arrives and is decoded.
                        # Identical in meaning to t_first_chunk in the naive path:
                        # the earliest moment the client has audio bytes to play.
                        now = time.perf_counter()
                        total_bytes += len(audio_bytes)
                        total_chunks += 1

                        if first_audio and metrics is not None:
                            metrics["t_first_chunk"] = now
                            # TTS_FIRST_CHUNK_LATENCY — the headline comparison metric.
                            # t_first_token_sent is the streaming t_tts_dispatch; if for any
                            # reason it wasn't set (e.g. the generator yielded nothing), fall
                            # back to t_connected so the metric is always defined.
                            t_dispatch = metrics.get("t_first_token_sent", t_connected)
                            metrics["tts_first_chunk_latency_ms"] = (now - t_dispatch) * 1000
                            first_audio = False

                        await audio_queue.put(audio_bytes)

                    elif event_type == "timestamps":
                        pass  # Word-level timing data; not needed for latency comparison.

                    elif event_type == "done":
                        if metrics is not None:
                            metrics["t_done"] = time.perf_counter()
                            metrics["total_audio_bytes"] = total_bytes
                            metrics["total_chunks"] = total_chunks
                        break

                    elif event_type == "error":
                        raise RuntimeError(f"Rime WebSocket error: {event}")

            except Exception as exc:
                await audio_queue.put(exc)
            finally:
                await audio_queue.put(None)  # Sentinel — signals the consumer loop to stop.

        sender_task = asyncio.create_task(_sender())
        receiver_task = asyncio.create_task(_receiver())

        try:
            while True:
                item = await audio_queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            await token_pull_task
            await sender_task
            await receiver_task
