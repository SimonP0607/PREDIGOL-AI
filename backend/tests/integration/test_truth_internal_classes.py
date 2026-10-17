"""The database's own truth checks tell a real gap from one with a reason.

5 Oct 2026: the truth audit's 26 HIGH findings were 13 Elo "gaps" (quarantined duplicates, results the provider
contradicts, a match settled after the last refresh), 5 "missing results" (the provider's own score blocks
contradict each other, so the writer keeps none by design), 5 duplicate pairings the historical validation had
already quarantined and 3 "stale" fixtures the provider itself had not updated when we asked again. None was ours to
fix; each now has its own class, and a real gap is still HIGH."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.truth.audit import merge_internal
from fbi.truth.findings import Finding, Kind, Severity, Tally
from fbi.truth.internal import run_internal
from tests.integration.conftest import Seed

NOW = datetime(2030, 1, 15, 12, 0, tzinfo=UTC)  # after any refresh another test may leave behind
LEAGUE = 9931
TEAMS = (99311, 99312, 99313, 99314)
REFRESHED = NOW - timedelta(hours=1)


@pytest.fixture
def league(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        comp = cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                           "competition_type, tier, is_tracked) VALUES (%s, 'Classes League', 'league', 'club', "
                           "'domestic_league', 1, true) RETURNING id", (LEAGUE,)).fetchone()[0]  # type: ignore[index]
        season = cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) "
                             "VALUES (%s, 2026, true) RETURNING id", (comp,)).fetchone()[0]  # type: ignore[index]
        team = [cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                            (pid, f"Classes {pid}")).fetchone()[0] for pid in TEAMS]  # type: ignore[index]
        run = cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, started_at, finished_at) "
                          "VALUES ('classes-elo', 'elo_refresh', 'completed', %s, %s) RETURNING id",
                          (REFRESHED, REFRESHED + timedelta(minutes=1))).fetchone()[0]  # type: ignore[index]
        fx: dict[str, int] = {}

        def fixture(name: str, pid: int, home: int, away: int, kickoff: datetime, short: str,
                    fetched: datetime | None, result: tuple[int, int] | None = None,
                    result_fetched: datetime | None = None) -> None:
            group = {"FT": "finished", "AET": "finished", "NS": "scheduled"}[short]
            fx[name] = cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group, source_payload_hash, source_fetched_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (pid, season, team[home], team[away], kickoff, short, group, seed.payload_hash if fetched else None,
                 fetched)
            ).fetchone()[0]  # type: ignore[index]
            if result is not None:
                cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, "
                            "ft_goals_away, source_payload_hash, source_fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (fx[name], *result, *result, seed.payload_hash,
                             result_fetched or kickoff + timedelta(hours=3)))

        day = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
        fixture("rated", 993101, 0, 1, day, "FT", day + timedelta(hours=3), (1, 0))
        fixture("dup_a", 993102, 0, 1, day + timedelta(days=9), "FT", day, (2, 2))
        fixture("dup_b", 993103, 0, 1, day + timedelta(days=9, hours=8), "FT", day, (2, 2))
        fixture("dup_c", 993104, 2, 3, day + timedelta(days=11), "FT", day, (0, 1))
        fixture("dup_d", 993105, 2, 3, day + timedelta(days=11, hours=6), "FT", day, (0, 1))
        fixture("gap", 993106, 1, 2, day + timedelta(days=14), "FT", day + timedelta(days=14), (3, 1))
        fixture("contradiction", 993107, 3, 0, day + timedelta(days=19), "AET", day + timedelta(days=19))
        fixture("no_result", 993108, 1, 3, day + timedelta(days=21), "FT", day + timedelta(days=21))
        fixture("late", 993109, 2, 0, NOW - timedelta(hours=4), "FT", NOW - timedelta(minutes=30), (1, 1),
                result_fetched=NOW - timedelta(minutes=30))
        fixture("lag", 993110, 0, 2, NOW - timedelta(hours=10), "NS", NOW - timedelta(hours=1))
        fixture("silent", 993111, 1, 0, NOW - timedelta(hours=72), "NS", NOW - timedelta(hours=2))
        fixture("stale", 993112, 3, 2, NOW - timedelta(hours=6), "NS", NOW - timedelta(hours=7))
        for side, t in ((0, team[0]), (1, team[1])):
            cur.execute("INSERT INTO features.elo_ratings (elo_version, run_id, team_id, fixture_id, kickoff_at, "
                        "rating_before, rating_after, expected_score, actual_score, k_factor, margin_multiplier) "
                        "VALUES ('classes', %s, %s, %s, %s, 1500, 1510, 0.5, %s, 20, 1)",
                        (run, t, fx["rated"], day, 1.0 if side == 0 else 0.0))
        for name in ("dup_a", "dup_b", "contradiction"):
            cur.execute("INSERT INTO analytics.fixture_validation (fixture_id, state, rule_version, validated_at) "
                        "VALUES (%s, %s, 'classes', %s)",
                        (fx[name], "INGESTED" if name == "contradiction" else "QUARANTINED", NOW))
        cur.execute("INSERT INTO audit.data_quality_issues (code, severity, entity_type, provider_entity_id, field, "
                    "observed, fingerprint) VALUES ('PROVIDER_INCONSISTENCY', 'warning', 'fixture_result', 993107, "
                    "'ft_goals_home', 'fulltime 4-0 with a final of 2-0', 'classes-993107')")
    yield {"run": run, "fixtures": fx}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        ids = list(fx.values())
        cur.execute("DELETE FROM audit.data_quality_issues WHERE fingerprint = 'classes-993107'")
        cur.execute("DELETE FROM features.elo_ratings WHERE run_id = %s", (run,))
        cur.execute("DELETE FROM analytics.fixture_validation WHERE fixture_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM core.fixture_results WHERE fixture_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run,))
        cur.execute("DELETE FROM core.teams WHERE provider_team_id = ANY(%s)", (list(TEAMS),))
        cur.execute("DELETE FROM core.competition_seasons WHERE id = %s", (season,))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (comp,))


def mine(tally: Tally, pid: int) -> list[Finding]:
    return [f for f in tally.findings if f"fixture {pid} " in f.entity]


def test_each_unexplained_gap_is_high_and_each_explained_one_has_its_class(migrated_database: str,
                                                                          league: dict[str, Any]) -> None:
    with psycopg.connect(migrated_database) as conn:
        conn.read_only = True
        tallies = run_internal(conn, at=NOW)
    fixtures, results, elo = tallies["fixtures"], tallies["results"], tallies["elo"]

    dup_quarantined = mine(fixtures, 993102)
    assert [(f.kind, f.severity) for f in dup_quarantined] == [(Kind.INCONSISTENT, Severity.LOW)]
    assert "quarantined both" in dup_quarantined[0].note
    assert [(f.kind, f.severity) for f in mine(fixtures, 993104)] == [(Kind.INCONSISTENT, Severity.HIGH)], \
        "a duplicate nothing keeps out of the models is still HIGH"

    contradiction = mine(results, 993107)
    assert [(f.kind, f.severity) for f in contradiction] == [(Kind.PROVIDER_CONTRADICTION, Severity.MEDIUM)]
    assert contradiction[0].api is not None and "fulltime 4-0" in contradiction[0].api
    assert [(f.kind, f.severity) for f in mine(results, 993108)] == [(Kind.MISSING_IN_DB, Severity.HIGH)], \
        "no result and no provider contradiction: ours"

    assert [(f.kind, f.severity) for f in mine(fixtures, 993110)] == [(Kind.PROVIDER_LAG, Severity.INFO)]
    assert [(f.kind, f.severity) for f in mine(fixtures, 993111)] == [(Kind.PROVIDER_LAG, Severity.MEDIUM)]
    stale = mine(fixtures, 993112)
    assert [(f.kind, f.severity) for f in stale] == [(Kind.STALE, Severity.HIGH)], "never asked again: ours"
    assert "not asked again" in stale[0].note

    gaps = [f for f in elo.findings if f"competition {LEAGUE} " in f.entity]
    assert len(gaps) == 1 and gaps[0].severity == Severity.HIGH
    assert gaps[0].note.startswith("3 finished with a result"), "the gap and the two unhandled duplicates"
    explained = next(n for n in elo.notes if "unrated by design" in n)
    assert "excluded by the historical validation" in explained and "unexplained" in explained


def test_the_provider_sample_and_the_database_do_not_report_one_thing_twice() -> None:
    entity = "fixture 993110 (Classes League 2026)"
    target = Tally("fixtures")
    target.add(Finding.of("fixtures", entity, "status_short", Kind.PROVIDER_LAG, Severity.INFO, api="NS", db="NS"))
    internal = Tally("fixtures")
    internal.add(Finding.of("fixtures", entity, "status_short", Kind.PROVIDER_LAG, Severity.INFO, api="NS", db="NS"))
    internal.add(Finding.of("fixtures", "fixture 993112 (Classes League 2026)", "status_short", Kind.STALE,
                            Severity.HIGH))
    internal.counts[("identity", "inconsistent", "low")] = 900  # beyond the kept examples
    internal.checked, internal.matched = 10, 8
    merge_internal(target, internal)
    assert [f.entity for f in target.findings].count(entity) == 1
    assert target.counts[("status_short", "provider_lag", "info")] == 1
    assert target.counts[("status_short", "stale", "high")] == 1
    assert target.counts[("identity", "inconsistent", "low")] == 900, "counts beyond the kept examples survive"
    assert (target.checked, target.matched) == (10, 8)
