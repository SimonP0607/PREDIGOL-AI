"""The verdict of the goals-prevented probe (plan PM, PM-05-05; BE-068): the field is published only when every test passes."""

from __future__ import annotations

from scripts.goals_prevented_probe import verdict

GOOD = {"both": 5000, "correlation": 0.82, "sign_agreement": 0.91, "out_of_range": 0}


def test_a_coherent_field_passes() -> None:
    assert verdict(GOOD) == {"verdict": "PASS", "reasons": []}


def test_each_test_can_fail_it() -> None:
    for change in ({"both": 199}, {"correlation": 0.59}, {"correlation": None}, {"sign_agreement": 0.69}, {"out_of_range": 1}):
        got = verdict(GOOD | change)
        assert got["verdict"] == "FAIL" and len(got["reasons"]) == 1, change
