from __future__ import annotations

from fbi.api.contracts.search import SearchHit
from fbi.api.envelope import Envelope, listing
from fbi.api.repositories import Conn
from fbi.api.repositories import search as repo


def search(conn: Conn, q: str, limit: int) -> Envelope[list[SearchHit]]:
    rows = repo.search(conn, q, limit)
    hits = [SearchHit(type=r["type"], id=r["id"], label=r["label"], sublabel=r["sublabel"]) for r in rows]
    return listing(hits, empty_reason=f"Nothing matches {q!r}.")
