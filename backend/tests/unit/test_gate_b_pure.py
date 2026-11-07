"""The arithmetic of Gate B (``fbi.ai.gate_b``, ``gate-b-v1``) that needs no database: every verdict path of every check, on plain values, and the
order in which the verdicts win. The gate on a built world is ``tests/integration/test_gate_b_bench.py``."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.ai import gate_b as g

D = Decimal
NOW = datetime(2032, 9, 30, 17, 0, tzinfo=UTC)
TODAY = date(2032, 9, 30)
SINCE = datetime(2032, 9, 16, 5, 0, tzinfo=UTC)


# ── the order of the verdicts ────────────────────────────────────────────────────────────────────────────────────

def test_a_failure_wins_over_both_pendings_and_manual_wins_over_time() -> None:
    assert g.worst([g.PASS, g.PENDING_TIME, g.PENDING_ACTIONS, g.FAIL]) == g.FAIL
    assert g.worst([g.PASS, g.PENDING_TIME, g.PENDING_ACTIONS]) == g.PENDING_ACTIONS
    assert g.worst([g.PASS, g.PENDING_TIME]) == g.PENDING_TIME
    assert g.worst([g.PASS, g.PASS]) == g.PASS


def test_a_check_keeps_every_reason_that_is_not_a_pass() -> None:
    c = g.check("x", "X", [(g.PENDING_TIME, "wait"), (g.FAIL, "broken"), (g.PASS, "fine")], {})
    assert c.verdict == g.FAIL and c.reasons == ("wait", "broken")


# ── the window ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_without_a_shadow_run_there_is_no_anchor() -> None:
    w = g.window_from(today=TODAY, through=None, first_shadow=None, events=[])
    assert w.anchor is None and not w.complete and (w.first, w.last) == (date(2032, 9, 16), date(2032, 9, 29))


def test_fourteen_stable_days_complete_the_window_and_thirteen_do_not() -> None:
    w = g.window_from(today=TODAY, through=None, first_shadow=date(2032, 9, 15), events=[])
    assert w.complete and w.stable_days == 14 and w.anchor == date(2032, 9, 16)
    w = g.window_from(today=TODAY, through=None, first_shadow=date(2032, 9, 16), events=[])
    assert not w.complete and w.stable_days == 13 and w.eligible_on == date(2032, 10, 1)


def test_the_latest_change_anchors_the_window_and_only_delays() -> None:
    w = g.window_from(today=TODAY, through=None, first_shadow=date(2032, 9, 1),
                      events=[(date(2032, 9, 10), "a"), (date(2032, 9, 20), "match match-v3 first ran")])
    assert w.anchor == date(2032, 9, 21) and not w.complete and "match-v3" in (w.anchored_by or "")


def test_only_a_complete_day_can_end_the_window() -> None:
    with pytest.raises(ValueError, match="not a complete day"):
        g.window_from(today=TODAY, through=TODAY, first_shadow=date(2032, 9, 1), events=[])


def test_a_new_version_after_the_first_day_is_a_change_and_the_first_day_is_the_baseline() -> None:
    rows = [("match", "match-v2", "p1", "s1", date(2032, 9, 1)), ("council", "council-v2", "p2", "s2", date(2032, 9, 12))]
    assert g.version_changes(rows, date(2032, 9, 1)) == [(date(2032, 9, 12), "council council-v2 (p2, s2) first ran")]


def test_an_incomplete_window_is_pending_by_time_even_when_a_check_fails() -> None:
    w = g.window_from(today=TODAY, through=None, first_shadow=date(2032, 9, 20), events=[])
    failing = g.Check("x", "X", g.FAIL, {})
    assert g.verdict_of(w, [failing]) == g.PENDING_TIME
    full = g.window_from(today=TODAY, through=None, first_shadow=date(2032, 9, 1), events=[])
    assert g.verdict_of(full, [failing, g.Check("y", "Y", g.PASS, {})]) == g.FAIL


# ── 1. final passes out of time ──────────────────────────────────────────────────────────────────────────────────

def final(**kw: int) -> g.FinalTimes:
    base = {"passes": 40, "late_passes": 0, "calls": 120, "late_calls": 0, "undated_calls": 0, "skipped_too_late": 2} | kw
    return g.FinalTimes(base["passes"], base["late_passes"], base["calls"], base["late_calls"], base["undated_calls"],
                        base["skipped_too_late"])


@pytest.mark.parametrize(("kw", "want"), [
    ({}, g.PASS),
    ({"late_passes": 1}, g.FAIL),
    ({"late_calls": 1}, g.FAIL),
    ({"undated_calls": 1}, g.PENDING_ACTIONS),
    ({"undated_calls": 1, "late_calls": 1}, g.FAIL),
    ({"passes": 0, "calls": 0}, g.PENDING_TIME),
])
def test_final_deadline(kw: dict[str, int], want: str) -> None:
    c = g.judge_final(final(**kw))
    assert c.verdict == want
    assert c.detail["passes_not_started_too_late"] == 2 and c.detail["margin_minutes"] == 15


# ── 2. invalid outputs ───────────────────────────────────────────────────────────────────────────────────────────

def tally(agent: str = "match", version: str = "match-v2", ok: int = 194, invalid: int = 6, **extra: int) -> g.AgentTally:
    return g.AgentTally(agent, version, {"ok": ok, "invalid": invalid, **extra}, {"bad_ref": invalid} if invalid else {})


def test_three_percent_exactly_passes_and_skipped_runs_are_not_outputs() -> None:
    t = tally(ok=194, invalid=6, skipped=50)
    assert t.answered == 200 and t.rate == D("0.03")
    assert g.judge_invalid([t]).verdict == g.PASS


def test_over_three_percent_fails_whatever_the_sample() -> None:
    assert g.judge_invalid([tally(ok=193, invalid=7)]).verdict == g.FAIL
    c = g.judge_invalid([tally(ok=9, invalid=1)])
    assert c.verdict == g.FAIL and "match match-v2" in c.reasons[0]


def test_fewer_than_the_minimum_answers_only_delays() -> None:
    c = g.judge_invalid([tally(ok=99, invalid=0), tally("council", "council-v1", ok=400, invalid=2)])
    assert c.verdict == g.PENDING_TIME and len(c.reasons) == 1 and "99 answers" in c.reasons[0]


def test_no_agent_is_pending_by_time() -> None:
    assert g.judge_invalid([]).verdict == g.PENDING_TIME


def test_each_version_is_its_own_agent() -> None:
    c = g.judge_invalid([tally(version="match-v1", ok=100, invalid=10), tally(version="match-v2", ok=500, invalid=0)])
    assert c.verdict == g.FAIL and [a["agent_version"] for a in c.detail["agents"]] == ["match-v1", "match-v2"]


def test_the_tallies_split_the_codes_of_an_invalid_run() -> None:
    ts = g.tallies([("match", "match-v2", "ok", None, 10), ("match", "match-v2", "invalid", "bad_ref,missing_field", 2),
                    ("match", "match-v2", "invalid", "model_mismatch", 1), ("council", "council-v1", "invalid", None, 1)])
    by = {(t.agent, t.version): t for t in ts}
    assert by[("match", "match-v2")].invalid == 3
    assert by[("match", "match-v2")].invalid_by_code == {"bad_ref": 2, "missing_field": 2, "model_mismatch": 1}
    assert by[("council", "council-v1")].invalid_by_code == {"unknown": 1}


# ── 3. duplicate payments ────────────────────────────────────────────────────────────────────────────────────────

def test_duplicate_payments() -> None:
    assert g.judge_duplicates(300, []).verdict == g.PASS
    c = g.judge_duplicates(300, [("a" * 64, 2, [1, 2])])
    assert c.verdict == g.FAIL and c.detail["keys_paid_twice"] == 1
    assert g.judge_duplicates(0, []).verdict == g.PENDING_TIME


# ── 4. the LAB ───────────────────────────────────────────────────────────────────────────────────────────────────

def months(spent: str = "40") -> list[g.LabMonth]:
    return [g.LabMonth(date(2032, 9, 1), date(2032, 9, 29), D(spent), D(55))]


def test_the_planned_excluded_days_are_stored_nowhere_so_the_lab_is_pending_by_manual_action() -> None:
    c = g.judge_lab(months(), {}, planned=None, cycles=300, envelope_source="ledger")
    assert c.verdict == g.PENDING_ACTIONS and "not stored anywhere" in c.reasons[0]


def test_a_month_over_its_envelope_fails_even_without_the_plan() -> None:
    assert g.judge_lab(months("55.01"), {}, planned=None, cycles=300, envelope_source="ledger").verdict == g.FAIL
    assert g.judge_lab(months("55"), {}, planned=3, cycles=300, envelope_source="ledger").verdict == g.PASS


def test_more_excluded_days_than_planned_fails() -> None:
    excluded = {date(2032, 9, 20): ["budget_stop:allocation_spent"], date(2032, 9, 21): ["paused:ma-v1:invalid_over_3pct"]}
    assert g.judge_lab(months(), excluded, planned=1, cycles=300, envelope_source="ledger").verdict == g.FAIL
    assert g.judge_lab(months(), excluded, planned=2, cycles=300, envelope_source="ledger").verdict == g.PASS


def test_without_orchestrate_cycles_the_excluded_days_cannot_be_read() -> None:
    assert g.judge_lab(months(), {}, planned=2, cycles=0, envelope_source="ledger").verdict == g.PENDING_TIME


def test_a_day_with_any_stop_or_pause_is_excluded_once() -> None:
    d1, d2 = date(2032, 9, 20), date(2032, 9, 21)
    got = g.excluded_days([(d1, {"budget_stop": "insufficient", "paused": []}), (d1, {"budget_stop": "insufficient"}),
                           (d2, {"budget_stop": None, "paused": ["cs-v1:circuit_open"]}), (date(2032, 9, 22), {"budget_stop": None})])
    assert got == {d1: ["budget_stop:insufficient"], d2: ["paused:cs-v1:circuit_open"]}


# ── 5. attribution ───────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("settled", "attributed", "want"), [(100, 95, g.PASS), (100, 94, g.FAIL), (0, 0, g.PENDING_TIME), (20, 20, g.PASS)])
def test_attribution(settled: int, attributed: int, want: str) -> None:
    assert g.judge_attribution(settled, attributed, [7]).verdict == want


# ── 6. the leak audit ────────────────────────────────────────────────────────────────────────────────────────────

DAYS = [date(2032, 9, 20), date(2032, 9, 21)]


def clean(day: date, *, shadow_n: int = 4) -> list[tuple[date, str, str, int, int]]:
    return [(day, r, "leak-audit-v8", shadow_n if r == "shadow_review_known" else 10, 0) for r in g.AUDIT_RULES]


def test_every_night_clean_with_shadow_reviews_seen_passes() -> None:
    assert g.judge_audit(DAYS, clean(DAYS[0]) + clean(DAYS[1])).verdict == g.PASS


def test_a_violation_fails() -> None:
    rows = clean(DAYS[0]) + [(DAYS[1], r, "v8", 10, 1 if r == "agent_known" else 0) for r in g.AUDIT_RULES]
    c = g.judge_audit(DAYS, rows)
    assert c.verdict == g.FAIL and c.detail["violations"] == ["2032-09-21 agent_known"]


def test_a_night_whose_shadow_review_known_read_nothing_fails() -> None:
    c = g.judge_audit(DAYS, clean(DAYS[0]) + clean(DAYS[1], shadow_n=0))
    assert c.verdict == g.FAIL and c.detail["shadow_review_known_empty"] == ["2032-09-21 shadow_review_known"]


def test_a_night_not_audited_is_pending_by_manual_action() -> None:
    c = g.judge_audit(DAYS, clean(DAYS[0]))
    assert c.verdict == g.PENDING_ACTIONS and len(c.detail["not_audited"]) == 4


def test_the_newest_row_of_a_night_decides_and_an_earlier_dirty_one_is_reported() -> None:
    newest_first = [(DAYS[0], "slice_known", "v8", 10, 0), (DAYS[0], "slice_known", "v8", 10, 2)]
    rows = newest_first + [r for r in clean(DAYS[0]) if r[1] != "slice_known"] + clean(DAYS[1])
    c = g.judge_audit(DAYS, rows)
    assert c.verdict == g.PASS and c.detail["superseded_with_violations"][0]["violations"] == 2


# ── 7. the battery ───────────────────────────────────────────────────────────────────────────────────────────────

def battery(*, passed: bool = True, at: datetime = SINCE + timedelta(days=2), targets: dict[str, dict[str, str]] | None = None) -> g.BatteryRow:
    t = targets if targets is not None else {"review": {"prompt": "review-v2"}, "match": {"prompt": "match-assess-v2"},
                                             "council": {"prompt": "council-v1"}}
    return g.BatteryRow(4, at, passed, {"battery": "battery-v3", "targets": t})


RUNNING = {"match": ["match-context-v1", "match-assess-v2"], "council": ["council-v1", "council-opus-v1"]}


def test_a_fresh_green_battery_covering_every_agent_passes() -> None:
    c = g.judge_battery(battery(), since=SINCE, running=RUNNING, stale=[])
    assert c.verdict == g.PASS and c.detail["covered_by"] == {"match": ["match"], "council": ["council"]}


def test_an_agent_without_a_target_fails_by_name() -> None:
    c = g.judge_battery(battery(), since=SINCE, running=RUNNING | {"stats": ["stats-v2"]}, stale=[])
    assert c.verdict == g.FAIL and "battery does not cover stats" in c.reasons


def test_a_target_whose_prompt_the_agent_ran_with_covers_it() -> None:
    row = battery(targets={"assess": {"prompt": "match-assess-v2"}, "cd": {"agent": "council", "prompt": "x"}})
    assert g.judge_battery(row, since=SINCE, running=RUNNING, stale=[]).verdict == g.PASS


@pytest.mark.parametrize(("row", "stale", "want"), [
    (None, [], g.PENDING_ACTIONS),
    ("failed", [], g.FAIL),
    ("old", [], g.PENDING_ACTIONS),
    ("ok", ["the cases or the bases are not the ones that were measured"], g.PENDING_ACTIONS),
])
def test_battery_paths(row: str | None, stale: list[str], want: str) -> None:
    rows = {None: None, "failed": battery(passed=False), "old": battery(at=SINCE - timedelta(days=1)), "ok": battery()}
    assert g.judge_battery(rows[row], since=SINCE, running=RUNNING, stale=stale).verdict == want


def test_no_agent_that_ran_is_pending_by_time() -> None:
    assert g.judge_battery(battery(), since=SINCE, running={}, stale=[]).verdict == g.PENDING_TIME


# ── 8. research v2 ───────────────────────────────────────────────────────────────────────────────────────────────

def test_research_v2() -> None:
    assert g.judge_research(None).verdict == g.PENDING_TIME
    evidence = {"checks": [{"id": "coverage", "detail": {"coverage_pct": "96.40"}}]}
    c = g.judge_research({"id": 9, "at": NOW, "passed": True, "evidence": evidence})
    assert c.verdict == g.PASS and c.detail["row"]["coverage_pct"] == "96.40"
    assert g.judge_research({"id": 10, "at": NOW, "passed": False, "evidence": {}}).verdict == g.FAIL


# ── the report ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_report_says_it_is_not_recorded_and_lists_what_fails() -> None:
    w = g.window_from(today=TODAY, through=None, first_shadow=date(2032, 9, 1), events=[])
    r = g.GateReport(g.FAIL, NOW, w, (g.judge_duplicates(10, [("a" * 64, 2, [1, 2])]),))
    doc = r.as_json()
    assert doc["method"] == "gate-b-v1" and doc["recorded"] is False and doc["failing_now"] == ["duplicate_payments"]
    assert r.lines()[0] == "GATE B · NO PASA"


def test_the_script_exits_0_on_a_pass_1_on_a_failure_and_3_on_either_pending() -> None:
    from scripts import ia_gate_b

    assert [ia_gate_b.exit_code(v) for v in (g.PASS, g.FAIL, g.PENDING_TIME, g.PENDING_ACTIONS)] == [0, 1, 3, 3]
    assert ia_gate_b.build_parser().parse_args(["evaluate", "--changed-on", "2032-09-20", "--json"]).changed_on == ["2032-09-20"]


def test_battery_v3_target_covers_an_agent_by_any_of_its_prompts() -> None:
    """battery-v3 names a multi-prompt target by its joined prompts and lists each one in ``prompts``: any of them covers the agent."""
    targets = {"council-target": {"prompt": "council-v1+council-opus-v1", "agent": "council-v1",
                                  "prompts": ["council-v1", "council-opus-v1"]}}
    assert g.covered_by("council", ["council-opus-v1"], targets) == ["council-target"]
    assert g.covered_by("stats", ["stats-assess-v2"], targets) == []
