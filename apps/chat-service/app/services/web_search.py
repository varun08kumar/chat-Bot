"""Web search tool, backed by a self-hosted SearXNG instance.

Gives the chatbot a way to answer current-events questions ("today's score",
"latest news on X") that a model's training data can't cover — no
third-party search API key required, since SearXNG aggregates public search
engines itself. See infra/searxng/.
"""

from __future__ import annotations

import httpx
from llm_obs_shared.logging import get_logger

logger = get_logger(__name__)

# The OpenAI-style tool schema LiteLLM forwards to any provider that
# supports function calling (OpenAI, Anthropic, Gemini, Groq's tool-use
# models, ...).
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for current information - news, scores, prices, "
            "recent events, or anything else that may have happened after the "
            "model's training cutoff or that changes frequently. Returns a list of "
            "results with titles, URLs, and short snippets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
            },
            "required": ["query"],
        },
    },
}


class WebSearchError(Exception):
    pass


async def web_search(query: str, *, base_url: str, max_results: int = 5) -> list[dict[str, str]]:
    """Query SearXNG's JSON API and return the top results."""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base_url}/search",
                params={"q": query, "format": "json"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise WebSearchError(str(exc)) from exc

    results = []
    for item in data.get("results", [])[:max_results]:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": (item.get("content") or "")[:400],
            }
        )
    return results


async def image_search(query: str, *, base_url: str, max_results: int = 5) -> list[dict[str, str]]:
    """Query SearXNG's image category and return real photo URLs (not
    generated ones) - this is a distinct feature from image generation,
    used when the user wants an actual existing photo (e.g. of a real
    person, place, or thing), not a fabricated likeness."""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base_url}/search",
                params={"q": query, "format": "json", "categories": "images"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise WebSearchError(str(exc)) from exc

    results = []
    for item in data.get("results", [])[:max_results]:
        img_src = item.get("img_src")
        if not img_src:
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "page_url": item.get("url", ""),
                "img_src": img_src,
                "source": item.get("source", ""),
            }
        )
    return results


async def fetch_first_working_image(
    candidates: list[dict[str, str]]
) -> tuple[dict[str, str], bytes, str] | None:
    """Download the first candidate whose ``img_src`` actually loads, and
    return its bytes along with it.

    Search engines index plenty of dead/moved/hotlink-blocked images, so
    blindly handing back the top result's URL leaves the frontend looking at
    a broken image about as often as not - some sites' hotlink protection
    even lets a plain server-side fetch through while still blocking the
    browser's real cross-origin ``<img>`` request (keyed off ``Referer``).
    Downloading the bytes here and handing them back to embed directly (the
    same way generated images already work) sidesteps that class of failure
    entirely, since the browser never talks to the source site at all.
    """

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        for candidate in candidates:
            try:
                resp = await client.get(candidate["img_src"])
                content_type = resp.headers.get("content-type", "").split(";")[0]
                if resp.status_code == 200 and content_type.startswith("image/"):
                    return candidate, resp.content, content_type
            except httpx.HTTPError:
                continue
    return None


def format_results_for_model(results: list[dict[str, str]]) -> str:
    """Render search results as compact text for the tool response message."""

    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, start=1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)
