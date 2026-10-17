"""Probe a candidate league before it is tracked: what the provider really serves, and whether it adds up.

The coverage flags (``raw.league_coverage``) say what a league *should* have. A probe asks what it has, for the
current season, in at most three requests - every answer stored in RAW and indexed like any other:

1. ``/fixtures?league&season``: the calendar, statuses and scores;
2. ``/fixtures?ids=`` for up to 20 of the latest finished matches: events, line-ups, team and player statistics;
3. ``/standings?league&season``: the table.

Checks, all on the provider's own answers (nothing is repaired, nothing is written outside RAW and the run ledger):

* **results** - a finished match without a readable score (the results normalizer refused its score blocks) is a
  contradiction, counted;
* **detail** - per sampled match: events present; both line-ups with eleven starters; team statistics for both
  sides; player statistics for at least 22 players; and, for a match decided in regular time, whether the goal
  events add up to the score (a missed penalty is not a goal);
* **table** - the games the table says were played (half the sum of ``played``) against the finished matches of the
  season. A league with play-off phases legitimately differs; it is shown, not scored.

``data_score`` is the mean of the four detail shares (events, line-ups, team statistics, player statistics);
``consistency`` is the share of sampled regular-time finishes whose goal events match the score. Neither decides on
its own: the selection reads them with the market's liquidity and the season's remaining length.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from fbi.core.errors import ProviderError
from fbi.ingestion.fixtures import status_group
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football.details import FixtureDetail
from fbi.providers.api_football.provider import MAX_IDS

SAMPLE = MAX_IDS
STARTERS = 11
PLAYERS_MIN = 22
REGULAR_TIME = frozenset({"FT"})


@dataclass
class LeagueProbe:
    league: int
    season: int
    requests: int = 0
    fixtures: int = 0
    finished: int = 0
    upcoming: int = 0
    unresolved_results: int = 0
    sampled: int = 0
    with_events: int = 0
    with_lineups: int = 0
    with_team_stats: int = 0
    with_player_stats: int = 0
    regular_time_sampled: int = 0
    goals_match_events: int = 0
    table_rows: int = 0
    table_groups: int = 0
    table_games: int | None = None
    errors: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def share(self, n: int) -> float | None:
        return round(n / self.sampled, 3) if self.sampled else None

    @property
    def data_score(self) -> float | None:
        if not self.sampled:
            return None
        parts = (self.with_events, self.with_lineups, self.with_team_stats, self.with_player_stats)
        return round(sum(parts) / (4 * self.sampled), 3)

    @property
    def consistency(self) -> float | None:
        return round(self.goals_match_events / self.regular_time_sampled, 3) if self.regular_time_sampled else None

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "data_score": self.data_score, "consistency": self.consistency,
                "events": self.share(self.with_events), "lineups": self.share(self.with_lineups),
                "team_stats": self.share(self.with_team_stats), "player_stats": self.share(self.with_player_stats)}


def goals_in_events(detail: FixtureDetail) -> int:
    return sum(1 for e in detail.events if e.event_type == "Goal" and (e.detail or "") != "Missed Penalty")


def lineups_complete(detail: FixtureDetail) -> bool:
    return len(detail.lineups) == 2 and all(sum(p.is_starter for p in lu.players) >= STARTERS
                                            for lu in detail.lineups)


def team_stats_complete(detail: FixtureDetail) -> bool:
    return len(detail.stats) == 2 and all(any(v is not None for v in s.values.values()) for s in detail.stats)


def judge_detail(probe: LeagueProbe, details: Sequence[FixtureDetail], scores: dict[int, tuple[str, int, int]]) -> None:
    """Fold one /fixtures?ids= answer into the probe. ``scores``: fixture -> (status, goals home, goals away)."""
    for d in details:
        probe.sampled += 1
        probe.with_events += int(bool(d.events))
        probe.with_lineups += int(lineups_complete(d))
        probe.with_team_stats += int(team_stats_complete(d))
        probe.with_player_stats += int(len(d.players) >= PLAYERS_MIN)
        status, home, away = scores.get(d.provider_fixture_id, ("", 0, 0))
        if status in REGULAR_TIME and d.events:
            probe.regular_time_sampled += 1
            found = goals_in_events(d)
            if found == home + away:
                probe.goals_match_events += 1
            elif len(probe.examples) < 5:
                probe.examples.append(f"fixture {d.provider_fixture_id}: score {home}-{away}, {found} goal events")


async def probe_league(provider: Any, league: int, season: int, *, at: datetime) -> tuple[LeagueProbe, list[Any]]:
    """Three requests at most. Returns the probe and the raw responses (for the ledger)."""
    probe = LeagueProbe(league, season)
    raws: list[Any] = []
    try:
        refs, raw = await provider.fetch_fixtures(league_id=league, season=season)
    except ProviderError as exc:
        probe.requests += 1
        probe.errors.append(f"/fixtures: {exc}")
        return probe, raws
    probe.requests += 1
    raws.append(raw)
    results = {r.provider_fixture_id: r for r in provider.parse_results(raw.body)}
    probe.fixtures = len(refs)
    finished = [r for r in refs if status_group(r.status_short) == "finished"]
    probe.finished = len(finished)
    probe.upcoming = sum(1 for r in refs if status_group(r.status_short) == "scheduled" and r.kickoff_at > at)
    probe.unresolved_results = sum(1 for r in finished if r.provider_fixture_id not in results)
    latest = sorted((r for r in finished if r.provider_fixture_id in results), key=lambda r: r.kickoff_at)[-SAMPLE:]
    if latest:
        scores = {r.provider_fixture_id: (results[r.provider_fixture_id].status_short,
                                          results[r.provider_fixture_id].goals_home,
                                          results[r.provider_fixture_id].goals_away) for r in latest}
        try:
            details, draw = await provider.fetch_fixture_details(provider_fixture_ids=[r.provider_fixture_id
                                                                                       for r in latest])
            raws.append(draw)
            judge_detail(probe, details, scores)
        except ProviderError as exc:
            probe.errors.append(f"/fixtures?ids: {exc}")
        probe.requests += 1
    try:
        table, sraw = await provider.fetch_standings(league_id=league, season=season)
        raws.append(sraw)
        rows = [t for t in table if (t.provider_league_id, t.season) == (league, season)]
        probe.table_rows = len(rows)
        probe.table_groups = len({t.group for t in rows})
        if probe.table_groups == 1:
            probe.table_games = sum(t.played for t in rows) // 2
    except ProviderError as exc:
        probe.errors.append(f"/standings: {exc}")
    probe.requests += 1
    return probe, raws


async def probe_leagues(conn: psycopg.Connection[Any], provider: Any, targets: Sequence[tuple[int, int]], *,
                        at: datetime, max_requests: int) -> tuple[list[LeagueProbe], int]:
    """Probe (league, season) pairs in order until ``max_requests`` would be passed. One ledger run, payloads
    indexed. Returns the probes and the run id."""
    ledger = RunLedger(conn)
    run_id = ledger.open("league_probe", params={"leagues": len(targets), "max_requests": max_requests},
                         scheduled_for=at)
    counters = RunCounters()
    out: list[LeagueProbe] = []
    try:
        for league, season in targets:
            if counters.api_calls + 3 > max_requests:
                counters.stopped_early = f"request cap {max_requests}: {len(targets) - len(out)} league(s) not probed"
                break
            probe, raws = await probe_league(provider, league, season, at=at)
            counters.api_calls += probe.requests
            counters.payloads_stored += ledger.record_payloads(run_id, raws)
            counters.errors.extend(f"{league}/{season} {e}" for e in probe.errors)
            out.append(probe)
            conn.commit()
    finally:
        ledger.close(run_id, counters, notes=f"{len(out)} league(s) probed, {counters.api_calls} requests")
        conn.commit()
    return out, run_id
