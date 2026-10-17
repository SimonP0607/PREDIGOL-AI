"""What the planner reads from the database: stored fixtures and provider coverage."""

from __future__ import annotations

import psycopg
from psycopg.rows import tuple_row

from fbi.providers.api_football.details import COVERAGE_FLAGS


class DatabaseFacts:
    """Loads everything once; the planner asks per (league, season)."""

    def __init__(self, conn: psycopg.Connection) -> None:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT c.provider_league_id, cs.season, count(*) FROM core.fixtures f "
                "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
                "JOIN core.competitions c ON c.id = cs.competition_id "
                "JOIN core.fixture_results r ON r.fixture_id = f.id "
                "WHERE f.status_group = 'finished' GROUP BY 1, 2"
            )
            self._stored = {(int(a), int(b)): int(n) for a, b, n in cur.fetchall()}
            cur.execute(f"SELECT provider_league_id, season, league_name, country, {', '.join(COVERAGE_FLAGS)} "
                        "FROM raw.league_coverage WHERE provider = 'api_football' ORDER BY observed_at")
            self._coverage: dict[tuple[int, int], dict[str, bool | None]] = {}
            self._listed: dict[int, set[int]] = {}
            self._names: dict[int, tuple[str | None, str | None]] = {}
            for row in cur.fetchall():
                league, season, name, country, *flags = row
                self._coverage[(int(league), int(season))] = dict(zip(COVERAGE_FLAGS, flags, strict=True))
                self._listed.setdefault(int(league), set()).add(int(season))
                self._names[int(league)] = (name, country)

    def stored_fixtures(self, league_id: int, season: int) -> int:
        return self._stored.get((league_id, season), 0)

    def coverage(self, league_id: int, season: int) -> dict[str, bool | None] | None:
        return self._coverage.get((league_id, season))

    def seasons_listed(self, league_id: int) -> set[int] | None:
        return self._listed.get(league_id)

    def provider_name(self, league_id: int) -> tuple[str | None, str | None] | None:
        """(league name, country) as the provider's /leagues answer gave them, if stored."""
        return self._names.get(league_id)


def _norm(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def name_mismatches(facts: DatabaseFacts, configured: dict[int, str]) -> list[tuple[int, str, str]]:
    """(league id, configured name, provider name) where the provider's name shares
    neither containment nor a word with ours - a wrong id, most likely. An id the
    provider has not described yet is not listed (nothing to compare)."""
    out = []
    for lid, name in sorted(configured.items()):
        known = facts.provider_name(lid)
        if known is None or not known[0]:
            continue
        mine, theirs = _norm(name.split("(")[0]), _norm(known[0])
        words = {w for w in name.casefold().replace("(", " ").replace(")", " ").split() if len(w) > 2}
        if mine in theirs or theirs in mine or any(w in known[0].casefold() for w in words):
            continue
        out.append((lid, name, f"{known[0]} ({known[1] or '?'})"))
    return out
