"""AD-E01 (IA-070): the catalogue of markets with a state - the rules one by one, the two that may never be broken (no settlement rule,
a single house: never evaluable), the catalogue built from the taxonomy, the snapshot the product reads and its reader."""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest

from fbi.api.contracts.intelligence.vocab import MarketState
from fbi.api.services import market_status as ms
from fbi.market.rules import RULES, RULES_BY_KEY
from fbi.odds.quote_taxonomy import EXTRACTED, spec_for

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "tests" / "fixtures" / "contracts" / "market_states"
"""Outside ``contracts/intelligence/``: a rule key (``corners_ft@v1``) reads as an e-mail address to its no-real-person check."""
LAB_FACTS = ROOT / "docs" / "owner" / "lab" / "IA_070" / "facts_20261117T0230Z.json"
LAB_AT = datetime(2026, 11, 17, 2, 30, tzinfo=UTC)

CORNERS = ms.CatalogEntry(key="CORNERS_OU", name="Corners Over Under", family="corners", period="FT", subject="match",
                          kind="over_under", bet_ids=(45,), extracted=True, rule_key="corners_ft@v1", rule_reason="ok")
FULL = ms.Evidence(priced_fixtures=500, books_median=5.0, fixtures_3_books=450, books_max=6, priced_finished=400, settleable=380,
                   model_fixtures=300, champions=("poisson",), rule_registered=True)


def judged(entry: ms.CatalogEntry = CORNERS, **changes: Any) -> tuple[str, str]:
    return ms.judge(entry, replace(FULL, **changes))


# ── the closed lists ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_reason_gives_one_state_of_the_contract_vocabulary() -> None:
    assert tuple(ms.REASONS) == get_args(ms.Reason)
    assert set(ms.REASONS.values()) == set(get_args(MarketState))
    assert [r for r, s in ms.REASONS.items() if s == "evaluable"] == ["completo"]


# ── each rule ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_market_with_everything_is_evaluable() -> None:
    assert judged() == ("evaluable", "completo")


def test_without_a_validated_calibrator_it_is_in_calibration() -> None:
    assert judged(champions=()) == ("en_calibracion", "sin_calibrador_validado")


def test_without_a_model_it_needs_data() -> None:
    assert judged(model_fixtures=0, champions=()) == ("necesita_datos", "sin_modelo")


def test_fewer_than_three_houses_needs_data() -> None:
    assert judged(books_median=2.0) == ("necesita_datos", "menos_de_3_casas")
    assert judged(books_median=1.0) == ("necesita_datos", "menos_de_3_casas")
    assert judged(books_median=None) == ("necesita_datos", "menos_de_3_casas")
    assert judged(books_median=3.0) == ("evaluable", "completo"), "three houses are enough"


def test_settlement_not_yet_seen_on_real_results_needs_data() -> None:
    assert judged(priced_finished=ms.MIN_SETTLE_SAMPLE - 1, settleable=ms.MIN_SETTLE_SAMPLE - 1) == (
        "necesita_datos", "liquidacion_sin_muestra")


def test_results_for_less_than_half_of_the_priced_matches_is_not_offered() -> None:
    assert judged(priced_finished=100, settleable=49) == ("no_ofrecer", "sin_datos_de_resultado")
    assert judged(priced_finished=100, settleable=50) == ("evaluable", "completo"), "half is the bar (TESIS §E)"


def test_no_price_at_all_is_not_offered() -> None:
    assert judged(priced_fixtures=0, books_median=None) == ("no_ofrecer", "sin_cuotas")


def test_a_rule_missing_from_the_database_is_not_offered() -> None:
    assert judged(rule_registered=False) == ("no_ofrecer", "regla_no_registrada")


def test_without_a_settlement_rule_it_is_not_offered() -> None:
    no_rule = replace(CORNERS, key="bet_77", rule_key=None, rule_reason="no_period_data")
    assert ms.judge(no_rule, FULL) == ("no_ofrecer", "sin_regla_liquidacion")
    not_liquidable = replace(CORNERS, rule_key="corners_1h@v1")
    assert not RULES_BY_KEY["corners_1h@v1"].liquidable
    assert ms.judge(not_liquidable, FULL) == ("no_ofrecer", "sin_regla_liquidacion")
    unknown = replace(CORNERS, rule_key="corners_ft@v9")
    assert ms.judge(unknown, FULL) == ("no_ofrecer", "sin_regla_liquidacion"), "a rule the code does not have grades nothing"


def test_out_of_scope_families_are_not_offered() -> None:
    timing = replace(CORNERS, key="bet_14", family="timing", rule_key=None, rule_reason="out_of_scope")
    assert ms.judge(timing, FULL) == ("no_ofrecer", "fuera_de_alcance")


def test_player_markets_wait_for_a_reliable_line_up_evaluation() -> None:
    """Decision 7. Today no player bet has a rule (``player_level``), so they are not offered; the day AD-E04 writes one they
    still wait for the line-up evaluation, and only the reviewed constant lets them through."""
    player_today = replace(CORNERS, key="bet_92", family="players", subject="player", rule_key=None, rule_reason="player_level")
    assert ms.judge(player_today, FULL) == ("no_ofrecer", "sin_regla_liquidacion")
    player_with_rule = replace(player_today, rule_key="shots_ft@v1")
    assert ms.judge(player_with_rule, FULL) == ("necesita_datos", "pendiente_alineaciones")
    assert ms.judge(player_with_rule, FULL, lineup_reliable=True) == ("evaluable", "completo")


# ── the two that may never be broken, over every combination of facts ───────────────────────────────────────────────

GRID = [ms.Evidence(priced_fixtures=p, books_median=b, fixtures_3_books=p, books_max=int(b or 0), priced_finished=f, settleable=s,
                    model_fixtures=m, champions=c, rule_registered=r)
        for p, b, f, s, m, c, r in itertools.product((0, 1, 500), (None, 1.0, 2.0, 2.5, 3.0, 9.0), (0, 29, 400), (0, 150, 400),
                                                    (0, 300), ((), ("poisson",)), (False, True))
        if s <= f]


def test_no_market_without_a_liquidable_settlement_rule_is_ever_evaluable() -> None:
    entries = [replace(CORNERS, rule_key=None), replace(CORNERS, rule_key="corners_2h@v1"), replace(CORNERS, rule_key="nope@v1")]
    for entry, ev in itertools.product(entries, GRID):
        assert ms.judge(entry, ev, lineup_reliable=True) == ("no_ofrecer", "sin_regla_liquidacion")


def test_a_single_house_is_never_evaluable() -> None:
    for ev in GRID:
        if ev.books_median is not None and ev.books_median < ms.MIN_BOOKS:
            assert ms.judge(CORNERS, ev, lineup_reliable=True)[0] != "evaluable"


# ── the catalogue from the taxonomy ─────────────────────────────────────────────────────────────────────────────────

def test_every_extracted_bet_is_in_exactly_one_market_and_the_five_keep_their_keys() -> None:
    entries = ms.entries(EXTRACTED)
    seen = [b for e in entries for b in e.bet_ids]
    assert sorted(seen) == sorted(s.bet_id for s in EXTRACTED)
    keys = {e.key for e in entries}
    assert {"1X2", "OU", "BTTS", "DC", "AH"} <= keys
    corners_dc = next(e for e in entries if e.key == "CORNERS_DC")
    assert corners_dc.bet_ids == (307, 339), "the provider lists corners double chance twice: one market"
    assert all(e.rule_key is not None for e in entries), "every extracted bet has a liquidable rule"


def test_a_bet_with_no_key_is_its_own_market_and_has_no_rule() -> None:
    entries = ms.entries([spec_for(92, "Anytime Goal Scorer"), spec_for(77, "Total Corners (1st Half)")])
    assert [(e.key, e.rule_key, e.rule_reason) for e in entries] == [
        ("bet_77", None, "no_period_data"), ("bet_92", None, "player_level")]


def test_the_price_query_reads_every_liquidable_rule() -> None:
    for rule in RULES:
        assert (f"'{rule.key}'" in ms.PRICES_SQL) == rule.liquidable
    assert [q[0] for q in ms.queries(LAB_AT)] == ["definitions", "prices", "models", "champions", "rules", "discovery"]


# ── the snapshot the product reads (the closing criterion, in CI) ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def snapshot_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(ms.SNAPSHOT.read_text(encoding="utf-8"))
    return data


def test_the_snapshot_has_a_state_and_a_reason_for_every_market_of_the_book(snapshot_data: dict[str, Any]) -> None:
    catalogue = ms.parse_snapshot(snapshot_data)
    for spec in EXTRACTED:
        m = catalogue.for_bet(spec.bet_id)
        assert m.reason != "fuera_del_catalogo", f"bet {spec.bet_id} is not in the catalogue"
        assert ms.REASONS[m.reason] == m.state
    for m in snapshot_data["markets"]:
        if m["evidence"]["priced_fixtures"] > 0:
            assert m["state"] in ms.States and m["reason"] in ms.REASONS


def test_no_market_of_the_snapshot_is_evaluable_without_a_rule_three_houses_and_a_champion(snapshot_data: dict[str, Any]) -> None:
    for m in snapshot_data["markets"]:
        if m["state"] == "evaluable":
            rule = RULES_BY_KEY.get(m["rule_key"] or "")
            assert rule is not None and rule.liquidable, m["key"]
            assert m["evidence"]["books_median"] >= ms.MIN_BOOKS and m["evidence"]["champions"], m["key"]


def test_the_stored_states_are_the_ones_this_code_gives(snapshot_data: dict[str, Any]) -> None:
    catalogue = ms.parse_snapshot(snapshot_data)
    assert snapshot_data["catalog_version"] == ms.CATALOG_VERSION
    for m in snapshot_data["markets"]:
        got = catalogue.status(m["key"])
        assert (got.state, got.reason) == (m["state"], m["reason"]), f"{m['key']}: run scripts.ia_market_states and review the diff"
    assert snapshot_data["counts"] == {s: sum(1 for m in snapshot_data["markets"] if m["state"] == s) for s in ms.States}


def test_the_snapshot_file_is_written_in_its_canonical_form(snapshot_data: dict[str, Any]) -> None:
    assert ms.dump_snapshot(snapshot_data) == ms.SNAPSHOT.read_text(encoding="utf-8")


def test_the_snapshot_is_the_measurement_of_17_nov_judged_by_this_code(snapshot_data: dict[str, Any]) -> None:
    """Repetition: the production export (six read-only queries, 17-nov-2026 02:30 UTC) rebuilds the snapshot exactly."""
    if snapshot_data["measured_at"] != "2026-11-17T02:30:00Z":
        pytest.skip("the snapshot was measured again; this repetition belongs to the measurement of 17-nov")
    facts = ms.facts_from_rows(LAB_AT, json.loads(LAB_FACTS.read_text(encoding="utf-8")))
    assert json.loads(json.dumps(ms.snapshot(facts, ms.build(facts)))) == snapshot_data


# ── the reader ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_reader_answers_by_key_by_bet_and_for_a_market_of_the_match_catalogue() -> None:
    catalogue = ms.load_catalogue()
    assert catalogue.for_bet(339).key == catalogue.for_bet(307).key == "CORNERS_DC"
    assert catalogue.for_market("CORNERS_OU").key == "CORNERS_OU"
    assert catalogue.for_market(None, [92]).key == "bet_92"
    unknown = catalogue.status("NOT_A_MARKET")
    assert (unknown.state, unknown.reason) == ("no_ofrecer", "fuera_del_catalogo")
    view = catalogue.view("CORNERS_OU")
    assert view.catalog_version == ms.CATALOG_VERSION and view.state == catalogue.status("CORNERS_OU").state


def test_the_reader_judges_again_and_never_trusts_a_stored_state(snapshot_data: dict[str, Any]) -> None:
    """A snapshot edited by hand to call a market evaluable does not make it so."""
    forged = json.loads(json.dumps(snapshot_data))
    for m in forged["markets"]:
        if m["key"] == "CORNERS_OU":
            m["state"], m["reason"] = "evaluable", "completo"
        if m["key"] == "OU":
            m["rule_key"] = None
    catalogue = ms.parse_snapshot(forged)
    assert catalogue.status("CORNERS_OU").state != "evaluable"
    assert catalogue.status("OU").state == "no_ofrecer"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_the_contract_examples_validate_and_round_trip(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    view = ms.MarketStatusView.model_validate(raw)
    assert json.loads(view.model_dump_json()) == raw
    assert path.name.split(".")[0] == view.state


def test_the_view_refuses_an_incoherent_state() -> None:
    raw = json.loads((EXAMPLES / "en_calibracion.private.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        ms.MarketStatusView.model_validate({**raw, "state": "evaluable"})
    with pytest.raises(ValueError):
        ms.MarketStatusView.model_validate({**raw, "state": "evaluable", "reason": "completo"})  # no validated calibrator
    with pytest.raises(ValueError):
        ms.MarketStatusView.model_validate({**raw, "reason": "inventado"})


def test_facts_from_an_export_and_from_rows_agree() -> None:
    rows = {"definitions": [{"provider_bet_id": 45, "name": "Corners Over Under"}],
            "prices": [{"key": "CORNERS_OU", "priced": 40, "books_median": 5, "priced_3": 38, "books_max": 6, "finished": 35,
                        "settleable": 30, "base": 50}],
            "models": [{"market_key": "CORNERS_OU", "fixtures": 33}], "champions": [],
            "rules": [{"rule_key": "corners_ft@v1", "liquidable": True}], "discovery": [[45, 40.0, 5.0]]}
    exported = {**rows, "definitions": [[45, "Corners Over Under", "CORNERS_OU", "corners_ft@v1"]]}
    a, b = ms.facts_from_rows(LAB_AT, rows), ms.facts_from_rows(LAB_AT, exported)
    assert a == b and a.base_fixtures == 50
    [status] = ms.build(a)
    assert (status.key, status.state, status.reason) == ("CORNERS_OU", "en_calibracion", "sin_calibrador_validado")
    assert status.evidence.settleable_share == pytest.approx(30 / 35)
