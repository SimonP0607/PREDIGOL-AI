"""PM-08-05: the difficulty of the coming matches (``fbi.competitions.schedule_difficulty``) - the formula recomputed independently for ten
teams, the home advantage, the uncertainty, the flags, and the switch born off (in shadow: DM-14)."""

from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime, timedelta

import pytest

from fbi.competitions import schedule_difficulty as sd

T0 = datetime(2026, 11, 22, 20, tzinfo=UTC)
# ten teams' next five rivals: (elo, venue of the team, rated matches, last ratings of the rival)
TEAMS = {
    team: [(1500 + 37 * ((team * 7 + k * 3) % 11) - 120, ("home", "away")[(team + k) % 2], 30 + team + k,
            [1500 + 37 * ((team * 7 + k * 3) % 11) - 120 + d * ((team + k) % 4 - 1.5) for d in range(10)]) for k in range(5)]
    for team in range(1, 11)
}


def rivals_of(team: int) -> list[sd.Rival]:
    return [sd.Rival(fixture_id=team * 10 + k, kickoff=T0 + timedelta(days=7 * k), opponent_id=100 + k, venue=venue,  # type: ignore[arg-type]
                     rating=elo, rated=rated, sigma=sd.sigma_of(last))
            for k, (elo, venue, rated, last) in enumerate(TEAMS[team])]


@pytest.mark.parametrize("team", sorted(TEAMS))
def test_the_index_of_ten_teams_recomputed_independently(team: int) -> None:
    got = sd.difficulty(rivals_of(team))
    rows = TEAMS[team]
    faced = [elo - 65 if venue == "home" else elo + 65 for elo, venue, _r, _l in rows]
    assert got.n == 5 and got.index == pytest.approx(sum(faced) / 5)
    home = [f for f, (_e, v, _r, _l) in zip(faced, rows, strict=True) if v == "home"]
    away = [f for f, (_e, v, _r, _l) in zip(faced, rows, strict=True) if v == "away"]
    assert got.home_index == pytest.approx(sum(home) / len(home)) and got.away_index == pytest.approx(sum(away) / len(away))
    sigmas = [statistics.pstdev(last) for _e, _v, _r, last in rows]
    assert got.margin95 == pytest.approx(1.96 * math.sqrt(sum(s * s for s in sigmas)) / 5)
    assert got.state == "medido"
    j = got.as_json()
    assert got.index is not None and got.margin95 is not None
    assert j["interval95"] == [round(got.index - got.margin95, 1), round(got.index + got.margin95, 1)]


def test_a_neutral_venue_takes_no_advantage() -> None:
    assert sd.faced(1600, "neutral") == 1600 and sd.faced(1600, "home") == 1535 and sd.faced(1600, "away") == 1665


def test_a_rival_rated_on_few_matches_or_without_a_rating_makes_the_index_uncertain() -> None:
    base = rivals_of(1)
    few = [*base[:4], sd.Rival(99, T0, 200, "away", 1500.0, 3, 1.0)]
    got = sd.difficulty(few)
    assert got.state == "incierto" and few[-1].as_json()["flag"] == "pocas_partidas"
    none = [*base[:4], sd.Rival(99, T0, 200, "away", None, 0, None)]
    got = sd.difficulty(none)
    assert got.n == 4 and got.unrated == 1 and got.state == "incierto"
    unknown_sigma = [*base[:4], sd.Rival(99, T0, 200, "away", 1500.0, 40, None)]
    assert sd.difficulty(unknown_sigma).margin95 is None


def test_no_coming_match_says_so() -> None:
    got = sd.difficulty([])
    assert (got.n, got.index, got.state) == (0, None, "sin_partidos")


def test_the_constants_are_the_elo_and_the_walk_forward_ones() -> None:
    from fbi.backtesting.walkforward import MIN_ELO_HISTORY
    from fbi.features.elo import EloParams

    assert EloParams().home_advantage == sd.HOME_ADVANTAGE
    assert sd.MIN_RATED == MIN_ELO_HISTORY


def test_the_switch_is_born_off_and_the_formula_says_it_is_not_a_forecast() -> None:
    assert sd.mode({}) == "off" and sd.mode({sd.SWITCH: "1"}) == "on"
    assert "no un pronóstico" in sd.FORMULA


def test_no_route_page_or_packet_reads_it() -> None:
    from pathlib import Path

    src = Path(sd.__file__).resolve().parents[1]
    readers = [p for p in src.rglob("*.py") if "schedule_difficulty" in p.read_text(encoding="utf-8") and p.name != "schedule_difficulty.py"]
    assert readers == [], readers


# ── RP-6.4: the note of an uneven recent calendar ─────────────────────────────────────────────────────

def _measured(index: float, margin: float) -> sd.Difficulty:
    return sd.Difficulty(n=5, index=index, margin95=margin, home_index=None, away_index=None, n_home=2, n_away=3, unrated=0, state="medido")


def test_a_recent_calendar_is_uneven_only_when_the_interval_leaves_the_league_mean_out() -> None:
    assert sd.calendar_note(_measured(1560.0, 20.0), 1500.0).state == "desigual_dificil"
    assert sd.calendar_note(_measured(1440.0, 20.0), 1500.0).state == "desigual_facil"
    for index in (1520.0, 1500.0, 1480.0):  # the edge of the interval (20) and inside it
        assert sd.calendar_note(_measured(index, 20.0), 1500.0).state == "equilibrado", index
    assert sd.calendar_note(_measured(1520.5, 20.0), 1500.0).state == "desigual_dificil", "just past the edge"
    note = sd.calendar_note(_measured(1560.0, 20.0), 1500.0)
    assert note.gap == pytest.approx(60.0) and note.text_es and "más duro" in note.text_es
    assert sd.calendar_note(_measured(1440.0, 20.0), 1500.0).text_es and "más fácil" in str(sd.calendar_note(_measured(1440.0, 20.0), 1500.0).text_es)
    assert sd.calendar_note(_measured(1500.0, 20.0), 1500.0).text_es is None


def test_an_uncertain_or_missing_index_never_gives_a_verdict() -> None:
    uncertain = sd.Difficulty(n=5, index=1600.0, margin95=None, home_index=None, away_index=None, n_home=2, n_away=3, unrated=1, state="incierto")
    note = sd.calendar_note(uncertain, 1500.0)
    assert note.state == "incierto" and note.text_es is None and note.gap == pytest.approx(100.0)
    empty = sd.Difficulty(0, None, None, None, None, 0, 0, 0, "sin_partidos")
    assert sd.calendar_note(empty, 1500.0).state == "sin_datos"
    assert sd.calendar_note(_measured(1600.0, 10.0), None).state == "sin_datos"
