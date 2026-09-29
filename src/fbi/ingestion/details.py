"""Write match detail (statistics, events, lineups, player statistics), injuries,
standings and coverage from provider payloads - idempotent and monotonic.

Every writer takes the payload hash and the instant the payload was fetched.
A row is replaced only by a payload fetched at the same instant or later, so
replaying an old payload can never overwrite a newer one, and applying the
same payload twice writes the same rows. A fixture the catalogue does not
hold is counted as skipped - never created from a detail payload.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.ingestion.identity import IdentityReport, apply_people, link_lineup_coaches
from fbi.providers.api_football.details import (
    COVERAGE_FLAGS,
    AbsenceRef,
    CoverageRef,
    FixtureDetail,
    LineupRef,
    StandingRef,
    iter_lineup_people,
)
from fbi.quality.issues import (
    EntityType,
    IssueCode,
    IssueRegistry,
    QualityIssue,
    Severity,
    inconsistency,
    issues_from,
    unknown_entity,
)

SOURCE = "api-football"

DATASET_OF_BLOCK: dict[str, str] = {
    "events": "events",
    "lineups": "lineups",
    "statistics": "team_statistics",
    "players": "player_statistics",
}
"""The provider's block names, and what we call the dataset they carry.
/fixtures?ids= returns all four inline, and a league-season without the matching
coverage flag simply has no block - which is why what ARRIVED is recorded per
fixture rather than inferred from an empty table."""

STARTERS_PER_SIDE = 11

TEAM_STAT_COLUMNS = (
    "shots", "shots_on_target", "shots_off_target", "shots_blocked", "shots_inside_box", "shots_outside_box",
    "corners", "fouls", "offsides", "yellow_cards", "red_cards", "saves", "possession_pct", "passes",
    "passes_accurate", "expected_goals", "goals_prevented",
)
PLAYER_STAT_COLUMNS = (
    "minutes", "rating", "is_captain", "is_substitute", "shots_total", "shots_on", "goals", "goals_conceded",
    "assists", "saves", "passes_total", "passes_key", "passes_accuracy_pct", "tackles", "blocks",
    "interceptions", "duels_total", "duels_won", "dribbles_attempts", "dribbles_success", "fouls_drawn",
    "fouls_committed", "yellow_cards", "red_cards", "penalties_scored", "penalties_missed",
)


@dataclass
class DetailReport:
    fixtures: int = 0
    skipped_unknown_fixture: int = 0
    stats_rows: int = 0
    events: int = 0
    lineups: int = 0
    lineup_players: int = 0
    player_rows: int = 0
    stale: int = 0
    """Payload older than what is stored for that fixture: nothing written."""
    unknown_stat_types: set[str] = field(default_factory=set)
    issues: list[QualityIssue] = field(default_factory=list)
    """What the provider sent that we could not store as sent. Recorded in
    audit.data_quality_issues, never silently dropped."""
    issues_opened: int = 0
    issues_seen_again: int = 0
    coverage_rows: int = 0
    """Rows written to core.fixture_detail_coverage: four per fixture, always."""
    identity: IdentityReport = field(default_factory=IdentityReport)
    """Players and coaches the payload named. They arrive with the detail, so
    recording them costs nothing extra."""

    @property
    def rows(self) -> int:
        return self.stats_rows + self.events + self.lineups + self.lineup_players + self.player_rows


def _fixture_map(conn: psycopg.Connection, provider_ids: Iterable[int]) -> dict[int, tuple[int, int, int]]:
    """provider fixture id -> (our fixture id, provider home team id, provider away team id)."""
    ids = sorted(set(provider_ids))
    if not ids:
        return {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT f.provider_fixture_id, f.id, th.provider_team_id, ta.provider_team_id FROM core.fixtures f "
            "JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id "
            "WHERE f.provider_fixture_id = ANY(%s)",
            (ids,),
        )
        return {int(a): (int(b), int(c), int(d)) for a, b, c, d in cur.fetchall()}


def _side(team_id: int | None, home: int, away: int) -> str | None:
    return "home" if team_id == home else "away" if team_id == away else None


def _clean(value: Decimal | int | bool | None) -> Decimal | int | bool | None:
    """Negative counts are the provider's error, not a statistic: dropped.

    The caller records what was dropped; see ``_team_stat_values``.
    """
    if isinstance(value, bool) or value is None:
        return value
    return None if value < 0 else value


CONTRADICTIONS: tuple[tuple[str, str], ...] = (
    ("shots_on_target", "shots"),
    ("passes_accurate", "passes"),
)
"""(the part, the whole). The schema forbids the part exceeding the whole, so a
contradictory value cannot be stored - but it can be named."""


def _team_stat_values(
    raw: dict[str, Decimal | int | bool | None],
    *,
    fixture_id: int,
    provider_team_id: int | None,
    payload_hash: str,
    run_id: int | None,
) -> tuple[list[Decimal | int | bool | None], list[str], list[QualityIssue]]:
    """The row to write, the columns dropped from it, and why.

    Two kinds of drop, both recorded rather than absorbed:
      * a negative count, which is not a statistic;
      * a part exceeding its whole, which the schema's CHECK refuses.
    """
    index = {name: i for i, name in enumerate(TEAM_STAT_COLUMNS)}
    values: list[Decimal | int | bool | None] = []
    dropped: list[str] = []
    issues: list[QualityIssue] = []
    for name in TEAM_STAT_COLUMNS:
        original = raw.get(name)
        cleaned = _clean(original)
        if cleaned is None and original is not None:
            dropped.append(name)
            issues.append(inconsistency(
                entity_type=EntityType.TEAM_STATISTICS, entity_id=fixture_id,
                provider_entity_id=provider_team_id, field_name=name, observed=original,
                expected="a count of zero or more", payload_hash=payload_hash, run_id=run_id,
                detail=f"{name} arrived negative, which is not a statistic",
            ))
        values.append(cleaned)
    for part, whole in CONTRADICTIONS:
        p_value, w_value = values[index[part]], values[index[whole]]
        if p_value is None or w_value is None or p_value <= w_value:
            continue
        dropped.append(part)
        issues.append(inconsistency(
            entity_type=EntityType.TEAM_STATISTICS, entity_id=fixture_id,
            provider_entity_id=provider_team_id, field_name=part, observed=p_value,
            expected=f"at most {whole} ({w_value})", payload_hash=payload_hash, run_id=run_id,
            detail=f"the provider reported {part}={p_value} with {whole}={w_value}; "
                   f"the schema forbids the part exceeding the whole, so {part} is not stored",
        ))
        values[index[part]] = None
    return values, sorted(set(dropped)), issues


def apply_fixture_details(conn: psycopg.Connection, details: Iterable[FixtureDetail], *, payload_hash: str,
                          fetched_at: datetime, run_id: int | None = None) -> DetailReport:
    details = list(details)
    fmap = _fixture_map(conn, (d.provider_fixture_id for d in details))
    report = DetailReport()
    with conn.cursor(row_factory=tuple_row) as cur:
        for d in details:
            known = fmap.get(d.provider_fixture_id)
            if known is None:
                report.skipped_unknown_fixture += 1
                continue
            fixture_id, home, away = known
            cur.execute(
                "SELECT greatest((SELECT max(fetched_at) FROM core.fixture_events WHERE fixture_id = %(f)s "
                "AND source = %(s)s), (SELECT max(fetched_at) FROM core.fixture_lineups WHERE fixture_id = %(f)s "
                "AND source = %(s)s), (SELECT max(fetched_at) FROM core.fixture_team_stats WHERE fixture_id = %(f)s "
                "AND source = %(s)s), (SELECT max(fetched_at) FROM core.fixture_player_stats "
                "WHERE fixture_id = %(f)s AND source = %(s)s))",
                {"f": fixture_id, "s": SOURCE},
            )
            newest = cur.fetchone()
            if newest and newest[0] is not None and newest[0] > fetched_at:
                report.stale += 1  # a newer payload for this fixture is already applied
                continue
            report.fixtures += 1
            delivered: dict[str, int] = dict.fromkeys(DATASET_OF_BLOCK.values(), 0)
            if "statistics" in d.blocks_present:
                for s in d.stats:
                    side = _side(s.provider_team_id, home, away)
                    if side is None:
                        continue
                    report.unknown_stat_types.update(s.unknown_types)
                    for unknown in sorted(s.unknown_types):
                        report.issues.append(unknown_entity(
                            entity_type=EntityType.TEAM_STATISTICS, name=unknown,
                            provider_entity_id=s.provider_team_id, payload_hash=payload_hash,
                            run_id=run_id,
                            detail="a statistic type the normaliser has no column for; the value is "
                                   "in the raw payload and is not stored",
                        ))
                    vals, dropped, found = _team_stat_values(
                        s.values, fixture_id=fixture_id, provider_team_id=s.provider_team_id,
                        payload_hash=payload_hash, run_id=run_id,
                    )
                    report.issues.extend(found)
                    cols = ", ".join(TEAM_STAT_COLUMNS)
                    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in TEAM_STAT_COLUMNS)
                    cur.execute(
                        f"INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, {cols}, payload_hash, "
                        f"fetched_at, dropped_fields) "
                        f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(TEAM_STAT_COLUMNS))}, %s, %s, %s) "
                        f"ON CONFLICT (fixture_id, team_side, source) DO UPDATE SET {sets}, "
                        "payload_hash = EXCLUDED.payload_hash, fetched_at = EXCLUDED.fetched_at, "
                        "dropped_fields = EXCLUDED.dropped_fields "
                        "WHERE core.fixture_team_stats.fetched_at <= EXCLUDED.fetched_at",
                        (fixture_id, side, SOURCE, *vals, payload_hash, fetched_at, dropped),
                    )
                    report.stats_rows += max(cur.rowcount, 0)
                    delivered["team_statistics"] += 1
            if "events" in d.blocks_present:
                cur.execute("DELETE FROM core.fixture_events WHERE fixture_id = %s AND source = %s",
                            (fixture_id, SOURCE))
                for e in d.events:
                    cur.execute(
                        "INSERT INTO core.fixture_events (fixture_id, source, seq, minute, extra_minute, team_side, "
                        "provider_team_id, provider_player_id, player_name, provider_assist_id, assist_name, "
                        "event_type, detail, comments, payload_hash, fetched_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (fixture_id, SOURCE, e.seq, e.minute, e.extra_minute,
                         _side(e.provider_team_id, home, away), e.provider_team_id, e.provider_player_id,
                         e.player_name, e.provider_assist_id, e.assist_name, e.event_type, e.detail, e.comments,
                         payload_hash, fetched_at),
                    )
                    report.events += 1
                    delivered["events"] += 1
            if "lineups" in d.blocks_present:
                for lu in d.lineups:
                    side = _side(lu.provider_team_id, home, away)
                    if side is None:
                        continue
                    cur.execute(
                        "INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, "
                        "provider_coach_id, coach_name, payload_hash, fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (fixture_id, team_side, source) DO UPDATE SET formation = EXCLUDED.formation, "
                        "provider_coach_id = EXCLUDED.provider_coach_id, coach_name = EXCLUDED.coach_name, "
                        "payload_hash = EXCLUDED.payload_hash, fetched_at = EXCLUDED.fetched_at",
                        (fixture_id, side, SOURCE, lu.formation, lu.provider_coach_id, lu.coach_name,
                         payload_hash, fetched_at),
                    )
                    report.lineups += 1
                    delivered["lineups"] += 1
                    cur.execute("DELETE FROM core.fixture_lineup_players WHERE fixture_id = %s AND team_side = %s "
                                "AND source = %s", (fixture_id, side, SOURCE))
                    seen: set[int] = set()
                    for p in lu.players:
                        if p.provider_player_id in seen:
                            continue
                        seen.add(p.provider_player_id)
                        cur.execute(
                            "INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, "
                            "provider_player_id, player_name, shirt_number, position, grid, is_starter) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (fixture_id, side, SOURCE, p.provider_player_id, p.name, p.number, p.position, p.grid,
                             p.is_starter),
                        )
                        report.lineup_players += 1
                    report.issues.extend(_lineup_issues(
                        lu, side=side, fixture_id=fixture_id, payload_hash=payload_hash, run_id=run_id,
                    ))
            if "players" in d.blocks_present:
                for ps in d.players:
                    side = _side(ps.provider_team_id, home, away)
                    if side is None:
                        continue
                    vals2 = [_clean(ps.values.get(c)) for c in PLAYER_STAT_COLUMNS]
                    cols = ", ".join(PLAYER_STAT_COLUMNS)
                    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in PLAYER_STAT_COLUMNS)
                    cur.execute(
                        f"INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, "
                        f"player_name, {cols}, payload_hash, fetched_at) VALUES (%s,%s,%s,%s,%s, "
                        f"{', '.join(['%s'] * len(PLAYER_STAT_COLUMNS))}, %s, %s) "
                        f"ON CONFLICT (fixture_id, source, provider_player_id) DO UPDATE SET team_side = "
                        f"EXCLUDED.team_side, player_name = EXCLUDED.player_name, {sets}, "
                        "payload_hash = EXCLUDED.payload_hash, fetched_at = EXCLUDED.fetched_at "
                        "WHERE core.fixture_player_stats.fetched_at <= EXCLUDED.fetched_at",
                        (fixture_id, SOURCE, ps.provider_player_id, side, ps.name, *vals2, payload_hash, fetched_at),
                    )
                    report.player_rows += max(cur.rowcount, 0)
                    delivered["player_statistics"] += 1
            # The payload already names every player and coach it mentions, so
            # identity comes free with the detail: no extra request, and the
            # "players without a mapping" gap closes itself.
            people, coaches = iter_lineup_people(d)
            apply_people(conn, people, coaches, payload_hash=payload_hash, fetched_at=fetched_at,
                         report=report.identity)
            if coaches:
                report.identity.lineups_linked += link_lineup_coaches(conn, fixture_id)
            report.coverage_rows += _write_coverage(
                cur, fixture_id=fixture_id, blocks_present=d.blocks_present, delivered=delivered,
                payload_hash=payload_hash, fetched_at=fetched_at, report=report, run_id=run_id,
            )
    _record(conn, report)
    return report


def _lineup_issues(lu: LineupRef, *, side: str, fixture_id: int, payload_hash: str,
                   run_id: int | None) -> list[QualityIssue]:
    """A line-up short of eleven starters, or missing its formation or coach.

    NOT filled in. Eleven starters is what a line-up means, so fewer is a fact
    about the provider's payload, recorded with what was actually there.
    """
    found: list[QualityIssue] = []
    starters = sum(1 for p in lu.players if p.is_starter)
    if starters != STARTERS_PER_SIDE:
        found.append(QualityIssue(
            code=IssueCode.INCOMPLETE_LINEUP, entity_type=EntityType.LINEUP,
            severity=Severity.WARNING, entity_id=fixture_id,
            provider_entity_id=lu.provider_team_id, payload_hash=payload_hash, run_id=run_id,
            field="starters", observed=starters, expected=str(STARTERS_PER_SIDE),
            detail=f"the {side} line-up arrived with {starters} starters and "
                   f"{len(lu.players) - starters} substitutes; it is stored as received",
        ))
    for name, value in (("formation", lu.formation), ("coach_name", lu.coach_name)):
        if value:
            continue
        found.append(QualityIssue(
            code=IssueCode.INCOMPLETE_LINEUP, entity_type=EntityType.LINEUP,
            severity=Severity.INFO, entity_id=fixture_id,
            provider_entity_id=lu.provider_team_id, payload_hash=payload_hash, run_id=run_id,
            field=name, observed=None, expected="a value",
            detail=f"the {side} line-up arrived without {name}",
        ))
    return found


def _write_coverage(cur: psycopg.Cursor[Any], *, fixture_id: int, blocks_present: frozenset[str],
                    delivered: dict[str, int], payload_hash: str, fetched_at: datetime,
                    report: DetailReport, run_id: int | None) -> int:
    """Record what this payload carried for this fixture, block by block.

    Always four rows, including the blocks that did not arrive: that absence is
    the whole point. A dataset with no row has never been fetched; a dataset with
    block_present = false has been fetched and is not published, and must not be
    requested again.
    """
    written = 0
    for block, dataset in DATASET_OF_BLOCK.items():
        present = block in blocks_present
        rows = delivered.get(dataset, 0) if present else 0
        cur.execute(
            "INSERT INTO core.fixture_detail_coverage (fixture_id, source, dataset, block_present, "
            " rows_written, payload_hash, fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (fixture_id, source, dataset) DO UPDATE SET "
            "  block_present = EXCLUDED.block_present, rows_written = EXCLUDED.rows_written, "
            "  payload_hash = EXCLUDED.payload_hash, fetched_at = EXCLUDED.fetched_at "
            "WHERE core.fixture_detail_coverage.fetched_at <= EXCLUDED.fetched_at",
            (fixture_id, SOURCE, dataset, present, rows, payload_hash, fetched_at),
        )
        written += max(cur.rowcount, 0)
        if not present:
            report.issues.append(QualityIssue(
                code=IssueCode.MISSING_DETAIL, entity_type=EntityType.FIXTURE,
                severity=Severity.WARNING, entity_id=fixture_id, payload_hash=payload_hash,
                run_id=run_id, field=dataset, observed=None, expected="a block in the payload",
                detail=f"the payload for this fixture carried no {block} block; recorded so the "
                       f"planner does not spend quota asking for it again",
            ))
    return written


def _record(conn: psycopg.Connection, report: DetailReport) -> None:
    """Persist what could not be stored as sent, in the same transaction as the
    rows that were. Deduplicated by fingerprint first, so one payload counts as
    one occurrence of each distinct problem."""
    if not report.issues:
        return
    result = IssueRegistry(conn).record_many(issues_from(report.issues))
    report.issues_opened = result.opened
    report.issues_seen_again = result.seen_again


def apply_injuries(conn: psycopg.Connection, absences: Iterable[AbsenceRef], *, payload_hash: str,
                   fetched_at: datetime) -> int:
    rows = list(absences)
    fmap = _fixture_map(conn, (a.provider_fixture_id for a in rows))
    written = 0
    with conn.cursor() as cur:
        for a in rows:
            known = fmap.get(a.provider_fixture_id)
            cur.execute(
                "INSERT INTO core.player_absences (source, provider_fixture_id, provider_player_id, fixture_id, "
                "provider_team_id, player_name, absence_type, reason, payload_hash, fetched_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source, provider_fixture_id, provider_player_id) "
                "DO UPDATE SET fixture_id = EXCLUDED.fixture_id, provider_team_id = EXCLUDED.provider_team_id, "
                "player_name = EXCLUDED.player_name, absence_type = EXCLUDED.absence_type, reason = EXCLUDED.reason, "
                "payload_hash = EXCLUDED.payload_hash, fetched_at = EXCLUDED.fetched_at "
                "WHERE core.player_absences.fetched_at <= EXCLUDED.fetched_at",
                (SOURCE, a.provider_fixture_id, a.provider_player_id, known[0] if known else None,
                 a.provider_team_id, a.player_name, a.absence_type, a.reason, payload_hash, fetched_at),
            )
            written += max(cur.rowcount, 0)
    return written


def apply_coverage(conn: psycopg.Connection, refs: Iterable[CoverageRef], *, payload_hash: str,
                   fetched_at: datetime) -> int:
    written = 0
    cols = ", ".join(COVERAGE_FLAGS)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in COVERAGE_FLAGS)
    with conn.cursor() as cur:
        for r in refs:
            cur.execute(
                f"INSERT INTO raw.league_coverage (provider, provider_league_id, season, league_name, country, "
                f"league_type, is_current, start_date, end_date, {cols}, payload_hash, observed_at) "
                f"VALUES ('api_football', %s, %s, %s, %s, %s, %s, %s, %s, "
                f"{', '.join(['%s'] * len(COVERAGE_FLAGS))}, %s, %s) "
                f"ON CONFLICT (provider, provider_league_id, season) DO UPDATE SET league_name = "
                f"EXCLUDED.league_name, country = EXCLUDED.country, league_type = EXCLUDED.league_type, "
                f"is_current = EXCLUDED.is_current, start_date = EXCLUDED.start_date, end_date = EXCLUDED.end_date, "
                f"{sets}, payload_hash = EXCLUDED.payload_hash, observed_at = EXCLUDED.observed_at "
                "WHERE raw.league_coverage.observed_at <= EXCLUDED.observed_at",
                (r.provider_league_id, r.season, r.league_name, r.country, r.league_type, r.is_current,
                 r.start_date, r.end_date, *(r.flags.get(c) for c in COVERAGE_FLAGS), payload_hash, fetched_at),
            )
            written += max(cur.rowcount, 0)
    return written


def apply_standings(conn: psycopg.Connection, refs: Iterable[StandingRef], *, fetched_at: datetime) -> int:
    """One snapshot per (competition season, team) at the payload's instant."""
    written = 0
    with conn.cursor(row_factory=tuple_row) as cur:
        for r in refs:
            cur.execute(
                "SELECT cs.id, t.id FROM core.competition_seasons cs "
                "JOIN core.competitions c ON c.id = cs.competition_id JOIN core.teams t ON t.provider_team_id = %s "
                "WHERE c.provider_league_id = %s AND cs.season = %s",
                (r.provider_team_id, r.provider_league_id, r.season),
            )
            row = cur.fetchone()
            if row is None:
                continue
            cur.execute(
                'INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, played, wins, '
                'draws, losses, goals_for, goals_against, form, "group") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                "ON CONFLICT DO NOTHING",
                (int(row[0]), int(row[1]), fetched_at, r.rank, r.points, r.played, r.wins, r.draws, r.losses,
                 r.goals_for, r.goals_against, r.form, r.group),
            )
            written += max(cur.rowcount, 0)
    return written
