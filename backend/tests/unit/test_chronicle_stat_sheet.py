"""PM-11-07 (IA-158, ``chronicle-stat-sheet-v1``): with ``FBI_CHRONICLE_STAT_SHEET`` on the chronicle's sheet tells each side's expected
goals from its C-13 document - the very value the profile serves - and nothing else does: the packet's ``xg`` is left out, the form keeps no
per-match average, the fact cites the metric keys and the document's date, a document computed after the plan never enters. Off, the plan
is the one of before. The watch (``stat_sheet.differences``) finds zero differences on every match of a real C-13 season, and the verifier
lets the C-13 figure stand and drops the packet's."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.api.contracts.intelligence.base import Missing
from fbi.api.contracts.intelligence.stats_profile import TeamBody
from fbi.chronicle import plan as cp
from fbi.chronicle import stat_sheet as ss
from fbi.chronicle import verify
from fbi.stats import job
from fbi.stats import team as st
from fbi.stats.data import Event, Match, Season, SeasonData
from tests.unit.test_chronicle_plan import AT, AWAY, HOME, inp

T0 = datetime(2034, 2, 1, 18, tzinfo=UTC)
COMPUTED = AT - timedelta(hours=5)


def test_the_switch_is_off_unless_said() -> None:
    assert ss.mode({}) == "off" and ss.mode({ss.SWITCH: "shadow"}) == "off" and ss.mode({ss.SWITCH: "0"}) == "off"
    assert ss.mode({ss.SWITCH: "on"}) == "on" and ss.mode({ss.SWITCH: " 1 "}) == "on"


def row(team: int, *, scope: str = "u10", xg_for: Any = 1.437, xg_against: Any = 0.912, n: int = 10,
        computed_at: datetime = COMPUTED) -> dict[str, Any]:
    return {"entity_id": team, "competition_season_id": 55, "scope": scope, "context": "all", "calc_version": "team-agg-v1",
            "computed_at": computed_at,
            "doc": {"record": {"matches": n}, "figures": [
                {"key": "xg_for", "value": xg_for, "matches_with_data": n},
                {"key": "xg_against", "value": xg_against, "matches_with_data": n - 1},
                {"key": "goals_for", "value": 1.8, "matches_with_data": n}]}}


def sheet(**kw: Any) -> dict[str, ss.SideSheet]:
    home = ss.side_sheet(row(11, **kw))
    assert home is not None
    return {"home": home}


def test_a_document_is_read_as_its_published_figures_only() -> None:
    s = ss.side_sheet(row(11, xg_against={"missing_reason": "sin_cobertura"}))
    assert s is not None and set(s.figures) == {"xg_for", "goals_for"}
    assert s.xg() is None, "C-13 does not publish xg_against: the chronicle does not tell xG"
    assert ss.side_sheet({**row(11), "doc": {"player": {}}}) is None
    assert ss.choose([row(11, scope="season"), row(11, scope="u10")])["scope"] == "u10"  # type: ignore[index]
    assert ss.choose([row(11, scope="season")])["scope"] == "season"  # type: ignore[index]
    assert ss.choose([]) is None


def test_off_the_plan_is_the_one_of_before() -> None:
    before = cp.build(inp())
    assert cp.build(inp(sheet=None)).hash == before.hash
    xg = [f for f in before.facts if f.kind == "xg"]
    assert [f.id for f in xg] == ["P:xg.home"] and xg[0].params["xg_for"] == 0.9
    assert cp.build(inp()).by_id()["P:form.home"].params["goals_for"] == 0.6


def test_on_the_xg_comes_from_c13_only_and_cites_its_metric_keys() -> None:
    plan = cp.build(inp(sheet=sheet()))
    facts = plan.by_id()
    assert "P:xg.home" not in facts and ("P:xg.home", "xg", "fuente_c13") in [(e.ref, e.kind, e.reason) for e in plan.excluded]
    fact = facts["C13:xg.home"]
    assert fact.kind == "xg" and fact.section == "estadisticas" and fact.side == "home"
    assert dict(fact.params) == {"side": "home", "team": HOME, "xg_for": 1.437, "xg_against": 0.912, "n": 9}
    assert fact.source == f"C-13:team/55/u10/all/xg_for,xg_against@team-agg-v1@{COMPUTED.isoformat()}"
    assert fact.known_at == COMPUTED
    assert not any(f.side == "away" and f.kind == "xg" for f in plan.facts), "a side without a document tells no xG"
    form = facts["P:form.home"].params
    assert not ss.FORM_AVERAGES & set(form) and form["sequence"] == "LLDLL" and form["wins"] == 0
    assert plan.hash != cp.build(inp()).hash


def test_on_with_an_empty_sheet_no_average_is_told() -> None:
    plan = cp.build(inp(sheet={}))
    assert not [f for f in plan.facts if f.kind == "xg"]
    assert not ss.FORM_AVERAGES & set(plan.by_id()["P:form.away"].params)


def test_a_document_computed_after_the_plan_or_without_both_figures_is_not_told() -> None:
    late = cp.build(inp(sheet=sheet(computed_at=AT + timedelta(minutes=1))))
    assert ("C13:xg.home", "posterior_al_plan") in [(e.ref, e.reason) for e in late.excluded]
    assert not [f for f in late.facts if f.kind == "xg"]
    empty = cp.build(inp(sheet=sheet(xg_for={"missing_reason": "sin_datos"})))
    assert ("C13:xg.home", "sin_cifra_c13") in [(e.ref, e.reason) for e in empty.excluded]


def test_the_plan_is_still_deterministic_and_reads_back() -> None:
    a, b = cp.build(inp(sheet=sheet())), cp.build(inp(sheet=sheet()))
    assert a.hash == b.hash
    back = cp.from_json(a.as_json())
    assert back.by_id()["C13:xg.home"].source == a.by_id()["C13:xg.home"].source


def _sentence(plan: cp.ContentPlan, text: str, fid: str) -> str | None:
    return verify.check_sentence(text, [fid], lang="es", section="estadisticas", plan=plan, texts={})


def test_the_verifier_lets_the_c13_figure_stand_and_drops_the_packets() -> None:
    plan = cp.build(inp(sheet=sheet()))
    assert _sentence(plan, f"El {HOME} genera 1,4 goles esperados por partido y concede 0,9 en sus últimos 9 partidos.",
                     "C13:xg.home") is None
    dropped = _sentence(plan, f"El {HOME} genera 0,9 goles esperados por partido y concede 1,7.", "C13:xg.home")
    assert dropped is not None and "numbers" in dropped, "the packet's 0,9 / 1,7 are no longer the sheet's figures"


# ── the watch on a real C-13 season ──────────────────────────────────────────────────────────────────────────────────────────

def season(teams: int = 10) -> SeasonData:
    """A double round robin whose expected goals change from match to match (three decimals), with a cup-like gap in coverage."""
    matches = []
    k = 0
    for h in range(teams):
        for a in range(teams):
            if h == a:
                continue
            k += 1
            numbers: dict[str, int | None] = {"goals_ft_home": k % 3, "goals_ft_away": (k * 7) % 4}
            stats = {"home": {"xg": round(0.4 + (k * 37 % 23) / 10, 2)}, "away": {"xg": round(0.3 + (k * 11 % 17) / 10, 2)}}
            matches.append(Match(k, T0 + timedelta(days=k), 100 + h, 100 + a, f"Equipo {h}", f"Equipo {a}", False, numbers, stats,
                                 [Event(10, None, "home", "Goal", "Normal Goal", "")]))
    return SeasonData(Season(55, 2034, 1, "Liga", "Colombia", len(matches)), matches, [])


def test_zero_differences_between_the_sheet_and_the_profile_on_every_match() -> None:
    data = season()
    docs, _, _ = st.season_documents(data)
    rows = {(d.team_id, d.scope, d.context): {"entity_id": d.team_id, "competition_season_id": 55, "scope": d.scope, "context": d.context,
                                              "calc_version": st.CALC_VERSION, "computed_at": COMPUTED,
                                              "doc": job.json.loads(job.dumps(d.body))}
            for d in docs}
    told = 0
    for m in data.matches:
        sides = {}
        profile: dict[str, dict[str, float]] = {}
        for side, team in (("home", m.home_id), ("away", m.away_id)):
            chosen = ss.choose([r for (t, _, c), r in rows.items() if t == team and c == "all"])
            assert chosen is not None
            got = ss.side_sheet(chosen)
            assert got is not None
            sides[side] = got
            body = TeamBody.model_validate(chosen["doc"])  # what the API validates and serves
            profile[side] = {f.key: float(f.value) for f in body.figures if not isinstance(f.value, Missing)}
        plan = cp.build(dataclasses.replace(inp(), fixture_id=m.fixture_id, sheet=sides))
        xg = [f for f in plan.facts if f.kind == "xg"]
        told += len(xg)
        assert ss.differences(m.fixture_id, plan.facts, profile) == []
    assert told == 2 * len(data.matches), "every side of every match told its C-13 xG"


def test_the_watch_reports_a_figure_the_profile_does_not_show() -> None:
    plan = cp.build(inp())  # the packet's 0.9 / 1.7, as today
    found = ss.differences(7001, plan.facts, {"home": {"xg_for": 1.437, "xg_against": 1.7}})
    assert [(d.key, d.chronicle, d.profile, d.note) for d in found] == [("xg_for", 0.9, 1.437, "cifra_distinta")]
    assert [d.note for d in ss.differences(7001, plan.facts, {})] == ["el_perfil_no_la_publica"] * 2
    assert found[0].as_json()["fixture_id"] == 7001


@pytest.mark.parametrize("name", [HOME, AWAY])
def test_the_team_named_is_the_plans(name: str) -> None:
    side = "home" if name == HOME else "away"
    s = ss.side_sheet(row(11 if side == "home" else 22))
    assert s is not None
    plan = cp.build(inp(sheet={side: s}))
    assert plan.by_id()[f"C13:xg.{side}"].params["team"] == name
