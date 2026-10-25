"""The command lines of the LAB (``scripts/ia_probe.py``, ``scripts/ia_equivalence.py``): what the owner runs where the worker runs.

They are thin - the experiments themselves are tested in ``test_lab.py`` - so what is checked here is what a command line must keep: a
missing key or envelope is a clear refusal that names variables and owner actions and sends nothing; a key is never printed; each
command's exit status tells a script whether the probe passed, did not, could not run or is still waiting; and the commands do what
their guide says, in the order it says (submit, wait, collect).

No network and no key: the provider is a mock transport or ``FakeBatches``. One transaction, rolled back."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import lab

from .test_lab import AT, SONNET, Api, Lab, NoCalls, cfg
from .test_lab import box as box  # the LAB, its ledger and its scripted model

KEY = "sk-test-lab-key"


def probe(box: Lab, command: str, settings: Any = None, **kw: Any) -> tuple[dict[str, Any], int]:
    from scripts import ia_probe

    kw.setdefault("tiers", ["bulk", "analysis"])
    kw.setdefault("at", AT)
    kw.setdefault("client", box.fake)
    return ia_probe.run(command, box.conn, settings or cfg(), ledger=box.ledger, **kw)


def equivalence(box: Lab, command: str, settings: Any = None, **kw: Any) -> tuple[dict[str, Any], int]:
    from scripts import ia_equivalence

    kw.setdefault("tier", "analysis")
    kw.setdefault("at", AT)
    return ia_equivalence.run(command, box.conn, settings or cfg(), ledger=box.ledger, client=box.fake, **kw)


def silent(report: dict[str, Any]) -> None:
    assert KEY not in json.dumps(report, default=str) and "sk-test-production-key" not in json.dumps(report, default=str), \
        "a report never carries a key"


# ── ia_probe ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_status_says_what_is_missing_by_name_and_sends_nothing(box: Lab) -> None:
    report, code = probe(box, "status", cfg(lab_keys={}, lab_monthly_budget=Decimal(0)))
    assert code == 2 and report["lab_key"] is False
    text = " ".join(report["blockers"])
    assert "FBI_AI_KEY_ANTHROPIC_LAB" in text and "FBI_AI_LAB_MONTHLY_BUDGET_USD" in text
    assert "owner actions 5 and 7" in text and "owner action 7" in text, "the owner is told which actions unblock it"
    assert set(report["optimisations"]["gates"]) == {"batch", "native_schema", "cache_layout", "gate_a"}
    silent(report)


def test_status_with_a_key_and_an_envelope_is_clean_and_shows_the_lab_month(box: Lab) -> None:
    report, code = probe(box, "status")
    assert code == 0 and report["blockers"] == [] and report["lab_key"] is True
    assert report["lab_envelope_usd"] == "15" and report["lab_tiers"] == {"bulk": "claude-haiku-5-5", "analysis": SONNET}
    assert report["lab_month"]["can_spend"] is True and Decimal(report["lab_month"]["remaining_usd"]) > 0
    assert Decimal(report["lab_month"]["allocation_usd"]) == 15 and Decimal(report["lab_month"]["spent_month_usd"]) == 0
    assert report["optimisations"]["batch"]["on"] is False and "waiting" in report["optimisations"]["batch"]["why"]
    silent(report)


def test_without_the_key_no_probe_calls_anything(box: Lab) -> None:
    for command in ("cache", "schema"):
        report, code = probe(box, command, cfg(lab_keys={}), transport=NoCalls())
        assert code == 2 and "FBI_AI_KEY_ANTHROPIC_LAB" in " ".join(report["blockers"]), command
    report, code = probe(box, "batch-submit", cfg(lab_keys={}))
    assert code == 2 and report["submitted"] == 0
    assert box.one("SELECT count(*) FROM ai.usage") == 0 and box.one("SELECT count(*) FROM ai.batch_items") == 0


def test_the_cache_probe_exits_ok_when_the_cache_reads_and_not_when_it_does_not(box: Lab) -> None:
    api = Api()
    report, code = probe(box, "cache", transport=api.transport())
    assert code == 0 and report["ok"] is True and set(api.keys) == {KEY}
    silent(report)
    report, code = probe(box, "cache", transport=Api(cache=False).transport(), at=AT + timedelta(minutes=30))
    assert code == 1 and report["ok"] is False, "a cache that does not read is an answer, not a failure to run"


def test_the_schema_probe_exits_by_what_the_model_answered(box: Lab) -> None:
    report, code = probe(box, "schema", transport=Api().transport())
    assert code == 0 and report["ok"] is True
    report, code = probe(box, "schema", transport=Api(native_word="delta").transport(), at=AT + timedelta(minutes=30))
    assert code == 1 and report["tiers"]["analysis"]["native"]["valid"] is False


def test_the_batch_probe_is_sent_waited_for_and_collected(box: Lab) -> None:
    sent, code = probe(box, "batch-submit")
    assert code == 0 and sent["run"] == AT.date().isoformat() and sent["states"] == {"queued": 6} and sent["sent"] == 6
    again, code = probe(box, "batch-submit", at=AT + timedelta(minutes=5))
    assert code == 0 and again["states"] == {"in_flight": 6} and again["sent"] == 0 and len(box.fake.created) == 1, \
        "the same day finds what is already sent"
    waiting, code = probe(box, "batch-collect", at=AT + timedelta(minutes=10))
    assert code == 3 and waiting["state"] == "waiting" and waiting["open"] == 6
    assert box.gate_rows("batch") == [], "nothing is decided while results are on their way"
    box.end()
    shown, code = probe(box, "batch-collect", at=AT + timedelta(hours=1), record=False)
    assert code == 0 and shown["passed"] is True and "gate_id" not in shown and box.gate_rows("batch") == []
    done, code = probe(box, "batch-collect", at=AT + timedelta(hours=1))
    assert code == 0 and done["passed"] is True and done["gate_id"] is not None
    assert sorted(done["models"]) == ["claude-haiku-5-5", SONNET]
    ((passed, evidence),) = box.gate_rows("batch")
    assert passed and sorted(evidence["models"]) == ["claude-haiku-5-5", SONNET]
    silent(done)


def test_collecting_before_anything_was_sent_says_so(box: Lab) -> None:
    report, code = probe(box, "batch-collect")
    assert code == 2 and "run batch-submit first" in " ".join(report["blockers"])


def test_the_tiers_option_takes_names_and_refuses_the_rest() -> None:
    from scripts import ia_probe

    assert ia_probe.parse_tiers("bulk, analysis,bulk") == ["bulk", "analysis"]
    assert ia_probe.parse_tiers("final") == ["final"]
    for bad in ("", " , ", "haiku", "bulk,sonnet"):
        with pytest.raises(ValueError):
            ia_probe.parse_tiers(bad)
    args = ia_probe.build_parser().parse_args(["batch-collect", "--run", "2026-10-26", "--no-record", "--tiers", "bulk"])
    assert args.run == "2026-10-26" and args.no_record is True and args.tiers == "bulk" and args.dsn is None


# ── ia_equivalence ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_plan_of_the_experiment_asks_for_what_the_plan_asks_for(box: Lab) -> None:
    box.stored(4)
    report, code = equivalence(box, "plan")
    assert code == 2 and report["inputs"] == 12 and report["submitted"] == 0
    assert f"{lab.MIN_INPUTS} are needed" in " ".join(report["blockers"]), "twelve stored reviews are not two hundred"
    assert box.one("SELECT count(*) FROM ai.batch_items") == 0 and box.fake.created == []


def test_the_whole_experiment_at_the_plan_size_from_plan_to_gates(box: Lab) -> None:
    box.stored(70)
    box.see_the_probes()
    planned, code = equivalence(box, "plan")
    assert code == 0 and planned["dry_run"] is True and planned["inputs"] == 210 and planned["asks"] == 840
    assert 5 < Decimal(planned["estimate_usd"]) < Decimal(planned["lab_remaining_usd"]), "it fits the LAB's envelope"
    assert box.one("SELECT count(*) FROM ai.batch_items") == 0 and box.fake.created == [], "a plan sends and reserves nothing"
    sent, code = equivalence(box, "submit")
    assert code == 0 and sent["submitted"] == 840 and sent["states"] == {"queued": 840}
    assert [len(b) for b in box.fake.created] == [840], "one batch"
    status, code = equivalence(box, "status")
    assert code == 0 and status["experiment"] == sent["experiment"] and status["asks_by_state"] == {"submitted": 840}
    waiting, code = equivalence(box, "collect", at=AT + timedelta(minutes=10))
    assert code == 3 and waiting["state"] == "waiting" and waiting["open"] == 840
    assert box.gate_rows("native_schema") == [] and box.gate_rows("cache_layout") == []
    box.end()
    shown, code = equivalence(box, "collect", at=AT + timedelta(hours=2), record=False)
    assert code == 0 and {v["verdict"] for v in shown["variants"].values()} == {"PASA"}
    assert box.gate_rows("native_schema") == [] and box.gate_rows("cache_layout") == [], "--no-record writes no gate"
    done, code = equivalence(box, "collect", at=AT + timedelta(hours=2))
    assert code == 0 and {v["verdict"] for v in done["variants"].values()} == {"PASA"}
    assert [p for p, _ in box.gate_rows("native_schema")] == [True] and [p for p, _ in box.gate_rows("cache_layout")] == [True]
    final, code = equivalence(box, "status", at=AT + timedelta(hours=3))
    assert final["asks_by_state"] == {"succeeded": 840} and final["gates"]["native_schema"]["passed"] is True
    silent(done)


def test_a_variant_that_changes_more_than_a_repeat_exits_with_no(box: Lab) -> None:
    box.stored(70)
    box.see_the_probes()
    box.panel.native |= set(range(0, 210, 3))  # structured outputs downgrade one input in three; a repeat changes none
    sent, code = equivalence(box, "submit")
    assert code == 0 and sent["submitted"] == 840
    box.end()
    done, code = equivalence(box, "collect", at=AT + timedelta(hours=2))
    assert code == 1, "one variant not passing is not a pass"
    assert done["variants"]["native_schema"]["verdict"] == "NO PASA" and done["variants"]["shared_layout"]["verdict"] == "PASA"
    assert [p for p, _ in box.gate_rows("native_schema")] == [False] and [p for p, _ in box.gate_rows("cache_layout")] == [True]


def test_without_the_key_the_experiment_is_refused_by_name(box: Lab) -> None:
    box.stored(70)
    for command in ("plan", "submit"):
        report, code = equivalence(box, command, cfg(lab_keys={}))
        assert code == 2 and "FBI_AI_KEY_ANTHROPIC_LAB" in " ".join(report["blockers"]), command
    assert box.one("SELECT count(*) FROM ai.batch_items") == 0 and box.fake.created == []


def test_collecting_before_anything_was_sent_says_so_for_the_experiment_too(box: Lab) -> None:
    report, code = equivalence(box, "collect")
    assert code == 2 and "run submit first" in " ".join(report["blockers"])
    status, code = equivalence(box, "status")
    assert code == 0 and status["experiment"] is None and status["asks_by_state"] == {}


def test_the_option_of_the_inputs_cannot_go_below_the_plans_bar() -> None:
    from scripts import ia_equivalence

    with pytest.raises(SystemExit) as stop:
        ia_equivalence.main(["plan", "--inputs", "50"])
    assert stop.value.code == 2
    args = ia_equivalence.build_parser().parse_args(["collect", "--experiment", "x", "--no-record", "--tier", "final"])
    assert args.experiment == "x" and args.no_record is True and args.tier == "final"
    assert ia_equivalence.build_parser().parse_args(["submit"]).inputs == lab.MIN_INPUTS + 10


# ── the commands as the owner runs them ─────────────────────────────────────────────────────────────────────────

def test_main_reads_the_environment_prints_json_and_never_a_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import os

    from scripts import ia_probe

    monkeypatch.setenv("FBI_AI_KEY_ANTHROPIC_LAB", "sk-test-environment-key")
    monkeypatch.setenv("FBI_AI_LAB_MONTHLY_BUDGET_USD", "15")
    monkeypatch.setenv("FBI_AI_KEY_ANTHROPIC", "sk-test-production-env-key")
    dsn = os.environ["FBI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    code = ia_probe.main(["status", "--dsn", dsn])
    out = capsys.readouterr().out
    report = json.loads(out)
    assert code in (0, 2) and report["lab_key"] is True and report["lab_envelope_usd"] == "15"
    assert "sk-test" not in out, "the commands print names, never values"
