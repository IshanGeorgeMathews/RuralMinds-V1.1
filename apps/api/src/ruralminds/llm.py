"""Client for the local llama-server instances. Only 127.0.0.1 URLs from config."""

import json
from collections.abc import AsyncIterator

import httpx

from .config import settings

EMBED_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
# Read timeout is per chunk of the stream, so it bounds stalls, not total answer time.
CHAT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


async def embed(texts: list[str], client: httpx.AsyncClient | None = None) -> list[list[float]]:
    """Embed texts with bge-m3 (CLS pooling, set on the server). Order is preserved."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=EMBED_TIMEOUT)
    try:
        reply = await client.post(
            f"{settings.embed_url}/v1/embeddings", json={"input": texts, "model": "bge-m3"}
        )
        reply.raise_for_status()
        rows = sorted(reply.json()["data"], key=lambda row: row["index"])
        return [row["embedding"] for row in rows]
    finally:
        if own_client:
            await client.aclose()


async def count_tokens(text: str, client: httpx.AsyncClient) -> int:
    """Token count from the embedding server's tokenizer (used for chunk sizes)."""
    reply = await client.post(f"{settings.embed_url}/tokenize", json={"content": text})
    reply.raise_for_status()
    return len(reply.json()["tokens"])


async def chat_stream(
    messages: list[dict[str, str]], client: httpx.AsyncClient
) -> AsyncIterator[str]:
    """Stream answer text pieces from llama-server's OpenAI-compatible endpoint.

    Closing the generator closes the HTTP stream, and llama-server then stops generating,
    so a student who leaves does not keep a slot busy.
    """
    payload = {
        "messages": messages,
        "stream": True,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "cache_prompt": True,  # reuse the KV cache for the shared system-prompt prefix
    }
    url = f"{settings.llm_url}/v1/chat/completions"
    async with client.stream("POST", url, json=payload, timeout=CHAT_TIMEOUT) as reply:
        reply.raise_for_status()
        async for line in reply.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ")
            if data == "[DONE]":
                break
            choices = json.loads(data).get("choices") or []
            piece = choices[0].get("delta", {}).get("content") if choices else None
            if piece:
                yield piece
