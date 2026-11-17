"""The search v2, C-10 (AD-I02, IA-081): the groups of the UX contract from the index of AD-I01 (``core.search_entries``).

One builder makes the private answer; the public one is its projection (``to_public``), so the two never disagree. While
the index has never been refreshed, every group says ``no_entregado`` (``AD-I01``) instead of failing: the route can be
deployed before the first ``scripts.search_index refresh``. ``GET /api/v1/search`` (the list of today) does not use this
module.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Any, Final

from fbi.api.cache import shared
from fbi.api.contracts.intelligence.base import Freshness, Missing
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.search import (
    KIND_GROUP,
    MatchPass,
    SearchFixtureHit,
    SearchHitV2Private,
    SearchIndexState,
    SearchSuggestion,
    SearchV2,
    SearchV2Private,
)
from fbi.api.repositories import Conn, Row
from fbi.api.repositories import search_v2 as repo
from fbi.core.clock import now

PER_GROUP: Final = 8
STALE_AFTER: Final = timedelta(days=7)
"""An index older than this is served with ``freshness.stale`` (``indice_antiguo``): the refresh is a script, not a job."""

PASSES: Final[dict[int, MatchPass]] = {0: "prefijo", 1: "palabras", 2: "trigramas"}
TEAM_KINDS: Final = ("team", "national_team")


def clean_query(raw: str) -> str:
    """Spaces collapsed and trimmed, at most 60 characters (the router already asks for 2 to 60)."""
    return re.sub(r"\s+", " ", raw).strip()[:60]


def _not_built(piece: str) -> dict[str, Any]:
    return {"items": [], "missing_reason": "no_entregado", "expected_piece": piece}


def _listing(items: list[Any]) -> dict[str, Any]:
    return {"items": items} if items else {"items": [], "missing_reason": "sin_resultados"}


def _hit(row: Row) -> SearchHitV2Private:
    return SearchHitV2Private(kind=row["kind"], id=int(row["entity_id"]), label=row["label"], sublabel=row["sublabel"] or "",
                              matched=row["matched_name"], alias_type=row["alias_type"], match=PASSES[int(row["pass"])],
                              score=round(min(1.0, max(0.0, float(row["score"]))), 4),
                              popularity=float(row["popularity"]), rank=round(float(row["rank"]), 4))


def _fixture(row: Row) -> SearchFixtureHit:
    return SearchFixtureHit(id=int(row["id"]), label=f"{row['home']} v {row['away']}", sublabel=row["competition"] or "",
                            kickoff_at=row["kickoff_at"], home_team_id=int(row["home_team_id"]),
                            away_team_id=int(row["away_team_id"]))


def _freshness(at: datetime, built: bool, indexed_at: datetime | None) -> Freshness:
    if not built:
        return Freshness(generated_at=at, stale=True, stale_reason="indice_sin_construir")
    if indexed_at is not None and at - indexed_at > STALE_AFTER:
        return Freshness(generated_at=at, stale=True, stale_reason="indice_antiguo")
    return Freshness(generated_at=at, stale=False)


def build(conn: Conn, q: str, per_group: int = PER_GROUP) -> SearchV2Private:
    """The private answer of C-10 for one query."""
    started = time.perf_counter()
    at = now()
    query = clean_query(q)
    state = repo.index_state(conn)
    built = bool(state and state["populated"])
    indexed_at: datetime | None = state["indexed_at"] if built and state else None
    groups: dict[str, Any]
    key: str | None = None
    if not built:
        groups = {g: _not_built("AD-I01") for g in (*KIND_GROUP.values(), "fixtures")}
        suggestions = _not_built("AD-I01")
    else:
        key = repo.search_key(conn, query)
        rows = repo.entities(conn, key, per_group) if key else []
        by_group: dict[str, list[SearchHitV2Private]] = {g: [] for g in KIND_GROUP.values()}
        for row in rows:
            by_group[KIND_GROUP[row["kind"]]].append(_hit(row))
        team_ids = [h.id for kind in TEAM_KINDS for h in by_group[KIND_GROUP[kind]]][:PER_GROUP]
        fixtures = [_fixture(r) for r in repo.fixtures(conn, team_ids, per_group)]
        groups = {g: _listing(hits) for g, hits in by_group.items()} | {"fixtures": _listing(fixtures)}
        close = [] if rows or not key else repo.suggestions(conn, key)
        suggestions = _listing([SearchSuggestion(text=r["matched_name"]) for r in close])
    groups["news"] = _not_built("AD-G01")
    index = SearchIndexState(
        built=built, indexed_at=indexed_at if indexed_at is not None else Missing(missing_reason="sin_datos"),
        rows_estimate=max(-1, int(state["rows_estimate"])) if state else -1, trigram_threshold=repo.TRIGRAM_THRESHOLD,
        popularity_weight=repo.POPULARITY_WEIGHT, elapsed_ms=int((time.perf_counter() - started) * 1000))
    return SearchV2Private.model_validate({
        "freshness": _freshness(at, built, indexed_at), "query": query, "normalized": key or "", "per_group": per_group,
        "groups": groups, "did_you_mean": suggestions, "index": index})


@shared(60)
def private_answer(conn: Conn, q: str, per_group: int = PER_GROUP) -> SearchV2Private:
    return build(conn, q, per_group)


def public_answer(conn: Conn, q: str, per_group: int = PER_GROUP) -> SearchV2:
    return to_public(private_answer(conn, q, per_group), SearchV2)
