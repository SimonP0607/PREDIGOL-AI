"""REVIEW PREDIGOL (11 Oct 2026), point 5: the Estadísticas tab before kick-off shows everything we hold about the
two teams - and says on how many matches each figure rests. A figure the data does not carry is null with n=0,
never a zero; an own goal first, or a match without events, is left out of "scored first" rather than guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg

from fbi.api.services.profile import match_profile
from tests.integration.conftest import Seed

KO = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)


def _at_ko(db: psycopg.Connection, seed: Seed) -> None:
    """Pin the seed match for this test - its kick-off, season and teams: other suites move the kick-off and
    re-file the teams (the transaction is rolled back)."""
    db.execute("UPDATE core.fixtures SET kickoff_at = %s, status_short = 'NS', status_group = 'scheduled', "
               "competition_season_id = %s, home_team_id = %s, away_team_id = %s WHERE id = %s",
               (KO, seed.season_id, seed.home_team_id, seed.away_team_id, seed.fixture_id))


def _team(db: psycopg.Connection, provider_id: int, name: str) -> int:
    row = db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                     (provider_id, name)).fetchone()
    assert row is not None
    return int(row[0])


def _played(db: psycopg.Connection, seed: Seed, pid: int, home: int, away: int, days_before: int,
            score: tuple[int, int], ht: tuple[int, int] | None, *, season: int | None = None) -> int:
    row = db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
        "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
        (pid, season or seed.season_id, home, away, KO - timedelta(days=days_before))).fetchone()
    assert row is not None
    fid = int(row[0])
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away) "
               "VALUES (%s, %s, %s, %s, %s)", (fid, score[0], score[1], ht[0] if ht else None,
                                               ht[1] if ht else None))
    return fid


def _goal(db: psycopg.Connection, seed: Seed, fid: int, seq: int, minute: int, side: str,
          detail: str = "Normal Goal", comments: str | None = None) -> None:
    db.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, detail, "
               "comments, payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, %s, 'Goal', %s, %s, %s, now())",
               (fid, seq, minute, side, detail, comments, seed.payload_hash))


def _stats(db: psycopg.Connection, seed: Seed, fid: int, side: str, *, corners: int | None, shots: int,
           source: str = "api-football", xg: str | None = None) -> None:
    db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, corners, expected_goals, "
               "yellow_cards, payload_hash, fetched_at) VALUES (%s, %s, %s, %s, %s, %s, 2, %s, now())",
               (fid, side, source, shots, corners, xg, seed.payload_hash))


def _metric(env: object, scope: str, key: str) -> tuple[object, object]:
    data = env.data  # type: ignore[attr-defined]
    sc = next(s for s in data.scopes if s.scope == scope)
    m = next(x for x in sc.metrics if x.key == key)
    return m.home, m.away


def test_the_profile_counts_only_what_the_data_carries(db: psycopg.Connection, seed: Seed) -> None:
    _at_ko(db, seed)
    other = _team(db, 9901, "Other FC")
    h = seed.home_team_id
    # three finished matches of the home side before kick-off, newest first: 2-1 W (home), 0-0 D (away), 1-3 L (home)
    a = _played(db, seed, 99001, h, other, 3, (2, 1), (1, 0))
    _played(db, seed, 99002, other, h, 10, (0, 0), (0, 0))  # 0-0: nobody scored first, and that is known
    c = _played(db, seed, 99003, h, other, 20, (1, 3), None)
    _goal(db, seed, a, 1, 10, "home")                  # scored first
    _goal(db, seed, a, 2, 50, "away")
    _goal(db, seed, a, 3, 80, "home", "Penalty")
    _goal(db, seed, a, 4, 85, "away", "Missed Penalty")  # the other side's miss: not ours
    _goal(db, seed, c, 1, 5, "away", "Own Goal")         # an own goal first: unknown, left out
    _goal(db, seed, c, 2, 60, "home", "Missed Penalty")
    _stats(db, seed, a, "home", corners=7, shots=15, xg="1.80")
    _stats(db, seed, a, "away", corners=3, shots=9, xg="0.70")
    _stats(db, seed, a, "home", corners=99, shots=99, source="football-data.co.uk")  # never mixed in
    _stats(db, seed, c, "home", corners=None, shots=11)  # a source without corners
    _stats(db, seed, c, "away", corners=None, shots=12)
    # a match AFTER kick-off never counts
    _played(db, seed, 99004, h, other, -2, (5, 0), (3, 0))

    env = match_profile(db, seed.fixture_id)
    assert env.status.value == "ok"
    assert env.data is not None and env.data.window == 10
    sc = env.data.scopes[0]
    assert (sc.scope, sc.home_matches) == ("all", 3)

    wins, _ = _metric(env, "all", "wins")
    assert (wins.count, wins.n, wins.value) == (1, 3, Decimal("0.3333"))  # type: ignore[attr-defined]
    ht, _ = _metric(env, "all", "ht_lead")
    assert (ht.count, ht.n) == (1, 2), "the match without a half-time score is left out"  # type: ignore[attr-defined]
    first, _ = _metric(env, "all", "scored_first")
    # a: own first; b: 0-0 (known: nobody); c: own goal first (unknown) -> 1 of 2
    assert (first.count, first.n) == (1, 2)  # type: ignore[attr-defined]
    corners, _ = _metric(env, "all", "corners")
    assert (corners.value, corners.n) == (Decimal("7.0000"), 1), "no corner data is not zero corners"  # type: ignore[attr-defined]
    shots, _ = _metric(env, "all", "shots")
    assert (shots.value, shots.n) == (Decimal("13.0000"), 2)  # type: ignore[attr-defined]
    xg_against, _ = _metric(env, "all", "xg_against")
    assert (xg_against.value, xg_against.n) == (Decimal("0.7000"), 1)  # type: ignore[attr-defined]
    pens, _ = _metric(env, "all", "penalties")
    assert (pens.count, pens.total, pens.n) == (1, 2, 2), "1 scored of 2 taken, over the 2 matches with events"  # type: ignore[attr-defined]
    goals_for, _ = _metric(env, "all", "goals_for")
    assert (goals_for.value, goals_for.n) == (Decimal("1.0000"), 3)  # type: ignore[attr-defined]


def test_the_competition_scope_keeps_to_this_competition(db: psycopg.Connection, seed: Seed) -> None:
    _at_ko(db, seed)
    other = _team(db, 9902, "Cup Rival")
    row = db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                     "VALUES (45, 'FA Cup', 'cup', 'club', 'domestic_cup') RETURNING id").fetchone()
    assert row is not None
    cup = db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) RETURNING id",
                     (row[0],)).fetchone()
    assert cup is not None
    _played(db, seed, 99011, seed.home_team_id, other, 4, (3, 0), (1, 0), season=int(cup[0]))
    _played(db, seed, 99012, seed.home_team_id, other, 8, (0, 1), (0, 0))
    env = match_profile(db, seed.fixture_id)
    assert env.data is not None
    by = {s.scope: s for s in env.data.scopes}
    assert (by["all"].home_matches, by["competition"].home_matches) == (2, 1)
    wins_comp, _ = _metric(env, "competition", "wins")
    assert wins_comp.count == 0, "the cup win is not a league win"  # type: ignore[attr-defined]


def test_no_history_is_empty_not_zero(db: psycopg.Connection, seed: Seed) -> None:
    home, away = _team(db, 9931, "New Home"), _team(db, 9932, "New Away")
    row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                     "kickoff_at) VALUES (99031, %s, %s, %s, %s) RETURNING id",
                     (seed.season_id, home, away, KO)).fetchone()
    assert row is not None
    env = match_profile(db, int(row[0]))
    assert env.status.value == "empty"
    assert env.data is not None
    wins, _ = _metric(env, "all", "wins")
    assert (wins.value, wins.n) == (None, 0)  # type: ignore[attr-defined]


# ── point 10: every captured price, the Cronología's numbers ───────────────


def _quote(db: psycopg.Connection, seed: Seed, book: int, market: str, sel: str, line: str, odds: str,
           at: datetime, source: str = "prematch") -> None:
    db.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal, "
               "captured_at, minutes_to_ko, source, payload_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
               (seed.fixture_id, book, market, sel, line, odds, at, int((KO - at).total_seconds() // 60), source,
                seed.payload_hash))


def test_every_captured_price_is_shown_with_the_cronologia_numbers(db: psycopg.Connection, seed: Seed) -> None:
    _at_ko(db, seed)
    from fbi.api.repositories import fixtures as fixtures_repo
    from fbi.api.services.matches import timeline
    from fbi.api.services.profile import match_markets

    row = db.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (11, '1xBet') RETURNING id"
                     ).fetchone()
    assert row is not None
    other = int(row[0])
    first, last = KO - timedelta(hours=24), KO - timedelta(hours=3)
    db.execute("INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive) VALUES "
               "('OU', 'Over/Under', 2, true, true) ON CONFLICT (key) DO NOTHING")
    for at, home_price in ((first, "2.10"), (last, "1.95")):
        _quote(db, seed, seed.bookmaker_id, "1X2", "Home", "0", home_price, at)
        _quote(db, seed, seed.bookmaker_id, "OU", "Over", "3.5", "2.40", at)
    _quote(db, seed, other, "1X2", "Home", "0", "2.05", last)  # a second bookmaker, only in the last capture

    env = match_markets(db, seed.fixture_id)
    assert env.status.value == "ok" and env.data is not None
    m = env.data
    assert [(c.quotes, c.bookmakers, c.by_market) for c in m.captures] == [
        (2, 1, {"1X2": 1, "OU": 1}), (3, 2, {"1X2": 2, "OU": 1})]
    assert m.quotes == 5
    home = next(s for s in m.selections if s.market_key == "1X2" and s.selection == "Home")
    assert [(b.bookmaker, b.odds, b.opening_odds, b.captures) for b in home.books] == [
        ("1xBet", Decimal("2.05"), Decimal("2.05"), 1), ("Bet365", Decimal("1.95"), Decimal("2.10"), 2)]
    assert any(s.market_key == "OU" and s.line == Decimal("3.5") for s in m.selections), (
        "an off-main line is shown too: no pick rule filters this view")

    # the Cronología counts the same captures, quote for quote
    fx = fixtures_repo.get_fixture(db, seed.fixture_id)
    assert fx is not None
    events = timeline(fx, fixtures_repo.capture_instants(db, seed.fixture_id), KO - timedelta(hours=1))
    counted = sorted(int(e.vars.get("quotes", 0)) for e in events if e.code in ("window_done", "extra_capture"))
    assert counted == sorted(c.quotes for c in m.captures)


def test_no_capture_is_empty(db: psycopg.Connection, seed: Seed) -> None:
    from fbi.api.services.profile import match_markets
    env = match_markets(db, seed.fixture_id)
    assert env.status.value == "empty" and env.data is not None and env.data.selections == []
