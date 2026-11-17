"""G-COH (plan 2026, AD-B09, IA-084): every output says the same figure for the same selection, moment and version - and a text that says
another, or none, or another version's, is refused. Without a database; the same against PostgreSQL, through the real readers, is in
``tests/integration/test_single_figure_parity.py``.

The outputs of ``forecast-v2`` (the single figure, AD-B05):

    single_figure ....... ``fbi.forecasting.single_figure.figure_set`` itself
    C-01 (private) ...... the contract's ``single_figure`` block (``fbi.api.services.match_intelligence.single_figures``)
    decision-v2 ......... the number its stages judge with ``--probability common --view-version forecast-v2`` (``fbi.decision.view``)
    text ................ a text that cites the figures (``fbi.forecasting.figure_text``)

``parity`` is the check: it fails, naming the selection and the outputs, as soon as two outputs disagree by more than the rounding of six
places, or one says another seal, model or version. A test below seeds a difference in each output to show that it bites.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal

import pytest

from fbi.api.contracts.intelligence.base import rounded_pct as contract_rounded_pct
from fbi.api.contracts.intelligence.match import FIGURE_ORIGIN
from fbi.api.services import match_intelligence as mi
from fbi.decision import engine
from fbi.decision import view as common
from fbi.decision.families import CORE, Candidate
from fbi.forecasting import figure_text as ft
from fbi.forecasting import single_figure as sf
from fbi.forecasting.market_view import CALIBRATED, Source
from fbi.intel.calibration import CalibrationState, Calibrator
from fbi.models.quoted import price_quoted_lines
from fbi.models.scoring import MARKET_ROWS, dc_tau, from_matrix, poisson_matrix

from .test_decision_v2_engine import AT, pick, world

FID = 77  # the engine's world knows this match
CUT = AT - timedelta(hours=2)
SIX = 1e-6
Reading = tuple[float, str, str, str]
"""(probability, seal, model, version) - what must agree."""


def rows(model: str, lh: float, la: float, rho: float | None, version: int) -> dict[sf.PriceKey, Source]:
    m = poisson_matrix(lh, la)
    if rho is not None:
        m = dc_tau(m, lh, la, rho)
    out = {sf.key_of(mk, s, line): Source(model, version, CUT, "fh", round(p, 6), round(p, 6) - 0.04, round(p, 6) + 0.04, 0.0)
           for (mk, s, line), p in zip(MARKET_ROWS, from_matrix(m, lh, la).as_rows(), strict=True)}
    quoted = [("OU", s, Decimal(x)) for x in ("1.5", "3.5") for s in ("Over", "Under")] + [
        ("AH", "Home", Decimal("-1")), ("AH", "Away", Decimal("1"))]
    for lp in price_quoted_lines(m, quoted):
        out[sf.key_of(lp.market_key, lp.selection, lp.line)] = Source(model, version, CUT, "fh", round(lp.p_win, 6), None, None,
                                                                       round(lp.p_push, 6))
    return out


@pytest.fixture
def figures() -> sf.FigureSet:
    numbers = {"dixon_coles": rows("dixon_coles", 1.5, 1.1, -0.07, 3), "poisson": rows("poisson", 1.45, 1.15, None, 4)}
    champions = {k: Calibrator(k[0], k[1], "logit2", {"a": 0.05, "b": 0.6, "c": 0.4}, id=20 + i, role="CHAMPION")
                 for i, k in enumerate((("1X2", "dixon_coles"), ("OU", "poisson"), ("AH", "dixon_coles")))}
    cal = CalibrationState(champions=champions, best=dict(champions), wf={}, edge={})
    prices = {k: (min(max(s.p + 0.02, 0.02), 0.98), AT - timedelta(hours=20)) for k, s in numbers["poisson"].items()}
    return sf.figure_set(FID, numbers, cal, prices)


# -- the outputs --------------------------------------------------------------------------------------------------------------------------

def from_function(fs: sf.FigureSet) -> dict[sf.PriceKey, Reading]:
    return {k: (f.p, f.label, f.model, f.version) for k, f in fs.figures.items()}


def from_contract(fs: sf.FigureSet) -> dict[sf.PriceKey, Reading]:
    by_id = fs.by_reading()
    out: dict[sf.PriceKey, Reading] = {}
    for item in mi.single_figures(fs, at=AT):
        f = by_id[item.reading_id]
        assert (item.market, item.selection, Decimal(str(item.line))) == (f.market_key, f.selection, f.line)
        out[sf.key_of(item.market, item.selection, item.line)] = (item.probability.value, item.probability.calibration, item.model,
                                                                  item.probability.origin)
    return out


def from_decision(fs: sf.FigureSet) -> dict[sf.PriceKey, Reading]:
    """What decision-v2's stages judge for each selection: the calibrated number, or the model's own when «Sin calibrar»."""
    views = common.figure_readings({FID: fs})
    cands = [Candidate(CORE, (FID, m, s, line), {"dixon_coles": pick(market=m, selection=s) | {"line": line}})
             for (m, s, line) in fs.figures]
    out: dict[sf.PriceKey, Reading] = {}
    for d in engine.decide_all(world(), common.judged(cands, views, family=CORE.name, version=sf.VERSION)):
        p = d.prediction
        assert p.source == engine.COMMON, d.key
        number = p.p_cal if p.calibration == CALIBRATED else p.p_model
        assert number is not None
        out[sf.key_of(d.key[1], d.key[2], d.key[3])] = (number, "calibrada" if p.calibration == CALIBRATED else "sin_calibrar",
                                                        p.model, str(p.version))
    return out


def from_text(fs: sf.FigureSet) -> dict[sf.PriceKey, Reading]:
    """A text that cites every figure (to one decimal), checked: it is accepted, and each figure it states is the reading it cites."""
    by_id = fs.by_reading()
    parts = [f"{f.market_key} {f.selection} {f.line}: {ft.cite(f.reading_id, f.p, version=f.version, decimals=1)}." for f in by_id.values()]
    text = " ".join(parts)
    verdict = ft.check(text, {rid: f.p for rid, f in by_id.items()}, version=sf.VERSION)
    assert verdict.accepted and verdict.figures == len(by_id), verdict.as_json()
    out: dict[sf.PriceKey, Reading] = {}
    for m in ft.CITATION.finditer(text):
        f = by_id[m.group("id")]
        out[f.key] = (f.p, f.label, f.model, m.group("version"))
    return out


def parity(outputs: Mapping[str, Mapping[sf.PriceKey, Reading]]) -> list[str]:
    """Every disagreement between outputs on the same selection (empty: G-COH holds)."""
    names = sorted(outputs)
    keys = set().union(*(set(o) for o in outputs.values()))
    found: list[str] = []
    for k in sorted(keys, key=str):
        seen = {n: outputs[n].get(k) for n in names}
        missing = [n for n, v in seen.items() if v is None]
        if missing:
            found.append(f"{k}: no figure in {missing}")
            continue
        values = [v for v in seen.values() if v is not None]
        ps = [v[0] for v in values]
        if max(ps) - min(ps) > SIX:
            found.append(f"{k}: { {n: round(v[0], 7) for n, v in seen.items() if v is not None} }")
        if len({v[1:] for v in values}) != 1:
            found.append(f"{k}: seal, model or version differ { {n: v[1:] for n, v in seen.items() if v is not None} }")
    return found


def outputs(fs: sf.FigureSet) -> dict[str, dict[sf.PriceKey, Reading]]:
    return {"single_figure": from_function(fs), "C-01": from_contract(fs), "decision-v2": from_decision(fs), "text": from_text(fs)}


# -- G-COH ---------------------------------------------------------------------------------------------------------------------------------

def test_every_output_of_forecast_v2_says_the_same_figure_seal_model_and_version(figures: sf.FigureSet) -> None:
    out = outputs(figures)
    assert not parity(out), "\n".join(parity(out))
    assert len(out["single_figure"]) >= 40, "1X2, DC, DNB, BTTS, total and Asian lines, the goals of each side, the European handicap"
    seals = {v[1] for v in out["single_figure"].values()}
    assert seals == {"calibrada", "sin_calibrar"}, "the case holds both seals"
    assert {v[3] for v in out["C-01"].values()} == {FIGURE_ORIGIN} == {sf.VERSION}


@pytest.mark.parametrize("output", ["C-01", "decision-v2", "text"])
def test_the_check_fails_when_one_output_moves_a_figure_by_a_tenth_of_a_point(figures: sf.FigureSet, output: str) -> None:
    out = outputs(figures)
    key = sf.key_of("OU", "Over", "2.5")
    p, *rest = out[output][key]
    out[output][key] = (p + 0.001, *rest)  # type: ignore[assignment]
    found = parity(out)
    assert len(found) == 1 and str(key) in found[0]


def test_the_check_fails_on_another_seal_or_version_or_a_missing_figure(figures: sf.FigureSet) -> None:
    out = outputs(figures)
    k1, k2, k3 = sf.key_of("1X2", "Home", 0), sf.key_of("DC", "1X", 0), sf.key_of("AH", "Home", -1)
    p, _, model, version = out["decision-v2"][k1]
    out["decision-v2"][k1] = (p, "sin_calibrar" if out["single_figure"][k1][1] == "calibrada" else "calibrada", model, version)
    p, seal, model, _ = out["C-01"][k2]
    out["C-01"][k2] = (p, seal, model, "forecast-v1")
    del out["text"][k3]
    assert len(parity(out)) == 3


# -- the text check: three adversarial cases (AD-B09's closing criterion) and the rest ----------------------------------------------

def readings(fs: sf.FigureSet) -> dict[str, float]:
    return {rid: f.p for rid, f in fs.by_reading().items()}


def test_a_text_that_repeats_its_cited_figures_is_accepted_with_any_rounding_it_states(figures: sf.FigureSet) -> None:
    f = figures.get("OU", "Over", "2.5")
    assert f is not None
    text = (f"Más de 2,5 goles: {ft.cite(f.reading_id, f.p, version=sf.VERSION)}; con un decimal, "
            f"{ft.cite(f.reading_id, f.p, version=sf.VERSION, decimals=1, comma=False)}.")
    v = ft.check(text, readings(figures), version=sf.VERSION)
    assert v.accepted and v.figures == 2


def test_three_seeded_texts_are_refused_a_figure_moved_a_tenth_one_without_citation_one_of_another_version(figures: sf.FigureSet) -> None:
    f = figures.get("OU", "Over", "2.5")
    assert f is not None
    shown = ft.rounded_pct(f.p, 1)
    moved = f"Más de 2,5 goles: {str(shown + Decimal('0.1')).replace('.', ',')} % [cifra {sf.VERSION} {f.reading_id}]."
    uncited = f"Más de 2,5 goles: {str(shown).replace('.', ',')} %."
    other = f"Más de 2,5 goles: {ft.cite(sf.reading_id('forecast-v1', FID, f.key, f.set_hash), f.p, version='forecast-v1', decimals=1)}."
    codes = [[p.code for p in ft.check(t, readings(figures), version=sf.VERSION).problems] for t in (moved, uncited, other)]
    assert codes == [[ft.MISMATCH], [ft.UNCITED], [ft.OTHER_VERSION]]


def test_a_citation_of_no_reading_and_a_citation_alone_are_refused(figures: sf.FigureSet) -> None:
    f = figures.get("BTTS", "Yes", 0)
    assert f is not None
    unknown = f"Ambos marcan: {ft.cite('0123456789ab', f.p, version=sf.VERSION)}."
    alone = f"Ambos marcan, según [cifra {sf.VERSION} {f.reading_id}]."
    assert [p.code for p in ft.check(unknown, readings(figures), version=sf.VERSION).problems] == [ft.UNKNOWN_READING]
    assert [p.code for p in ft.check(alone, readings(figures), version=sf.VERSION).problems] == [ft.ORPHAN]
    assert ft.check("Sin cifras: el equipo llega bien.", readings(figures), version=sf.VERSION).accepted


@pytest.mark.parametrize("p", [0.0, 0.004999, 0.005, 0.12345, 0.5, 0.57449, 0.5745, 0.785, 0.99951, 1.0])
def test_the_text_check_rounds_as_the_contract_does(p: float) -> None:
    for decimals in (0, 1):
        assert float(ft.rounded_pct(p, decimals)) == float(contract_rounded_pct(p, decimals)), (p, decimals)
