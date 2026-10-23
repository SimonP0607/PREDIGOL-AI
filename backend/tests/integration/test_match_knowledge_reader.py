"""Match Knowledge, read from a real database (``fbi.knowledge.reader``, plan F7): what the layers are made of, and the fingerprint of it.

The fingerprint is how the builder knows a match needs building again WITHOUT reading it. These tests hold it to the two promises it makes:
it moves, and only in its own source, when a fact a layer reads changes; and it does not move when only the moment a fact was fetched
does (the provider reading a match again and finding the same lines must not add a row that says what the last one said). The transaction
is rolled back after every test."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.intel import tactics
from fbi.knowledge import layers, reader

from .conftest import Seed
from .knowledge_world import FETCHED, KICKOFF, NOW, World

pytestmark = pytest.mark.integration

Change = Callable[[World, int], object]


def fingerprint(db: psycopg.Connection[Any], fid: int) -> dict[str, Any]:
    return reader.fingerprints(db, [fid])[fid]


def moved(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {k for k in before if before[k] != after[k]}


def first_decision(db: psycopg.Connection[Any], fid: int) -> int:
    return scalar_id(db.execute("SELECT min(id) FROM intel.decisions WHERE fixture_id = %s", (fid,)))


# ── the fingerprint ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_fingerprint_of_a_match_is_the_same_every_time_and_has_a_place_for_every_source(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    first = fingerprint(db, fid)
    assert first == fingerprint(db, fid)
    assert set(first) == {"rules", *reader.SOURCES}
    assert first["rules"] == layers.RULES
    present = {src for src in reader.SOURCES if first[src] is not None}
    assert present == set(reader.SOURCES) - {"revisions", "tie", "crossed"}, "a source with nothing for the match says None"
    assert reader.signatures(db, [fid]) == {fid: layers.signature_hash(first)}


def test_a_match_that_does_not_exist_has_an_empty_fingerprint_and_an_empty_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    World(db, seed)
    nothing = fingerprint(db, 987_654_321)
    assert all(nothing[src] is None for src in reader.SOURCES)
    assert reader.read(db, [987_654_321]) == {}
    assert reader.fingerprints(db, []) == {} and reader.read(db, []) == {}


def test_the_fingerprint_is_of_the_content_and_not_of_when_it_was_fetched(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = World(db, seed).golden()
    before = fingerprint(db, fid)
    later = FETCHED + timedelta(days=3)
    for statement in (
            "UPDATE core.fixture_events SET fetched_at = %s WHERE fixture_id = %s",
            "UPDATE core.fixture_team_stats SET fetched_at = %s WHERE fixture_id = %s",
            "UPDATE core.fixture_player_stats SET fetched_at = %s WHERE fixture_id = %s",
            "UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s",
            "UPDATE core.fixture_results SET source_fetched_at = %s, settled_at = %s WHERE fixture_id = %s"):
        params = (later, later, fid) if "settled_at" in statement else (later, fid)
        db.execute(statement, params)
    db.execute("UPDATE core.fixtures SET updated_at = %s, source_fetched_at = %s, source_payload_hash = %s WHERE id = %s",
               (later, later, seed.payload_hash, fid))
    assert fingerprint(db, fid) == before, "the provider read the match again and found what it had found: nothing to build"


CHANGES: list[tuple[str, Change, set[str]]] = [
    ("the status of the match (and the correction it leaves behind)",
     lambda w, f: w.db.execute("UPDATE core.fixtures SET status_short = 'AET' WHERE id = %s", (f,)), {"fixture", "revisions"}),
    ("a neutral ground", lambda w, f: w.db.execute("UPDATE core.fixtures SET is_neutral = true WHERE id = %s", (f,)), {"fixture"}),
    ("the kick-off, later (the same prices are the last before it)",
     lambda w, f: w.db.execute("UPDATE core.fixtures SET kickoff_at = kickoff_at + interval '1 hour' WHERE id = %s", (f,)), {"fixture"}),
    ("the kick-off, earlier than the last price (which is no longer before it)",
     lambda w, f: w.db.execute("UPDATE core.fixtures SET kickoff_at = kickoff_at - interval '30 minutes' WHERE id = %s", (f,)),
     {"fixture", "market"}),
    ("the score (and the correction it leaves behind)",
     lambda w, f: w.db.execute("UPDATE core.fixture_results SET goals_home = 3 WHERE fixture_id = %s", (f,)), {"result", "revisions"}),
    ("the break", lambda w, f: w.db.execute("UPDATE core.fixture_results SET ht_goals_home = 0 WHERE fixture_id = %s", (f,)),
     {"result", "revisions"}),
    ("a correction of the result", lambda w, f: w.revision(f, FETCHED), {"revisions"}),
    ("a statistic of a team",
     lambda w, f: w.db.execute("UPDATE core.fixture_team_stats SET shots = 15 WHERE fixture_id = %s AND team_side = 'home'", (f,)), {"team_stats"}),
    ("the second provider of a team's statistics",
     lambda w, f: w.team_stats(f, "home", source="football-data.co.uk", shots=1), {"team_stats"}),
    ("the minute of a line of the events",
     lambda w, f: w.db.execute("UPDATE core.fixture_events SET minute = 13 WHERE fixture_id = %s AND seq = 0", (f,)), {"events"}),
    ("the man a line names",
     lambda w, f: w.db.execute("UPDATE core.fixture_events SET provider_player_id = 599 WHERE fixture_id = %s AND seq = 0", (f,)), {"events"}),
    ("a line of the events that is gone",
     lambda w, f: w.db.execute("DELETE FROM core.fixture_events WHERE fixture_id = %s AND seq = 7", (f,)), {"events"}),
    ("a line of the events that is new",
     lambda w, f: w.events(f, [{"seq": 8, "minute": 90, "extra_minute": 3, "team_side": "home", "provider_player_id": None, "player_name": None,
                                "provider_assist_id": None, "assist_name": None, "event_type": "Card", "detail": "Yellow Card", "comments": None}]),
     {"events"}),
    ("the rating of a man",
     lambda w, f: w.db.execute("UPDATE core.fixture_player_stats SET rating = 8.25 WHERE fixture_id = %s AND provider_player_id = 501", (f,)),
     {"players"}),
    ("a man who was not listed",
     lambda w, f: w.men(f, "away", [(699, {"minutes": 12, "rating": 6.0, "is_captain": False, "is_substitute": True})]), {"players"}),
    ("the formation of a side",
     lambda w, f: w.db.execute("UPDATE core.fixture_lineups SET formation = '4-2-3-1' WHERE fixture_id = %s AND team_side = 'home'", (f,)),
     {"lineups"}),
    ("the coach of a side",
     lambda w, f: w.db.execute("UPDATE core.fixture_lineups SET coach_name = 'Someone Else' WHERE fixture_id = %s AND team_side = 'away'", (f,)),
     {"lineups"}),
    ("the side the statistics put the men on",
     lambda w, f: w.db.execute("UPDATE core.fixture_player_stats SET team_side = 'away' WHERE fixture_id = %s AND provider_player_id IN "
                               "(501, 502, 503, 505)", (f,)), {"players", "crossed"}),
    ("a price in the last minutes before the kick-off",
     lambda w, f: w.quote(f, "1X2", "Home", 0, 0.52, KICKOFF - timedelta(minutes=5)), {"market"}),
    ("the first price the market ever had",
     lambda w, f: w.quote(f, "1X2", "Home", 0, 0.40, KICKOFF - timedelta(days=6, hours=2)), set()),
    ("a decision", lambda w, f: w.decision(f, "OU", "Under", 2.5, "APROBADO", checkpoint="T-1h"), {"decisions"}),
    ("how a decision ended", lambda w, f: w.outcome(w.decision(f, "BTTS", "Yes", 0, "CAUTELA", checkpoint="T-5h"), "loss", -1), {"decisions", "outcomes"}),
    ("how a pick ended",
     lambda w, f: w.db.execute("UPDATE picks.pick_results SET result_status = 'loss', profit_units = -1", ()), {"picks"}),
    ("a pick that is new", lambda w, f: w.pick(f, "BTTS", "Yes", 0, result=None), {"picks"}),
    ("a post-mortem", lambda w, f: w.postmortem(first_decision(w.db, f), f, version="pm-v6"), {"postmortems"}),
]
"""(what changed, how, the sources whose fingerprint must move - and no other)"""


@pytest.mark.parametrize(("label", "change", "expected"), CHANGES, ids=[c[0] for c in CHANGES])
def test_the_fingerprint_moves_in_its_source_when_a_fact_a_layer_reads_changes(db: psycopg.Connection[Any], seed: Seed, label: str,
                                                                              change: Change, expected: set[str]) -> None:
    w = World(db, seed)
    fid = w.golden()
    before = fingerprint(db, fid)
    change(w, fid)
    assert moved(before, fingerprint(db, fid)) == expected, label


@pytest.mark.parametrize(("label", "change"), [
    ("a price after the kick-off", lambda w, f: w.quote(f, "1X2", "Home", 0, 0.95, KICKOFF + timedelta(minutes=30))),
    ("a price de-vigged another way", lambda w, f: w.quote(f, "1X2", "Home", 0, 0.52, KICKOFF - timedelta(minutes=5), method="proportional")),
    ("the events of another match", lambda w, f: w.events(w.match(KICKOFF + timedelta(days=1)), [{
        "seq": 0, "minute": 1, "extra_minute": None, "team_side": "home", "provider_player_id": None, "player_name": None,
        "provider_assist_id": None, "assist_name": None, "event_type": "Goal", "detail": "Normal Goal", "comments": None}])),
    ("the decisions of another match", lambda w, f: w.decision(w.match(KICKOFF + timedelta(days=1)), "1X2", "Home", 0, "APROBADO")),
])
def test_the_fingerprint_does_not_move_for_what_is_not_the_match_or_not_before_its_kick_off(db: psycopg.Connection[Any], seed: Seed, label: str,
                                                                                         change: Change) -> None:
    w = World(db, seed)
    fid = w.golden()
    before = fingerprint(db, fid)
    change(w, fid)
    assert fingerprint(db, fid) == before, label


def test_the_fingerprint_carries_the_versions_of_the_rules(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    fid = World(db, seed).golden()
    before = reader.signatures(db, [fid])
    monkeypatch.setattr(layers, "RULES", {**layers.RULES, "events": "events-v2"})
    after = reader.signatures(db, [fid])
    assert after != before, "a new rule rebuilds what it touches"


def test_the_fingerprint_of_one_match_does_not_depend_on_the_others_in_the_batch(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    a, b = w.golden(), w.golden(KICKOFF + timedelta(days=1))
    together = reader.signatures(db, [a, b])
    assert together[a] == reader.signatures(db, [a])[a] and together[b] == reader.signatures(db, [b])[b]
    assert together[a] != together[b], "two matches with the same lines are two matches"


# ── the rows ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_source_is_read_into_its_place(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid = w.golden()
    w.revision(fid, FETCHED)
    got = reader.read(db, [fid])[fid]
    inp = got.inputs
    assert (inp.fixture.id, inp.fixture.status, inp.fixture.neutral, inp.fixture.kickoff_at) == (fid, "FT", False, KICKOFF)
    assert inp.result is not None and (inp.result.goals_home, inp.result.goals_away, inp.result.reg_home, inp.result.reg_away) == (2, 1, 2, 1)
    assert (inp.result.ht_home, inp.result.ht_away, inp.result.pen_home) == (1, 0, None)
    assert [(v.kind, v.changed) for v in inp.revisions] == [("score", ("goals_home",))]
    assert inp.tie is None and not inp.sheets_crossed
    assert {t.side for t in inp.team_stats} == {"home", "away"}
    home = next(t for t in inp.team_stats if t.side == "home")
    assert home.values["shots"] == 14 and home.values["possession_pct"] == 54.5 and home.values["expected_goals"] == 1.874
    assert isinstance(home.values["possession_pct"], float) and isinstance(home.values["shots"], int)
    assert [r.seq for r in inp.events] == list(range(8)) and inp.events_fetched_at == FETCHED
    assert (inp.events[4].event_type, inp.events[4].detail, inp.events[4].side, inp.events[4].player_id) == ("Goal", "Penalty", "away", 602)
    assert sorted(got.event_stamps) == list(range(8)) and set(got.event_stamps.values()) == {FETCHED}
    assert len(inp.players) == 12 and {p.side for p in inp.players} == {"home", "away"}
    captain = next(p for p in inp.players if p.player_id == 501)
    assert (captain.captain, captain.substitute, captain.minutes, captain.rating, captain.goals) == (True, False, 90, 8.1, 1)
    assert {(s.side, s.formation, s.coach_name) for s in inp.lineups} == {("home", "4-3-3", "Coach Home"), ("away", "4-4-2", "Coach Away")}
    close = {(q.market, q.selection, q.line): q for q in inp.close_quotes}
    assert len(close) == 7 and close[("1X2", "Home", 0)].p_fair == 0.5 and close[("1X2", "Home", 0)].books == 10
    assert close[("1X2", "Home", 0)].as_of == KICKOFF - timedelta(minutes=20)
    opened = {(q.market, q.selection, q.line): q for q in inp.open_quotes}
    assert opened[("1X2", "Home", 0)].p_fair == 0.45 and opened[("1X2", "Home", 0)].as_of == KICKOFF - timedelta(days=6)
    assert {(d.market, d.selection, d.state, d.result, d.profit) for d in inp.decisions} == {
        ("1X2", "Home", "PICK_PREMIUM", "win", 1.1), ("OU", "Over", "RECHAZADO", "win", 0.9)}
    assert next(d for d in inp.decisions if d.market == "1X2").stake == 1.0
    assert [(t.market, t.result, t.n, t.profit) for t in inp.picks] == [("1X2", "win", 1, 1.1)]
    assert [(p.version, p.verdict, p.quality, p.outcome, p.causes) for p in inp.postmortems] == [("pm-v5", "MERECIDO", "GOOD", "won", ("red_card",))]


def test_the_opening_is_the_first_price_of_the_week_before_the_kick_off_and_the_close_the_last_before_it(db: psycopg.Connection[Any],
                                                                                                         seed: Seed) -> None:
    w = World(db, seed)
    fid = w.match()
    for as_of, p in ((KICKOFF - timedelta(days=9), 0.30), (KICKOFF - timedelta(days=5), 0.40), (KICKOFF - timedelta(days=1), 0.45),
                     (KICKOFF - timedelta(minutes=30), 0.50), (KICKOFF - timedelta(minutes=10), 0.52), (KICKOFF + timedelta(minutes=10), 0.99)):
        w.quote(fid, "1X2", "Home", 0, p, as_of)
    w.quote(fid, "DC", "Home/Draw", 0, 0.7, KICKOFF - timedelta(minutes=10))     # a market the layers do not read
    inp = reader.read(db, [fid])[fid].inputs
    assert [(q.p_fair, q.as_of) for q in inp.close_quotes] == [(0.52, KICKOFF - timedelta(minutes=10))]
    assert [(q.p_fair, q.as_of) for q in inp.open_quotes] == [(0.40, KICKOFF - timedelta(days=5))], "9 days before is outside the week"


def test_the_statistics_of_the_teams_come_from_the_provider_that_has_both_sides(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    both, mixed, only_old = w.match(), w.match(KICKOFF + timedelta(days=1)), w.match(KICKOFF + timedelta(days=2))
    w.team_stats(both, "home", shots=10), w.team_stats(both, "away", shots=8)
    w.team_stats(both, "home", source="football-data.co.uk", shots=99), w.team_stats(both, "away", source="football-data.co.uk", shots=98)
    w.team_stats(mixed, "home", shots=10)                                                         # api-football has only one side...
    w.team_stats(mixed, "home", source="football-data.co.uk", shots=77), w.team_stats(mixed, "away", source="football-data.co.uk", shots=66)
    w.team_stats(only_old, "away", source="football-data.co.uk", shots=5)
    got = reader.read(db, [both, mixed, only_old])
    shots = {fid: {t.side: t.values["shots"] for t in got[fid].inputs.team_stats} for fid in (both, mixed, only_old)}
    assert shots[both] == {"home": 10, "away": 8}, "api-football first when it has both"
    assert shots[mixed] == {"home": 77, "away": 66}, "and the other provider when it is the one with both: never a side from each"
    assert shots[only_old] == {"away": 5}


def test_the_sheets_the_provider_crossed_are_found_as_the_tactics_module_finds_them(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    straight, crossed = w.match(), w.match(KICKOFF + timedelta(days=1))
    home, away = list(range(701, 712)), list(range(801, 812))
    for fid, swap in ((straight, False), (crossed, True)):
        w.men(fid, "home", [(p, {"minutes": 90}) for p in home])
        w.men(fid, "away", [(p, {"minutes": 90}) for p in away])
        w.sheet(fid, "home", "4-4-2", away if swap else home)            # a crossed sheet lists the other side's men
        w.sheet(fid, "away", "4-3-3", home if swap else away)
    got = reader.read(db, [straight, crossed])
    assert not got[straight].inputs.sheets_crossed and got[crossed].inputs.sheets_crossed
    assert tactics.crossed_sheets(db, [straight, crossed], at=NOW) == {crossed}, "the same answer as the module that profiles the tactics"
    assert layers.build(got[crossed].inputs).layers[layers.C5_TACTICS]["notes"].count("sheets_crossed") == 1


def test_a_leg_of_a_tie_reads_the_tie(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid = w.match(KICKOFF, home=0, away=1, goals=(1, 0), status="FT")
    stage = scalar_id(db.execute(
        "INSERT INTO core.competition_stages (competition_season_id, stage, ordinal, phase, base_stage, kind, role, rule, numbered, fixtures, "
        "first_kickoff_at, last_kickoff_at, ties, stages_version, ties_version, build_hash) VALUES (%s, 'Final', 1, 'knockout', 'Final', 'knockout', "
        "'final', 'test', false, 1, %s, %s, 1, 'stages-v1', 'ties-v1', 'x') RETURNING id", (w.season, KICKOFF, KICKOFF)))
    tie = scalar_id(db.execute(
        "INSERT INTO core.ties (stage_id, team_a_id, team_b_id, format, status, legs, played, aggregate_a, aggregate_b, winner_team_id, decided_by, "
        "winner_check, version) VALUES (%s, %s, %s, 'single', 'decided', 1, 1, 1, 0, %s, 'normal_time', 'confirmed', 'ties-v1') RETURNING id",
        (stage, w.team[0], w.team[1], w.team[0])))
    db.execute("UPDATE core.fixtures SET tie_id = %s, stage_id = %s, leg = 1 WHERE id = %s", (tie, stage, fid))
    inp = reader.read(db, [fid])[fid].inputs
    assert inp.fixture.tie_id == tie and inp.fixture.leg == 1
    assert inp.tie is not None and (inp.tie.format, inp.tie.status, inp.tie.winner_team_id, inp.tie.winner_check) == ("single", "decided", w.team[0],
                                                                                                                    "confirmed")
    block = layers.build(inp).layers[layers.C1_RESULT]["data"]["tie"]
    assert block == {"format": "single", "legs": 1, "leg": 1, "aggregate": [1, 0], "winner": "home", "decided_by": "normal_time"}
    assert moved(fingerprint(db, fid), fingerprint(db, fid)) == set()
    before = fingerprint(db, fid)
    db.execute("UPDATE core.ties SET decided_by = 'extra_time' WHERE id = %s", (tie,))
    assert moved(before, fingerprint(db, fid)) == {"tie"}


def scalar_id(cur: psycopg.Cursor[Any]) -> int:
    row = cur.fetchone()
    assert row is not None
    return int(row[0])
