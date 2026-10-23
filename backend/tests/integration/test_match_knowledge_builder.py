"""Match Knowledge, built over a real database (``fbi.knowledge.builder``, plan F7): which matches are due, what is written, and what happens
when a match changes, two builders meet, a match fails or a pass is cut short.

The promises held here: a match is built when it is settled and again - as a NEW row that names the one it replaced - only when what it was
built from has changed; a match nobody has touched costs a read and writes nothing; a failure is the failing match's and no other's; and the
lines of the events follow the events. The transaction of every test is rolled back afterwards (``commit=False``; where the commits are the
point they are counted, not made)."""

from __future__ import annotations

import dataclasses
import json
import time
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.knowledge import builder, events, layers, reader

from .conftest import Seed
from .knowledge_world import KICKOFF, NOW, World, ev, goal

pytestmark = pytest.mark.integration

LATER = KICKOFF + timedelta(days=10)
"""A moment when every match of these tests has been settled for a long time."""


def build(db: psycopg.Connection[Any], *ids: int, **kw: Any) -> builder.BuildReport:
    return builder.build_many(db, list(ids), commit=False, **kw)


def rows(db: psycopg.Connection[Any], fid: int) -> list[dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intel.match_knowledge WHERE fixture_id = %s ORDER BY id", (fid,))
        return cur.fetchall()


def kinds(db: psycopg.Connection[Any], fid: int) -> list[tuple[Any, ...]]:
    return db.execute("SELECT seq, kind, period, side, player_side, pair_seq, flags FROM core.fixture_event_kinds WHERE fixture_id = %s ORDER BY seq",
                      (fid,)).fetchall()


def several(w: World, n: int, **kw: Any) -> list[int]:
    """``n`` finished matches, an hour apart, with a result and nothing else."""
    return [w.match(KICKOFF + timedelta(hours=i), **kw) for i in range(n)]


# ── one match ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_finished_match_is_built_once_and_what_is_stored_is_what_the_layers_say(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    report = build(db, fid)
    assert (report.seen, report.due, report.built, report.same_content, report.raced, report.failed, report.stopped) == (1, 1, 1, 0, 0, 0, None)
    (row,) = rows(db, fid)
    built = layers.build(reader.read(db, [fid])[fid].inputs)
    assert (row["version"], row["supersedes"], row["completeness"], row["known_at"]) == (layers.VERSION, None, "complete", built.known_at)
    assert row["layers"] == json.loads(json.dumps(built.layers)) and row["quality"] == built.quality
    assert (row["content_hash"], row["inputs_hash"]) == (built.content_hash, reader.signatures(db, [fid])[fid])
    assert set(row["layers"]) == set(layers.LAYERS)
    assert dict(report.by_completeness) == {"complete": 1} and report.by_layer[f"{layers.C7_CONTEXT}:off"] == 1
    assert 0 < report.bytes == report.biggest, "the weight of the one row built"


def test_the_lines_of_the_events_are_written_with_the_row(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    report = build(db, fid)
    assert report.kinds == 8
    got = kinds(db, fid)
    assert [(k[0], k[1], k[2], k[3]) for k in got] == [
        (0, "goal", "1H", "home"), (1, "yellow", "1H", "away"), (2, "yellow", "2H", "home"), (3, "second_yellow", "2H", "home"),
        (4, "penalty_goal", "2H", "away"), (5, "sub", "2H", "home"), (6, "goal", "2H", "home"), (7, "var_goal_cancelled", "2H", "away")]
    assert (got[2][5], got[3][5]) == (3, 2), "the two lines of a dismissal for two yellows name each other"
    assert list(got[2][6]) == ["second_of_pair"] and list(got[0][6]) == []
    assert db.execute("SELECT DISTINCT rules_version, source FROM core.fixture_event_kinds WHERE fixture_id = %s", (fid,)).fetchall() == [
        (events.VERSION, "api-football")]


def test_a_match_nobody_has_touched_costs_a_read_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    again = build(db, fid)
    assert (again.seen, again.due, again.built, again.kinds, again.bytes) == (1, 0, 0, 0, 0)
    assert len(rows(db, fid)) == 1


def test_the_provider_reading_the_match_again_and_finding_the_same_facts_adds_no_row(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    later = KICKOFF + timedelta(days=3)
    for table in ("fixture_events", "fixture_team_stats", "fixture_player_stats", "fixture_lineups"):
        db.execute(f"UPDATE core.{table} SET fetched_at = %s WHERE fixture_id = %s", (later, fid))
    db.execute("UPDATE core.fixture_results SET source_fetched_at = %s WHERE fixture_id = %s", (later, fid))
    assert build(db, fid).due == 0 and len(rows(db, fid)) == 1


def test_a_correction_of_the_result_adds_a_row_that_names_the_one_it_replaced_and_says_it_was_corrected(db: psycopg.Connection[Any],
                                                                                                     seed: Seed) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    db.execute("UPDATE core.fixture_results SET goals_home = 3, ft_goals_home = 3 WHERE fixture_id = %s", (fid,))
    report = build(db, fid)
    assert (report.due, report.built, report.same_content) == (1, 1, 0)
    first, second = rows(db, fid)
    assert (first["supersedes"], second["supersedes"]) == (None, first["id"])
    assert first["content_hash"] != second["content_hash"] and first["inputs_hash"] != second["inputs_hash"]
    old, new = first["layers"][layers.C1_RESULT]["data"], second["layers"][layers.C1_RESULT]["data"]
    assert (old["reg"], new["reg"]) == ([2, 1], [3, 1]) and "revisions" not in old
    assert new["revisions"]["n"] == 1 and new["revisions"]["kinds"] == ["score"]
    assert db.execute("SELECT id FROM intel.match_knowledge_latest WHERE fixture_id = %s", (fid,)).fetchall() == [(second["id"],)]


def test_a_change_that_no_layer_shows_adds_a_row_that_says_the_same(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid = w.golden()
    build(db, fid)
    w.team_stats(fid, "home", source="football-data.co.uk", shots=1)       # the statistics read are the other provider's: nothing shows it
    report = build(db, fid)
    assert (report.built, report.same_content) == (1, 1)
    first, second = rows(db, fid)
    assert second["supersedes"] == first["id"] and second["content_hash"] == first["content_hash"] and second["inputs_hash"] != first["inputs_hash"]


def test_a_match_that_goes_back_to_what_it_was_has_three_rows_and_the_newest_is_what_it_is(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    db.execute("UPDATE core.fixture_team_stats SET shots = 15 WHERE fixture_id = %s AND team_side = 'home'", (fid,))
    assert build(db, fid).built == 1
    db.execute("UPDATE core.fixture_team_stats SET shots = 14 WHERE fixture_id = %s AND team_side = 'home'", (fid,))
    report = build(db, fid)
    assert (report.built, report.same_content) == (1, 0), "it is not the same as the newest row: it is the same as the first"
    first, second, third = rows(db, fid)
    assert (first["supersedes"], second["supersedes"], third["supersedes"]) == (None, first["id"], second["id"])
    assert third["content_hash"] == first["content_hash"] != second["content_hash"]
    assert db.execute("SELECT id FROM intel.match_knowledge_latest WHERE fixture_id = %s", (fid,)).fetchall() == [(third["id"],)]


def test_a_row_of_another_version_of_the_rules_is_not_the_one_a_build_replaces(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    db.execute("INSERT INTO intel.match_knowledge (fixture_id, version, known_at, inputs_hash, content_hash, completeness, layers) "
               "VALUES (%s, 'mk-v0', %s, %s, %s, 'minimal', '{}')", (fid, KICKOFF, "a" * 64, "b" * 64))
    assert build(db, fid).built == 1
    old, new = rows(db, fid)
    assert (old["version"], new["version"], new["supersedes"]) == ("mk-v0", layers.VERSION, None)


def test_a_match_without_a_result_is_built_minimal_and_built_again_when_the_result_arrives(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid = w.match(KICKOFF, goals=None)
    build(db, fid)
    (row,) = rows(db, fid)
    assert row["completeness"] == "minimal" and row["layers"][layers.C1_RESULT]["status"] == "missing"
    assert "no_result" in row["quality"]["doubts"]
    w.result(fid, (1, 0))
    assert build(db, fid).built == 1
    second = rows(db, fid)[-1]
    assert second["supersedes"] == row["id"] and second["layers"][layers.C1_RESULT]["status"] == "ok"


def test_a_match_that_went_to_penalties_is_built_with_its_extra_time_and_its_shoot_out(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid = w.match(KICKOFF, goals=(2, 2), ft=(1, 1), et=(1, 1), pen=(4, 3), ht=(1, 0), status="PEN")
    lines = [goal(0, 20, "home", 501), goal(1, 70, "away", 601), goal(2, 100, "home", 502), goal(3, 115, "away", 602)]
    scored = {"home": [True, True, True, False, True], "away": [True, True, False, True, False]}
    for kick in range(5):
        for side, player in (("home", 510 + kick), ("away", 610 + kick)):
            hit = scored[side][kick]
            lines.append(ev(len(lines), 120, side, "Goal", "Penalty" if hit else "Missed Penalty", player=player, name=f"Man {player}",
                            comments="Penalty Shootout"))
    w.events(fid, lines)
    report = build(db, fid)
    assert (report.built, report.failed) == (1, 0)
    (row,) = rows(db, fid)
    result, goals = row["layers"][layers.C1_RESULT]["data"], row["layers"][layers.C3_EVENTS]["data"]
    assert (result["reg"], result["final"], result["pen"], result["decided_by"]) == ([1, 1], [2, 2], [4, 3], "penalties")
    assert goals["by_period"] == {"1H": [1, 0], "2H": [0, 1], "ET": [1, 1], "PEN": [4, 3]}
    assert goals["check"] == {"reg": True, "ht": True, "et": True, "pen": True}, "the provider's list gives every score the result states"
    shoot = [k for k in kinds(db, fid) if k[2] == "PEN"]
    assert sorted(k[1] for k in shoot) == ["shootout_goal"] * 7 + ["shootout_miss"] * 3
    assert [k[2] for k in kinds(db, fid)][:4] == ["1H", "2H", "ET", "ET"]


# ── the lines of the events ──────────────────────────────────────────────────────────────────────────────────────────────


def test_the_lines_of_the_events_follow_the_events(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    db.execute("DELETE FROM core.fixture_events WHERE fixture_id = %s AND seq = 7", (fid,))
    db.execute("UPDATE core.fixture_events SET detail = 'Own Goal' WHERE fixture_id = %s AND seq = 6", (fid,))
    report = build(db, fid)
    assert report.built == 1 and report.kinds == 2, "one line gone, one line changed: the other six are not touched"
    got = {k[0]: k for k in kinds(db, fid)}
    assert sorted(got) == [0, 1, 2, 3, 4, 5, 6]
    assert (got[6][1], got[6][3], got[6][4]) == ("own_goal", "home", "away"), "an own goal counts for the side it is filed under; the man is the other's"


def test_a_change_that_is_not_in_the_lines_leaves_the_lines_alone(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    db.execute("UPDATE core.fixture_events SET minute = 13 WHERE fixture_id = %s AND seq = 0", (fid,))
    report = build(db, fid)
    assert (report.built, report.kinds) == (1, 0), "the layer shows the minute and the table of kinds does not"


def test_when_the_events_are_gone_so_are_their_lines(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    db.execute("DELETE FROM core.fixture_events WHERE fixture_id = %s", (fid,))
    report = build(db, fid)
    assert (report.built, report.kinds) == (1, 8)
    assert kinds(db, fid) == [] and rows(db, fid)[-1]["layers"][layers.C3_EVENTS]["status"] == "missing"


def test_new_rules_build_the_match_again_and_read_the_lines_again(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    monkeypatch.setattr(events, "VERSION", "events-v2")
    monkeypatch.setattr(layers, "RULES", {**layers.RULES, "events": "events-v2"})
    report = build(db, fid)
    assert (report.due, report.built, report.kinds) == (1, 1, 8)
    assert db.execute("SELECT DISTINCT rules_version FROM core.fixture_event_kinds WHERE fixture_id = %s", (fid,)).fetchall() == [("events-v2",)]
    old, new = rows(db, fid)
    assert new["supersedes"] == old["id"] and old["layers"][layers.C3_EVENTS]["data"]["rules"] == "events-v1"
    assert new["layers"][layers.C3_EVENTS]["data"]["rules"] == "events-v2"


# ── two builders, a failure, a dry run, a limit ──────────────────────────────────────────────────────────────────────────


def test_the_builder_that_finds_the_place_taken_leaves_the_match_to_the_one_that_took_it(db: psycopg.Connection[Any], seed: Seed,
                                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    fid = World(db, seed).golden()
    real = builder.write

    def second_of_two(conn: psycopg.Connection[Any], read: reader.Read, built: layers.Knowledge, **kw: Any) -> tuple[int, int] | None:
        real(conn, read, built, **kw)            # the other builder got there first, from the same newest build...
        return real(conn, read, built, **kw)     # ... and this one finds the place taken

    monkeypatch.setattr(builder, "write", second_of_two)
    report = build(db, fid)
    assert (report.built, report.raced, report.failed, report.kinds, report.bytes) == (0, 1, 0, 0, 0)
    assert len(rows(db, fid)) == 1 and len(kinds(db, fid)) == 8, "one row and one set of lines"


def test_a_match_that_fails_is_left_and_the_others_are_built(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    a, bad, c = w.golden(), w.golden(KICKOFF + timedelta(hours=1)), w.golden(KICKOFF + timedelta(hours=2))
    real = layers.build

    def rule_that_cannot_cope(inp: layers.Inputs) -> layers.Knowledge:
        if inp.fixture.id == bad:
            raise RuntimeError("a rule that cannot cope")
        return real(inp)

    monkeypatch.setattr(layers, "build", rule_that_cannot_cope)
    report = build(db, a, bad, c)
    assert (report.seen, report.due, report.built, report.failed, report.stopped) == (3, 3, 2, 1, None)
    assert report.errors == [f"match {bad}: RuntimeError: a rule that cannot cope"]
    assert [len(rows(db, f)) for f in (a, bad, c)] == [1, 0, 1] and kinds(db, bad) == []
    monkeypatch.setattr(layers, "build", real)
    assert build(db, a, bad, c).built == 1, "the next pass builds it, and only it"


def test_a_row_the_database_refuses_is_the_failure_of_its_match_and_the_connection_goes_on(db: psycopg.Connection[Any], seed: Seed,
                                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    a, bad, c = w.golden(), w.golden(KICKOFF + timedelta(hours=1)), w.golden(KICKOFF + timedelta(hours=2))
    real = layers.build

    def short_hash(inp: layers.Inputs) -> layers.Knowledge:
        built = real(inp)
        return dataclasses.replace(built, content_hash="short") if inp.fixture.id == bad else built

    monkeypatch.setattr(layers, "build", short_hash)
    report = build(db, a, bad, c)
    assert (report.built, report.failed) == (2, 1) and "CheckViolation" in report.errors[0] and f"match {bad}" in report.errors[0]
    assert [len(rows(db, f)) for f in (a, bad, c)] == [1, 0, 1]
    assert len(kinds(db, a)) == 8 and kinds(db, bad) == [] and len(kinds(db, c)) == 8, "the savepoint of the failing match took its lines with it"


def test_a_value_the_reader_refuses_is_the_failure_of_its_match_and_not_of_its_chunk(db: psycopg.Connection[Any], seed: Seed,
                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    a, bad, c = w.golden(), w.golden(KICKOFF + timedelta(hours=1)), w.golden(KICKOFF + timedelta(hours=2))
    real = reader.read

    def picky(conn: psycopg.Connection[Any], ids: list[int]) -> dict[int, reader.Read]:
        if bad in ids:
            raise ValueError("a value the reader does not know")
        return real(conn, ids)

    monkeypatch.setattr(reader, "read", picky)
    report = build(db, a, bad, c)
    assert (report.seen, report.due, report.built, report.failed) == (3, 3, 2, 1)
    assert report.errors == [f"match {bad}: ValueError: a value the reader does not know"]
    assert [len(rows(db, f)) for f in (a, bad, c)] == [1, 0, 1]


def test_trouble_with_the_database_fails_the_chunk_and_three_failed_chunks_in_a_row_stop_the_pass(db: psycopg.Connection[Any], seed: Seed,
                                                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    ids = several(World(db, seed), 5)

    def timeout(conn: psycopg.Connection[Any], ids: list[int]) -> dict[int, str]:
        raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

    monkeypatch.setattr(reader, "signatures", timeout)
    report = build(db, *ids, chunk=1)
    assert (report.seen, report.failed, report.built, report.stopped, report.left) == (3, 3, 0, "errors", 2)
    assert "QueryCanceled" in report.errors[0]


def test_a_chunk_that_fails_does_not_stop_a_pass_whose_next_chunks_are_read(db: psycopg.Connection[Any], seed: Seed,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    ids = several(World(db, seed), 5)
    real = reader.signatures
    calls: list[int] = []

    def first_two_time_out(conn: psycopg.Connection[Any], chunk: list[int]) -> dict[int, str]:
        calls.append(len(calls))
        if len(calls) <= 2:
            raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        return real(conn, chunk)

    monkeypatch.setattr(reader, "signatures", first_two_time_out)
    report = build(db, *ids, chunk=1)
    assert (report.seen, report.failed, report.built, report.stopped) == (5, 2, 3, None)


def test_a_dry_run_says_what_it_would_do_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    report = build(db, fid, apply=False)
    assert (report.due, report.built, report.kinds) == (1, 1, 0) and report.bytes > 0
    assert rows(db, fid) == [] and kinds(db, fid) == []
    assert build(db, fid).built == 1, "and the real pass still has it to do"


def test_a_limit_stops_the_pass_and_says_how_many_are_left(db: psycopg.Connection[Any], seed: Seed) -> None:
    ids = several(World(db, seed), 5)
    report = build(db, *ids, limit=2)
    assert (report.due, report.built, report.stopped, report.left) == (5, 2, "limit", 3)
    assert build(db, *ids).built == 3, "the next pass does the rest"


def test_a_limit_is_checked_between_chunks_too(db: psycopg.Connection[Any], seed: Seed) -> None:
    ids = several(World(db, seed), 5)
    report = build(db, *ids, limit=2, chunk=2)
    assert (report.seen, report.built, report.stopped, report.left) == (2, 2, "limit", 3)


def test_a_spent_budget_of_time_stops_the_pass_before_it_starts(db: psycopg.Connection[Any], seed: Seed) -> None:
    ids = several(World(db, seed), 3)
    report = build(db, *ids, max_seconds=-1)                  # a budget already spent
    assert (report.seen, report.built, report.stopped, report.left) == (0, 0, "time", 3)


def test_time_that_runs_out_in_the_middle_stops_the_pass_between_two_matches(db: psycopg.Connection[Any], seed: Seed,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    ids = several(World(db, seed), 3)
    real = layers.build

    def slow(inp: layers.Inputs) -> layers.Knowledge:
        time.sleep(0.3)
        return real(inp)

    monkeypatch.setattr(layers, "build", slow)
    report = build(db, *ids, max_seconds=0.2)
    assert (report.built, report.stopped, report.left) == (1, "time", 2)


def test_a_pass_looks_at_the_matches_a_chunk_at_a_time_and_reports_after_each(db: psycopg.Connection[Any], seed: Seed) -> None:
    ids = several(World(db, seed), 5)
    seen: list[tuple[int, int]] = []
    report = build(db, *ids, chunk=2, progress=lambda r: seen.append((r.seen, r.built)))
    assert seen == [(2, 2), (4, 4), (5, 5)] and report.built == 5


def test_a_pass_commits_once_a_chunk(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = several(World(db, seed), 5)
    commits: list[int] = []
    monkeypatch.setattr(db, "commit", lambda: commits.append(1))          # the transaction of the test is not to be committed
    report = builder.build_many(db, ids, chunk=2)
    assert report.built == 5 and len(commits) == 3
    commits.clear()
    assert builder.build_many(db, ids, apply=False).built == 0 and len(commits) == 1


def test_the_report_tells_what_the_rows_weigh_and_what_state_the_layers_are_in(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid = w.golden()
    thin = w.match(KICKOFF + timedelta(hours=1))
    report = build(db, fid, thin)
    summary = report.as_dict()
    assert summary["built"] == 2 and summary["bytes_max"] == report.biggest > summary["bytes_mean"] > 0
    assert summary["by_completeness"] == {"complete": 1, "minimal": 1}
    assert summary["by_layer"][f"{layers.C3_EVENTS}:ok"] == 1 and summary["by_layer"][f"{layers.C3_EVENTS}:missing"] == 1
    assert sum(summary["layer_bytes"].values()) < summary["bytes"] and summary["stopped"] is None


# ── which matches ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_candidates_are_the_finished_matches_settled_in_the_window_newest_first(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    now = KICKOFF + timedelta(days=30)
    old = w.match(now - timedelta(days=12))
    inside = w.match(now - timedelta(days=9))
    w.match(now - timedelta(hours=24))                                                   # over 24 hours ago: not yet settled
    settled = w.match(now - timedelta(hours=27))
    just = w.match(now - builder.SETTLE)                                                 # exactly 26 hours ago: settled
    w.match(now - timedelta(days=2), group="live", status="2H", goals=None)
    w.match(now - timedelta(days=2), group="postponed", status="PST", goals=None)
    w.match(now - timedelta(days=2), group="cancelled", status="CANC", goals=None)
    assert builder.candidates(db, now=now) == [just, settled, inside]
    assert builder.candidates(db, now=now, days=13) == [just, settled, inside, old]
    assert builder.candidates(db, now=now, days=13, until=now - timedelta(days=10)) == [old]


def test_the_workers_pass_builds_the_candidates_and_a_dry_pass_builds_none(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid = w.golden()
    w.match(KICKOFF + timedelta(days=1, hours=23), goals=(0, 0))                          # kicked off a few hours before NOW: not settled
    dry = builder.refresh_pending(db, now=NOW, commit=False, apply=False)
    assert (dry.seen, dry.built) == (1, 1) and rows(db, fid) == []
    report = builder.refresh_pending(db, now=NOW, commit=False)
    assert (report.seen, report.built, report.failed) == (1, 1, 0) and len(rows(db, fid)) == 1
    assert builder.refresh_pending(db, now=NOW, commit=False).built == 0


# ── coverage ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_coverage_counts_the_matches_with_a_build_and_the_matches_whose_events_are_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    a, b = w.golden(), w.golden(KICKOFF + timedelta(days=1))
    c = w.match(KICKOFF + timedelta(days=2), goals=None)                                  # finished, without result and without events
    w.match(KICKOFF + timedelta(days=3), group="live", status="2H", goals=None)           # not finished: not counted
    before = builder.coverage(db, now=LATER, days=30)
    assert (before["finished"], before["built"], before["share"]) == (3, 0, 0.0)
    assert before["events"] == {"with_events": 2, "read": 0, "unread": 2, "stale": 0}
    build(db, a, b)
    after = builder.coverage(db, now=LATER, days=30)
    assert (after["built"], after["complete"], after["partial"], after["minimal"], after["share"]) == (2, 2, 0, 0, 66.67)
    assert after["events"] == {"with_events": 2, "read": 2, "unread": 0, "stale": 0}
    w.events(a, [ev(8, 90, "home", "Card", "Yellow Card", extra=3, player=505, name="Man 505")])
    assert builder.coverage(db, now=LATER, days=30)["events"] == {"with_events": 2, "read": 1, "unread": 0, "stale": 1}, "a line the table does not have"
    build(db, a, b, c)
    done = builder.coverage(db, now=LATER, days=30)
    assert (done["built"], done["minimal"], done["share"]) == (3, 1, 100.0)
    assert done["events"] == {"with_events": 2, "read": 2, "unread": 0, "stale": 0}


def test_lines_read_by_older_rules_are_stale(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    build(db, fid)
    db.execute("UPDATE core.fixture_event_kinds SET rules_version = 'events-v0' WHERE fixture_id = %s AND seq = 3", (fid,))
    assert builder.coverage(db, now=LATER, days=30)["events"] == {"with_events": 1, "read": 0, "unread": 0, "stale": 1}
