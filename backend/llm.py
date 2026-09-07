"""
LLM streaming using Groq (Llama 3.1 8B Instant).
"""

import time
import asyncio
from typing import AsyncGenerator, Optional
from groq import AsyncGroq
from backend.config import GROQ_API_KEY, GROQ_LLM_MODEL


def _get_async_client() -> AsyncGroq:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set in environment or .env file.")
    return AsyncGroq(api_key=GROQ_API_KEY)


DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, conversational voice assistant. "
    "Keep responses concise, natural, and clear (1 to 2 sentences) for speech."
)


async def stream_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_retries: int = 3,
) -> AsyncGenerator[str, None]:
    """Stream LLM tokens for the given prompt.
    Yields individual token strings as they arrive.
    Includes retry/backoff handling for rate limits (429).
    """
    client = _get_async_client()
    sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    selected_model = model or GROQ_LLM_MODEL

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt},
    ]

    for attempt in range(max_retries):
        try:
            stream = await client.chat.completions.create(
                model=selected_model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=256,
            )
            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
            return

        except Exception as e:
            # Check for 429 rate limit
            is_rate_limit = "429" in str(e) or "rate_limit" in str(e).lower()
            if is_rate_limit and attempt < max_retries - 1:
                wait_seconds = 2 ** (attempt + 1)
                await asyncio.sleep(wait_seconds)
                continue
            raise


async def get_full_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[str, float]:
    """Non-streaming completion for naive pipeline baseline comparison.
    Returns (full_text, elapsed_ms).
    """
    client = _get_async_client()
    sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    selected_model = model or GROQ_LLM_MODEL

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt},
    ]

    for attempt in range(3):
        t0 = time.perf_counter()
        response = await client.chat.completions.create(
            model=selected_model,
            messages=messages,
            stream=False,
            temperature=0.7,
            max_tokens=384,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        text = response.choices[0].message.content or ""
        if text.strip():
            return text.strip(), elapsed_ms
        await asyncio.sleep(1.0)

    return text.strip(), elapsed_ms
