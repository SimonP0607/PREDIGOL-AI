"""The planner bug, reproduced, and the invariant that replaces it.

    "fixture exists" is NOT proof that "fixture details exist"

1,893 played fixtures had no detail of any kind while every task row said their
seasons were complete. Three separate holes produced that, and each has a test
here that fails against the old code:

  * seed_plan expanded detail units only when the FIXTURES unit was newly
    created, so a season a previous plan had already stored got none;
  * expand_detail_batches read "covered" from task batch keys regardless of
    status, so a pending, failed or refused unit counted as done;
  * nothing recorded what a payload actually carried, so an empty table meant
    "not published", "never asked" and "asked and failed" all at once.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.ingestion.backfill import expand_detail_batches
from fbi.ingestion.details import apply_fixture_details
from fbi.migration.completeness import (
    dataset_completeness,
    fixtures_missing_detail,
    season_gaps,
)
from fbi.migration.planner import MigrationPlan, SeasonPlan, UnitCost
from fbi.migration.units import seed_plan
from fbi.providers.api_football.details import (
    FixtureDetail,
    LineupPlayerRef,
    LineupRef,
    TeamStatsRef,
)
from tests.integration.conftest import Seed

KO = datetime(2026, 2, 1, 15, 0, tzinfo=UTC)
FETCHED = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
LEAGUE = 39
SEASON = 2025


@pytest.fixture(autouse=True)
def clean_slate(db: psycopg.Connection) -> Iterator[None]:
    """seed_plan and expand_detail_batches commit, so this module cannot rely on
    the db fixture's rollback. Everything it creates is named and removed."""
    yield
    db.rollback()  # a test that failed mid-statement leaves the transaction aborted
    with db.cursor() as cur:
        cur.execute("DELETE FROM audit.data_quality_issues")
        cur.execute("DELETE FROM raw.backfill_tasks WHERE provider_league_id = %s", (LEAGUE,))
        cur.execute("DELETE FROM raw.league_coverage WHERE provider_league_id = %s", (LEAGUE,))
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 81000 AND 82999")
        cur.execute("UPDATE core.competitions SET tier = NULL WHERE provider_league_id = %s", (LEAGUE,))
    db.commit()


@pytest.fixture()
def played(db: psycopg.Connection, seed: Seed) -> list[int]:
    """Six finished fixtures of the seeded competition-season, none with detail."""
    ids = []
    with db.cursor() as cur:
        cur.execute("UPDATE core.competitions SET tier = 1 WHERE id = %s", (seed.competition_id,))
        for i in range(6):
            cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                "away_team_id, kickoff_at, status_short, status_group) "
                "VALUES (%s,%s,%s,%s,%s,'FT','finished') RETURNING provider_fixture_id",
                (81000 + i, seed.season_id, seed.home_team_id, seed.away_team_id,
                 KO + timedelta(days=7 * i)),
            )
            row = cur.fetchone()
            assert row is not None
            ids.append(int(row[0]))
    db.commit()  # seed_plan commits, so these have to be visible to it
    return ids


def _plan() -> MigrationPlan:
    units = [UnitCost("fixtures_season", 1, 1.0, "one page"),
             UnitCost("fixture_details", 1, 1.0, "twenty per request")]
    season = SeasonPlan(tier=1, league_id=LEAGUE, name="Premier League", season=SEASON,
                        fixtures=6, fixtures_source="stored", coverage="verified", units=units)
    return MigrationPlan(tiers=(1,), ids_batching=True, with_optional=False, seasons=[season],
                         global_units=[])


def _detail(fixture: int, team: int, *, blocks: frozenset[str], starters: int = 11) -> FixtureDetail:
    players = tuple(
        LineupPlayerRef(provider_player_id=7000 + n, name=f"P{n}", number=n + 1, position="M",
                        grid=None, is_starter=n < starters)
        for n in range(starters + 7)
    )
    return FixtureDetail(
        provider_fixture_id=fixture,
        stats=(TeamStatsRef(provider_fixture_id=fixture, provider_team_id=team,
                            values={"shots": 11, "shots_on_target": 4}),),
        events=(),
        lineups=(LineupRef(provider_fixture_id=fixture, provider_team_id=team, formation="4-3-3",
                           provider_coach_id=55, coach_name="A Coach", players=players),),
        players=(),
        blocks_present=blocks,
    )


def _team_provider_id(db: psycopg.Connection, seed: Seed) -> int:
    with db.cursor() as cur:
        cur.execute("SELECT provider_team_id FROM core.teams WHERE id = %s", (seed.home_team_id,))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ── hole 1: a season already stored got no detail units ─────────────────────


def test_a_season_whose_fixtures_are_already_stored_still_gets_detail_units(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    """The if/elif. Seeding the plan twice used to create the fixtures unit on the
    first pass and then, on every later pass, take the same branch, hit ON
    CONFLICT DO NOTHING, and expand nothing."""
    first = seed_plan(db, _plan(), plan_id=None, current_season=SEASON)
    assert first.by_kind.get("fixtures_season") == 1
    assert first.detail_units == 1, "six played fixtures, twenty per batch: one unit"

    second = seed_plan(db, _plan(), plan_id=None, current_season=SEASON)
    assert second.created == 0, "nothing new to create"
    assert second.detail_units == 0, "and nothing missing to expand"

    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw.backfill_tasks WHERE kind = 'fixture_details'")
        assert cur.fetchone() == (1,)


def test_seeding_a_plan_for_a_season_stored_by_an_earlier_plan_expands_detail(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    """The exact shape of the failure: the fixtures unit exists and is DONE from a
    previous plan, and the new plan must still create the detail units."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, "
            " params, status, last_payload_hash, completed_at) "
            "VALUES ('fixtures_season',%s,%s,100,'/fixtures',%s,'done',%s,now())",
            (LEAGUE, SEASON, '{"league": 39, "season": 2025, "then_details": true}', seed.payload_hash),
        )
    db.commit()
    report = seed_plan(db, _plan(), plan_id=None, current_season=SEASON)
    assert report.by_kind.get("fixtures_season") is None, "the fixtures unit already existed"
    assert report.detail_units == 1, "and the detail units were still created"


# ── hole 2: a failed unit counted as covered ────────────────────────────────


def test_a_failed_detail_unit_does_not_count_as_covered(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    """Coverage is what was APPLIED, not what was once asked for. A unit whose
    request failed left the fixtures uncovered and must be regenerated."""
    key = "-".join(str(i) for i in played)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, "
            " params, batch_key, status, last_error) VALUES ('fixture_details',%s,%s,100,'/fixtures',"
            " '{}', %s, 'failed', 'connection reset')", (LEAGUE, SEASON, key)
        )
    assert fixtures_missing_detail(db, league_id=LEAGUE, season=SEASON) == played
    assert expand_detail_batches(db, league_id=LEAGUE, season=SEASON, priority=100) == 1


def test_a_pending_detail_unit_is_not_duplicated(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    """Regenerating must be idempotent: the same batch key already exists, so
    add_unit adds nothing."""
    assert expand_detail_batches(db, league_id=LEAGUE, season=SEASON, priority=100) == 1
    assert expand_detail_batches(db, league_id=LEAGUE, season=SEASON, priority=100) == 0


def test_a_fixture_whose_detail_was_applied_is_not_requested_again(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    team = _team_provider_id(db, seed)
    apply_fixture_details(
        db, [_detail(played[0], team, blocks=frozenset({"statistics", "lineups", "events", "players"}))],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    assert fixtures_missing_detail(db, league_id=LEAGUE, season=SEASON) == played[1:]


# ── hole 3: an empty table meant three different things ─────────────────────


def test_a_block_the_provider_did_not_send_is_recorded_and_not_asked_for_again(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    """A league-season without lineups coverage has no line-ups block. Treating
    that as "missing" would re-request every fixture for ever."""
    team = _team_provider_id(db, seed)
    report = apply_fixture_details(
        db, [_detail(played[0], team, blocks=frozenset({"statistics"}))],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    assert report.coverage_rows == 4, "all four datasets get a row, including the absent ones"
    with db.cursor() as cur:
        cur.execute("SELECT dataset, block_present, rows_written FROM core.fixture_detail_coverage "
                    "WHERE fixture_id = (SELECT id FROM core.fixtures WHERE provider_fixture_id = %s) "
                    "ORDER BY dataset", (played[0],))
        assert cur.fetchall() == [("events", False, 0), ("lineups", False, 0),
                                  ("player_statistics", False, 0), ("team_statistics", True, 1)]
        cur.execute("SELECT field FROM audit.data_quality_issues WHERE code = 'MISSING_DETAIL' "
                    "ORDER BY field")
        assert [r[0] for r in cur.fetchall()] == ["events", "lineups", "player_statistics"]
    assert played[0] not in fixtures_missing_detail(db, league_id=LEAGUE, season=SEASON), \
        "one request already answered that question, and the answer was no"


def test_completeness_is_measured_per_dataset(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    """Statistics complete and line-ups absent is a real state, and the old model
    - one 'done' flag per season - could not express it."""
    team = _team_provider_id(db, seed)
    for fixture in played:
        apply_fixture_details(
            db, [_detail(fixture, team, blocks=frozenset({"statistics"}))],
            payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
        )
    rows = {c.dataset: c for c in dataset_completeness(db, league_id=LEAGUE, season=SEASON)}
    assert set(rows) == {"events", "lineups", "team_statistics", "player_statistics"}
    assert rows["team_statistics"].with_rows == 6 and rows["team_statistics"].ratio == 1.0
    assert rows["team_statistics"].state == "complete"
    assert rows["lineups"].with_rows == 0 and rows["lineups"].not_published == 6
    assert rows["lineups"].never_fetched == 0, "fetched, and not published"
    assert rows["lineups"].state == "delivered_incomplete"
    assert rows["lineups"].outstanding == 0, "nothing left to request"


def test_a_season_with_nothing_played_has_no_percentage(
    db: psycopg.Connection, seed: Seed
) -> None:
    """played = 0 is not 0% and not 100%. The view does not invent a denominator."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
            "away_team_id, kickoff_at, status_short, status_group) "
            "VALUES (82000,%s,%s,%s,%s,'NS','scheduled')",
            (seed.season_id, seed.home_team_id, seed.away_team_id, KO),
        )
    assert dataset_completeness(db, league_id=LEAGUE, season=SEASON) == []


def test_the_provider_s_own_coverage_flag_makes_a_gap_unsupported(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    """If the provider says a league-season has no player statistics, the absence
    is not our gap and the planner must not price it as work."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.league_coverage (provider_league_id, season, events, lineups, "
            " statistics_fixtures, statistics_players, payload_hash, observed_at) "
            "VALUES (%s,%s,true,true,true,false,%s,%s)",
            (LEAGUE, SEASON, seed.payload_hash, FETCHED),
        )
    rows = {c.dataset: c for c in dataset_completeness(db, league_id=LEAGUE, season=SEASON)}
    assert rows["player_statistics"].provider_claims is False
    assert rows["player_statistics"].state == "unsupported"
    assert rows["events"].provider_claims is True and rows["events"].state == "pending"


# ── the report the bug made impossible ──────────────────────────────────────


def test_the_outstanding_work_can_be_counted_and_priced(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    gaps = {(g.provider_league_id, g.season): g for g in season_gaps(db, tier=1)}
    gap = gaps[(LEAGUE, SEASON)]
    assert (gap.played, gap.missing, gap.batches) == (6, 6, 1)

    team = _team_provider_id(db, seed)
    apply_fixture_details(
        db, [_detail(played[0], team, blocks=frozenset({"statistics"}))],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    after = {(g.provider_league_id, g.season): g for g in season_gaps(db, tier=1)}[(LEAGUE, SEASON)]
    assert (after.played, after.missing) == (6, 5)


def test_a_season_with_no_gap_is_not_reported(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    team = _team_provider_id(db, seed)
    for fixture in played:
        apply_fixture_details(
            db, [_detail(fixture, team, blocks=frozenset({"statistics"}))],
            payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
        )
    assert [g for g in season_gaps(db, tier=1) if g.provider_league_id == LEAGUE] == []


# ── line-ups are not filled in ──────────────────────────────────────────────


def test_a_short_lineup_is_stored_as_received_and_recorded(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    """Fifteen line-ups arrived with fewer than eleven starters. They are not
    padded: the count that came is what is stored, and the shortfall is a
    recorded fact about the provider's payload."""
    team = _team_provider_id(db, seed)
    apply_fixture_details(
        db, [_detail(played[0], team, blocks=frozenset({"lineups"}), starters=9)],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FILTER (WHERE is_starter), count(*) "
                    "FROM core.fixture_lineup_players")
        assert cur.fetchone() == (9, 16), "stored exactly as received"
        cur.execute("SELECT field, observed, expected, detail FROM audit.data_quality_issues "
                    "WHERE code = 'INCOMPLETE_LINEUP'")
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][:3] == ("starters", "9", "11")
    assert "9 starters and 7 substitutes" in rows[0][3]


def test_a_complete_lineup_records_nothing(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    team = _team_provider_id(db, seed)
    apply_fixture_details(
        db, [_detail(played[0], team, blocks=frozenset({"lineups"}))],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit.data_quality_issues WHERE code = 'INCOMPLETE_LINEUP'")
        assert cur.fetchone() == (0,)


def test_a_refused_unit_is_left_alone(db: psycopg.Connection, seed: Seed, played: list[int]) -> None:
    """The provider or the plan said no. Reviving it in a loop is how quota is
    wasted on an answer we already have."""
    key = "-".join(str(i) for i in played)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, "
            " params, batch_key, status, last_error, retryable) VALUES ('fixture_details',%s,%s,100,"
            " '/fixtures','{}',%s,'refused','this plan does not allow ids=', false)",
            (LEAGUE, SEASON, key),
        )
    db.commit()
    assert expand_detail_batches(db, league_id=LEAGUE, season=SEASON, priority=100) == 0
    with db.cursor() as cur:
        cur.execute("SELECT status FROM raw.backfill_tasks WHERE kind = 'fixture_details'")
        assert cur.fetchone() == ("refused",)


def test_a_unit_that_failed_unretryably_is_left_alone(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    key = "-".join(str(i) for i in played)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, "
            " params, batch_key, status, last_error, retryable) VALUES ('fixture_details',%s,%s,100,"
            " '/fixtures','{}',%s,'failed','the payload was not valid JSON', false)",
            (LEAGUE, SEASON, key),
        )
    db.commit()
    assert expand_detail_batches(db, league_id=LEAGUE, season=SEASON, priority=100) == 0


def test_reviving_a_failed_unit_clears_the_in_flight_marker(
    db: psycopg.Connection, seed: Seed, played: list[int]
) -> None:
    key = "-".join(str(i) for i in played)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, "
            " params, batch_key, status, last_error, started_at) VALUES ('fixture_details',%s,%s,100,"
            " '/fixtures','{}',%s,'failed','timeout', now())",
            (LEAGUE, SEASON, key),
        )
    db.commit()
    assert expand_detail_batches(db, league_id=LEAGUE, season=SEASON, priority=100) == 1
    with db.cursor() as cur:
        cur.execute("SELECT status, started_at, last_error IS NOT NULL FROM raw.backfill_tasks "
                    "WHERE kind = 'fixture_details'")
        assert cur.fetchone() == ("pending", None, True), \
            "back in the queue, and the reason it failed is kept"
