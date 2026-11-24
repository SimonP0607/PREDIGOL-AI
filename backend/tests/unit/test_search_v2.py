"""IA-078 / IA-081: the pure parts of the search v2 (C-10) and of ``scripts.search_index`` - no database.

The contract itself (examples, projection, no leak, versions) is covered by the generic tests of IA-057
(``test_intelligence_contract_*.py``) since C-10 is registered; the queries by ``tests/integration/test_search_index.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest
from scripts.search_index import build_parser, in_quiet_window, refusal

from fbi.api.contracts.intelligence.registry import CATALOGUE, by_id
from fbi.api.contracts.intelligence.search import (
    GROUPS,
    KIND_GROUP,
    SearchGroups,
    SearchV2,
    SearchV2Private,
)
from fbi.api.repositories import search_v2 as repo
from fbi.api.services import search_v2 as service

AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)


def test_c10_is_registered_with_its_two_routes() -> None:
    spec = by_id()["C-10"]
    assert (spec.public, spec.private) == (SearchV2, SearchV2Private)
    assert spec.version == "1.1.0"  # C-10 1.1: localized names and the senior team first, no field changed
    assert spec.public_routes == CATALOGUE["C-10"].public == ("/api/v1/search/v2",)
    assert spec.private_routes == CATALOGUE["C-10"].private == ("/api/v1/admin/search/v2",)


def test_the_groups_are_the_ux_contracts_in_its_order() -> None:
    # Equipos, Selecciones, Jugadores, Competiciones, Entrenadores, Árbitros, Estadios, Partidos, Noticias.
    assert tuple(SearchGroups.model_fields) == GROUPS
    assert set(KIND_GROUP.values()) == set(GROUPS) - {"fixtures", "news"}


def test_the_old_search_contract_is_untouched() -> None:
    hit = import_module("fbi.api.contracts.search").SearchHit
    assert set(hit.model_fields) == {"type", "id", "label", "sublabel"}
    assert hit.model_fields["type"].annotation.__args__ == ("fixture", "team", "competition")


@pytest.mark.parametrize(("raw", "clean"), [("  Real   Madrid ", "Real Madrid"), ("a\tb\nc", "a b c"),
                                            ("x" * 80, "x" * 60)])
def test_the_query_is_cleaned(raw: str, clean: str) -> None:
    assert service.clean_query(raw) == clean


@pytest.mark.parametrize(("key", "words", "trigrams"), [
    ("ac", False, False), ("mes", True, False), ("mesi", True, True), ("j r", True, False), ("jam rod", True, True),
])
def test_which_passes_run(key: str, words: bool, trigrams: bool) -> None:
    assert repo.passes_for(key) == (words, trigrams)


def test_the_prefix_is_a_bound_like_pattern_with_its_wildcards_escaped() -> None:
    assert repo.like_prefix("atletico") == "atletico%"
    assert repo.like_prefix("a%b_c\\") == "a\\%b\\_c\\\\%"


def test_the_thresholds_are_the_plans() -> None:
    assert repo.TRIGRAM_THRESHOLD == 0.6  # AD-I02: initial 0.6; the lab of 17-nov-2026 kept it (0.5 / 0.45 found no more)
    assert 0 < repo.SUGGEST_THRESHOLD < repo.TRIGRAM_THRESHOLD


def test_freshness_says_when_the_index_is_missing_or_old() -> None:
    assert service._freshness(AT, False, None).stale_reason == "indice_sin_construir"
    assert service._freshness(AT, True, AT - timedelta(days=8)).stale_reason == "indice_antiguo"
    fresh = service._freshness(AT, True, AT - timedelta(hours=3))
    assert not fresh.stale and fresh.stale_reason is None


def test_the_sql_is_static_and_parametrised() -> None:
    for sql in (repo.ENTITIES_SQL, repo.FIXTURES_SQL, repo.SUGGEST_SQL, repo.STATE_SQL):
        assert "{" not in sql, "no formatting into the SQL text"
    assert "%(key)s" in repo.ENTITIES_SQL and "%(prefix)s" in repo.ENTITIES_SQL


# ── scripts.search_index ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("argv", [["status"], ["refresh"], ["refresh", "--apply"], ["refresh", "--apply", "--force"]])
def test_every_command_parses(argv: list[str]) -> None:
    assert build_parser().parse_args(argv).command == argv[0]


def test_refresh_is_a_dry_run_unless_asked() -> None:
    args = build_parser().parse_args(["refresh"])
    assert args.apply is False and args.force is False


@pytest.mark.parametrize(("hour", "minute", "quiet"), [(3, 49, False), (3, 50, True), (4, 59, True), (5, 0, False),
                                                       (16, 0, False)])
def test_the_night_window_is_kept(hour: int, minute: int, quiet: bool) -> None:
    assert in_quiet_window(datetime(2026, 11, 21, hour, minute, tzinfo=UTC)) is quiet


def test_the_refresh_refuses_the_window_and_an_open_fixtures_sync() -> None:
    assert refusal(datetime(2026, 11, 21, 4, 0, tzinfo=UTC), 0) is not None
    assert refusal(datetime(2026, 11, 21, 12, 0, tzinfo=UTC), 1) == "1 fixtures_sync run(s) open"
    assert refusal(datetime(2026, 11, 21, 12, 0, tzinfo=UTC), 0) is None


# ── C-10 1.1: the senior national team first ─────────────────────────────────────────────────────────────────────────

def test_the_senior_national_team_comes_first_unless_the_query_asks_for_a_junior_one() -> None:
    sql = repo.ENTITIES_SQL
    assert "ORDER BY junior, rank DESC, length(label), label, entity_id" in sql
    assert "b.kind = 'national_team' AND NOT q.asks_junior AND b.label ~ ' (W|U[0-9][0-9])( |$)'" in sql
    assert "sub ?[0-9][0-9]" in sql and "femenina" in sql and "women" in sql
    assert sql.rstrip().endswith("ORDER BY kind, rn")  # the junior flag orders, it is never selected
    assert "junior" not in sql.split("SELECT kind, entity_id, label")[1].split("FROM ranked")[0]
