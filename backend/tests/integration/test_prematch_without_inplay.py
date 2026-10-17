"""The pre-match pipeline gives the same answer whatever the in-play book holds - so removing its history cannot
change a forecast, a consensus, a candidate, a pick or a settlement (revisions 0068 and 0069).

Run the chain from test_pick_pipeline twice for the same match and the same pre-match prices: once with no in-play
data at all, once with the in-play book full of absurd prices for that very match (and, while the old history
tables still exist, absurd history too). Every derived row must come out identical, and the settlement must follow
the 90-minute result alone.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.ingestion.ledger import RunLedger
from fbi.market.consensus import recompute_from_snapshots
from fbi.odds.live_repository import LiveOddsRepository
from fbi.picks.engine import evaluate_captures, settle_open_picks
from fbi.predictions.forecast import forecast_upcoming
from fbi.providers.api_football.live import LiveFixtureState, LiveOddsQuote
from tests.integration.test_pick_pipeline import (  # noqa: F401 (fixture)
    AT,
    CAPTURED,
    KO,
    _snapshot,
    league,
)

ABSURD = Decimal("97.000")


def _outputs(db: psycopg.Connection, target: int) -> dict[str, list[tuple[Any, ...]]]:
    """Everything the pre-match chain derives for the match, without ids or wall-clock stamps."""
    queries = {
        "predictions": "SELECT market_key, selection, line, p_raw, p_calibrated FROM models.predictions "
                       "WHERE fixture_id = %s ORDER BY 1, 2, 3, 4",
        "consensus": "SELECT market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, overround, "
                     "best_odds, dispersion FROM market.market_consensus WHERE fixture_id = %s ORDER BY 1, 2, 3, 4",
        "candidates": "SELECT market_key, selection, line, bookmaker_id, market_odds, p_calibrated, p_market_fair, "
                      "edge, ev, decision, rejection_reason, odds_captured_at, odds_payload_hash "
                      "FROM picks.pick_candidates WHERE fixture_id = %s ORDER BY 1, 2, 3, 4, 5",
        "picks": "SELECT market_key, selection, line, status, mode, market_odds, bookmaker_id, p_calibrated, "
                 "p_market_fair, edge, ev, odds_captured_at, odds_payload_hash "
                 "FROM picks.picks WHERE fixture_id = %s ORDER BY 1, 2, 3, 6, 7, 8, 12",  # total: two models, one selection
    }
    out: dict[str, list[tuple[Any, ...]]] = {}
    with db.cursor() as cur:
        for key, sql in queries.items():
            cur.execute(sql, (target,))
            out[key] = list(cur.fetchall())
    return out


def _clear_derived(db: psycopg.Connection, target: int) -> None:
    with db.cursor() as cur:
        cur.execute("DELETE FROM audit.notifications")
        cur.execute("DELETE FROM picks.picks WHERE fixture_id = %s", (target,))
        cur.execute("DELETE FROM picks.pick_candidates WHERE fixture_id = %s", (target,))
        cur.execute("DELETE FROM market.market_consensus WHERE fixture_id = %s", (target,))
    db.commit()


def _fill_the_inplay_book(db: psycopg.Connection, target: int) -> None:
    """Absurd in-play prices for the very match the chain is judging, at an instant before its pre-match price."""
    with db.cursor() as cur:
        cur.execute("SELECT provider_fixture_id FROM core.fixtures WHERE id = %s", (target,))
        provider_id = int((cur.fetchone() or (0,))[0])
    at = CAPTURED - timedelta(minutes=5)
    state = LiveFixtureState(provider_fixture_id=provider_id, captured_at=at, payload_hash="pipeline-odds",
                             elapsed_minute=88, score_home=5, score_away=0, status_long="Second Half")
    quotes = [LiveOddsQuote(provider_fixture_id=provider_id, provider_bet_id=59, market_key="1X2", selection=sel,
                            line=Decimal(0), odds_decimal=ABSURD, is_suspended=False, is_main_line=None,
                            elapsed_minute=88, elapsed_seconds="88:00", score_home=5, score_away=0,
                            status_long="Second Half", is_stopped=False, is_blocked=False, provider_updated_at=at,
                            captured_at=at, payload_hash="pipeline-odds")
              for sel in ("Home", "Draw", "Away")]
    LiveOddsRepository(db).write([state], quotes)
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('market.live_odds_snapshots') IS NOT NULL")
        if (cur.fetchone() or (False,))[0]:
            for sel in ("Home", "Draw", "Away"):
                cur.execute("INSERT INTO market.live_odds_snapshots (fixture_id, provider_bet_id, market_key, "
                            "selection, line, odds_decimal, captured_at, payload_hash) VALUES "
                            "(%s, 59, '1X2', %s, 0, %s, %s, 'pipeline-odds')", (target, sel, ABSURD, at))
    db.commit()


def _empty_the_inplay_book(db: psycopg.Connection) -> None:
    with db.cursor() as cur:
        cur.execute("DELETE FROM market.live_odds_current")
        cur.execute("DELETE FROM market.live_fixture_current")
        cur.execute("SELECT to_regclass('market.live_odds_snapshots') IS NOT NULL")
        if (cur.fetchone() or (False,))[0]:
            cur.execute("DELETE FROM market.live_odds_snapshots WHERE payload_hash = 'pipeline-odds'")
    db.commit()


def _run_chain(db: psycopg.Connection, target: int, books: list[int]) -> None:
    with db.cursor() as cur:
        for book, home in ((books[0], Decimal("2.40")), (books[1], Decimal("1.95"))):
            _snapshot(cur, target, book, "Home", home)
            _snapshot(cur, target, book, "Draw", Decimal("3.60"))
            _snapshot(cur, target, book, "Away", Decimal("3.90"))
    recompute_from_snapshots(db, fixture_ids=[target])
    db.commit()
    evaluate_captures(db, run_id=RunLedger(db).open("shadow_picks"), code_version="pipetest")
    db.commit()


def test_the_prematch_chain_ignores_the_inplay_book_from_forecast_to_settlement(
    db: psycopg.Connection, league: dict[str, object]  # noqa: F811 (the fixture imported above)
) -> None:
    target = int(league["target"])  # type: ignore[call-overload]
    books: list[int] = league["books"]  # type: ignore[assignment]
    try:
        forecast_upcoming(db, at=AT, code_version="pipetest")
        db.commit()

        _run_chain(db, target, books)
        without = _outputs(db, target)
        assert without["predictions"] and without["consensus"] and without["candidates"] and without["picks"], without

        _clear_derived(db, target)
        with db.cursor() as cur:
            cur.execute("DELETE FROM market.odds_snapshots WHERE fixture_id = %s", (target,))
        db.commit()
        _fill_the_inplay_book(db, target)
        again = forecast_upcoming(db, at=AT + timedelta(minutes=10), code_version="pipetest")
        db.commit()
        assert again.written == 0, "no new information for the forecast: in-play prices are not information to it"
        _run_chain(db, target, books)
        with_inplay = _outputs(db, target)
        assert with_inplay == without, "the in-play book changed something the pre-match chain derived"

        # Settlement follows the 90-minute result alone, with the in-play book still full of absurd prices.
        with db.cursor() as cur:
            cur.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
                        (target,))
            cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 0, 2)",
                        (target,))
        settled = settle_open_picks(db, run_id=RunLedger(db).open("shadow_picks"))
        db.commit()
        with db.cursor() as cur:
            cur.execute("SELECT p.selection, r.result_status FROM picks.pick_results r JOIN picks.picks p "
                        "ON p.id = r.pick_id WHERE p.fixture_id = %s ORDER BY 1", (target,))
            results = cur.fetchall()
        assert settled.settled == len(results)
        assert all(status == ("win" if sel == "Away" else "loss") for sel, status in results), results
        assert KO > AT
    finally:
        _empty_the_inplay_book(db)
        with db.cursor() as cur:
            cur.execute("DELETE FROM core.fixture_results WHERE fixture_id = %s", (target,))
            cur.execute("DELETE FROM picks.pick_results WHERE pick_id IN (SELECT id FROM picks.picks "
                        "WHERE fixture_id = %s)", (target,))
        db.commit()
