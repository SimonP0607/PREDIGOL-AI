"""RP-12.2 ``review-prefilter-v1``: the model is not asked about a selection the rules already rejected (except a fixed control share)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.ai import review as rv
from fbi.ai import review_prefilter as rp
from fbi.ai.config import AiSettings


def keys(n: int) -> list[tuple[int, str, str, Decimal]]:
    return [(1000 + i, "1X2" if i % 2 else "OU", "Home" if i % 3 else "Over", Decimal("2.5") if i % 2 == 0 else Decimal(0)) for i in range(n)]


def test_it_skips_only_what_the_rules_rejected_and_keeps_a_stable_control() -> None:
    ks = keys(2000)
    assert all(not rp.skips(d, *k) for d in ("APPROVE", "DOWNGRADE", "ABSTAIN") for k in ks[:50]), "only REJECT is skipped"
    skipped = [k for k in ks if rp.skips("REJECT", *k)]
    kept = len(ks) - len(skipped)
    assert 0.07 < kept / len(ks) < 0.13, "about a tenth stays as the control"
    assert skipped == [k for k in ks if rp.skips("REJECT", *k)], "stable: no state, no clock"
    assert all(rp.in_control(*k) for k in ks if not rp.skips("REJECT", *k))


def test_the_control_does_not_depend_on_the_outcome_or_the_decision() -> None:
    k = (4242, "1X2", "Home", Decimal(0))
    assert rp.bucket(*k) == rp.bucket(*k) and 0 <= rp.bucket(*k) < rp.BUCKETS
    assert rp.in_control(*k) == (rp.bucket(*k) < int(rp.CONTROL_SHARE * rp.BUCKETS))


def test_a_rules_reject_cannot_be_lifted_by_the_model_so_skipping_it_changes_nothing() -> None:
    for model in ("APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"):
        results = [rv.EngineResult("rules", rv.RULES_VERSION, "REJECT", {}, input_hash="a"),
                   rv.EngineResult("llm", "review-v2", model, {}, input_hash="b")]
        assert rv.combine(results) == "REJECT"


def row(i: int, rules: str | None, llm: str, cost: str = "0.04", combined: str | None = "REJECT") -> dict[str, object]:
    k = keys(2000)[i]
    return {"fixture_id": k[0], "market_key": k[1], "selection": k[2], "line": k[3], "rules": rules, "llm": llm, "cost": cost, "combined": combined}


def test_the_replay_counts_what_would_not_be_asked_and_what_it_would_cost_to_keep() -> None:
    rows = [row(i, "REJECT", "REJECT") for i in range(400)] + [row(i, "DOWNGRADE", "REJECT", combined="REJECT") for i in range(400, 700)] \
        + [row(i, "APPROVE", "APPROVE", combined="APPROVE") for i in range(700, 710)] + [row(5, None, "APPROVE", combined=None)]
    p = rp.replay(rows, window_days=30)
    assert p.reviews == 711 and p.cost == Decimal("0.04") * 711
    assert p.skipped + p.control == 400
    assert p.skipped_cost == Decimal("0.04") * p.skipped and p.skipped > 300
    assert p.combined_approvals_changed == 0 and p.approved_where_rules_rejected == 0
    d = rp.as_dict(p)
    assert d["version"] == "review-prefilter-v1" and d["would_skip"] == p.skipped and 0 < d["share_of_cost"] < 1


def test_a_skipped_review_whose_combined_decision_was_not_reject_would_be_counted_as_a_change() -> None:
    bad = [row(i, "REJECT", "APPROVE", combined="APPROVE") for i in range(100)]
    p = rp.replay(bad, window_days=7)
    assert p.skipped > 0 and p.combined_approvals_changed == p.skipped and p.approved_where_rules_rejected == 100


def test_the_switch_is_off_unless_it_says_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw, expected in ((None, False), ("", False), ("0", False), ("off", False), ("1", True), ("on", True), ("Yes", True)):
        env = {} if raw is None else {"FBI_AI_REVIEW_PREFILTER": raw}
        monkeypatch.setattr("fbi.ai.config.environment", lambda env=env: env)
        s = AiSettings.from_env()
        assert s.review_prefilter is expected and s.public()["review_prefilter"] is expected, raw
