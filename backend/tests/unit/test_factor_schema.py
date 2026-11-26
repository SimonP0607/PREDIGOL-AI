"""The one schema of a context fact (RP-4.1, ``fbi.ai.factor_schema``): seven attributes, five categories, and the category by code."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import factor_counts
from fbi.ai import factor_schema as fs

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def fact(**over: Any) -> fs.FactView:
    base: dict[str, Any] = {"origin": "web", "kind": "stakes", "status": "PROBABLE", "source_name": "Marca", "source_url": "https://www.marca.com/x",
                               "published_at": NOW - timedelta(hours=3), "subject_type": "TEAM", "subject_id": 7,
                               "fresh_until": NOW + timedelta(days=2), "claim": "El equipo se juega el ascenso", "payload_hash": None,
                               "attributes": {}, "side": "home", "fact_schema": fs.VERSION}
    base.update(over)
    return fs.FactView(**base)


def test_a_complete_fact_misses_nothing_and_each_attribute_can_be_the_missing_one() -> None:
    assert fs.missing(fact()) == []
    cases: dict[str, dict[str, Any]] = {"source": {"source_name": "  "}, "source_date": {"published_at": None}, "entity": {"subject_id": None},
             "validity": {"fresh_until": None}, "evidence": {"claim": ""}, "relation": {"side": None}}
    for attribute, change in cases.items():
        assert fs.missing(fact(**change)) == [attribute], attribute
    assert set(cases) <= set(fs.ATTRIBUTES) and len(fs.ATTRIBUTES) == 7 and "state" not in cases, "the state is the server's and always exists"


def test_a_web_fact_without_its_address_and_a_calculation_without_its_calculation_are_refused() -> None:
    assert fs.missing(fact(source_url=None)) == ["source", "evidence"]
    assert fs.missing(fact(origin="own_calc", source_url=None)) == ["evidence"], "a calculated fact says how it was calculated"
    assert fs.missing(fact(origin="own_calc", source_url=None, attributes={"calculation": "scenarios-v1"})) == []
    with pytest.raises(fs.IncompleteFactError) as err:
        fs.require(fact(side="elsewhere", fresh_until=None))
    assert err.value.absent == ["validity", "relation"]


def test_the_category_is_given_by_code_from_the_state_and_never_to_what_cannot_be_argued() -> None:
    assert fs.category_of("CONFIRMED", "web", "media") == "hecho_confirmado"
    assert fs.category_of("PROBABLE", "web", "media") == "informacion_probable"
    assert fs.category_of("PROBABLE", "web", "aggregator") == "rumor", "an aggregator never rises above a rumour"
    assert fs.category_of("RUMOR", "web", "social") == "rumor"
    assert fs.category_of("PROBABLE", "own_calc") == fs.category_of("RUMOR", "owner") == "hecho_confirmado"
    assert fs.category_of("CONTRADICTORY", "web", "media") is None and fs.category_of("OUTDATED", "provider", "provider") is None
    assert {fs.category_of(s, "web", "media") for s in ("CONFIRMED", "PROBABLE", "RUMOR", "OUTDATED")} - {None} <= set(fs.EVIDENCE_CATEGORIES)
    assert fs.CATEGORIES[3:] == ("interpretacion_tactica", "hipotesis"), "the last two are written by the text and by the registry, not given to evidence"


def test_the_table_of_levels_gives_the_same_categories() -> None:
    assert [fs.category_of_level(x) for x in ("oficial", "dos_origenes", "declaracion", "un_medio", "rumor", None, "otro")] == [
        "hecho_confirmado", "hecho_confirmado", "informacion_probable", "informacion_probable", "rumor", None, None]


def test_the_words_of_the_schema_are_the_words_of_the_migration() -> None:
    path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0180_context_fact_schema.py"
    spec = importlib.util.spec_from_file_location("m0180", path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert (m.OLD_KINDS, m.NEW_KINDS, m.SIDES) == (fs.OLD_KINDS, fs.NEW_KINDS, fs.SIDES)
    assert (*m.OLD_ORIGINS, "own_calc") == fs.ORIGINS and (*fs.OLD_KINDS, *fs.NEW_KINDS) == fs.KINDS


def test_the_counts_keep_the_new_facts_apart_from_the_old_and_say_which_new_kinds_have_none() -> None:
    def row(**c: object) -> dict[str, object]:
        base: dict[str, object] = {"kind": "injury", "origin": "web", "status": "PROBABLE", "source_tier": "media", "fact_schema": None, "side": None,
                                   "has_validity": False, "has_date": True, "has_entity": False, "has_source": True, "n": 1}
        base.update(c)
        return base

    doc = factor_counts.report([
        row(n=80), row(kind="stakes", fact_schema=fs.VERSION, side="home", has_validity=True, has_entity=True, n=3, status="CONFIRMED"),
        row(kind="referee", fact_schema=fs.VERSION, side="match", has_validity=True, has_entity=True, n=1, status="RUMOR", origin="provider"),
    ])
    assert doc["new"] == {"facts": 4, "complete": 4, "complete_share": 1.0, "by_kind": {"referee": 1, "stakes": 3},
                          "by_category": {"hecho_confirmado": 3, "rumor": 1}}
    assert doc["before"]["facts"] == 80 and doc["before"]["with_all_attributes"] == 0
    assert doc["new_kinds_seen"] == ["referee", "stakes"] and doc["new_kinds_missing"] == ["format", "formation", "rotation", "statement"]
    assert "100% completos" in "\n".join(factor_counts.lines(doc))
