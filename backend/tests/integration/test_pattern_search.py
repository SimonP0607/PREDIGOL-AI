"""Plan F12.6 on a real database: the settled decisions as the search reads them (one row per selection, the last decision before the kick-off, with
where each was played, its coach and its referee), the window and the picks-only switch, the matches with two referee observations counted once, a
planted pattern found through the database and proposed once however often it is seen, and the command that reads without writing and proposes only
when it is told to.

The arithmetic is in ``tests/unit/test_pattern_search.py``; here the rows come out of ``intel.decisions`` and ``intel.decision_outcomes`` through
the real statements."""

from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import patterns as cli

from fbi.research import pattern_search as ps

from .conftest import Seed
from .helpers import scalar
from .knowledge_world import World

pytestmark = pytest.mark.integration

AT = datetime(2034, 6, 1, 12, tzinfo=UTC)
KICK = datetime(2034, 5, 10, 19, tzinfo=UTC)
START = AT - timedelta(days=90)


class Ground:
    """The world of the Match Knowledge tests (a league, four teams, a season) with what the search reads on top of it."""

    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db = db
        self.w = World(db, seed)
        self.n = 0

    # ── where a match is played ──────────────────────────────────────────────────────────────────────────────────────

    def competition(self, name: str, kind: str) -> tuple[int, int]:
        """A competition of a type (``domestic_cup``...) with a season: (competition id, season id)."""
        self.n += 1
        comp = int(scalar(self.db.execute(
            "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, is_tracked) "
            "VALUES (%s, %s, 'Colombia', 'league', 'club', %s, true) RETURNING id", (98980 + self.n, name, kind))))
        season = int(scalar(self.db.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2034, false) RETURNING id",
                                            (comp,))))
        return comp, season

    def match(self, kickoff: datetime = KICK, *, season: int | None = None, home: int = 0, away: int = 1) -> int:
        """A finished match (no result row: the search does not read the score, it reads the settled decisions)."""
        if season is None:
            return self.w.match(kickoff, home=home, away=away, goals=None)
        league = self.w.season
        self.w.season = season
        try:
            return self.w.match(kickoff, home=home, away=away, goals=None)
        finally:
            self.w.season = league

    def stage(self, fixture: int, season: int, role: str) -> None:
        stage = scalar(self.db.execute(
            "INSERT INTO core.competition_stages (competition_season_id, stage, ordinal, phase, base_stage, kind, role, rule, numbered, fixtures, "
            "first_kickoff_at, last_kickoff_at, ties, stages_version, ties_version, build_hash) VALUES (%s, %s, 1, 'knockout', %s, 'knockout', %s, 'test', "
            "false, 1, %s, %s, 1, 'stages-v1', 'ties-v1', 'x') RETURNING id", (season, role, role, role, KICK, KICK)))
        self.db.execute("UPDATE core.fixtures SET stage_id = %s WHERE id = %s", (stage, fixture))

    # ── who whistled it and who coached it ───────────────────────────────────────────────────────────────────────────

    def referee(self, name: str) -> tuple[int, int]:
        """A referee and one spelling of his name that F3 settled on: (referee id, alias id)."""
        rid = int(scalar(self.db.execute("INSERT INTO core.referees (name, name_key, origin, version) VALUES (%s, %s, 'rules', 'test') RETURNING id",
                                         (name, name.lower()))))
        alias = int(scalar(self.db.execute("INSERT INTO core.referee_aliases (referee_id, name_key, scope, display, basis, placed_by, version) "
                                           "VALUES (%s, %s, 'testland', %s, 'identity', 'rules', 'test') RETURNING id", (rid, name.lower(), name))))
        return rid, alias

    def whistle(self, fixture: int, alias: int, observed: datetime) -> None:
        self.db.execute("INSERT INTO core.fixture_officials (fixture_id, role, observed_at, alias_id) VALUES (%s, 'referee', %s, %s)",
                        (fixture, observed, alias))

    def coaches(self, fixture: int, home: str, away: str, away_provider_id: int) -> int:
        """The home coach as a person of the catalogue and the away coach only by the provider's id: the id of the first."""
        person = int(scalar(self.db.execute("INSERT INTO core.coaches (provider_coach_id, name) VALUES (%s, %s) RETURNING id", (5550000 + fixture, home))))
        self.w.sheet(fixture, "home", "4-3-3", [], coach=home, coach_id=person)
        self.w.sheet(fixture, "away", "4-4-2", [], coach=away)
        self.db.execute("UPDATE core.fixture_lineups SET provider_coach_id = %s WHERE fixture_id = %s AND team_side = 'away'", (away_provider_id, fixture))
        return person

    # ── what the system decided and what came of it ──────────────────────────────────────────────────────────────────

    def decide(self, fixture: int, market: str, selection: str, line: float, *, kickoff: datetime = KICK, known: datetime | None = None,
               state: str = "CAUTELA", odds: float | None = 2.2, p_model: float = 0.5, p_cal: float | None = None, role: str | None = None,
               model: str = "dixon_coles", context: str = "PENDING", p_push: float | None = None, checkpoint: str = "T-3h") -> int:
        known = known or kickoff - timedelta(hours=3)
        stake = 0 if state in ("RECHAZADO", "INVESTIGACION") else 1
        return int(scalar(self.db.execute(
            "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, odds, "
            "p_model, p_push, p_cal, calibrator_role, p_market, filters, state, stake_units, context_status, input_hash) VALUES "
            "('decision-v1', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0.5, %s, %s, %s, %s, %s) RETURNING id",
            (known, checkpoint, fixture, kickoff, market, selection, line, model, odds, p_model, p_push, p_cal, role, Jsonb([]), state, stake, context,
             f"{fixture}|{market}|{selection}|{line}|{checkpoint}|{known.isoformat()}|{state}"))))

    def settle(self, decision: int, result: str, *, clv: float | None = 0.0, close: float | None = 0.5) -> None:
        self.db.execute(
            "INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, close_p_fair, close_odds, "
            "close_as_of, clv, version, computed_at) VALUES (%s, %s, %s, 0, 0, %s, 2.0, %s, %s, 'outcome-v1', %s)",
            (decision, KICK + timedelta(days=1), result, close, KICK - timedelta(minutes=20), clv, KICK + timedelta(days=1)))


@pytest.fixture()
def ground(db: psycopg.Connection[Any], seed: Seed) -> Ground:
    return Ground(db, seed)


def by_selection(rows: list[ps.Obs]) -> dict[str, ps.Obs]:
    return {r.tags["selection"][0]: r for r in rows}


# ── the rows ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_each_selection_is_read_once_with_its_last_decision_and_where_it_was_played(db: psycopg.Connection[Any], ground: Ground) -> None:
    g, w = ground, ground.w
    fid = g.match()
    first, second = g.referee("First Referee"), g.referee("Second Referee")
    g.whistle(fid, first[1], KICK - timedelta(days=3))
    g.whistle(fid, second[1], KICK - timedelta(days=1))  # the provider changed its mind: the later observation is the referee
    person = g.coaches(fid, "Home Coach", "Away Coach", away_provider_id=7771)

    early = g.decide(fid, "1X2", "Home", 0, known=KICK - timedelta(days=2), state="INVESTIGACION", odds=2.6, p_model=0.40, context="LIMITED")
    last = g.decide(fid, "1X2", "Home", 0, known=KICK - timedelta(hours=1), checkpoint="T-60m", state="CAUTELA", odds=2.2, p_model=0.50, p_cal=0.55,
                    role="CHALLENGER", context="FULL")
    g.settle(early, "loss", clv=-0.30, close=0.30)
    g.settle(last, "win", clv=0.05, close=0.45)
    over = g.decide(fid, "OU", "Over", 2.5, state="APROBADO", odds=1.85, p_model=0.60)
    g.settle(over, "loss", clv=-0.02, close=0.55)
    asian = g.decide(fid, "AH", "Home", -0.25, p_model=0.52)
    g.settle(asian, "half_loss", clv=0.01)
    push = g.decide(fid, "OU", "Under", 2.0, p_model=0.30, p_push=0.2)
    g.settle(push, "push", clv=0.0)
    draw = g.decide(fid, "1X2", "Draw", 0, state="RECHAZADO", odds=3.4, p_model=0.27)
    g.settle(draw, "win", clv=0.03, close=0.30)
    void = g.decide(fid, "BTTS", "Yes", 0, p_model=0.55)
    g.settle(void, "void", clv=0.0)
    g.decide(fid, "BTTS", "No", 0, p_model=0.45)  # not settled yet: not a result to read

    rows, labels = ps.read(db, start=START, end=AT)
    got = by_selection(rows)
    assert len(rows) == 5 and sorted(got) == ["1X2 Draw", "1X2 Home", "AH Home", "OU Over", "OU Under"], (
        "one row per selection (the referee's two observations do not multiply them); the voided and the unsettled are not rows")
    comp = str(scalar(g.db.execute("SELECT competition_id FROM core.competition_seasons WHERE id = %s", (w.season,))))
    t0, t1 = str(w.team[0]), str(w.team[1])

    home = got["1X2 Home"]
    assert (home.fixture_id, home.kickoff_at, home.p, home.won, home.p_close, home.clv) == (fid, KICK, 0.55, 1, 0.45, 0.05), "the last decision, calibrated"
    assert home.lead_hours == pytest.approx(1.0), "taken an hour before the kick-off (the early one, two days before, is not the decision)"
    assert got["OU Over"].lead_hours == pytest.approx(3.0) and ps.stratum(home) == ("1X2 0", "2.00-2.49", "1-3 h")
    assert dict(home.tags) == {
        "market": ("1X2",), "market_line": ("1X2 0",), "selection": ("1X2 Home",), "model": ("dixon_coles",), "calibration_role": ("CHALLENGER",),
        "context": ("FULL",), "match_type": ("domestic_league:unknown",), "competition": (comp,), "team": (t0,), "odds_band": ("2.00-2.49",),
        "coach": (str(person),), "referee": (str(second[0]),)}, "the side it backs: that team and that team's coach"

    over_row = got["OU Over"]
    assert (over_row.p, over_row.won, over_row.p_close, over_row.clv) == (0.60, 0, 0.55, -0.02), "no calibrator: the model's own probability"
    assert over_row.tags["calibration_role"] == ("none",) and over_row.tags["market_line"] == ("OU 2.5",) and over_row.tags["odds_band"] == ("1.70-1.99",)
    assert over_row.tags["team"] == (t0, t1) and over_row.tags["coach"] == (str(person), "p7771"), "a market about the whole match belongs to both sides"

    assert got["AH Home"].won is None and got["AH Home"].clv == 0.01, "a quarter line that settled half lost: the price counts, the probability cannot be read"
    assert got["OU Under"].won is None, "a push that the model thought possible (p_push 0.2): its probability is not one of winning outright"
    draw_row = got["1X2 Draw"]
    assert draw_row.won == 1 and draw_row.tags["team"] == (t0, t1) and draw_row.tags["odds_band"] == ("2.50-3.49",)

    assert labels[("competition", comp)] == "Knowledge League" and labels[("team", t0)] == "Knowledge 0" and labels[("team", t1)] == "Knowledge 1"
    assert labels[("referee", str(second[0]))] == "Second Referee" and ("referee", str(first[0])) not in labels
    assert labels[("coach", str(person))] == "Home Coach" and labels[("coach", "p7771")] == "Away Coach"


def test_the_window_includes_its_start_and_excludes_its_end_and_the_picks_only_switch_drops_the_rejected(db: psycopg.Connection[Any],
                                                                                                         ground: Ground) -> None:
    g = ground
    for kickoff in (START - timedelta(hours=1), START, KICK, AT, AT + timedelta(days=1)):  # just before, the start, inside, the end, after
        fid = g.match(kickoff)
        for selection, state in (("Home", "CAUTELA"), ("Draw", "RECHAZADO"), ("Away", "INVESTIGACION")):
            g.settle(g.decide(fid, "1X2", selection, 0, kickoff=kickoff, state=state, p_model=0.3), "loss")
    rows, _ = ps.read(db, start=START, end=AT)
    assert sorted(r.kickoff_at for r in rows) == sorted([START, START, START, KICK, KICK, KICK]), "the start is in, the end is out"
    picks, _ = ps.read(db, start=START, end=AT, selected_only=True)
    assert sorted(r.kickoff_at for r in picks) == [START, KICK], "only the decisions that stayed as picks or watch-list"
    assert {r.tags["selection"] for r in picks} == {("1X2 Home",)}


def test_the_type_of_match_is_the_type_of_the_competition_and_the_role_of_the_stage(db: psycopg.Connection[Any], ground: Ground) -> None:
    g = ground
    cup, cup_season = g.competition("Knowledge Cup", "domestic_cup")
    final = g.match(season=cup_season, home=2, away=3)
    g.stage(final, cup_season, "final")
    friendly = g.match(KICK + timedelta(days=1))  # a league match with no stage
    for fid, kickoff in ((final, KICK), (friendly, KICK + timedelta(days=1))):
        g.settle(g.decide(fid, "1X2", "Home", 0, kickoff=kickoff, p_model=0.4), "win")
    rows, labels = ps.read(db, start=START, end=AT)
    kinds = {r.fixture_id: (r.tags["match_type"], r.tags["competition"]) for r in rows}
    assert kinds[final] == (("domestic_cup:final",), (str(cup),)) and kinds[friendly][0] == ("domestic_league:unknown",)
    assert labels[("competition", str(cup))] == "Knowledge Cup"


def test_a_side_with_two_sheets_takes_the_coach_of_the_one_read_last(db: psycopg.Connection[Any], ground: Ground) -> None:
    """The table holds one sheet per side today (its ``source`` may only be api-football); the choice is written for the day another source is allowed,
    and is tried here with the check lifted inside this test's own transaction (a rollback gives it back)."""
    g = ground
    fid = g.match()
    check = scalar(db.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'core.fixture_lineups'::regclass AND contype = 'c' "
                              "AND pg_get_constraintdef(oid) LIKE '%api-football%'"))
    db.execute(f'ALTER TABLE core.fixture_lineups DROP CONSTRAINT "{check}"')
    old, new = (int(scalar(db.execute("INSERT INTO core.coaches (provider_coach_id, name) VALUES (%s, %s) RETURNING id", (5560000 + i, name))))
                for i, name in enumerate(("Old Coach", "New Coach")))
    g.w.sheet(fid, "home", "4-3-3", [], coach="Old Coach", coach_id=old, fetched=KICK - timedelta(days=5))
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, coach_name, coach_id, payload_hash, fetched_at) "
               "SELECT fixture_id, team_side, 'other-provider', formation, 'New Coach', %s, payload_hash, %s FROM core.fixture_lineups WHERE fixture_id = %s",
               (new, KICK - timedelta(days=1), fid))
    g.settle(g.decide(fid, "1X2", "Home", 0, p_model=0.4), "win")
    rows, labels = ps.read(db, start=START, end=AT)
    [home] = rows
    assert home.tags["coach"] == (str(new),) and labels[("coach", str(new))] == "New Coach" and ("coach", str(old)) not in labels


# ── the search through the database ──────────────────────────────────────────────────────────────────────────────

def plant(g: Ground, per_competition: int = 32, *, bands: bool = False) -> tuple[int, int]:
    """Five competitions of ``per_competition`` matches over 60 days with one decision each. The price taken in the cup beats the close by 8 points,
    in the four leagues it loses by 2 (noise of 6 points: with the cup in their rest the leagues stay under the bar). With ``bands`` every other
    decision is taken at odds of 1.6 and the others at 3.0, and the first beat the close by 10 points more than the second: the structure of the price
    itself, the same in every competition. Returns the ids of the cup and of the league of the world."""
    league = int(scalar(g.db.execute("SELECT competition_id FROM core.competition_seasons WHERE id = %s", (g.w.season,))))
    cup, cup_season = g.competition("Planted Cup", "domestic_cup")
    seasons: list[tuple[int | None, float]] = [(None, -0.02), (cup_season, 0.08)]
    for k in range(3):
        seasons.append((g.competition(f"Planted League {k}", "domestic_league")[1], -0.02))
    rng = np.random.default_rng(23)
    for k, (season, shift) in enumerate(seasons):
        for i in range(per_competition):
            kickoff = START + timedelta(days=1 + (i * 59) / per_competition, hours=k)
            fid = g.match(kickoff, season=season)
            high = bands and i % 2 == 0
            d = g.decide(fid, "OU", "Over", 2.5, kickoff=kickoff, p_model=0.5, odds=1.6 if high else 3.0 if bands else 2.2)
            g.settle(d, "win" if rng.random() < 0.5 else "loss", clv=float(shift + (0.05 if high else -0.05 if bands else 0.0) + rng.normal(0.0, 0.06)), close=0.5)
    return cup, league


def test_a_pattern_planted_in_the_database_is_found_and_proposed_once_however_often_it_is_seen(db: psycopg.Connection[Any], ground: Ground) -> None:
    cup, league = plant(ground)
    report = ps.run(db, at=AT, days=90, metrics=("clv",), dimensions=("competition",))
    assert report["window"]["days"] == 90 and report["rows"]["decisions"] == 160 and report["rows"]["matches"] == 160
    assert report["coverage"]["clv"]["competition"] == {"groups": 5, "tested": 5, "same": 0} and report["tests"] == 5
    [f] = report["found"]
    assert (f["dimension"], f["value"], f["label"], f["metric"]) == ("competition", str(cup), "Planted Cup", "clv")
    assert f["delta"] > 0.05 and f["z"] > 6 and f["stable"] is True and f["survives_correction"] is True and f["matches"] == 32 and f["matches_rest"] == 128
    assert str(league) in {x["value"] for x in report["nearest"]} and len(report["nearest"]) == 4 and all(abs(x["z"]) < 3 for x in report["nearest"])
    [band] = report["lead"]
    assert (band["band"], band["decisions"], band["matches"]) == ("3-6 h", 160, 160), "every one was taken three hours before the kick-off"
    assert band["mean"] == pytest.approx(float(scalar(db.execute("SELECT avg(clv) FROM intel.decision_outcomes")))), "the same mean the database gives"

    [p] = ps.proposals(report)
    assert p.key == f"pattern2:clv:competition:{cup}:up" and p.target == "pick_engine" and p.title.startswith("Competición Planted Cup")
    assert ps.known(db, [p]) == {}
    assert len(ps.register(db, [p], at=AT)) == 1
    [(hid, status)] = [(i, s) for i, s in ps.known(db, [p]).values()]
    row = db.execute("SELECT proposed_by, status, target, title, evidence FROM analytics.research_hypotheses WHERE id = %s", (hid,)).fetchone()
    assert row is not None and row[:3] == ("system", "PROPOSED", "pick_engine") and status == "PROPOSED"
    assert row[4]["group"] == "Competición: Planted Cup" and row[4]["measure"] == "valor de cierre (CLV)" and row[4]["tests"] == 5
    shown = [k for k in row[4] if k not in ("n_matches", "impact", "investigation_cost", "pattern_version")]
    assert shown == ["z", "delta", "group", "tests", "measure", "expected_by_chance"], (
        "the order the card of Evolución shows them in (web/src/live/aiModel.test.ts): the database hands a JSON object back shortest key first")

    assert ps.register(db, [p], at=AT + timedelta(days=7)) == [], "seen again a week later: proposed once"
    db.execute("UPDATE analytics.research_hypotheses SET status = 'REJECTED', decided_at = %s WHERE id = %s", (AT, hid))
    assert ps.register(db, [p], at=AT + timedelta(days=14)) == [], "and what the owner rejected is not asked again"
    assert ps.known(db, [p])[p.key] == (hid, "REJECTED")


def test_known_answers_only_for_the_proposals_it_is_asked_about(db: psycopg.Connection[Any], ground: Ground) -> None:
    plant(ground)
    [p] = ps.proposals(ps.run(db, at=AT, days=90, metrics=("clv",), dimensions=("competition",)))
    other = dataclasses.replace(p, key="pattern2:clv:competition:0:down", title="Another group: the price loses against the close")
    assert ps.known(db, [p, other]) == {}
    assert len(ps.register(db, [p, other], at=AT)) == 2
    assert set(ps.known(db, [p])) == {p.key} and set(ps.known(db, [other])) == {other.key}, "another hypothesis in the database is not an answer"
    assert set(ps.known(db, [p, other])) == {p.key, other.key} and ps.known(db, []) == {}


def hypotheses(db: psycopg.Connection[Any]) -> int:
    return int(scalar(db.execute("SELECT count(*) FROM analytics.research_hypotheses WHERE dedup_key LIKE 'pattern2:%'")))


def test_the_weekly_step_is_off_by_default_reads_in_report_and_proposes_in_propose(db: psycopg.Connection[Any], ground: Ground,
                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    plant(ground)
    monkeypatch.delenv(ps.SWITCH, raising=False)
    assert ps.weekly(db, at=AT) == {"mode": "off"} and hypotheses(db) == 0

    monkeypatch.setenv(ps.SWITCH, "report")
    seen = ps.weekly(db, at=AT)
    assert seen["mode"] == "report" and seen["decisions"] == 160 and seen["found"] >= 1 and seen["repeating"] >= 1 and "proposed" not in seen
    assert seen["descriptive"] == 0
    assert seen["top"][0]["group"] == "Planted Cup" and seen["top"][0]["repeats"] is True and hypotheses(db) == 0, "report reads and writes no hypothesis"

    monkeypatch.setenv(ps.SWITCH, "propose")
    first = ps.weekly(db, at=AT)
    assert first["mode"] == "propose" and first["proposed"] == hypotheses(db) >= 1
    assert ps.weekly(db, at=AT + timedelta(days=7))["proposed"] == 0 and hypotheses(db) == first["proposed"], "the second week proposes nothing new"


# ── the command ──────────────────────────────────────────────────────────────────────────────────────────────────

def parsed(*argv: str) -> argparse.Namespace:
    return cli.build_parser().parse_args([*argv, "--until", AT.isoformat()])


def test_search_prints_the_reading_as_text_or_json_and_writes_nothing(db: psycopg.Connection[Any], ground: Ground, capsys: pytest.CaptureFixture[str],
                                                                       tmp_path: Any) -> None:
    plant(ground)
    before = hypotheses(db)
    assert cli.search_command(db, parsed("search", "--metric", "clv", "--dimension", "competition")) == 0
    text = capsys.readouterr().out
    assert text.startswith("pattern search search-v1") and "comparisons made: 5." in text and "FOUND, |z| >= 3: 1" in text and "Planted Cup" in text
    out = tmp_path / "reading.json"
    assert cli.search_command(db, parsed("search", "--metric", "clv", "--dimension", "competition", "--json", "--out", str(out))) == 0
    printed, saved = json.loads(capsys.readouterr().out), json.loads(out.read_text(encoding="utf-8"))
    assert printed == saved and printed["version"] == "search-v1" and printed["found"][0]["label"] == "Planted Cup"
    assert hypotheses(db) == before == 0


def test_propose_is_a_dry_run_until_it_is_confirmed_and_never_asks_twice(db: psycopg.Connection[Any], ground: Ground,
                                                                        capsys: pytest.CaptureFixture[str]) -> None:
    plant(ground)
    flags = ("--metric", "clv", "--dimension", "competition")
    assert cli.propose_command(db, parsed("propose", *flags)) == 0
    dry = capsys.readouterr().out
    assert "1 findings reached the bar in 5 comparisons" in dry and "1 repeat in both halves" in dry and "WOULD PROPOSE pattern2:clv:competition:" in dry
    assert "Nothing was written. Add --confirm" in dry and hypotheses(db) == 0

    assert cli.propose_command(db, parsed("propose", *flags, "--confirm")) == 0
    done = capsys.readouterr().out
    assert "PROPOSING pattern2:clv:competition:" in done and "Proposed 1 hypotheses to the owner (ids #" in done and hypotheses(db) == 1

    assert cli.propose_command(db, parsed("propose", *flags, "--confirm")) == 0
    again = capsys.readouterr().out
    assert "already proposed: pattern2:clv:competition:" in again and "(PROPOSED)" in again and "Proposed" not in again and hypotheses(db) == 1


def test_propose_says_which_findings_it_leaves_out_and_why(db: psycopg.Connection[Any], ground: Ground, capsys: pytest.CaptureFixture[str]) -> None:
    plant(ground, bands=True)
    flags = ("--metric", "clv", "--dimension", "competition", "--dimension", "odds_band")
    assert cli.propose_command(db, parsed("propose", *flags, "--confirm")) == 0
    said = capsys.readouterr().out
    assert "2 findings reached the bar in 6 comparisons" in said and "2 repeat in both halves of the window; 1 would be proposed." in said
    assert "left out: Rango de cuota 1.40-1.69 (valor de cierre (CLV), z " in said and "- descriptive: how the price is built" in said
    assert "PROPOSING pattern2:clv:competition:" in said and "pattern2:clv:odds_band" not in said and hypotheses(db) == 1, "only the competition is a hypothesis"
    report = ps.run(db, at=AT, metrics=("clv",), dimensions=("competition", "odds_band"))
    by = {f["dimension"]: f for f in report["found"]}
    assert by["odds_band"]["descriptive"] is True and by["odds_band"]["within_strata"] is False and abs(by["odds_band"]["z"]) > 8
    assert by["competition"]["descriptive"] is False and by["competition"]["within_strata"] is True and by["competition"]["z"] > 6, (
        "the cup is compared with the others inside each odds band, and it is still 8 points better")


def test_propose_says_so_when_nothing_repeats(db: psycopg.Connection[Any], ground: Ground, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.propose_command(db, parsed("propose")) == 0
    said = capsys.readouterr().out
    assert "0 findings reached the bar in 0 comparisons" in said and "Nothing to propose." in said and hypotheses(db) == 0


def test_the_command_refuses_what_it_does_not_know(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.build_parser().parse_args(["search", "--metric", "luck"])
    assert stop.value.code == 2
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["search", "--dimension", "zodiac"])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["search", "--until", "next week"])
    assert cli.options(cli.build_parser().parse_args(["search", "--metric", "clv", "--metric", "clv", "--dimension", "team"])) == {
        "min_matches": ps.MIN_MATCHES, "min_z": ps.MIN_Z, "half_min_matches": ps.HALF_MIN_MATCHES, "half_min_z": ps.HALF_MIN_Z, "alpha": ps.ALPHA,
        "metrics": ("clv",), "dimensions": ("team",)}
    assert cli.main(["search", "--days", "1"]) == 0
    assert "pattern search search-v1" in capsys.readouterr().out


def test_the_limit_and_the_picks_only_switch_reach_the_search(db: psycopg.Connection[Any], ground: Ground, capsys: pytest.CaptureFixture[str]) -> None:
    plant(ground)
    rejected = ground.match(KICK)
    ground.settle(ground.decide(rejected, "OU", "Over", 2.5, state="RECHAZADO", p_model=0.4), "loss")
    flags = ("--metric", "clv", "--dimension", "competition")
    assert cli.search_command(db, parsed("search", *flags)) == 0
    every = capsys.readouterr().out
    assert cli.search_command(db, parsed("search", *flags, "--selected-only")) == 0
    picks = capsys.readouterr().out
    assert "settled decisions read: 161 in 161 matches" in every and "picks only" not in every
    assert "settled decisions read: 160 in 160 matches" in picks and "(90 days, picks only)" in picks

    assert cli.propose_command(db, parsed("propose", *flags, "--limit", "0", "--confirm")) == 0
    said = capsys.readouterr().out
    assert "0 would be proposed" in said and "beyond the 0 proposals of a search" in said and "Nothing to propose." in said and hypotheses(db) == 0


class Wired:
    """Stands in for the connection ``main`` opens: the test's own (so that it sees the world the test planted), which notes how it was asked for and
    whether it was committed or rolled back, and does neither for real - the test's transaction is rolled back at its end."""

    def __init__(self, db: psycopg.Connection[Any]) -> None:
        self.db = db
        self.options: str | None = "never opened"
        self.calls: list[str] = []

    def connect(self, url: str, options: str | None = None) -> Wired:
        self.options = options
        return self

    def __enter__(self) -> Wired:
        return self

    def __exit__(self, *error: object) -> None:
        return None

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.db, name)


def test_a_command_reads_through_a_connection_that_cannot_write_and_only_a_confirmed_proposal_writes_and_commits(
        db: psycopg.Connection[Any], ground: Ground, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    plant(ground)
    wired = Wired(db)
    monkeypatch.setattr(psycopg, "connect", wired.connect)
    flags = ["--metric", "clv", "--dimension", "competition", "--until", AT.isoformat()]

    assert cli.main(["search", *flags]) == 0
    assert (wired.options, wired.calls) == (cli.READ_ONLY, ["rollback"]), "a reading is rolled back, never committed, and its connection cannot write"
    wired.calls.clear()
    assert cli.main(["propose", *flags]) == 0
    assert (wired.options, wired.calls) == (cli.READ_ONLY, ["rollback"]) and hypotheses(db) == 0, "the dry run is a reading as well"
    wired.calls.clear()
    assert cli.main(["propose", *flags, "--confirm"]) == 0
    assert (wired.options, wired.calls) == (None, ["commit"]) and hypotheses(db) == 1, "only a confirmed proposal opens a connection that can write, and commits"
    capsys.readouterr()

    wired.calls.clear()
    assert cli.main(["search", *flags, "--alpha", "0"]) == 3, "an alpha of 0 cannot be corrected for: refused, with a message and a code of its own"
    assert capsys.readouterr().err.startswith("refused: ") and wired.calls == []


def test_the_option_of_the_connection_really_makes_it_read_only(migrated_database: str) -> None:
    assert cli.READ_ONLY == "-c default_transaction_read_only=on"
    with psycopg.connect(migrated_database, options=cli.READ_ONLY) as conn:
        assert scalar(conn.execute("SHOW default_transaction_read_only")) == "on"
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("CREATE TABLE core.pattern_search_should_not_exist (id int)")


def test_a_day_is_read_as_utc_and_an_instant_keeps_its_zone() -> None:
    assert cli.instant("2034-06-01") == datetime(2034, 6, 1, tzinfo=UTC)
    assert cli.instant("2034-06-01T09:30") == datetime(2034, 6, 1, 9, 30, tzinfo=UTC)
    assert cli.instant("2034-06-01T09:30:00+02:00") == datetime(2034, 6, 1, 7, 30, tzinfo=UTC)


def test_the_options_of_the_bar_and_the_window_are_the_ones_the_command_line_gave() -> None:
    args = cli.build_parser().parse_args(["search", "--min-matches", "7", "--min-z", "2.5", "--half-min-matches", "4", "--half-min-z", "0.5",
                                          "--alpha", "0.01"])
    assert cli.options(args) == {"min_matches": 7, "min_z": 2.5, "half_min_matches": 4, "half_min_z": 0.5, "alpha": 0.01}
    assert cli.build_parser().parse_args(["propose"]).days == cli.build_parser().parse_args(["search"]).days == ps.WINDOW_DAYS == 90
