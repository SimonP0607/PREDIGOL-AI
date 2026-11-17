"""The base types and the closed vocabularies of every Intelligence contract (AD-J01, IA-057).

No database: the models are checked on their own. What a contract can say is fixed here once - an absence always has its
reason, a probability always its seal and the percentage the server rounded, a time always its zone - so that no contract
and no screen has to decide it again.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar, get_args

import pytest
from pydantic import ValidationError

from fbi.api.contracts.intelligence import vocab
from fbi.api.contracts.intelligence.base import (
    DatedFact,
    Freshness,
    IntelligenceContract,
    ItemList,
    MarketValidation,
    Missing,
    Probability,
    rounded_pct,
)
from fbi.picks.settlement import Status

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "owner" / "IA_057_CONTRATO_INTELLIGENCE.md"
AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)


# ── vocabularies ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_cycle_has_ten_states_and_a_reader_sees_three() -> None:
    assert len(vocab.VOCABULARIES["lifecycle_state"]) == 10
    assert vocab.VOCABULARIES["public_state"] == ("publicada", "en_juego", "liquidada")
    assert set(vocab.VOCABULARIES["public_state"]) - {"publicada"} <= set(vocab.VOCABULARIES["lifecycle_state"])


def test_every_list_is_closed_and_has_no_repeated_code() -> None:
    for name, codes in vocab.VOCABULARIES.items():
        assert codes and len(codes) == len(set(codes)), name
    assert set(vocab.VOCABULARIES["missing_reason"]) >= vocab.LIST_ONLY_REASONS
    assert all(code.isupper() for code in vocab.VOCABULARIES["abstention_code"]), "abstentions are upper case"
    assert "SIN_OBJETIVO_DEMOSTRADO" not in vocab.VOCABULARIES["abstention_code"]
    assert not set(vocab.VOCABULARIES["abstention_code"]) & set(vocab.VOCABULARIES["missing_reason"])


def test_settlement_results_are_the_ones_settle_v4_stores() -> None:
    assert set(get_args(vocab.SettlementResult)) == {s.value for s in Status}


@pytest.mark.parametrize("state", vocab.VOCABULARIES["lifecycle_state"])
def test_nothing_is_public_without_the_owners_authorisation(state: str) -> None:
    assert vocab.public_state_of(state, authorised=False) is None


def test_the_public_state_derives_from_the_cycle() -> None:
    derived = {s: vocab.public_state_of(s, authorised=True) for s in vocab.VOCABULARIES["lifecycle_state"]}
    assert derived == {"detectado": None, "en_investigacion": None, "en_evaluacion": None,
                       "pendiente_alineaciones": None, "confirmada_sombra": "publicada", "retirada": None,
                       "descartada": None, "en_juego": "en_juego", "liquidada": "liquidada", "evaluada": "liquidada"}
    with pytest.raises(ValueError, match="unknown lifecycle state"):
        vocab.public_state_of("publicada", authorised=True)


def test_the_owners_guide_lists_every_code() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    absent = [f"{name}: {code}" for name, codes in vocab.VOCABULARIES.items() for code in codes
              if f"`{code}`" not in text]
    assert not absent, f"the guide does not list: {absent}"


# ── absent with a reason ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_missing_field_says_only_what_its_reason_needs() -> None:
    assert Missing(missing_reason="no_entregado", expected_piece="AD-B02").model_dump(mode="json") == {
        "missing_reason": "no_entregado", "expected_piece": "AD-B02"}
    assert Missing(missing_reason="sin_datos").model_dump(mode="json") == {"missing_reason": "sin_datos"}
    wait = Missing(missing_reason="aun_no_disponible", expected_at=AT)
    assert wait.model_dump(mode="json") == {"missing_reason": "aun_no_disponible", "expected_at": "2026-11-21T16:42:00Z"}


@pytest.mark.parametrize(("data", "message"), [
    ({"missing_reason": "no_entregado"}, "no_entregado needs expected_piece"),
    ({"missing_reason": "aun_no_disponible"}, "aun_no_disponible needs expected_at"),
    ({"missing_reason": "muestra_insuficiente", "sample": 3}, "needs min_sample"),
    ({"missing_reason": "muestra_insuficiente", "sample": 5, "min_sample": 5}, "is not below min_sample"),
    ({"missing_reason": "sin_datos", "expected_piece": "AD-B02"}, "sin_datos does not take expected_piece"),
    ({"missing_reason": "sin_publicados"}, "reason of an empty list"),
    ({"missing_reason": "no_entregado", "expected_piece": "B02"}, "pattern"),
    ({"missing_reason": "olvidado"}, "missing_reason"),
    ({"missing_reason": "sin_datos", "why": "x"}, "Extra inputs"),
])
def test_a_missing_field_without_what_its_reason_needs_is_refused(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Missing.model_validate(data)


def test_a_list_says_why_exactly_when_it_is_empty() -> None:
    assert ItemList[int](items=[], missing_reason="sin_publicados").model_dump(mode="json") == {
        "items": [], "missing_reason": "sin_publicados"}
    assert ItemList[int](items=[1]).model_dump(mode="json") == {"items": [1]}
    ItemList[int](items=[], missing_reason="no_entregado", expected_piece="AD-D02")
    with pytest.raises(ValidationError, match="an empty list needs a missing_reason"):
        ItemList[int](items=[])
    with pytest.raises(ValidationError, match="carries no missing_reason"):
        ItemList[int](items=[1], missing_reason="sin_datos")
    with pytest.raises(ValidationError, match="no_entregado needs expected_piece"):
        ItemList[int](items=[], missing_reason="no_entregado")


# ── the sealed probability ───────────────────────────────────────────────────────────────────────────────────────────

def sealed(value: float, decimals: int = 0, **over: Any) -> Probability:
    data: dict[str, Any] = {"calibration": "calibrada", "as_of": AT, "origin": "forecast-v1", "evaluation": "E2",
                            "evaluation_version": 2, "interval": Missing(missing_reason="sin_datos")} | over
    return Probability.of(value, decimals=decimals, **data)


def test_the_server_rounds_half_up_and_only_once() -> None:
    assert rounded_pct(0.785) == 79 and rounded_pct(0.785, 1) == 78.5
    assert rounded_pct(0.575) == 58 and rounded_pct(0.5749) == 57 and rounded_pct(0.59) == 59
    assert sealed(0.59).pct == 59 and isinstance(sealed(0.59).pct, int)
    assert sealed(0.785, 1).model_dump(mode="json")["pct"] == 78.5
    with pytest.raises(ValueError, match="0 or 1 decimals"):
        rounded_pct(0.5, 2)


def test_a_percentage_the_server_did_not_round_from_the_value_is_refused() -> None:
    data = sealed(0.59).model_dump(mode="json")
    with pytest.raises(ValidationError, match=r"pct 60 is not 0\.59 rounded"):
        Probability.model_validate(data | {"pct": 60})
    with pytest.raises(ValidationError, match=r"pct 58\.9"):
        Probability.model_validate(data | {"pct": 58.9})


def test_the_seal_is_whole() -> None:
    assert sealed(0.59, interval=(52, 66)).interval_pct.model_dump() == {"low": 52, "high": 66}
    with pytest.raises(ValidationError, match="outside its interval"):
        sealed(0.59, interval=(60, 66))
    with pytest.raises(ValidationError, match="both given or both missing"):
        sealed(0.59, evaluation=Missing(missing_reason="no_entregado", expected_piece="AD-D06"))
    before_evaluations = sealed(0.59, evaluation=Missing(missing_reason="no_entregado", expected_piece="AD-D06"),
                                evaluation_version=Missing(missing_reason="no_entregado", expected_piece="AD-D06"))
    assert before_evaluations.model_dump(mode="json")["evaluation"] == {"missing_reason": "no_entregado",
                                                                        "expected_piece": "AD-D06"}
    with pytest.raises(ValidationError, match="calibration"):
        sealed(0.59, calibration="calibrado")
    with pytest.raises(ValidationError, match="starts at 1"):
        sealed(0.59, evaluation_version=0)


def test_times_carry_their_zone_and_are_served_in_utc() -> None:
    bogota = timezone(timedelta(hours=-5))
    assert sealed(0.5, as_of=datetime(2026, 11, 21, 11, 42, tzinfo=bogota)).model_dump(mode="json")["as_of"] == (
        "2026-11-21T16:42:00Z")
    with pytest.raises(ValidationError, match="timezone"):
        Probability.model_validate(sealed(0.5).model_dump(mode="json") | {"as_of": "2026-11-21T16:42:00"})


# ── dates, freshness, validation ─────────────────────────────────────────────────────────────────────────────────────

def test_a_day_only_date_is_a_day() -> None:
    midnight = datetime(2026, 11, 21, tzinfo=UTC)
    gone = Missing(missing_reason="sin_datos")
    DatedFact(published_at=midnight, published_day_only=True, known_at=AT, fact_at=gone, valid_until=gone)
    with pytest.raises(ValidationError, match="published_day_only needs published_at at 00:00 UTC"):
        DatedFact(published_at=AT, published_day_only=True, known_at=AT, fact_at=gone, valid_until=gone)
    with pytest.raises(ValidationError, match="fact_day_only"):
        DatedFact(published_at=gone, known_at=AT, fact_at=gone, fact_day_only=True, valid_until=gone)
    with pytest.raises(ValidationError, match="known_at"):
        DatedFact.model_validate({"published_at": gone.model_dump(), "fact_at": gone.model_dump(),
                                  "valid_until": gone.model_dump()})


def test_the_server_says_when_an_answer_is_old() -> None:
    assert Freshness(generated_at=AT, stale=False).model_dump(mode="json") == {
        "generated_at": "2026-11-21T16:42:00Z", "stale": False, "stale_reason": None}
    Freshness(generated_at=AT, stale=True, stale_reason="price_too_old")
    with pytest.raises(ValidationError, match="exactly when stale"):
        Freshness(generated_at=AT, stale=True)
    with pytest.raises(ValidationError, match="exactly when stale"):
        Freshness(generated_at=AT, stale=False, stale_reason="price_too_old")


def test_a_verdict_agrees_with_its_sample() -> None:
    MarketValidation(verdict="INSUFICIENTE", sample=37, needed=400)
    MarketValidation(verdict="NO_VALIDADO", sample=400, needed=400)
    for verdict, sample in (("VALIDADO", 37), ("NO_VALIDADO", 12), ("INSUFICIENTE", 400)):
        with pytest.raises(ValidationError, match="does not agree"):
            MarketValidation(verdict=verdict, sample=sample, needed=400)  # type: ignore[arg-type]


# ── the head of every contract ───────────────────────────────────────────────────────────────────────────────────────

class Tiny(IntelligenceContract):
    CONTRACT_ID: ClassVar[str] = "C-99"
    CONTRACT_VERSION: ClassVar[str] = "2.1.0"

    note: str


def test_every_answer_says_its_contract_version_and_projection() -> None:
    answer = Tiny(freshness=Freshness(generated_at=AT, stale=False), note="x")
    assert answer.model_dump(mode="json") == {
        "contract": "C-99", "contract_version": "2.1.0", "projection": "public",
        "freshness": {"generated_at": "2026-11-21T16:42:00Z", "stale": False, "stale_reason": None}, "note": "x"}
    data = answer.model_dump(mode="json")
    with pytest.raises(ValidationError, match=r"C-99 2\.0\.0 is not C-99 2\.1\.0"):
        Tiny.model_validate(data | {"contract_version": "2.0.0"})
    with pytest.raises(ValidationError, match="is the public projection, not private"):
        Tiny.model_validate(data | {"projection": "private"})
    with pytest.raises(ValidationError, match="Extra inputs"):
        Tiny.model_validate(data | {"secret": 1})
    assert re.fullmatch(r"\d+\.\d+\.\d+", answer.contract_version)
