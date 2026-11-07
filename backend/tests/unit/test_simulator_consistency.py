"""``sim-v1``'s check, without a database: recovering a goal model's intensities from its own rows, the comparison, and the rules of
coherence over stored numbers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fbi.models.lines import asian_handicap, double_chance, over_under
from fbi.models.scoring import MARKET_ROWS, dc_tau, from_matrix, poisson_matrix
from fbi.simulator import consistency as cs
from fbi.simulator import joint as jt


def stored(lh: float, la: float, rho: float | None = None) -> list[cs.StoredRow]:
    """What the forecast writer stores for a goal model (``fbi.predictions.forecast``): the seven fixed rows and quoted lines, 6 decimals."""
    m = poisson_matrix(lh, la)
    if rho is not None:
        m = dc_tau(m, lh, la, rho)
    rows = [cs.StoredRow(mk, s, ln, round(v, 6)) for (mk, s, ln), v in zip(MARKET_ROWS, from_matrix(m, lh, la).as_rows(), strict=True)]
    for line in ("-1.25", "-0.75", "-0.5", "-0.25", "0", "0.25", "0.5", "1"):
        for side, ln in (("Home", Decimal(line)), ("Away", -Decimal(line))):
            o = asian_handicap(m, selection=side, line=ln)
            rows.append(cs.StoredRow("AH", side, float(ln), round(o.win, 6), round(o.push, 6)))
    for line in ("0.5", "1.5", "2", "2.25", "2.75", "3.5"):
        for side in ("Over", "Under"):
            o = over_under(m, selection=side, line=Decimal(line))
            rows.append(cs.StoredRow("OU", side, float(line), round(o.win, 6), round(o.push, 6)))
    rows += [cs.StoredRow("DC", s, 0.0, round(v, 6)) for s, v in double_chance(m).items()]
    return rows


@pytest.mark.parametrize(("kind", "lh", "la", "rho"), [("poisson", 1.7, 0.9, None), ("dixon_coles", 1.2, 1.35, -0.11),
                                                       ("dixon_coles", 2.4, 0.6, 0.05)])
def test_the_intensities_are_recovered_from_the_models_own_rows(kind: str, lh: float, la: float, rho: float | None) -> None:
    rows = stored(lh, la, rho)
    inv = cs.invert(rows, kind)
    assert inv is not None and inv.residual < 2e-6
    assert inv.lam_home == pytest.approx(lh, rel=1e-4) and inv.lam_away == pytest.approx(la, rel=1e-4)
    if rho is not None:
        assert inv.rho == pytest.approx(rho, abs=1e-3)


def test_the_simulator_reproduces_every_stored_line_of_a_coherent_model() -> None:
    rows = stored(1.45, 1.1, -0.08)
    assert cs.incoherences(rows) == []
    doc = cs.check_model(cs.ModelForecast("dixon_coles", 7, datetime(2026, 11, 7, tzinfo=UTC), rows))
    assert doc["status"] == "compared" and doc["incoherences"] == []
    assert set(doc["markets"]) == {"1X2 (inversion rows)", "OU (inversion rows)", "BTTS (inversion rows)", "AH", "OU", "DC"}
    assert doc["max_abs"] < 1e-5  # the rounding of the stored rows and the source's 10-10 truncation, nothing else
    assert doc["markets"]["AH"]["n"] == 16


def test_a_line_that_disagrees_with_its_model_shows_in_the_comparison() -> None:
    rows = [r if (r.market_key, r.selection, r.line) != ("AH", "Home", -0.75) else replace(r, p=r.p + 0.02) for r in stored(1.45, 1.1)]
    doc = cs.check_model(cs.ModelForecast("poisson", 7, datetime(2026, 11, 7, tzinfo=UTC), rows))
    assert doc["markets"]["AH"]["max_abs"] == pytest.approx(0.02, abs=1e-5)
    assert doc["markets"]["DC"]["max_abs"] < 1e-5


def test_fixed_rows_no_intensities_reproduce_are_reported() -> None:
    rows = [replace(r, p=0.30) if (r.market_key, r.selection) == ("BTTS", "Yes") else
            replace(r, p=0.70) if (r.market_key, r.selection) == ("BTTS", "No") else r for r in stored(1.45, 1.1)]
    doc = cs.check_model(cs.ModelForecast("poisson", 7, datetime(2026, 11, 7, tzinfo=UTC), rows))
    assert doc["status"] == "incoherent_fixed_rows"
    assert any(i["rule"] == "fixed_rows_reproducible" for i in doc["incoherences"])


def test_elo_is_compared_across_models_not_simulated() -> None:
    rows = [cs.StoredRow("1X2", "Home", 0.0, 0.5), cs.StoredRow("1X2", "Draw", 0.0, 0.27), cs.StoredRow("1X2", "Away", 0.0, 0.23)]
    doc = cs.check_model(cs.ModelForecast("elo_ologit", 3, datetime(2026, 11, 7, tzinfo=UTC), rows))
    assert doc["status"] == "not_simulable" and doc["incoherences"] == []
    spread = cs.spread({"elo_ologit": rows, "poisson": stored(1.45, 1.1)})
    home = next(s for s in spread if s["selection"] == "Home" and s["market_key"] == "1X2")
    assert set(home["models"]) == {"elo_ologit", "poisson"} and home["spread"] > 0
    assert cs.check_model(cs.ModelForecast("poisson", 3, datetime(2026, 11, 7, tzinfo=UTC), rows))["status"] == "not_invertible"


def rules(rows: list[cs.StoredRow]) -> set[str]:
    return {i.rule for i in cs.incoherences(rows)}


def test_each_rule_of_coherence_fires_on_what_breaks_it() -> None:
    base = stored(1.45, 1.1)
    key = {(r.market_key, r.selection, r.line): r for r in base}

    def with_(**changes: float) -> list[cs.StoredRow]:
        names = {"home": ("1X2", "Home", 0.0), "draw": ("1X2", "Draw", 0.0), "btts": ("BTTS", "Yes", 0.0),
                 "btts_no": ("BTTS", "No", 0.0), "o25": ("OU", "Over", 2.5), "u25": ("OU", "Under", 2.5),
                 "o15": ("OU", "Over", 1.5), "dc1x": ("DC", "1X", 0.0), "o35": ("OU", "Over", 3.5),
                 "ah_m05": ("AH", "Home", -0.5), "ah_m025": ("AH", "Home", -0.25)}
        out = dict(key)
        for name, value in changes.items():
            out[names[name]] = replace(out[names[name]], p=value)
        return list(out.values())

    assert rules(base) == set()
    assert "1x2_sums_to_one" in rules(with_(home=key[("1X2", "Home", 0.0)].p + 0.01))
    assert "dc_is_1x2_sum" in rules(with_(dc1x=0.99))
    assert "ah_matches_1x2" in rules(with_(ah_m05=0.2))
    assert "ou_monotone" in rules(with_(o35=0.9))
    assert "ah_monotone" in rules(with_(ah_m025=0.9))
    # BTTS 0.62 with a draw of ~0.26 needs over 2.5 >= 0.36: a model saying 0.30 is incoherent, whatever else it says
    assert "btts_over25_lower_bound" in rules(with_(btts=0.62, btts_no=0.38, o25=0.30, u25=0.70))
    assert "btts_over25_upper_bound" in rules(with_(btts=0.05, btts_no=0.95, o25=0.85, u25=0.15))
    assert "btts_within_over15" in rules(with_(btts=0.80, btts_no=0.20))
    assert "btts_sums_to_one" in rules(with_(btts=0.6))
    assert "ou_sums_to_one" in rules(with_(o25=0.6))


def test_the_check_uses_documented_constants() -> None:
    assert jt.MAX_HALF_GOALS == 10 and jt.FIRST_HALF_SHARE_HOME == jt.FIRST_HALF_SHARE_AWAY == 0.45
    assert pytest.approx(1e-5) == cs.TOLERANCE and {"poisson", "dixon_coles"} == cs.GOAL_MODELS
