"""The provider's extras in the statistics documents (plan PM, PM-05-05; BE-068): off, the documents are byte for byte what they were
(the nightly pass rewrites nothing); on, a player and a team carry ``provider_extras`` with sample, coverage and origin, validated
against C-13 1.1.0; goals prevented only with its own switch."""

from __future__ import annotations

from dataclasses import replace

from fbi.api.contracts.intelligence.base import Missing
from fbi.stats import data as sd
from fbi.stats import extras as px
from fbi.stats import job
from fbi.stats import player as sp
from fbi.stats import team as st
from tests.unit.test_stats_documents import _players, body_of, league, player_of


def _with_extras(data: sd.SeasonData, *, every: int = 1) -> sd.SeasonData:
    """Each player line reports its extras (one in ``every`` lines leaves them out); each team-match its offsides and goals
    prevented."""
    lines = []
    for i, line in enumerate(data.players):
        extra = {} if every > 1 and i % every == 0 else {"offsides": 1.0, "dribbled_past": 2.0, "penalties_won": 0.0,
                                                          "penalties_committed": 0.0, "penalties_saved": None}
        lines.append(replace(line, counts={**line.counts, **extra}))
    for m in data.matches:
        for side, (off, gp) in (("home", (2.0, 0.5)), ("away", (1.0, -0.25))):
            m.team_stats[side] = {**m.team_stats.get(side, {}), "offsides": off, "goals_prevented": gp}
    data.players = lines
    return data


def test_the_switches_are_off_by_default() -> None:
    assert px.extras_on({}) is False and px.goals_prevented_on({}) is False
    assert px.extras_on({px.SWITCH: "1"}) is True
    assert px.goals_prevented_on({px.GOALS_PREVENTED_SWITCH: "1"}) is False, "goals prevented is one of the extras"
    assert px.goals_prevented_on({px.SWITCH: "on", px.GOALS_PREVENTED_SWITCH: "on"}) is True


def test_off_the_documents_do_not_change() -> None:
    data = _with_extras(_players())
    before = [job.dumps(d.body) for d in sp.season_documents(data)]
    assert all("provider_extras" not in b for b in before)
    teams, _, _ = st.season_documents(data)
    assert all("provider_extras" not in d.body for d in teams)
    plain = _players()
    assert [job.dumps(d.body) for d in sp.season_documents(plain)] == before, "the extras read changes nothing while off"


def test_a_player_carries_his_extras() -> None:
    data = _with_extras(_players())
    doc = next(d for d in sp.season_documents(data, extras=True) if d.player_id == 502)
    body = player_of(doc.body)
    got = {f.key: f for f in body.provider_extras}
    assert list(got) == [e.key for e in px.PLAYER_EXTRAS]
    assert got["offsides"].value == 1.0 and got["offsides"].unit == "por_90", "one a match of 90 minutes"
    assert got["dribbled_past"].value == 2.0 and got["penalties_won"].value == 0.0 and got["penalties_won"].unit == "total"
    assert isinstance(got["penalties_saved"].value, Missing) and got["penalties_saved"].value.missing_reason == "sin_datos"
    assert all(f.origin == "api_football" and f.matches_with_data in (0, 6) for f in got.values())
    assert got["offsides"].coverage == 1.0


def test_an_extra_under_the_coverage_is_not_shown() -> None:
    data = _with_extras(_players(), every=4)  # a quarter of the lines without extras: 75 % < 80 %
    body = player_of(sp.season_documents(data, extras=True)[0].body)
    off = next(f for f in body.provider_extras if f.key == "offsides")
    assert isinstance(off.value, Missing) and off.value.missing_reason == "sin_cobertura" and off.coverage == 0.75


def test_a_team_carries_its_offsides_and_goals_prevented_only_with_its_switch() -> None:
    data = _with_extras(league())
    docs, _, _ = st.season_documents(data, extras=True)
    home = body_of(next(d.body for d in docs if d.team_id == 100 and d.scope == "season" and d.context == "home"))
    assert [f.key for f in home.provider_extras] == ["offsides"]
    assert home.provider_extras[0].value == 2.0 and home.provider_extras[0].unit == "por_partido"
    docs, _, _ = st.season_documents(data, extras=True, goals_prevented=True)
    away = body_of(next(d.body for d in docs if d.team_id == 100 and d.scope == "season" and d.context == "away"))
    got = {f.key: f.value for f in away.provider_extras}
    assert got == {"offsides": 1.0, "goals_prevented": -0.25}


def test_every_document_with_extras_validates_against_c13() -> None:
    data = _with_extras(_players())
    for d in sp.season_documents(data, extras=True):
        player_of(d.body)
    docs, _, _ = st.season_documents(_with_extras(league()), extras=True, goals_prevented=True)
    for t in docs:
        body_of(t.body)


def test_the_data_layer_reads_the_same_extras_as_the_documents() -> None:
    assert sd.EXTRA_COUNTS == px.PLAYER_COLUMNS
