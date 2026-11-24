"""C-11 1.1 (AP-A04, AP-A05): every reason the research writes has its code, read from the very sentences
``fbi.research.roles.model_role`` and ``fbi.research.v2_record`` produce - so a change of wording that loses a code fails
here, not in the console. An unknown sentence has no code."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast, get_args

import pytest

from fbi.api.contracts.research import ResearchEntry
from fbi.research.reason_codes import CODES, ReasonCode, reason_code
from fbi.research.roles import model_role
from fbi.research.v2_record import prospective_role


def comparison(mean: float, lo: float, hi: float, n: int = 1700, blocks: int = 60) -> Any:
    verdict = "better" if hi < 0 else "worse" if lo > 0 else "inconclusive"
    return SimpleNamespace(logloss_diff=SimpleNamespace(mean=mean, lo=lo, hi=hi), n_common=n, verdict=verdict,
                           n_blocks=blocks)


def blend(w: float, lo: float, hi: float, *, beats: bool) -> Any:
    return SimpleNamespace(w_test=w, w_test_lo=lo, w_test_hi=hi, adds_information=lo > 0, blend_beats_market=beats,
                           diff_mean=-0.01 if beats else 0.01, diff_lo=-0.02 if beats else 0.0,
                           diff_hi=-0.001 if beats else 0.02)


@pytest.mark.parametrize(("vs", "bl", "role", "code"), [
    (None, None, "RESEARCH", "sin_partidos_comunes"),
    (comparison(-0.02, -0.03, -0.01), None, "CHALLENGER", "mejor_que_mercado"),
    (comparison(0.01, -0.01, 0.02), blend(0.3, 0.1, 0.5, beats=True), "CHALLENGER", "aporta_informacion"),
    (comparison(0.02, 0.01, 0.03), blend(0.0, -0.1, 0.1, beats=False), "REJECTED", "rechazado_peor_que_mercado"),
    (comparison(0.02, 0.01, 0.03), None, "REJECTED", "rechazado_peor_que_mercado"),
    (comparison(0.0, -0.01, 0.01), None, "RESEARCH", "evidencia_insuficiente"),
])
def test_each_role_of_a_model_has_its_code(vs: Any, bl: Any, role: str, code: str) -> None:
    r = model_role(cast(Any, vs), cast(Any, bl), champion="pinnacle/closing/shin")
    assert (r.role, reason_code(r.reason)) == (role, code)


def segment(n: int, c: Any, w: tuple[float, float, float] | None, *, judged: bool) -> Any:
    return SimpleNamespace(comparison=c, judged=judged, n_common=n, w=w)


@pytest.mark.parametrize(("seg", "role", "code"), [
    (segment(12, comparison(0.0, -0.1, 0.1, n=12, blocks=3), None, judged=False), "RESEARCH", "muestra_insuficiente"),
    (segment(0, None, None, judged=False), "RESEARCH", "muestra_insuficiente"),
    (segment(400, comparison(-0.02, -0.03, -0.01, n=400), None, judged=True), "CHALLENGER", "mejor_que_mercado"),
    (segment(400, comparison(0.02, 0.01, 0.03, n=400), (0.0, -0.1, 0.1), judged=True), "REJECTED",
     "rechazado_peor_que_mercado"),
    (segment(400, comparison(0.0, -0.01, 0.01, n=400), None, judged=True), "RESEARCH", "evidencia_insuficiente"),
])
def test_each_role_of_a_prospective_segment_has_its_code(seg: Any, role: str, code: str) -> None:
    got_role, reason = prospective_role(cast(Any, seg))
    assert (got_role, reason_code(reason)) == (role, code)


def test_the_two_market_reasons_have_their_codes() -> None:
    assert reason_code("lowest log loss of the de-vigged market baselines, 0.95000 on the 1700 fixtures every one of "
                       "them priced") == "campeon_mercado"
    assert reason_code("a market variant: log loss 0.96000, +0.01000 against the champion on the same 1700 "
                       "fixtures") == "variante_mercado"


@pytest.mark.parametrize("reason", [None, "", "because", "12 matches with a forecast", "Worse than the champion"])
def test_an_unknown_reason_has_no_code(reason: str | None) -> None:
    assert reason_code(reason) is None


def test_the_codes_are_the_contracts_and_an_older_entry_still_reads() -> None:
    assert get_args(ReasonCode) == CODES
    base = {"experiment_id": 1, "name": "x", "kind": "backtest", "model_family": "m", "role": None, "role_reason": None,
            "segment": None, "finished_at": None, "data_as_of": None, "metrics": {}}
    for code in CODES:
        assert ResearchEntry.model_validate(base | {"role_reason_code": code}).role_reason_code == code
    with pytest.raises(ValueError):
        ResearchEntry.model_validate(base | {"role_reason_code": "worse"})
    old = {"experiment_id": 1, "name": "x", "kind": "backtest", "model_family": "m", "role": "REJECTED",
           "role_reason": "worse than the champion and adds nothing to it", "segment": None, "finished_at": None,
           "data_as_of": None, "metrics": {}}
    entry = ResearchEntry.model_validate(old)  # an answer without the new field (the API before C-11 1.1)
    assert entry.role_reason_code is None
