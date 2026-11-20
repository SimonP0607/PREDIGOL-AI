"""PM-02-04: the resolver of the seven states on a real database, and its acceptance - for 1,000 selections of sample, Mi parlay's verdict
as the resolver gives it is EXACTLY the one ``fbi.userdata.records.validate_parlay`` gives today for that selection as one leg (refusals and
their order), with Mi parlay's switch on and off and the catalogue's states of every kind."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count

import psycopg
import pytest

import fbi.coverage.resolve as resolve
import fbi.market.in_force as in_force
from fbi.odds.quote_current import CurrentBook, CurrentQuote
from fbi.userdata.records import LegIn, MarketPolicy, validate_parlay

pytestmark = pytest.mark.integration
AT = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def parlay_rules() -> resolve.ParlayRules:
    """Mi parlay's own checks, as the API hands them to the resolver (``fbi.api.services.availability.parlay_rules``)."""
    from fbi.picks.count_settlement import settle_numbers
    from fbi.userdata import records

    return resolve.ParlayRules(core_markets=records.CORE_MARKETS, lookback=records.SNAPSHOT_LOOKBACK,
                               valid_selection=records.valid_selection, quarter_line=records.quarter_line,
                               outlier_price=records.outlier_price, grade=settle_numbers)
_ids = count(950_000)

CATALOGUE = (  # (bet, family, kind, period, subject, name)
    (45, "corners", "over_under", "FT", "match", "Corners Over Under"),
    (55, "corners", "one_x_two", "FT", "match", "Corners 1x2"),
    (80, "cards", "over_under", "FT", "match", "Cards Over/Under"),
    (6, "goals_half", "over_under", "1H", "match", "Goals Over/Under First Half"),
    (87, "shots", "over_under", "FT", "match", "Total ShotOnGoal"),
    (1, "result", "one_x_two", "FT", "match", "Match Winner"),
)
SELECTIONS = ("Home", "Draw", "Away", "Over", "Under", "Yes", "No", "1", "X")
LINES = tuple(Decimal(x) for x in ("0", "0.5", "1.5", "2.5", "2.25", "-1", "-0.75", "9.5", "10", "4.5"))


def one(c: psycopg.Connection, sql: str, params: tuple[object, ...] | None = None) -> int:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture()
def world(migrated_database: str) -> Iterator[tuple[psycopg.Connection, list[int], dict[int, tuple[CurrentQuote, ...]]]]:
    """A season with 12 finished matches (corners in 11, cards in none), three matches to come and one started, consensus prices of the
    core markets (two of them outliers) and a book of catalogue prices per match, 1 to 5 houses."""
    rng = random.Random(1602)
    with psycopg.connect(migrated_database) as c:
        comp = one(c, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                      "VALUES (%s, 'Liga R', 'league', 'club', 'domestic_league') RETURNING id", (next(_ids),))
        cs = one(c, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,))
        h = f"res-{next(_ids)}"
        run = one(c, "INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES ('t', 't', 'completed') RETURNING id")
        c.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
                  "VALUES (%s, %s, '/x', now(), 200, 'x', 1)", (h, run))
        books = [one(c, "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id",
                     (next(_ids), f"Casa {i}")) for i in range(5)]

        def fixture(kickoff: datetime, status: tuple[str, str]) -> int:
            a = one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'A') RETURNING id", (next(_ids),))
            b = one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'B') RETURNING id", (next(_ids),))
            return one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                          "status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                       (next(_ids), cs, a, b, kickoff, *status))

        for i in range(12):
            fid = fixture(AT - timedelta(days=30 - i), ("FT", "finished"))
            c.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away) "
                      "VALUES (%s, 2, 1, 1, 0)", (fid,))
            for side in ("home", "away"):
                c.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, corners, payload_hash, fetched_at) "
                          "VALUES (%s, %s, 'api-football', %s, %s, now())", (fid, side, None if i == 0 else 5, h))
        upcoming = [fixture(AT + timedelta(hours=5 + i), ("NS", "scheduled")) for i in range(3)]
        started = fixture(AT - timedelta(minutes=20), ("1H", "live"))
        quotes: dict[int, tuple[CurrentQuote, ...]] = {}
        for fid in [*upcoming, started]:
            for key, sels, line in (("1X2", ("Home", "Draw", "Away"), Decimal(0)), ("OU", ("Over", "Under"), Decimal("2.5")),
                                    ("BTTS", ("Yes", "No"), Decimal(0)), ("AH", ("Home", "Away"), Decimal("-0.75"))):
                for sel in sels:
                    outlier = rng.random() < 0.15
                    c.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, "
                              "n_bookmakers, overround, best_odds, best_bookmaker_id) VALUES (%s, %s, %s, %s, %s, 'shin', %s, 4, 1.05, %s, %s)",
                              (fid, key, sel, line, AT - timedelta(hours=rng.choice((1, 3, 40))), Decimal("0.40"),
                               Decimal("4.50") if outlier else Decimal("2.30"), books[0]))
            qs: list[CurrentQuote] = []
            for bet, family, kind, period, subject, name in CATALOGUE:
                n_books = rng.randint(1, 5)
                for line in rng.sample(LINES, 3):
                    for sel in SELECTIONS[:3] if kind == "one_x_two" else ("Over", "Under"):
                        for b in books[:n_books]:
                            qs.append(CurrentQuote(bookmaker_id=b, bookmaker=f"Casa {b}", bet_id=bet, family=family, period=period,
                                                   subject=subject, kind=kind, has_line=kind == "over_under", market_key=None,
                                                   provider_name=name, selection=sel, line=line if kind == "over_under" else Decimal(0),
                                                   odds=Decimal(str(round(rng.uniform(1.3, 3.5), 2))), captured_at=AT, since=AT))
            quotes[fid] = tuple(qs)
        c.commit()
        yield c, [*upcoming, started], quotes
        c.rollback()


def _book(quotes: dict[int, tuple[CurrentQuote, ...]]) -> Callable[..., CurrentBook | None]:
    def fake(conn: object, fixture_id: int) -> CurrentBook | None:
        qs = quotes.get(fixture_id)
        return None if qs is None else CurrentBook(fixture_id=fixture_id, kickoff_at=AT, in_force=None, quotes=qs)  # type: ignore[arg-type]
    return fake


def _policies() -> list[MarketPolicy | None]:
    states = ("evaluable", "en_calibracion", "necesita_datos", "no_ofrecer")
    return [None, MarketPolicy(enabled=False), MarketPolicy(enabled=True),
            MarketPolicy(enabled=True, state_of=lambda bet: states[bet % 4]),
            MarketPolicy(enabled=True, state_of=lambda bet: "en_calibracion")]


def test_mi_parlay_verdict_matches_validate_parlay_on_1000_selections(world, monkeypatch: pytest.MonkeyPatch) -> None:
    c, fixtures, quotes = world
    fake = _book(quotes)
    monkeypatch.setattr(in_force, "book", fake)          # what validate_parlay reads (imported when it runs)
    monkeypatch.setattr(resolve, "book", fake)           # and the resolver
    rng = random.Random(20261120)
    keys = ["1X2", "OU", "BTTS", "AH", "DC", "corners_over_under.FT.match", "corners_1x2.FT.match", "cards_over_under.FT.match",
            "goals_over_under_first_half.1H.match", "total_shotongoal.FT.match", "match_winner.FT.match", "nada.FT.match"]
    keys += sorted({in_force.key_of(q) for qs in quotes.values() for q in qs})
    policies = _policies()
    rules = parlay_rules()
    inputs = {(f, i): resolve.load(c, f, at=AT, rules=rules, parlay_on=bool(p and p.enabled), state_of=p.state_of if p else None)
              for f in fixtures for i, p in enumerate(policies)}
    seen: set[tuple[str, ...]] = set()
    for n in range(1000):
        fid = rng.choice(fixtures)
        pi = rng.randrange(len(policies))
        key = rng.choice(keys)
        priced = [q for q in quotes[fid] if in_force.key_of(q) == key]
        if priced and rng.random() < 0.6:
            q = rng.choice(priced)
            sel, line = q.selection, q.line
        else:
            sel, line = rng.choice(SELECTIONS), rng.choice(LINES)
        try:
            got = validate_parlay(c, [LegIn(fid, key, sel, line)], at=AT, policy=policies[pi])
            old = tuple(e["code"] for e in got.errors if e.get("leg") == 1)
        except ValueError as exc:                        # a core market by its catalogue key, unpriced: max() of nothing (a 500)
            assert "max()" in str(exc)
            c.rollback()
            old = (resolve.CRASH,)
        mine = inputs[(fid, pi)]
        assert mine is not None
        new = resolve.parlay_leg(mine, key, sel, line)
        assert new == old, (n, fid, pi, key, sel, str(line), old, new)
        seen.add(old)
    # the sample reaches every kind of verdict, not only the easy ones
    flat = {code for v in seen for code in v}
    assert () in seen
    assert {"invalid_selection", "quarter_line", "started", "market_not_priced", "outlier_price"} <= flat


def test_the_states_of_a_match(world, monkeypatch: pytest.MonkeyPatch) -> None:
    c, fixtures, quotes = world
    monkeypatch.setattr(resolve, "book", _book(quotes))
    got = resolve.availability(c, fixtures[0], at=AT, rules=parlay_rules(), parlay_on=True, state_of=lambda bet: "evaluable",
                               forecast_users=True)
    assert got is not None
    body = got.as_json()
    assert body["rules_version"] == "coverage-levels-v1" and body["fixture_id"] == fixtures[0]
    by_key = {m["key"]: m for m in body["markets"]}
    assert {"1X2", "OU", "BTTS", "AH", "DC"} <= set(by_key)
    corners = by_key["corners_over_under.FT.match"]
    assert corners["settleable"] is True                 # 11 of 12 finished matches carry the corners
    assert corners["matrix_market"] == "corners"
    cards = by_key["cards_over_under.FT.match"]
    assert cards["settleable"] is False and cards["reason"] == "sin_cobertura"
    assert cards["modules"]["mi_parlay"] == {"ok": False, "reason": "invalid_selection"}
    for m in body["markets"]:
        books = max((s["books"] for s in m["selections"]), default=0)
        assert m["price_in_force"] == (books >= 3)
        assert m["prob_authorised"] is False             # no forecast stored
    # no cell yet (the nightly batch has not run): the blocks say so instead of guessing
    assert body["blocks"]["team_stats"]["level"] is None and body["blocks"]["team_stats"]["reason"] == "sin_medir"
    assert resolve.availability(c, -1, at=AT, rules=parlay_rules()) is None
