"""Plan F12 - the model code does not change without a promotion on record, and the trace says what covers each change.

The first test is the gate: it fails the moment the model packages fingerprint as something the ledger does not have in force. The rest hold the
ledger well formed and the classification of each fingerprint to the cases the plan names."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.core.version import MODEL_PACKAGES, model_code_fingerprint
from fbi.research import promotions, trace
from fbi.research.promotions import CodePromotion
from fbi.research.trace import Recorded

T0 = datetime(2026, 10, 22, 13, 0, tzinfo=UTC)
REASON = "a reason a person can look back on, longer than the forty characters the ledger asks for"


def test_the_model_code_in_the_tree_is_the_one_the_ledger_has_in_force() -> None:
    code = promotions.label_of(model_code_fingerprint())
    assert code == promotions.in_force().fingerprint, (
        f"the packages {MODEL_PACKAGES} now fingerprint as {code} and the last entry of the ledger is {promotions.in_force().fingerprint}: "
        "model code cannot change without a promotion on record. Add a CodePromotion for it to fbi/research/promotions.py (who decided, why, what it "
        "rested on) in the same commit as the change - or, if the change was not meant to alter what the models predict, undo it: it opens a new "
        "version of every model and production forecasts with it from the next pass.")


def test_the_ledger_is_well_formed() -> None:
    ledger = promotions.LEDGER
    assert ledger, "the ledger has at least its baseline"
    assert [p.baseline for p in ledger] == [True] + [False] * (len(ledger) - 1), "the first entry is the baseline and only it"
    assert len({p.fingerprint for p in ledger}) == len(ledger), "one entry per fingerprint"
    assert [p.decided_at for p in ledger] == sorted(p.decided_at for p in ledger), "oldest first"
    for p in ledger:
        assert promotions.FINGERPRINT.match(p.fingerprint), p.fingerprint
        assert p.decided_at.tzinfo is not None
        assert p.decided_by in promotions.DECIDERS, p.fingerprint
        assert p.phase.strip(), p.fingerprint
        assert len(p.reason) >= promotions.MIN_REASON, f"{p.fingerprint}: a promotion without a reason is not a decision"
        hypothesis = p.evidence.get("hypothesis_id")
        assert hypothesis is None or isinstance(hypothesis, int), p.fingerprint
        assert all(isinstance(x, int) for x in p.evidence.get("experiment_ids", [])), p.fingerprint


def test_the_label_of_a_fingerprint_is_what_a_model_version_carries() -> None:
    assert promotions.label_of("9a7bec97caec") == "mc9a7bec97ca"
    assert promotions.find("mc9a7bec97ca") is promotions.LEDGER[0]
    assert promotions.find("mc0000000000") is None


@pytest.mark.parametrize(("version", "code"), [
    ("2.0.0/xi=0.002,penalty=1@mc9a7bec97ca", "mc9a7bec97ca"),
    ("2.0.0/elo=v2.0,K=20,home=65@mce0abbbb30d", "mce0abbbb30d"),
    ("2.0.0/xi=0.002,penalty=3@ea1d0c8", "legacy"),             # keyed by the repository commit, before 5 Oct 2026
    ("2.0.0/features=43,early_stopping=False,l2_regularization=1.0", "legacy"),
])
def test_a_model_version_names_its_code_or_is_a_legacy_one(version: str, code: str) -> None:
    assert trace.fingerprint_of(version) == code


def entry(fingerprint: str, at: datetime, *, baseline: bool = False) -> CodePromotion:
    return CodePromotion(fingerprint, at, "system", "F0", REASON, baseline)


def recorded(at: datetime, *, decided: datetime, baseline: bool = False) -> Recorded:
    return Recorded(1, at, "system", REASON, decided, baseline, {})


def test_each_fingerprint_has_the_status_the_plan_describes() -> None:
    ledger = [entry("mc1111111111", T0, baseline=True), entry("mc2222222222", T0 + timedelta(days=2))]
    rows = {"mc1111111111": recorded(T0 + timedelta(days=5), decided=T0, baseline=True),
            "mc2222222222": recorded(T0 + timedelta(days=5), decided=T0 + timedelta(days=2)),
            "mc4444444444": recorded(T0 + timedelta(days=5), decided=T0 + timedelta(days=4))}

    def status(code: str, appeared: datetime) -> str:
        return trace.classify(code, appeared, ledger=ledger, recorded=rows)

    assert status("legacy", T0 + timedelta(days=1)) == "PRE_LEDGER", "versions keyed by a commit are older than any ledger"
    assert status("mc0000000000", T0 - timedelta(hours=1)) == "PRE_LEDGER", "it came into being before the ledger began: never counted"
    assert status("mc1111111111", T0 + timedelta(minutes=4)) == "BASELINE", "the code already in force, recorded after the fact and said so"
    assert status("mc2222222222", T0 + timedelta(days=2, hours=1)) == "PROMOTED", "decided before the code first ran"
    assert status("mc2222222222", T0 + timedelta(days=1)) == "AFTER_USE", "the decision is on record but the code ran before it"
    assert status("mc4444444444", T0 + timedelta(days=3)) == "AFTER_USE", "a row in the database with no entry in the ledger still covers it"
    assert status("mc3333333333", T0 + timedelta(days=3)) == "UNTRACED", "no decision anywhere: what the plan says must not happen"
    ledger.append(entry("mc3333333333", T0 + timedelta(days=3)))
    assert status("mc3333333333", T0 + timedelta(days=4)) == "PENDING_SYNC", "in the ledger, not yet copied to intel.promotions"


def report(*statuses: str) -> dict[str, Any]:
    fingerprints = [{"fingerprint": f"mc{i:010d}", "status": s, "appeared_at": T0 + timedelta(days=i), "last_use": T0 + timedelta(days=i, hours=3),
                     "versions": 3, "models": ["dixon_coles", "poisson"], "rows": {"predictions": 12000, "decisions": 40}, "in_force_now": i == 0,
                     "promotion": {"id": 7, "decided_by": "owner", "decided_at": T0, "reason": REASON, "evidence": {}} if s == "PROMOTED" else None}
                    for i, s in enumerate(statuses)]
    counted = [f for f in fingerprints if f["status"] != "PRE_LEDGER"]
    traced = [f for f in counted if f["status"] in trace.TRACED]
    return {"now": T0 + timedelta(days=9), "since": T0 - timedelta(days=21), "days": 30, "ledger_since": T0, "ledger_in_force": "mc0000000000",
            "fingerprints": fingerprints,
            "counts": {"fingerprints": len(fingerprints), "counted": len(counted), "traced": len(traced),
                       "untraced": sum(f["status"] == "UNTRACED" for f in counted), "pending_sync": 0, "after_use": 0,
                       "pre_ledger": len(fingerprints) - len(counted)},
            "coverage": len(traced) / len(counted) if counted else None, "other": {"goal_spec": 1, "calibrator": 12}}


def test_the_text_gives_the_count_of_the_criterion_and_names_what_is_not_traced() -> None:
    text = trace.render(report("PRE_LEDGER", "BASELINE", "PROMOTED", "UNTRACED"))
    assert "criterion of the plan" in text and "2 of 3 = 67 %" in text and "untraced 1" in text
    assert "1 fingerprint(s) older than the ledger are listed, not counted" in text
    assert "promotion #7 by owner" in text and "decisions 40, predictions 12 000" in text
    assert "IN FORCE NOW" in text and "calibrator 12, goal_spec 1" in text


def test_a_window_with_no_change_since_the_ledger_began_says_so() -> None:
    assert "no change since the ledger began" in trace.render(report("PRE_LEDGER"))
    assert "100 %" in trace.render(report("BASELINE", "PROMOTED"))
