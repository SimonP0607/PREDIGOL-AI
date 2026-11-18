"""The statistics documents of plan EA (EA-003 to EA-006): formulas, honesty rules and the contract they are written in."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fbi.api.contracts.intelligence.base import Missing
from fbi.api.contracts.intelligence.stats_profile import PlayerBody, TeamBody
from fbi.statmath import formulas as fx
from fbi.stats import job
from fbi.stats import player as sp
from fbi.stats import team as st
from fbi.stats.data import Event, Match, PlayerLine, Season, SeasonData

T0 = datetime(2034, 1, 1, 18, tzinfo=UTC)


# ── formulas ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_wilson_of_seven_in_ten() -> None:
    assert fx.wilson_pct(7, 10) == (70, 40, 89)
    assert fx.wilson_pct(0, 5)[0] == 0 and fx.wilson_pct(5, 5)[2] == 100


def test_wilson_refuses_impossible_counts() -> None:
    with pytest.raises(ValueError):
        fx.wilson(3, 2)


def test_percentile_is_mid_rank() -> None:
    assert fx.percentile(3, [1, 2, 3, 4]) == 63
    assert fx.percentile(1, [1, 1, 1, 1]) == 50
    assert fx.percentile(10, [1, 2, 3]) == 100


@pytest.mark.parametrize(("minute", "extra", "pulse", "interval"), [
    (1, None, 0, 0), (5, None, 0, 0), (6, None, 1, 0), (45, None, 8, 2), (45, 2, 9, 3), (46, None, 10, 4), (90, None, 18, 6),
    (90, 3, 19, 7), (105, None, None, None),
])
def test_bins_of_a_minute(minute: int, extra: int | None, pulse: int | None, interval: int | None) -> None:
    assert fx.pulse_bin(minute, extra) == pulse
    assert fx.interval_bin(minute, extra) == interval


def test_the_smoothing_keeps_the_mass_of_each_half_and_the_added_minutes() -> None:
    s = fx.smoothing_matrix()
    assert np.allclose(s.sum(axis=1), 1.0)
    assert s[9, 9] == 1.0 and s[19, 19] == 1.0
    assert s[0, 10] == 0.0, "a first-half goal never leaks into the second half"


def test_the_pulse_band_is_reproducible_and_contains_the_index() -> None:
    counts = np.zeros((12, 20))
    for i in range(12):
        counts[i, (i * 3) % 20] = 1
    league = np.full(20, 0.05)
    a = fx.pulse(counts, league, seed=7)
    b = fx.pulse(counts, league, seed=7)
    assert a[1] == b[1] and a[2] == b[2] and a[3] == b[3]
    inside = sum(1 for i, lo, hi in zip(a[1], a[2], a[3], strict=True)
                 if i is not None and lo is not None and hi is not None and lo <= i <= hi)
    assert inside >= 16


def test_survival_is_the_share_of_matches_still_level() -> None:
    pts = fx.survival([None, 10.0, 10.0, 50.0])
    by = {label: s for label, _, s in pts}
    assert by["5"] == 1.0 and by["10"] == 0.5 and by["90+"] == 0.25
    assert fx.median_label(pts) == "10"


# ── a small league ───────────────────────────────────────────────────────────────────────────────────────────────────

def _numbers(gh: int, ga: int, *, corners: tuple[int, int] | None = (5, 4), ht: tuple[int, int] | None = (0, 0)) -> dict[str, int | None]:
    n: dict[str, int | None] = dict.fromkeys(("corners_ft_home", "corners_ft_away", "shots_ft_home", "shots_ft_away", "shots_on_target_ft_home", "shots_on_target_ft_away", "fouls_ft_home", "fouls_ft_away", "saves_ft_home", "saves_ft_away", "yellow_ft_home", "yellow_ft_away", "red_ft_home", "red_ft_away", "cards_lines_ft_home", "cards_lines_ft_away"))
    n.update(goals_ft_home=gh, goals_ft_away=ga, goals_1h_home=ht[0] if ht else None, goals_1h_away=ht[1] if ht else None,
             goals_2h_home=gh - ht[0] if ht else None, goals_2h_away=ga - ht[1] if ht else None,
             shots_ft_home=10, shots_ft_away=8, cards_lines_ft_home=2, cards_lines_ft_away=3)
    if corners:
        n.update(corners_ft_home=corners[0], corners_ft_away=corners[1])
    return n


def league(teams: int = 10, *, broken_events: bool = False) -> SeasonData:
    """A double round robin of ``teams`` sides: the home side wins 2-1 (goals at 10' home, 50' away, 90+2 home), corners 5-4."""
    matches = []
    k = 0
    for h in range(teams):
        for a in range(teams):
            if h == a:
                continue
            k += 1
            events = [Event(10, None, "home", "Goal", "Normal Goal", ""), Event(50, None, "away", "Goal", "Normal Goal", ""),
                      Event(90, 2, "home", "Goal", "Penalty", ""), Event(30, None, "away", "Card", "Yellow Card", "")]
            if broken_events and h == 0:
                events = events[:1]
            matches.append(Match(k, T0 + timedelta(days=k), 100 + h, 100 + a, f"Equipo {h}", f"Equipo {a}", False,
                                 _numbers(2, 1, ht=(1, 0)),
                                 {"home": {"xg": 1.5, "possession": 55.0, "passes": 400.0, "passes_accurate": 320.0},
                                  "away": {"xg": 0.9, "possession": 45.0, "passes": 300.0, "passes_accurate": 210.0}},
                                 events))
    return SeasonData(Season(1, 2034, 1, "Liga", "Colombia", len(matches)), matches, [])


def body_of(doc: dict[str, object]) -> TeamBody:
    """Every document the tests build is validated against C-13 through its JSON, as the API reads it."""
    return TeamBody.model_validate_json(job.dumps(doc))


def player_of(doc: dict[str, object]) -> PlayerBody:
    return PlayerBody.model_validate_json(job.dumps(doc))


def _doc(docs: list[st.TeamDoc], team: int, scope: str, context: str) -> TeamBody:
    return body_of(next(d.body for d in docs if d.team_id == team and d.scope == scope and d.context == context))


def test_every_team_gets_every_available_scope_and_context() -> None:
    docs, _, _ = st.season_documents(league())
    keys = {(d.team_id, d.scope, d.context) for d in docs}
    assert (100, "season", "all") in keys and (100, "u10", "all") in keys and (100, "u5", "home") in keys
    assert (100, "u20", "home") not in keys, "nine home matches cannot make a scope of twenty"


def test_figures_records_and_percentiles() -> None:
    docs, _, _ = st.season_documents(league())
    body = _doc(docs, 100, "season", "home")
    assert body.record.wins == 9 and body.record.points == 27
    fig = {f.key: f for f in body.figures}
    assert fig["goals_for"].value == 2.0 and fig["xg_for"].value == 1.5
    assert fig["finishing"].value == 0.5
    assert isinstance(fig["goals_for"].percentile, int)
    assert fig["fouls"].value == Missing(missing_reason="sin_datos")


def test_a_figure_under_the_coverage_is_not_shown() -> None:
    data = league()
    for m in data.matches[: len(data.matches) // 2]:
        m.numbers["corners_ft_home"] = m.numbers["corners_ft_away"] = None
    docs, _, _ = st.season_documents(data)
    fig = {f.key: f for f in _doc(docs, 100, "season", "all").figures}
    assert isinstance(fig["corners_for"].value, Missing) and fig["corners_for"].value.missing_reason == "sin_cobertura"


def test_a_percentile_needs_enough_teams() -> None:
    docs, _, _ = st.season_documents(league(teams=4))
    fig = {f.key: f for f in _doc(docs, 100, "season", "all").figures}
    assert isinstance(fig["goals_for"].percentile, Missing)
    assert fig["goals_for"].percentile.missing_reason == "muestra_insuficiente"


def test_the_curves_read_only_matches_whose_goals_add_up() -> None:
    docs, _, _ = st.season_documents(league(broken_events=True))
    body = _doc(docs, 100, "season", "home")
    assert isinstance(body.pulse_for, Missing), "every home match of team 0 has a goal missing from its list"
    away = _doc(docs, 100, "season", "away")
    assert not isinstance(away.pulse_for, Missing)


def test_goal_intervals_and_game_states() -> None:
    docs, _, _ = st.season_documents(league())
    body = _doc(docs, 100, "season", "home")
    assert not isinstance(body.intervals, Missing)
    bins = {b.label: b for b in body.intervals.bins}
    assert bins["1-15"].goals_for == 9 and bins["46-60"].goals_against == 9 and bins["90+"].goals_for == 9
    assert bins["90+"].goals_for_list[0].extra_minute == 2
    assert not isinstance(body.states, Missing)
    assert body.states.minutes_leading == 40.0 and body.states.minutes_level == 50.0, "1-0 at 10', 1-1 at 50', 2-1 at 90+2"
    assert body.states.points_ceded == 0 and body.states.matches_led == 9


def test_survival_of_level_and_its_median() -> None:
    docs, _, _ = st.season_documents(league())
    body = _doc(docs, 100, "season", "all")
    assert not isinstance(body.survival, Missing)
    by = {p.label: p.survival for p in body.survival.points}
    assert by["5"] == 1.0 and by["10"] == 0.0
    assert body.survival.median_first_goal == "10"
    assert body.survival.level_at_half == 0.0


def test_trends_count_with_the_settlement_rules() -> None:
    docs, _, _ = st.season_documents(league())
    assert not isinstance(_doc(docs, 100, "season", "home").trends, Missing)
    rows = {t.key: t for t in _doc(docs, 100, "season", "home").trends.items}
    assert rows["win"].hits == 9 and rows["win"].n == 9 and rows["win"].pct == 100
    assert rows["over_2_5"].pct == 100 and rows["btts"].pct == 100
    assert rows["corners_over_8_5"].pct == 100 and rows["corners_over_9_5"].pct == 0
    assert rows["corners_over_9_5"].rule_key == "corners_ft@v1"
    assert rows["win"].league_pct == 100 and rows["win"].deviation_pts == 0
    away = {t.key: t for t in _doc(docs, 100, "season", "away").trends.items}
    assert away["loss"].pct == 100 and away["clean_sheet"].pct == 0


def test_the_radar_is_oriented_so_that_more_is_better() -> None:
    docs, _, _ = st.season_documents(league())
    axes = {a.key: a for a in _doc(docs, 100, "season", "all").radar}
    assert set(axes) == {"ataque", "pegada", "volumen", "presencia", "defensa", "disciplina"}
    assert axes["defensa"].percentile == 50, "every team is alike: the inverted axis sits at the middle too"


def test_every_team_document_validates_against_c13() -> None:
    docs, _, _ = st.season_documents(league())
    for d in docs:
        body = body_of(d.body)
        assert TeamBody.model_validate(json.loads(body.model_dump_json())) == body


# ── players ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _players(n: int = 12, *, minutes: int = 90, matches: int = 6) -> SeasonData:
    data = league(teams=4)
    lines = []
    for p in range(n):
        for k in range(matches):
            m = data.matches[k]
            lines.append(PlayerLine(m.fixture_id, m.kickoff_at, 500 + p, f"Jugador {p}", "home", minutes, True, "F", None,
                                    {"goals": float(p % 3), "assists": 0.0, "shots_total": 2.0, "shots_on": 1.0, "passes_total": 20.0,
                                     "passes_key": 1.0, "passes_accuracy_pct": 15.0, "tackles": None, "blocks": None,
                                     "interceptions": None, "duels_total": 10.0, "duels_won": 5.0, "dribbles_attempts": 2.0,
                                     "dribbles_success": 1.0, "fouls_drawn": 1.0, "fouls_committed": 1.0, "yellow_cards": 0.0,
                                     "red_cards": 0.0, "saves": None, "goals_conceded": None}))
    data.players = lines
    return data


def test_a_forward_gets_his_template_with_percentiles_and_distribution() -> None:
    docs = sp.season_documents(_players())
    body = player_of(next(d.body for d in docs if d.player_id == 502))
    assert body.position == "delantero"
    keys = [f.key for f in body.figures]
    assert keys == list(sp.TEMPLATES["F"])
    goals = next(f for f in body.figures if f.key == "goals")
    assert goals.value == 2.0 and isinstance(goals.percentile, int) and not isinstance(goals.distribution, Missing)
    acc = sp.value_of(sp.METRICS["pass_accuracy"], _players().players[:6])
    assert acc.value == pytest.approx(75.0)
    assert len(body.last5) == 5 and body.last5[-1].values[0].key == "goals"


def test_a_player_under_five_nineties_has_no_percentile() -> None:
    docs = sp.season_documents(_players(minutes=30, matches=6))
    goals = next(f for f in player_of(docs[0].body).figures if f.key == "goals")
    assert isinstance(goals.percentile, Missing) and goals.percentile.missing_reason == "muestra_insuficiente"


def test_every_player_document_validates_against_c13() -> None:
    for d in sp.season_documents(_players()):
        player_of(d.body)


def test_scored_first_is_read_from_the_goal_events() -> None:
    docs, _, _ = st.season_documents(league())
    home = {t.key: t for t in _doc(docs, 100, "season", "home").trends.items}
    away = {t.key: t for t in _doc(docs, 100, "season", "away").trends.items}
    assert home["scores_first"].pct == 100 and away["scores_first"].pct == 0
    assert isinstance(home["scores_first"].rule_key, Missing)


def test_the_matrix_has_a_column_per_context_and_only_in_the_all_document() -> None:
    data = league()
    for m in data.matches:
        m.closing = {"Home": 0.5, "Draw": 0.25, "Away": 0.25}
    docs, _, _ = st.season_documents(data)
    body = _doc(docs, 100, "season", "all")
    assert not isinstance(body.matrix, Missing)
    cols = {c.context: c for c in body.matrix}
    assert cols["all"].matches == 18 and cols["home"].matches == 9 and cols["favorite"].matches == 9
    assert isinstance(_doc(docs, 100, "season", "home").matrix, Missing)


def test_the_pass_commits_each_season_on_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """BE-048: the reads open the connection's transaction, so each season is committed by the pass itself; a failing season is
    rolled back alone and never takes the ones already written with it."""
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from typing import Any

    from fbi.stats import data as sd
    from fbi.stats import job

    log: list[str] = []

    class Conn:
        def execute(self, sql: str, params: object = None) -> Any:
            return SimpleNamespace(fetchone=lambda: (True,) if "lock" in sql else (7,))

        def commit(self) -> None:
            log.append("commit")

        def rollback(self) -> None:
            log.append("rollback")

    seasons = [SimpleNamespace(id=i) for i in (1, 2, 3)]
    monkeypatch.setattr(sd, "seasons", lambda conn, min_matches: seasons)
    monkeypatch.setattr(sd, "load_season", lambda conn, s: s)

    def write(conn: Any, data: Any, run_id: Any, at: Any) -> int:
        if data.id == 2:
            raise RuntimeError("boom")
        log.append(f"write {data.id}")
        return 10

    monkeypatch.setattr(job, "write_season", write)
    r = job.run_pass(Conn(), now=datetime(2034, 1, 1, tzinfo=UTC))  # type: ignore[arg-type]
    assert r.seasons == 2 and r.documents == 20 and len(r.errors) == 1
    assert log[:6] == ["commit", "write 1", "commit", "rollback", "write 3", "commit"]
