"""The forecast spec (plan F0, defect 2): what a backtest session chose, as the forecast reads it.

Pure functions only: the promotion history itself is tested on a real database (tests/integration/
test_promoted_forecast_spec.py)."""

from __future__ import annotations

from typing import Any

import pytest

from fbi.backtesting.walkforward import GoalSpec, WalkForwardConfig
from fbi.predictions import spec as fs

SELECTION: dict[str, Any] = {
    "poisson": {"chosen": {"xi": 0.002, "penalty": 1.0}, "grid": [{"xi": 0.0, "penalty": 0.5}]},
    "dixon_coles": {"chosen": {"xi": 0.0015, "penalty": 2.0}},
    "elo_ologit": {"chosen": {"k": 20}},  # a model with no goal hyper-parameters: not part of the spec
}
CONFIG: dict[str, Any] = {"history_days": 365, "config_hash": "x"}


def old_logic(competition_ids: list[int], config: dict[str, Any], selection: dict[str, Any], session_id: int) -> fs.Spec:
    """``current_spec`` as it was before this change, from a session's columns (the oracle the seed must reproduce)."""
    cfg = WalkForwardConfig(competition_ids=tuple(int(x) for x in competition_ids),
                            history_days=int(config.get("history_days", 730)))
    goal = {kind: GoalSpec(kind, float(sel["chosen"]["xi"]), float(sel["chosen"]["penalty"]))
            for kind, sel in dict(selection).items() if kind in ("poisson", "dixon_coles")}
    return fs.Spec(cfg.competition_ids, cfg, goal, session_id)


def test_a_snapshot_keeps_the_goal_models_the_window_and_the_competitions_only() -> None:
    assert fs.snapshot([39, 140], CONFIG, SELECTION) == {
        "version": "spec-v1", "competition_ids": [39, 140], "history_days": 365,
        "goal": {"poisson": {"xi": 0.002, "penalty": 1.0}, "dixon_coles": {"xi": 0.0015, "penalty": 2.0}}}


def test_a_session_without_a_window_gets_the_default_one() -> None:
    assert fs.snapshot([39], {}, SELECTION)["history_days"] == fs.DEFAULT_HISTORY_DAYS == 730


@pytest.mark.parametrize("config", [CONFIG, {}, {"history_days": 1000}])
def test_the_spec_read_from_a_snapshot_is_the_spec_the_forecast_used_to_read_from_the_session(
        config: dict[str, Any]) -> None:
    doc = fs.snapshot([39, 140], config, SELECTION)
    assert fs.parse(doc, session_id=9) == old_logic([39, 140], config, SELECTION, 9)


def test_the_cfg_carries_the_competitions_and_the_window() -> None:
    s = fs.parse(fs.snapshot([39, 140], CONFIG, SELECTION), session_id=1)
    assert s.competition_ids == (39, 140) and s.cfg.competition_ids == (39, 140) and s.cfg.history_days == 365
    assert s.goal["poisson"].tag == "xi=0.002,penalty=1" and s.session_id == 1


def good() -> dict[str, Any]:
    return fs.snapshot([39], CONFIG, SELECTION)


@pytest.mark.parametrize(("change", "message"), [
    ({"version": "spec-v0"}, "unknown forecast spec version"),
    ({"competition_ids": []}, "at least one competition"),
    ({"history_days": 0}, "at least one day"),
    ({"goal": {"poisson": {"xi": -0.1, "penalty": 1.0}}}, "finite and not negative"),
    ({"goal": {"poisson": {"xi": 0.1, "penalty": float("nan")}}}, "finite and not negative"),
    ({"goal": {"poisson": {"xi": float("inf"), "penalty": 1.0}}}, "finite and not negative"),
    ({"goal": {"mnlogit": {"xi": 0.1, "penalty": 1.0}}}, "is not a goal model"),
], ids=["version", "no competition", "no window", "negative xi", "nan penalty", "infinite xi", "other model"])
def test_a_spec_that_cannot_be_used_stops_the_forecast_instead_of_fitting_something_else(
        change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        fs.parse(good() | change, session_id=1)


def spec_of(goal: dict[str, tuple[float, float]], *, window: int = 730, competitions: tuple[int, ...] = (39, 140),
            session_id: int = 1) -> fs.Spec:
    return fs.Spec(competitions, WalkForwardConfig(competition_ids=competitions, history_days=window),
                   {k: GoalSpec(k, xi, pen) for k, (xi, pen) in goal.items()}, session_id)


BASE = spec_of({"poisson": (0.002, 1.0), "dixon_coles": (0.0015, 2.0)})


def test_the_same_forecast_in_another_session_changes_nothing() -> None:
    assert fs.describe(BASE, spec_of({"poisson": (0.002, 1.0), "dixon_coles": (0.0015, 2.0)}, session_id=2)) == []


def test_the_first_spec_says_what_it_holds() -> None:
    [line] = fs.describe(None, BASE)
    assert "first spec" in line and "dixon_coles xi=0.0015 penalty=2" in line and "730 days" in line


def test_a_change_names_every_parameter_that_moves() -> None:
    new = spec_of({"poisson": (0.004, 1.0), "dixon_coles": (0.0015, 3.0)}, window=365, competitions=(39, 78))
    assert fs.describe(BASE, new) == [
        "dixon_coles: xi 0.0015 -> 0.0015, penalty 2 -> 3",
        "poisson: xi 0.002 -> 0.004, penalty 1 -> 1",
        "training window 730 -> 365 days",
        "competitions added to the feature models: [78]",
        "competitions removed from the feature models: [140]"]


def test_a_goal_model_that_appears_or_disappears_is_said() -> None:
    assert fs.describe(BASE, spec_of({"poisson": (0.002, 1.0)})) == ["dixon_coles: removed"]
    assert fs.describe(spec_of({"poisson": (0.002, 1.0)}), BASE) == ["dixon_coles: added"]


def test_a_promotion_needs_a_person_or_the_seed_and_a_reason_to_look_back_on() -> None:
    assert fs.check_reason("owner", "  the 2026 re-fit beat the old one on the validation season ") == (
        "the 2026 re-fit beat the old one on the validation season")
    with pytest.raises(ValueError, match="at least 10 characters"):
        fs.check_reason("owner", "because")
    with pytest.raises(ValueError, match="promoted_by"):
        fs.check_reason("research_v2", "a perfectly good reason")
