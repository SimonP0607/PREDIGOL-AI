"""The single registry of promotions (``fbi.governance.promotions``, registry-v1), without a database: each ledger's shape normalised into
one record, what «current» means for each kind, the reading as of a moment, and that the module only ever reads."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import ia_registry

from fbi.governance import promotions as g
from fbi.research import promotions as code_ledger
from fbi.research.promotions import CodePromotion

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
HASH = "c" * 64


def intel_row(n: int, entity: str, to_role: str, *, at: datetime | None = None, market: str | None = "OU", model: str | None = "dixon_coles",
              entity_id: int | None = None, from_role: str | None = None, criteria: dict[str, Any] | None = None,
              gate: str = "calib-gate-v1", by: str = "system") -> dict[str, Any]:
    return {"id": n, "at": at or T0 + timedelta(hours=n), "entity": entity, "market_key": market, "model_name": model, "entity_id": entity_id,
            "from_role": from_role, "to_role": to_role, "gate_version": gate, "criteria": criteria or {}, "reason": f"reason number {n}",
            "decided_by": by}


# ── normalising each shape ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_calibrator_row_is_keyed_by_its_slot_and_versioned_by_the_calibrator() -> None:
    p = g.from_intel_promotion(intel_row(1, "calibrator", "CHAMPION", entity_id=42, criteria={"ece": 0.02, "checks": {"a": 1, "b": 2}}))
    assert (p.entity_type, p.entity_key, p.version, p.decision, p.in_force) == ("calibrator", "OU/dixon_coles", "42", "CHAMPION", True)
    assert (p.source_table, p.source_id, p.gate_version, p.decided_by, p.effective) == ("intel.promotions", "1", "calib-gate-v1", "system", True)
    assert p.evidence == {"checks": {"keys": ["a", "b"]}, "ece": 0.02}


def test_a_market_edge_row_is_one_slot_whatever_calibrator_it_came_from() -> None:
    p = g.from_intel_promotion(intel_row(2, "market_edge", "NOT_VALIDATED", entity_id=42, from_role="VALIDATED", gate="edge-gate-v1"))
    assert (p.entity_key, p.version, p.in_force) == ("OU/dixon_coles", None, False)
    assert p.evidence == {"calibrator_id": 42, "from_role": "VALIDATED"}


def test_a_model_code_row_is_versioned_by_its_fingerprint() -> None:
    p = g.from_intel_promotion(intel_row(3, "model", "CHAMPION", market=None, model=None, gate="code-gate-v1",
                                         criteria={"model_code": "mc9a7bec97ca", "baseline": True}))
    assert (p.entity_type, p.entity_key, p.version) == ("model", g.MODEL_CODE_KEY, "mc9a7bec97ca")


def test_an_agent_row_is_keyed_by_its_family_and_versioned_by_its_promotion_name() -> None:
    p = g.from_intel_promotion(intel_row(4, "agent", "CHAMPION", market="1X2", model="match@match-v1", gate="ma-gate-v1", by="owner",
                                         criteria={"report_hash": HASH}))
    assert (p.entity_type, p.entity_key, p.version, p.decided_by, p.gate_version) == ("agent", "1X2", "match@match-v1", "owner", "ma-gate-v1")


def test_an_entry_of_the_code_ledger_is_listed_but_never_effective() -> None:
    entry = code_ledger.LEDGER[0]
    p = g.from_code_ledger(entry, 0)
    assert (p.entity_type, p.entity_key, p.version, p.decision, p.effective) == ("model", g.MODEL_CODE_KEY, entry.fingerprint, "CHAMPION", False)
    assert p.source_table == g.CODE_LEDGER_SOURCE and p.gate_version == code_ledger.GATE_VERSION and p.evidence["baseline"] is True


def test_a_goal_spec_is_versioned_by_the_hash_of_what_it_says() -> None:
    spec = {"version": "spec-v1", "competition_ids": [39], "history_days": 900, "goal": {"xi": 0.002}}
    row = {"id": 5, "session_id": 11, "promoted_at": T0, "promoted_by": "owner", "reason": "a better goal model", "spec": spec,
           "previous_id": 4, "evidence": {"gain": 0.01}}
    p = g.from_goal_spec(row)
    assert (p.entity_type, p.entity_key, p.decision, p.in_force) == ("goal_spec", g.GOAL_SPEC_KEY, "PROMOTED", True)
    assert p.version is not None and re.fullmatch(r"spec-v1:[0-9a-f]{12}", p.version)
    assert g.spec_fingerprint(dict(reversed(list(spec.items())))) == p.version, "the key order of the JSON does not change the version"
    assert g.spec_fingerprint(spec | {"history_days": 901}) != p.version
    assert p.evidence == {"gain": 0.01, "session_id": 11, "previous_id": 4}


@pytest.mark.parametrize(("action", "version", "decision", "in_force"), [("promote", "neutral-v1", "PROMOTED", True), ("retire", None, "RETIRED", False)])
def test_the_neutral_rule(action: str, version: str | None, decision: str, in_force: bool) -> None:
    row = {"id": 6, "promoted_at": T0, "promoted_by": "owner", "action": action, "rule_version": version, "reason": "the rule, decided",
           "run_id": 3 if version else None, "previous_id": None, "evidence": {}}
    p = g.from_neutral_rule(row)
    assert (p.entity_type, p.entity_key, p.version, p.decision, p.in_force) == ("neutral_rule", g.NEUTRAL_KEY, version, decision, in_force)


def test_a_feature_gate_row() -> None:
    row = {"id": 7, "gate": "batch", "at": T0, "passed": False, "evidence": {"version": "batch-gate-v1", "n": 3, "rows": [1, 2]},
           "evidence_hash": HASH, "decided_by": "script", "code_version": "abc123"}
    p = g.from_feature_gate(row)
    assert (p.entity_type, p.entity_key, p.version, p.decision, p.in_force, p.gate_version) == (
        "ai_gate", "batch", "abc123", "FAILED", False, "batch-gate-v1")
    assert p.evidence == {"n": 3, "rows": {"items": 2}, "version": "batch-gate-v1", "evidence_hash": HASH}


def test_the_switches_are_not_a_gate_and_are_left_out() -> None:
    assert "gate <> 'switches'" in g.GATES_SQL


def test_the_evidence_is_compact() -> None:
    big = {f"k{i:02d}": "x" * 400 for i in range(30)}
    out = g.compact_evidence(big)
    assert len(out) == g.EVIDENCE_KEYS + 1 and out["…"] == "14 more" and all(len(v) <= g.TEXT_CUT for v in out.values())
    assert g.compact_evidence(None) == {} and g.compact_evidence([1]) == {}


@pytest.mark.parametrize(("word", "expected"), [("CHAMPION", True), ("VALIDATED", True), ("PROMOTED", True), ("PASSED", True),
                                                ("CHALLENGER", False), ("RETIRED", False), ("REJECTED", False), ("NOT_VALIDATED", False),
                                                ("FAILED", False), ("SOMETHING", None)])
def test_in_force_of(word: str, expected: bool | None) -> None:
    assert g.in_force_of(word) is expected


def test_every_kind_has_a_rule_for_current() -> None:
    assert not g.BY_VERSION & g.NEWEST
    assert set(g.ENTITY_TYPES) == {"calibrator", "market_edge", "selection_rule", "model", "agent", "goal_spec", "neutral_rule", "ai_gate"}


# ── current and history ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def cal(n: int, role: str, entity_id: int, **kw: Any) -> g.Promotion:
    return g.from_intel_promotion(intel_row(n, "calibrator", role, entity_id=entity_id, **kw))


def test_a_challenger_of_another_calibrator_does_not_depose_the_champion() -> None:
    rows = [cal(1, "CHAMPION", 10), cal(2, "CHALLENGER", 11)]
    now = g.current_of(rows, "calibrator", "OU/dixon_coles")
    assert now is not None and now.version == "10" and now.in_force


def test_a_new_champion_and_the_old_ones_retirement_at_the_same_moment() -> None:
    """``fbi.intel.calibration`` writes the new CHAMPION first and the RETIRED of the old one after it, at the same ``at``."""
    rows = [cal(1, "CHAMPION", 10), cal(2, "CHAMPION", 12, at=T0 + timedelta(days=3)), cal(3, "RETIRED", 10, at=T0 + timedelta(days=3))]
    now = g.current_of(rows, "calibrator", "OU/dixon_coles")
    assert now is not None and now.version == "12"


def test_a_retired_champion_leaves_nothing_in_force_and_current_says_what_took_it_out() -> None:
    rows = [cal(1, "CHAMPION", 10), cal(2, "RETIRED", 10)]
    now = g.current_of(rows, "calibrator", "OU/dixon_coles")
    assert now is not None and now.decision == "RETIRED" and now.in_force is False


def test_current_as_of_a_moment_and_history_in_order() -> None:
    rows = [cal(2, "RETIRED", 10), cal(1, "CHAMPION", 10)]
    before = g.current_of(rows, "calibrator", "OU/dixon_coles", at=T0 + timedelta(hours=1, minutes=30))
    assert before is not None and before.decision == "CHAMPION"
    assert [p.source_id for p in g.history_of(rows, "calibrator", "OU/dixon_coles")] == ["1", "2"]
    assert g.current_of(rows, "calibrator", "OU/dixon_coles", at=T0) is None, "nothing was decided yet"
    assert g.current_of(rows, "calibrator", "BTTS/dixon_coles") is None


def test_an_agent_demoted_by_the_system_is_out_and_a_later_champion_is_in() -> None:
    a = lambda n, role, name, by="owner", src=None: g.from_intel_promotion(  # noqa: E731
        intel_row(n, "agent", role, market="1X2", model=name, by=by, from_role=src, criteria={"report_hash": HASH}, gate="ma-gate-v1"))
    rows = [a(1, "CHAMPION", "match@match-v1"), a(2, "CHALLENGER", "match@match-v1", "system", "CHAMPION")]
    now = g.current_of(rows, "agent", "1X2")
    assert now is not None and now.in_force is False
    rows.append(a(3, "CHAMPION", "match@match-v2"))
    now = g.current_of(rows, "agent", "1X2")
    assert now is not None and now.version == "match@match-v2"


def test_the_newest_row_decides_the_edge_the_neutral_rule_and_a_gate() -> None:
    edge = [g.from_intel_promotion(intel_row(1, "market_edge", "VALIDATED", entity_id=5)),
            g.from_intel_promotion(intel_row(2, "market_edge", "NOT_VALIDATED", entity_id=7))]
    now = g.current_of(edge, "market_edge", "OU/dixon_coles")
    assert now is not None and now.decision == "NOT_VALIDATED"
    neutral = [g.from_neutral_rule({"id": 1, "promoted_at": T0, "promoted_by": "owner", "action": "promote", "rule_version": "nv-v1",
                                    "reason": "promote the rule", "run_id": 1, "previous_id": None, "evidence": {}}),
               g.from_neutral_rule({"id": 2, "promoted_at": T0 + timedelta(days=1), "promoted_by": "owner", "action": "retire",
                                    "rule_version": None, "reason": "switch it off", "run_id": None, "previous_id": 1, "evidence": {}})]
    now = g.current_of(neutral, "neutral_rule", g.NEUTRAL_KEY)
    assert now is not None and now.decision == "RETIRED"


def test_the_code_ledger_never_becomes_current_by_itself() -> None:
    entry = CodePromotion(fingerprint="mc0123456789", decided_at=T0, decided_by="owner", phase="F12", reason="r" * 50)
    declared = [g.from_code_ledger(entry, 0)]
    assert g.current_of(declared, "model", g.MODEL_CODE_KEY) is None
    synced = g.from_intel_promotion(intel_row(9, "model", "CHAMPION", market=None, model=None, gate=code_ledger.GATE_VERSION,
                                              criteria={"model_code": "mc0123456789"}))
    now = g.current_of([*declared, synced], "model", g.MODEL_CODE_KEY)
    assert now is not None and now.source_table == "intel.promotions" and now.version == "mc0123456789"


# ── only reading ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_statement_is_a_select_and_nothing_commits() -> None:
    for name, sql in {k: v for k, v in vars(g).items() if k.endswith("_SQL") and isinstance(v, str)}.items():
        assert sql.lstrip().upper().startswith("SELECT"), name
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP|CREATE)\b", sql, re.IGNORECASE), name
    for path in (ROOT / "src/fbi/governance/promotions.py", ROOT / "scripts/ia_registry.py"):
        assert ".commit(" not in path.read_text(encoding="utf-8"), path
    assert {s for s, _, _ in g.SOURCES} == {"intel.promotions", "analytics.promoted_forecast_spec", "analytics.neutral_rule_promotion",
                                             "ai.feature_gates"}


@pytest.mark.parametrize("argv", [["show"], ["show", "--type", "agent"], ["list", "--at", "yesterday"], ["list", "--at", "2026-10-01T00:00:00"]])
def test_the_command_refuses_what_it_cannot_answer(argv: list[str]) -> None:
    args = ia_registry.build_parser().parse_args(argv)
    out, code = ia_registry.run(args, conn=None)  # type: ignore[arg-type]
    assert code == ia_registry.CANNOT and isinstance(out, dict) and "error" in out
