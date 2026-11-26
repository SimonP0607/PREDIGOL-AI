"""RP-8.4 (tranche 2), the rule: a promoted version is judged with the words the calibrators already had, says nothing on a small sample, and a degrading one drafts a
withdrawal for the owner's signature with the way back - never a promotion, never a probability."""

from __future__ import annotations

from datetime import UTC, datetime

from fbi.proposals import problems
from fbi.proposals import surveillance as s

SINCE = datetime(2026, 12, 1, tzinfo=UTC)


def finding(reading: s.Reading | None, *, automatic: bool = False, previous: str | None = "41") -> s.Finding:
    return s.Finding("calibrator", "1X2/poisson", "42", SINCE, previous, reading, s.judge(reading), automatic=automatic)


def test_the_rule_is_the_one_of_the_calibrators() -> None:
    assert (s.WINDOW_DAYS, s.MIN_N, s.MAX_ECE, s.MARGIN) == (14, 500, 0.05, 0.0)


def test_a_small_sample_says_nothing_and_withdraws_nothing() -> None:
    v = s.judge(s.Reading(499, 0.70, 0.60, 0.20))
    assert v.state == s.SHORT and "499" in v.reasons[0]
    assert s.judge(None).state == s.SHORT
    assert s.judge(s.Reading(900, None, 0.6)).state == s.SHORT


def test_a_version_that_is_not_worse_is_kept() -> None:
    assert s.judge(s.Reading(500, 0.60, 0.60, 0.05)).state == s.KEEPS, "equal to its reference and at the calibration limit is not worse"
    assert s.judge(s.Reading(2000, 0.58, 0.60, 0.01)).state == s.KEEPS


def test_worse_than_the_reference_or_badly_calibrated_degrades() -> None:
    assert s.judge(s.Reading(800, 0.6001, 0.60, 0.01)).state == s.DEGRADES
    v = s.judge(s.Reading(800, 0.55, 0.60, 0.051))
    assert v.state == s.DEGRADES and "calibración" in v.reasons[0]
    both = s.judge(s.Reading(800, 0.70, 0.60, 0.20))
    assert len(both.reasons) == 2


def test_a_degrading_version_drafts_a_withdrawal_with_the_way_back() -> None:
    p = s.withdrawal(finding(s.Reading(800, 0.70, 0.60, 0.20)))
    assert p is not None
    assert (p.kind, p.target, p.current_version, p.proposed_version) == ("retirada", "store:promotion/calibrator/1X2/poisson", "42", "41")
    assert p.rollback_to == "42" and p.evidence["n"] == 800 and p.evidence["rule"] == s.VERSION
    assert problems(p) == [], "a proposal that lowers a threshold or names a probability is refused: this one does neither"
    assert p.hash == s.withdrawal(finding(s.Reading(800, 0.70, 0.60, 0.20))).hash  # type: ignore[union-attr]


def test_with_no_previous_version_the_way_back_says_so() -> None:
    p = s.withdrawal(finding(s.Reading(800, 0.70, 0.60), previous=None))
    assert p is not None and p.proposed_version == "sin-version-anterior"


def test_nothing_is_drafted_for_a_healthy_short_or_self_withdrawing_version() -> None:
    assert s.withdrawal(finding(s.Reading(800, 0.55, 0.60, 0.01))) is None
    assert s.withdrawal(finding(s.Reading(100, 0.90, 0.60, 0.20))) is None
    assert s.withdrawal(finding(s.Reading(800, 0.70, 0.60), automatic=True)) is None, "the calibration step already retires it under this rule"
