"""BE-082 (plan PM, PM-09-04 and PM-09-03): the season tables of a competition as a reader's page reads them, the switches of the
readers' pages of wave 4, and the shared cases of the calculator «¿Qué pasa si…?».

The database is replaced by the fixture of BE-075 (every match of Primera A 2024-2026 as production stored it on 20-nov-2026): the
service must answer what ``fbi.competitions.season_tables`` computes, with PrediGol's team ids, and list the matches still to be
decided with the tables they count in. The cases of ``what_if_cases.json`` are checked here with the server's ranking; the web
reproduces them (``web/src/product/competitions/whatIf.test.ts``).
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from fbi.api import switches
from fbi.api.contracts.auth import Me
from fbi.api.envelope import DataStatus
from fbi.api.problem import ApiError
from fbi.api.services import season_tables as svc
from fbi.competitions import ranking as rk
from fbi.competitions.rules import Points

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "competitions"
DATA: dict[str, Any] = json.loads((FIXTURES / "239_primera_a_2024_2026.json").read_text(encoding="utf-8"))
CASES: dict[str, Any] = json.loads((FIXTURES / "what_if_cases.json").read_text(encoding="utf-8"))
CHICO, JAGUARES = 1132, 1133


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_API_CACHE", "0")


def fake_db(monkeypatch: pytest.MonkeyPatch, league: int = 239, newest: int | None = 2026) -> None:
    rows = [{"season": s, "fixture_id": 900_000 + i, "provider_fixture_id": f, "round": r, "status_short": status,
             "kickoff_at": ko, "home": h, "away": a, "goals_home": gh, "goals_away": ga, "pen_home": ph, "pen_away": pa}
            for i, (s, f, r, status, ko, h, a, gh, ga, ph, pa) in enumerate(DATA["matches"])]

    def fetch_one(_conn: Any, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
        assert sql is svc.COMPETITION_SQL
        return {"id": params["c"], "provider_league_id": league, "newest": newest} if params["c"] == 16 else None

    def fetch_all(_conn: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if sql is svc.MATCHES_SQL:
            return [r for r in rows if r["season"] in params["seasons"]]
        assert sql is svc.TEAMS_SQL
        return [{"id": 10_000 + t, "provider_team_id": t, "name": f"Club {t}", "logo_url": None} for t in params["ids"]]

    monkeypatch.setattr(svc, "fetch_one", fetch_one)
    monkeypatch.setattr(svc, "fetch_all", fetch_all)


def test_the_route_is_closed_while_fbi_competition_tables_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_COMPETITION_TABLES", raising=False)
    fake_db(monkeypatch)
    with pytest.raises(ApiError) as err:
        svc.season_tables(None, 16)  # type: ignore[arg-type]
    assert err.value.status == 404


def test_it_serves_the_tables_of_the_rules_file_with_the_teams_of_predigol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_COMPETITION_TABLES", "1")
    fake_db(monkeypatch)
    env = svc.season_tables(None, 16)  # type: ignore[arg-type]
    assert env.status is DataStatus.OK and env.data is not None
    data = env.data
    assert (data.contract, data.contract_version, data.league_id, data.season, data.rules_version) == (
        "season-tables", "1.0.0", 239, 2026, 2)
    assert data.rules_file.endswith("v2.yaml") and len(data.rules_sha256) == 64
    assert (data.points.win, data.points.draw, data.points.loss) == (3, 1, 0)
    by_key = {t.key: t for t in data.tables}
    assert set(by_key) == {"tabla_liga_i", "tabla_liga_ii", "reclasificacion", "descenso"}
    descenso = by_key["descenso"]
    assert descenso.kind == "average" and descenso.complete
    assert [r.team.provider_team_id for r in descenso.rows[-2:]] == [CHICO, JAGUARES]
    assert all(r.team.team_id == 10_000 + r.team.provider_team_id for r in descenso.rows)
    assert descenso.rows[-1].average is not None and descenso.rows[-1].window == [2026]
    assert [z.kind for z in descenso.zones] == ["relegation"] and descenso.zones[0].state == "definitivo"
    assert descenso.tiebreakers[0] == "points" and descenso.counts == ["liga_i.fase_1", "liga_ii.fase_1"]
    reclas = by_key["reclasificacion"]
    assert reclas.kind == "aggregate" and reclas.rows[0].wins is not None and reclas.rows[0].average is None
    assert [p.competition for p in reclas.places][:1] == ["CONMEBOL Libertadores 2027"]
    assert {p.state for p in reclas.places} <= {"calculado", "provisional", "pendiente", "no_calculado"}
    assert data.unverified_decisions == 4
    # what is left to play counts in the tables of tournament II and the reclasificación, never in the (final) average
    assert data.remaining, "the cuadrangulares and the final of the Liga II were still to be played on 20-nov"
    for m in data.remaining:
        assert "descenso" not in m.tables and "reclasificacion" in m.tables and m.fixture_id is not None
    assert reclas.pending_matches == sum(1 for m in data.remaining if "reclasificacion" in m.tables)


def test_a_competition_without_season_tables_answers_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_COMPETITION_TABLES", "1")
    fake_db(monkeypatch, league=39, newest=2025)
    env = svc.season_tables(None, 16)  # type: ignore[arg-type]
    assert env.status is DataStatus.EMPTY and env.data is None and env.reason


def test_an_unknown_competition_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_COMPETITION_TABLES", "1")
    fake_db(monkeypatch)
    with pytest.raises(ApiError) as err:
        svc.season_tables(None, 17)  # type: ignore[arg-type]
    assert err.value.status == 404


def test_the_readers_pages_of_wave_4_are_born_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FBI_COMPETITION_PAGE", "FBI_COMPETITION_DIRECTORY", "FBI_PLAYER_PROFILE_EXTRAS", "FBI_WHAT_IF"):
        monkeypatch.delenv(name, raising=False)
    assert not any((switches.competition_page_on(), switches.competition_directory_on(),
                    switches.player_profile_extras_on(), switches.what_if_on()))
    for field in ("competition_page", "competition_tables", "competition_directory", "player_profile_extras", "what_if"):
        assert Me.model_fields[field].default is False
    monkeypatch.setenv("FBI_WHAT_IF", "1")
    assert switches.what_if_on() is True


# ── the shared cases of the calculator ─────────────────────────────────────────────────────────────────────────────────────────

SCORE = {"home": (1, 0), "draw": (0, 0), "away": (0, 1)}


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_the_shared_cases_hold_for_the_servers_ranking(case: dict[str, Any]) -> None:
    pts = Points(**case["points"])
    order0 = [r["team"] for r in case["rows"]]
    chosen = [(case["remaining"][int(i)], SCORE[c]) for i, c in case["choices"].items()]
    if case["kind"] == "aggregate":
        played = [rk.Result(*m) for m in case["played"]]
        before = rk.rows_of(played, pts, teams=order0)
        assert {r["team"]: (r["points"], r["played"]) for r in case["rows"]} == {
            t: (before[t].points, before[t].played) for t in order0}, "the rows are what the played matches give"
        after = rk.rows_of(played + [rk.Result(h, a, gh, ga) for (h, a), (gh, ga) in chosen], pts, teams=order0)
        value: dict[int, Fraction] = {t: Fraction(after[t].points) for t in order0}
        figures = {t: (after[t].points, after[t].played) for t in order0}
    else:
        p = {r["team"]: r["points"] for r in case["rows"]}
        n = {r["team"]: r["played"] for r in case["rows"]}
        now = {r["team"]: r["counts_now"] for r in case["rows"]}
        for (h, a), (gh, ga) in chosen:
            one = rk.rows_of([rk.Result(h, a, gh, ga)], pts)
            for t in (h, a):
                if now[t]:
                    p[t] += one[t].points
                    n[t] += 1
        value = {t: Fraction(p[t], n[t]) for t in order0}
        figures = {t: (p[t], n[t]) for t in order0}
    expected = case["expected"]
    assert {e["team"]: (e["points"], e["played"]) for e in expected} == figures
    assert [e["team"] for e in expected] == sorted(order0, key=lambda t: (-value[t], order0.index(t)))
    for e in expected:
        assert e["tied"] == (sum(1 for t in order0 if value[t] == value[e["team"]]) > 1)
        assert e["position"] == expected.index(e) + 1
