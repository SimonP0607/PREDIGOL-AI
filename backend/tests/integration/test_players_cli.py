"""``player-engine-v1`` (IA-017, shadow) against the real schema: the played matches seeded in ``core.fixture_player_stats`` are read as
of a moment (nothing read after it, nothing of the match itself), a line-up counts only once it was fetched, an absence only once it was
observed, and the command's ``show`` and ``evaluate`` report with their sample sizes. The transaction is rolled back afterwards."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from scripts import ia_players as cli

from fbi.players import families as fam
from fbi.players import history as hist

from .conftest import Seed
from .helpers import scalar

pytestmark = pytest.mark.integration

T0 = datetime(2026, 3, 7, 15, 0, tzinfo=UTC)
ROUNDS = 12
_fixture = itertools.count(8_810_000)
POSITIONS = ["G", "D", "D", "D", "D", "M", "M", "M", "F", "F", "F", "M", "F", "D"]


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        self.home, self.away = seed.home_team_id, seed.away_team_id
        self.played: list[int] = []
        for r in range(ROUNDS):
            home, away = (self.home, self.away) if r % 2 == 0 else (self.away, self.home)
            fid = self.fixture(home, away, T0 + timedelta(days=7 * r), status="finished")
            self.played.append(fid)
            for side, team in (("home", home), ("away", away)):
                self.stats(fid, side, team, T0 + timedelta(days=7 * r, hours=3))
        self.kickoff = T0 + timedelta(days=7 * ROUNDS)
        self.target = self.fixture(self.home, self.away, self.kickoff, status="scheduled")

    def fixture(self, home: int, away: int, at: datetime, *, status: str) -> int:
        return int(scalar(self.db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_group) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (next(_fixture), self.seed.season_id, home, away, at, status))))

    def man(self, team: int, j: int) -> int:
        return 7_000_000 + team * 100 + j

    def stats(self, fid: int, side: str, team: int, fetched: datetime) -> None:
        for j in range(14):
            starter = j < 11
            minutes = 90 if starter else (15 if j == 11 else None)
            self.db.execute(
                "INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, is_substitute, goals, "
                "assists, shots_total, shots_on, fouls_committed, yellow_cards, red_cards, saves, payload_hash, fetched_at) "
                "VALUES (%s, 'api-football', %s, %s, %s, %s, %s, 0, %s, %s, 1, 0, 0, %s, %s, %s)",
                (fid, self.man(team, j), side, minutes, not starter, 1 if j == 9 and fid % 2 == 0 else 0, 3 if j >= 8 else 0,
                 1 if j >= 8 else 0, 4 if j == 0 else None, self.seed.payload_hash, fetched))
        self.db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                        "VALUES (%s, %s, 'api-football', %s, %s)", (fid, side, self.seed.payload_hash, fetched))
        for j in range(14):
            self.db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, position, "
                            "is_starter) VALUES (%s, %s, 'api-football', %s, %s, %s)", (fid, side, self.man(team, j), POSITIONS[j], j < 11))

    def lineup(self, side: str, team: int, fetched: datetime, starters: list[int], bench: list[int]) -> None:
        self.db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                        "VALUES (%s, %s, 'api-football', %s, %s)", (self.target, side, self.seed.payload_hash, fetched))
        for j in starters + bench:
            self.db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, position, "
                            "is_starter) VALUES (%s, %s, 'api-football', %s, %s, %s)",
                            (self.target, side, self.man(team, j), POSITIONS[j], j in starters))

    def absence(self, team: int, j: int, at: datetime, status: str = "LISTED", kind: str = "Missing Fixture") -> None:
        self.db.execute("INSERT INTO core.player_availability_obs (fixture_id, source, provider_player_id, observed_at, status, "
                        "provider_fixture_id, absence_type, payload_hash, origin, normalizer_version) "
                        "VALUES (%s, 'api-football', %s, %s, %s, 1, %s, %s, 'answer', 'test')",
                        (self.target, self.man(team, j), at, status, kind, self.seed.payload_hash))


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


def players(doc: dict[str, Any], side: str) -> dict[int, dict[str, Any]]:
    return {p["player_id"]: p for p in doc["sides"][side]["players"]}


def test_before_the_lineup_the_regulars_are_predicted_and_nothing_of_the_match_is_read(world: World) -> None:
    at = world.kickoff - timedelta(hours=3)
    doc, code = cli.show(world.db, world.target, at=at)
    assert code == cli.OK and doc["shadow"] is True and doc["version"] == "player-engine-v1"
    assert doc["matches_in_history"] == ROUNDS
    home = players(doc, "home")
    assert set(home) == {world.man(world.home, j) for j in range(14)}
    keeper, unused = home[world.man(world.home, 0)], home[world.man(world.home, 13)]
    assert keeper["availability"]["basis"] == "predicted" and keeper["availability"]["p_start"] > 0.8
    assert unused["availability"]["p_start"] < 0.2
    assert [p["family"] for p in keeper["props"]] == ["keeper_saves"]
    assert all(p["status"] == fam.SHADOW for man in home.values() for p in man["props"])
    assert doc["sides"]["home"]["lineup_confirmed"] is False
    verdicts = {f["family"]: f for f in doc["calibration_window"]["families"]}
    assert all(f["verdict"] == fam.NOT_MODELABLE for f in verdicts.values())  # a dozen matches: no family has the data
    text = cli.render("show", doc)
    assert "not confirmed" in text and "NOT_MODELABLE" in text


def test_a_lineup_counts_once_it_was_fetched(world: World) -> None:
    fetched = world.kickoff - timedelta(minutes=60)
    world.lineup("home", world.home, fetched, starters=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12], bench=[10, 11])
    before, _ = cli.show(world.db, world.target, at=fetched - timedelta(minutes=1))
    assert before["sides"]["home"]["lineup_confirmed"] is False
    after, _ = cli.show(world.db, world.target, at=fetched + timedelta(minutes=1))
    assert after["sides"]["home"]["lineup_confirmed"] is True and after["sides"]["away"]["lineup_confirmed"] is False
    home = players(after, "home")
    assert set(home) == {world.man(world.home, j) for j in [*range(13)]}  # the man left off (13) is not a candidate any more
    assert home[world.man(world.home, 12)]["availability"]["basis"] == "confirmed_starter"
    assert home[world.man(world.home, 12)]["availability"]["p_start"] == 1.0
    bench = home[world.man(world.home, 10)]["availability"]
    assert bench["basis"] == "confirmed_bench" and bench["p_start"] == 0.0


def test_an_absence_counts_once_it_was_observed_and_until_it_was_cleared(world: World) -> None:
    listed = world.kickoff - timedelta(days=2)
    world.absence(world.home, 9, listed)
    world.absence(world.home, 9, world.kickoff - timedelta(hours=5), status="CLEARED")
    striker = world.man(world.home, 9)
    early, _ = cli.show(world.db, world.target, at=listed - timedelta(hours=1))
    assert players(early, "home")[striker]["availability"]["basis"] == "predicted"
    out, _ = cli.show(world.db, world.target, at=listed + timedelta(hours=1))
    a = players(out, "home")[striker]["availability"]
    assert a["basis"] == "out" and a["p_play"] == 0.0
    assert all(v == 0.0 for p in players(out, "home")[striker]["props"] for v in p["p_over"].values())
    back, _ = cli.show(world.db, world.target, at=world.kickoff - timedelta(hours=4))
    assert players(back, "home")[striker]["availability"]["basis"] == "predicted"


def test_a_match_read_after_the_moment_is_not_in_the_history(world: World) -> None:
    last = world.played[-1]
    ko = scalar(world.db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (last,)))
    at = ko + timedelta(hours=20)
    world.db.execute("UPDATE core.fixture_player_stats SET fetched_at = %s WHERE fixture_id = %s", (at + timedelta(hours=1), last))
    doc, _ = cli.show(world.db, world.target, at=at)
    assert doc["matches_in_history"] == ROUNDS - 1
    # read again long after (the post-match job): the statistics existed within two days of the kick-off
    world.db.execute("UPDATE core.fixture_player_stats SET fetched_at = %s WHERE fixture_id = %s", (ko + timedelta(days=30), last))
    doc, _ = cli.show(world.db, world.target, at=ko + timedelta(days=3))
    assert doc["matches_in_history"] == ROUNDS
    assert hist.available_at(ko, ko + timedelta(days=30)) == ko + timedelta(hours=48)


def test_a_past_match_is_forecast_as_of_its_kickoff(world: World) -> None:
    last = world.played[-1]
    doc, code = cli.show(world.db, last, at=datetime(2030, 1, 1, tzinfo=UTC))
    assert code == cli.OK and doc["clamped_to_kickoff"] is True
    assert doc["matches_in_history"] == ROUNDS - 1  # never itself


def test_goal_shares_follow_the_team_expected_goals(world: World) -> None:
    doc, _ = cli.show(world.db, world.target, at=world.kickoff - timedelta(hours=3), team_xg=(1.7, 0.9))
    for side, xg in (("home", 1.7), ("away", 0.9)):
        total = sum(p["mean"] for man in doc["sides"][side]["players"] for p in man["props"] if p["family"] == "player_goals")
        assert total == pytest.approx(xg, rel=1e-3)


def test_evaluate_states_its_samples(world: World) -> None:
    doc, code = cli.evaluate(world.db, T0 + timedelta(days=28), T0 + timedelta(days=7 * ROUNDS))
    assert code == cli.OK
    assert doc["fixtures_evaluated"] == ROUNDS - 4 and doc["sides_evaluated"] == 2 * (ROUNDS - 4)
    assert doc["availability"]["start"]["n"] > 0
    by = {f["family"]: f for f in doc["families"]}
    assert by["keeper_saves"]["starters"] == 2 * (ROUNDS - 4) and by["keeper_saves"]["coverage"] == 1.0
    assert by["player_shots"]["player_matches"] == 2 * (ROUNDS - 4) * 10
    assert all(f["verdict"] == fam.NOT_MODELABLE and f["reasons"] for f in by.values())
    json.dumps(doc, default=str)  # the --json report
    assert "NOT_MODELABLE" in cli.render("evaluate", doc)


def test_the_command_refuses_what_it_cannot_run(migrated_database: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["show", "--fixture", "987654321", "--dsn", migrated_database, "--json"]) == cli.CANNOT
    assert "unknown" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["evaluate", "--from", "2026-01-01"])
    with psycopg.connect(migrated_database) as conn:
        doc, code = cli.evaluate(conn, datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))
    assert code == cli.CANNOT and "error" in doc
