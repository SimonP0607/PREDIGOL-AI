"""``market-signals-v1`` (IA-011, shadow) against the real schema: odds snapshots seeded in ``market.odds_snapshots`` are read as of a
moment (nothing captured later, nothing at or after kick-off, nothing in-play), turned into the same numbers the pure functions give, and
the CLV after kick-off is the closing reference's. The command's ``show`` and ``day`` read the pipeline's decisions for the model's
probability and the taken price. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import ia_market_signals as cli

from fbi.market import closing_value
from fbi.market import signals as s
from fbi.market.closing_reference import Key

from .conftest import Seed
from .helpers import scalar

pytestmark = pytest.mark.integration


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        self.cur = db.cursor()
        self.ko = scalar(self.cur.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (seed.fixture_id,)))
        self.books = [seed.bookmaker_id]
        for pid in (9801, 9802):
            self.cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id",
                             (pid, f"Book {pid}"))
            self.books.append(scalar(self.cur))
        self.key: Key = (seed.fixture_id, "1X2", "Home", Decimal(0))

    def capture(self, minutes_to_ko: int, home: str, *, source: str = "prematch", books: int = 3) -> None:
        at = self.ko - timedelta(minutes=minutes_to_ko)
        h = f"sig-{source}-{minutes_to_ko}"
        self.cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
                         "VALUES (%s, %s, '/odds', %s, 200, 'x', 1)", (h, self.seed.run_id, at))
        for b in self.books[:books]:
            for selection, odds in (("Home", home), ("Draw", "3.40"), ("Away", "3.80")):
                self.cur.execute(
                    "INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal, "
                    "captured_at, minutes_to_ko, source, payload_hash) VALUES (%s, %s, '1X2', %s, 0, %s, %s, %s, %s, %s)",
                    (self.seed.fixture_id, b, selection, Decimal(odds), at, minutes_to_ko, source, h))

    def close(self, minutes_to_ko: int, p: str) -> None:
        self.cur.execute(
            "INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, "
            "overround, best_odds, best_bookmaker_id) VALUES (%s, '1X2', 'Home', 0, %s, 'shin', %s, 3, 1.05, 1.85, %s)",
            (self.seed.fixture_id, self.ko - timedelta(minutes=minutes_to_ko), Decimal(p), self.seed.bookmaker_id))

    def decision(self, minutes_to_ko: int, p_model: str, odds: str, *, version: str = "decision-v1") -> int:
        known = self.ko - timedelta(minutes=minutes_to_ko)
        self.cur.execute(
            "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, "
            "model_name, odds, bookmaker_id, price_at, n_bookmakers, p_model, filters, state, context_status, input_hash) "
            "VALUES (%s, %s, 'T-3h', %s, %s, '1X2', 'Home', 0, 'dixon_coles', %s, %s, %s, 3, %s, %s, 'INVESTIGACION', 'AI_OFF', %s) "
            "RETURNING id",
            (version, known, self.seed.fixture_id, self.ko, Decimal(odds), self.seed.bookmaker_id, known, Decimal(p_model),
             Jsonb([]), f"sig-{version}-{minutes_to_ko}"))
        return int(scalar(self.cur))

    def standard(self) -> None:
        self.capture(26 * 60, "2.00")
        self.capture(120, "1.95")
        self.capture(90, "1.70")  # three books shorten Home together within 30 minutes: steam
        self.capture(60, "1.30", books=1, source="live")  # not the pre-match series
        self.capture(-5, "1.20")  # after kick-off: not pre-match


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


def test_the_signals_read_only_what_was_captured_by_the_moment(w: World) -> None:
    w.standard()
    early = s.read_signals(w.db, w.key, at=w.ko - timedelta(minutes=100), p_model=0.60)
    assert early is not None and early.n_captures == 2, "the T-90m capture was not known at T-100m"
    kickoff, captures = s.read_captures(w.db, w.key[0], "1X2", at=w.ko - timedelta(minutes=100))
    assert kickoff == w.ko and early == s.market_signals(captures, w.key, at=w.ko - timedelta(minutes=100), kickoff_at=w.ko,
                                                         p_model=0.60), "the reader is a thin layer over the pure functions"
    assert early.current is not None and (early.current.n_bookmakers, early.current.best_odds) == (3, Decimal("1.950"))
    assert early.staleness_minutes == pytest.approx(20) and not early.stale
    assert early.sharp.status == s.NO_SHARP_SOURCE and early.closing.status == s.BEFORE_KICKOFF
    assert [v.status for v in early.velocities] == [s.OK] * 3, "every window reaches back to the T-26h opening"
    assert early.velocities[0].delta_points == pytest.approx(early.movement_points)
    assert early.velocities[0].reference_at == w.ko - timedelta(hours=26)


def test_after_kickoff_the_series_stops_at_it_and_the_clv_is_the_closing_references(w: World) -> None:
    w.standard()
    w.close(40, "0.55")
    got = s.read_signals(w.db, w.key, at=w.ko + timedelta(hours=3), p_model=0.60, taken_odds=2.0)
    assert got is not None and got.n_captures == 3, "neither the in-play row nor the one after kick-off is pre-match"
    assert got.effective_at == w.ko and got.staleness_minutes == pytest.approx(90) and got.stale is False
    assert got.steam and got.steam_events[0].direction == s.UP and len(got.steam_events[0].books) == 3
    assert got.movement_points is not None and got.movement_points > 3 and got.side == s.TOWARD
    assert (got.closing.status, got.closing.p_close) == (s.OK, 0.55)
    assert got.closing.clv == pytest.approx(closing_value.clv(2.0, 0.55))
    assert got.closing.close is not None and got.closing.close.minutes_to_ko == 40


def test_no_snapshot_no_close_and_an_unknown_fixture(w: World) -> None:
    got = s.read_signals(w.db, w.key, at=w.ko + timedelta(hours=1), p_model=0.5, taken_odds=2.0)
    assert got is not None and got.status == s.NO_PRICES and got.closing.status == s.NO_CLOSE
    assert s.read_signals(w.db, (-1, "1X2", "Home", Decimal(0)), at=w.ko) is None
    doc, code = cli.show(w.db, (-1, "1X2", "Home", Decimal(0)), at=w.ko)
    assert code == cli.CANNOT and "unknown" in doc["error"]


def test_show_takes_the_model_and_the_price_from_the_newest_decision_known_then(w: World) -> None:
    w.standard()
    w.close(40, "0.55")
    w.decision(300, "0.400000", "2.100")
    newest = w.decision(100, "0.450000", "1.950")
    w.decision(50, "0.900000", "1.500", version="decision-fam-v1")  # another layer: never read
    doc, code = cli.show(w.db, w.key, at=w.ko + timedelta(hours=2))
    assert code == cli.OK and doc["decision"]["id"] == newest and doc["p_model"] == 0.45
    assert doc["closing"]["odds"] == 1.95 and doc["side"] == s.AGAINST, "the model saw Home less likely; the market shortened it"
    before, _ = cli.show(w.db, w.key, at=w.ko - timedelta(minutes=200))
    assert before["decision"]["known_at"] == (w.ko - timedelta(minutes=300)).isoformat()
    assert "side against" in cli.render("show", doc)


def test_the_day_summarises_the_decisions_of_its_matches(w: World) -> None:
    w.standard()
    w.close(40, "0.55")
    w.decision(100, "0.450000", "1.950")
    doc, code = cli.day(w.db, date(2026, 9, 15), now=w.ko + timedelta(hours=4))
    assert code == cli.OK and doc["shadow"] is True
    summary = doc["summary"]
    assert (summary["selections"], summary["priced"], summary["sided"], summary["against"], summary["with_steam"],
            summary["clv_n"]) == (1, 1, 1, 1, 1, 1)
    assert summary["against_share"] == 1.0 and summary["median_movement_points"] > 3
    empty, _ = cli.day(w.db, date(2026, 9, 16), now=w.ko + timedelta(hours=4))
    assert empty["summary"]["selections"] == 0 and empty["summary"]["against_share"] is None
    assert "day 2026-09-15" in cli.render("day", doc)
