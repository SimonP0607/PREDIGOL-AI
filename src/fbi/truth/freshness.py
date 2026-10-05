"""How current each dataset is, against what the provider could have given us.

"Updated recently" is meaningless on its own: a table refreshed an hour ago is behind
if a match ended since, and a squad list a month old may be perfectly current. So
each dataset has a service level stated in terms of the event that makes it go out
of date, derived from the provider's own update cadence
(``docs/api-football/06_UPDATE_FREQUENCIES.md``):

======================  ====================================  ===========================
dataset                 provider updates                      ours is FRESH when
======================  ====================================  ===========================
fixtures (schedule)     every 15 s                            the season's list was read in the last 14 h
results                 every 15 s (some competitions: 48 h)  a match 3 h past kick-off has a final status
live                    every 15 s                            a match in play was read in the last 3 min
standings               every hour                            the table was read after the last match ended
injuries                every 4 h                             read in the last 6 h (season playing in 48 h)
lineups                 every 15 min                          a played match has its line-ups
match detail            every minute                          read after the match ended
pre-match odds          every 3 h                             a match in the next 72 h was priced in the last 3 h
teams                   several times a week                  identity read in the last 120 days
players / coaches       several times a week                  a profile has been read at all
elo                     (ours)                                a finished match of the last 30 days is rated
coverage flags          several times a day                   read in the last 8 days
======================  ====================================  ===========================

Four states, never more:

* FRESH - we hold what the provider holds, by the rule above.
* STALE - the provider has newer data than we hold, and asking was our job.
* UNKNOWN - we cannot tell: never fetched, or nothing to compare against.
* UNAVAILABLE - the provider does not have it: its coverage flag says no, or we asked
  after the event and it had not published yet (its lag, not ours).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row


class Freshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


ORDER = (Freshness.STALE, Freshness.UNKNOWN, Freshness.UNAVAILABLE, Freshness.FRESH)


@dataclass
class DatasetFreshness:
    dataset: str
    sla: str
    entity: str
    """What one counted thing is: "competition-season", "fixture", "player"."""
    counts: dict[str, int] = field(default_factory=lambda: {f.value: 0 for f in Freshness})
    by_competition: dict[str, dict[str, int]] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)

    def add(self, state: Freshness, n: int = 1, *, competition: str | None = None, example: str | None = None) -> None:
        self.counts[state.value] += n
        if competition is not None:
            bucket = self.by_competition.setdefault(competition, {f.value: 0 for f in Freshness})
            bucket[state.value] += n
        if example is not None and state is not Freshness.FRESH:
            kept = self.examples.setdefault(state.value, [])
            if len(kept) < 12:
                kept.append(example)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def status(self) -> Freshness:
        """STALE if anything is stale - one table behind is a table behind. Otherwise the
        state of most entities, FRESH winning ties."""
        if self.total == 0:
            return Freshness.UNKNOWN
        if self.counts[Freshness.STALE.value]:
            return Freshness.STALE
        return max((f for f in Freshness if f is not Freshness.STALE),
                   key=lambda f: (self.counts[f.value], f is Freshness.FRESH))

    def label(self) -> str:
        if self.total == 0:
            return "UNKNOWN (nothing to measure)"
        parts = [f"{f.value} {self.counts[f.value] / self.total:.0%}" for f in ORDER if self.counts[f.value]]
        return " · ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        worst = sorted(self.by_competition.items(),
                       key=lambda kv: (-kv[1][Freshness.STALE.value], -kv[1][Freshness.UNKNOWN.value], kv[0]))
        return {"dataset": self.dataset, "sla": self.sla, "entity": self.entity, "status": self.status.value,
                "label": self.label(), "total": self.total, "counts": self.counts,
                "by_competition": [{"competition": k, **v} for k, v in worst[:60]], "examples": self.examples}


def _label(r: Mapping[str, Any]) -> str:
    season = r.get("season")
    return f"{r['competition']} {season}" if season is not None else str(r["competition"])


# ── the queries, one per dataset ────────────────────────────────────────────

FIXTURES_SQL = """
SELECT c.name AS competition, cs.season, max(f.source_fetched_at) AS last_read, count(f.id) AS n
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixtures f ON f.competition_season_id = cs.id
 WHERE c.is_tracked AND cs.is_current
   AND (cs.end_date IS NULL OR cs.end_date >= (%(at)s - interval '30 days')::date)
 GROUP BY c.name, cs.season
"""

RESULTS_SQL = """
SELECT c.name AS competition, cs.season, f.provider_fixture_id, f.status_group, f.status_short, f.kickoff_at,
       f.source_fetched_at
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at BETWEEN %(at)s - interval '7 days' AND %(at)s - interval '3 hours'
"""

LIVE_SQL = """
SELECT c.name AS competition, cs.season, f.provider_fixture_id, f.status_short,
       GREATEST(f.source_fetched_at,
                (SELECT max(s.observed_at) FROM core.fixture_live_states s WHERE s.fixture_id = f.id),
                (SELECT max(r.started_at) FROM raw.ingestion_runs r
                  WHERE r.job_type = 'live_match_capture' AND r.status = 'completed'
                    AND r.started_at BETWEEN f.kickoff_at - interval '2 minutes'
                                         AND f.kickoff_at + interval '3 hours')) AS last_read
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'live'
"""
"""When a match in play was last read. A byte-identical answer (half-time: nothing moves for 15 minutes) keeps
its first index time, so neither the fixture's lineage nor its live states move although the follower asked
every minute: on 5 Oct 2026 a friendly at half-time read as STALE 6 minutes after it was last *changed*. A
completed (uncapped, error-free) ``live_match_capture`` pass in the follower's window - from 2 minutes before
kick-off to 3 hours after, ``fbi.ingestion.live_match.FOLLOW_*`` - asked every tracked match in play."""

STANDINGS_SQL = """
WITH snap AS (SELECT competition_season_id AS cs, max(snapshot_at) AS at FROM core.standings GROUP BY 1),
     fin AS (SELECT competition_season_id AS cs, max(kickoff_at) AS last_kickoff FROM core.fixtures
              WHERE status_group = 'finished' GROUP BY 1)
SELECT c.name AS competition, cs.season, snap.at AS snapshot_at, fin.last_kickoff, k.checked_at,
       lc.standings AS covered
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
  JOIN fin ON fin.cs = cs.id
  LEFT JOIN snap ON snap.cs = cs.id
  LEFT JOIN core.context_checks k ON k.competition_season_id = cs.id AND k.dataset = 'standings'
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND cs.is_current AND c.type = 'league'
"""

INJURIES_SQL = """
SELECT c.name AS competition, cs.season, k.checked_at, lc.injuries AS covered,
       (SELECT max(a.fetched_at) FROM core.player_absences a JOIN core.fixtures f2 ON f2.id = a.fixture_id
         WHERE f2.competition_season_id = cs.id) AS last_absence
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.context_checks k ON k.competition_season_id = cs.id AND k.dataset = 'injuries'
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND cs.is_current
   AND EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = cs.id AND f.status_group = 'scheduled'
                  AND f.kickoff_at BETWEEN %(at)s AND %(at)s + interval '48 hours')
"""

DETAIL_SQL = """
SELECT c.name AS competition, cs.season, f.provider_fixture_id, f.kickoff_at, d.dataset, d.block_present,
       d.rows_written, d.fetched_at, lc.lineups AS cov_lineups, lc.events AS cov_events,
       lc.statistics_fixtures AS cov_statistics, lc.statistics_players AS cov_players
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_detail_coverage d ON d.fixture_id = f.id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND f.status_group = 'finished'
   AND f.kickoff_at BETWEEN %(at)s - interval '7 days' AND %(at)s - interval '3 hours'
"""

ODDS_SQL = """
WITH asked AS (
    SELECT pid AS provider_fixture_id, max(at) AS last_asked FROM (
        SELECT (p.params->>'fixture')::bigint AS pid, p.fetched_at AS at
          FROM raw.ingestion_payloads p
         WHERE p.endpoint = '/odds' AND p.params ? 'fixture' AND p.params->>'fixture' ~ '^[0-9]+$'
           AND p.fetched_at >= %(at)s - interval '20 days'
        UNION ALL
        SELECT a.provider_fixture_id, a.asked_at FROM market.odds_asks a
         WHERE a.asked_at >= %(at)s - interval '20 days') x
     GROUP BY 1
)
SELECT c.name AS competition, cs.season, f.provider_fixture_id, f.kickoff_at,
       CASE WHEN EXISTS (SELECT 1 FROM market.odds_mapping_seen m WHERE m.provider_fixture_id = f.provider_fixture_id)
            THEN true ELSE lc.odds END AS covered,
       (SELECT max(o.captured_at) FROM market.odds_snapshots o WHERE o.fixture_id = f.id) AS last_capture,
       a.last_asked
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
  LEFT JOIN asked a ON a.provider_fixture_id = f.provider_fixture_id
 WHERE c.is_tracked AND f.status_group = 'scheduled'
   AND f.kickoff_at BETWEEN %(at)s AND %(at)s + interval '72 hours'
"""
"""``last_asked``: the RAW index keeps one row per distinct answer, so an empty answer asked again is only in
market.odds_asks (0064). ``covered``: the season's coverage flag, overruled by /odds/mapping when it lists the fixture.
Asks older than 20 days cannot concern a match of the next 72 h (prices appear up to ~19 days ahead)."""

TEAMS_SQL = """
SELECT DISTINCT ON (t.id) c.name AS competition, cs.season, t.provider_team_id, t.country, t.source_fetched_at
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
 WHERE c.is_tracked AND cs.is_current
 ORDER BY t.id, c.tier NULLS LAST
"""

PEOPLE_SQL = """
WITH appeared AS (
    SELECT DISTINCT lp.provider_player_id
      FROM core.fixture_lineup_players lp JOIN core.fixtures f ON f.id = lp.fixture_id
     WHERE f.kickoff_at > %(at)s - interval '365 days' AND lp.provider_player_id > 0
)
SELECT 'players' AS dataset, count(*) AS total,
       count(*) FILTER (WHERE p.profile_fetched_at > %(at)s - interval '45 days') AS profiled,
       count(*) FILTER (WHERE p.profile_fetched_at <= %(at)s - interval '45 days') AS old_profile,
       count(p.id) AS known,
       count(*) FILTER (WHERE p.profile_fetched_at IS NULL AND k.results = 0) AS provider_none
  FROM appeared a LEFT JOIN core.players p ON p.provider_player_id = a.provider_player_id
  LEFT JOIN core.reference_checks k ON k.feed = 'profiles_players' AND k.target = 'player:' || a.provider_player_id
UNION ALL
SELECT 'coaches', count(*),
       count(*) FILTER (WHERE co.birth_date IS NOT NULL OR co.nationality IS NOT NULL OR cp.birth_date IS NOT NULL
                          OR cp.nationality IS NOT NULL),
       0, count(co.id),
       count(*) FILTER (WHERE NOT COALESCE(co.birth_date IS NOT NULL OR co.nationality IS NOT NULL
                                           OR cp.birth_date IS NOT NULL OR cp.nationality IS NOT NULL, false)
                          AND k.checked_at IS NOT NULL AND k.error IS NULL)
  FROM (SELECT DISTINCT l.provider_coach_id FROM core.fixture_lineups l JOIN core.fixtures f ON f.id = l.fixture_id
         WHERE f.kickoff_at > %(at)s - interval '365 days' AND l.provider_coach_id > 0) x
  LEFT JOIN core.coaches co ON co.provider_coach_id = x.provider_coach_id
  LEFT JOIN core.coach_profiles_latest cp ON cp.provider_coach_id = x.provider_coach_id
  LEFT JOIN core.reference_checks k ON k.feed = 'coachs_by_id' AND k.target = 'coach:' || x.provider_coach_id
"""
"""Coaches: a profile from the line-ups' identity rows or from /coachs (the reference feed, weekly per tracked team,
since 4 Oct 2026 - before it, no coach had a profile and the dataset read UNKNOWN 100%). ``provider_none``: asked by
id (``profiles_players``, ``coachs_by_id``, 5 Oct 2026) and the provider gave no profile - or, for a coach, one with
neither birth date nor nationality: the provider's gap, not one we never read."""

SQUADS_SQL = """
SELECT DISTINCT ON (t.id) c.name AS competition, cs.season, t.provider_team_id, t.squad_checked_at,
       k.asked_at, k.asked_results
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
  LEFT JOIN LATERAL (
      SELECT b.updated_at AS asked_at, p.results_count AS asked_results
        FROM raw.backfill_tasks b LEFT JOIN raw.ingestion_payloads p ON p.hash = b.last_payload_hash
       WHERE b.kind = 'team_squad' AND b.batch_key = t.provider_team_id::text AND b.status = 'done'
       ORDER BY b.updated_at DESC LIMIT 1) k ON true
 WHERE c.is_tracked AND cs.is_current AND c.name !~* 'friendl'
 ORDER BY t.id, c.tier NULLS LAST
"""
"""``asked_at``/``asked_results``: the newest done unit of the weekly /players/squads round and how many entries its
answer had. A team asked and answered with nothing is the provider's gap, not a team never read (5 Oct 2026: all
300 'never read' teams had been asked twice and answered nothing)."""

ELO_SQL = """
SELECT c.name AS competition, NULL::int AS season, f.provider_fixture_id, f.kickoff_at,
       r.fixture_id IS NOT NULL AS rated, fr.fixture_id IS NOT NULL AS scored
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN (SELECT DISTINCT fixture_id FROM features.elo_ratings) r ON r.fixture_id = f.id
  LEFT JOIN core.fixture_results fr ON fr.fixture_id = f.id
 WHERE c.is_tracked AND f.status_group = 'finished' AND f.kickoff_at > %(at)s - interval '30 days'
"""

COVERAGE_SQL = """
SELECT c.name AS competition, cs.season, lc.observed_at
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND cs.is_current
"""

HOURS = 3600.0
MATCH_ENDS_AFTER = 110 * 60.0
"""Seconds from kick-off to a final whistle: 90 minutes, the interval and stoppage time. A
detail read after this was read from a finished match; the live follower's last read
lands here."""


def _age_h(at: datetime, then: datetime | None) -> float | None:
    return None if then is None else (at - then).total_seconds() / HOURS


FIXTURES_FRESH_HOURS = 14
"""Two six-hour fixture syncs plus two hours: one missed run is tolerated, two are not."""


def _fixtures(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("fixtures", f"every current season's fixture list read in the last "
                           f"{FIXTURES_FRESH_HOURS} h (sync every 6 h; the provider updates every 15 s)",
                           "competition-season")
    for r in rows:
        age = _age_h(at, r["last_read"])
        state = (Freshness.UNKNOWN if r["n"] == 0 or age is None
                 else Freshness.FRESH if age <= FIXTURES_FRESH_HOURS else Freshness.STALE)
        out.add(state, competition=_label(r), example=f"{_label(r)}: read {age:.0f} h ago" if age else _label(r))
    return out


def _results(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("results", "a match 3 h past kick-off carries a final status (finished, cancelled, "
                           "postponed); if we re-read it and the provider still says NS, that is its lag",
                           "fixture")
    for r in rows:
        if r["status_group"] in ("finished", "cancelled", "postponed"):
            out.add(Freshness.FRESH, competition=_label(r))
            continue
        read_after = r["source_fetched_at"] is not None and (r["source_fetched_at"] - r["kickoff_at"]).total_seconds() \
            > 3 * HOURS and (at - r["source_fetched_at"]).total_seconds() < 2 * HOURS
        out.add(Freshness.UNAVAILABLE if read_after else Freshness.STALE, competition=_label(r),
                example=f"fixture {r['provider_fixture_id']} {r['status_short']} since "
                        f"{r['kickoff_at']:%Y-%m-%d %H:%M}Z")
    return out


def _live(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("live", "a match in play was read in the last 3 minutes (follower every 60 s)", "fixture")
    for r in rows:
        age = _age_h(at, r["last_read"])
        out.add(Freshness.FRESH if age is not None and age * 60 <= 3 else Freshness.STALE, competition=_label(r),
                example=f"fixture {r['provider_fixture_id']} {r['status_short']}, read "
                        f"{(age or 0) * 60:.0f} min ago")
    return out


TABLE_REFLECTS_AFTER = 2 * HOURS
"""Seconds from a match's kick-off after which a table can include it."""


TABLE_REASONS = ("not_covered", "no_table", "no_match_yet", "reflects_last_match", "provider_not_updated",
                 "not_asked_since")
"""Stable codes for ``table_state``'s reasons, so a page can say them in its reader's language."""


def table_reason(snapshot: datetime | None, last_finished: datetime | None, checked: datetime | None,
                 covered: bool | None) -> tuple[Freshness, str]:
    """``table_state`` as (state, reason code)."""
    if snapshot is None:
        return (Freshness.UNAVAILABLE, "not_covered") if covered is False else (Freshness.UNKNOWN, "no_table")
    if last_finished is None:
        return Freshness.FRESH, "no_match_yet"
    ended = last_finished.timestamp() + TABLE_REFLECTS_AFTER
    if snapshot.timestamp() >= ended:
        return Freshness.FRESH, "reflects_last_match"
    if checked is not None and checked.timestamp() >= ended:
        return Freshness.UNAVAILABLE, "provider_not_updated"
    return Freshness.STALE, "not_asked_since"


def table_state(snapshot: datetime | None, last_finished: datetime | None, checked: datetime | None,
                covered: bool | None) -> tuple[Freshness, str]:
    """Whether a league table is current, and why - the rule the Match Center and the audit share.

    ``snapshot`` is when the newest content was first seen, ``checked`` when the provider was
    last asked (an unchanged answer moves ``checked`` but not ``snapshot``), ``last_finished``
    the kick-off of the season's last finished match.
    """
    if snapshot is None:
        if covered is False:
            return Freshness.UNAVAILABLE, "the provider publishes no table for this season"
        return Freshness.UNKNOWN, "no table stored"
    if last_finished is None:
        return Freshness.FRESH, "no match has been played yet"
    ended = last_finished.timestamp() + TABLE_REFLECTS_AFTER
    if snapshot.timestamp() >= ended:
        return Freshness.FRESH, "the table reflects the last match played"
    if checked is not None and checked.timestamp() >= ended:
        return Freshness.UNAVAILABLE, (f"asked {checked:%d %b %H:%M} UTC, after the last match; the provider had "
                                       "not updated its table yet")
    return Freshness.STALE, (f"table from {snapshot:%d %b %H:%M} UTC, last match {last_finished:%d %b %H:%M} UTC; "
                             "not asked since it ended")


def _standings(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("standings", "the table was read after the season's last match ended (the provider "
                           "updates hourly); asked after and unchanged = its lag", "competition-season")
    for r in rows:
        state, why = table_state(r["snapshot_at"], r["last_kickoff"], r["checked_at"], r["covered"])
        out.add(state, competition=_label(r), example=f"{_label(r)}: {why}")
    return out


def _injuries(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("injuries", "a season playing in the next 48 h had its list read in the last 6 h "
                           "(the provider updates every 4 h)", "competition-season")
    for r in rows:
        last = r["checked_at"] or r["last_absence"]
        age = _age_h(at, last)
        if r["covered"] is False:
            out.add(Freshness.UNAVAILABLE, competition=_label(r))
        elif age is None:
            out.add(Freshness.UNKNOWN, competition=_label(r), example=f"{_label(r)}: never read")
        else:
            out.add(Freshness.FRESH if age <= 6 else Freshness.STALE, competition=_label(r),
                    example=f"{_label(r)}: read {age:.0f} h ago")
    return out


def _detail(rows: list[dict[str, Any]], at: datetime) -> tuple[DatasetFreshness, DatasetFreshness]:
    lineups = DatasetFreshness("lineups", "a match played in the last 7 days has its line-ups", "fixture")
    detail = DatasetFreshness("match_detail", "a match played in the last 7 days had its events and statistics "
                              "read after it ended", "fixture")
    per_fixture: dict[int, dict[str, Any]] = {}
    for r in rows:
        f = per_fixture.setdefault(int(r["provider_fixture_id"]), {"row": r, "sets": {}})
        if r["dataset"]:
            f["sets"][r["dataset"]] = r
    for pid, f in per_fixture.items():
        r = f["row"]
        sets: dict[str, dict[str, Any]] = f["sets"]
        ended = r["kickoff_at"].timestamp() + MATCH_ENDS_AFTER
        lu = sets.get("lineups")
        if r["cov_lineups"] is False:
            lineups.add(Freshness.UNAVAILABLE, competition=_label(r))
        elif lu is None:
            lineups.add(Freshness.STALE, competition=_label(r), example=f"fixture {pid}: never read")
        elif lu["block_present"] and (lu["rows_written"] or 0) > 0:
            lineups.add(Freshness.FRESH, competition=_label(r))
        elif lu["fetched_at"] is not None and lu["fetched_at"].timestamp() >= ended:
            lineups.add(Freshness.UNAVAILABLE, competition=_label(r))
        else:
            lineups.add(Freshness.STALE, competition=_label(r), example=f"fixture {pid}: read before kick-off only")
        ev = sets.get("events") or sets.get("team_statistics")
        if r["cov_events"] is False and r["cov_statistics"] is False:
            detail.add(Freshness.UNAVAILABLE, competition=_label(r))
        elif ev is None:
            detail.add(Freshness.STALE, competition=_label(r), example=f"fixture {pid}: detail never read")
        elif ev["fetched_at"] is not None and ev["fetched_at"].timestamp() >= ended:
            detail.add(Freshness.FRESH if ev["block_present"] else Freshness.UNAVAILABLE, competition=_label(r))
        else:
            detail.add(Freshness.STALE, competition=_label(r),
                       example=f"fixture {pid}: detail read {ev['fetched_at']:%H:%M}Z, before the end")
    return lineups, detail


def price_state(*, kickoff: datetime, at: datetime, last_capture: datetime | None, last_asked: datetime | None,
                covered: bool | None, windows: list[int] | None = None,
                tolerance: int | None = None) -> tuple[Freshness, str]:
    """Whether a match's pre-match price is as current as the capture plan says it should be.

    Prices are captured at fixed windows before kick-off (T-72h ... T-3h), aligned on the
    provider's three-hourly update; between two windows nothing newer exists to ask for. So a
    price is FRESH when it was captured at or after the most recent window the match has
    reached (with the planner's tolerance), and a match no window has reached yet is not due.
    Asked and answered with nothing is the provider not pricing it: UNAVAILABLE.
    """
    from fbi.core.config import settings

    windows = windows if windows is not None else settings.odds.prematch_windows
    tolerance = tolerance if tolerance is not None else settings.odds.odds_window_tolerance
    minutes = (kickoff - at).total_seconds() / 60
    reached = [w for w in windows if w >= minutes]
    if not reached:
        return Freshness.FRESH, "no capture window reached yet"
    due_from = kickoff.timestamp() - (min(reached) + tolerance) * 60
    if last_capture is not None and last_capture.timestamp() >= due_from:
        return Freshness.FRESH, f"captured at the T-{min(reached) // 60} h window or later"
    if last_capture is None and (last_asked is not None or covered is False):
        return Freshness.UNAVAILABLE, "asked; the provider had no prices" if last_asked else "not covered"
    if last_capture is None:
        return Freshness.STALE, f"the T-{min(reached) // 60} h window passed and it was never asked for"
    return Freshness.STALE, f"newest price {(at - last_capture).total_seconds() / 3600:.1f} h old; the " \
                            f"T-{min(reached) // 60} h window passed without a capture"


def _odds(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("odds_prematch", "a match in the next 72 h was priced at the most recent capture window "
                           "it reached (T-72/48/24/12/6/3 h, aligned on the provider's 3-hourly update)", "fixture")
    for r in rows:
        state, why = price_state(kickoff=r["kickoff_at"], at=at, last_capture=r["last_capture"],
                                 last_asked=r["last_asked"], covered=r["covered"])
        out.add(state, competition=_label(r), example=f"fixture {r['provider_fixture_id']}: {why}")
    return out


def _teams(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("teams", "identity (country, venue, logo) read in the last 120 days", "team")
    for r in rows:
        age = _age_h(at, r["source_fetched_at"])
        if age is None:
            out.add(Freshness.UNKNOWN, competition=_label(r), example=f"team {r['provider_team_id']}: never read")
        else:
            out.add(Freshness.FRESH if age <= 120 * 24 else Freshness.STALE, competition=_label(r))
    return out


def _people(rows: list[dict[str, Any]]) -> list[DatasetFreshness]:
    out = []
    for r in rows:
        players = r["dataset"] == "players"
        d = DatasetFreshness(str(r["dataset"]), "the profile of everyone in a line-up in the last 365 days was read "
                             "in the last 45 days (monthly sweep of /players/profiles)" if players else
                             "a profile (birth date or nationality, /coachs weekly per tracked team) exists for "
                             "every coach in a line-up in the last 365 days", "person")
        total, fresh, old = int(r["total"] or 0), int(r["profiled"] or 0), int(r["old_profile"] or 0)
        none = int(r.get("provider_none") or 0)
        d.add(Freshness.FRESH, fresh)
        d.add(Freshness.STALE, old, example=f"{old:,} profiles older than 45 days" if old else None)
        d.add(Freshness.UNAVAILABLE, none,
              example=f"{none:,} asked by id: the provider has no profile for them" if none else None)
        d.add(Freshness.UNKNOWN, total - fresh - old - none,
              example=f"{total - fresh - old - none:,} without a profile, not asked by id yet "
                      f"({total - int(r['known'] or 0):,} not even an identity row)")
        out.append(d)
    return out


def _squads(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("squads", "every team of a current season had its squad read in the last 8 days (weekly "
                           "round of /players/squads)", "team")
    for r in rows:
        age = _age_h(at, r["squad_checked_at"])
        asked = _age_h(at, r.get("asked_at"))
        if age is None and asked is not None and asked <= 8 * 24 and not r.get("asked_results"):
            out.add(Freshness.UNAVAILABLE, competition=_label(r),
                    example=f"team {r['provider_team_id']}: asked {asked / 24:.0f} days ago, the provider has no squad")
        elif age is None:
            out.add(Freshness.UNKNOWN, competition=_label(r), example=f"team {r['provider_team_id']}: never read")
        else:
            out.add(Freshness.FRESH if age <= 8 * 24 else Freshness.STALE, competition=_label(r),
                    example=f"team {r['provider_team_id']}: read {age / 24:.0f} days ago")
    return out


ELO_REFRESH_GRACE_HOURS = 7.0
"""The full Elo recompute runs every 6 hours; a match that ended since the last one is
waiting for the next, not missed."""


def _elo(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("elo", "every match finished in the last 30 days carries a rating once the next "
                           "6-hourly recompute has run; a match without a stored score cannot be rated", "fixture")
    for r in rows:
        if r["rated"]:
            out.add(Freshness.FRESH, competition=_label(r))
        elif not r.get("scored", True):
            out.add(Freshness.UNAVAILABLE, competition=_label(r),
                    example=f"{r['competition']}: fixture {r['provider_fixture_id']} has no stored score")
        else:
            ended = _age_h(at, r.get("kickoff_at"))
            pending = ended is not None and ended - MATCH_ENDS_AFTER / HOURS <= ELO_REFRESH_GRACE_HOURS
            out.add(Freshness.FRESH if pending else Freshness.STALE, competition=_label(r),
                    example=None if pending else f"{r['competition']}: fixture {r['provider_fixture_id']} unrated")
    return out


def _coverage(rows: list[dict[str, Any]], at: datetime) -> DatasetFreshness:
    out = DatasetFreshness("coverage", "the provider's coverage flags for each current season read in the last "
                           "8 days", "competition-season")
    for r in rows:
        age = _age_h(at, r["observed_at"])
        out.add(Freshness.UNKNOWN if age is None else Freshness.FRESH if age <= 8 * 24 else Freshness.STALE,
                competition=_label(r), example=f"{_label(r)}: read {age / 24:.0f} days ago" if age else None)
    return out


SIMPLE: tuple[tuple[str, Callable[[list[dict[str, Any]], datetime], DatasetFreshness]], ...] = (
    (FIXTURES_SQL, _fixtures), (RESULTS_SQL, _results), (LIVE_SQL, _live), (STANDINGS_SQL, _standings),
    (INJURIES_SQL, _injuries), (ODDS_SQL, _odds), (TEAMS_SQL, _teams), (ELO_SQL, _elo), (COVERAGE_SQL, _coverage),
    (SQUADS_SQL, _squads),
)


def measure(conn: psycopg.Connection, *, at: datetime) -> list[DatasetFreshness]:
    """Every dataset's freshness right now. Reads only; a few seconds on the full database."""
    out: list[DatasetFreshness] = []
    with conn.cursor(row_factory=dict_row) as cur:
        for sql, fn in SIMPLE:
            cur.execute(sql, {"at": at})
            out.append(fn(cur.fetchall(), at))
        cur.execute(DETAIL_SQL, {"at": at})
        out.extend(_detail(cur.fetchall(), at))
        cur.execute(PEOPLE_SQL, {"at": at})
        out.extend(_people(cur.fetchall()))
    order = ["fixtures", "results", "live", "standings", "injuries", "lineups", "match_detail", "odds_prematch",
             "elo", "teams", "players", "squads", "coaches", "coverage"]
    return sorted(out, key=lambda d: order.index(d.dataset) if d.dataset in order else 99)
