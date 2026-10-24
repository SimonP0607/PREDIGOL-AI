"""The steps another package asks the intelligence jobs to run (plan F11): spliced in after the step they name, never in silence, and added by
the worker - the only place that knows both sides - only while the families' switch is not ``off``.

The families sit above ``fbi.intel`` (they import its decision layer); if ``fbi.intel.cycle`` imported them, the import cycle of the code would
grow past the number ``tests/unit/test_architecture.py`` holds. So the cycle takes the steps it is handed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.familydecisions import decide as fd
from fbi.familydecisions import outcomes as fo
from fbi.intel import cycle
from fbi.intel.cycle import Step, with_extra


def _step(name: str) -> Step:
    return (name, lambda: name)


def names(steps: list[Step]) -> list[str]:
    return [n for n, _ in steps]


def test_without_extra_steps_a_job_is_exactly_what_it_was() -> None:
    steps = [_step("decide"), _step("select")]
    assert with_extra(steps, None) is steps
    assert with_extra(steps, {}) is steps


def test_an_extra_step_runs_right_after_the_one_it_names() -> None:
    steps = [_step("a"), _step("b"), _step("c")]
    assert names(with_extra(steps, {"b": [_step("x")]})) == ["a", "b", "x", "c"]
    assert names(with_extra(steps, {"c": [_step("x")]})) == ["a", "b", "c", "x"], "after the last one is after the last one"
    assert names(with_extra(steps, {"a": [_step("x")], "c": [_step("y")]})) == ["a", "x", "b", "c", "y"]


def test_the_extra_steps_of_one_step_keep_the_order_they_were_given() -> None:
    steps = [_step("a"), _step("b")]
    assert names(with_extra(steps, {"a": [_step("x"), _step("y"), _step("z")]})) == ["a", "x", "y", "z", "b"]


def test_the_jobs_own_steps_and_what_they_do_are_untouched() -> None:
    mine = _step("a")
    out = with_extra([mine, _step("b")], {"a": [_step("x")]})
    assert out[0][0] == "a" and out[0][1] is mine[1] and out[0][1]() == "a" and out[1][1]() == "x"


def test_a_step_asked_to_run_after_one_that_does_not_exist_is_an_error_not_a_silence() -> None:
    with pytest.raises(ValueError, match=r"\['nope'\].*not steps of this job"):
        with_extra([_step("a"), _step("b")], {"nope": [_step("x")], "a": [_step("y")]})


def test_both_jobs_accept_the_steps_and_the_names_the_worker_uses_are_steps_of_theirs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building a job touches nothing (its steps are closures): ``_run`` is taken out to read the steps the job would run."""
    import inspect

    ran: dict[str, list[Step]] = {}
    monkeypatch.setattr(cycle, "_run", lambda conn, job, at, steps: ran.setdefault(job, steps) and None)
    at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    for job in (cycle.run_decide, cycle.run_nightly):
        assert inspect.signature(job).parameters["after"].default is None, "a job that is handed nothing runs what it always ran"

    cycle.run_decide(Conn(), at=at)  # type: ignore[arg-type]
    cycle.run_nightly(Conn(), at=at)  # type: ignore[arg-type]
    assert names(ran["decide"]) == ["decide", "select"]
    assert names(ran["nightly"]) == ["outcomes", "postmortems", "memory", "calibration", "leakage_audit", "hypotheses", "report"]

    ran.clear()
    cycle.run_decide(Conn(), at=at, after={"select": [_step("families")]})  # type: ignore[arg-type]
    cycle.run_nightly(Conn(), at=at, after={"outcomes": [_step("family_outcomes")]})  # type: ignore[arg-type]
    assert names(ran["decide"]) == ["decide", "select", "families"]
    assert names(ran["nightly"])[:3] == ["outcomes", "family_outcomes", "postmortems"]

    with pytest.raises(ValueError, match="not steps of this job"):
        cycle.run_decide(Conn(), at=at, after={"outcomes": [_step("x")]})  # type: ignore[arg-type]


class Conn:
    """The steps keep the connection they are handed and use it only when they run: building them touches nothing."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"building the steps used the connection ({name})")


def _switch(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(fd, "environment", lambda: {} if value is None else {fd.SWITCH: value})


@pytest.mark.parametrize("value", [None, "off", "", "OFF", "on", "true", "1", "live", "production"])
def test_with_the_switch_off_the_worker_hands_over_nothing(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    _switch(monkeypatch, value)
    at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    assert scheduler.family_decide_steps(Conn(), at) == {}  # type: ignore[arg-type]
    assert scheduler.family_nightly_steps(Conn(), at) == {}  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["shadow", "SHADOW", " shadow "])
def test_in_shadow_the_decision_follows_the_picks_of_the_day_and_the_settlement_follows_the_outcomes(
        monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    _switch(monkeypatch, value)
    at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    decide = scheduler.family_decide_steps(Conn(), at)  # type: ignore[arg-type]
    nightly = scheduler.family_nightly_steps(Conn(), at)  # type: ignore[arg-type]
    assert {k: names(list(v)) for k, v in decide.items()} == {"select": ["families"]}, (
        "after the choice of the picks of the day, so that it cannot delay it")
    assert {k: names(list(v)) for k, v in nightly.items()} == {"outcomes": ["family_outcomes"]}
    # and the job accepts exactly those names
    assert names(with_extra([_step("decide"), _step("select")], decide)) == ["decide", "select", "families"]


def test_the_steps_call_the_families_with_the_connection_and_the_moment_of_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _switch(monkeypatch, "shadow")
    seen: list[tuple[str, object, object]] = []
    def fake(name: str) -> Any:
        def run(conn: object, *, at: object) -> dict[str, str]:
            seen.append((name, conn, at))
            return {"mode": "shadow"}

        return run

    monkeypatch.setattr(fd, "run_step", fake("decide"))
    monkeypatch.setattr(fo, "run_step", fake("outcomes"))
    conn, at = object(), datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    d = scheduler.family_decide_steps(conn, at)  # type: ignore[arg-type]
    n = scheduler.family_nightly_steps(conn, at)  # type: ignore[arg-type]
    assert d["select"][0][1]() == {"mode": "shadow"} and n["outcomes"][0][1]() == {"mode": "shadow"}
    assert seen == [("decide", conn, at), ("outcomes", conn, at)]


def test_the_record_of_a_run_names_the_versions_of_the_families() -> None:
    from fbi.core import decision_versions as dv

    v = cycle.versions()
    assert v["decision"] == dv.DECISION_CORE and v["outcome"] == dv.OUTCOME_CORE
    assert v["decision_families"] == dv.DECISION_FAMILIES == fd.VERSION
    assert v["outcome_families"] == dv.OUTCOME_FAMILIES == fo.VERSION
