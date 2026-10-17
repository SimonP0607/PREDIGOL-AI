"""The API-Football v3 contract as documented, and the integration map that says what PrediGol does with it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.audit_api_contract import leaf_paths

from fbi.providers.api_football.contract import CONTRACT, by_path, endpoints, field_paths, parse
from fbi.providers.api_football.integration import USES


def test_the_contract_text_is_the_one_checked_against_the_documentation() -> None:
    meta = json.loads((CONTRACT.parent / "v3_contract.meta.json").read_text())
    assert hashlib.sha256(CONTRACT.read_bytes()).hexdigest() == meta["sha256"]
    assert len(endpoints()) == meta["operations"] == 38
    assert "XxXx" not in CONTRACT.read_text(encoding="utf-8"), "never a key, not even the placeholder"


def test_endpoint_facts() -> None:
    e = by_path()
    assert e["/fixtures"].batch_limits == {"ids": 20}
    assert e["/injuries"].batch_limits == {"ids": 20}
    assert e["/trophies"].batch_limits == {"players": 20, "coachs": 20}
    assert e["/players/profiles"].page_size == 250 and e["/players"].page_size == 20 and e["/odds"].page_size == 10
    assert e["/odds/mapping"].page_size == 100
    assert e["/standings"].update_frequency == "This endpoint is updated every hour."
    assert e["/standings"].recommended_calls.startswith("1 call per hour for the leagues or teams")  # type: ignore[union-attr]
    assert e["/teams"].requires_a_param and e["/timezone"].needs_no_param
    assert [p.name for p in e["/standings"].query_params] == ["league", "season", "team"]
    assert [p.name for p in e["/standings"].query_params if p.required] == ["season"]
    season = next(p for p in e["/players"].params if p.name == "season")
    assert season.pattern == "YYYY | Requires the fields Id, League or Team" and season.max_length == "4"
    assert sum(len(x.query_params) for x in endpoints()) == 140


def test_documented_standings_fields_keep_each_table() -> None:
    fields = dict(by_path()["/standings"].fields())
    assert fields["response[].league.standings[][].group"] == "string"
    assert fields["response[].league.standings[][].home.goals.for"] == "number"
    assert fields["response[].league.standings[][].update"] == "string"
    assert sum(len(x.fields()) for x in endpoints()) == 993


def test_skeleton_and_payload_paths_share_one_notation() -> None:
    assert list(field_paths("{R[]:{a:s,b:{c:n,d[]:{e:b}},f:z}}")) == [
        ("response[].a", "string"), ("response[].b.c", "number"), ("response[].b.d[].e", "boolean"),
        ("response[].f", "null")]
    body: list[dict[str, object]] = [{"a": "x", "b": {"c": 1, "d": [{"e": True}]}, "f": None, "g": []}]
    assert sorted(leaf_paths(body, "response")) == [
        ("response[].a", "string"), ("response[].b.c", "number"), ("response[].b.d[].e", "boolean"),
        ("response[].f", "null"), ("response[].g[]", "array")]


def test_parse_rejects_unknown_lines() -> None:
    try:
        parse("## GET /x [T] op :: S\nQ what\n")
    except ValueError as exc:
        assert "unknown line kind" in str(exc)
    else:
        raise AssertionError("an unknown line kind must not be skipped silently")


def test_every_documented_endpoint_has_an_integration_entry() -> None:
    assert set(USES) == {e.path for e in endpoints()}
    assert all(u.status in ("FULL", "PARTIAL", "COVERED", "MISSING", "WRONG") for u in USES.values())
    assert all(u.covered_by for u in USES.values() if u.status == "COVERED")
    assert USES["/standings"].fixed, "the standings read bug stays on record"
    assert Path(CONTRACT).name == "v3_contract.txt"
