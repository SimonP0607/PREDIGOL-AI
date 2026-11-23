"""PM-12-06: the models judged by competition and by coverage level - the measures of a segment as the backtest computes them, the
verdict («insuficiente» below the sample, never a number as a judgement), the segments adding back to the global figure, the
verdicts by competition, and state 5 of the resolver: with the switch on a market is authorised only where its competition's own
sample says ``apta`` (a competition with no verdict - every new one - is not); with it off, as before."""

from __future__ import annotations

import dataclasses
import math
import random
from datetime import date, timedelta

import numpy as np
import pytest

import fbi.coverage.resolve as resolve
from fbi.coverage import model_segments as sg
from fbi.evaluation import board
from fbi.market.in_force import key_of
from fbi.models.metrics import brier, log_loss, per_match_rps
from tests.unit.test_coverage_resolve import SPECS, inputs, quote

DAY = date(2026, 10, 23)


def sample(*, comp: int = 1, level: str = "B", model: str = "m", market: str = "1X2", p: tuple[float, ...] = (0.5, 0.3, 0.2),
           y: int = 0, day: int = 0, fixture: int = 1, source: str = "forecast") -> sg.Sample:
    return sg.Sample(source=source, model=model, market=market, fixture_id=fixture, competition_id=comp, level=level,
                     day=DAY + timedelta(days=day), p=p, y=y)


def informed(n: int, *, comp: int, level: str, sharp: bool, seed: int) -> list[sg.Sample]:
    """``n`` 1X2 matches over 40 days; a ``sharp`` model gives 0.7 to what happens, a dull one 0.5 to an outcome drawn at random."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        y = rnd.randrange(3)
        hi = 0.7 if sharp else 0.5
        p = [(1 - hi) / 2] * 3
        p[y if sharp else rnd.randrange(3)] = hi
        out.append(sample(comp=comp, level=level, p=tuple(p), y=y, day=i % 40, fixture=comp * 10_000 + i))
    return out


def test_the_needed_sample_is_the_boards() -> None:
    assert sg.NEEDED == board.NEEDED == 300


def test_the_outcome_of_each_market_with_the_90_minute_score() -> None:
    assert [sg.outcome("1X2", 2, 1), sg.outcome("1X2", 1, 1), sg.outcome("1X2", 0, 3)] == [0, 1, 2]
    assert [sg.outcome("OU", 2, 1), sg.outcome("OU", 1, 1)] == [0, 1]
    assert [sg.outcome("BTTS", 1, 1), sg.outcome("BTTS", 2, 0)] == [0, 1]
    with pytest.raises(ValueError):
        sg.outcome("AH", 1, 0)


def test_the_measures_are_the_backtests() -> None:
    items = informed(120, comp=1, level="B", sharp=True, seed=3)
    g = sg.group(items)
    p = np.array([s.p for s in items])
    y = np.array([s.y for s in items], dtype=np.int64)
    assert g["log_loss"] == pytest.approx(log_loss(p, y), abs=1e-6)
    assert g["brier"] == pytest.approx(brier(p, y), abs=1e-6)
    assert g["rps"] == pytest.approx(float(per_match_rps(p, y).mean()), abs=1e-6)
    assert g["n"] == 120 and g["days"] == 40
    assert g["log_loss_low"] <= g["log_loss"] <= g["log_loss_high"]
    clim = [-math.log(sum(1 for s in items if s.y == s0.y) / 120) for s0 in items]
    assert g["skill"] == pytest.approx(g["log_loss"] - sum(clim) / 120, abs=1e-6)
    assert g["verdict"] == "insuficiente"  # 120 matches: no judgement, whatever the skill


def test_the_verdict_with_the_sample() -> None:
    assert sg.group(informed(400, comp=1, level="B", sharp=True, seed=1))["verdict"] == "apta"
    assert sg.group(informed(400, comp=1, level="B", sharp=False, seed=1))["verdict"] == "sin_habilidad"
    assert sg.verdict(299, -1.0) == "insuficiente" and sg.verdict(300, None) == "sin_habilidad" and sg.verdict(300, -0.01) == "apta"
    one_day = [dataclasses.replace(s, day=DAY) for s in informed(400, comp=1, level="B", sharp=True, seed=1)]
    assert sg.group(one_day)["verdict"] == "sin_habilidad"  # one day: no interval, so no «apta»


def test_the_segments_add_back_to_the_global_figure() -> None:
    items = (informed(350, comp=1, level="A", sharp=True, seed=5) + informed(90, comp=2, level="C", sharp=False, seed=6)
             + informed(15, comp=3, level="sin_medir", sharp=True, seed=7))
    items += [dataclasses.replace(s, model="otro") for s in items[:200]]
    segs = sg.build(items)
    checks = sg.reproduction(segs)
    assert len(checks) == 4 and all(c["reproduced"] for c in checks)
    by = {(s["model"], s["kind"], s["key"]): s for s in segs}
    assert by[("m", "global", "*")]["n"] == 455 and by[("m", "competition", "1")]["verdict"] == "apta"
    assert by[("m", "competition", "2")]["verdict"] == "insuficiente" and by[("m", "level", "sin_medir")]["n"] == 15
    assert sg.by_competition(segs) == {"1": {"1X2": "apta"}, "2": {"1X2": "insuficiente"}, "3": {"1X2": "insuficiente"}}
    broken = [dict(s, _ll_sum=s["_ll_sum"] + 1) if s["kind"] == "level" and s["key"] == "C" else s for s in segs]
    assert not all(c["reproduced"] for c in sg.reproduction(broken))
    assert "_ll_sum" not in sg.public(segs[0])


def test_a_match_with_a_selection_missing_is_left_out() -> None:
    from datetime import UTC, datetime

    ko = datetime(2026, 11, 1, 20, tzinfo=UTC)
    base = {"fixture_id": 9, "model": "poisson", "goals_home": 2, "goals_away": 1, "kickoff_at": ko, "competition_id": 4,
            "competition_season_id": 44}
    rows = [{**base, "market_key": "OU", "selection": "Over", "p": 0.55}, {**base, "market_key": "OU", "selection": "Under", "p": 0.45},
            {**base, "market_key": "BTTS", "selection": "Yes", "p": 0.5}]
    got, missing = sg.samples_of(rows, source="forecast", levels_of={44: "B*"})
    assert missing == 1 and len(got) == 1
    assert got[0].p == (0.55, 0.45) and got[0].y == 0 and got[0].level == "B*"


def test_the_switch_is_off_by_default() -> None:
    assert sg.mode({}) == "off" and sg.mode({"FBI_MODEL_SEGMENTS": "1"}) == "on"
    from fbi.api import switches

    assert switches.PROB_BY_COMPETITION == "FBI_PROB_BY_COMPETITION"


def _one_x_two() -> int:
    return next(i for i, s in enumerate(SPECS) if s.kind == "one_x_two" and s.period == "FT")


def test_state_5_by_the_competitions_own_sample() -> None:
    i = _one_x_two()
    qs = tuple(quote(i, b, sel, "0") for b in (1, 2, 3) for sel in ("Home", "Draw", "Away"))
    forecasts = frozenset(key_of(q) for q in qs)
    before = inputs(qs, forecasts=forecasts)

    def state5(own: dict[str, str] | None) -> bool:
        got = resolve.resolve(dataclasses.replace(before, own_sample=own))
        m = next(m for m in got.markets if m.key == key_of(qs[0]))
        return m.prob_authorised

    assert state5(None) is True                    # switch off: as before
    assert state5({}) is False                     # a competition with no verdict: not authorised
    assert state5({"1X2": "insuficiente"}) is False
    assert state5({"1X2": "sin_habilidad"}) is False
    assert state5({"1X2": "apta"}) is True
    assert state5({"OU": "apta"}) is False         # another market's verdict does not count
