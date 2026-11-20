"""BE-075 (plan PM, PM-09-01): the Colombian tables computed from the rules file, checked against real tables.

The fixture ``tests/fixtures/competitions/239_primera_a_2024_2026.json`` is every match of Primera A 2024-2026 as production
stores it and the provider's newest tables, read on 20-nov-2026 14:22 UTC, after the last round of the Fase I of the Liga II
2026 (14-nov). The relegation table is therefore final and is compared with the one published that day by Win Sports, the
league's own channel (https://www.winsports.co/futbol-colombiano/liga-dimayor/descenso, read 20-nov-2026); the owner's cotejo
(DOC-008) compares it with DIMAYOR's before anything is shown.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
import yaml

from fbi.competitions import ranking as rk
from fbi.competitions import rules as rl
from fbi.competitions import season_tables as st

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "competitions" / "239_primera_a_2024_2026.json"
DATA: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))

NACIONAL, TOLIMA, AMERICA, SANTA_FE, BUCARAMANGA, JUNIOR, MEDELLIN, MILLONARIOS = 1137, 1142, 1138, 1139, 1131, 1135, 1128, 1125
ONCE_CALDAS, PASTO, CALI, AGUILAS, FORTALEZA, LLANEROS, PEREIRA, CUCUTA = 1136, 1126, 1127, 1144, 1147, 1464, 1462, 1470
INTER, ALIANZA, CHICO, JAGUARES = 1134, 1141, 1132, 1133

WINSPORTS_20NOV2026 = {  # team: (points, played), as published; position 20 = last
    JAGUARES: (31, 38), CHICO: (106, 116), ALIANZA: (126, 116), INTER: (130, 116), CUCUTA: (43, 38), PEREIRA: (134, 116),
    LLANEROS: (91, 78), FORTALEZA: (140, 116), CALI: (145, 116), AGUILAS: (145, 116), PASTO: (146, 116),
    ONCE_CALDAS: (181, 116), MILLONARIOS: (186, 116), MEDELLIN: (188, 116), JUNIOR: (189, 116), BUCARAMANGA: (190, 116),
    SANTA_FE: (198, 116), AMERICA: (199, 116), TOLIMA: (204, 116), NACIONAL: (208, 116),
}


def matches() -> list[st.Match]:
    return [st.Match(s, f, r, status, h, a, gh, ga, ph, pa) for s, f, r, status, _ko, h, a, gh, ga, ph, pa in DATA["matches"]]


def provider(season: int, table: str) -> list[dict[str, Any]]:
    rows = [r for r in DATA["provider_tables"] if r["season"] == season and r["table"] == table]
    assert rows, (season, table)
    return sorted(rows, key=lambda r: r["rank"])


def colombia() -> rl.CompetitionRules:
    answer = rl.rules_for(239, 2026)
    assert isinstance(answer, rl.Coded)
    return answer.rules


def reading(**kw: Any) -> st.Reading:
    return st.compute(colombia(), 2026, matches(), decisions=st.load_decisions(239), **kw)


def figures(rows: Iterable[dict[str, Any]]) -> dict[int, tuple[int, int, int, int]]:
    return {int(r["team"]): (r["played"], r["points"], r["goals_for"], r["goals_against"]) for r in rows}


# ── the rules file ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_v2_is_in_force_and_cites_art_34_for_the_relegation_v1_is_retired() -> None:
    lib = rl.Library.read()
    v1, v2 = lib.versions(239)
    assert (v1.rules.version, v1.rules.state, v2.rules.version, v2.rules.state) == (1, "retired", 2, "coded")
    assert "art. 34" in (v1.rules.retired_reason or "")
    r = colombia()
    assert r.version == 2
    descenso = r.table("descenso")
    assert [(z.kind, z.last, z.note) for z in descenso.zones] == [("relegation", 2, "art. 34")]
    assert r.sources[0].articles == "arts. 4-34" and r.sources[0].url.endswith("REGLAMENTO-LIGA-2026-V0.pdf")
    assert [p.season for p in descenso.past] == [2024, 2025]
    assert {w.team: w.seasons for w in descenso.windows} == {JAGUARES: (2026,), CUCUTA: (2026,), LLANEROS: (2025, 2026)}
    assert descenso.ties_on == ("liga_i.fase_1", "liga_ii.fase_1")
    assert [p.competition for p in r.table("reclasificacion").places] == ["CONMEBOL Libertadores 2027",
                                                                          "CONMEBOL Sudamericana 2027"]
    assert {g.topic for g in r.gaps} == {"continental", "table"}


@pytest.mark.parametrize(("change", "fragment"), [
    ({"tables": [{"key": "tt", "name": "Table", "kind": "aggregate", "counts": ["season.league"],
                  "ranking": {"tiebreakers": ["goal_difference"]},
                  "past": [{"season": 2025, "rounds": ["R*"]}]}]}, "earlier seasons of an average"),
    ({"tables": [{"key": "tt", "name": "Table", "kind": "aggregate", "counts": ["season.league"],
                  "ranking": {"tiebreakers": ["goal_difference"]}, "ties_on": ["season.nope"]}]}, "breaks ties on"),
    ({"tables": [{"key": "tt", "name": "Table", "kind": "aggregate", "counts": ["season.league"],
                  "ranking": {"tiebreakers": ["goal_difference"]},
                  "places": [{"competition": "Cup", "article": "art. 1",
                              "slots": [{"slot": "X 1", "source": "champion", "of": "nope"}]}]}]}, "not a tournament here"),
    ({"tables": [{"key": "tt", "name": "Table", "kind": "aggregate", "counts": ["season.league"],
                  "ranking": {"tiebreakers": ["goal_difference"]},
                  "places": [{"competition": "Cup", "article": "art. 1",
                              "slots": [{"slot": "X 1", "source": "table_rank", "of": "season"}]}]}]}, "'of' names"),
])
def test_the_schema_refuses_table_data_that_does_not_hold(change: dict[str, Any], fragment: str, tmp_path: Path) -> None:
    base: dict[str, Any] = {
        "schema": "competition-rules/1", "league_id": 999, "competition": "Test", "country": "Nowhere", "version": 1,
        "seasons": [2026], "sources": [{"publisher": "Test FA", "title": "Rules", "url": "https://example.org/r.pdf",
                                        "checked_at": "2026-11-20", "applies_to": "2026"}],
        "tournaments": [{"key": "season", "name": "Season", "phases": [
            {"key": "league", "name": "League", "format": "league", "rounds": ["R*"], "teams": 4,
             "schedule": "double_round_robin", "ranking": {"tiebreakers": ["goal_difference"]}}]}],
    }
    folder = tmp_path / "999_test"
    folder.mkdir()
    (folder / "v1.yaml").write_text(yaml.safe_dump({**base, **change}), encoding="utf-8")
    with pytest.raises(rl.RulesError, match=fragment):
        rl.load_files(tmp_path)


# ── the Fase I tables and the reclasificación reproduce the provider's ─────────────────────────────────────────────────────────


def test_both_fase_i_tables_of_2026_are_the_providers_in_figures_and_order() -> None:
    r = reading()
    for key, label in (("liga_i.fase_1", "Primera Division: Apertura"), ("liga_ii.fase_1", "Primera Division: Clausura")):
        table = r.table(key)
        rows = provider(2026, label)
        assert table.complete and table.pending == 0, key
        assert figures(table.rows) == figures(rows), key
        assert table.order() == [x["team"] for x in rows], key


def test_without_the_decision_of_clausura_1_the_liga_ii_table_differs_in_exactly_two_clubs() -> None:
    plain = st.compute(colombia(), 2026, matches())
    computed = figures(plain.table("liga_ii.fase_1").rows)
    published = figures(provider(2026, "Primera Division: Clausura"))
    assert {t for t in computed if computed[t] != published[t]} == {INTER, AMERICA}
    assert computed[AMERICA][1] - published[AMERICA][1] == 3 and published[INTER][1] - computed[INTER][1] == 3


def test_the_reclasificacion_is_the_providers_tabla_anual() -> None:
    table = reading().table("reclasificacion")
    rows = provider(2026, "Primera Division: Tabla Anual")
    assert figures(table.rows) == figures(rows)
    assert table.order() == [x["team"] for x in rows]
    assert table.rows[0]["played"] == 44 and table.rows[0]["points"] == 95  # Nacional: 19 + 19 + 6 knock-out matches
    assert not table.complete and table.pending == 8  # the cuadrangulares are being played; the final is not on the calendar


def test_the_earlier_seasons_with_their_decisions_are_the_providers_tables() -> None:
    applied = st.apply_decisions(matches(), st.load_decisions(239))
    assert not applied.problems and len(applied.applied) == 4 and applied.unverified == 4
    for season, prefix, label in ((2024, "Apertura", "Primera A: Apertura"), (2024, "Clausura", "Primera A: Clausura"),
                                  (2025, "Clausura", "Primera A, Clausura 2025")):
        pattern = re.compile(rf"^{prefix} - [0-9]+$")
        own = [m.result() for m in applied.matches if m.season == season and m.round and pattern.match(m.round) and m.counts]
        rows = rk.rows_of(own, rk.THREE_ONE_ZERO)
        for p in provider(season, label):
            row = rows[p["team"]]
            assert (row.played, row.points) == (p["played"], p["points"]), (season, label, p["team"])
    # what still differs is one goal in four rows (no point): the provider's table and its own match scores disagree
    pattern = re.compile(r"^Clausura - [0-9]+$")
    own = [m.result() for m in applied.matches if m.season == 2024 and m.round and pattern.match(m.round) and m.counts]
    rows = rk.rows_of(own, rk.THREE_ONE_ZERO)
    off = {p["team"] for p in provider(2024, "Primera A: Clausura")
           if (rows[p["team"]].goals_for, rows[p["team"]].goals_against) != (p["goals_for"], p["goals_against"])}
    assert off == {PASTO, CALI}


# ── the relegation table (arts. 32-34) ──────────────────────────────────────────────────────────────────────────────────────────


def test_the_relegation_table_is_the_published_one_and_chico_and_jaguares_go_down() -> None:
    table = reading().table("descenso")
    assert {r["team"]: (r["points"], r["played"]) for r in table.rows} == WINSPORTS_20NOV2026
    assert table.complete and table.pending == 0
    zone = table.zones[0]
    assert (zone["kind"], zone["state"], zone["positions"], set(zone["teams"])) == ("relegation", "definitivo", [19, 20],
                                                                                   {CHICO, JAGUARES})
    assert table.rows[-1]["team"] == JAGUARES and table.rows[-1]["average"] == "31/38"
    assert table.rounding == {"2_half_up": "igual", "3_half_up": "igual", "2_down": "igual", "3_down": "igual"}
    assert table.unverified_decisions == 4  # Nacional-Junior 2024, the two awarded matches of 2025, Inter-América 2026


def test_a_tie_in_the_average_is_broken_on_the_points_of_2026_only() -> None:
    rows = {r["team"]: r for r in reading().table("descenso").rows}
    cali, aguilas = rows[CALI], rows[AGUILAS]
    assert cali["average"] == aguilas["average"] == "5/4"  # 145 / 116
    assert (cali["tie_scope"]["points"], aguilas["tie_scope"]["points"]) == (62, 51)
    assert cali["position"] + 1 == aguilas["position"] and cali["decided_by"] == "points"
    # the published table of 20-nov-2026 lists Águilas above Cali: a finding for the cotejo (art. 33), not a rule


def test_the_club_windows_of_art_32_are_applied_even_where_the_data_has_more_seasons() -> None:
    rows = {r["team"]: r for r in reading().table("descenso").rows}
    assert any(m.season == 2024 and JAGUARES in (m.home, m.away) for m in matches())  # Jaguares played Primera A 2024
    assert rows[JAGUARES]["window"] == [2026] and set(rows[JAGUARES]["seasons"]) == {"2026"}
    assert rows[LLANEROS]["window"] == [2025, 2026] and rows[LLANEROS]["played"] == 78
    assert rows[CUCUTA]["played"] == 38 and rows[NACIONAL]["window"] == [2024, 2025, 2026]


def test_the_cut_figure_with_three_decimals_is_the_published_one() -> None:
    rows = {r["team"]: r for r in reading().table("descenso").rows}
    assert (rows[TOLIMA]["average_3_cut"], rows[TOLIMA]["average_3"]) == ("1.758", "1.759")
    assert rows[BUCARAMANGA]["average_3_cut"] == "1.637"


# ── champions and places (arts. 30-31) ──────────────────────────────────────────────────────────────────────────────────────────


def test_the_liga_i_champion_is_junior_and_the_liga_ii_champion_is_not_known_yet() -> None:
    champs = reading().champions
    assert champs["liga_i"]["team"] == JUNIOR  # 3-0 and 0-1: three points each, 3-1 on aggregate
    assert champs["liga_i"]["decided_by"] == "aggregate"
    assert champs["liga_ii"]["team"] is None and "no match" in champs["liga_ii"]["reason"]


def test_places_wait_for_what_is_not_known_and_never_say_definitive_before_it() -> None:
    places = reading().table("reclasificacion").places
    states = [(p["competition"][9:20], p["slot"], p["team"], p["state"]) for p in places]
    assert states[0] == ("Libertadore", "Colombia 1", JUNIOR, "calculado")
    assert states[1][3] == "pendiente" and states[4][3] == "pendiente"
    assert all(p["state"] == "provisional" for p in places if p["source"] == "table_rank")
    assert [p["team"] for p in places if p["source"] == "table_rank"][:2] == [NACIONAL, AMERICA]


def test_a_club_that_would_take_two_places_stops_the_allocation_paragraph_not_coded() -> None:
    places = reading(cup_winners={"Copa BetPlay DIMAYOR 2026": JUNIOR}).table("reclasificacion").places
    sud = [p for p in places if "Sudamericana" in p["competition"]]
    assert sud[0]["state"] == "no_calculado" and "parrafo_sin_codificar" in sud[0]["reason"]
    assert all(p["state"] == "no_calculado" and p["team"] is None for p in sud[1:])


def test_zones_of_the_reclasificacion_are_conditional_never_definitive() -> None:
    assert {z["state"] for z in reading().table("reclasificacion").zones} == {"condicional"}


# ── decisions ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_an_awarded_match_without_score_or_decision_is_left_out_and_said() -> None:
    applied = st.apply_decisions(matches(), {})
    assert sum("no score and no decision" in p for p in applied.problems) == 2


def test_a_decision_over_a_score_that_changed_is_not_applied(tmp_path: Path) -> None:
    folder = tmp_path / "239_test" / "decisions"
    folder.mkdir(parents=True)
    (folder / "2026.yaml").write_text(yaml.safe_dump({
        "schema": "competition-decisions/1", "league_id": 239, "season": 2026, "decisions": [
            {"fixture": 1549689, "round": "Clausura - 1", "home": INTER, "away": AMERICA, "kind": "awarded",
             "result": {"home": 3, "away": 0}, "stored": {"home": 1, "away": 1}, "evidence": "a test of a stale decision file"}]}),
        encoding="utf-8")
    applied = st.apply_decisions(matches(), st.load_decisions(239, tmp_path))
    assert not applied.applied and any("not applied" in p for p in applied.problems)
    (folder / "2025.yaml").write_text((folder / "2026.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(rl.RulesError, match=r"decisions/2026.yaml"):
        st.load_decisions(239, tmp_path)


def test_the_repository_decision_files_validate_and_none_is_verified_yet() -> None:
    files = st.load_decisions(239)
    assert sorted(files) == [2024, 2025, 2026]
    assert [x.verified for d in files.values() for x in d.decisions] == [False] * 4


# ── nothing is shown ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_switch_is_off_unless_the_line_says_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(st.SWITCH, raising=False)
    monkeypatch.setattr(st, "environment", lambda: {})
    assert st.switch_on() is False
    monkeypatch.setattr(st, "environment", lambda: {st.SWITCH: "on"})
    assert st.switch_on() is True
    monkeypatch.setattr(st, "environment", lambda: {st.SWITCH: "maybe"})
    assert st.switch_on() is False


def test_the_reading_is_json_and_reproducible() -> None:
    a, b = reading().as_json(), reading().as_json()
    assert a == b and json.loads(json.dumps(a)) == a
    assert a["version"] == st.VERSION and a["rules_version"] == 2


def test_the_shadow_command_compares_with_every_provider_table_of_the_same_clubs() -> None:
    from scripts import competition_tables as ct

    assert ct.seasons_needed(colombia(), 2026) == [2024, 2025, 2026]
    tables: dict[str, list[dict[str, Any]]] = {}
    for r in DATA["provider_tables"]:
        if r["season"] == 2026:
            tables.setdefault(r["table"], []).append({**r, "snapshot_at": "2026-11-20T13:27:52+00:00"})
    found = ct.compare(reading(), tables)
    pairs = {(c["table"], c["provider_table"]) for c in found}
    assert ("reclasificacion", "Primera Division: Tabla Anual") in pairs
    assert ("liga_i.fase_1", "Primera Division: Apertura") in pairs and ("liga_ii.fase_1", "Primera Division: Clausura") in pairs
    assert all(not c["differences"] and c["same_order"] for c in found
               if c["provider_table"].startswith("Primera Division") and (c["table"], c["provider_table"]) in {
                   ("reclasificacion", "Primera Division: Tabla Anual"), ("liga_i.fase_1", "Primera Division: Apertura"),
                   ("liga_ii.fase_1", "Primera Division: Clausura")})
    assert ("tabla_liga_i", "Primera Division: Apertura") not in pairs  # 25 matches against 19: another scope, not compared
    assert all(not c["differences"] and c["same_order"] for c in found)
