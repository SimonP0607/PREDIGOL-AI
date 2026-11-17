"""The scenarios engine (IA-082) on real seasons, frozen from production (``tests/fixtures/scenarios``, read-only exports of
16-nov-2026): closed seasons replayed match day by match day with zero false claims, and the cases of Doc 1 where stakes-v5 wrote
"nothing at stake" answered right - Millonarios and Once Caldas (Colombia, Clausura 2026, round 19) still had the play-off to play
for, and the four competitions without coded rules assert nothing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from fbi.competitions import rules as rl
from fbi.competitions import scenario_compare as cmp
from fbi.competitions import scenario_replay as rp
from fbi.competitions import scenarios as sc

DATA = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((DATA / name).read_text(encoding="utf-8"))
    return doc


def matches_of(doc: Mapping[str, Any]) -> list[rp.Match]:
    return [rp.Match(sc.Fixture(int(i), rd, int(h), int(a), gh, ga), datetime.fromisoformat(ko))
            for i, rd, h, a, ko, gh, ga in doc["matches"]]


@pytest.mark.parametrize(("name", "step"), [("premier_league_2025.json", 2), ("argentina_2026_apertura.json", 6),
                                            ("mls_2026_regular.json", 3)])
def test_a_closed_season_replayed_day_by_day_has_no_false_claim(name: str, step: int) -> None:
    doc = load(name)
    final = {k: [(int(r), int(t)) for r, t in v] for k, v in doc["final"].items()}
    report = rp.replay(rl.rules_for(doc["league_id"], doc["season"]), matches_of(doc), final=final, step=step)
    assert report["status"] == "ok" and report["tables"], report
    assert report["claims_checked"] >= 20
    assert report["false_claims"] == 0, report["examples"]
    assert report["flips"] == 0
    assert report["open_after_last_match"] == 0


def test_the_premier_league_table_is_held_to_the_providers_final_table() -> None:
    doc = load("premier_league_2025.json")
    final = {k: [(int(r), int(t)) for r, t in v] for k, v in doc["final"].items()}
    report = rp.replay(rl.rules_for(39, 2025), matches_of(doc), final=final, step=6)
    assert report["sources"] == ["proveedor:Premier League"]


def colombia() -> tuple[dict[str, Any], dict[str, Any]]:
    doc = load("colombia_2026_clausura_20261114.json")
    at = datetime.fromisoformat(doc["at"])
    provider = {k: [sc.ProviderRow(int(t), int(p), int(n)) for t, p, n in v] for k, v in doc["provider"].items()}
    fixtures = [m.fixture for m in matches_of(doc)]
    reading = sc.evaluate(rl.rules_for(239, 2026, on=at.date()), fixtures, at=at, provider=provider, focus=doc["fixtures_of_doc1"])
    return doc, reading


MILLONARIOS, ONCE_CALDAS = 3901, 3910


def test_doc1_millonarios_and_once_caldas_still_had_the_play_off_to_play_for() -> None:
    doc, reading = colombia()
    table = next(t for t in reading["tables"] if t["key"] == "liga_ii.fase_1")
    rows = {r["team"]: r for r in table["teams"]}
    for team in (MILLONARIOS, ONCE_CALDAS):
        o = rows[team]["objetivos"][0]
        assert (rows[team]["puntos"], rows[team]["partidos_restantes"]) == (27, 1)
        assert o["objetivo"] == "clasificacion" and o["terminar_entre_los"] == 8
        assert o["estado"] == "abierto" and o["decidido"]["demostrado"] is False
        assert reading["teams"][str(team)]["hecho"] is None
    # with a win Millonarios is through whatever the others do
    win = table["matches"]["31702"]["home"]["objetivos"][0]["victoria"]
    assert win["estado"] == "conseguido"
    # stakes-v5 said both had nothing at stake: the engine contradicts it, provably
    result = cmp.compare_side(doc["stakes"]["home"], reading, MILLONARIOS)
    assert result["contradice"] and result["contradicciones"][0]["tipo"] == "cerrado_pero_abierto"


def test_the_provider_table_compared_is_the_one_of_the_same_tournament() -> None:
    _, reading = colombia()
    assert [t["key"] for t in reading["tables"]] == ["liga_ii.fase_1"]
    table = reading["tables"][0]
    # the Apertura and the Clausura tables have the same 20 clubs: the Clausura one is compared. It disagrees with the results on
    # two clubs (one is the Internacional de Bogota row AD-B01 found); both versions are certified and only what both prove is said
    assert "datos_discrepantes" in table["flags"]
    assert len(table["provider_differences"]) == 2, table["provider_differences"]


def test_colombia_never_proves_no_objective_while_its_relegation_average_is_not_computed() -> None:
    _, reading = colombia()
    assert not any(v["demostrado"] for v in reading["teams"].values())
    assert any("tabla_promedio_no_calculada" in m for m in reading["teams"][str(MILLONARIOS)]["motivos"])


@pytest.mark.parametrize(("league", "season", "fixture"), [(82, 2026, 170768), (281, 2026, 32914), (5, 2026, 134466),
                                                           (549, 2026, 174774), (72, 2026, 25780)])
def test_doc1_competitions_without_coded_rules_assert_nothing(league: int, season: int, fixture: int) -> None:
    answer = rl.rules_for(league, season)
    assert isinstance(answer, rl.NotCoded), fixture
    reading = sc.evaluate(answer, [sc.Fixture(fixture, "Regular Season - 1", 1, 2)], at=datetime.fromisoformat("2026-11-15T12:00:00+00:00"))
    assert reading["status"] == "reglamento_no_codificado" and reading["tables"] == [] and reading["teams"] == {}
    assert cmp.compare_side({"pressure": "settled", "settled": True}, reading, 1)["contradicciones"] == []
