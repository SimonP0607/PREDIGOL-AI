"""The observable tactics of each side in the AI packet (plan F6: ``packet-v8``, ``dossier.tactics``; ``leak-audit-v6``, rule
``tactics_known``), on the world of ``tests/integration/tactics_world.py``: what the profile counts, what it leaves out and says so, the
moment it reads as of, and the nightly proof. The honest packets are built by the real builder; the dishonest ones are the same packets
edited by hand, which is what a faulty reader would have stored. The transaction is rolled back afterwards."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.ai.packet import PACKET_VERSION, Packet, PacketBuilder, store_packet
from fbi.intel import dossier, leakage, tactics

from .conftest import Seed
from .tactics_world import AT, KICKOFF, World

RULE = "tactics_known"


def audited(db: psycopg.Connection[Any], at: datetime, run: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = leakage.audit_day(db, day=local_day(at), at=at + timedelta(hours=1, minutes=run))[RULE]
    return out


def packet(db: psycopg.Connection[Any], w: World, at: datetime = AT) -> Packet:
    got = PacketBuilder(db).build(w.f["U"], at=at)
    assert got is not None
    return got


def handmade(db: psycopg.Connection[Any], fid: int, content: dict[str, Any], at: datetime) -> int:
    row = db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id", (fid, PACKET_VERSION, at, at, hashlib.sha256(repr((fid, at, content)).encode()).hexdigest(),
                         Jsonb(content))).fetchone()
    assert row is not None
    return int(row[0])


def tampered(p: Packet, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    content = copy.deepcopy(p.content)
    change(content)
    return content


@pytest.fixture
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    w = World(db, seed)
    w.build()
    return w


def ids(w: World, *keys: str) -> list[int]:
    return [w.f[k] for k in keys]


# ── what the block says ────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_home_side_carries_what_its_last_matches_show(world: World, db: psycopg.Connection[Any]) -> None:
    got = packet(db, world)
    block = got.content["dossier"]["tactics"]
    assert (block["version"], block["status"]) == (tactics.VERSION, "DESCRIPTIVE") and "descripciones" in block["note"]
    home = block["home"]
    assert home["team_id"] == world.team[0] and home["n"] == 7
    assert home["fixtures"] == ids(world, "A", "H", "B", "C", "D", "E", "F"), "the match whose result came after the moment (G) is not one"
    assert home["read"] == {"events": ids(world, "A", "B", "C", "D"), "sheets": ids(world, "A", "B", "C", "D", "E")}
    assert home["data"] == {"sheets": {"none": 2, "crossed": 1, "without_formation": 0, "without_the_eleven": 1},
                            "events": {"none": 2, "inconsistent": 1}}, "H and E have no list, F has one that does not give the score"
    assert home["formations"] == {"n": 4, "main": "4-3-3", "main_count": 3, "last": "4-3-3", "distinct": 2, "changes": 1,
                                  "counts": {"4-3-3": 3, "4-2-3-1": 1}}, "the crossed sheet's 5-3-2 is not T0's"
    assert home["starters"] == {"n": 3, "pairs": 1, "changes": [2], "avg_changes": 2.0, "ever_present": 9}
    assert home["coach"] == {"n": 5, "distinct": 1, "newest_matches": 5}, "the coach beside a crossed sheet is the right one"
    goals = home["goals"]
    assert (goals["n"], goals["for"], goals["against"], goals["total_for"], goals["total_against"]) == (
        4, [0, 3, 0, 0, 0, 2], [1, 0, 1, 0, 0, 1], 5, 3)
    assert goals["late"] == {"for": 2, "against": 1, "matches_for": 2, "matches_against": 1}
    score = home["with_the_score"]
    assert score["n"] == 4 and score["goalless"] == 0
    assert score["scored_first"] == {"n": 2, "wins": 1, "draws": 1, "losses": 0}
    assert score["conceded_first"] == {"n": 2, "wins": 1, "draws": 0, "losses": 1}
    assert (score["led_and_did_not_win"], score["trailed_and_did_not_lose"]) == (1, 1)
    assert score["half_time"] == {"n": 6, "leading": {"n": 3, "wins": 2, "draws": 1, "losses": 0},
                                  "level": {"n": 2, "wins": 1, "draws": 1, "losses": 0},
                                  "trailing": {"n": 1, "wins": 0, "draws": 0, "losses": 1}}
    subs = home["substitutions"]
    assert (subs["n"], subs["with_substitutions"], subs["per_match"]) == (4, 4, 1.5)
    assert subs["first_minute"] == {"mean": 57.8, "median": 60.0}
    assert subs["first_by_state"] == {"leading": {"n": 2, "mean_minute": 55.5}, "level": {"n": 1, "mean_minute": 60.0},
                                      "trailing": {"n": 1, "mean_minute": 60.0}}
    assert any(s.get("block") == "dossier" for s in got.sources)


def test_the_away_side_has_its_own_sample(world: World, db: psycopg.Connection[Any]) -> None:
    away = packet(db, world).content["dossier"]["tactics"]["away"]
    assert away["team_id"] == world.team[1] and away["fixtures"] == ids(world, "I", "J", "E")
    assert away["read"] == {"events": ids(world, "I", "J"), "sheets": ids(world, "I")}
    assert away["data"]["sheets"] == {"none": 2, "crossed": 0, "without_formation": 0, "without_the_eleven": 0}
    assert away["data"]["events"] == {"none": 1, "inconsistent": 0}
    assert away["formations"] == {"n": 1, "main": "5-4-1", "main_count": 1, "last": "5-4-1", "distinct": 1, "changes": 0,
                                  "counts": {"5-4-1": 1}}
    assert away["starters"] == {"n": 1, "pairs": 0, "changes": [], "avg_changes": None}
    assert away["goals"]["for"] == [0, 0, 0, 1, 0, 1] and away["goals"]["against"] == [1, 0, 0, 0, 0, 0]
    score = away["with_the_score"]
    assert score["goalless"] == 1 and score["scored_first"]["n"] == 0 and score["conceded_first"] == {
        "n": 1, "wins": 1, "draws": 0, "losses": 0}
    assert score["half_time"]["trailing"] == {"n": 2, "wins": 1, "draws": 0, "losses": 1}
    assert away["substitutions"]["per_match"] == 0.5 and away["substitutions"]["first_by_state"]["level"] == {"n": 1, "mean_minute": 70.0}


def test_a_side_and_its_team_block_cite_the_same_matches(world: World, db: psycopg.Connection[Any]) -> None:
    """The profile and ``dossier.teams`` are built apart; this holds their samples together."""
    block = packet(db, world).content["dossier"]["tactics"]
    for side, team in (("home", world.team[0]), ("away", world.team[1])):
        profile = dossier.team_profile(db, team, kickoff=KICKOFF, at=AT, elo=None)
        assert block[side]["fixtures"] == profile["_fixtures"], side


def test_a_side_without_matches_says_so(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.upcoming(2, 3)
    block = packet(db, w).content["dossier"]["tactics"]
    assert block["home"] == {"team_id": w.team[2], "n": 0, "fixtures": []} and block["away"]["n"] == 0


# ── the moment ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_result_or_a_list_that_arrived_after_the_moment_is_not_there_and_is_there_once_it_has(
        world: World, db: psycopg.Connection[Any]) -> None:
    before = packet(db, world).content["dossier"]["tactics"]["home"]
    after = packet(db, world, AT + timedelta(hours=3)).content["dossier"]["tactics"]["home"]
    assert world.f["G"] not in before["fixtures"] and world.f["H"] not in before["read"]["events"]
    assert after["fixtures"][:2] == ids(world, "G", "A") and after["n"] == 8, "G's result was recorded an hour after the moment"
    assert world.f["H"] in after["read"]["events"], "and H's list two hours after it"
    assert after["goals"]["total_for"] == before["goals"]["total_for"] + 1, "H: T0's 70th-minute goal"


def test_statistics_that_show_a_sheet_crossed_count_from_the_moment_they_were_fetched(
        world: World, db: psycopg.Connection[Any]) -> None:
    db.execute("UPDATE core.fixture_player_stats SET fetched_at = %s WHERE fixture_id = %s", (AT + timedelta(hours=1), world.f["D"]))
    early = packet(db, world).content["dossier"]["tactics"]["home"]
    late = packet(db, world, AT + timedelta(hours=2)).content["dossier"]["tactics"]["home"]
    assert early["data"]["sheets"]["crossed"] == 0 and early["formations"]["counts"] == {"4-3-3": 3, "4-2-3-1": 1, "5-3-2": 1}, \
        "at the moment nobody knew the provider had crossed the sheet: it was read as it came"
    assert late["data"]["sheets"]["crossed"] == 1 and "5-3-2" not in late["formations"]["counts"]


# ── what is left out ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_crossed_sheet_gives_no_formation_to_the_coach_block_either_but_keeps_its_coach(
        world: World, db: psycopg.Connection[Any]) -> None:
    home = packet(db, world).content["dossier"]["teams"]["home"]
    assert home["coach"]["formations"] == {"4-3-3": 3, "4-2-3-1": 1} and home["coach"]["main_formation"] == "4-3-3"
    assert home["coach"]["name"] == "Coach One" and home["coach"]["matches_seen"] == 5


def test_events_that_do_not_give_the_score_are_not_read(world: World, db: psycopg.Connection[Any]) -> None:
    home = packet(db, world).content["dossier"]["tactics"]["home"]
    assert world.f["F"] in home["fixtures"] and world.f["F"] not in home["read"]["events"]
    assert home["data"]["events"]["inconsistent"] == 1 and home["goals"]["total_for"] == 5, "F's 2-0 is not in the goals"


def test_a_goal_filed_under_the_side_that_gets_it_is_the_teams_own_goal_count(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.match("A", 3, 0, 2, (1, 0), ht=(1, 0))
    w.events("A", [(40, "home", "Goal", "Own Goal")])
    w.upcoming(0, 1)
    home = packet(db, w).content["dossier"]["tactics"]["home"]
    assert home["goals"]["for"] == [0, 0, 1, 0, 0, 0] and home["goals"]["total_against"] == 0 and home["data"]["events"]["inconsistent"] == 0


# ── the nightly proof ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v8" and RULE in (leakage.__doc__ or "")


def test_an_honest_packet_passes_one_check_per_cited_match_and_two_per_side(world: World, db: psycopg.Connection[Any]) -> None:
    at = KICKOFF - timedelta(hours=6)
    store_packet(db, packet(db, world), built_at=at)
    assert audited(db, at) == {"checked": 14, "violations": 0, "examples": []}, "7 + 3 matches, and the sample and the omissions of two sides"
    rows = db.execute("SELECT version, n_violations FROM intel.audit_checks WHERE rule = %s", (RULE,)).fetchall()
    assert rows and all(v == "leak-audit-v8" and bad == 0 for v, bad in rows)


def test_a_packet_without_the_block_is_not_read(world: World, db: psycopg.Connection[Any]) -> None:
    content = tampered(packet(db, world), lambda c: c["dossier"].pop("tactics"))
    handmade(db, world.f["U"], content, AT)
    assert audited(db, AT) == {"checked": 0, "violations": 0, "examples": []}


def _cases(w: World) -> list[tuple[str, Callable[[dict[str, Any]], None], int | None]]:
    """What a faulty reader would have stored, and how many checks catch it: one where the other figures were kept consistent (so
    that only this check can be the one), None where one lie necessarily breaks several."""

    def future_match(c: dict[str, Any]) -> None:
        c["dossier"]["tactics"]["home"]["fixtures"][0] = w.f["U"]

    def another_teams_match(c: dict[str, Any]) -> None:
        c["dossier"]["tactics"]["home"]["fixtures"][-1] = w.f["I"]

    def result_after_the_moment(c: dict[str, Any]) -> None:
        c["dossier"]["tactics"]["home"]["fixtures"][0] = w.f["G"]

    def events_after_the_moment(c: dict[str, Any]) -> None:  # H: 1-1, so the goals are kept in step
        home = c["dossier"]["tactics"]["home"]
        home["read"]["events"].append(w.f["H"])
        home["goals"]["total_for"] += 1
        home["goals"]["total_against"] += 1

    def sheet_that_does_not_exist(c: dict[str, Any]) -> None:
        c["dossier"]["tactics"]["home"]["read"]["sheets"].append(w.f["F"])

    def a_sample_bigger_than_the_last_ten(c: dict[str, Any]) -> None:
        home = c["dossier"]["tactics"]["home"]
        home["fixtures"] += [w.f["A"]] * 4
        home["n"] = len(home["fixtures"])

    def a_recent_match_left_out(c: dict[str, Any]) -> None:  # A: 2-1 and a half-time score; everything else is kept in step
        home = c["dossier"]["tactics"]["home"]
        for key in (home["fixtures"], home["read"]["events"], home["read"]["sheets"]):
            key.remove(w.f["A"])
        home["n"] -= 1
        home["goals"]["total_for"] -= 2
        home["goals"]["total_against"] -= 1
        home["with_the_score"]["half_time"]["n"] -= 1

    def more_goals_than_the_matches_had(c: dict[str, Any]) -> None:
        c["dossier"]["tactics"]["home"]["goals"]["total_for"] += 1

    def fewer_goals_against(c: dict[str, Any]) -> None:
        c["dossier"]["tactics"]["away"]["goals"]["total_against"] -= 1

    def another_half_time_sample(c: dict[str, Any]) -> None:
        c["dossier"]["tactics"]["home"]["with_the_score"]["half_time"]["n"] += 1

    return [
        ("a match that kicked off after the one described", future_match, None),
        ("a match of another team", another_teams_match, None),
        ("a match whose result was recorded after the moment", result_after_the_moment, None),
        ("events read that were fetched after the moment", events_after_the_moment, 1),
        ("a sheet read that no sheet fetched", sheet_that_does_not_exist, 1),
        ("more than the last ten matches", a_sample_bigger_than_the_last_ten, 1),
        ("a recent match known by the moment left out", a_recent_match_left_out, 1),
        ("goals scored that the matches read did not have", more_goals_than_the_matches_had, 1),
        ("goals conceded that the matches read did not have", fewer_goals_against, 1),
        ("a half-time sample that is not the matches with a half-time score", another_half_time_sample, 1),
    ]


@pytest.mark.parametrize("index", range(10))
def test_the_rule_catches_a_profile_the_packet_could_not_have_read(world: World, db: psycopg.Connection[Any], index: int) -> None:
    name, change, exact = _cases(world)[index]
    pid = handmade(db, world.f["U"], tampered(packet(db, world), change), AT)
    result = audited(db, AT)
    assert pid in result["examples"], name
    assert result["violations"] >= 1 if exact is None else result["violations"] == exact, name


# ── a re-read is not a read from the future ─────────────────────────────────────────────────────────────────────────────


def _rewritten_after_the_moment(db: psycopg.Connection[Any], fid: int, *, payload: str, asked: str | None) -> None:
    """What the post-match job does 26 hours after the kick-off: the match is read again, its line-ups are rewritten with the instant of
    the new answer and its events are replaced by the provider's corrected list - all of it after the moment of the packet; ``asked`` is
    the payload the job's ask names (None: no ask is recorded, as if some other job had written the rows)."""
    later = AT + timedelta(hours=1)
    db.execute("UPDATE core.fixture_lineups SET fetched_at = %s, payload_hash = %s WHERE fixture_id = %s", (later, payload, fid))
    db.execute("UPDATE core.fixture_events SET fetched_at = %s, payload_hash = %s WHERE fixture_id = %s", (later, payload, fid))
    if asked is not None:
        db.execute("INSERT INTO core.detail_asks (fixture_id, stage, asked_at, payload_hash) VALUES (%s, 'late', %s, %s)",
                   (fid, later, asked))


def _second_payload(db: psycopg.Connection[Any], seed: Seed) -> str:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
               "VALUES ('h2', %s, '/fixtures', %s, 200, 'y', 1)", (seed.run_id, AT + timedelta(hours=1)))
    return "h2"


def test_a_match_read_again_by_the_post_match_job_after_the_moment_is_not_a_read_from_the_future(
        world: World, db: psycopg.Connection[Any], seed: Seed) -> None:
    at = KICKOFF - timedelta(hours=6)
    store_packet(db, packet(db, world), built_at=at)
    late = _second_payload(db, seed)
    _rewritten_after_the_moment(db, world.f["A"], payload=late, asked=late)
    assert audited(db, at) == {"checked": 14, "violations": 0, "examples": []}, \
        "the packet read A's events and sheets as they were at its moment; the job's re-read only moved their fetched_at"


def test_the_same_rows_written_after_the_moment_by_another_job_are_still_a_read_from_the_future(
        world: World, db: psycopg.Connection[Any], seed: Seed) -> None:
    at = KICKOFF - timedelta(hours=6)
    pid = store_packet(db, packet(db, world), built_at=at)
    _rewritten_after_the_moment(db, world.f["A"], payload=_second_payload(db, seed), asked=None)
    assert audited(db, at) == {"checked": 14, "violations": 1, "examples": [pid]}, "no ask of the post-match job names these rows"


def test_an_ask_that_names_another_payload_does_not_excuse_the_rows(
        world: World, db: psycopg.Connection[Any], seed: Seed) -> None:
    at = KICKOFF - timedelta(hours=6)
    pid = store_packet(db, packet(db, world), built_at=at)
    _rewritten_after_the_moment(db, world.f["A"], payload=_second_payload(db, seed), asked="h1")
    assert audited(db, at) == {"checked": 14, "violations": 1, "examples": [pid]}, "the rows came from h2, the job asked for h1"
