"""Historical odds from Football-Data.co.uk, attached to OUR fixtures - carefully.

The source names teams its own way and has no fixture ids. A CSV row is
attached to a stored fixture only when the competition, the date (±1 day for
time-zone shifts) AND the full-time score all agree, and the names then pick
one candidate clearly. Anything else is reported as unmatched or ambiguous and
left out: a wrong join would silently give a model the market of a different
match, which is worse than no market at all.

Each accepted name becomes an alias with its evidence count, and an alias
that would map to two different teams is rejected along with every row that
relied on it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import psycopg
from psycopg.rows import tuple_row

from fbi.providers.football_data.names import similarity
from fbi.providers.football_data.parse import FDRow

SOURCE = "football-data.co.uk"
MIN_PAIR_SIMILARITY = 1.2
"""Home + away similarity. Two names averaging 0.6 each, on top of an exact date and score."""
MIN_MARGIN = 0.3
"""The best candidate must beat the second by this much, or the row is ambiguous."""


@dataclass(frozen=True, slots=True)
class OurFixture:
    fixture_id: int
    kickoff_date: date
    home_id: int
    home: str
    away_id: int
    away: str
    goals_home: int
    goals_away: int


@dataclass
class MatchReport:
    matched: list[tuple[FDRow, OurFixture]] = field(default_factory=list)
    unmatched: list[tuple[FDRow, str]] = field(default_factory=list)
    aliases: dict[str, tuple[int, int]] = field(default_factory=dict)
    """alias -> (team_id, evidence)"""


def load_our_fixtures(conn: psycopg.Connection, competition_id: int, season: int) -> list[OurFixture]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT f.id, (f.kickoff_at AT TIME ZONE 'UTC')::date, th.id, th.name, ta.id, ta.name,
                   r.goals_home, r.goals_away
            FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
            JOIN core.fixture_results r ON r.fixture_id = f.id
            WHERE cs.competition_id = %s AND cs.season = %s AND f.status_group = 'finished'
            """,
            (competition_id, season),
        )
        return [OurFixture(int(a), b, int(c), str(d), int(e), str(f), int(g), int(h))
                for a, b, c, d, e, f, g, h in cur.fetchall()]


def load_aliases(conn: psycopg.Connection) -> dict[str, int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT alias, team_id FROM core.team_aliases WHERE source = %s", (SOURCE,))
        return {str(a): int(b) for a, b in cur.fetchall()}


def match_rows(rows: list[FDRow], ours: list[OurFixture], known: dict[str, int] | None = None) -> MatchReport:
    index: dict[tuple[date, int, int], list[OurFixture]] = defaultdict(list)
    for f in ours:
        for shift in (-1, 0, 1):
            index[(f.kickoff_date + timedelta(days=shift), f.goals_home, f.goals_away)].append(f)
    report = MatchReport()
    provisional: list[tuple[FDRow, OurFixture]] = []
    for row in rows:
        cands = index.get((row.match_date, row.goals_home, row.goals_away), [])
        # An alias already established by earlier evidence is a hard constraint.
        if known:
            cands = [f for f in cands
                     if known.get(row.home, f.home_id) == f.home_id and known.get(row.away, f.away_id) == f.away_id]
        if not cands:
            report.unmatched.append((row, _why_no_candidate(row, ours)))
            continue
        scored = sorted(
            ((similarity(row.home, f.home) + similarity(row.away, f.away), f.fixture_id, f) for f in cands),
            key=lambda t: (-t[0], t[1]),
        )
        best_score, _, best = scored[0]
        if best_score < MIN_PAIR_SIMILARITY:
            why = _why_no_candidate(row, ours)
            if not why.startswith("score disagreement"):
                why = f"names too different from {best.home} v {best.away}"
            report.unmatched.append((row, why))
            continue
        if len(scored) > 1 and best_score - scored[1][0] < MIN_MARGIN:
            report.unmatched.append((row, "ambiguous: two stored fixtures fit equally well"))
            continue
        provisional.append((row, best))

    # One fixture, one row. Two rows claiming the same fixture means one of them is wrong.
    claims: dict[int, int] = defaultdict(int)
    for _, f in provisional:
        claims[f.fixture_id] += 1
    # One alias, one team - across the whole file.
    seen: dict[str, set[int]] = defaultdict(set)
    for row, f in provisional:
        seen[row.home].add(f.home_id)
        seen[row.away].add(f.away_id)
    conflicted = {alias for alias, teams in seen.items() if len(teams) > 1}
    evidence: dict[str, int] = defaultdict(int)
    for row, f in provisional:
        if claims[f.fixture_id] > 1:
            report.unmatched.append((row, "two rows claim the same stored fixture"))
            continue
        if row.home in conflicted or row.away in conflicted:
            report.unmatched.append((row, "a team name maps to more than one stored team"))
            continue
        report.matched.append((row, f))
        evidence[row.home] += 1
        evidence[row.away] += 1
        report.aliases[row.home] = (f.home_id, evidence[row.home])
        report.aliases[row.away] = (f.away_id, evidence[row.away])
    return report


def _why_no_candidate(row: FDRow, ours: list[OurFixture]) -> str:
    """Tell a genuine absence from a disagreement between the sources.

    If a stored fixture on that date has clearly the same teams but a
    different score, the two sources disagree about the result - an awarded
    match, a corrected score. That is worth surfacing, not just skipping.
    """
    for f in ours:
        if abs((f.kickoff_date - row.match_date).days) <= 1 and \
                similarity(row.home, f.home) + similarity(row.away, f.away) >= 1.6:
            return (f"score disagreement: this source says {row.goals_home}-{row.goals_away}, "
                    f"stored fixture {f.fixture_id} says {f.goals_home}-{f.goals_away}")
    return "no stored fixture with that date and score"


def write_matched(conn: psycopg.Connection, report: MatchReport, *, payload_hash: str) -> int:
    """Insert the prices of matched rows, and record the aliases. Idempotent."""
    written = 0
    with conn.cursor() as cur:
        for row, f in report.matched:
            for p in row.prices:
                cur.execute(
                    "INSERT INTO market.historical_odds (fixture_id, source, bookmaker_code, market_key, selection, "
                    "line, price_kind, odds_decimal, source_payload_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (fixture_id, source, bookmaker_code, market_key, selection, line, price_kind) "
                    "DO UPDATE SET odds_decimal = EXCLUDED.odds_decimal, "
                    "source_payload_hash = EXCLUDED.source_payload_hash",
                    (f.fixture_id, SOURCE, p.bookmaker_code, p.market_key, p.selection, p.line, p.price_kind,
                     p.odds, payload_hash),
                )
                written += 1
        for alias, (team_id, n) in report.aliases.items():
            cur.execute(
                "INSERT INTO core.team_aliases (source, alias, team_id, method, evidence) "
                "VALUES (%s, %s, %s, 'fixture_and_score', %s) "
                "ON CONFLICT (source, alias) DO UPDATE SET evidence = GREATEST(core.team_aliases.evidence, EXCLUDED.evidence)",
                (SOURCE, alias, team_id, n),
            )
    return written


STAT_FIELDS = ("shots", "shots_on_target", "corners", "fouls", "yellow_cards", "red_cards")


def write_matched_stats(conn: psycopg.Connection, report: MatchReport, *, payload_hash: str,
                        fetched_at: datetime) -> int:
    """Team match statistics of matched rows into core.fixture_team_stats (source
    football-data.co.uk). A row with no statistic at all writes nothing; shots on
    target above total shots are the source's error and dropped. Idempotent and
    monotonic on fetched_at."""
    written = 0
    cols = ", ".join(STAT_FIELDS)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in STAT_FIELDS)
    with conn.cursor() as cur:
        for row, f in report.matched:
            for side, stats in (("home", row.home_stats), ("away", row.away_stats)):
                values = [stats.get(c) for c in STAT_FIELDS]
                if all(v is None for v in values):
                    continue
                if values[0] is not None and values[1] is not None and values[1] > values[0]:
                    values[1] = None
                cur.execute(
                    f"INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, {cols}, payload_hash, "
                    f"fetched_at) VALUES (%s, %s, %s, {', '.join(['%s'] * len(STAT_FIELDS))}, %s, %s) "
                    f"ON CONFLICT (fixture_id, team_side, source) DO UPDATE SET {sets}, "
                    "payload_hash = EXCLUDED.payload_hash, fetched_at = EXCLUDED.fetched_at "
                    "WHERE core.fixture_team_stats.fetched_at <= EXCLUDED.fetched_at",
                    (f.fixture_id, side, SOURCE, *values, payload_hash, fetched_at),
                )
                written += max(cur.rowcount, 0)
    return written
