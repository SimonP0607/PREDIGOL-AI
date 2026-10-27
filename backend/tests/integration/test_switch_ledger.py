"""The ledger of the owner's words (``gates.record_switches``) and what Gate A reads from it (review of phase 2, M5).

Gate A judges the optimisations that were in force during its seven days. An environment variable changed by hand wrote no row of its own, so
the gate could only read the words of the process that evaluated it - and ``FBI_AI_NATIVE_SCHEMA=on`` forced during the window, against its own
failing evidence, and put back to ``auto`` right before ``--record`` left the judgement without it. These tests hold the three things that close
that: the worker writes the words it runs with when they change, a change of the words is a day the configuration changed, and what is in force
is read from the ledger as well as from the process that evaluates.

The world is the one of ``test_gate_a.py`` (September 2032, the window is the 13th to the 19th, today the 20th at noon in Bogotá)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.ai import gate_a, gates

from .conftest import Seed
from .test_gate_a import (
    DEPLOY,
    GATES_AT,
    NOW,
    SONNET,
    build,
    checks,
    equivalence,
    evaluate,
    failing,
    lab_switches,
    noon,
    settings,
)

FORCED = lab_switches(native_schema="on")


def newest_gate_a_rows(db: psycopg.Connection[Any]) -> int:
    row = db.execute("SELECT count(*) FROM ai.feature_gates WHERE gate = 'gate_a'").fetchone()
    assert row is not None
    return int(row[0])


def native_rejected(db: psycopg.Connection[Any]) -> None:
    """The evidence of the experiment: the probe passed, the layout passed, the structured outputs changed more verdicts than repeating the call."""
    gates.record_gate(db, gate="batch", passed=True, at=GATES_AT, evidence={"models": [SONNET.model]})
    bad, passed = equivalence("native_schema", repeat=3, changed=9)
    assert passed is False
    gates.record_gate(db, gate="native_schema", passed=False, at=GATES_AT, evidence=bad)
    good, ok = equivalence("shared_layout")
    gates.record_gate(db, gate="cache_layout", passed=ok, at=GATES_AT, evidence=good)


# ── what the worker writes ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_first_look_is_the_baseline_and_the_same_words_again_write_nothing(db: psycopg.Connection[Any]) -> None:
    cfg = settings()
    first = gates.record_switches(db, cfg, at=noon(DEPLOY), code_version="v1")
    assert first is not None
    assert gates.record_switches(db, cfg, at=noon(DEPLOY) + timedelta(minutes=10), code_version="v1") is None
    assert gates.record_switches(db, settings(), at=noon(DEPLOY) + timedelta(days=3)) is None, "other object, same words: nothing"
    row = db.execute("SELECT gate, passed, decided_by, code_version, evidence, evidence_hash FROM ai.feature_gates WHERE id = %s", (first,)).fetchone()
    assert row is not None
    gate, passed, decided_by, code_version, evidence, digest = row
    assert (gate, passed, decided_by, code_version) == ("switches", True, "script", "v1")
    assert evidence["kind"] == "switch-words-v1" and evidence["baseline"] is True and evidence["changed"] == []
    assert evidence["words"] == gates.switch_words(cfg) and digest == gates.evidence_hash(evidence)
    assert db.execute("SELECT count(*) FROM ai.feature_gates WHERE gate = 'switches'").fetchone() == (1,)


def test_a_change_of_a_word_writes_a_row_that_says_what_changed_and_going_back_is_a_change_too(db: psycopg.Connection[Any]) -> None:
    base = settings()
    gates.record_switches(db, base, at=noon(DEPLOY))
    changed = settings(switches=FORCED, research_v2="shadow")
    row = gates.record_switches(db, changed, at=noon(DEPLOY) + timedelta(days=1))
    assert row is not None
    evidence = db.execute("SELECT evidence FROM ai.feature_gates WHERE id = %s", (row,)).fetchone()
    assert evidence is not None and evidence[0]["baseline"] is False
    assert evidence[0]["changed"] == ["research_v2: off -> shadow", "switches.native_schema: auto -> on"]
    assert gates.record_switches(db, changed, at=noon(DEPLOY) + timedelta(days=2)) is None
    back = gates.record_switches(db, base, at=noon(DEPLOY) + timedelta(days=3))
    assert back is not None, "the ledger is a history, not a state: the words that were first are a change from the ones that came after"
    ledger = gates.switch_ledger(db)
    assert [r[0] for r in ledger] == sorted(r[0] for r in ledger) and len(ledger) == 3
    assert [r[2] for r in ledger] == [gates.switch_words(base), gates.switch_words(changed), gates.switch_words(base)]


def test_no_key_reaches_the_ledger(db: psycopg.Connection[Any]) -> None:
    cfg = settings(keys={"anthropic": "sk-ant-api03-SECRET-KEY"}, lab_keys={"anthropic": "sk-ant-api03-SECRET-LAB"}, workspace="PREDIGOL",
                   key_label="worker-prod")
    gates.record_switches(db, cfg, at=noon(DEPLOY))
    gates.record_switches(db, settings(monthly_budget=Decimal(200)), at=noon(DEPLOY) + timedelta(days=1))
    dump = " ".join(str(r) for r in db.execute("SELECT evidence::text, evidence_hash, decided_by, code_version FROM ai.feature_gates "
                                               "WHERE gate = 'switches'").fetchall())
    assert "SECRET" not in dump and "sk-ant" not in dump and "worker-prod" not in dump and "PREDIGOL" not in dump


def test_a_row_of_the_ledger_that_carries_no_words_is_not_read(db: psycopg.Connection[Any]) -> None:
    gates.record_gate(db, gate="switches", passed=True, at=noon(DEPLOY), evidence={"hello": "nothing to read here"})
    assert gates.switch_ledger(db) == []
    assert gate_a.switch_changes(db) == []
    row = gates.record_switches(db, settings(), at=noon(DEPLOY) + timedelta(hours=1))
    assert row is not None, "and the next look writes the words, as a baseline"
    assert [r[2] for r in gates.switch_ledger(db)] == [gates.switch_words(settings())]


def test_the_ledger_is_not_a_gate_nothing_waits_for_it(db: psycopg.Connection[Any]) -> None:
    gates.record_switches(db, settings(), at=noon(DEPLOY))
    described = gates.describe(db, settings())
    assert "switches" not in described["gates"], "the panel of costs shows the gates; the ledger of the owner's words is not one of them"
    assert gates.gate_state(db, "switches").passed is True, "(it is a row like the others, and always a true one)"
    for name in ("batch", "native_schema", "cache_layout"):
        assert described[name]["on"] is False, "a row of the ledger turns nothing on"
    assert not gates.gate_state(db, "gate_a").passed


# ── a change of the words is a day the configuration changed ─────────────────────────────────────────────────────────

def test_the_first_row_is_the_baseline_and_not_a_change_even_inside_the_window(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    gates.record_switches(db, settings(), at=noon(date(2032, 9, 15)))  # the ledger begins in the middle of the window
    assert gate_a.switch_changes(db) == []
    assert gate_a.window_of(db, at=NOW).complete
    assert evaluate(db).verdict == gate_a.PASS, "a healthy week with a ledger that has just begun is still a pass"


def test_a_change_of_the_words_inside_the_window_moves_the_start_of_the_window(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    gates.record_switches(db, settings(), at=noon(date(2032, 9, 10)))
    gates.record_switches(db, settings(research_v2="shadow"), at=noon(date(2032, 9, 15)))
    ((day, why),) = gate_a.switch_changes(db)
    assert day == date(2032, 9, 15) and "research_v2: off -> shadow" in why
    w = gate_a.window_of(db, at=NOW)
    assert not w.complete and w.anchor == date(2032, 9, 16) and "the owner's words changed" in str(w.anchored_by)
    report = evaluate(db)
    assert report.verdict == gate_a.PENDING_TIME and not report.recordable
    assert gate_a.record(db, report) is None and newest_gate_a_rows(db) == 0


def test_a_change_before_the_window_does_not_move_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    gates.record_switches(db, settings(), at=noon(date(2032, 9, 10)))
    gates.record_switches(db, settings(research_v2="shadow"), at=noon(date(2032, 9, 12)))
    assert gate_a.window_of(db, at=NOW).complete


def test_the_same_words_written_again_are_no_change(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Two rows with the same words can only exist if somebody wrote them by hand: the gate reads words, not rows."""
    build(db, seed)
    gates.record_gate(db, gate="switches", passed=True, at=noon(date(2032, 9, 10)),
                      evidence={"kind": gates.WORDS_KIND, "words": gates.switch_words(settings())})
    gates.record_gate(db, gate="switches", passed=True, at=noon(date(2032, 9, 16)),
                      evidence={"kind": gates.WORDS_KIND, "words": gates.switch_words(settings()), "again": True})
    assert gate_a.switch_changes(db) == [] and gate_a.window_of(db, at=NOW).complete


# ── what is in force: the ledger as well as the process that evaluates ───────────────────────────────────────────────

def test_without_the_ledger_only_this_process_is_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    on, meta = gate_a.in_force_by_ledger(db)
    assert on is None and meta["rows"] == 0 and "has not written the ledger" in meta["note"]
    check = gate_a.check_equivalence(db, settings())
    assert check.detail["in_force_by_ledger"] is None and check.detail["ledger_and_process_disagree"] == []
    assert check.detail["in_force"] == check.detail["in_force_now"] == {"batch": True, "native_schema": True, "cache_layout": True}


def test_when_the_ledger_and_the_process_agree_each_optimisation_is_judged_once(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    gates.record_switches(db, settings(), at=noon(DEPLOY))
    check = gate_a.check_equivalence(db, settings())
    every = {"batch": True, "native_schema": True, "cache_layout": True}
    assert check.ok is True and check.detail["in_force_by_ledger"] == check.detail["in_force_now"] == check.detail["in_force"] == every
    assert check.detail["judged"] == ["batch", "native_schema", "cache_layout"] and check.detail["ledger_and_process_disagree"] == []
    assert check.detail["switch_ledger"]["rows"] == 1 and check.detail["switch_ledger"]["words"] == gates.switch_words(settings())
    assert evaluate(db).verdict == gate_a.PASS


def test_a_switch_forced_on_in_the_window_and_put_back_before_the_verdict_is_still_judged(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The scenario of the review (M5): ``FBI_AI_NATIVE_SCHEMA=on`` during the window, against its own failing evidence, and ``auto`` again in the
    environment of whoever evaluates. Before the ledger the gate read that environment, found the optimisation off, did not judge it and passed."""
    build(db, seed, with_gates=False)
    native_rejected(db)
    gates.record_switches(db, settings(switches=FORCED), at=noon(DEPLOY))  # the worker's baseline: forced on since the deploy
    put_back = settings()
    check = gate_a.check_equivalence(db, put_back)
    assert check.ok is False and check.detail["failed"] == ["native_schema"] and check.revert == "FBI_AI_NATIVE_SCHEMA"
    assert check.detail["in_force"]["native_schema"] is True
    assert check.detail["in_force_now"]["native_schema"] is False and check.detail["in_force_by_ledger"]["native_schema"] is True
    assert check.detail["ledger_and_process_disagree"] == ["native_schema"] and "disagree on: native_schema" in check.detail["note"]
    report = evaluate(db, cfg=put_back)
    assert report.verdict == gate_a.FAIL and "verdict_equivalence" in failing(report)
    assert report.consequence is not None and "FBI_AI_NATIVE_SCHEMA" in report.consequence


def test_putting_it_back_in_the_environment_leaves_a_row_that_moves_the_window_so_the_verdict_waits(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The same scenario once the worker has looked: it saw the change and wrote it, so the window is not complete and nothing can be recorded."""
    build(db, seed, with_gates=False)
    native_rejected(db)
    gates.record_switches(db, settings(switches=FORCED), at=noon(DEPLOY))
    gates.record_switches(db, settings(), at=noon(date(2032, 9, 19)))  # the last day of the window
    report = evaluate(db, cfg=settings())
    assert report.verdict == gate_a.PENDING_TIME and not report.recordable
    assert report.window.anchor == date(2032, 9, 20) and "native_schema: on -> auto" in str(report.window.anchored_by)
    assert gate_a.record(db, report) is None and newest_gate_a_rows(db) == 0


def test_what_the_ledger_says_is_off_does_not_take_out_what_this_process_forces(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, with_gates=False)
    native_rejected(db)
    gates.record_switches(db, settings(), at=noon(DEPLOY))
    check = gate_a.check_equivalence(db, settings(switches=FORCED))
    assert check.ok is False and check.detail["failed"] == ["native_schema"], "the union: judged because one of the two says it runs"
    assert check.detail["in_force_by_ledger"]["native_schema"] is False and check.detail["in_force_now"]["native_schema"] is True


def test_the_ledger_reads_the_words_like_describe_does(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Auto waits for the gate of its evidence, on is forced, off is rolled back; the shared layout needs the cache not off and its own gate."""
    build(db, seed)  # the three gates pass
    gates.record_switches(db, settings(switches=lab_switches(batch="off", native_schema="on", cache="off")), at=noon(DEPLOY))
    on, meta = gate_a.in_force_by_ledger(db)
    assert on == {"batch": False, "native_schema": True, "cache_layout": False}, meta
    gates.record_switches(db, settings(), at=noon(DEPLOY) + timedelta(days=1))
    on, _ = gate_a.in_force_by_ledger(db)
    assert on == {"batch": True, "native_schema": True, "cache_layout": True}, "auto with its gate passing is in force"
    gates.record_gate(db, gate="native_schema", passed=False, at=noon(DEPLOY) + timedelta(days=2), evidence={"why": "reverted"})
    on, _ = gate_a.in_force_by_ledger(db)
    assert on == {"batch": True, "native_schema": False, "cache_layout": True}, "and a newer failing row switches an auto one off"


def test_a_batch_the_ledger_says_ran_and_sent_nothing_is_a_failure_even_if_this_process_holds_it_off(db: psycopg.Connection[Any],
                                                                                                    seed: Seed) -> None:
    build(db, seed, batch=None)  # not one request went through a batch
    gates.record_switches(db, settings(switches=lab_switches(batch="on")), at=noon(DEPLOY))
    window = gate_a.window_of(db, at=NOW)
    held_off = gate_a.check_batch(db, settings(switches=lab_switches(batch="off")), window, at=NOW)
    assert held_off.ok is False and held_off.detail["batch_on"] is True and "ON and not one request" in held_off.detail["note"]


def test_a_batch_that_ran_nowhere_and_is_off_in_both_is_not_a_failure(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, batch=None)
    gates.record_switches(db, settings(switches=lab_switches(batch="off")), at=noon(DEPLOY))
    off = gate_a.check_batch(db, settings(switches=lab_switches(batch="off")), gate_a.window_of(db, at=NOW), at=NOW)
    assert off.ok is True and off.detail["batch_on"] is False and "off and nothing went through it" in off.detail["note"]


def test_a_healthy_week_with_the_ledger_is_recorded_with_the_ledger_on_view(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    gates.record_switches(db, settings(), at=noon(DEPLOY))
    report = evaluate(db)
    assert report.verdict == gate_a.PASS
    detail = checks(report)["verdict_equivalence"].detail
    assert detail["switch_ledger"]["rows"] == 1 and detail["in_force_by_ledger"] == detail["in_force_now"]
    assert "words" in detail["switch_ledger"] and "sk-ant" not in str(detail) and "key" not in str(detail["switch_ledger"]["words"]).lower()
    assert gate_a.record(db, report) is not None and newest_gate_a_rows(db) == 1
