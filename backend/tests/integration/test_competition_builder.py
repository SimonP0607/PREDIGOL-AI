"""The builder against the real schema (plan F2): a competition season read from the database, its stages and ties written,
every fixture given its stage / tie / leg - once, idempotently, without touching what other jobs read.

The pure rules are tested in ``tests/unit/test_competition_{stages,ties,seasons}.py``. What is tested here is what only the
database can show: the upserts and their constraints, the ids staying put when a rebuild changes a tie, the stale rows going,
``core.fixtures.updated_at`` left alone, the lock per season, a failing season never holding back the others, the clock
(a tie waiting for a leg gives up as days pass) and the audit that recomputes the aggregates in SQL.

Every test ends by comparing what is STORED with what the pure layer says about the fixtures as they stand
(``assert_stored_is_the_build``), so a column that is written wrongly, or not at all, fails whatever the scenario."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.rows import dict_row

from fbi.competitions import builder, seasons
from fbi.competitions import stages as stg
from fbi.competitions import ties as tl
from fbi.ingestion import competition_structure
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, Seed, _dsn
from tests.integration.helpers import scalar

pytestmark = pytest.mark.integration

D0 = datetime(2025, 8, 1, 19, tzinfo=UTC)
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
TOUCHED = datetime(2026, 1, 1, 0, tzinfo=UTC)
"""The ``updated_at`` every fixture is created with: the builder must leave it exactly like this."""
GROUP = {"FT": "finished", "AET": "finished", "PEN": "finished", "NS": "scheduled", "PST": "postponed",
         "CANC": "cancelled", "WO": "cancelled", "AWD": "cancelled"}
SCRATCH = "fbi_test_builder"

STAGE_COLUMNS = ("stage", "ordinal", "phase", "base_stage", "is_replay", "kind", "role", "rule", "numbered", "round_key",
                 "teams", "round_no", "fixtures", "first_kickoff_at", "last_kickoff_at", "tie_format", "tie_reason",
                 "ties", "stages_version", "ties_version", "build_hash")
TIE_COLUMNS = ("stage_id", "team_a_id", "team_b_id", "format", "status", "legs", "played", "aggregate_a", "aggregate_b",
               "winner_team_id", "decided_by", "reason", "decided_at", "shootout_a", "shootout_b", "winner_check", "flags",
               "version")


@dataclass
class World:
    db: psycopg.Connection[Any]
    payload_hash: str
    competition: int
    league: int
    season: int
    team: dict[int, int]
    counter: int = 0

    def fixture(self, rnd: str | None, home: int, away: int, day: int, goals: tuple[int, int] | None = None,
                status: str = "FT", *, ft: tuple[int, int] | None = None, et: tuple[int, int] | None = None,
                pens: tuple[int, int] | None = None, season: int | None = None) -> int:
        """A fixture ``day`` days after ``D0`` between team numbers ``home`` and ``away``; with ``goals`` it has a result
        (stored two hours after kick-off, the way the first result of a match is)."""
        self.counter += 1
        kickoff = D0 + timedelta(days=day)
        full_time = ft or goals
        with self.db.cursor() as cur:
            cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                "round, status_short, status_group, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (self.league * 1000 + self.counter, season or self.season, self.team[home], self.team[away], kickoff, rnd,
                 status, GROUP[status], TOUCHED))
            fixture_id = scalar(cur)
            if goals is not None and full_time is not None:
                cur.execute(
                    "INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, ft_goals_away, "
                    "et_goals_home, et_goals_away, pen_home, pen_away, settled_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (fixture_id, goals[0], goals[1], full_time[0], full_time[1], et[0] if et else None,
                     et[1] if et else None, pens[0] if pens else None, pens[1] if pens else None,
                     kickoff + timedelta(hours=2)))
        return fixture_id

    def set_goals(self, fixture_id: int, home: int, away: int) -> None:
        """The provider corrects a result."""
        self.db.execute("UPDATE core.fixture_results SET goals_home = %s, goals_away = %s, ft_goals_home = %s, "
                        "ft_goals_away = %s WHERE fixture_id = %s", (home, away, home, away, fixture_id))

    def facts(self, fixture_id: int, at: datetime, home_winner: bool | None, away_winner: bool | None) -> None:
        """One observation of the provider's winner flags."""
        self.db.execute("INSERT INTO core.fixture_facts (fixture_id, observed_at, home_winner, away_winner, payload_hash, "
                        "normalizer_version) VALUES (%s, %s, %s, %s, %s, 'test')",
                        (fixture_id, at, home_winner, away_winner, self.payload_hash))

    def another_season(self, year: int) -> int:
        with self.db.cursor() as cur:
            cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, %s) RETURNING id",
                        (self.competition, year))
            return int(scalar(cur))

    def points(self, fixture_id: int) -> tuple[Any, ...]:
        """(stage_id, leg, tie_id) of a fixture."""
        return self.rows("SELECT stage_id, leg, tie_id FROM core.fixtures WHERE id = %s", fixture_id)[0]

    def rows(self, sql: str, *params: Any) -> list[tuple[Any, ...]]:
        with self.db.cursor() as cur:
            cur.execute(sql, params)
            return [tuple(r) for r in cur.fetchall()]

    def dicts(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        with self.db.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def one(self, sql: str, *params: Any) -> Any:
        with self.db.cursor() as cur:
            cur.execute(sql, params)
            return scalar(cur)

    def stage_ids(self, season: int | None = None) -> dict[str, int]:
        return {stage: ident for ident, stage in self.rows(
            "SELECT id, stage FROM core.competition_stages WHERE competition_season_id = %s", season or self.season)}

    def tie_ids(self, season: int | None = None) -> dict[str, int]:
        """The id of the (one) tie of each stage that has one."""
        return dict(self.rows(
            "SELECT s.stage, t.id FROM core.ties t JOIN core.competition_stages s ON s.id = t.stage_id "
            "WHERE s.competition_season_id = %s", season or self.season))

    def versions(self) -> set[tuple[Any, ...]]:
        """The versions of the rules the stored stages were built with."""
        return set(self.rows("SELECT stages_version, ties_version FROM core.competition_stages "
                             "WHERE competition_season_id = %s", self.season))

    def physical(self, season: int | None = None) -> dict[str, list[tuple[Any, ...]]]:
        """Where each stored row physically is (``ctid``) and when it was built: a row that was rewritten, even with the
        same values, moves."""
        season = season or self.season
        return {
            "stages": self.rows("SELECT id, ctid::text, built_at FROM core.competition_stages "
                                "WHERE competition_season_id = %s ORDER BY id", season),
            "ties": self.rows("SELECT t.id, t.ctid::text, t.built_at FROM core.ties t JOIN core.competition_stages s "
                              "ON s.id = t.stage_id WHERE s.competition_season_id = %s ORDER BY t.id", season),
            "fixtures": self.rows("SELECT id, ctid::text FROM core.fixtures WHERE competition_season_id = %s ORDER BY id",
                                  season),
        }


def make_world(db: psycopg.Connection[Any], seed: Seed | None, league: int, *, teams: int = 8) -> World:
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                    "VALUES (%s, %s, 'cup', 'club', 'continental') RETURNING id", (league, f"Competition {league}"))
        competition = int(scalar(cur))
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2025, true) "
                    "RETURNING id", (competition,))
        season = int(scalar(cur))
        team = {}
        for n in range(1, teams + 1):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                        (league * 100 + n, f"Team {league}-{n}"))
            team[n] = int(scalar(cur))
    return World(db, seed.payload_hash if seed is not None else "", competition, league, season, team)


def champions_league(w: World, *, season: int | None = None, shift: int = 0) -> dict[str, int]:
    """Two-legged qualifying, a group stage, two-legged last 16 and quarter-finals, a final decided on penalties. Team 1
    wins every tie, so each round agrees with the one before (the next round is the witness that confirms the winner)."""
    s = season
    return {
        "q1": w.fixture("3rd Qualifying Round", 1, 2, shift + 0, (1, 0), season=s),
        "q2": w.fixture("3rd Qualifying Round", 2, 1, shift + 7, (1, 1), season=s),
        "g1": w.fixture("Group Stage - 1", 1, 3, shift + 30, (0, 0), season=s),
        "g2": w.fixture("Group Stage - 1", 4, 5, shift + 30, (2, 1), season=s),
        "r1": w.fixture("Round of 16", 1, 4, shift + 100, (1, 0), season=s),
        "r2": w.fixture("Round of 16", 4, 1, shift + 107, (0, 0), season=s),
        "k1": w.fixture("Quarter-finals", 1, 6, shift + 130, (2, 0), season=s),
        "k2": w.fixture("Quarter-finals", 6, 1, shift + 137, (1, 1), season=s),
        "fin": w.fixture("Final", 1, 7, shift + 200, (1, 1), "PEN", ft=(1, 1), pens=(4, 3), season=s),
    }


def stored_form(row: dict[str, Any]) -> dict[str, Any]:
    """A row the builder writes, as the database gives it back (timestamps are written as ISO text)."""
    return {k: datetime.fromisoformat(v) if k.endswith("_at") and isinstance(v, str) else v for k, v in row.items()}


def assert_stored_is_the_build(w: World, *, now: datetime = NOW, season: int | None = None) -> seasons.SeasonBuild:
    """Whatever a test did, the rows in the database are exactly what the pure layer says of the fixtures as they stand:
    every column of every stage and tie, and the stage / leg / tie of every fixture."""
    season = season or w.season
    build = seasons.build_season(builder.load_fixtures(w.db, season), now=now)
    digest = seasons.fingerprint(build)
    stages = w.dicts(f"SELECT {', '.join(STAGE_COLUMNS)} FROM core.competition_stages WHERE competition_season_id = %s "
                     "ORDER BY ordinal", season)
    assert stages == [stored_form(r) for r in builder.stage_rows(build, digest)]

    ids = w.stage_ids(season)
    ties = w.dicts(f"SELECT {', '.join('t.' + c for c in TIE_COLUMNS)} FROM core.ties t WHERE t.stage_id = ANY(%s) "
                   "ORDER BY t.stage_id, LEAST(t.team_a_id, t.team_b_id)", list(ids.values()))
    wanted = sorted((builder.tie_row(t, ids[t.stage]) for t in build.ties),
                    key=lambda r: (r["stage_id"], min(r["team_a_id"], r["team_b_id"])))
    assert ties == [stored_form(r) for r in wanted]

    got = {fid: (stage, leg, tie_stage, low, high) for fid, stage, leg, tie_stage, low, high in w.rows(
        "SELECT f.id, s.stage, f.leg, ts.stage, LEAST(t.team_a_id, t.team_b_id), GREATEST(t.team_a_id, t.team_b_id) "
        "FROM core.fixtures f LEFT JOIN core.competition_stages s ON s.id = f.stage_id "
        "LEFT JOIN core.ties t ON t.id = f.tie_id LEFT JOIN core.competition_stages ts ON ts.id = t.stage_id "
        "WHERE f.competition_season_id = %s", season)}
    wanted_slots = {fid: (slot.stage, slot.leg, *(slot.tie or (None, None, None))) for fid, slot in build.slots.items()}
    assert got == wanted_slots
    assert w.one("SELECT count(*) FROM core.fixtures WHERE competition_season_id = %s AND updated_at <> %s",
                 season, TOUCHED) == 0, "the builder never touches updated_at: other jobs read it as 'this fixture changed'"
    return build


# ── the first build ─────────────────────────────────────────────────────────


def test_a_season_is_built_and_every_fixture_knows_its_stage_tie_and_leg(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99801)
    f = champions_league(w)
    revisions = "SELECT count(*) FROM core.fixture_result_revisions WHERE fixture_id = ANY(%s)"

    report = builder.build_one(db, w.season, now=NOW)

    assert (report.first_build, report.changed, report.fixtures, report.stages, report.ties) == (True, True, 9, 5, 4)
    assert report.ties_by_status == {"decided": 4} and report.contradicted == 0 and report.unresolved_fixtures == 0
    assert (report.fixtures_updated, report.stages_removed, report.ties_removed) == (9, 0, 0)
    assert w.rows("SELECT stage, ordinal, kind, role, round_key, teams, fixtures, tie_format, ties, stages_version, "
                  "ties_version, built_at FROM core.competition_stages WHERE competition_season_id = %s ORDER BY ordinal",
                  w.season) == [
        ("3rd Qualifying Round", 1, "qualifying", "qualifying", "round_3", None, 2, "two_legged", 1, stg.VERSION, tl.VERSION, NOW),
        ("Group Stage", 2, "league", "group", None, None, 2, None, 0, stg.VERSION, tl.VERSION, NOW),
        ("Round of 16", 3, "knockout", "knockout", "round_of_16", 16, 2, "two_legged", 1, stg.VERSION, tl.VERSION, NOW),
        ("Quarter-finals", 4, "knockout", "knockout", "quarter_final", 8, 2, "two_legged", 1, stg.VERSION, tl.VERSION, NOW),
        ("Final", 5, "knockout", "final", "final", 2, 1, "single", 1, stg.VERSION, tl.VERSION, NOW),
    ]
    t = w.team
    assert w.rows("SELECT s.stage, t.team_a_id, t.team_b_id, t.format, t.status, t.legs, t.played, t.aggregate_a, "
                  "t.aggregate_b, t.winner_team_id, t.decided_by, t.shootout_a, t.shootout_b, t.winner_check, t.decided_at, "
                  "t.version FROM core.ties t JOIN core.competition_stages s ON s.id = t.stage_id "
                  "WHERE s.competition_season_id = %s ORDER BY s.ordinal", w.season) == [
        ("3rd Qualifying Round", t[1], t[2], "two_legged", "decided", 2, 2, 2, 1, t[1], "aggregate", None, None,
         "confirmed", D0 + timedelta(days=7, hours=2), tl.VERSION),
        ("Round of 16", t[1], t[4], "two_legged", "decided", 2, 2, 1, 0, t[1], "aggregate", None, None, "confirmed",
         D0 + timedelta(days=107, hours=2), tl.VERSION),
        ("Quarter-finals", t[1], t[6], "two_legged", "decided", 2, 2, 3, 1, t[1], "aggregate", None, None, "confirmed",
         D0 + timedelta(days=137, hours=2), tl.VERSION),
        ("Final", t[1], t[7], "single", "decided", 1, 1, 1, 1, t[1], "penalties", 4, 3, "unknown",
         D0 + timedelta(days=200, hours=2), tl.VERSION),
    ]
    stage_id, tie_id = w.stage_ids(), w.tie_ids()
    where = {"q1": ("3rd Qualifying Round", 1), "q2": ("3rd Qualifying Round", 2), "g1": ("Group Stage", None),
             "g2": ("Group Stage", None), "r1": ("Round of 16", 1), "r2": ("Round of 16", 2),
             "k1": ("Quarter-finals", 1), "k2": ("Quarter-finals", 2), "fin": ("Final", 1)}
    for name, (stage, leg) in where.items():
        assert w.points(f[name]) == (stage_id[stage], leg, tie_id.get(stage)), name
    assert w.one(revisions, list(f.values())) == 0, "no 'result revision' is logged: the builder writes no status or result"
    assert_stored_is_the_build(w)


def test_a_dry_run_writes_nothing_and_says_what_would_change(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99802)
    f = champions_league(w)

    first = builder.build_one(db, w.season, now=NOW, apply=False)

    assert (first.first_build, first.changed, first.fixtures, first.stages, first.ties) == (True, True, 9, 5, 4)
    assert first.fixtures_updated == 0 and first.digest
    assert w.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = %s", w.season) == 0
    assert w.one("SELECT count(*) FROM core.fixtures WHERE competition_season_id = %s AND stage_id IS NOT NULL", w.season) == 0
    assert builder.drift(db, [w.season], now=NOW) == [w.season], "never built is drift"

    built = builder.build_one(db, w.season, now=NOW)
    assert built.digest == first.digest
    assert w.one("SELECT DISTINCT build_hash FROM core.competition_stages WHERE competition_season_id = %s", w.season) == first.digest
    again = builder.build_one(db, w.season, now=NOW, apply=False)
    assert (again.first_build, again.changed) == (False, False)
    assert builder.drift(db, [w.season], now=NOW) == []

    w.set_goals(f["r2"], 2, 0)  # the provider corrects a result: the dry run sees it, the tables do not move
    seen = builder.build_one(db, w.season, now=NOW, apply=False)
    assert seen.changed and seen.contradicted == 1 and seen.digest != first.digest
    assert w.one("SELECT winner_team_id FROM core.ties t JOIN core.competition_stages s ON s.id = t.stage_id "
                 "WHERE s.stage = 'Round of 16' AND s.competition_season_id = %s", w.season) == w.team[1]
    assert builder.drift(db, [w.season], now=NOW) == [w.season]
    assert builder.build_one(db, w.season, now=NOW, apply=False, force=True).changed, "force says it would rewrite"


# ── rebuilding ──────────────────────────────────────────────────────────────


def test_a_rebuild_that_changes_nothing_writes_nothing_and_force_rewrites_in_place(db: psycopg.Connection[Any],
                                                                                  seed: Seed) -> None:
    w = make_world(db, seed, 99803)
    champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    before = w.physical()
    stage_id, tie_id = w.stage_ids(), w.tie_ids()

    quiet = builder.build_one(db, w.season, now=NOW + timedelta(hours=1))

    assert (quiet.first_build, quiet.changed, quiet.fixtures_updated) == (False, False, 0)
    assert (quiet.stages, quiet.ties) == (5, 4), "the report still says what the season is"
    assert w.physical() == before, "not one row was rewritten (not even built_at)"

    forced = builder.build_one(db, w.season, now=NOW + timedelta(hours=2), force=True)

    assert (forced.changed, forced.first_build, forced.fixtures_updated) == (True, False, 0)
    after = w.physical()
    assert after["fixtures"] == before["fixtures"], "the fixtures already pointed where they should: not rewritten"
    assert [r[0] for r in after["stages"]] == [r[0] for r in before["stages"]] and w.stage_ids() == stage_id
    assert [r[0] for r in after["ties"]] == [r[0] for r in before["ties"]] and w.tie_ids() == tie_id, "ids stay put"
    assert {r[2] for r in after["stages"]} == {r[2] for r in after["ties"]} == {NOW + timedelta(hours=2)}
    assert_stored_is_the_build(w)


def test_a_corrected_result_changes_the_tie_in_place_and_back(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99804)
    f = champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    ties = w.tie_ids()
    first_hash = w.one("SELECT DISTINCT build_hash FROM core.competition_stages WHERE competition_season_id = %s", w.season)
    last16 = "SELECT winner_team_id, aggregate_a, aggregate_b, winner_check, decided_by FROM core.ties WHERE id = %s"
    assert w.rows(last16, ties["Round of 16"]) == [(w.team[1], 1, 0, "confirmed", "aggregate")]

    # the second leg ends 2-0 to the home side (team 4) instead of 0-0: team 4 wins the tie on the pitch...
    w.set_goals(f["r2"], 2, 0)
    flipped = builder.build_one(db, w.season, now=NOW)

    assert (flipped.changed, flipped.first_build, flipped.fixtures_updated) == (True, False, 0)
    assert (flipped.stages_removed, flipped.ties_removed, flipped.contradicted) == (0, 0, 1)
    assert w.tie_ids() == ties, "the same pairing is the same row"
    # ... and the next round says otherwise (team 1 plays the quarter-finals, team 4 does not): the pitch wins, the audit lists it
    assert w.rows(last16, ties["Round of 16"]) == [(w.team[4], 1, 2, "contradicted", "aggregate")]
    assert_stored_is_the_build(w)

    w.set_goals(f["r2"], 0, 0)  # corrected back
    back = builder.build_one(db, w.season, now=NOW)

    assert (back.changed, back.contradicted) == (True, 0)
    assert w.rows(last16, ties["Round of 16"]) == [(w.team[1], 1, 0, "confirmed", "aggregate")]
    assert w.one("SELECT DISTINCT build_hash FROM core.competition_stages WHERE competition_season_id = %s", w.season) == first_hash, (
        "the same facts give the same digest")
    assert_stored_is_the_build(w)


def test_a_renamed_round_moves_its_fixtures_and_leaves_no_orphans(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99805)
    f = champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    old_stage, old_tie = w.stage_ids()["Round of 16"], w.tie_ids()["Round of 16"]

    db.execute("UPDATE core.fixtures SET round = '8th Finals' WHERE id = ANY(%s)", ([f["r1"], f["r2"]],))
    report = builder.build_one(db, w.season, now=NOW)

    assert (report.changed, report.stages, report.ties) == (True, 5, 4)
    assert (report.stages_removed, report.ties_removed, report.fixtures_updated) == (1, 1, 2)
    stage_id, tie_id = w.stage_ids(), w.tie_ids()
    assert "Round of 16" not in stage_id and "Round of 16" not in tie_id
    assert w.one("SELECT count(*) FROM core.competition_stages WHERE id = %s", old_stage) == 0
    assert w.one("SELECT count(*) FROM core.ties WHERE id = %s", old_tie) == 0
    assert w.points(f["r1"]) == (stage_id["8th Finals"], 1, tie_id["8th Finals"])
    assert w.points(f["r2"]) == (stage_id["8th Finals"], 2, tie_id["8th Finals"])
    assert w.one("SELECT count(*) FROM core.fixtures WHERE competition_season_id = %s AND stage_id IS NULL", w.season) == 0
    assert w.one("SELECT count(*) FROM core.ties t LEFT JOIN core.competition_stages s ON s.id = t.stage_id "
                 "WHERE s.id IS NULL") == 0
    assert w.one("SELECT stage FROM core.competition_stages WHERE competition_season_id = %s AND ordinal = 3", w.season) == "8th Finals"
    assert_stored_is_the_build(w)


def test_a_fixture_that_leaves_the_season_takes_its_stage_and_tie_with_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99806)
    f = champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    quarter = w.tie_ids()["Quarter-finals"]
    assert w.one("SELECT winner_check FROM core.ties WHERE id = %s", quarter) == "confirmed", "the final is its witness"

    db.execute("DELETE FROM core.fixtures WHERE id = %s", (f["fin"],))
    report = builder.build_one(db, w.season, now=NOW)

    assert (report.changed, report.stages, report.ties, report.stages_removed, report.ties_removed) == (True, 4, 3, 1, 1)
    assert "Final" not in w.stage_ids() and "Final" not in w.tie_ids()
    assert w.tie_ids()["Quarter-finals"] == quarter, "the quarter-final is the same row..."
    assert w.one("SELECT winner_check FROM core.ties WHERE id = %s", quarter) == "unknown", (
        "...no longer confirmed: nothing comes after it")
    assert_stored_is_the_build(w)


def test_a_season_whose_fixtures_are_all_gone_has_nothing_left_stored(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99807)
    champions_league(w)
    builder.build_one(db, w.season, now=NOW)

    db.execute("DELETE FROM core.fixtures WHERE competition_season_id = %s", (w.season,))
    report = builder.build_one(db, w.season, now=NOW)

    assert (report.changed, report.first_build, report.fixtures, report.stages, report.ties) == (True, False, 0, 0, 0)
    assert (report.stages_removed, report.ties_removed) == (5, 4)
    assert w.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = %s", w.season) == 0
    assert w.one("SELECT count(*) FROM core.ties") == 0
    again = builder.build_one(db, w.season, now=NOW)
    assert (again.changed, again.first_build) == (False, False), "an empty season stays empty without writing"
    assert_stored_is_the_build(w)


def test_a_season_that_never_had_fixtures_is_not_a_first_build(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99808)

    report = builder.build_one(db, w.season, now=NOW)

    assert (report.first_build, report.changed, report.fixtures, report.stages, report.ties) == (False, False, 0, 0, 0)


def test_two_seasons_of_one_competition_never_mix(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99809)
    older = w.another_season(2024)
    champions_league(w)
    champions_league(w, season=older, shift=-365)  # the same teams meet in the same rounds a year earlier
    new_report = builder.build_one(db, w.season, now=NOW)
    old_report = builder.build_one(db, older, now=NOW)
    assert (new_report.stages, new_report.ties, old_report.stages, old_report.ties) == (5, 4, 5, 4)
    assert set(w.stage_ids().values()).isdisjoint(w.stage_ids(older).values())
    assert set(w.tie_ids().values()).isdisjoint(w.tie_ids(older).values())
    assert_stored_is_the_build(w)
    assert_stored_is_the_build(w, season=older)
    other_season = w.physical(older)

    db.execute("DELETE FROM core.fixtures WHERE competition_season_id = %s AND round = 'Final'", (w.season,))
    rebuilt = builder.build_one(db, w.season, now=NOW)

    assert (rebuilt.stages_removed, rebuilt.ties_removed) == (1, 1)
    assert w.physical(older) == other_season, "the other season was not touched"
    assert (len(w.stage_ids()), len(w.stage_ids(older))) == (4, 5)
    assert_stored_is_the_build(w)
    assert_stored_is_the_build(w, season=older)


# ── what the fixtures say ───────────────────────────────────────────────────


def test_the_winner_flags_of_the_provider_settle_a_level_tie_and_only_the_latest_observation_counts(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99810)
    final = w.fixture("Final", 1, 2, 0, (1, 1))  # level, the provider kept FT and stored no shoot-out
    builder.build_one(db, w.season, now=NOW)
    assert w.rows("SELECT status, reason, winner_team_id FROM core.ties") == [("unresolved", "level_without_shootout", None)]

    w.facts(final, D0 + timedelta(hours=1), home_winner=False, away_winner=True)  # an early reading of the flags
    w.facts(final, D0 + timedelta(hours=3), home_winner=True, away_winner=False)  # the later one corrects it
    loaded = {x.fixture_id: x for x in builder.load_fixtures(db, w.season)}[final]
    assert (loaded.home_winner, loaded.away_winner) == (True, False), "the latest observation, not the first"
    assert (loaded.goals_home, loaded.goals_away, loaded.ft_home, loaded.status) == (1, 1, 1, "FT")
    assert loaded.settled_at == D0 + timedelta(hours=2)

    builder.build_one(db, w.season, now=NOW)

    assert w.rows("SELECT status, winner_team_id, decided_by, flags, decided_at, aggregate_a, aggregate_b FROM core.ties") == [
        ("decided", w.team[1], "penalties", ["shootout_not_stored"], D0 + timedelta(hours=2), 1, 1)]
    assert_stored_is_the_build(w)

    w.facts(final, D0 + timedelta(hours=5), home_winner=None, away_winner=None)  # the newest observation says nothing
    builder.build_one(db, w.season, now=NOW)
    assert w.rows("SELECT status, reason, winner_team_id FROM core.ties") == [("unresolved", "level_without_shootout", None)]
    assert_stored_is_the_build(w)


def test_a_league_season_has_stages_but_no_ties_and_a_fixture_without_a_round_is_kept_unresolved(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99811)
    f = {"a": w.fixture("Regular Season - 1", 1, 2, 0, (1, 0)), "b": w.fixture("Regular Season - 2", 3, 4, 7, (2, 2)),
         "c": w.fixture(None, 5, 6, 8, (0, 0))}

    report = builder.build_one(db, w.season, now=NOW)

    assert (report.stages, report.ties, report.unresolved_fixtures) == (2, 0, 1)
    assert w.rows("SELECT stage, kind, role, rule, numbered, fixtures, tie_format, ties FROM core.competition_stages "
                  "WHERE competition_season_id = %s ORDER BY ordinal", w.season) == [
        ("Regular Season", "league", "league", "league_format", True, 2, None, 0),
        ("", "unresolved", "unresolved", "no_rule", False, 1, None, 0)]
    league = w.stage_ids()["Regular Season"]
    assert w.points(f["a"]) == (league, None, None) and w.points(f["b"]) == (league, None, None)
    assert w.points(f["c"]) == (w.stage_ids()[""], None, None), "unresolved is a state, not a failure: it has a stage"
    assert w.one("SELECT count(*) FROM core.ties") == 0
    assert builder.coverage(db, tracked_only=False, seasons=[w.season])["unresolved"] == 1
    assert_stored_is_the_build(w)


def test_a_replay_is_the_second_leg_of_the_tie_it_replays(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99812)
    first = w.fixture("3rd Round", 1, 2, 0, (1, 1))
    other = w.fixture("3rd Round", 3, 4, 0, (2, 0))
    replay = w.fixture("3rd Round Replays", 2, 1, 5, (0, 1))

    builder.build_one(db, w.season, now=NOW)

    stage = w.stage_ids()
    assert w.rows("SELECT stage, is_replay, base_stage, ties, fixtures FROM core.competition_stages "
                  "WHERE competition_season_id = %s ORDER BY ordinal", w.season) == [
        ("3rd Round", False, "3rd Round", 2, 2), ("3rd Round Replays", True, "3rd Round", 0, 1)]
    tie = w.rows("SELECT id, format, status, legs, played, winner_team_id, decided_by, aggregate_a FROM core.ties "
                 "WHERE stage_id = %s AND team_a_id = %s", stage["3rd Round"], w.team[1])[0]
    assert tie[1:] == ("replay", "decided", 2, 2, w.team[1], "normal_time", None), "a replay has no aggregate"
    assert w.points(first) == (stage["3rd Round"], 1, tie[0])
    assert w.points(replay) == (stage["3rd Round Replays"], 2, tie[0]), "the replay sits in its own stage, in the tie it replays"
    single = w.rows("SELECT format, winner_team_id, aggregate_a, aggregate_b FROM core.ties WHERE stage_id = %s AND team_a_id = %s",
                    stage["3rd Round"], w.team[3])
    assert single == [("single", w.team[3], 2, 0)]
    assert w.points(other)[1] == 1
    assert w.one("SELECT count(*) FROM core.ties") == 2
    assert_stored_is_the_build(w)


def test_a_stage_that_is_not_a_bracket_gets_no_ties_and_says_why(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99813)
    f = [w.fixture("Playoffs", 1, 2, 0, (1, 0)), w.fixture("Playoffs", 2, 3, 3, (1, 1)), w.fixture("Playoffs", 3, 1, 6, (0, 2))]

    report = builder.build_one(db, w.season, now=NOW)

    assert (report.stages, report.ties) == (1, 0)
    assert w.rows("SELECT stage, kind, role, tie_format, tie_reason, ties FROM core.competition_stages") == [
        ("Playoffs", "knockout", "playoff", "not_a_bracket", "a_team_plays_several_opponents", 0)]
    stage = w.stage_ids()["Playoffs"]
    assert [w.points(x) for x in f] == [(stage, None, None)] * 3
    assert_stored_is_the_build(w)


def test_a_cancelled_match_has_a_stage_but_belongs_to_no_tie(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99814)
    f = {"first": w.fixture("Quarter-finals", 1, 2, 0, (2, 0)), "second": w.fixture("Quarter-finals", 2, 1, 7, None, "CANC"),
         "other_first": w.fixture("Quarter-finals", 3, 4, 0, (1, 0)),
         "other_second": w.fixture("Quarter-finals", 4, 3, 7, (1, 1))}

    report = builder.build_one(db, w.season, now=NOW)

    stage = w.stage_ids()["Quarter-finals"]
    assert (report.stages, report.ties, report.ties_by_status["unresolved"], report.ties_by_status["decided"]) == (1, 2, 1, 1)
    assert w.points(f["second"]) == (stage, None, None), "a cancelled match is in no tie"
    lone = w.rows("SELECT legs, played, status, reason, winner_team_id, flags FROM core.ties WHERE team_a_id = %s", w.team[1])
    assert lone == [(1, 1, "unresolved", "second_leg_missing", None, ["second_leg_not_listed"])]
    tie = w.points(f["first"])[2]
    assert tie is not None and w.points(f["other_first"])[2] != tie
    assert w.points(f["other_second"])[1] == 2
    assert builder.coverage(db, tracked_only=False, seasons=[w.season]) == {
        "fixtures": 4, "with_stage": 4, "unresolved": 0, "in_ties": 4, "with_tie": 3}
    assert_stored_is_the_build(w)


def test_a_tie_waiting_for_a_leg_gives_up_as_days_pass_and_a_rebuild_notices(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99815)
    w.fixture("Quarter-finals", 1, 2, 0, (2, 0))
    w.fixture("Quarter-finals", 2, 1, 7, None, "NS")
    w.fixture("Quarter-finals", 3, 4, 0, (1, 0))
    w.fixture("Quarter-finals", 4, 3, 7, (1, 1))
    waiting = "SELECT id, status, reason, played FROM core.ties WHERE team_a_id = %s"

    day3 = builder.build_one(db, w.season, now=D0 + timedelta(days=3))
    tie_id, status, reason, played = w.rows(waiting, w.team[1])[0]
    assert (status, reason, played) == ("in_progress", None, 1)
    assert day3.ties_by_status == {"in_progress": 1, "decided": 1}
    assert_stored_is_the_build(w, now=D0 + timedelta(days=3))

    day8 = builder.build_one(db, w.season, now=D0 + timedelta(days=8))
    assert day8.changed is False, "a day later the second leg is still to come: the build is the same, nothing is written"
    assert w.rows(waiting, w.team[1]) == [(tie_id, "in_progress", None, 1)]

    day12 = builder.build_one(db, w.season, now=D0 + timedelta(days=12))
    assert day12.changed is True and day12.fixtures_updated == 0
    assert w.rows(waiting, w.team[1]) == [(tie_id, "unresolved", "second_leg_missing", 1)], "the same row, now unresolved"
    assert_stored_is_the_build(w, now=D0 + timedelta(days=12))


# ── which seasons, and how many ─────────────────────────────────────────────


def test_pending_seasons_come_never_built_first_then_old_rules_then_those_near_now(db: psycopg.Connection[Any],
                                                                               seed: Seed) -> None:
    near = (NOW - D0).days + 2
    # created in the order the answer must NOT come in, so that priority beats the order of the ids
    recent = make_world(db, seed, 99820)
    recent.fixture("Group Stage - 1", 1, 2, near, None, "NS")
    old_rules = make_world(db, seed, 99821)
    champions_league(old_rules)
    never = make_world(db, seed, 99822)
    champions_league(never)
    quiet = make_world(db, seed, 99823)
    champions_league(quiet)
    for w in (recent, old_rules, quiet):
        builder.build_one(db, w.season, now=NOW)
    db.execute("UPDATE core.competition_stages SET ties_version = 'ties-0' WHERE competition_season_id = %s",
               (old_rules.season,))
    mine = {never.season, old_rules.season, recent.season, quiet.season}

    def pending() -> list[int]:
        return [cs for cs in builder.pending(db, now=NOW) if cs in mine]

    assert pending() == [never.season, old_rules.season, recent.season], (
        "never built, then built by older rules, then a fixture near now; the quiet one is left alone")

    done = builder.build_many(db, pending(), now=NOW, commit=False)

    assert (done.seasons, done.changed, done.unchanged, done.first_builds, done.failed) == (3, 2, 1, 1, 0), (
        "the season with a fixture near now is read again and, nothing having changed, writes nothing")
    assert pending() == [recent.season], "only the season with a fixture near now is left to read again"
    again = builder.build_many(db, pending(), now=NOW, commit=False)
    assert (again.seasons, again.changed, again.unchanged) == (1, 0, 1)
    assert old_rules.versions() == {(stg.VERSION, tl.VERSION)}


def test_the_seasons_nearest_to_now_come_first_and_the_sweep_adds_every_other_season_last(db: psycopg.Connection[Any],
                                                                                         seed: Seed) -> None:
    today = (NOW - D0).days
    # created in the order the answer must NOT come in: 30 days ahead, two days back, one day ahead
    built: dict[str, World] = {}
    for name, league, day in (("far", 99850, today + 30), ("behind", 99851, today - 2), ("near", 99852, today + 1)):
        built[name] = make_world(db, seed, league)
        built[name].fixture("Group Stage - 1", 1, 2, day, None, "NS")
        builder.build_one(db, built[name].season, now=NOW)
    quiet = make_world(db, seed, 99853)
    champions_league(quiet)  # a season that ended months ago
    builder.build_one(db, quiet.season, now=NOW)
    never = make_world(db, seed, 99854)
    champions_league(never)
    mine = {w.season for w in built.values()} | {quiet.season, never.season}
    far, behind, near = (built[n].season for n in ("far", "behind", "near"))

    def pending(**kwargs: bool) -> list[int]:
        return [cs for cs in builder.pending(db, now=NOW, **kwargs) if cs in mine]

    assert pending() == [never.season, near, behind, far], (
        "never built first, then by how close the nearest match is to now (31 hours ahead, 41 back, 30 days ahead); "
        "the season that ended months ago is not read")
    assert pending(everything=True) == [never.season, near, behind, far, quiet.season], "the sweep adds the rest, last"
    assert set(builder.pending(db, now=NOW, everything=True)) >= set(builder.pending(db, now=NOW))



def test_a_time_budget_stops_the_pass_between_seasons(db: psycopg.Connection[Any], seed: Seed) -> None:
    a = make_world(db, seed, 99824)
    champions_league(a)
    b = make_world(db, seed, 99825)
    champions_league(b)

    report = builder.build_many(db, [a.season, b.season], now=NOW, max_seconds=-1.0, commit=False)

    assert (report.seasons, report.stopped_for_time, report.seasons_left) == (0, True, 2)
    assert a.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = ANY(%s)",
                 [a.season, b.season]) == 0


def test_a_season_the_pure_layer_refuses_is_reported_and_the_others_go_on(db: psycopg.Connection[Any], seed: Seed,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    bad = make_world(db, seed, 99826)
    bad_ids = set(champions_league(bad).values())
    good = make_world(db, seed, 99827)
    champions_league(good)
    real = seasons.build_season

    def refusing(fixtures: Sequence[seasons.SeasonFixture], *, now: datetime) -> seasons.SeasonBuild:
        if any(x.fixture_id in bad_ids for x in fixtures):
            raise ValueError("a defect in the rules")
        return real(fixtures, now=now)

    monkeypatch.setattr(seasons, "build_season", refusing)

    report = builder.build_many(db, [bad.season, good.season], now=NOW, commit=False)

    assert (report.seasons, report.failed, report.changed, report.first_builds) == (1, 1, 1, 1)
    assert report.errors == [f"season {bad.season}: a defect in the rules"]
    assert bad.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = %s", bad.season) == 0
    assert bad.one("SELECT count(*) FROM core.fixtures WHERE competition_season_id = %s", bad.season) == 9, (
        "the caller's transaction is intact: only the season's own work was undone")
    monkeypatch.undo()
    assert_stored_is_the_build(good)


def test_a_season_the_database_refuses_leaves_no_half_written_season_and_the_others_go_on(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = make_world(db, seed, 99828)
    bad_ids = set(champions_league(bad).values())
    good = make_world(db, seed, 99829)
    champions_league(good)
    real = builder.stage_rows

    def corrupt(build: seasons.SeasonBuild, digest: str) -> list[dict[str, Any]]:
        rows = real(build, digest)
        if bad_ids & set(build.slots):
            rows[-1]["kind"] = "semi"  # a kind nobody reads: the table refuses it, after the other stages were written
        return rows

    monkeypatch.setattr(builder, "stage_rows", corrupt)

    report = builder.build_many(db, [bad.season, good.season], now=NOW, commit=False)

    assert (report.seasons, report.failed, report.changed) == (1, 1, 1)
    assert "CheckViolation" in report.errors[0] and report.errors[0].startswith(f"season {bad.season}:")
    assert bad.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = %s", bad.season) == 0
    assert bad.one("SELECT count(*) FROM core.fixtures WHERE competition_season_id = %s AND stage_id IS NOT NULL",
                   bad.season) == 0
    assert bad.one("SELECT count(*) FROM core.fixtures WHERE competition_season_id = %s", bad.season) == 9
    monkeypatch.undo()
    assert_stored_is_the_build(good)


def test_two_writers_never_build_the_same_season_at_once(db: psycopg.Connection[Any], seed: Seed,
                                                         migrated_database: str) -> None:
    a = make_world(db, seed, 99830)
    champions_league(a)
    b = make_world(db, seed, 99831)
    champions_league(b)
    other = psycopg.connect(migrated_database)
    try:
        # someone else (the worker, a person at the console) is writing season ``a``: they hold its lock
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s), %s::int)", (builder.LOCK_KEY, a.season))

        with pytest.raises(psycopg.errors.LockNotAvailable), db.transaction():
            db.execute("SET LOCAL lock_timeout = '300ms'")
            builder.build_one(db, a.season, now=NOW)

        assert a.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = %s", a.season) == 0
        assert builder.build_one(db, b.season, now=NOW).changed, "the lock is per season: another season is not held back"
        other.rollback()
        assert builder.build_one(db, a.season, now=NOW).changed, "released, the season can be built"
    finally:
        other.close()
    assert_stored_is_the_build(a)
    assert_stored_is_the_build(b)


# ── the checks from the outside ─────────────────────────────────────────────


def test_coverage_counts_what_has_a_stage_and_the_aggregate_check_recomputes_it_in_sql(db: psycopg.Connection[Any],
                                                                                      seed: Seed) -> None:
    w = make_world(db, seed, 99840)
    champions_league(w)
    mine = [w.season]

    assert builder.coverage(db, tracked_only=False, seasons=mine) == {
        "fixtures": 9, "with_stage": 0, "unresolved": 0, "in_ties": 0, "with_tie": 0}
    builder.build_one(db, w.season, now=NOW)
    assert builder.coverage(db, tracked_only=False, seasons=mine) == {
        "fixtures": 9, "with_stage": 9, "unresolved": 0, "in_ties": 7, "with_tie": 7}
    assert builder.coverage(db, seasons=mine)["fixtures"] == 0, "by default only the competitions that are followed count"
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (w.competition,))
    assert builder.coverage(db, seasons=mine)["with_stage"] == 9

    clean = {"checked": 4, "repaired": 0, "unknown": 0, "missing": 0, "different": 0}
    assert builder.aggregate_check(db, seasons=mine) == clean
    assert builder.aggregate_differences(db, seasons=mine) == []
    tie = w.tie_ids()["Round of 16"]
    db.execute("UPDATE core.ties SET aggregate_a = aggregate_a + 5 WHERE id = %s", (tie,))
    assert builder.aggregate_check(db, seasons=mine) == {**clean, "different": 1}, (
        "the check sums the legs' goals itself: a stored aggregate the builder got wrong cannot hide")
    assert builder.aggregate_differences(db, seasons=mine) == [
        {"tie_id": tie, "stored_a": 6, "stored_b": 0, "summed_a": 1, "summed_b": 0, "kind": "different"}]
    db.execute("UPDATE core.ties SET aggregate_a = NULL, aggregate_b = NULL WHERE id = %s", (tie,))
    assert builder.aggregate_check(db, seasons=mine) == {**clean, "missing": 1}, "legs with scores but no aggregate"
    assert [d["kind"] for d in builder.aggregate_differences(db, seasons=mine)] == ["missing"]


def test_a_tie_that_cannot_have_an_aggregate_is_not_reported_as_wrong(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The two ways the builder stores NO aggregate on purpose: a leg awarded without a score (a walkover), and a shoot-out
    the goals contradict (the sides were not level, so the provider's score cannot be the score of the match)."""
    w = make_world(db, seed, 99842)
    w.fixture("Quarter-finals", 1, 2, 0, (1, 0))
    w.fixture("Quarter-finals", 2, 1, 7, None, "WO")
    w.fixture("Quarter-finals", 3, 4, 0, (1, 0))
    w.fixture("Quarter-finals", 4, 3, 7, (1, 1), "PEN", ft=(1, 1), pens=(0, 1))
    builder.build_one(db, w.season, now=NOW)

    assert w.rows("SELECT team_a_id, status, reason, decided_by, aggregate_a, flags FROM core.ties "
                  "ORDER BY team_a_id") == [
        (w.team[1], "unresolved", "awarded_without_score", None, None, []),
        (w.team[3], "decided", None, "penalties", None, ["score_inconsistent_with_shootout"])]
    assert builder.aggregate_check(db, seasons=[w.season]) == {
        "checked": 2, "repaired": 0, "unknown": 2, "missing": 0, "different": 0}
    assert builder.aggregate_differences(db, seasons=[w.season]) == []
    assert_stored_is_the_build(w)


# ── the worker's job ────────────────────────────────────────────────────────


@pytest.fixture
def ledger_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The runs the job writes in the ledger. The real ledger commits (it must, to be visible to the watchdog), which would
    end the transaction a test runs in."""
    runs: list[dict[str, Any]] = []

    class FakeLedger:
        def __init__(self, conn: Any) -> None:
            self.conn = conn

        def open(self, job_type: str, *, params: dict[str, object] | None = None, **_: Any) -> int:
            runs.append({"job": job_type, "params": params, "counters": None, "notes": None})
            return len(runs)

        def close(self, run_id: int, counters: Any, *, notes: str | None = None) -> None:
            runs[run_id - 1].update(counters=counters, notes=notes)

    monkeypatch.setattr("fbi.ingestion.competition_structure.RunLedger", FakeLedger)
    return runs


def test_the_job_leaves_a_ledger_run_only_when_it_changed_something(db: psycopg.Connection[Any], seed: Seed,
                                                                   ledger_runs: list[dict[str, Any]]) -> None:
    runs = ledger_runs
    w = make_world(db, seed, 99841)
    champions_league(w)

    report = competition_structure.run_job(db, now=NOW, commit=False)

    assert report.failed == 0 and report.changed >= 1
    assert len(runs) == 1 and runs[0]["job"] == competition_structure.JOB == builder.JOB == "competition_structure"
    assert runs[0]["params"] == {"limit": 400, "max_seconds": 120.0, "stages": stg.VERSION, "ties": tl.VERSION,
                                 "sweep": False}
    counters = runs[0]["counters"]
    assert (counters.rows_inserted, counters.rows_updated, counters.rows_normalized) == (
        report.rows_written, report.fixtures_updated, report.seasons)
    assert counters.errors == [] and report.rows_written >= 9
    assert w.one("SELECT count(*) FROM core.fixtures WHERE competition_season_id = %s AND stage_id IS NOT NULL", w.season) == 9

    quiet = competition_structure.run_job(db, now=NOW, commit=False)

    assert (quiet.changed, quiet.failed) == (0, 0)
    assert len(runs) == 1, "a pass that changed nothing leaves no row in the ledger"
    assert_stored_is_the_build(w)


def test_the_daily_sweep_finds_a_result_corrected_long_after_its_season_left_the_window(
        db: psycopg.Connection[Any], seed: Seed, ledger_runs: list[dict[str, Any]]) -> None:
    w = make_world(db, seed, 99843)
    f = champions_league(w)  # played between August and February: months before NOW
    competition_structure.run_job(db, now=NOW, commit=False)
    assert_stored_is_the_build(w)
    runs_so_far = len(ledger_runs)
    winner = "SELECT winner_team_id, winner_check FROM core.ties t JOIN core.competition_stages s ON s.id = t.stage_id " \
             "WHERE s.stage = 'Round of 16' AND s.competition_season_id = %s"
    assert w.rows(winner, w.season) == [(w.team[1], "confirmed")]

    w.set_goals(f["r2"], 2, 0)  # the provider corrects the second leg: team 4 went through on the pitch

    ordinary = competition_structure.run_job(db, now=NOW, commit=False)
    assert (ordinary.changed, ordinary.failed) == (0, 0) and len(ledger_runs) == runs_so_far, "a season this old is not read"
    assert w.rows(winner, w.season) == [(w.team[1], "confirmed")], "so the tie still says what it said"

    sweep = competition_structure.run_job(db, now=NOW, commit=False, everything=True, limit=None)

    assert (sweep.changed, sweep.failed) == (1, 0) and sweep.seasons > 1, "every season was read, one needed writing"
    assert len(ledger_runs) == runs_so_far + 1
    assert ledger_runs[-1]["params"] == {"limit": None, "max_seconds": 120.0, "stages": stg.VERSION, "ties": tl.VERSION,
                                         "sweep": True}
    assert w.rows(winner, w.season) == [(w.team[4], "contradicted")], "the sporting winner, with the next round as witness"
    assert_stored_is_the_build(w)

    quiet = competition_structure.run_job(db, now=NOW, commit=False, everything=True, limit=None)
    assert (quiet.changed, quiet.failed) == (0, 0) and len(ledger_runs) == runs_so_far + 1, "a sweep that finds nothing is silent"


# ── the path the worker takes: real commits ─────────────────────────────────


def _scratch_config() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop_scratch() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def test_a_pass_that_commits_keeps_the_seasons_that_worked_and_leaves_out_the_ones_that_failed(
        migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other tests run inside one rolled-back transaction. The worker commits after every season; this one runs the
    same code with real commits, in a scratch database, and looks at what another connection sees."""
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop_scratch()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_scratch_config(), "head")
        with psycopg.connect(dsn) as work, psycopg.connect(dsn) as watcher:
            worlds = [make_world(work, None, 99850 + i) for i in range(5)]
            fixtures = [champions_league(w) for w in worlds]
            work.commit()
            refused, rejected = set(fixtures[1].values()), set(fixtures[3].values())
            real_build, real_rows = seasons.build_season, builder.stage_rows

            def build(rows: Sequence[seasons.SeasonFixture], *, now: datetime) -> seasons.SeasonBuild:
                if any(x.fixture_id in refused for x in rows):
                    raise ValueError("a defect in the rules")
                return real_build(rows, now=now)

            def stage_rows(b: seasons.SeasonBuild, digest: str) -> list[dict[str, Any]]:
                out = real_rows(b, digest)
                if rejected & set(b.slots):
                    out[-1]["kind"] = "semi"
                return out

            monkeypatch.setattr(seasons, "build_season", build)
            monkeypatch.setattr(builder, "stage_rows", stage_rows)

            report = builder.build_many(work, [w.season for w in worlds], now=NOW)

            assert (report.seasons, report.changed, report.failed, report.first_builds) == (3, 3, 2, 3)
            assert work.info.transaction_status == psycopg.pq.TransactionStatus.IDLE, "the connection is left usable"
            seen: dict[int, int] = dict(watcher.execute(
                "SELECT competition_season_id, count(*) FROM core.competition_stages GROUP BY 1").fetchall())
            assert seen == {worlds[0].season: 5, worlds[2].season: 5, worlds[4].season: 5}, (
                "what another connection sees: the seasons built before and after a failure are committed")
            assert watcher.execute("SELECT count(*) FROM core.fixtures WHERE stage_id IS NOT NULL").fetchone() == (27,)
            monkeypatch.undo()
            later = builder.build_many(work, [w.season for w in worlds], now=NOW)
            assert (later.changed, later.unchanged, later.failed) == (2, 3, 0), (
                "once the defect is gone the two seasons are built, and the three already built are left alone")
    finally:
        _drop_scratch()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous

