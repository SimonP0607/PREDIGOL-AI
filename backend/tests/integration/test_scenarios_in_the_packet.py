"""The scenarios of a match in the AI packet (plan F6: ``packet-v8``, block ``scenarios``; ``leak-audit-v6``, rule ``scenarios_known``).

Two worlds the earlier phases built: a championship round whose table is a snapshot the provider served (the match's own stage), and a
Champions League draw whose round of 16 has a second leg. The honest packets are built by the real builder; the dishonest ones are the
same packets edited by hand, which is what a faulty reader would have stored. The transaction is rolled back afterwards."""

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
from fbi.intel import leakage, scenarios
from tests.integration.conftest import Seed
from tests.integration.test_competition_context import built, kickoff
from tests.integration.test_competition_tables_asof import championship, packet

RULE = "scenarios_known"


def audited(db: psycopg.Connection[Any], at: datetime, run: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = leakage.audit_day(db, day=local_day(at), at=at + timedelta(hours=1, minutes=run))[RULE]
    return out


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


# ── the table ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_match_of_a_stage_with_a_table_carries_what_it_does_to_that_table(db: psycopg.Connection[Any], seed: Seed) -> None:
    _s, match, ko = championship(db, 99961)
    got = packet(db, match, ko)
    block = got.content["scenarios"]
    assert (block["version"], block["status"]) == (scenarios.VERSION, "DESCRIPTIVE")
    table = block["table"]
    assert table["basis"] == "this_match_alone" and table["group"] == "Championship Round" and table["teams"] == 6
    st = got.content["standings"]
    assert (table["home"]["rank_now"], table["home"]["points_now"], table["home"]["played"]) == (
        st["home"]["rank"], st["home"]["points"], st["home"]["played"]), "the sides are the ones of the standings block"
    assert set(table["after"]) == {"home_win", "draw", "away_win"}
    win = table["after"]["home_win"]["home"]
    assert win["points"] == st["home"]["points"] + 3 and win["rank_best"] <= win["rank_worst"]
    assert block["tie"] is None
    assert any(s.get("block") == "scenarios" and s.get("version") == scenarios.VERSION for s in got.sources)


def test_a_match_with_neither_a_table_of_its_stage_nor_a_tie_has_no_scenarios(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, f = built(db, seed, 99962)
    got = PacketBuilder(db).build(f["g1"], at=kickoff(30) - timedelta(hours=3))
    assert got is not None and "scenarios" not in got.content, "a group match of a season with no stored table, and not a tie"


def test_the_table_effect_is_the_same_for_a_packet_built_later_unless_a_newer_snapshot_exists(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    s, match, ko = championship(db, 99963)
    before = packet(db, match, ko)
    s.snapshot(ko + timedelta(days=1), {"Regular Season": dict.fromkeys(s.team, 5), "Championship Round": dict.fromkeys(s.team, 9)})
    after = packet(db, match, ko)
    assert after.content["scenarios"] == before.content["scenarios"], "a snapshot taken after the moment changes nothing"


# ── the tie ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_second_leg_carries_the_margins_with_which_each_side_goes_through(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, f = built(db, seed, 99964)
    got = PacketBuilder(db).build(f["r2"], at=kickoff(107) - timedelta(hours=3))
    assert got is not None
    tie = got.content["scenarios"]["tie"]
    assert got.content["scenarios"]["table"] is None, "no table of the stage was stored for this season"
    assert tie["kind"] == "second_leg" and tie["aggregate_before"] == {"home_side": 0, "away_side": 1}
    assert tie["lead_home_side"] == -1
    assert tie["home_side"]["needs_to_win_by_at_least"] == 2 and tie["home_side"]["can_lose_by_up_to"] is None
    assert tie["away_side"]["can_lose_by_up_to"] == 0 and tie["away_side"]["needs_to_win_by_at_least"] is None
    assert tie["if_level"] == "competition_rules"
    # the same numbers the phase block already carries, from the other side of the arithmetic
    assert got.content["phase"]["tie"]["outlook"]["home_side_ahead_if_home_margin_at_least"] == tie["home_side"]["ahead_if_margin_at_least"]


def test_a_first_leg_is_passed_through(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, f = built(db, seed, 99965)
    got = PacketBuilder(db).build(f["r1"], at=kickoff(100) - timedelta(hours=3))
    assert got is not None
    assert got.content["scenarios"]["tie"] == {"version": scenarios.VERSION, "kind": "first_leg"}


# ── the nightly proof ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v6" and RULE in (leakage.__doc__ or "")


def test_honest_packets_pass_one_check_for_the_snapshot_and_one_per_side_and_one_per_tie(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    _s, match, ko = championship(db, 99966)
    at = ko - timedelta(hours=3)
    store_packet(db, packet(db, match, ko), built_at=at)
    assert audited(db, at) == {"checked": 3, "violations": 0, "examples": []}, "the snapshot and the two sides"
    _w, f = built(db, seed, 99967)
    at2 = kickoff(107) - timedelta(hours=3)
    leg = PacketBuilder(db).build(f["r2"], at=at2)
    assert leg is not None
    store_packet(db, leg, built_at=at2)
    assert audited(db, at2, run=1)["checked"] == 1, "and the reading of the second leg, on its own day"
    rows = db.execute("SELECT version, n_violations FROM intel.audit_checks WHERE rule = %s ORDER BY id", (RULE,)).fetchall()
    assert all(v == "leak-audit-v6" and bad == 0 for v, bad in rows)


def _table_cases() -> list[tuple[str, Callable[[dict[str, Any]], None]]]:
    def snapshot_after_the_moment(c: dict[str, Any]) -> None:
        c["scenarios"]["table"]["snapshot_at"] = "2099-01-01T00:00:00+00:00"

    def wrong_points(c: dict[str, Any]) -> None:
        c["scenarios"]["table"]["home"]["points_now"] += 3

    def wrong_games(c: dict[str, Any]) -> None:
        c["scenarios"]["table"]["away"]["played"] += 1

    def another_group(c: dict[str, Any]) -> None:
        c["scenarios"]["table"]["group"] = "Somewhere Else"

    return [
        ("a snapshot taken after the packet's moment", snapshot_after_the_moment),
        ("points the snapshot does not hold", wrong_points),
        ("games played the snapshot does not hold", wrong_games),
        ("a group the snapshot does not have", another_group),
    ]


@pytest.mark.parametrize("index", range(4))
def test_the_rule_catches_a_table_the_packet_could_not_have_read(db: psycopg.Connection[Any], seed: Seed, index: int) -> None:
    _s, match, ko = championship(db, 99970 + index)
    at = ko - timedelta(hours=3)
    name, change = _table_cases()[index]
    got = packet(db, match, ko)
    pid = handmade(db, match, tampered(got, change), at)
    result = audited(db, at)
    assert result["violations"] >= 1 and pid in result["examples"], name


def _tie_cases() -> list[tuple[str, Callable[[dict[str, Any]], None]]]:
    def another_aggregate(c: dict[str, Any]) -> None:
        c["scenarios"]["tie"]["aggregate_before"]["away_side"] = 0  # the first leg was not that

    def wrong_margin(c: dict[str, Any]) -> None:
        c["scenarios"]["tie"]["home_side"]["ahead_if_margin_at_least"] -= 1

    def wrong_lead(c: dict[str, Any]) -> None:
        c["scenarios"]["tie"]["lead_home_side"] += 1

    return [("an aggregate the phase block does not have", another_aggregate),
            ("a margin that is not the arithmetic of the aggregate", wrong_margin),
            ("a lead that is not the aggregate's difference", wrong_lead)]


@pytest.mark.parametrize("index", range(3))
def test_the_rule_catches_a_reading_of_the_tie_that_is_not_the_arithmetic_of_what_the_packet_knew(
        db: psycopg.Connection[Any], seed: Seed, index: int) -> None:
    _w, f = built(db, seed, 99980 + index)
    at = kickoff(107) - timedelta(hours=3)
    name, change = _tie_cases()[index]
    got = PacketBuilder(db).build(f["r2"], at=at)
    assert got is not None
    pid = handmade(db, f["r2"], tampered(got, change), at)
    assert audited(db, at) == {"checked": 1, "violations": 1, "examples": [pid]}, name
