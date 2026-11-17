"""IA-079 (AD-J08): the Intelligence console, contract C-11. Pure: no database.

* The closed words of the contract are the system's own (the registry's states and verdicts, the panel's statuses, the families' modes).
* Every switch is read with the code's parser and shown as the word it reads as: a raw value never travels, not even a key put by mistake.
* «Nada sale de la sombra» breaks exactly on the Picks board reading Intelligence, the AI's veto in force or a published selection.
* The blocks are made from what the registry, the cost register and the panel of the gates say; a block that fails is a ReadFailure.
* The console is read only: its route is a GET, the Admin Console's AI routes change no switch and its module writes nothing.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import psycopg
import pytest

from fbi.ai import budget_v3, capability_budget, costs_v3, gates_panel
from fbi.ai.config import AiSettings
from fbi.api.contracts.intelligence import console as contract
from fbi.api.contracts.intelligence.base import Freshness, Missing
from fbi.api.contracts.intelligence.vocab import CapabilityState
from fbi.api.services import intelligence_console as svc
from fbi.familydecisions import decide
from fbi.intel import capabilities as registry

AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)
BACKEND = Path(__file__).resolve().parents[2]


def settings(**kw: Any) -> AiSettings:
    base: dict[str, Any] = {"monthly_budget": Decimal(185), "lab_monthly_budget": Decimal(55), "exa_monthly_budget": Decimal(35),
                            "joint_ceiling": Decimal(190)}
    return AiSettings(**(base | kw))


# ── the words are the system's ────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_words_are_the_systems_own() -> None:
    assert get_args(contract.SafetyWord) == registry.SAFETY
    assert get_args(contract.ValidationWord) == registry.VALIDATION
    assert get_args(contract.GateStatus) == gates_panel.STATUSES
    assert svc.FAMILY_MODES == decide.MODES and decide.SWITCH == "FBI_FAMILY_DECISIONS"


def test_each_state_of_the_registry_is_one_of_the_four_of_the_contract() -> None:
    assert tuple(svc.STATE_WORDS) == registry.STATES
    assert tuple(svc.STATE_WORDS.values()) == get_args(CapabilityState)
    with pytest.raises(ValueError, match="unknown capability state"):
        svc.state_word("aprobada")


def test_the_catalogs_switches_are_all_shown() -> None:
    shown = {s.switch for s in svc.SPECS}
    assert {c.switch for c in registry.CATALOG if c.switch} <= shown
    assert {"FBI_PICKS_SOURCE", "FBI_AI_MODE", "FBI_MATCH_INTELLIGENCE"} <= shown


# ── switches: the word they read as, never their value ────────────────────────────────────────────────────────────────────────

def test_a_switch_reads_as_its_parser_says(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FBI_PICKS_SOURCE", "FBI_FAMILY_DECISIONS", "FBI_MATCH_INTELLIGENCE", "FBI_SEARCH"):
        monkeypatch.delenv(name, raising=False)
    words = svc.switch_words(settings(), {})
    assert words["FBI_PICKS_SOURCE"] == "legacy" and words["FBI_AI_MODE"] == "shadow"
    assert words["FBI_FAMILY_DECISIONS"] == "off" and words["FBI_AI_AGENTS"] == "ninguno" and words["FBI_AI_ENGINES"] == "rules,llm"
    assert all(words[s.switch] == s.default for s in svc.SPECS), "with no line, every switch reads as its default"
    monkeypatch.setenv("FBI_PICKS_SOURCE", " Intelligence ")
    monkeypatch.setenv("FBI_MATCH_INTELLIGENCE", "1")
    on = svc.switch_words(settings(mode="enforce", agents=("match", "council"), research_v2="shadow"), {"FBI_FAMILY_DECISIONS": "SHADOW"})
    assert on["FBI_PICKS_SOURCE"] == "intelligence" and on["FBI_AI_MODE"] == "enforce" and on["FBI_FAMILY_DECISIONS"] == "shadow"
    assert on["FBI_AI_AGENTS"] == "match,council" and on["FBI_MATCH_INTELLIGENCE"] == "on"


def test_a_raw_value_never_travels(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-ant-api03-NOT-A-REAL-KEY"
    monkeypatch.setenv("FBI_PICKS_SOURCE", secret)
    monkeypatch.setenv("FBI_SEARCH", secret)
    words = svc.switch_words(settings(), {"FBI_FAMILY_DECISIONS": secret})
    states = [svc.switch_state(s, words[s.switch], {"mode": secret, "research_v2": "shadow"}) for s in svc.SPECS]
    text = json.dumps([s.model_dump(mode="json") for s in states])
    assert "sk-" not in text and "NOT-A-REAL" not in text
    assert all(s.changeable_here is False for s in states)


def test_the_workers_word_is_its_ledgers() -> None:
    mode, agents, family = svc.SPEC_OF["FBI_AI_MODE"], svc.SPEC_OF["FBI_AI_AGENTS"], svc.SPEC_OF["FBI_FAMILY_DECISIONS"]
    assert svc.worker_word({"mode": "enforce"}, mode) == "enforce"
    assert svc.worker_word({"mode": "enforce"}, agents) == "ninguno", "a word at its default is not written: absent is the default"
    assert svc.worker_word({"pm_reviewer": True}, svc.SPEC_OF["FBI_AI_PM_REVIEWER"]) == "on"
    assert svc.worker_word(None, mode) == Missing(missing_reason="sin_datos")
    assert svc.worker_word({"mode": "x"}, family) == Missing(missing_reason="sin_datos"), "the worker does not record the families"
    assert svc.worker_word({"mode": "sk-ant-x"}, mode) == Missing(missing_reason="sin_datos"), "only the words the ledger can hold"
    assert svc.worker_word({"engines": "rules,llm,ma-v1"}, svc.SPEC_OF["FBI_AI_ENGINES"]) == "rules,llm,ma-v1"


# ── «nada sale de la sombra» ──────────────────────────────────────────────────────────────────────────────────────────────────

def enforcement(enforced: bool) -> contract.AiEnforcement:
    return contract.AiEnforcement(mode="enforce", enforced=enforced, reason="enforced" if enforced else "shadow_gate_not_passed",
                                  gate_verdict="pass" if enforced else "fail")


def test_the_shadow_breaks_on_exactly_three_things() -> None:
    off = contract.ReadFailure(error="QueryCanceled")
    assert svc.breaks_of("legacy", enforcement(False), 0) == []
    assert svc.breaks_of("intelligence", enforcement(True), 3) == ["picks_source_intelligence", "ai_enforced", "picks_published"]
    assert svc.breaks_of("legacy", off, off) == [], "a read that failed breaks nothing: the verdict says it could not check"


def test_enforce_alone_is_not_a_veto_in_force() -> None:
    words = svc.switch_words(settings(mode="enforce"), {})
    states = {s.switch: svc.switch_state(s, words[s.switch], None) for s in svc.SPECS}
    shadow = contract.Shadow(verdict="se_cumple", breaks=[], picks_source=states["FBI_PICKS_SOURCE"], ai_mode=states["FBI_AI_MODE"],
                             ai_enforcement=enforcement(False), published_picks=0, switches=[], worker_ledger=svc.NO_DATA)
    assert shadow.ai_mode.reads_as == "enforce" and not shadow.ai_mode.at_default
    with pytest.raises(ValueError, match="should be sin_comprobar"):
        contract.Shadow(**(shadow.__dict__ | {"published_picks": contract.ReadFailure(error="QueryCanceled")}))
    with pytest.raises(ValueError, match="should be no_se_cumple"):
        contract.Shadow(**(shadow.__dict__ | {"breaks": ["ai_enforced"]}))


# ── the blocks ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def overview_item(cap: registry.Capability, state: str | None) -> dict[str, Any]:
    gate = {"gate": "battery", "row": 41, "at": "2026-11-15T17:12:20+00:00", "verdict": "NO PASA"}
    return {"key": cap.key, "piece": cap.piece, "title": cap.title, "switch": cap.switch, "state": state,
            "since": None if state is None else "2026-11-17T05:00:00+00:00", "decided_by": None if state is None else "system",
            "signed_by_owner": False, "safety": {"verdict": None if state is None else "PASA"},
            "validation": {"verdict": None if state is None else "INSUFICIENTE", "sample": None if state is None else 12},
            "live": {"safety_gates": [gate for _ in cap.safety_gates],
                     "validation_gates": [{"gate": g, "row": None, "at": None, "verdict": None} for g in cap.validation_gates]},
            "warnings": registry.warnings_for(state, "PASA", "INSUFICIENTE", {"battery": gate} if cap.safety_gates else {}, {})}


def test_capabilities_carry_one_of_four_states_and_their_verdicts() -> None:
    states = ["en_sombra", "lista_para_revision", None, *["construida"] * (len(registry.CATALOG) - 3)]
    items = [overview_item(c, s) for c, s in zip(registry.CATALOG, states, strict=True)]
    by_state = {s: sum(1 for x in states if x == s) for s in registry.STATES}
    view = svc.capabilities_of({"version": registry.VERSION, "capabilities": items, "by_state": by_state,
                                "unregistered": [items[2]["key"]], "not_in_code": []})
    first, second, third = view.items.items[:3]
    assert first.state == "en_sombra" and second.state == "lista_revision" and third.state == Missing(missing_reason="sin_datos")
    assert first.validation == "INSUFICIENTE" and first.validation_sample == 12
    assert first.safety_gates[0].verdict == "NO PASA" and "dice NO PASA" in first.warnings[0]
    assert [(c.state, c.count) for c in view.by_state] == [("construida", 4), ("en_sombra", 1), ("lista_revision", 1), ("autorizada", 0)]
    chronicle = next(i for i in view.items.items if i.key == "chronicle_review")
    assert chronicle.switch == Missing(missing_reason="sin_datos"), "a job of the worker without a switch says so"
    empty = svc.capabilities_of({"version": registry.VERSION, "capabilities": [], "by_state": {}, "unregistered": [], "not_in_code": []})
    assert empty.items.items == [] and empty.items.missing_reason == "sin_datos"


def test_costs_are_the_envelopes_of_decision_12_and_the_caps() -> None:
    s = settings()
    figures = budget_v3.figures_of(intelligence=Decimal("140.10"), readers=Decimal("9.90"), lab=Decimal("10"), exa=Decimal("2"), settings=s)
    rows = [capability_budget.Row("lab", "replay-bank-v1", None, Decimal("2.85"))]
    costs = svc.costs_of(costs_v3.Month(date(2026, 11, 1), figures, capability_budget.report(rows)), s)
    production = costs.envelopes[0]
    assert production.scope == "production" and production.spent_usd == "150.00" and production.alert == "80"
    assert [(p.name, p.spent_usd) for p in production.parts] == [("intelligence", "140.10"), ("readers", "9.90")]
    replay = next(c for c in costs.capabilities if c.key == "replay_regression")
    assert replay.alert == "95" and replay.spent_usd == "2.85"
    assert all(d.fits for d in costs.declared)
    assert costs.joint_ceiling.usd == "190.00" and costs.joint_ceiling.applies and costs.joint_ceiling.pending_owner
    assert not svc.costs_of(costs_v3.Month(date(2026, 11, 1), figures, []), settings(envelopes_independent=True)).joint_ceiling.applies


def test_the_gates_are_the_panels_with_their_real_verdict() -> None:
    closure = gates_panel.Row(4501, "gate_b", AT, False, "owner", "c" * 64, None, None, None, gates_panel.CLOSURE_KIND, "decisión del dueño")
    battery = gates_panel.Row(4410, "battery", AT, False, "script", "c" * 64)
    doc = gates_panel.panel(gates_panel.PanelInputs(at=AT, rows={"gate_b": closure, "battery": battery}))
    gates = svc.gates_of(doc, AT)
    gate_b = next(g for g in gates.items if g.id == "gate_b")
    assert gate_b.status == "NO EVALUADO" and not gate_b.approved and gate_b.recorded_row == 4501
    assert gates.rule_holds and not any(g.approved for g in gates.items)
    assert sum(c.count for c in gates.summary) == len(gates.items) == len(doc["gates"])
    assert svc.battery_of({"battery": battery}) == contract.Battery(verdict="NO PASA", row=4410, at=AT)
    assert svc.battery_of({}).verdict == Missing(missing_reason="sin_datos")


def test_the_leak_audit_is_its_newest_night() -> None:
    rows = [{"day": date(2026, 11, 20), "rule": r, "version": "leak-audit-v9", "n_checked": 100, "n_violations": n}
            for r, n in (("price_known", 1), ("evidence_known", 2), ("pick_known", 0))]
    audit = svc.leak_audit_of(rows)
    assert isinstance(audit, contract.LeakAudit)
    assert (audit.rules, audit.violations) == (3, 3)
    assert [r.rule for r in audit.with_violations] == ["evidence_known", "price_known"]
    assert svc.leak_audit_of([]) == Missing(missing_reason="sin_datos")


def test_the_code_head_is_the_newest_migration() -> None:
    head = svc.code_head(BACKEND / "migrations" / "versions")
    assert head is not None and "," not in head
    assert svc.MIGRATIONS == BACKEND / "migrations" / "versions"
    assert svc.code_head(BACKEND / "no-such-folder") is None


def test_a_block_that_fails_says_its_error_and_nothing_more() -> None:
    class Conn:
        def transaction(self) -> Any:
            class T:
                def __enter__(self) -> None:
                    return None

                def __exit__(self, *a: object) -> None:
                    return None
            return T()

    def fail() -> int:
        raise psycopg.errors.UndefinedTable('relation "intel.capabilities" does not exist')

    failure = svc.attempt(Conn(), fail)  # type: ignore[arg-type]
    assert failure == contract.ReadFailure(error="UndefinedTable")
    assert "intel" not in json.dumps(failure.model_dump(mode="json"))
    assert svc.attempt(Conn(), lambda: 7) == 7  # type: ignore[arg-type]


def test_the_news_engine_and_the_alert_queue_wait_for_their_pieces() -> None:
    assert Missing(missing_reason="no_entregado", expected_piece="AD-G01") == svc.NEWS_ENGINE
    assert Missing(missing_reason="no_entregado", expected_piece="AD-D08") == svc.ALERT_QUEUE
    fields = contract.ConsoleContract.model_fields
    assert fields["news_engine"].annotation is Missing and fields["alert_queue"].annotation is Missing
    assert contract.ConsoleContract.PRIVATE_ONLY and contract.ConsoleContract.expected_projection() == "private"
    assert Freshness(generated_at=AT, stale=False).stale is False


# ── read only ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_console_and_the_ai_routes_change_no_switch() -> None:
    from fbi.api.app import create_app

    paths = create_app().openapi()["paths"]
    ours = {p: set(ops) for p, ops in paths.items() if p.startswith(("/api/v1/admin/intelligence", "/api/v1/admin/ai/"))}
    assert ours["/api/v1/admin/intelligence/console"] == {"get"}
    writes = sorted((p, m) for p, ops in ours.items() for m in ops - {"get"})
    assert writes == [("/api/v1/admin/ai/report/run", "post"), ("/api/v1/admin/ai/review/run", "post"),
                      ("/api/v1/admin/ai/run-requests", "post")], "the writes of these pages run or queue a job; none changes a switch"
    assert not any(word in p for p, _ in writes for word in ("switch", "flag", "mode", "env", "gate"))
    assert all(ops == {"get"} for p, ops in ours.items() if p.startswith("/api/v1/admin/intelligence"))


def test_the_console_writes_nothing() -> None:
    source = inspect.getsource(svc)
    tree = ast.parse(source)
    strings = " ".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)).upper()
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE", "ALTER ", "DROP "):
        assert verb not in strings
    assert "os.environ[" not in source and "putenv" not in source and ".record(" not in source
