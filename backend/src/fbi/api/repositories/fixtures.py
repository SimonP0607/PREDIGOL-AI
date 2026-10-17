"""Fixtures with everything a list row or a Match Center needs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one, fetch_value


@dataclass(frozen=True, slots=True)
class FixtureFilter:
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = None
    competition_id: int | None = None
    team_id: int | None = None
    fixture_ids: list[int] | None = None
    kickoff_after: datetime | None = None
    kickoff_before: datetime | None = None

    def params(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from, "date_to": self.date_to, "status": self.status,
            "competition_id": self.competition_id, "team_id": self.team_id,
            "fixture_ids": self.fixture_ids, "after": self.kickoff_after, "before": self.kickoff_before,
        }


_WHERE = """
    (%(date_from)s::date IS NULL OR f.kickoff_at >= %(date_from)s::date)
    AND (%(date_to)s::date IS NULL OR f.kickoff_at < (%(date_to)s::date + 1))
    AND (%(status)s::text IS NULL OR f.status_group = %(status)s::text)
    AND (%(competition_id)s::bigint IS NULL OR cs.competition_id = %(competition_id)s::bigint)
    AND (%(team_id)s::bigint IS NULL OR f.home_team_id = %(team_id)s::bigint OR f.away_team_id = %(team_id)s::bigint)
    AND (%(fixture_ids)s::bigint[] IS NULL OR f.id = ANY(%(fixture_ids)s::bigint[]))
    AND (%(after)s::timestamptz IS NULL OR f.kickoff_at >= %(after)s::timestamptz)
    AND (%(before)s::timestamptz IS NULL OR f.kickoff_at < %(before)s::timestamptz)
"""

_SELECT = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at, f.status_short, f.status_group, f.round,
       f.created_at, f.updated_at, f.source_payload_hash, f.source_fetched_at, f.venue_id, f.venue_name,
       f.venue_city,
       c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.provider_league_id, c.competition_type, c.is_tracked, cs.season,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag, c.country_code AS competition_country_code,
       th.id AS home_id, th.name AS home_name, th.provider_team_id AS home_provider_id, th.logo_url AS home_logo,
       ta.id AS away_id, ta.name AS away_name, ta.provider_team_id AS away_provider_id, ta.logo_url AS away_logo,
       r.goals_home, r.goals_away, r.ht_goals_home, r.ht_goals_away, r.et_goals_home, r.et_goals_away,
       r.pen_home, r.pen_away, r.outcome_1x2, r.total_goals, r.btts,
       r.source_payload_hash AS result_payload_hash, r.source_fetched_at AS result_fetched_at,
       COALESCE(o.snapshots, 0) AS odds_snapshots, COALESCE(o.bookmakers, 0) AS odds_bookmakers,
       COALESCE(o.markets, 0) AS odds_markets, o.first_at AS odds_first_at, o.last_at AS odds_last_at,
       COALESCE(n.near_close, 0) AS near_close_snapshots, COALESCE(p.predictions, 0) AS predictions
FROM page
JOIN core.fixtures f ON f.id = page.id
JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
JOIN core.competitions c ON c.id = cs.competition_id
JOIN core.teams th ON th.id = f.home_team_id
JOIN core.teams ta ON ta.id = f.away_team_id
LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
LEFT JOIN LATERAL (
    SELECT count(*) AS snapshots, count(DISTINCT bookmaker_id) AS bookmakers,
           count(DISTINCT market_key) AS markets, min(captured_at) AS first_at, max(captured_at) AS last_at
    FROM market.odds_snapshots o WHERE o.fixture_id = f.id
) o ON true
LEFT JOIN LATERAL (SELECT count(*) AS near_close FROM market.near_close_snapshots n WHERE n.fixture_id = f.id) n ON true
LEFT JOIN LATERAL (SELECT count(*) AS predictions FROM models.predictions p WHERE p.fixture_id = f.id) p ON true
"""

_PAGE_ASC = (
    "WITH page AS (SELECT f.id, f.kickoff_at FROM core.fixtures f "
    "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id WHERE " + _WHERE +
    " ORDER BY f.kickoff_at ASC, f.id ASC LIMIT %(limit)s OFFSET %(offset)s) " + _SELECT +
    " ORDER BY f.kickoff_at ASC, f.id ASC"
)
_PAGE_DESC = (
    "WITH page AS (SELECT f.id, f.kickoff_at FROM core.fixtures f "
    "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id WHERE " + _WHERE +
    " ORDER BY f.kickoff_at DESC, f.id DESC LIMIT %(limit)s OFFSET %(offset)s) " + _SELECT +
    " ORDER BY f.kickoff_at DESC, f.id DESC"
)
_COUNT = (
    "SELECT count(*) AS n FROM core.fixtures f "
    "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id WHERE " + _WHERE
)


def list_fixtures(
    conn: Conn, flt: FixtureFilter, *, limit: int, offset: int, order: Literal["asc", "desc"]
) -> tuple[list[Row], int]:
    params = {**flt.params(), "limit": limit, "offset": offset}
    rows = fetch_all(conn, _PAGE_ASC if order == "asc" else _PAGE_DESC, params)
    total = int(fetch_value(conn, _COUNT, flt.params()) or 0)
    return rows, total


def get_fixture(conn: Conn, fixture_id: int) -> Row | None:
    rows, _ = list_fixtures(conn, FixtureFilter(fixture_ids=[fixture_id]), limit=1, offset=0, order="asc")
    return rows[0] if rows else None


def get_lineage(conn: Conn, payload_hash: str) -> Row | None:
    return fetch_one(
        conn,
        "SELECT p.endpoint, p.params, p.fetched_at, p.run_id, r.job_type "
        "FROM raw.ingestion_payloads p LEFT JOIN raw.ingestion_runs r ON r.id = p.run_id WHERE p.hash = %s",
        (payload_hash,),
    )


def get_venue(conn: Conn, venue_id: int) -> Row | None:
    return fetch_one(conn, "SELECT id, name, city, country, capacity, surface, address, image_url FROM core.venues "
                           "WHERE id = %s", (venue_id,))


GENERIC_PLACE_WORDS = frozenset({
    "estadio", "estadi", "estadium", "stadium", "stadio", "stade", "stadion", "stadionul", "stadyumu", "stadyum",
    "arena", "park", "campo", "field", "ground", "municipal", "sports", "sport", "complex", "centre", "center",
    "de", "del", "la", "el", "los", "las", "do", "da", "dos", "das", "di", "the", "of", "y", "e", "and",
})
"""Words that name the kind of place, not which one: 'Estadio Diego Armando Maradona' and 'Diego Armando Maradona'
are one ground, 'Estadio Banorte' and 'Estadio Azteca' are not said to be (a rename is not guessed)."""


def _place_words(x: object) -> frozenset[str]:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.split(r"[^a-z0-9]+", text) if w and w not in GENERIC_PLACE_WORDS)


def _same_place(a: object, b: object) -> bool:
    """Two spellings of one ground: case, accents, punctuation and the generic words aside, the distinctive words of
    the shorter name all appear in the longer ('Estadio Marcelo Bielsa' / 'Estadio Marcelo Alberto Bielsa')."""
    wa, wb = _place_words(a), _place_words(b)
    if not wa or not wb:
        return False
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return short <= long_


def fixture_venue(conn: Conn, row: Row) -> Row | None:
    """The match's venue AS ITS PAYLOAD NAMES IT, with the venue's details (capacity, surface...) only when the venue
    the provider's id points at is that same ground. The id alone is not enough: the provider keeps a club's venue
    id for a home match played elsewhere (Milan v Como at Optus Stadium, Perth, carries San Siro's id) and uses one
    venue id for different grounds. A fixture with no name of its own falls back to the identified venue."""
    venue = get_venue(conn, int(row["venue_id"])) if row.get("venue_id") else None
    if not row.get("venue_name"):
        return venue
    if venue is not None and _same_place(venue["name"], row["venue_name"]):
        return {**venue, "name": row["venue_name"], "city": row.get("venue_city") or venue.get("city")}
    return {"id": None, "name": row["venue_name"], "city": row.get("venue_city")}


def latest_quotes(conn: Conn, fixture_id: int) -> list[Row]:
    """Latest price per bookmaker/market/selection/line."""
    return fetch_all(
        conn,
        """
        SELECT DISTINCT ON (o.bookmaker_id, o.market_key, o.selection, o.line)
               o.bookmaker_id, b.name AS bookmaker, o.market_key, o.selection, o.line, o.odds_decimal,
               o.captured_at, o.minutes_to_ko, o.source, o.payload_hash
        FROM market.odds_snapshots o JOIN market.bookmakers b ON b.id = o.bookmaker_id
        WHERE o.fixture_id = %s
        ORDER BY o.bookmaker_id, o.market_key, o.selection, o.line, o.captured_at DESC
        """,
        (fixture_id,),
    )


def capture_instants(conn: Conn, fixture_id: int) -> list[Row]:
    """One row per capture: when, how far from kick-off, from which feed."""
    return fetch_all(
        conn,
        "SELECT captured_at, min(minutes_to_ko) AS minutes_to_ko, source, count(*) AS quotes "
        "FROM market.odds_snapshots WHERE fixture_id = %s GROUP BY captured_at, source ORDER BY captured_at",
        (fixture_id,),
    )


def odds_asks(conn: Conn, provider_fixture_id: int) -> list[Row]:
    """Every pre-match /odds request for this match, answered or empty (market.odds_asks)."""
    return fetch_all(
        conn,
        "SELECT asked_at, minutes_to_ko, window_minutes, results, quotes FROM market.odds_asks "
        "WHERE provider_fixture_id = %s ORDER BY asked_at",
        (provider_fixture_id,),
    )


def final_prematch_check(conn: Conn, fixture_id: int) -> Row | None:
    """The newest read of the provider's last pre-match prices after the match (market.final_prematch_checks)."""
    return fetch_one(
        conn,
        "SELECT checked_at, outcome, provider_update_at, bookmakers, quotes FROM market.final_prematch_checks "
        "WHERE fixture_id = %s ORDER BY checked_at DESC LIMIT 1",
        (fixture_id,),
    )


def first_live_state(conn: Conn, fixture_id: int) -> Any:
    """When the match was first seen in play (core.fixture_live_states), if ever."""
    return fetch_value(conn, "SELECT min(observed_at) FROM core.fixture_live_states WHERE fixture_id = %s",
                       (fixture_id,))


def predictions_for(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        """
        WITH latest AS (
            SELECT id FROM analytics.backtest_sessions WHERE status = 'completed'
            ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1
        )
        SELECT m.name AS model, v.version AS model_version,
               CASE WHEN p.backtest_session_id IS NULL THEN 'forecast' ELSE 'backtest' END AS kind,
               p.backtest_session_id, p.market_key, p.selection, p.line,
               p.p_raw, p.p_calibrated, p.p_lo, p.p_hi, p.data_cutoff_ts, p.feature_set_hash, p.created_at
        FROM models.predictions p
        JOIN models.model_versions v ON v.id = p.model_version_id
        JOIN models.model_registry m ON m.id = v.model_id
        WHERE p.fixture_id = %s
          AND (p.backtest_session_id IS NULL
               OR p.model_version_id IN (SELECT r.model_version_id FROM analytics.backtest_runs r
                                         WHERE r.session_id = (SELECT id FROM latest)))
        ORDER BY kind DESC, m.name, p.market_key, p.line, p.selection
        """,
        (fixture_id,),
    )
