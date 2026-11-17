"""The registry of capabilities (IA-056, AD-003): its rules, its catalog against the seed of revision 0138, the command line and the private
route. The database's own refusals are proved in ``tests/integration/test_migration_0138.py``."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from scripts import ia_capabilities as cli

from fbi.intel import capabilities as reg

BACKEND = Path(__file__).resolve().parents[2]
EXAMPLE = BACKEND / "tests" / "fixtures" / "contracts" / "intelligence" / "admin_capabilities.json"
AT = datetime(2026, 11, 16, 21, 0, tzinfo=UTC)


def migration() -> ModuleType:
    path = BACKEND / "migrations" / "versions" / "0138_capability_registry.py"
    spec = importlib.util.spec_from_file_location("m0138", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tip(state: str, **kw: Any) -> reg.Tip:
    return reg.Tip(1, state, kw.get("safety", reg.PENDING_ACTIONS), kw.get("validation", reg.PENDING_DEPENDENCIES), None, AT, "system")


def prop(to: str, **kw: Any) -> reg.Proposal:
    base: dict[str, Any] = {"key": "council", "to_state": to, "safety": reg.PENDING_ACTIONS, "validation": reg.PENDING_DEPENDENCIES,
                            "reason": "prueba"}
    base.update(kw)
    return reg.Proposal(**base)


PASSED = {"safety": reg.PASS, "safety_evidence": {"gate": "battery", "row": 20}}
OWNER = {"decided_by": "owner", "owner_signature": "Autorizo esta capacidad, el dueño, 2026-12-01"}


# ── the rules ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_states_are_four_in_one_order() -> None:
    assert reg.STATES == ("construida", "en_sombra", "lista_para_revision", "autorizada")


def test_a_capability_moves_one_state_at_a_time() -> None:
    assert reg.problems(tip(reg.BUILT), prop(reg.SHADOW)) == []
    assert reg.problems(tip(reg.SHADOW), prop(reg.REVIEW, **PASSED)) == []
    skipped = reg.problems(tip(reg.BUILT), prop(reg.REVIEW, **PASSED))
    assert any("no state is skipped" in p for p in skipped)
    assert any("no state is skipped" in p for p in reg.problems(tip(reg.SHADOW), prop(reg.AUTHORISED, **PASSED, **OWNER)))


def test_going_back_and_new_verdicts_in_the_same_state_are_allowed() -> None:
    assert reg.problems(tip(reg.REVIEW), prop(reg.BUILT, safety=reg.FAIL, safety_evidence={"gate": "battery"})) == []
    assert reg.problems(tip(reg.SHADOW), prop(reg.SHADOW, validation=reg.INSUFFICIENT, validation_sample=40,
                                              validation_evidence={"protocol": "x"})) == []


def test_nothing_reaches_autorizada_without_the_owners_signature() -> None:
    by_system = reg.problems(tip(reg.REVIEW), prop(reg.AUTHORISED, **PASSED))
    assert any("owner's alone" in p for p in by_system)
    unsigned = reg.problems(tip(reg.REVIEW), prop(reg.AUTHORISED, **PASSED, decided_by="owner"))
    assert any("signature" in p for p in unsigned)
    assert reg.problems(tip(reg.REVIEW), prop(reg.AUTHORISED, **PASSED, **OWNER)) == []
    assert any("safety PASA" in p for p in reg.problems(tip(reg.REVIEW), prop(reg.AUTHORISED, **OWNER)))


def test_every_state_and_every_word_reaches_autorizada_only_through_the_owner() -> None:
    """Exhaustive over what the system can write: no tip, no verdicts, no sample gets a system row to autorizada."""
    for state in (None, *reg.STATES):
        for safety in reg.SAFETY:
            for validation in reg.VALIDATION:
                p = prop(reg.AUTHORISED, safety=safety, safety_evidence={"e": 1}, validation=validation, validation_sample=500,
                         validation_evidence={"e": 1})
                assert reg.problems(None if state is None else tip(state), p), (state, safety, validation)


def test_record_refuses_autorizada_without_the_owners_confirmation() -> None:
    with pytest.raises(PermissionError):
        reg.record(None, prop(reg.AUTHORISED, **PASSED, **OWNER), at=AT)  # type: ignore[arg-type]
    with pytest.raises(PermissionError):
        reg.record(None, prop(reg.SHADOW, **OWNER), at=AT)  # type: ignore[arg-type]


def test_only_safety_stops_a_capability() -> None:
    no = reg.problems(tip(reg.BUILT), prop(reg.SHADOW, safety=reg.FAIL, safety_evidence={"gate": "battery"}))
    assert any("keeps the capability at construida" in p for p in no)
    for word in (reg.NOT_VALIDATED, reg.INSUFFICIENT):
        assert reg.problems(tip(reg.SHADOW), prop(reg.REVIEW, **PASSED, validation=word, validation_sample=12,
                                                  validation_evidence={"protocol": "p"})) == [], word
    assert any("needs a safety PASA" in p for p in reg.problems(tip(reg.SHADOW), prop(reg.REVIEW)))


def test_a_measured_validation_carries_its_sample_and_a_verdict_its_evidence() -> None:
    found = reg.problems(tip(reg.SHADOW), prop(reg.SHADOW, validation=reg.VALIDATED))
    assert any("carries its sample" in p for p in found) and any("validation VALIDADO carries its evidence" in p for p in found)
    assert any("safety PASA carries its evidence" in p for p in reg.problems(tip(reg.SHADOW), prop(reg.REVIEW, safety=reg.PASS)))


def test_a_gate_that_says_no_pasa_stops_every_forward_move_and_contradicts_a_pasa() -> None:
    live = {"battery": reg.FAIL}
    assert any("no forward move" in p for p in reg.problems(tip(reg.BUILT), prop(reg.SHADOW), live_safety=live))
    assert any("contradicts" in p for p in reg.problems(tip(reg.SHADOW), prop(reg.SHADOW, **PASSED), live_safety=live))
    assert reg.problems(tip(reg.SHADOW), prop(reg.BUILT), live_safety=live) == [], "going back is always allowed"
    assert reg.problems(tip(reg.BUILT), prop(reg.SHADOW), live_safety={"battery": reg.PASS}) == []


def test_entry_and_signature_rules() -> None:
    assert reg.problems(None, prop(reg.BUILT)) == [] and reg.problems(None, prop(reg.SHADOW)) == []
    assert any("enters the registry" in p for p in reg.problems(None, prop(reg.REVIEW, **PASSED)))
    assert any("only the owner signs" in p for p in reg.problems(tip(reg.SHADOW), prop(reg.SHADOW, owner_signature="firma larga aquí")))
    assert any("unknown capability" in p for p in reg.problems(None, prop(reg.BUILT, key="nope")))
    assert any("reason" in p for p in reg.problems(None, prop(reg.BUILT, reason="  ")))


def test_the_warnings_never_read_better_than_the_verdicts() -> None:
    gates = {"battery": {"gate": "battery", "row": 18, "verdict": reg.FAIL}}
    w = reg.warnings_for(reg.SHADOW, reg.PENDING_ACTIONS, reg.PENDING_DEPENDENCIES, gates, {})
    assert any("fila 18" in x and "NO PASA" in x for x in w) and any("no validada" in x for x in w)
    assert reg.warnings_for(reg.REVIEW, reg.PASS, reg.VALIDATED, {}, {}) == []
    assert reg.warnings_for(None, None, None, {}, {})[0].startswith("sin registrar")


# ── the catalog and the seed ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_seed_of_0138_is_the_code_catalog() -> None:
    m = migration()
    assert [{k: e[k] for k in ("key", "piece", "title", "description", "switch", "components")} for e in m.SEED] == [
        c.entry() for c in reg.CATALOG]
    assert m.STATES == reg.STATES and m.SAFETY == reg.SAFETY and m.VALIDATION == reg.VALIDATION and set(m.MEASURED) == reg.MEASURED


def test_the_seed_invents_no_verdict_and_hashes_like_the_code() -> None:
    m = migration()
    for entry in m.SEED:
        doc = m.seed_document(entry)
        assert doc["safety"] == reg.PENDING_ACTIONS and doc["validation"] == reg.PENDING_DEPENDENCIES and doc["validation_sample"] is None
        assert m.evidence_hash(doc) == reg.evidence_hash(doc)
        assert doc["observed"]["at"] == "2026-11-16T20:45:00Z" and doc["observed"]["window_days"] == 7
        assert reg.problems(None, reg.Proposal(entry["key"], reg.SHADOW, doc["safety"], doc["validation"], doc["reason"])) == []


def test_the_catalog_is_well_formed() -> None:
    keys = [c.key for c in reg.CATALOG]
    assert len(keys) == len(set(keys))
    for c in reg.CATALOG:
        assert c.piece.startswith("AD-") and c.title and c.description and c.components
        assert c.switch is None or c.switch.startswith("FBI_")
    from fbi.ai.gates import GATES

    assert {g for c in reg.CATALOG for g in (*c.safety_gates, *c.validation_gates)} <= set(GATES)


def test_sync_plans_only_what_is_missing_or_changed() -> None:
    stored = {c.key: {**c.entry(), "id": i + 1, "version": 1} for i, c in enumerate(reg.CATALOG)}
    assert reg.sync_plan(stored) == []
    changed = dict(stored)
    changed["council"] = {**stored["council"], "description": "otra"}
    del changed["readers"]
    plan = {c.key: (s, v) for c, s, v in reg.sync_plan(changed)}
    assert plan == {"readers": (None, 1), "council": (stored["council"]["id"], 2)}


# ── the command line ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_cli_refuses_owner_words_outside_propose() -> None:
    with pytest.raises(SystemExit):
        cli.main(["list", "--confirm-owner"])
    with pytest.raises(SystemExit):
        cli.main(["history", "--write"])


def test_the_cli_builds_the_owner_row_only_with_confirm_owner() -> None:
    args = cli.build_parser().parse_args(["propose", "--key", "council", "--to", "autorizada", "--safety", "PASA", "--validation",
                                          "VALIDADO", "--reason", "r", "--signature", "Autorizo, el dueño, hoy"])
    with pytest.raises(ValueError, match="--confirm-owner"):
        cli.proposal(args)
    args.confirm_owner = True
    p = cli.proposal(args)
    assert p.decided_by == "owner" and p.owner_signature == "Autorizo, el dueño, hoy"
    args.signature, args.confirm_owner = None, False
    assert cli.proposal(args).decided_by == "system"
    args.safety_evidence = "[1]"
    with pytest.raises(ValueError, match="JSON object"):
        cli.proposal(args)


# ── the private route ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_registry_is_served_only_by_the_admin_console() -> None:
    from fbi.api.app import create_app

    paths = create_app().openapi()["paths"]
    found = [p for p in paths if "capabilit" in p]
    assert found == ["/api/v1/admin/intelligence/capabilities"], found
    assert list(paths[found[0]]) == ["get"], "reading only"


def test_no_public_contract_names_the_registry() -> None:
    contracts = BACKEND / "src" / "fbi" / "api" / "contracts"
    assert not [p.name for p in contracts.rglob("*.py") if "capability_transitions" in p.read_text(encoding="utf-8")
                or "intel.capabilities" in p.read_text(encoding="utf-8")]


def test_the_contract_example_carries_every_capability_and_only_closed_words() -> None:
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data = doc["data"]
    assert doc["status"] == "ok" and data["version"] == reg.VERSION and data["decides"] is False
    assert [c["key"] for c in data["capabilities"]] == [c.key for c in reg.CATALOG]
    for c in data["capabilities"]:
        assert c["state"] in reg.STATES and c["safety"]["verdict"] in reg.SAFETY and c["validation"]["verdict"] in reg.VALIDATION
        assert set(c) == set(data["capabilities"][0])
