"""``web_research``: what the AI layer may read from the web, with the dates provenance needs.

Backed by a search API that returns each result's publication date (Exa; see
``docs/research/AI_PROVIDER_SELECTION_2026.md`` section 2). It is OFF until the owner sets
``EXA_API_KEY`` - creating that account is the owner's decision (credentials), so without it
the tool says it is not configured and the rest of the layer works without web research.

Every result carries: url, title, publisher (the host), published_at (as the source states
it, or None), retrieved_at (now), and a snippet. A claim may cite only a URL returned here in
the same run (``fbi.analyst.provenance``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from fbi.core.env import environment

EXA_URL = "https://api.exa.ai/search"
MAX_RESULTS = 8


class SearchNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SearchResult:
    url: str
    title: str
    publisher: str
    published_at: str | None
    retrieved_at: str
    snippet: str

    def as_json(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "publisher": self.publisher,
                "published_at": self.published_at, "retrieved_at": self.retrieved_at, "snippet": self.snippet}


def configured() -> bool:
    return bool(environment().get("EXA_API_KEY"))


def search(query: str, *, at: datetime, days: int = 7, transport: httpx.BaseTransport | None = None
           ) -> list[SearchResult]:
    key = environment().get("EXA_API_KEY")
    if not key:
        raise SearchNotConfiguredError("web research is not configured (EXA_API_KEY unset: an owner decision)")
    since = at.timestamp() - days * 86400
    body = {"query": query[:300], "numResults": MAX_RESULTS, "type": "auto",
            "startPublishedDate": datetime.fromtimestamp(since, tz=at.tzinfo).isoformat(),
            "contents": {"text": {"maxCharacters": 600}}}
    with httpx.Client(timeout=20.0, transport=transport) as client:
        r = client.post(EXA_URL, headers={"x-api-key": key, "content-type": "application/json"}, json=body)
    if r.status_code != 200:
        raise RuntimeError(f"web research failed with HTTP {r.status_code}")
    out = []
    for item in (r.json().get("results") or [])[:MAX_RESULTS]:
        url = str(item.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        out.append(SearchResult(url, str(item.get("title") or "")[:200], urlparse(url).netloc,
                                item.get("publishedDate"), at.isoformat(), str(item.get("text") or "")[:600]))
    return out
