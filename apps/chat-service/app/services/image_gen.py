"""Image generation, backed by Pollinations.ai.

Pollinations is a free, keyless text-to-image API: a plain GET request
returns the generated image's raw bytes directly (no JSON envelope, no
auth) - so unlike xAI/OpenAI-style providers, this needs no API key at all.
"""

from __future__ import annotations

import base64
from urllib.parse import quote

import httpx

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"


class ImageGenError(Exception):
    pass


async def generate_image(prompt: str) -> str:
    """Generate an image and return it as a ``data:`` URI (base64)."""

    url = POLLINATIONS_URL.format(prompt=quote(prompt))
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url, params={"nologo": "true"})
            resp.raise_for_status()
            image_bytes = resp.content
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    except httpx.HTTPError as exc:
        raise ImageGenError(str(exc)) from exc

    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{b64}"
