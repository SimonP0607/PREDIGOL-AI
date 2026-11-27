"""RP-8.3 on a real database: an experiment is due only when its condition is met (never before its sample, never twice for a decided verdict), runs outside the
worker through the launcher's gate, and leaves its verdict only on a protocol registered before the result. Counters and runners are injected; nothing here measures a model."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from scripts import exp_run

from fbi.research import exp_conditions as ec
from fbi.research import exp_protocol, launcher, verdicts
from fbi.research.protocol import fingerprint

pytestmark = pytest.mark.integration

NOW = datetime(2026, 12, 20, 12, tzinfo=UTC)
E1 = exp_protocol.EXPERIMENTS["EXP-E1"]
CODE = "model-code-A"


class Box:
    """A counter and a runner the test controls."""

    def __init__(self, sample: int = 0, verdict: str = "exito") -> None:
        self.sample, self.verdict, self.calls = sample, verdict, 0

    def count(self, conn: psycopg.Connection[Any], since: date) -> int:
        assert since == ec.SIGNED_ON, "the sample is counted from the signature of the protocol"
        return self.sample

    def run(self, conn: psycopg.Connection[Any], at: datetime) -> tuple[exp_protocol.Judgement, dict[str, Any]]:
        self.calls += 1
        if self.verdict == "insuficiente":
            return exp_protocol.Judgement("insuficiente", "el intervalo aún admite las dos respuestas", 0.001, -0.004, 0.006, self.sample), {"matches": self.sample}
        return exp_protocol.Judgement("exito", "por debajo del umbral, con intervalo y mismo signo en las dos mitades", -0.002, -0.005, 0.001, self.sample), {"matches": self.sample}


@pytest.fixture()
def box() -> Iterator[Box]:
    b = Box()
    ec.register("EXP-E1", count=b.count, run=b.run)
    yield b
    for key in ("EXP-E1", "EXP-E3", "EXP-E6", "EXP-E7"):  # the launcher's gate registers the plugins it finds: leave nothing behind
        ec.unregister(key)


def put(db: psycopg.Connection[Any], *, verdict: str, n: int, at: datetime, code: str = CODE, fp: str | None = None) -> None:
    mean = {"mean": -0.002, "low": -0.005, "high": 0.001} if verdict != "insuficiente" else {"mean": None, "low": None, "high": None}
    db.execute("INSERT INTO analytics.experiment_verdicts (experiment, protocol_version, protocol_fingerprint, verdict, reason, n, mean, low, high, population, computed_at, "
               "recorded_by) VALUES ('EXP-E1', %s, %s, %s, 'un motivo suficientemente largo', %s, %s, %s, %s, %s::jsonb, %s, 'system')",
               (E1.version, fp or fingerprint(E1), verdict, n, mean["mean"], mean["low"], mean["high"], f'{{"model_code": "{code}"}}', at))


def test_an_experiment_with_no_counter_is_never_launched(db: psycopg.Connection[Any]) -> None:
    d = ec.check(db, "EXP-E1", at=NOW, model_code=CODE)
    assert (d.due, d.code) == (False, "no_counter")
    assert ec.check(db, "EXP-E9", at=NOW).code == "unknown"


def test_before_its_sample_nothing_is_due_and_nothing_is_computed(db: psycopg.Connection[Any], box: Box) -> None:
    box.sample = 999
    d = ec.check(db, "EXP-E1", at=NOW, model_code=CODE)
    assert (d.due, d.code, d.sample, d.required) == (False, "sample", 999, 1000)
    with pytest.raises(exp_protocol.ProtocolRefusedError, match="no toca"):
        ec.run(db, "EXP-E1", at=NOW, model_code=CODE)
    assert box.calls == 0 and verdicts.latest(db) == []


def test_at_the_sample_it_is_due_runs_once_and_writes_a_verdict_with_what_it_stood_on(db: psycopg.Connection[Any], box: Box) -> None:
    box.sample = 1000
    d = ec.check(db, "EXP-E1", at=NOW, model_code=CODE)
    assert (d.due, d.code) == (True, "sample_reached")
    v = ec.run(db, "EXP-E1", at=NOW, model_code=CODE)
    assert (v.experiment, v.verdict, v.n) == ("EXP-E1", "exito", 1000) and v.protocol_fingerprint == fingerprint(E1)
    assert v.population["model_code"] == CODE and v.population["sample"] == 1000 and v.population["trigger"] == "sample_reached"
    again = ec.check(db, "EXP-E1", at=NOW + timedelta(days=60), model_code="another")
    assert (again.due, again.code) == (False, "decided"), "a verdict of success on this protocol is final"


def test_an_insufficient_verdict_is_looked_at_again_only_on_a_new_model_code_or_four_weeks_with_more_matches(db: psycopg.Connection[Any], box: Box) -> None:
    box.sample = 1200
    put(db, verdict="insuficiente", n=1200, at=NOW)
    soon = ec.check(db, "EXP-E1", at=NOW + timedelta(days=3), model_code=CODE)
    assert (soon.due, soon.code) == (False, "waiting")
    assert ec.check(db, "EXP-E1", at=NOW + timedelta(days=3), model_code="model-code-B").code == "model_code_changed"
    assert ec.check(db, "EXP-E1", at=NOW + timedelta(days=29), model_code=CODE).code == "waiting", "four weeks without more matches is not a reason"
    box.sample = 1500
    assert ec.check(db, "EXP-E1", at=NOW + timedelta(days=29), model_code=CODE).code == "four_weeks"


def test_an_attempt_that_was_short_of_sample_is_due_when_the_sample_arrives(db: psycopg.Connection[Any], box: Box) -> None:
    put(db, verdict="insuficiente", n=40, at=NOW - timedelta(days=2))
    box.sample = 1000
    assert ec.check(db, "EXP-E1", at=NOW, model_code=CODE).code == "sample_reached"


def test_a_new_version_of_the_protocol_makes_a_decided_experiment_due_again(db: psycopg.Connection[Any], box: Box) -> None:
    put(db, verdict="abandono", n=1100, at=NOW - timedelta(days=5), fp="a" * 64)
    box.sample = 1100
    assert ec.check(db, "EXP-E1", at=NOW, model_code=CODE).code == "new_protocol"


def test_the_survey_lists_every_experiment_and_only_those_with_a_runner_are_launched(db: psycopg.Connection[Any], box: Box) -> None:
    box.sample = 1000
    ec.register("EXP-E3", count=lambda c, s: 1500, run=None)
    try:
        states = {d.experiment: d for d in ec.survey(db, at=NOW, model_code=CODE)}
        assert list(states) == list(exp_protocol.EXPERIMENTS)
        assert states["EXP-E1"].due and states["EXP-E3"].due, "both reached their sample"
        assert [d.experiment for d in ec.due_now(db, at=NOW, model_code=CODE)] == ["EXP-E1"], "E3 has no runner yet: it is reported, not launched"
        with pytest.raises(ec.NotRegisteredError):
            ec.run(db, "EXP-E3", at=NOW, model_code=CODE)
    finally:
        ec.unregister("EXP-E3")


def test_the_launcher_gate_says_no_experiment_is_due_or_lets_it_through(db: psycopg.Connection[Any], box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fbi.research.loop.frozen", lambda: None)
    job = launcher.JOBS["experiments_due"]
    assert job.gate == "experiments_due" and job.argv == ("-m", "scripts.exp_run", "--due")
    assert launcher.experiments_gate(db, NOW, job) == "no experiment of the plan is due"
    box.sample = 1000
    assert launcher.experiments_gate(db, NOW, job) is None
    monkeypatch.setattr("fbi.research.loop.frozen", lambda: "audit in progress")
    assert "frozen" in (launcher.experiments_gate(db, NOW, job) or "")


def test_a_result_computed_before_the_protocol_was_signed_is_refused_even_if_it_is_due(db: psycopg.Connection[Any], box: Box) -> None:
    box.sample = 1000
    with pytest.raises(exp_protocol.ProtocolRefusedError, match="anterior a la firma"):
        ec.run(db, "EXP-E1", at=datetime(2026, 11, 1, tzinfo=UTC), model_code=CODE)
    assert verdicts.latest(db) == []


def test_the_status_command_lists_each_experiment_with_why(db: psycopg.Connection[Any], box: Box) -> None:
    box.sample = 400
    text = "\n".join(exp_run.status_lines(ec.survey(db, at=NOW, model_code=CODE)))
    assert "EXP-E1" in text and "muestra 400/1000" in text and "EXP-E8" in text and "no_counter" in text


def test_the_launcher_gate_finds_the_plugins_by_itself_and_none_of_them_is_due_before_its_sample(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fbi.research.loop.frozen", lambda: None)
    try:
        assert set(ec.registered()) == set()
        assert launcher.experiments_gate(db, NOW, launcher.JOBS["experiments_due"]) == "no experiment of the plan is due"
        assert set(ec.registered()) == {"EXP-E1", "EXP-E3", "EXP-E6", "EXP-E7"}, "the gate registered what the plan's pieces say about themselves"
    finally:
        for key in ("EXP-E1", "EXP-E3", "EXP-E6", "EXP-E7"):
            ec.unregister(key)
