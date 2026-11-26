"""RP-8.5: the fixed groups of decisions and their report in three columns. Pure: the rows are simulated, nothing reads a database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from fbi.research import decision_groups as dg
from fbi.research import pattern_search as ps
from fbi.research.pattern_search import Obs

T0 = datetime(2026, 10, 13, tzinfo=UTC)
REASONS = ("ev", "model", "thin_market", "ninguno")


def test_the_dimensions_are_the_ones_the_plan_fixed_and_the_search_knows_them() -> None:
    assert dg.DIMENSIONS == ("reject_reason", "market", "odds_band", "market_distance", "competition_tier", "searched", "lineups", "news")
    assert all(d in ps.DIMENSIONS or d in ps.GROUPS for d in dg.DIMENSIONS)
    assert all(d in ps.DIMENSION_ES and d in ps.STANDS_FOR for d in ps.GROUPS)
    assert len(ps.DIMENSIONS) == 12, "the 12 of the search v1 are not touched"


def test_the_distance_to_the_market_is_a_band_that_includes_its_lower_edge() -> None:
    assert dg.distance_band(-0.06) == "bajo -5 puntos" and dg.distance_band(-0.05) == "-5 a -2 puntos"
    assert dg.distance_band(0.0) == "-2 a +2 puntos" and dg.distance_band(0.02) == "+2 a +5 puntos" and dg.distance_band(0.05) == "sobre +5 puntos"


def test_news_is_confirmed_only_by_a_confirmed_item_of_any_origin() -> None:
    assert dg.confirmed_news({"web:CONFIRMED": 2}) and dg.confirmed_news({"provider:PROBABLE": 3, "provider:CONFIRMED": 1})
    assert not dg.confirmed_news({"web:PROBABLE": 4, "web:CONFIRMED": 0}) and not dg.confirmed_news({}) and not dg.confirmed_news(None)


def test_the_groups_of_a_decision_leave_out_what_the_row_cannot_say() -> None:
    full = dg.group_tags(reasons=["ev", "model"], p=0.54, p_market=0.5, tier=1,
                         context={"web_searched": True, "lineups_at": "2026-10-20T10:00:00+00:00", "evidence": {"web:CONFIRMED": 1}})
    assert full == {"reject_reason": ("ev",), "market_distance": ("+2 a +5 puntos",), "competition_tier": ("nivel 1",), "searched": ("yes",),
                    "lineups": ("yes",), "news": ("yes",)}
    bare = dg.group_tags(reasons=[], p=0.5, p_market=None, tier=None, context={"web_searched": False, "lineups_at": None})
    assert bare == {"reject_reason": ("ninguno",), "searched": ("no",), "lineups": ("no",)}


def world(seed: int, *, matches: int = 600, effect: float = 0.0, reason: str = "model") -> list[Obs]:
    """``matches`` matches of 1 to 3 rows. The calibration of a row is noise; ``effect`` is added to the rows whose rejection reason is ``reason``."""
    rng = np.random.default_rng(seed)
    rows: list[Obs] = []
    for m in range(matches):
        day = m * 90 / matches
        for _ in range(1 + int(rng.integers(0, 3))):
            r = REASONS[int(rng.integers(0, len(REASONS)))]
            p = float(np.clip(0.5 + rng.normal(0, 0.1), 0.05, 0.95))
            won = int(rng.random() < p + (effect if r == reason else 0.0))
            tags = {"reject_reason": (r,), "market": (("1X2", "DC", "AH")[int(rng.integers(0, 3))],), "searched": (("yes", "no")[int(rng.integers(0, 2))],),
                    "lineups": (("yes", "no")[int(rng.integers(0, 2))],), "news": (("yes", "no")[int(rng.integers(0, 2))],),
                    "market_distance": (dg.distance_band(float(rng.normal(0, 0.04))),), "competition_tier": (f"nivel {int(rng.integers(1, 4))}",)}
            rows.append(Obs(m, T0 + timedelta(days=day), p, won, None, None, tags, None))
    return rows


def report(rows: list[Obs]) -> dict[str, Any]:
    return ps.search(rows, labels=dict(dg.VALUE_ES), metrics=("calibration",), dimensions=dg.DIMENSIONS)


@pytest.mark.parametrize("seed", range(8))
def test_a_world_with_no_effect_confirms_nothing(seed: int) -> None:
    rep = report(world(seed))
    cols = dg.columns(rep)
    assert cols["confirmed"] == [], "no group survives the correction in a world made of noise"
    assert ps.proposals(rep, only_surviving=True) == []
    assert cols["tests"] > 0 and cols["discarded"] + cols["no_evidence"]["reached_the_bar_but_not_confirmed"] <= cols["tests"]


def test_a_planted_effect_is_confirmed_and_proposed_with_its_key() -> None:
    rep = report(world(3, matches=900, effect=0.2, reason="model"))
    cols = dg.columns(rep)
    assert [(c["dimension"], c["group"]) for c in cols["confirmed"]][:1] == [("reject_reason", "model")]
    made = ps.proposals(rep, only_surviving=True)
    assert made and made[0].key == "pattern2:calibration:reject_reason:model:up"
    text = dg.render(cols)
    assert "SE CONFIRMA (" in text and "Motivo de rechazo: model" in text and "SE DESCARTA" in text and "SIN EVIDENCIA" in text


def test_a_finding_that_does_not_survive_the_correction_is_not_proposed_but_is_not_lost() -> None:
    rep = report(world(5, matches=900, effect=0.2))
    rep["found"] = [{**f, "survives_correction": False} for f in rep["found"]]
    assert ps.proposals(rep, only_surviving=True) == []
    assert ps.triage(rep, only_surviving=True)[1], "each is listed with why it was left out"


def test_the_switch_is_off_unless_it_says_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(dg.SWITCH, raising=False)
    monkeypatch.setattr(dg, "environment", lambda: {})
    assert dg.mode() == "off"
    monkeypatch.setattr(dg, "environment", lambda: {dg.SWITCH: "Propose"})
    assert dg.mode() == "propose"
    monkeypatch.setattr(dg, "environment", lambda: {dg.SWITCH: "yes"})
    assert dg.mode() == "off", "anything unknown means off"
