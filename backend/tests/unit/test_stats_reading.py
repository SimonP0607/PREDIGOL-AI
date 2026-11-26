"""RP-6.1: what Intelligence reads of the statistics documents - the figure as the document holds it, with its sample, calculation, identifier
and date; the document in force at a cut-off; a figure the document does not publish is not a value."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.stats import reading as rd
from fbi.stats import team as st
from tests.unit.test_stats_documents import body_of, league

T = datetime(2034, 6, 1, 7, 20, tzinfo=UTC)


def row_of(body: dict[str, Any], *, computed_at: datetime = T, kind: str = "team", scope: str = "u10", context: str = "all") -> dict[str, Any]:
    return {"kind": kind, "entity_id": 100, "competition_season_id": 1, "scope": scope, "context": context, "calc_version": "stats-docs-v1",
            "sample": 10, "doc": body, "computed_at": computed_at}


def a_team_doc() -> dict[str, Any]:
    docs, _, _ = st.season_documents(league())
    return next(d.body for d in docs if d.team_id == 100 and d.scope == "u10" and d.context == "all")


def test_every_figure_of_a_team_document_is_read_equal_to_what_c13_validates() -> None:
    body = a_team_doc()
    contract = body_of(body)
    doc = rd.document_of(row_of(body))
    assert doc.status == "ok" and [r.key for r in doc.readings] == [f.key for f in contract.figures]
    for r, f in zip(doc.readings, contract.figures, strict=True):
        assert (r.key, r.unit, r.better, r.matches_with_data) == (f.key, f.unit, f.better, f.matches_with_data)
        expected = None if not isinstance(f.value, (int, float)) else float(f.value)
        assert r.value == expected
        assert (r.value is None) == (r.missing_reason is not None), "a missing figure says why, a value has no reason"


def test_a_figure_the_document_does_not_publish_is_not_a_value_and_says_why() -> None:
    body = {"figures": [{"key": "xg_for", "unit": "por_partido", "better": "more", "value": {"missing_reason": "sin_cobertura"},
                         "matches_with_data": 3, "percentile": {"missing_reason": "sin_datos"}, "league_value": 1.2},
                        {"key": "goals_for", "unit": "por_partido", "better": "more", "value": 1.6, "matches_with_data": 10,
                         "percentile": 70, "league_value": 1.3}]}
    doc = rd.document_of(row_of(body))
    xg, goals = doc.get("xg_for"), doc.get("goals_for")
    assert xg is not None and xg.value is None and xg.missing_reason == "sin_cobertura" and xg.percentile is None
    assert goals is not None and goals.value == 1.6 and goals.percentile == 70 and goals.league_value == 1.3
    assert doc.value("xg_for") is None and doc.citation("xg_for") is None, "nothing is cited without a value"
    assert doc.value("nope") is None and doc.get("nope") is None


def test_a_document_computed_after_the_cutoff_is_not_read() -> None:
    body = a_team_doc()
    after = rd.document_of(row_of(body, computed_at=T), as_of=T - timedelta(seconds=1))
    assert after.status == "after_cutoff" and after.readings == () and after.document_id is None
    on_time = rd.document_of(row_of(body, computed_at=T), as_of=T)
    assert on_time.status == "ok" and on_time.readings
    assert rd.document_of(row_of(body, computed_at=T)).status == "ok", "no cut-off: the document in force"


def test_the_citation_names_the_document_its_calculation_and_its_date() -> None:
    doc = rd.document_of(row_of(a_team_doc()))
    key = doc.readings[0].key
    cite = doc.citation(key)
    assert cite is not None
    assert cite["source"] == "C-13" and cite["document_id"] == "stat:team:100:1:u10:all:stats-docs-v1"
    assert cite["calc_version"] == "stats-docs-v1" and cite["known_at"] == T.isoformat() and cite["matches_with_data"] >= 0


def test_only_the_asked_keys_are_read_and_a_body_without_figures_reads_nothing() -> None:
    body = a_team_doc()
    first = body["figures"][0]["key"]
    assert [r.key for r in rd.document_of(row_of(body), keys=[first]).readings] == [first]
    assert rd.document_of(row_of({})).readings == () and rd.document_of(row_of({"figures": "no"})).readings == ()


def test_a_player_document_reads_the_same_way() -> None:
    body = {"figures": [{"key": "shots_per90", "unit": "por_90", "better": "more", "value": 2.5, "matches_with_data": 12,
                         "percentile": 80, "league_value": 1.7}]}
    doc = rd.document_of(row_of(body, kind="player", scope="season"))
    assert doc.kind == "player" and doc.value("shots_per90") == 2.5 and doc.document_id == "stat:player:100:1:season:all:stats-docs-v1"


def test_the_reader_refuses_a_kind_it_does_not_hold_before_touching_the_database() -> None:
    with pytest.raises(ValueError):
        rd.read(None, kind="league", entity_id=1, competition_season_id=1)  # type: ignore[arg-type]


