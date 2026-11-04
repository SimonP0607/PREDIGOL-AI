"""The weighted head-to-head in the AI packet (plan F6: ``packet-v8``, ``dossier-v4``, ``leak-audit-v6``, rule ``h2h_known``).

The packet and the match page read the same function, so the same list. The honest packets here are built by the real builder; the
dishonest ones are the same packets edited by hand, which is what a faulty reader would have stored. The transaction is rolled back
afterwards."""

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
from fbi.api.services import center
from fbi.intel import h2h, leakage
from fbi.intel.narrative import rules_narrative

from .conftest import Seed
from .h2h_world import AT, KICKOFF, World

RULE = "h2h_known"


def played(db: psycopg.Connection[Any], seed: Seed) -> tuple[World, int, dict[str, int]]:
    """Two sides, three meetings known at AT (league, cup after extra time, a friendly), others that are not, and the match."""
    w = World(db, seed)
    ids = {
        "league": w.fixture("league", 0, 1, AT - timedelta(days=30), result=(2, 1)),
        "cup": w.fixture("cup", 1, 0, AT - timedelta(days=200), "AET", result=(2, 1), extra=(1, 0)),
        "friendly": w.fixture("friendly", 0, 1, AT - timedelta(days=400), neutral=True, result=(0, 3)),
        "awarded": w.fixture("league", 1, 0, AT - timedelta(days=60), "AWD", result=(3, 0)),
        "late": w.fixture("league", 0, 1, AT - timedelta(days=5), result=(1, 0), settled=AT + timedelta(hours=1)),
    }
    match = w.fixture("league", 0, 1, KICKOFF, "NS")
    return w, match, ids


def built(db: psycopg.Connection[Any], fixture_id: int, at: datetime = AT) -> Packet:
    packet = PacketBuilder(db).build(fixture_id, at=at)
    assert packet is not None
    return packet


def audited(db: psycopg.Connection[Any], at: datetime = AT, run: int = 0) -> dict[str, Any]:
    """The rule on the Bogotá day of ``at`` (the audit keeps every run under its ``checked_at``, so a second run in a test moves it)."""
    out: dict[str, Any] = leakage.audit_day(db, day=local_day(at), at=at + timedelta(hours=1, minutes=run))[RULE]
    return out


def handmade(db: psycopg.Connection[Any], fid: int, content: dict[str, Any], at: datetime = AT) -> int:
    row = db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id", (fid, PACKET_VERSION, at, at, hashlib.sha256(repr((fid, at, content)).encode()).hexdigest(),
                         Jsonb(content))).fetchone()
    assert row is not None
    return int(row[0])


def tampered(packet: Packet, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    content = copy.deepcopy(packet.content)
    change(content)
    return content


# ── the block ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_packet_carries_the_weighted_head_to_head(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, match, ids = played(db, seed)
    packet = built(db, match)
    assert packet.version == PACKET_VERSION == "packet-v8"
    block = packet.content["h2h"]
    assert (block["version"], block["status"], block["n"]) == (h2h.VERSION, "DESCRIPTIVE", 3)
    assert [m["fixture_id"] for m in block["meetings"]] == [ids["league"], ids["cup"], ids["friendly"]], (
        "played, before the match, recorded by AT: not the awarded one, not the one recorded an hour later")
    assert block["home_view"]["n"] == 3 and block["last_days_ago"] == 30 and block["oldest_days_ago"] == 400
    assert block["weights"]["fitted"] is False and block["relevance"] in ("baja", "media")
    assert "h2h" not in packet.missing
    assert any(s.get("block") == "h2h" and s.get("version") == h2h.VERSION for s in packet.sources)
    d = packet.content["dossier"]["h2h"]
    assert d["n"] == 3 and d["n_effective"] == block["n_effective"] and d["relevance"] == block["relevance"]


def test_the_packet_and_the_page_list_the_same_meetings(db: psycopg.Connection[Any], seed: Seed) -> None:
    """One function for both: the same meetings, in the same order, with the same weights, when asked for the same moment."""
    w, match, _ = played(db, seed)
    packet = built(db, match)
    page = w.h2h(at=AT)
    assert [m["fixture_id"] for m in packet.content["h2h"]["meetings"]] == [r["fixture_id"] for r in page.as_api()]
    assert [m["weight"] for m in packet.content["h2h"]["meetings"]] == [r["weight"] for r in page.as_api()]
    assert packet.content["h2h"]["n_effective"] == round(page.n_effective, 1)


def test_the_match_page_reads_the_same_head_to_head_as_the_packet(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    """The page asks for 'now'; asked for the moment of the packet it lists the same meetings with the same weights - and each row
    says how the meeting was decided: the final score, the 90 minutes, the shoot-out."""
    _w, match, ids = played(db, seed)
    packet = built(db, match)
    monkeypatch.setattr(center, "now", lambda: AT)
    body = center.match_center(db, match).data
    assert body is not None and body.h2h.status.value == "ok"
    rows = body.h2h.data
    assert [r.fixture_id for r in rows] == [m["fixture_id"] for m in packet.content["h2h"]["meetings"]]
    assert [round(r.weight, 2) for r in rows] == [m["weight"] for m in packet.content["h2h"]["meetings"]]
    cup = next(r for r in rows if r.fixture_id == ids["cup"])
    assert (cup.goals_home, cup.goals_away) == (2, 1) and (cup.regulation_goals_home, cup.regulation_goals_away) == (1, 1)
    assert cup.after_extra_time is True and cup.scope == "other_official" and cup.home_side_was == "away"
    friendly = next(r for r in rows if r.fixture_id == ids["friendly"])
    assert friendly.scope == "friendly" and friendly.home_side_was == "neutral" and friendly.weight < cup.weight


def test_a_result_recorded_after_the_moment_is_not_in_the_packet_and_is_in_the_next_one(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, match, ids = played(db, seed)
    early = built(db, match)
    later = built(db, match, at=AT + timedelta(hours=2))
    assert ids["late"] not in [m["fixture_id"] for m in early.content["h2h"]["meetings"]]
    assert later.content["h2h"]["meetings"][0]["fixture_id"] == ids["late"]
    assert later.content["h2h"]["n"] == 4


def test_no_meetings_is_named_missing_and_the_narrative_reads_the_relevance(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    match = w.fixture("league", 0, 1, KICKOFF, "NS")
    packet = built(db, match)
    assert packet.content["h2h"]["n"] == 0 and packet.content["h2h"]["relevance"] == "nula"
    assert "h2h" in packet.missing
    assert rules_narrative(packet.content, [])  # the narrative reads dossier.h2h.relevance and does not need the meetings


# ── the nightly proof ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v8" and RULE in (leakage.__doc__ or "")


def test_an_honest_packet_passes_one_check_per_meeting_and_one_for_the_list(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, match, _ = played(db, seed)
    store_packet(db, built(db, match), built_at=AT)
    assert audited(db) == {"checked": 4, "violations": 0, "examples": []}, "3 meetings cited, and nothing known left out"
    rows = db.execute("SELECT version, n_checked, n_violations FROM intel.audit_checks WHERE rule = %s", (RULE,)).fetchall()
    assert rows == [("leak-audit-v8", 4, 0)]


def test_a_packet_without_the_new_block_is_not_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, match, _ = played(db, seed)
    packet = built(db, match)
    old = tampered(packet, lambda c: c.update(h2h={"n": 3, "home_view": c["h2h"]["home_view"]}))
    handmade(db, match, old)
    assert audited(db) == {"checked": 0, "violations": 0, "examples": []}


def _cases(ids: dict[str, int], other_pair: int) -> list[tuple[str, Callable[[dict[str, Any]], None]]]:
    def cite(c: dict[str, Any], fixture_id: int, days_ago: int) -> None:
        c["h2h"]["meetings"].append({"fixture_id": fixture_id, "days_ago": days_ago, "competition": "x", "scope": "same_kind",
                                     "home_side_was": "home", "goals_home_side": 1, "goals_away_side": 0,
                                     "after_extra_time": False, "coach_changed": {"home": None, "away": None}, "weight": 0.5})

    def wrong_age(c: dict[str, Any]) -> None:
        c["h2h"]["meetings"][0]["days_ago"] += 1

    def left_out(c: dict[str, Any]) -> None:
        c["h2h"]["meetings"].pop(0)  # the newest known meeting was not read: an older answer than the one that existed

    def coach_claim(c: dict[str, Any]) -> None:
        c["h2h"]["meetings"][1]["coach_changed"] = {"home": True, "away": None}  # no match sheet by then for that meeting

    return [
        ("a result recorded after the packet's moment", lambda c: cite(c, ids["late"], 5)),
        ("a match that was not played to a result", lambda c: cite(c, ids["awarded"], 60)),
        ("a meeting of another pair", lambda c: cite(c, other_pair, 20)),
        ("a meeting that does not exist", lambda c: cite(c, 987654321, 20)),
        ("an age that is not the meeting's", wrong_age),
        ("a known meeting left out", left_out),
        ("a coach change nobody had a sheet for", coach_claim),
    ]


@pytest.mark.parametrize("index", range(7))
def test_the_rule_catches_each_way_a_packet_could_have_known_more_or_less_than_it_should(
        db: psycopg.Connection[Any], seed: Seed, index: int) -> None:
    w, match, ids = played(db, seed)
    other = w.fixture("league", 0, 2, AT - timedelta(days=20), result=(5, 0))
    name, change = _cases(ids, other)[index]
    packet = built(db, match)
    pid = handmade(db, match, tampered(packet, change))
    got = audited(db)
    assert got["violations"] == 1 and got["examples"] == [pid], name
