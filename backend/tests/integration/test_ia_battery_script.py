"""The command line of the battery (``scripts/ia_battery.py``) against the database: what the owner runs where the worker runs.

The rounds themselves are tested in ``test_battery_run.py``; what is checked here is what a command line must keep: a missing key or
envelope is a clear refusal that names variables and sends nothing; a key is never printed; each command's exit status tells a script
whether the battery passed, did not, could not run or is still waiting; and the commands do what their guide says, in the order it says
(offline, plan, submit, wait, collect, status).

No network and no key: the provider is ``FakeBatches`` with a scripted model. One transaction, rolled back."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from scripts import ia_battery

from fbi.ai.battery import TARGETS, run
from tests.unit.battery_model import Obeys

from .conftest import TEST_DB, _dsn
from .test_battery_run import LATER, Rig
from .test_battery_run import rig as rig
from .test_lab import AT, cfg

KEYS = ("sk-test-lab-key", "sk-test-production-key")


def command(rig: Rig, name: str, settings: Any = None, **kw: Any) -> tuple[dict[str, Any], int]:
    kw.setdefault("targets", list(TARGETS))
    kw.setdefault("at", AT)
    return ia_battery.execute(name, rig.conn, settings or cfg(), ledger=rig.ledger, client=rig.fake, **kw)


def silent(report: dict[str, Any]) -> None:
    text = json.dumps(report, default=str)
    assert not any(k in text for k in KEYS), "a report never carries a key"


# ── plan and submit ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_plan_is_ok_says_what_a_round_costs_and_sends_nothing(rig: Rig) -> None:
    report, code = command(rig, "plan")
    assert code == ia_battery.OK and report["asks"] == 110 and report["dry_run"] is True and report["submitted"] == 0
    assert Decimal("0.05") < Decimal(report["estimate_usd"]) < Decimal(2) and Decimal(report["lab_remaining_usd"]) == 15
    assert rig.fake.created == [] and rig.one("SELECT count(*) FROM ai.batch_items") == 0
    silent(report)


def test_without_a_lab_key_or_an_envelope_plan_and_submit_exit_two_naming_the_variables_and_send_nothing(rig: Rig) -> None:
    for name in ("plan", "submit"):
        for settings in (cfg(lab_keys={}), cfg(lab_monthly_budget=Decimal(0))):
            report, code = command(rig, name, settings)
            assert code == ia_battery.CANNOT and report["submitted"] == 0, (name, report)
            assert "FBI_AI_KEY_ANTHROPIC_LAB" in " ".join(report["blockers"]) or "FBI_AI_LAB_MONTHLY_BUDGET_USD" in " ".join(report["blockers"])
            silent(report)
    assert rig.fake.created == [] and rig.one("SELECT count(*) FROM ai.batch_items") == 0 and rig.one("SELECT count(*) FROM ai.usage") == 0


def test_a_lab_that_cannot_pay_for_the_round_is_exit_two_and_nothing_is_sent(rig: Rig) -> None:
    report, code = command(rig, "submit", cfg(lab_monthly_budget=Decimal("0.01")))
    assert code == ia_battery.CANNOT and report["submitted"] == 0 and "cannot pay" in report["blockers"][0]
    assert rig.fake.created == []


def test_submit_sends_the_round_once_and_asking_again_is_still_ok_and_pays_nothing(rig: Rig) -> None:
    sent, code = command(rig, "submit")
    assert code == ia_battery.OK and sent["submitted"] == 110 and sent["states"] == {"queued": 110} and len(rig.fake.created) == 1
    silent(sent)
    again, code = command(rig, "submit", at=AT + timedelta(minutes=5))
    assert code == ia_battery.OK and again["nothing_due"] is True and again["submitted"] == 0 and len(rig.fake.created) == 1


def test_a_round_the_provider_would_not_take_is_exit_one_and_can_be_sent_again_whole(rig: Rig) -> None:
    rig.fake.fail_create = "timeout"
    report, code = command(rig, "submit")
    assert code == ia_battery.NO and report["submitted"] == 0 and report["failed"] == 110 and report["error"]
    assert rig.one("SELECT count(*) FROM ai.usage") == 0 and rig.fake.created == []
    rig.fake.fail_create = None
    report, code = command(rig, "submit", at=AT + timedelta(minutes=10))
    assert code == ia_battery.OK and report["submitted"] == 110 and len(rig.fake.created) == 1


# ── collect ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_collecting_before_anything_was_sent_is_exit_two_and_says_to_submit_first(rig: Rig) -> None:
    report, code = command(rig, "collect", at=LATER)
    assert code == ia_battery.CANNOT and report["state"] == "nothing_submitted" and "run submit first" in " ".join(report["blockers"])


def test_asks_still_on_their_way_are_exit_three_and_nothing_is_decided(rig: Rig) -> None:
    command(rig, "submit")
    report, code = command(rig, "collect", at=LATER)
    assert code == ia_battery.WAITING and report["state"] == "waiting" and report["open"] == 110 and "verdict" not in report
    assert rig.gate_rows() == []


def test_a_model_that_nothing_moves_is_exit_zero_and_the_gate_is_written_once(rig: Rig) -> None:
    command(rig, "submit")
    rig.end()
    report, code = command(rig, "collect", at=LATER)
    assert code == ia_battery.OK and report["verdict"] == "PASA" and report["state"] == "ended" and report["gate_id"] is not None
    assert len(rig.gate_rows()) == 1
    silent(report)
    again, code = command(rig, "collect", at=LATER + timedelta(hours=1))
    assert code == ia_battery.OK and again["gate_id"] is None and len(rig.gate_rows()) == 1


def test_no_record_shows_the_verdict_and_writes_nothing(rig: Rig) -> None:
    command(rig, "submit")
    rig.end()
    report, code = command(rig, "collect", at=LATER, record=False)
    assert code == ia_battery.OK and report["verdict"] == "PASA" and "gate_id" not in report and rig.gate_rows() == []


def test_a_suspect_case_is_exit_three_until_it_is_asked_again_and_exit_one_when_it_repeats(rig: Rig) -> None:
    rig.model.rules = (Obeys(("review.ignore.1",), "APPROVE"),)
    command(rig, "submit")
    rig.end()
    waiting, code = command(rig, "collect", at=LATER)
    assert code == ia_battery.WAITING and waiting["state"] == "incomplete" and waiting["verdict"] == "INCOMPLETA"
    assert "submit" in waiting["next"] and rig.gate_rows() == []
    repeat, code = command(rig, "submit", at=LATER)
    assert code == ia_battery.OK and repeat["asks"] == 3 and repeat["submitted"] == 3
    rig.end()
    done, code = command(rig, "collect", at=LATER + timedelta(hours=2))
    assert code == ia_battery.NO and done["verdict"] == "NO PASA" and done["targets"]["review"]["confirmed"] == ["review.ignore.1"]
    ((passed, _evidence),) = rig.gate_rows()
    assert passed is False


def test_one_target_alone_is_collected_but_is_never_the_gate(rig: Rig) -> None:
    command(rig, "submit", targets=["extract"])
    rig.end()
    report, code = command(rig, "collect", at=LATER, targets=["extract"])
    assert code == ia_battery.OK and report["verdict"] == "PASA" and "gate_id" not in report and rig.gate_rows() == []


def test_the_native_route_and_a_suffix_are_other_measurements(rig: Rig) -> None:
    command(rig, "submit")
    command(rig, "submit", native=True)
    command(rig, "submit", suffix="2")
    assert len(rig.fake.created) == 3 and rig.one("SELECT count(*) FROM ai.batch_items") == 330
    rig.end()
    native, code = command(rig, "collect", at=LATER, native=True)
    assert code == ia_battery.OK and native["runs"]["review"] == run.run_id("review", native=True)
    assert rig.gate_rows()[0][1]["native"] is True


# ── status ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_status_only_reads_and_says_when_nothing_has_been_measured(rig: Rig) -> None:
    report, code = command(rig, "status", at=LATER)
    assert code == ia_battery.OK and report["fresh"] is False and report["stale"] == ["no measurement has been recorded"]
    assert report["gate"]["passed"] is False and report["version"] == "battery-v1"
    assert rig.fake.created == [] and rig.one("SELECT count(*) FROM ai.batch_items") == 0


def test_status_after_a_passing_run_says_the_evidence_speaks_for_the_corpus_in_force(rig: Rig) -> None:
    command(rig, "submit")
    rig.end()
    command(rig, "collect", at=LATER)
    report, code = command(rig, "status", at=LATER)
    assert code == ia_battery.OK and report["fresh"] is True and report["stale"] == [] and report["gate"]["passed"] is True
    assert {t: r["asks"] for t, r in report["runs"].items()} == {"review": 55, "extract": 55}
    silent(report)


# ── the command line itself ─────────────────────────────────────────────────────────────────────────────────────────

def test_main_runs_a_command_against_the_database_it_is_given_and_prints_json(
        capsys: pytest.CaptureFixture[str], rig: Rig) -> None:
    code = ia_battery.main(["status", "--dsn", _dsn(TEST_DB)])
    printed = json.loads(capsys.readouterr().out)
    assert code == ia_battery.OK and printed["version"] == "battery-v1" and set(printed["runs"]) == set(TARGETS)
    assert printed["gate"]["gate"] == "battery"


# ── what a command writes, it commits ──────────────────────────────────────────────────────────────────────────────

def test_what_a_command_writes_it_commits_after_writing_it_and_a_status_commits_nothing(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The connection is the caller's but the commit is the command's: a plan that is never committed is lost when the process ends."""
    events: list[str] = []
    real_commit = rig.conn.commit

    def commit() -> None:
        events.append("commit")
        real_commit()

    rig.conn.commit = commit
    for name in ("submit", "collect"):
        real = getattr(run, name)

        def wrapped(*a: Any, _real: Any = real, _name: str = name, **kw: Any) -> Any:
            out = _real(*a, **kw)
            events.append(f"{_name} done")
            return out

        monkeypatch.setattr(run, name, wrapped)
    command(rig, "plan")
    assert events[-2:] == ["submit done", "commit"]
    events.clear()
    command(rig, "submit")
    assert events[-2:] == ["submit done", "commit"]
    events.clear()
    rig.end()
    command(rig, "collect", at=LATER)
    assert events[-2:] == ["collect done", "commit"]
    events.clear()
    command(rig, "status", at=LATER)
    assert events == []


def test_status_of_the_native_route_and_of_a_suffix_speaks_of_those_runs_and_not_of_the_plain_one(rig: Rig) -> None:
    command(rig, "submit", native=True)
    command(rig, "submit", suffix="2", at=AT + timedelta(minutes=5))
    native, code = command(rig, "status", at=LATER, native=True)
    assert code == ia_battery.OK and native["runs"]["review"]["run"] == run.run_id("review", native=True) and native["runs"]["review"]["asks"] == 55
    suffixed, code = command(rig, "status", at=LATER, suffix="2")
    assert code == ia_battery.OK and suffixed["runs"]["extract"]["run"] == run.run_id("extract", suffix="2") and suffixed["runs"]["extract"]["asks"] == 55
    plain, _code = command(rig, "status", at=LATER)
    assert plain["runs"]["review"]["asks"] == 0 and plain["runs"]["extract"]["asks"] == 0
