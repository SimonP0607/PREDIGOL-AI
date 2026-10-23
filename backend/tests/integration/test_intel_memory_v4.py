"""Memory with a confidence on a real database (plan F8, ``memory-v4``): the corners, cards and xG of the teams and of their leagues, each
row with the confidence it rests on and the matches or decisions it names; the weight of age from one day to the next; a statistic that
arrives late; the lineage, built from its first day and resumable; the readers, which ask for the newest version.

The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.api.services import intelligence
from fbi.intel import cycle, memory

from .conftest import Seed
from .helpers import scalar
from .test_intel_memory_late import DAY, KICKOFF, World, _night

pytestmark = pytest.mark.integration

NEXT = DAY + timedelta(days=1)
AFTER = DAY + timedelta(days=2)
LAMBDA_TEAM = memory.TEAM_FIGURES.half_life
LAMBDA_LEAGUE = memory.LEAGUE_FIGURES.half_life


class League:
    """Teams that keep their identity from one day to the next (the world of the late-news tests makes new ones for every match)."""

    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed, self.n = db, seed, 0
        self.teams: dict[str, int] = {}

    def team(self, name: str) -> int:
        if name not in self.teams:
            self.teams[name] = int(scalar(self.db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                                          (881000 + len(self.teams), name))))
        return self.teams[name]

    def competition(self, name: str, provider_id: int) -> tuple[int, int]:
        """A second competition, with a season: (competition id, competition season id)."""
        competition = int(scalar(self.db.execute(
            "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
            "VALUES (%s, %s, 'league', 'club', 'domestic_league') RETURNING id", (provider_id, name))))
        season = int(scalar(self.db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) RETURNING id",
                                            (competition,))))
        return competition, season

    def match(self, home: str, away: str, kickoff: datetime, *, result: tuple[int, int] = (1, 0), season: int | None = None) -> int:
        self.n += 1
        fid = int(scalar(self.db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
            "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
            (8810000 + self.n, season or self.seed.season_id, self.team(home), self.team(away), kickoff))))
        self.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)", (fid, *result))
        return fid

    def stats(self, fid: int, side: str, *, corners: int | None = None, yellow: int | None = None, red: int | None = None,
              xg: float | None = None, at: datetime = KICKOFF + timedelta(hours=3)) -> None:
        self.db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, corners, yellow_cards, red_cards, expected_goals, "
                        "payload_hash, fetched_at) VALUES (%s, %s, 'api-football', %s, %s, %s, %s, %s, %s)",
                        (fid, side, corners, yellow, red, xg, self.seed.payload_hash, at))

    def both(self, fid: int, home: dict[str, Any], away: dict[str, Any], **kw: Any) -> None:
        self.stats(fid, "home", **home, **kw)
        self.stats(fid, "away", **away, **kw)


def row(db: psycopg.Connection[Any], day: date, kind: str, entity: int | str, aspect: str) -> dict[str, Any]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intel.entity_memory WHERE as_of_day = %s AND entity_type = %s AND entity_id = %s AND aspect = %s "
                    "AND version = %s", (day, kind, str(entity), aspect, memory.VERSION))
        found = cur.fetchone()
    assert found is not None, (day, kind, entity, aspect)
    return dict(found)


def absent(db: psycopg.Connection[Any], day: date, kind: str, entity: int | str, aspect: str) -> bool:
    return scalar(db.execute("SELECT count(*) FROM intel.entity_memory WHERE as_of_day = %s AND entity_type = %s AND entity_id = %s "
                             "AND aspect = %s AND version = %s", (day, kind, str(entity), aspect, memory.VERSION))) == 0


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> League:
    league = League(db, seed)
    league.m1 = league.match("Alpha", "Bravo", KICKOFF, result=(2, 1))                # type: ignore[attr-defined]
    league.both(league.m1, {"corners": 8, "yellow": 2, "red": 0, "xg": 1.8}, {"corners": 4, "yellow": 3, "red": 1, "xg": 0.6})  # type: ignore[attr-defined]
    league.m2 = league.match("Charlie", "Delta", KICKOFF + timedelta(hours=1), result=(0, 0))  # type: ignore[attr-defined]
    league.both(league.m2, {"corners": 6}, {"corners": 10})                           # type: ignore[attr-defined]   # no cards, no xG reported
    league.m3 = league.match("Echo", "Foxtrot", KICKOFF + timedelta(hours=2))        # type: ignore[attr-defined]   # no statistics at all
    return league


def test_a_day_of_matches_writes_the_figures_of_its_teams_and_its_league_each_with_its_confidence_and_its_matches(
        db: psycopg.Connection[Any], world: League, seed: Seed) -> None:
    m1, m2 = world.m1, world.m2                                                        # type: ignore[attr-defined]
    assert memory.build_memory(db, day=DAY, at=_night(DAY), late_days=0) > 0

    # the league: the mean per team in a match, from 2 matches
    corners = row(db, DAY, "competition", seed.competition_id, "corners")
    assert corners["stats"]["matches"] == 2 and corners["stats"]["total"] == 28 and corners["stats"]["rate"] == 7.0
    assert float(corners["confidence"]) == pytest.approx(2 / (2 + memory.LEAGUE_FIGURES.k), abs=1e-4)
    assert corners["evidence_ref"] == {"fixtures": sorted([m1, m2], reverse=True)} and sorted(corners["sources"]) == sorted([m1, m2])
    assert row(db, DAY, "competition", seed.competition_id, "cards")["stats"]["total"] == 6, "2+0+3+1 and a line with no cards: none"
    xg = row(db, DAY, "competition", seed.competition_id, "xg")["stats"]
    assert (xg["matches"], xg["total"], xg["rate"]) == (1, 2.4, 1.2), "only the match that reports expected goals"

    # a team: what it produced, what it conceded, shrunk to its league
    alpha = world.team("Alpha")
    r = row(db, DAY, "team", alpha, "corners")
    assert r["entity_name"] == "Alpha"
    s = r["stats"]
    assert (s["matches"], s["own"], s["opp"], s["by_competition"]) == (1, 8, 4, {str(seed.competition_id): 1})
    assert (s["n_eff"], s["own_rate"], s["opp_rate"], s["prior"], s["prior_matches"]) == (1.0, 8.0, 4.0, 7.0, 1)
    m = memory.METRICS["corners"].prior_weight
    assert s["own_shrunk"] == pytest.approx((8 + m * 7) / (1 + m), abs=1e-4) and s["opp_shrunk"] == pytest.approx((4 + m * 7) / (1 + m), abs=1e-4)
    assert float(r["confidence"]) == pytest.approx(1 / (1 + memory.TEAM_FIGURES.k), abs=1e-4)
    assert r["evidence_ref"] == {"fixtures": [m1]}
    cards = row(db, DAY, "team", world.team("Bravo"), "cards")["stats"]
    assert (cards["own"], cards["opp"]) == (4, 2), "3 yellow and a red; the other side's 2 yellow"

    # a team whose match reported nothing of a figure has no row for it; a match with no statistics gives no row at all
    assert absent(db, DAY, "team", world.team("Charlie"), "xg") and absent(db, DAY, "team", world.team("Delta"), "xg")
    assert row(db, DAY, "team", world.team("Charlie"), "cards")["stats"]["own"] == 0, "a line with no cards says none"
    for name in ("Echo", "Foxtrot"):
        assert all(absent(db, DAY, "team", world.team(name), a) for a in ("corners", "cards", "xg")), name
    assert memory.build_memory(db, day=DAY, at=_night(DAY), late_days=0) == 0, "a day is written once"


def test_the_next_day_ages_what_the_row_before_knew_and_adds_the_new_match(db: psycopg.Connection[Any], world: League, seed: Seed) -> None:
    memory.build_memory(db, day=DAY, at=_night(DAY), late_days=0)
    m5 = world.match("Alpha", "Charlie", KICKOFF + timedelta(days=1), result=(1, 1))
    world.both(m5, {"corners": 5, "yellow": 1, "red": 0, "xg": 1.0}, {"corners": 9, "yellow": 2, "red": 0, "xg": 1.4})
    memory.build_memory(db, day=NEXT, at=_night(NEXT), late_days=0)

    ageing = memory.decay(1, LAMBDA_TEAM)
    s = row(db, NEXT, "team", world.team("Alpha"), "corners")["stats"]
    assert (s["matches"], s["own"], s["opp"]) == (2, 13, 13), "the numbers are the numbers: they do not age"
    assert s["n_eff"] == pytest.approx(ageing + 1, abs=1e-5) and s["w_own"] == pytest.approx(8 * ageing + 5, abs=1e-4)
    assert s["own_rate"] == pytest.approx((8 * ageing + 5) / (ageing + 1), abs=1e-3)
    league = row(db, NEXT, "competition", seed.competition_id, "corners")["stats"]
    assert league["matches"] == 3 and league["total"] == 42
    stale = memory.decay(1, LAMBDA_LEAGUE)
    assert league["n_eff"] == pytest.approx(2 * stale + 1, abs=1e-5) and league["rate"] == pytest.approx((28 * stale + 14) / (2 * (2 * stale + 1)), abs=1e-3)
    assert s["prior"] == pytest.approx(league["rate"], abs=1e-3), "shrunk to the league as it stands that night, the night's match included"
    bigger = float(row(db, NEXT, "team", world.team("Alpha"), "corners")["confidence"])
    assert bigger > float(row(db, DAY, "team", world.team("Alpha"), "corners")["confidence"]), "two matches say more than one"
    charlie = row(db, NEXT, "team", world.team("Charlie"), "corners")
    assert charlie["stats"]["matches"] == 2 and charlie["evidence_ref"] == {"fixtures": [m5]}, "the row names the matches of its day"


def test_a_statistic_that_arrives_after_the_night_is_booked_with_the_weight_of_its_own_day(db: psycopg.Connection[Any], seed: Seed) -> None:
    league = League(db, seed)
    played = league.match("Golf", "Hotel", KICKOFF, result=(3, 0))
    memory.build_memory(db, day=DAY, at=_night(DAY))
    assert absent(db, DAY, "team", league.team("Golf"), "corners"), "the statistics had not arrived"
    league.both(played, {"corners": 7, "yellow": 1, "xg": 2.1}, {"corners": 3, "yellow": 4, "xg": 0.3}, at=_night(DAY) + timedelta(hours=2))
    memory.build_memory(db, day=NEXT, at=_night(NEXT))

    r = row(db, NEXT, "team", league.team("Golf"), "corners")
    assert r["delta"]["late"][DAY.isoformat()] == {"matches": 1, "own": 7, "opp": 3, "by_competition": {str(seed.competition_id): 1}}
    assert r["stats"]["matches"] == 1 and r["stats"]["n_eff"] == pytest.approx(memory.decay(1, LAMBDA_TEAM), abs=1e-5), \
        "a match of yesterday weighs what yesterday weighs"
    assert r["evidence_ref"] == {"fixtures": [played]}
    xg = row(db, NEXT, "competition", seed.competition_id, "xg")
    assert xg["stats"]["rate"] == pytest.approx(1.2, abs=1e-4) and xg["evidence_ref"] == {"fixtures": [played]}
    assert memory.build_memory(db, day=AFTER, at=_night(AFTER)) == 0 or absent(db, AFTER, "team", league.team("Golf"), "corners"), \
        "booked once: nothing new the night after"


def test_a_league_whose_row_of_the_day_exists_already_is_the_ground_a_team_added_later_is_shrunk_to(
        db: psycopg.Connection[Any], world: League, seed: Seed) -> None:
    memory.build_memory(db, day=DAY, at=_night(DAY), late_days=0)
    league_row = row(db, DAY, "competition", seed.competition_id, "corners")
    # the statistics of a third match arrive the same day, after the rows were written: the league's row stays as it was written
    late = world.match("India", "Juliet", KICKOFF + timedelta(hours=3))
    world.both(late, {"corners": 12}, {"corners": 12}, at=_night(DAY) - timedelta(hours=1))
    assert memory.build_memory(db, day=DAY, at=_night(DAY) + timedelta(minutes=5), late_days=0) >= 2
    again = row(db, DAY, "competition", seed.competition_id, "corners")
    assert again["id"] == league_row["id"] and again["stats"] == league_row["stats"], "a row is never rewritten"
    india = row(db, DAY, "team", world.team("India"), "corners")["stats"]
    assert india["prior"] == 7.0 and india["prior_matches"] == 1, "shrunk to the league as that row says, not to a league it never saw"


def test_the_decision_rows_name_their_decisions_and_the_post_mortem_that_judged_each(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fixture = w.match(KICKOFF, result=(1, 0))
    decision = w.decision(fixture, KICKOFF, "Home")
    other = w.decision(w.match(KICKOFF, result=(0, 0)), KICKOFF, "Draw")
    w.outcome(decision, "win", KICKOFF + timedelta(hours=3))
    w.outcome(other, "loss", KICKOFF + timedelta(hours=3))
    judged = scalar(db.execute(
        "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, verdict, answers) "
        "VALUES (%s, %s, %s, 'pm-v6', 'won', 'GOOD', 'MERECIDO', '{}') RETURNING id", (decision, fixture, _night(DAY))))
    memory.build_memory(db, day=DAY, at=_night(DAY), late_days=0)

    market = row(db, DAY, "market", "1X2", "decisions")
    assert market["evidence_ref"] == {"decisions": sorted([decision, other], reverse=True), "postmortems": [judged]}
    assert market["stats"]["verdicts"] == {"MERECIDO": 1}
    assert float(market["confidence"]) == pytest.approx(2 / (2 + memory.DECISIONS_MARKET.k), abs=1e-4)
    team = row(db, DAY, "team", scalar(db.execute("SELECT home_team_id FROM core.fixtures WHERE id = %s", (fixture,))), "market:1X2")
    assert team["evidence_ref"] == {"decisions": [decision], "postmortems": [judged]}
    assert float(team["confidence"]) == pytest.approx(1 / (1 + memory.DECISIONS_TEAM.k), abs=1e-4)
    assert row(db, DAY, "competition", seed.competition_id, "market:1X2")["confidence"] is not None


def test_every_row_the_memory_writes_says_how_far_to_trust_it(db: psycopg.Connection[Any], world: League, seed: Seed) -> None:
    w = World(db, seed)
    fixture = w.match(KICKOFF, result=(2, 1), referee="B. Referee")
    w.outcome(w.decision(fixture, KICKOFF, "Home"), "win", KICKOFF + timedelta(hours=3))
    w.stats(fixture, "home", yellow=2, red=0, fouls=10, at=KICKOFF + timedelta(hours=3))
    w.stats(fixture, "away", yellow=1, red=0, fouls=12, at=KICKOFF + timedelta(hours=3))
    memory.build_memory(db, day=DAY, at=_night(DAY), late_days=0)
    rows = db.execute("SELECT entity_type, aspect, confidence, evidence_ref FROM intel.entity_memory WHERE version = %s", (memory.VERSION,)).fetchall()
    assert len(rows) > 10
    for kind, aspect, confidence, evidence in rows:
        assert confidence is not None and 0 < float(confidence) < 1, (kind, aspect)
        assert evidence and set(evidence) <= {"decisions", "postmortems", "fixtures"}, (kind, aspect, evidence)
    kinds = {(r[0], r[1]) for r in rows}
    assert {("team", "corners"), ("team", "cards"), ("team", "xg"), ("competition", "corners"), ("market", "decisions"),
            ("team", "market:1X2")} <= kinds


# ── the lineage ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_lineage_is_built_day_by_day_from_its_first_day_and_a_second_run_finds_it_built(
        db: psycopg.Connection[Any], world: League, seed: Seed) -> None:
    m5 = world.match("Alpha", "Charlie", KICKOFF + timedelta(days=1), result=(1, 1))
    world.both(m5, {"corners": 5, "yellow": 1}, {"corners": 9, "yellow": 2})
    m6 = world.match("Bravo", "Delta", KICKOFF + timedelta(days=2), result=(2, 2))
    world.both(m6, {"corners": 2, "yellow": 0}, {"corners": 6, "yellow": 5})
    report = memory.rebuild(db, start=DAY, end=AFTER, at=_night(AFTER))
    assert (report.days, report.first, report.last, report.stopped) == (3, DAY, AFTER, None)
    assert report.rows == sum(report.by_day.values()) and all(n > 0 for n in report.by_day.values())

    # each day is built on the rows of the day before it: the last row of a team is its whole history
    alpha = row(db, NEXT, "team", world.team("Alpha"), "corners")["stats"]
    assert (alpha["matches"], alpha["own"]) == (2, 13)
    bravo = row(db, AFTER, "team", world.team("Bravo"), "corners")["stats"]
    assert (bravo["matches"], bravo["own"], bravo["opp"]) == (2, 6, 14), "Bravo: 4 against Alpha's 8, then 2 against Delta's 6"
    assert memory.rebuild(db, start=DAY, end=AFTER, at=_night(AFTER)).rows == 0, "built once"
    assert memory.lineage_started(db, NEXT) and not memory.lineage_started(db, DAY), "the lineage has rows before the day after its first"


def test_a_rebuild_with_a_budget_stops_between_days_and_the_next_run_goes_on(db: psycopg.Connection[Any], world: League) -> None:
    for n in (1, 2):
        fid = world.match("Alpha", "Bravo", KICKOFF + timedelta(days=n), result=(1, 0))
        world.both(fid, {"corners": 5}, {"corners": 4})
    ticks = iter(range(0, 10_000, 100))
    first = memory.rebuild(db, start=DAY, end=AFTER, at=_night(AFTER), max_seconds=50, clock=lambda: float(next(ticks)))
    assert (first.days, first.stopped, first.last) == (1, "time", DAY), "it never stops before the first day: a budget is not a refusal"
    second = memory.rebuild(db, start=DAY, end=AFTER, at=_night(AFTER))
    assert second.stopped is None and second.by_day[DAY] == 0 and second.by_day[NEXT] > 0, "it goes on from where it stopped: the built day is skipped"
    alpha = row(db, NEXT, "team", world.team("Alpha"), "corners")["stats"]
    assert alpha["matches"] == 2 and alpha["own"] == 13, "and the state is the same as if it had not stopped"


def test_a_rebuild_commits_each_day_as_it_goes(db: psycopg.Connection[Any], world: League) -> None:
    commits: list[int] = []
    memory.rebuild(db, start=DAY, end=DAY + timedelta(days=2), at=_night(AFTER), commit=lambda: commits.append(1))
    assert len(commits) == 3, "one per day, empty days included: what is built is durable before the next day begins"


def test_the_nightly_step_waits_for_the_lineage_and_continues_it(db: psycopg.Connection[Any], world: League) -> None:
    at = _night(DAY)  # 07:50 on the 5th in Bogotá: the night of the 4th
    assert cycle.memory_step(db, at=at) == {DAY.isoformat(): 0, "waiting_for_rebuild": 1}
    assert scalar(db.execute("SELECT count(*) FROM intel.entity_memory WHERE version = %s", (memory.VERSION,))) == 0
    memory.rebuild(db, start=DAY - timedelta(days=1), end=DAY - timedelta(days=1), at=at)  # an empty day does not begin a lineage
    assert cycle.memory_step(db, at=at)["waiting_for_rebuild"] == 1
    fid = world.match("Alpha", "Bravo", KICKOFF - timedelta(days=1), result=(1, 0))
    world.both(fid, {"corners": 5}, {"corners": 4})
    memory.rebuild(db, start=DAY - timedelta(days=1), end=DAY - timedelta(days=1), at=at)
    counts = cycle.memory_step(db, at=at)
    assert "waiting_for_rebuild" not in counts and counts[DAY.isoformat()] > 0


def test_the_first_day_of_the_lineage_needs_no_rows_before_it(db: psycopg.Connection[Any], world: League,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fbi.intel.memory.LINEAGE_START", DAY)
    counts = cycle.memory_step(db, at=_night(DAY))
    assert "waiting_for_rebuild" not in counts and counts[DAY.isoformat()] > 0


# ── the readers ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_console_reads_the_newest_version_with_its_confidence_and_what_it_rests_on(db: psycopg.Connection[Any], world: League,
                                                                                       seed: Seed) -> None:
    alpha = world.team("Alpha")
    db.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, built_at, version, stats, delta, sources) "
               "VALUES ('team', %s, 'Alpha', 'corners', %s, %s, 'memory-v3', '{\"matches\": 99}', '{}', '[]')", (str(alpha), DAY, _night(DAY)))
    memory.build_memory(db, day=DAY, at=_night(DAY), late_days=0)

    listed = {(i["entity_id"], i["aspect"]): i for i in intelligence.memory(db, entity_type="team", q="Alpha", limit=50).data["items"]}  # type: ignore[index]
    item = listed[(str(alpha), "corners")]
    assert item["version"] == "memory-v4" and item["stats"]["matches"] == 1, "the older version's row of the same day does not show"
    assert item["confidence"] == pytest.approx(1 / (1 + memory.TEAM_FIGURES.k), abs=1e-4) and item["evidence_ref"] == {"fixtures": [world.m1]}  # type: ignore[attr-defined]
    history = intelligence.memory_history(db, "team", str(alpha)).data["history"]  # type: ignore[index]
    mine = [h for h in history if h["aspect"] == "corners"]
    assert [(h["as_of_day"], h["version"]) for h in mine] == [(DAY.isoformat(), "memory-v4")], "one row per day: the newest version"

    # the list is cut after sorting by sample: one aspect at a time keeps the kinds with the most rows from crowding the others out
    only = intelligence.memory(db, entity_type=None, q=None, limit=50, aspect="corners").data["items"]  # type: ignore[index]
    assert only and {i["aspect"] for i in only} == {"corners"} and {i["entity_type"] for i in only} == {"team", "competition"}
    assert intelligence.memory(db, entity_type="team", q=None, limit=50, aspect="no-such-aspect").data["items"] == []  # type: ignore[index]


def test_the_row_of_a_version_before_memory_v4_has_no_confidence_and_is_still_read(db: psycopg.Connection[Any]) -> None:
    db.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, built_at, version, stats, delta, sources) "
               "VALUES ('market', 'OU', 'OU', 'decisions', %s, %s, 'memory-v1', '{\"decisions\": 3}', '{}', '[]')", (DAY, _night(DAY)))
    item = next(i for i in intelligence.memory(db, entity_type="market", q=None, limit=10).data["items"] if i["entity_id"] == "OU")  # type: ignore[index]
    assert item["version"] == "memory-v1" and item["confidence"] is None and item["evidence_ref"] is None
