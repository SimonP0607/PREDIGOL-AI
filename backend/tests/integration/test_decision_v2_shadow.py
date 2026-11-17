"""decision-v2's kept shadow (IA-093, AD-D01) against a real PostgreSQL, on the replay's own scene (two matches decided by decision-v1):

* the mirror keeps one decision of decision-v2 for every row decision-v1 wrote, at the same moment, and each is the replay's decision
  (``verify``: 0 differences; and the states are decision-v1's read through state-v2, as the replay of the same day says);
* E4 decides by itself before kick-off, E1 keeps its moment even with nothing to decide, and neither is decided twice;
* no kept input is later than its moment, the two tables refuse UPDATE and DELETE, ``intel.decisions`` does not move;
* the chains reach the cycle of states through its API, under their own writer, legal by the machine.

The pass runs inside the test's transaction (``commit=False``: one savepoint per group), so nothing outlives the test."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai.calendar import local_day
from fbi.decision import engine, replay, shadow
from fbi.intel import decision, state_v2
from fbi.lifecycle import derive, machine, store
from tests.integration.conftest import Seed

from .test_decision_v2_replay import core_scene
from .test_intel import AT

pytestmark = pytest.mark.integration

V20 = shadow.Config(rules=engine.RULES_V20, price=engine.CONSENSUS, probability=engine.OWN, view_version="forecast-v1")
"""decision-v1's price and probability: the configuration whose decisions the replay holds equal to decision-v1's."""
V21 = shadow.Config(price=engine.CONSENSUS)
"""The shadow's own ruleset and single figure, priced by the consensus (the book needs RAW bodies: tests/integration/test_decision_v2_book_price.py)."""


def count(db: psycopg.Connection[Any], sql: str, *args: Any) -> int:
    row = db.execute(sql, args).fetchone()
    assert row is not None
    return int(row[0])


def test_the_mirror_keeps_every_candidate_of_decision_v1_at_its_moment_and_is_the_replay(db: psycopg.Connection[Any], seed: Seed) -> None:
    core_scene(db, seed)
    decision.decide(db, at=AT)
    v1_before = count(db, "SELECT count(*) FROM intel.decisions")
    rep = shadow.run_pass(db, now=AT + timedelta(minutes=5), store=None, triggers=("mirror",), config=V20, commit=False)
    assert not rep.errors and rep.leaks == 0, rep.errors
    v1_rows = count(db, "SELECT count(*) FROM intel.decisions WHERE decision_version = 'decision-v1' AND checkpoint <> 'selection'")
    assert rep.mirror_rows == v1_rows == rep.mirror_matched and rep.moments["mirror"] == 2, rep.as_json()
    assert count(db, "SELECT count(*) FROM intel.decisions") == v1_before, "decision-v1's table does not move"

    kept = db.execute("SELECT d.state, d.reason, d.codes, v.state, v.reasons, v.filters, v.checkpoint, d.checkpoint, d.known_at, v.known_at "
                      "FROM intel.decisions_v2 d JOIN intel.decisions v ON v.id = d.mirror_of WHERE d.config_key = %s",
                      (V20.key,)).fetchall()
    assert len(kept) == v1_rows
    for state, _reason, _codes, v1_state, reasons, filters, v1_cp, cp, at2, at1 in kept:
        expected, _ = state_v2.classify({"state": v1_state, "reasons": reasons, "filters": filters})
        assert state == expected and cp == v1_cp and at1 == at2, (state, expected, cp, v1_cp)
    day = replay.replay_day(db, day=local_day(AT))
    assert day["agreement"]["rate"] == 1.0, "the replay of the same day agrees with decision-v1 on the same rows"

    check = shadow.verify(db, start=AT - timedelta(hours=1), end=AT + timedelta(hours=1), store=None, config=V20)
    assert check["coverage"]["rate"] == 1.0 and check["equivalence"]["differences"] == 0, check
    assert check["equivalence"]["moments_checked"] == 2

    again = shadow.run_pass(db, now=AT + timedelta(minutes=10), store=None, triggers=("mirror",), config=V20, commit=False)
    assert again.decisions == 0 and not again.moments, "a moment is kept once"


def test_every_kept_decision_carries_its_inputs_no_later_than_its_moment_and_its_previous_version(db: psycopg.Connection[Any],
                                                                                                  seed: Seed) -> None:
    w, a, _b = core_scene(db, seed)
    decision.decide(db, at=AT)
    later = AT + timedelta(minutes=30)
    w.consensus(a, "OU", "Over", "2.5", p_fair=0.48, best=2.15, as_of=later - timedelta(minutes=5))
    decision.decide(db, at=later)
    rep = shadow.run_pass(db, now=later + timedelta(minutes=2), store=None, triggers=("mirror",), config=V21, commit=False)
    assert not rep.errors and rep.leaks == 0 and rep.decisions > 0, rep.as_json()
    rows = db.execute("SELECT id, previous_id, known_at, price_at, model_cutoff, inputs, rules, probability_source, probability_version, "
                      "decision, evidence, chain_key FROM intel.decisions_v2 WHERE config_key = %s ORDER BY id", (V21.key,)).fetchall()
    for _id, _prev, known_at, price_at, cutoff, inputs, rules, source, version, body, evidence, _key in rows:
        assert rules == engine.RULES_V21 and body["rules"] == engine.RULES_V21
        assert price_at is None or price_at <= known_at
        assert cutoff is None or cutoff <= known_at
        assert inputs["at"] == known_at.isoformat() and set(evidence) >= {"ids", "counts", "status", "review"}
        assert source == engine.COMMON or body["prediction"]["missing"] is not None, "judged with the single figure, or it says why not"
        assert version in (None, "forecast-v2")
        assert [s["stage"] for s in body["stages"]] == list(engine.STAGES)
    by_chain: dict[str, list[tuple[int, int | None]]] = {}
    for r in rows:
        by_chain.setdefault(r[11], []).append((r[0], r[1]))
    assert any(len(v) == 2 for v in by_chain.values())
    for versions in by_chain.values():
        assert versions[0][1] is None and all(prev == versions[i][0] for i, (_, prev) in enumerate(versions[1:])), versions
    moments = db.execute("SELECT trigger, evaluation, mirrored_version, candidates, decided, world_hash FROM intel.decision_v2_moments "
                         "WHERE config_key = %s", (V21.key,)).fetchall()
    assert moments and all(t == "mirror" and e is None and mv == "decision-v1" and d <= c and len(h) == 64 for t, e, mv, c, d, h in moments)

    for sql in ("UPDATE intel.decisions_v2 SET state = 'RECOMMENDED'", "DELETE FROM intel.decisions_v2",
                "UPDATE intel.decision_v2_moments SET decided = 0", "DELETE FROM intel.decision_v2_moments"):
        with pytest.raises(psycopg.Error), db.transaction():
            db.execute(sql)


def test_e4_decides_by_itself_before_the_floor_and_e1_keeps_its_moment_once(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, a, b = core_scene(db, seed)
    kickoff_a = AT + timedelta(hours=5)
    e4 = shadow.run_pass(db, now=kickoff_a - timedelta(minutes=15), store=None, triggers=("E1", "E4"), config=V21, commit=False)
    assert not e4.errors and e4.moments["E4"] == 1 and e4.decisions >= 1, e4.as_json()
    got = db.execute("SELECT DISTINCT trigger, evaluation, evaluation_version, checkpoint FROM intel.decisions_v2 WHERE fixture_id = %s",
                     (a,)).fetchall()
    assert {(t, e, v) for t, e, v, _ in got} == {("E4", "E4", 1)}
    assert all(cp in decision.FINAL_CHECKPOINTS or cp.startswith("T-") for *_, cp in got)
    assert shadow.run_pass(db, now=kickoff_a - timedelta(minutes=12), store=None, triggers=("E4",), config=V21, commit=False).decisions == 0

    kickoff_b = AT + timedelta(hours=8)
    early = kickoff_b - timedelta(hours=13)  # inside E1, before the picks were made: nothing to decide, the moment is kept
    e1 = shadow.run_pass(db, now=early, store=None, triggers=("E1", "E4"), config=V21, commit=False)
    assert e1.moments["E1"] >= 1 and not e1.errors, e1.as_json()
    assert count(db, "SELECT count(*) FROM intel.decision_v2_moments WHERE fixture_id = %s AND trigger = 'E1'", b) == 1
    assert shadow.run_pass(db, now=early + timedelta(hours=1), store=None, triggers=("E1",), config=V21, commit=False).moments == {}


def test_the_chains_go_to_the_cycle_through_its_api_under_their_own_writer(db: psycopg.Connection[Any], seed: Seed) -> None:
    core_scene(db, seed)
    decision.decide(db, at=AT)
    shadow.run_pass(db, now=AT + timedelta(minutes=5), store=None, triggers=("mirror",), config=V20, commit=False, link=False)
    assert count(db, "SELECT count(*) FROM intel.selection_lifecycle WHERE writer = %s", shadow.WRITER) == 0
    early = shadow.link_lifecycle(db, now=AT + timedelta(minutes=10), config=V20)
    assert early.appended == 0, "a decision younger than LINK_LAG waits: an earlier moment may still arrive"
    rep = shadow.link_lifecycle(db, now=AT + timedelta(hours=1), config=V20)
    assert rep.appended > 0 and rep.illegal == 0 and rep.divergent == 0, rep.as_json()
    rows = db.execute("SELECT chain_key, state, reason, layer, source, source_id FROM intel.selection_lifecycle WHERE writer = %s "
                      "ORDER BY chain_key, id", (shadow.WRITER,)).fetchall()
    assert {r[3] for r in rows} == {"decision-v2"} and {r[4] for r in rows} == {"intel.decisions_v2"}
    chains: dict[str, list[machine.Step]] = {}
    for key, state, reason, *_ in rows:
        chains.setdefault(key, []).append(machine.Step(state, reason))
    for steps in chains.values():
        machine.check_chain(steps)
    # the same scene read off decision-v1 by the cycle's own writer ends every selection where decision-v2's chain ends it
    fixtures = {f.id: f for f in (derive.Fixture(int(i), k, s, g) for i, k, s, g in db.execute(
        "SELECT id, kickoff_at, status_short, status_group FROM core.fixtures WHERE id IN (SELECT fixture_id FROM intel.decisions_v2)"))}
    v1 = {f"{k.fixture_id}|{k.market_key}|{k.selection}|{k.line}": derive.derive(h, fixtures[k.fixture_id], now=AT + timedelta(hours=1))
          for k, h in store.histories(db, sorted(fixtures), layers=(decision.VERSION,)).items()}
    ours = {key.split("|", 1)[1]: steps for key, steps in chains.items()}
    assert set(ours) == set(v1) and all((ours[k][-1].state, ours[k][-1].reason) == (v1[k][-1].step.state, v1[k][-1].step.reason)
                                        for k in ours), (ours, v1)
    again = shadow.link_lifecycle(db, now=AT + timedelta(hours=1), config=V20)
    assert again.appended == 0 and again.unchanged == again.selections, "the same database says the same thing as nothing"
    played = shadow.link_lifecycle(db, now=AT + timedelta(hours=9), config=V20)
    assert played.illegal == 0


def test_the_shadows_own_configuration_reads_the_book_from_raw_and_says_why_a_selection_has_no_price(db: psycopg.Connection[Any],
                                                                                                       seed: Seed, tmp_path: Any) -> None:
    """``CONFIG`` as the worker runs it: decision-v2.1, the book's price, the single figure. With no ask in the book the core's selections are
    kept «sin precio» with the book's reason (never asked), and nothing is invented."""
    from fbi.storage.payload_store import PayloadStore

    core_scene(db, seed)
    decision.decide(db, at=AT)
    rep = shadow.run_pass(db, now=AT + timedelta(minutes=5), store=PayloadStore(tmp_path), triggers=("mirror",), commit=False)
    assert not rep.errors and rep.mirror_matched == rep.mirror_rows > 0, rep.as_json()
    rows = db.execute("SELECT price_source, price_state, odds, decision->'price'->>'missing', state FROM intel.decisions_v2 "
                      "WHERE config_key = %s", (shadow.CONFIG.key,)).fetchall()
    assert rows and {r[0] for r in rows} == {"book"} and all(r[2] is None and r[1] == "sin_precio" and r[3] for r in rows), rows
    assert {r[4] for r in rows} <= {"REJECTED", "ABSTAIN", "WATCH"}, "no price is never a recommendation"
    with pytest.raises(ValueError, match="RAW"):
        shadow.run_pass(db, now=AT, store=None, commit=False)
