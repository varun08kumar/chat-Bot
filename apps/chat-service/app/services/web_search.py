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


def format_results_for_model(results: list[dict[str, str]]) -> str:
    """Render search results as compact text for the tool response message."""

    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, start=1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)
