"""The forecast of the counts in a real database (plan F10, ``family-v1``): what is written, where, with which version, and what is not.

The pure parts are in tests/unit/test_families_forecast.py. Here: the history is read from the outcomes view of F9, the strengths are fitted on
what was known at ``at``, every market the catalogue has a key for is stored whole under a version of its own, a second run writes nothing, a
new code writes again, the page of the forecast of a match sees none of it, and the gate of the forecast of F5 applies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import psycopg
import pytest

from fbi.api.services import forecast as page
from fbi.families import forecast, versioning
from fbi.families.fit import OUTCOME_KNOWN_AFTER
from tests.integration.conftest import Seed

from .knowledge_world import World

pytestmark = pytest.mark.integration

AT = datetime(2035, 3, 1, 12, tzinfo=UTC)

# the keys of the catalogue these tests make available (a family states nothing else): key, outcomes, has a line
CATALOGUE = (("OU_1H", 2, True), ("1X2_1H", 3, False), ("HTFT", 9, False), ("HSH", 3, False), ("CORNERS_OU", 2, True),
             ("CORNERS_OU_HOME", 2, True), ("CORNERS_1X2", 3, False), ("CARDS_OU", 2, True), ("YELLOW_OU", 2, True))
WRITTEN = {key for key, _, _ in CATALOGUE}
FAMILY_OF = {"OU_1H": "GOALS_HALF", "1X2_1H": "GOALS_HALF", "HTFT": "GOALS_HALF", "HSH": "GOALS_HALF", "CORNERS_OU": "CORNERS",
             "CORNERS_OU_HOME": "CORNERS", "CORNERS_1X2": "CORNERS", "CARDS_OU": "CARDS", "YELLOW_OU": "YELLOW"}


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The world has 120 matches in the window of the dispersion, not 300: the threshold is tested on its own below."""
    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def catalogue(db: psycopg.Connection[Any], keys: tuple[tuple[str, int, bool], ...] = CATALOGUE) -> None:
    for key, n, has_line in keys:
        db.execute("INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive) VALUES (%s, %s, %s, %s, true) "
                   "ON CONFLICT (key) DO NOTHING", (key, key, n, has_line))


def referees(db: psycopg.Connection[Any], *names: str) -> list[int]:
    """The alias (a spelling that F3 settled on) of one new referee for each name: what a match is whistled by."""
    out = []
    for name in names:
        referee_id = db.execute("INSERT INTO core.referees (name, name_key, origin, version) VALUES (%s, %s, 'rules', 'test') RETURNING id",
                                (name, name.lower())).fetchall()[0][0]
        out.append(int(db.execute("INSERT INTO core.referee_aliases (referee_id, name_key, scope, display, basis, placed_by, version) "
                                  "VALUES (%s, %s, 'testland', %s, 'identity', 'rules', 'test') RETURNING id",
                                  (referee_id, name.lower(), name)).fetchall()[0][0]))
    return out


def whistle(db: psycopg.Connection[Any], fixture_id: int, alias_id: int, observed: datetime) -> None:
    db.execute("INSERT INTO core.fixture_officials (fixture_id, role, observed_at, alias_id) VALUES (%s, 'referee', %s, %s)",
               (fixture_id, observed, alias_id))


def played(w: World, n: int = 330, days: int = 330, refs: tuple[tuple[int, float], ...] = ()) -> None:
    """``n`` finished matches of four teams, one every ``days / n`` days up to a day before ``AT``: goals by half, corners and cards.

    With ``refs`` - (alias, how many times the usual yellow cards) - each match is whistled by one of them, picked at random, and has that many
    times the cards."""
    rng = np.random.default_rng(11)
    pick = np.random.default_rng(5)
    attack, defence = np.array([0.25, 0.05, -0.10, -0.20]), np.array([0.15, 0.0, -0.05, -0.10])
    pairs = [(h, a) for h in range(4) for a in range(4) if h != a]
    step = timedelta(days=days) / n
    for i in range(n):
        home, away = pairs[i % len(pairs)]
        kickoff = AT - timedelta(days=days) + step * i
        scale = (float(np.exp(attack[home] - defence[away])), float(np.exp(attack[away] - defence[home])))
        first = [int(rng.poisson(0.65 * s)) for s in scale]
        second = [int(rng.poisson(0.85 * s)) for s in scale]
        fid = w.match(kickoff, home, away, goals=(first[0] + second[0], first[1] + second[1]), ht=(first[0], first[1]), settled=None)
        strict = 1.0
        if refs:
            alias, strict = refs[int(pick.integers(len(refs)))]
            whistle(w.db, fid, alias, kickoff + timedelta(hours=3))
        for side, s in (("home", scale[0]), ("away", scale[1])):
            w.team_stats(fid, side, corners=int(rng.poisson(5.0 * s * rng.gamma(10.0, 0.1))),
                         yellow_cards=int(rng.poisson(2.0 * s * strict * rng.gamma(10.0, 0.1))), red_cards=int(rng.random() < 0.04))


def upcoming(w: World, home: int = 0, away: int = 1, when: timedelta = timedelta(days=1)) -> int:
    return w.match(AT + when, home, away, goals=None, status="NS", group="scheduled")


def stored(db: psycopg.Connection[Any], fixture_id: int, version: str = forecast.VERSION) -> list[tuple[Any, ...]]:
    return db.execute("SELECT market_key, line, selection, p, p_model, family, calibration, basis, model_name, model_version_id, known_at "
                      "FROM models.match_forecasts WHERE fixture_id = %s AND version = %s ORDER BY market_key, line, selection, known_at",
                      (fixture_id, version)).fetchall()


def run(db: psycopg.Connection[Any], ids: list[int] | None, at: datetime = AT) -> forecast.FamilyReport:
    return forecast.write_family_forecasts(db, at=at, code_version="test", fixture_ids=ids)


def test_every_family_states_the_markets_the_catalogue_has_under_a_version_of_its_own(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    report = run(db, [fid])
    assert report.targets == 1 and report.not_fit == 0
    assert all(report.specs[s.key].markets_written > 0 for s in forecast.SPECS), report.summary()

    rows = stored(db, fid)
    assert {r[0] for r in rows} == WRITTEN, "the keys of the catalogue that exist here, and not one more"
    assert {(r[6], r[7]) for r in rows} == {("UNCALIBRATED", "no_champion")} and all(r[3] == r[4] for r in rows)
    assert {r[0]: r[5] for r in rows} == FAMILY_OF
    by_market: dict[tuple[str, Any], float] = {}
    for key, line, _, p, *_ in rows:
        assert 0 < p < 1
        by_market[(key, line)] = by_market.get((key, line), 0.0) + float(p)
    assert all(abs(total - 1.0) < 1e-4 for total in by_market.values()), "each market is stored whole and adds up to one"
    assert {(k, float(ln)) for k, ln in by_market if k == "CORNERS_OU"} == {("CORNERS_OU", x) for x in (8.5, 9.5, 10.5, 11.5, 12.5)}
    assert len({r[2] for r in rows if r[0] == "HTFT"}) == 9 and "Home/Draw" in {r[2] for r in rows if r[0] == "HTFT"}

    assert db.execute("SELECT count(*) FROM models.match_forecasts WHERE version <> %s", (forecast.VERSION,)).fetchone() == (0,)
    registry = db.execute("SELECT r.name, r.family, v.version, v.status FROM models.model_versions v JOIN models.model_registry r ON r.id = v.model_id "
                          "WHERE r.name LIKE 'family-%' ORDER BY r.name").fetchall()
    assert [(n, f, s) for n, f, _, s in registry] == [(s.model, "counts", "experimental") for s in sorted(forecast.SPECS, key=lambda x: x.model)]
    assert all(v.startswith("1.0.0/") and v.endswith(f"@{versioning.code_version()}") for _, _, v, _ in registry)
    assert {r[8] for r in rows} == {s.model for s in forecast.SPECS}


def test_the_page_of_the_forecast_of_a_match_sees_none_of_it(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    assert stored(db, fid)
    body = page.match_forecast(db, fid, preview=True, at=AT + timedelta(hours=1)).data
    assert body is not None and not body.forecast.data, "the page reads forecast-v1 and nothing else"


def test_the_upcoming_matches_are_found_when_none_is_named(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    report = run(db, None)
    assert report.targets >= 1 and stored(db, fid), "the matches of followed competitions inside the horizon"


def test_a_second_run_writes_nothing_and_a_new_code_writes_again(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    first = stored(db, fid)
    again = run(db, [fid])
    assert all(r.rows_written == 0 and r.unchanged > 0 for r in again.specs.values()), again.summary()
    later = run(db, [fid], at=AT + timedelta(hours=1))
    assert all(r.rows_written == 0 for r in later.specs.values()), "an hour later, with nothing new, the numbers have not moved"
    assert stored(db, fid) == first

    monkeypatch.setattr(versioning, "code_version", lambda: "fcOTHERCODE")
    renewed = run(db, [fid], at=AT + timedelta(hours=2))
    assert all(r.rows_written > 0 for r in renewed.specs.values()), "another code is another version of the model: the market is written again"
    ids = {r[9] for r in stored(db, fid)}
    assert len(ids) == 2 * len(forecast.SPECS), "and the first rows stay where they are"
    assert len(stored(db, fid)) == 2 * len(first)


def test_a_result_that_is_not_known_yet_changes_nothing(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    before = stored(db, fid)
    recent = w.match(AT - OUTCOME_KNOWN_AFTER + timedelta(minutes=1), 0, 1, goals=(9, 8), ht=(5, 4), settled=None)
    w.team_stats(recent, "home", corners=40, yellow_cards=15, red_cards=3)
    w.team_stats(recent, "away", corners=38, yellow_cards=14, red_cards=2)
    again = run(db, [fid])
    assert all(r.rows_written == 0 for r in again.specs.values()), "a match whose result is not known by then is not in the training"
    assert stored(db, fid) == before
    known = run(db, [fid], at=AT + timedelta(minutes=2))
    assert any(r.rows_written > 0 for r in known.specs.values()), "and a minute later it is: the numbers move"


def test_a_competition_without_history_and_a_team_nobody_knows_get_no_forecast(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    stranger = int(db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (989799, 'Newcomers') RETURNING id").fetchall()[0][0])
    new_team = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                          "status_short, status_group) VALUES (9899001, %s, %s, %s, %s, 'NS', 'scheduled') RETURNING id",
                          (w.season, stranger, w.team[1], AT + timedelta(days=1))).fetchall()[0][0]
    comp = db.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, is_tracked) "
                      "VALUES (98972, 'Small League', 'Colombia', 'league', 'club', 'domestic_league', true) RETURNING id").fetchall()[0][0]
    season = db.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2034, true) RETURNING id",
                        (comp,)).fetchall()[0][0]
    small = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                       "status_short, status_group) VALUES (9899002, %s, %s, %s, %s, 'NS', 'scheduled') RETURNING id",
                       (season, w.team[0], w.team[1], AT + timedelta(days=1))).fetchall()[0][0]
    report = run(db, [int(new_team), int(small)])
    assert not stored(db, int(new_team)) and not stored(db, int(small))
    for r in report.specs.values():
        assert r.competitions_skipped["team not known"] >= 1, "the competition fits, the team is not in it"
        assert r.competitions_skipped["short history"] >= 1, "the other competition has no finished match"
        assert r.rows_written == 0


def test_the_gate_of_the_forecast_of_a_match_applies(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    db.execute("INSERT INTO analytics.competition_data_scores (competition_season_id, computed_at, rule_version, class, score, finished, approved, "
               "quarantined, components) VALUES (%s, %s, 'test', 'INSUFFICIENT', 0.1, 0, 0, 0, '{}'::jsonb)", (w.season, AT - timedelta(hours=2)))
    report = run(db, [fid])
    assert (report.targets, report.not_fit) == (1, 1) and not report.specs and not stored(db, fid), "a competition the models do not trust"
    db.execute("UPDATE analytics.competition_data_scores SET class = 'PRODUCT_ONLY' WHERE competition_season_id = %s", (w.season,))
    assert run(db, [fid]).not_fit == 1
    db.execute("UPDATE analytics.competition_data_scores SET class = 'MODEL_READY' WHERE competition_season_id = %s", (w.season,))
    db.execute("INSERT INTO analytics.fixture_validation (fixture_id, state, rule_version, failed, validated_at) "
               "VALUES (%s, 'QUARANTINED', 'test', '[]'::jsonb, %s)", (fid, AT - timedelta(hours=1)))
    assert run(db, [fid]).not_fit == 1, "and a match that failed validation"


def test_a_dispersion_measured_on_too_few_matches_states_nothing(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 300)
    catalogue(db)
    played(w)
    fid = upcoming(w)
    report = run(db, [fid])
    assert "nothing stated" in report.specs["corners_ft"].note and report.specs["corners_ft"].rows_written == 0
    assert report.specs["goals_halves"].rows_written > 0, "the goals of a half are Poisson: they have no dispersion to measure"
    assert {r[5] for r in stored(db, fid)} == {"GOALS_HALF"}


def test_the_dispersion_is_measured_once_a_day_when_the_process_keeps_it(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    calls: list[str] = []
    real = forecast.out_of_sample

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(str(kwargs["measure"]))
        return real(*args, **kwargs)

    monkeypatch.setattr(forecast, "out_of_sample", counting)
    over_dispersed = sum(1 for s in forecast.SPECS if s.over_dispersed)
    memory: forecast.DispersionCache = {}
    forecast.write_family_forecasts(db, at=AT, code_version="test", fixture_ids=[fid], dispersions=memory)
    assert len(calls) == over_dispersed and len(memory) == over_dispersed, "the first pass of the day measures each one"
    forecast.write_family_forecasts(db, at=AT + timedelta(hours=3), code_version="test", fixture_ids=[fid], dispersions=memory)
    assert len(calls) == over_dispersed, "the passes that follow the same day reuse them"
    forecast.write_family_forecasts(db, at=AT + timedelta(days=1), code_version="test", fixture_ids=[fid], dispersions=memory)
    assert len(calls) == 2 * over_dispersed and {k[1] for k in memory} == {(AT + timedelta(days=1)).date()}, "the next day measures them again and drops yesterday's"
    forecast.write_family_forecasts(db, at=AT + timedelta(days=1, hours=1), code_version="test", fixture_ids=[fid])
    assert len(calls) == 3 * over_dispersed, "with no memory every call measures"


def over(db: psycopg.Connection[Any], fixture_id: int, key: str, line: float) -> float:
    """The latest probability stated for the Over of a line (the rows of a market are ordered by the moment they were written)."""
    return float([r for r in stored(db, fixture_id) if r[0] == key and float(r[1]) == line and r[2] == "Over"][-1][3])


def digests(db: psycopg.Connection[Any], fixture_id: int, family: str) -> set[str]:
    return {str(r[0]) for r in db.execute("SELECT input_hash FROM models.match_forecasts WHERE fixture_id = %s AND version = %s AND family = %s",
                                         (fixture_id, forecast.VERSION, family)).fetchall()}


def test_a_referee_who_gives_more_cards_moves_the_cards_and_only_the_cards(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    strict, calm = referees(db, "Strict Referee", "Calm Referee")
    played(w, refs=((strict, 2.0), (calm, 0.5)))
    with_strict, with_calm, nobody, late = (upcoming(w, when=timedelta(days=1, hours=h)) for h in range(4))
    whistle(db, with_strict, strict, AT - timedelta(hours=5))
    whistle(db, with_calm, calm, AT - timedelta(hours=5))
    whistle(db, late, strict, AT + timedelta(minutes=1))  # named after the pass: not known by then
    report = run(db, [with_strict, with_calm, nobody, late])
    cards = report.specs["cards_lines_ft"]
    assert cards.uses_referee and cards.with_referee == 2 and "(2 with a referee)" in report.summary(), report.summary()
    assert not any(report.specs[k].uses_referee for k in ("corners_ft", "yellow_ft", "goals_halves"))

    strict_p, calm_p, nobody_p = (over(db, f, "CARDS_OU", 4.5) for f in (with_strict, with_calm, nobody))
    assert calm_p + 0.2 < nobody_p < strict_p - 0.2, "the strict referee's match is expected to have more cards, the calm one's fewer"
    assert over(db, late, "CARDS_OU", 4.5) == pytest.approx(nobody_p), "a referee seen after the moment of the numbers is not known"
    for key, line in (("CORNERS_OU", 9.5), ("YELLOW_OU", 3.5), ("OU_1H", 0.5)):
        assert over(db, with_strict, key, line) == pytest.approx(over(db, nobody, key, line)), "the other families do not look at the referee"
    assert len(digests(db, with_strict, "CARDS")) == 1 and digests(db, with_strict, "CARDS") != digests(db, nobody, "CARDS")
    assert digests(db, with_strict, "CARDS") != digests(db, with_calm, "CARDS"), "what the number was computed from holds the referee"

    version = db.execute("SELECT v.version, v.feature_names, v.hyperparameters FROM models.model_versions v JOIN models.model_registry r "
                         "ON r.id = v.model_id WHERE r.name = 'family-cards_lines_ft'").fetchall()
    assert len(version) == 1 and ",referee=" in version[0][0] and "referee" in version[0][1]
    assert version[0][2]["referee_kappa"] == next(s.referee_kappa for s in forecast.SPECS if s.key == "cards_lines_ft")


def test_a_referee_named_later_changes_the_cards_and_writes_them_again(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    strict, calm = referees(db, "Strict Referee", "Calm Referee")
    played(w, refs=((strict, 2.0), (calm, 0.5)))
    fid = upcoming(w)
    first = run(db, [fid])
    before = over(db, fid, "CARDS_OU", 4.5)
    assert first.specs["cards_lines_ft"].with_referee == 0
    whistle(db, fid, strict, AT + timedelta(minutes=30))
    second = run(db, [fid], at=AT + timedelta(hours=1))
    assert second.specs["cards_lines_ft"].with_referee == 1 and second.specs["cards_lines_ft"].rows_written > 0
    assert all(second.specs[k].rows_written == 0 for k in ("corners_ft", "yellow_ft", "goals_halves")), "only the cards moved"
    assert over(db, fid, "CARDS_OU", 4.5) > before + 0.2
    third = run(db, [fid], at=AT + timedelta(hours=2))
    assert all(r.rows_written == 0 for r in third.specs.values()), "and the same referee a pass later changes nothing"

