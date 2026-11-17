"""AD-J07 (IA-133): contract C-08 «Evaluación posterior».

The rows of ``intel.selection_evaluations`` here are made by ``eval-sel-v1`` itself (``fbi.evaluation.selection.evaluate``) and read back
as the statement of the service reads them, so the six answers are tested against what the evaluation really writes. The examples
(``tests/fixtures/contracts/intelligence/C-08``) are made by the service's builder and held equal to it (``FBI_WRITE_EXAMPLES=1``
rewrites them). Here: a win without value (SUERTE), a loss with value (VARIANZA), a void (NULO, not scored), the six questions answered or
absent with their reason, the fixed notice, a verdict always with its sample, and a database without the table.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.api.contracts.intelligence.base import Missing
from fbi.api.contracts.intelligence.post_evaluation import NOTICE, PostMatchEvaluation
from fbi.api.services import post_evaluation as svc
from fbi.evaluation import board as board_module
from fbi.evaluation import selection as ev

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence" / "C-08"
AT = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
KO = datetime(2026, 11, 21, 20, 0, tzinfo=UTC)
FIXTURE: dict[str, Any] = {"id": 990001, "kickoff_at": KO, "status_short": "FT", "status_group": "finished",
                           "round": "Regular Season - 12", "venue_name": "Estadio Ejemplo", "home_team_id": 9101,
                           "home_name": "Atlético Ejemplo", "away_team_id": 9102, "away_name": "Deportivo Muestra",
                           "competition_id": 39, "competition": "Liga Ejemplo", "country": "Ejemplia"}


def inputs(n: int, *, market: str, selection: str, line: str, result: str, odds: str, close: str, p_cal: float | None,
           facts: tuple[ev.Fact, ...] = (), before: ev.Point | None = None) -> ev.Inputs:
    decided = ev.Decided(layer="decision-v1", source="intel.decisions", decision_id=770000 + n, fixture_id=990001, market_key=market,
                         selection=selection, line=Decimal(line), known_at=KO - timedelta(minutes=40), kickoff_at=KO, checkpoint="lineups",
                         state="APROBADO", p_model=0.61, p_cal=p_cal, p_market=0.52, odds=Decimal(odds),
                         evidence_ids=tuple(f.id for f in facts))
    settled = ev.Settled(result=result, settled_at=KO + timedelta(hours=2), source="intel.decision_outcomes", version="settle-v4",
                         close_p_fair=Decimal(close), close_minutes_to_ko=5,
                         stored_clv=(Decimal(odds) * Decimal(close) - 1).quantize(ev.CLV_Q))
    players = {5501: ev.PlayerDay(in_squad=True, starter=True, minutes=90), 5503: ev.PlayerDay(in_squad=True, starter=False, minutes=12)}
    match = ev.Match(status="FT", reg_home=2, reg_away=1, lineup_at=KO - timedelta(minutes=55), players=players, rederived=None)
    return ev.Inputs(decided=decided, settled=settled, match=match, facts=facts, before_lineup=before, estimate=(9, 11))


def row_of(i: ev.Inputs, n: int) -> dict[str, Any]:
    """An evaluation as ``ROWS_SQL`` reads it back (numbers as float8)."""
    e = ev.evaluate(i)
    row: dict[str, Any] = {k: (float(v) if isinstance(v, Decimal) and k != "line" else v) for k, v in e.row.items()}
    return row | {"id": 880000 + n, "detail": json.loads(json.dumps(dict(e.detail))), "created_at": AT}


FACTS = (ev.Fact(id=660001, kind="injury", assertion="out", provider_player_id=5502),
         ev.Fact(id=660002, kind="lineup", assertion="starts", provider_player_id=5501),
         ev.Fact(id=660003, kind="news", assertion=None, provider_player_id=None))


def rows() -> dict[str, dict[str, Any]]:
    return {
        # a win at a price that the close made bad: SUERTE - a hit is never value
        "ganada_sin_valor": row_of(inputs(1, market="1X2", selection="Home", line="0", result="win", odds="1.80", close="0.52",
                                          p_cal=0.57, facts=FACTS,
                                          before=ev.Point(known_at=KO - timedelta(hours=12), state="CAUTELA", p=0.55)), 1),
        # a loss at a price the close confirmed: VARIANZA
        "perdida_con_valor": row_of(inputs(2, market="OU", selection="Over", line="2.5", result="loss", odds="2.10", close="0.52",
                                           p_cal=None), 2),
        # a void: NULO, not scored
        "anulada": row_of(inputs(3, market="AH", selection="Home", line="-1", result="void", odds="1.95", close="0.50", p_cal=0.53), 3),
    }


def board_over(rs: list[dict[str, Any]]) -> dict[str, Any]:
    return board_module.build(board_module.from_rows(rs))


def cases() -> dict[str, PostMatchEvaluation]:
    out = {}
    for case, r in rows().items():
        out[case] = svc.assemble(at=AT, fixture=FIXTURE, rows=[r], board=board_over(list(rows().values())))
    out["sin_evaluaciones"] = svc.assemble(at=AT, fixture=FIXTURE, rows=None, board=None)
    return out


def dumped(model: Any) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


def test_the_examples_are_what_the_builder_makes() -> None:
    files = {EXAMPLES / f"{case}.private.json": dumped(m) for case, m in cases().items()}
    if os.environ.get("FBI_WRITE_EXAMPLES") == "1":
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for path, data in files.items():
        assert json.loads(path.read_text(encoding="utf-8")) == data, path.name


def one(case: str) -> Any:
    return cases()[case].selections.items[0]


def test_a_win_without_value_is_luck_and_says_a_hit_validates_nothing() -> None:
    s = one("ganada_sin_valor")
    assert (s.happened.result, s.happened.hit, s.price.quality, s.price.verdict) == ("win", True, "BAD", "SUERTE")
    assert s.price.clv_pct == -6.4 and s.notice_es == NOTICE == "Un acierto no valida el mercado."
    assert cases()["ganada_sin_valor"].notice_es == NOTICE
    assert s.anticipated.probability.calibration == "calibrada" and s.anticipated.probability.pct == 57.0
    assert not isinstance(s.happened.scores, Missing)


def test_a_loss_with_value_is_variance_and_an_uncalibrated_figure_says_so() -> None:
    s = one("perdida_con_valor")
    assert (s.happened.result, s.happened.hit, s.price.quality, s.price.verdict) == ("loss", False, "GOOD", "VARIANZA")
    assert s.price.clv_pct == 9.2 and s.anticipated.probability.calibration == "sin_calibrar"
    assert s.anticipated.probability.origin == "decision-v1"


def test_a_void_is_null_and_not_scored() -> None:
    s = one("anulada")
    assert (s.happened.result, s.happened.hit, s.price.verdict) == ("void", None, "NULO")
    assert isinstance(s.happened.scores, Missing)


def test_the_six_questions_are_answered_or_absent_with_their_reason() -> None:
    s = one("ganada_sin_valor")
    assert s.anticipated.market_pct == 52.0 and s.anticipated.cycle_state == "confirmada_sombra" and s.anticipated.taken
    assert (s.evidence.held, s.evidence.contradicted, s.evidence.unevaluable) == (2, 0, 1)
    assert [(f.id, f.status, f.why) for f in s.evidence.facts.items] == [
        (660001, "sostenido", "no_jugo"), (660002, "sostenido", "fue_titular"), (660003, "no_evaluable", "sin_regla")]
    assert (s.lineup.changed, s.lineup.why, s.lineup.state_before) == (True, "comparada", "CAUTELA")
    assert not isinstance(s.lineup.estimate, Missing) and s.lineup.estimate.hits == 9
    assert isinstance(s.scenario, Missing) and (s.scenario.missing_reason, s.scenario.expected_piece) == ("no_entregado", "AD-B02")
    no_facts = one("perdida_con_valor")
    assert no_facts.evidence.facts.missing_reason == "sin_datos"


def test_a_verdict_travels_with_its_sample_and_the_calibration_is_the_board_s() -> None:
    m = cases()["ganada_sin_valor"]
    s = m.selections.items[0]
    assert not isinstance(s.validation, Missing)
    assert (s.validation.verdict, s.validation.needed) == ("INSUFICIENTE", 300) and s.validation_cell == "decision-v1|core|1X2"
    cells = [c.cell for c in m.calibration.items]
    assert cells == ["decision-v1|core|1X2", "decision-v1|core|*"]
    assert all(c.verdict == "INSUFICIENTE" and c.sample < c.needed for c in m.calibration.items)
    assert not isinstance(m.board, Missing) and m.board.version == "board-v1" and not m.board.signed_by_owner


def test_a_database_without_the_table_says_so_block_by_block() -> None:
    m = cases()["sin_evaluaciones"]
    assert m.selections.missing_reason == "sin_datos" and m.calibration.missing_reason == "sin_datos"
    assert isinstance(m.board, Missing) and m.match.id == 990001 and m.match.phase == "terminado"


def test_an_unknown_match_is_a_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.api.problem import ApiError

    monkeypatch.setattr(svc, "fetch_one", lambda conn, sql, params: None)
    with pytest.raises(ApiError) as caught:
        svc.evaluation(None, 1)  # type: ignore[arg-type]
    assert caught.value.status == 404


def test_the_service_reads_its_own_version_of_the_evaluations_only() -> None:
    assert "FROM intel.selection_evaluations" in svc.ROWS_SQL and "version = %(v)s" in svc.ROWS_SQL
    assert "INSERT" not in svc.ROWS_SQL.upper() and svc.BOARD_DAYS == 30
    assert svc.origin_of("decision-fam-v1") == "decision_fam-v1" and svc.origin_of("decision-v2") == "decision-v2"
