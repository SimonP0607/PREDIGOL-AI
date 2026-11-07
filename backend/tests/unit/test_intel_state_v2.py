"""state-v2 (plan IA, P0): five states read off decision-v1's rows. The rows here are made by ``fbi.intel.decision.evaluate`` itself over a world
built in memory, so ``classify`` is held to the filters and reasons decision-v1 really records, not to a copy of them."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.intel import decision, state_v2
from fbi.intel.calibration import CalibrationState, Calibrator

AT = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
KEY: decision.Key = (77, "1X2", "Home", Decimal("0.00"))
SRC = Path(decision.__file__).read_text(encoding="utf-8")


def world(*, champion: bool = True, best: bool = False, edge: bool = True) -> decision.World:
    cal = Calibrator("1X2", "dixon_coles", "identity", {}, id=5, role="champion" if champion else "fit")
    return decision.World(
        at=AT, cal=CalibrationState(champions={("1X2", "dixon_coles"): cal} if champion else {},
                                    best={("1X2", "dixon_coles"): cal} if (best or champion) else {},
                                    wf={("1X2", "dixon_coles"): {"ece_cal": 0.02, "rule_clv": 0.01, "logloss_cal": 0.6}},
                                    edge={("1X2", "dixon_coles"): edge}),
        quality={77: {"data_class": "MODEL_READY", "quarantined": False}}, reviews={}, rules={}, evidence={}, passes={}, lineups={},
        type_clv={}, previous={}, ai_mode="shadow")


def candidate(*, odds: float = 2.0, p: float = 0.56, p_fair: float = 0.48, price_age: timedelta = timedelta(minutes=20)) -> dict[str, Any]:
    return {"pick_id": 1, "fixture_id": 77, "market_key": "1X2", "selection": "Home", "line": Decimal("0"), "model_name": "dixon_coles",
            "model_version_id": 3, "p_model": p, "p_push": 0.0, "p_low": p - 0.05, "p_high": p + 0.05, "kickoff_at": AT + timedelta(hours=5),
            "status_short": "NS", "status_group": "scheduled", "data_cutoff_ts": AT - timedelta(hours=2), "best_odds": odds, "p_fair": p_fair,
            "best_bookmaker_id": 8, "n_bookmakers": 6, "overround": 0.05, "dispersion": 0.01, "price_at": AT - price_age}


def row(w: decision.World, c: dict[str, Any], *, ident: int = 1) -> dict[str, Any]:
    """A row of ``intel.decisions`` as ``decision.store`` writes the fields ``classify`` reads."""
    e = decision.evaluate(w, KEY, {"dixon_coles": c})
    decision.correlate([e])
    return {"id": ident, "state": e.state, "reasons": list(e.reasons), "filters": e.filters, "checkpoint": e.checkpoint, "fixture_id": 77,
            "market_key": "1X2", "selection": "Home", "line": Decimal("0.00")}


def test_an_approval_is_recommended_and_its_label_stays_a_label() -> None:
    r = row(world(), candidate())
    assert r["state"] == "CANDIDATO_PARLAY"
    assert state_v2.classify(r) == ("RECOMMENDED", "approved")
    assert state_v2.label_of(r) == "CANDIDATO_PARLAY"
    for label in ("APROBADO", "PICK_PREMIUM", "PICK_DEL_DIA"):
        assert state_v2.classify(r | {"state": label})[0] == "RECOMMENDED"
    assert state_v2.label_of(r | {"state": "APROBADO"}) is None


def test_an_edge_not_validated_out_of_sample_is_abstain() -> None:
    r = row(world(edge=False), candidate())
    assert r["state"] == "INVESTIGACION" and "edge_not_validated" in r["reasons"]
    assert state_v2.classify(r) == ("ABSTAIN", "edge_not_validated")


def test_no_champion_calibrator_is_abstain() -> None:
    r = row(world(champion=False, best=True), candidate())
    assert r["state"] == "INVESTIGACION" and r["reasons"][0] == "not_calibrated"
    assert state_v2.classify(r) == ("ABSTAIN", "not_calibrated")


def test_no_calibrator_at_all_is_abstain_for_the_calibration_not_for_the_ev() -> None:
    r = row(world(champion=False, best=False), candidate())
    assert {"not_calibrated", "ev_unknown"} <= set(r["reasons"])
    assert state_v2.classify(r) == ("ABSTAIN", "not_calibrated")
    assert state_v2.classify(r | {"reasons": ["ev_unknown"]}) == ("ABSTAIN", "ev_unknown")


def test_a_stale_price_is_watch() -> None:
    r = row(world(), candidate(price_age=timedelta(hours=4)))
    assert r["state"] == "INVESTIGACION" and r["reasons"] == ["price_stale"]
    assert state_v2.classify(r) == ("WATCH", "price_stale")


def test_a_structural_reason_wins_over_a_resolvable_one() -> None:
    r = row(world(champion=False, best=True), candidate(price_age=timedelta(hours=4)))
    assert {"price_stale", "not_calibrated"} <= set(r["reasons"])
    assert state_v2.classify(r) == ("ABSTAIN", "not_calibrated")


def test_caution_and_rejected_carry_the_reason_of_their_own_effect() -> None:
    caution = row(world(), candidate(odds=3.5, p=0.40, p_fair=0.27))
    assert caution["state"] == "CAUTELA"
    assert state_v2.classify(caution) == ("CAUTION", "risk")
    rejected = row(world(), candidate(odds=2.0, p=0.49, p_fair=0.48))
    assert rejected["state"] == "RECHAZADO"
    assert state_v2.classify(rejected) == ("REJECTED", "ev_cal_below")
    assert state_v2.classify({"state": "CAUTELA", "reasons": []}) == ("CAUTION", "none")


def test_an_investigation_no_rule_knows_is_abstain_unclassified_and_listed() -> None:
    odd = {"id": 9, "state": "INVESTIGACION", "reasons": ["a_reason_of_tomorrow"], "filters": [], "fixture_id": 77, "checkpoint": "T-3h",
           "market_key": "1X2", "selection": "Home", "line": Decimal("0")}
    assert state_v2.classify(odd) == ("ABSTAIN", "unclassified")
    rep = state_v2.classify_rows([odd, row(world(), candidate(price_age=timedelta(hours=4)), ident=2)])
    assert rep["unclassified"] == 1 and rep["unclassified_rows"][0]["decision_id"] == 9
    assert rep["by_state"] == {"RECOMMENDED": 0, "CAUTION": 0, "WATCH": 1, "ABSTAIN": 1, "REJECTED": 0}
    assert rep["by_reason"]["ABSTAIN"] == {"unclassified": 1}


def test_without_reasons_the_filter_that_parked_it_says_why_but_the_final_filter_never_does() -> None:
    r = row(world(champion=False, best=True), candidate())
    assert state_v2.classify(r | {"reasons": []}) == ("ABSTAIN", "not_calibrated")
    stale = row(world(), candidate(price_age=timedelta(hours=4)))
    assert state_v2.classify(stale | {"reasons": []}) == ("WATCH", "price_stale")
    edge = row(world(edge=False), candidate())
    assert any(f["key"] == "final" and f.get("effect") == "INVESTIGACION" for f in edge["filters"])
    assert state_v2.classify(edge | {"reasons": []}) == ("ABSTAIN", "unclassified"), "filter 10 records the state, not the reason"


def test_an_unknown_state_is_refused() -> None:
    with pytest.raises(ValueError):
        state_v2.classify({"state": "MAYBE", "reasons": []})


def test_the_tables_are_decision_v1s_own_reason_codes() -> None:
    """Every reason decision-v1 writes is in ``REASON_EFFECT`` with the effect it writes it with, and every INVESTIGACION one has a rule."""
    written = {why: state for state, why in re.findall(r'stop\("([A-Z]+)", "(\w+)"\)', SRC)}
    written |= {"ai_reject": "CAUTELA", "ai_downgrade": "CAUTELA"}  # stop("CAUTELA", f"ai_{review_decision.lower()}")
    assert 'f"ai_{review_decision.lower()}"' in SRC and 'review_decision in ("REJECT", "DOWNGRADE")' in SRC
    written |= {"edge_not_validated": "INVESTIGACION", "correlated_same_match": "CAUTELA"}
    assert 'reasons.append("edge_not_validated")' in SRC and 'reasons.append("correlated_same_match")' in SRC
    assert written == dict(state_v2.REASON_EFFECT)
    parking = {why for why, state in written.items() if state == "INVESTIGACION"}
    assert parking == {code for code, *_ in state_v2.INVESTIGATION_RULES}
    for code, n, key, _ in state_v2.INVESTIGATION_RULES:
        assert re.search(rf'_f\("{key}",[^\n]*\n?[^\n]*\b{n}\b', SRC), (code, key, n)
