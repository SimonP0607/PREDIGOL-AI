"""The registry of context factors in the AI packet (plan F6: ``packet-v8``, block ``factors``; ``leak-audit-v6``, rule ``factors_known``).

The packet says, for each context factor, what it was AS OF the packet's moment - DESCRIPTIVE unless a person validated that version of the
code citing an experiment - and the blocks that say their own ``status`` (the head-to-head, the scenarios, the tactics) say the same. The
honest packets are built by the real builder over the world of ``tests/integration/tactics_world.py`` (and a championship round for the
scenarios); the dishonest ones are the same packets edited by hand, which is what a faulty reader would have stored. The transaction is
rolled back afterwards."""

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
from fbi.intel import factors, h2h, leakage, tactics

from .conftest import Seed
from .tactics_world import AT, World
from .test_competition_tables_asof import championship
from .test_competition_tables_asof import packet as championship_packet

RULE = "factors_known"
REASON = "the experiment beat the form on the test matches"
RESULT = {"matches": 2100, "logloss_delta": -0.004}
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


def decide(db: psycopg.Connection[Any], key: str, at: datetime, experiment: str = "F12-01") -> factors.Decision:
    return factors.promote(db, key, experiment=experiment, result=RESULT, reason=REASON, who="Simon", at=at).decision


def take_back(db: psycopg.Connection[Any], key: str, at: datetime) -> factors.Decision:
    return factors.retire(db, key, reason="the experiment did not replicate", who="Simon", at=at).decision


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


def says(content: dict[str, Any], key: str) -> str:
    return str(content["factors"][key]["status"])


@pytest.fixture
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    w = World(db, seed)
    w.build()
    return w


# ── what the packet says ───────────────────────────────────────────────────────────────────────────────────────────────


def test_while_nobody_has_validated_anything_every_factor_and_every_block_is_descriptive(world: World, db: psycopg.Connection[Any]) -> None:
    got = packet(db, world)
    assert got.content["factors"] == factors.block(factors.unread())
    assert list(got.content["factors"]) == ["version", "note", "h2h_weighted", "scenarios", "tactics_profile", "rest_congestion"]
    assert got.content["h2h"]["status"] == got.content["dossier"]["tactics"]["status"] == "DESCRIPTIVE"
    assert "factors" not in got.missing
    assert {"block": "factors", "table": "intel.context_factors", "as_of": AT.isoformat(), "version": factors.VERSION} in got.sources


def test_each_entry_says_the_version_in_force_and_where_the_factor_is_in_the_packet(world: World, db: psycopg.Connection[Any]) -> None:
    c = packet(db, world).content
    assert c["factors"]["h2h_weighted"]["version"] == c["h2h"]["version"] == h2h.VERSION
    assert c["factors"]["tactics_profile"]["version"] == c["dossier"]["tactics"]["version"] == tactics.VERSION
    for f in factors.CATALOGUE:
        assert c["factors"][f.key]["block"] == f.where


def test_a_validated_factor_is_validated_in_its_entry_and_in_its_block_from_the_moment_it_was_decided(world: World,
                                                                                                db: psycopg.Connection[Any]) -> None:
    h = decide(db, factors.H2H, AT - HOUR)
    t = decide(db, factors.TACTICS, AT - 2 * HOUR, "F12-tactics-01")
    c = packet(db, world).content
    assert c["factors"]["h2h_weighted"] == {"version": h2h.VERSION, "block": "h2h", "status": "VALIDATED",
                                           "decision": {"id": h.id, "decided_at": (AT - HOUR).isoformat(), "experiment": "F12-01"}}
    assert c["factors"]["tactics_profile"]["decision"] == {"id": t.id, "decided_at": (AT - 2 * HOUR).isoformat(),
                                                           "experiment": "F12-tactics-01"}
    assert c["h2h"]["status"] == "VALIDATED" and c["dossier"]["tactics"]["status"] == "VALIDATED"
    assert says(c, "scenarios") == says(c, "rest_congestion") == "DESCRIPTIVE", "what nobody decided on is as it was"
    assert "Simon" not in repr(c["factors"]) and REASON not in repr(c["factors"]), "no name and no free text go to the language model"


def test_a_decision_taken_after_the_packets_moment_is_not_in_it_and_is_in_the_packet_built_afterwards(world: World,
                                                                                                    db: psycopg.Connection[Any]) -> None:
    decide(db, factors.H2H, AT + 2 * HOUR)
    early = packet(db, world, AT).content
    assert says(early, "h2h_weighted") == "DESCRIPTIVE" and early["h2h"]["status"] == "DESCRIPTIVE"
    assert early["factors"]["h2h_weighted"]["decision"] is None
    late = packet(db, world, AT + 3 * HOUR).content
    assert says(late, "h2h_weighted") == "VALIDATED" and late["h2h"]["status"] == "VALIDATED"


def test_a_validation_taken_back_is_descriptive_in_the_packet_built_after_it_and_validated_in_the_one_before(
        world: World, db: psycopg.Connection[Any]) -> None:
    first = decide(db, factors.H2H, AT - 3 * DAY)
    back = take_back(db, factors.H2H, AT - DAY)
    before = packet(db, world, AT - 2 * DAY).content
    assert says(before, "h2h_weighted") == "VALIDATED" and before["factors"]["h2h_weighted"]["decision"]["id"] == first.id
    after = packet(db, world).content
    assert says(after, "h2h_weighted") == "DESCRIPTIVE" and after["h2h"]["status"] == "DESCRIPTIVE"
    assert after["factors"]["h2h_weighted"]["decision"] == {"id": back.id, "decided_at": (AT - DAY).isoformat(), "experiment": None}


def test_the_packet_is_a_new_packet_when_a_decision_is_taken(world: World, db: psycopg.Connection[Any]) -> None:
    before = packet(db, world)
    decide(db, factors.H2H, AT - HOUR)
    after = packet(db, world)
    assert before.hash != after.hash, "the brief is asked again when what the AI may use as a signal changes"
    assert packet(db, world).hash == after.hash, "and not otherwise"


def test_a_validation_of_another_version_of_the_code_is_not_in_the_packet(world: World, db: psycopg.Connection[Any]) -> None:
    db.execute("INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence) "
               "VALUES (%s, 'h2h-v1', 'VALIDATED', %s, 'owner', 'Simon', %s, %s)",
               (factors.H2H, AT - DAY, REASON, Jsonb({"factor": factors.H2H, "version": "h2h-v1", "experiment": "old", "result": RESULT})))
    c = packet(db, world).content
    assert says(c, "h2h_weighted") == "DESCRIPTIVE" and c["h2h"]["status"] == "DESCRIPTIVE"


def test_a_registry_that_cannot_be_read_costs_the_packet_nothing_and_leaves_every_factor_descriptive(
        world: World, db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    decide(db, factors.H2H, AT - DAY)

    def broken(_conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, factors.Standing]:
        raise psycopg.errors.UndefinedTable("the registry is gone")

    monkeypatch.setattr(factors, "standings", broken)
    got = packet(db, world)
    assert got.content["factors"]["error"] == "UndefinedTable" and "factors" in got.missing
    assert all(says(got.content, f.key) == "DESCRIPTIVE" for f in factors.CATALOGUE)
    assert got.content["h2h"]["status"] == "DESCRIPTIVE" and got.content["h2h"]["n"] == 1, "and the rest of the packet is there"
    assert got.content["dossier"]["tactics"]["home"]["n"] > 0
    monkeypatch.undo()
    assert says(packet(db, world).content, "h2h_weighted") == "VALIDATED", "the next packet reads it again"


def test_the_scenarios_of_a_match_are_validated_when_the_scenarios_factor_is(db: psycopg.Connection[Any], seed: Seed) -> None:
    _s, match, ko = championship(db, 99971)
    assert championship_packet(db, match, ko).content["scenarios"]["status"] == "DESCRIPTIVE"
    decide(db, factors.SCENARIOS, ko - timedelta(hours=4))
    c = championship_packet(db, match, ko).content
    assert c["scenarios"]["status"] == c["factors"]["scenarios"]["status"] == "VALIDATED"


# ── the nightly proof ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v9" and RULE in (leakage.__doc__ or "")


def test_an_honest_packet_passes_one_check_per_factor_and_one_per_block_that_states_its_status(world: World,
                                                                                            db: psycopg.Connection[Any]) -> None:
    store_packet(db, packet(db, world), built_at=AT)
    assert audited(db, AT) == {"checked": 6, "violations": 0, "examples": []}, "4 factors; the head-to-head and the tactics (no scenarios here)"
    rows = db.execute("SELECT version, n_violations FROM intel.audit_checks WHERE rule = %s", (RULE,)).fetchall()
    assert rows and all(v == "leak-audit-v9" and bad == 0 for v, bad in rows)


def test_honest_packets_pass_whatever_the_registry_said_when_they_were_built(world: World, db: psycopg.Connection[Any]) -> None:
    """Never decided; validated; taken back; validated again by another experiment; another factor validated; and a decision to come.
    Each packet is built the day after the decision it shows, as a decision is: the proof is of what the packet could have read."""
    steps: list[tuple[datetime, Callable[[], object]]] = [
        (AT - 6 * DAY, lambda: None),
        (AT - 5 * DAY, lambda: decide(db, factors.H2H, AT - 5 * DAY)),
        (AT - 4 * DAY, lambda: take_back(db, factors.H2H, AT - 4 * DAY)),
        (AT - 3 * DAY, lambda: decide(db, factors.H2H, AT - 3 * DAY, "F12-02")),
        (AT - 2 * DAY, lambda: decide(db, factors.TACTICS, AT - 2 * DAY, "F12-tactics-01")),
        (AT - 1 * DAY, lambda: decide(db, factors.SCENARIOS, AT, "F12-after")),
    ]
    built: dict[datetime, Packet] = {}
    for when, step in steps:
        step()
        built[when + HOUR] = packet(db, world, when + HOUR)
        store_packet(db, built[when + HOUR], built_at=when + HOUR)
    assert len({p.hash for p in built.values()}) == len(steps), "each state of the registry is a different packet"
    states = [{k: p.content["factors"][k]["status"] for k in factors.BY_KEY} for p in built.values()]
    assert [s["h2h_weighted"] for s in states] == ["DESCRIPTIVE", "VALIDATED", "DESCRIPTIVE", "VALIDATED", "VALIDATED", "VALIDATED"]
    assert [s["tactics_profile"] for s in states] == ["DESCRIPTIVE"] * 4 + ["VALIDATED"] * 2
    assert [s["scenarios"] for s in states] == ["DESCRIPTIVE"] * 6, "a decision to come is not in the packet"
    for run, at in enumerate(built):
        assert audited(db, at, run) == {"checked": 6, "violations": 0, "examples": []}, f"the packet of {at}"


def test_a_packet_without_the_block_is_not_read(world: World, db: psycopg.Connection[Any]) -> None:
    handmade(db, world.f["U"], tampered(packet(db, world), lambda c: c.pop("factors")), AT)
    assert audited(db, AT) == {"checked": 0, "violations": 0, "examples": []}


def test_a_packet_that_says_it_could_not_read_the_registry_states_descriptive_and_is_not_blamed_for_it(
        world: World, db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    decide(db, factors.H2H, AT - DAY)

    def broken(_conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, factors.Standing]:
        raise psycopg.errors.UndefinedTable("the registry is gone")

    monkeypatch.setattr(factors, "standings", broken)
    store_packet(db, packet(db, world), built_at=AT)
    assert audited(db, AT) == {"checked": 2, "violations": 0, "examples": []}, "only its blocks and its entries agree: the safe side"


def _entry(c: dict[str, Any], key: str, status: str, decision: dict[str, Any] | None, block: str | None = None) -> None:
    c["factors"][key]["status"] = status
    c["factors"][key]["decision"] = decision
    if block == "h2h":
        c["h2h"]["status"] = status
    elif block == "tactics":
        c["dossier"]["tactics"]["status"] = status


def _cite(d: factors.Decision) -> dict[str, Any]:
    return {"id": d.id, "decided_at": d.decided_at.isoformat(), "experiment": d.experiment}


def caught(db: psycopg.Connection[Any], world: World, change: Callable[[dict[str, Any]], None], violations: int = 1) -> None:
    pid = handmade(db, world.f["U"], tampered(packet(db, world), change), AT)
    result = audited(db, AT)
    assert result["examples"] == [pid] and result["violations"] == violations, result


def test_a_validation_nobody_decided_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    caught(db, world, lambda c: _entry(c, "h2h_weighted", "VALIDATED", None, "h2h"))


def test_a_decision_that_does_not_exist_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    caught(db, world, lambda c: _entry(c, "h2h_weighted", "DESCRIPTIVE", {"id": 987_654_321, "decided_at": AT.isoformat(), "experiment": None}))


def test_a_decision_taken_after_the_packets_moment_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    later = decide(db, factors.H2H, AT + 2 * HOUR)
    caught(db, world, lambda c: _entry(c, "h2h_weighted", "VALIDATED", _cite(later), "h2h"))


def test_a_decision_that_was_known_and_is_left_out_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    decide(db, factors.H2H, AT - 2 * DAY)
    caught(db, world, lambda c: _entry(c, "h2h_weighted", "DESCRIPTIVE", None, "h2h"))


def test_a_validation_that_was_taken_back_and_is_still_stated_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    first = decide(db, factors.H2H, AT - 3 * DAY)
    take_back(db, factors.H2H, AT - DAY)
    caught(db, world, lambda c: _entry(c, "h2h_weighted", "VALIDATED", _cite(first), "h2h"))


def test_a_taking_back_that_is_hidden_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    decide(db, factors.H2H, AT - 3 * DAY)
    take_back(db, factors.H2H, AT - DAY)
    caught(db, world, lambda c: _entry(c, "h2h_weighted", "DESCRIPTIVE", None, "h2h"))


def test_another_experiment_than_the_one_decided_on_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    decide(db, factors.H2H, AT - 2 * DAY)

    def change(c: dict[str, Any]) -> None:
        c["factors"]["h2h_weighted"]["decision"]["experiment"] = "a better experiment"

    caught(db, world, change)


def test_the_decision_about_another_factor_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    mine = decide(db, factors.H2H, AT - 2 * DAY)

    def change(c: dict[str, Any]) -> None:
        _entry(c, "tactics_profile", "VALIDATED", _cite(mine), "tactics")

    caught(db, world, change)


def test_a_head_to_head_that_says_another_status_than_its_factor_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    decide(db, factors.H2H, AT - 2 * DAY)

    def change(c: dict[str, Any]) -> None:
        c["h2h"]["status"] = "DESCRIPTIVE"

    caught(db, world, change)


def test_tactics_that_say_another_status_than_their_factor_are_caught(world: World, db: psycopg.Connection[Any]) -> None:
    def change(c: dict[str, Any]) -> None:
        c["dossier"]["tactics"]["status"] = "VALIDATED"

    caught(db, world, change)


def test_a_validation_of_another_version_used_for_this_one_is_caught(world: World, db: psycopg.Connection[Any]) -> None:
    """A reader that looked the head-to-head up at ``h2h-v1`` found a validation and stated it - for a block that is ``h2h-v2``."""
    old = db.execute("INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence) "
                     "VALUES (%s, 'h2h-v1', 'VALIDATED', %s, 'owner', 'Simon', %s, %s) RETURNING id",
                     (factors.H2H, AT - DAY, REASON, Jsonb({"factor": factors.H2H, "version": "h2h-v1", "experiment": "old",
                                                           "result": RESULT}))).fetchone()
    assert old is not None

    def change(c: dict[str, Any]) -> None:
        _entry(c, "h2h_weighted", "VALIDATED", {"id": old[0], "decided_at": (AT - DAY).isoformat(), "experiment": "old"}, "h2h")
        c["factors"]["h2h_weighted"]["version"] = "h2h-v1"

    caught(db, world, change)
