"""The odds book's price as of a moment (``fbi.decision.book_price``, plan INT-A06, IA-037) against a real PostgreSQL: the asks of the capture and
of the book refreshes and the RAW index read by key, a capture's body priced exactly as the capture's own consensus, a refresh newer than the
capture in force, the window before kick-off - and the replay priced by the book, which writes nothing and leaves the default as it was.

The matches and the bodies are built the way the capture and the book build them (tests/integration/test_odds_book.py): a real answer of the
provider stored in RAW, its ask recorded, its consensus computed by the capture's own path."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.ai.calendar import local_day
from fbi.decision import book_price, engine, replay
from fbi.intel import decision
from fbi.market.consensus import recompute_from_snapshots
from fbi.odds.repository import OddsRepository
from fbi.providers.api_football.normalize import iter_odds
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

from .test_decision_v2_replay import core_scene, writes
from .test_intel import AT
from .test_odds_book import KO, T1, T2, ask, real_body
from .test_odds_quotes_extract import add_fixture, add_payload

pytestmark = pytest.mark.integration

PID = 870_123


def book_ask(db: psycopg.Connection[Any], pid: int, at: Any, payload_hash: str | None, results: int = 1) -> None:
    db.execute("INSERT INTO market.book_asks (provider_fixture_id, asked_at, minutes_to_ko, window_minutes, results, quotes, payload_hash) "
               "VALUES (%s, %s, %s, 120, %s, 0, %s)", (pid, at, int((KO - at).total_seconds() // 60), results, payload_hash))


def captured(db: psycopg.Connection[Any], seed: Seed, root: Path, pid: int, body: dict[str, Any], at: Any) -> str:
    """A capture as the capture makes it: the body in RAW, its prices in the snapshots, its consensus, its ask."""
    h = add_payload(db, seed, PayloadStore(root), body, fixture=pid, fetched_at=at)
    OddsRepository(db).write_snapshots(list(iter_odds(body, kickoff_at=KO, captured_at=at, payload_hash=h, source="prematch")))
    fixture_id = int(scalar(db.execute("SELECT id FROM core.fixtures WHERE provider_fixture_id = %s", (pid,))))
    recompute_from_snapshots(db, fixture_ids=[fixture_id])
    ask(db, pid, at, h)
    return h


def stored_consensus(db: psycopg.Connection[Any], fixture_id: int, as_of: Any) -> dict[tuple[str, str, Decimal], tuple[float, float, int, int]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT market_key, selection, line, best_odds::float8 AS o, p_fair::float8 AS p, n_bookmakers, best_bookmaker_id "
                    "FROM market.market_consensus WHERE fixture_id = %s AND as_of = %s AND devig_method = 'shin'", (fixture_id, as_of))
        return {(r["market_key"], r["selection"], Decimal(r["line"]).quantize(decision.LINE_Q)): (r["o"], r["p"], int(r["n_bookmakers"]),
                                                                                                  int(r["best_bookmaker_id"]))
                for r in cur.fetchall()}


def test_a_captures_body_is_priced_as_its_own_consensus_and_a_newer_refresh_is_in_force(db: psycopg.Connection[Any], seed: Seed,
                                                                                         tmp_path: Path) -> None:
    fixture_id = add_fixture(db, seed, PID, KO)
    a = captured(db, seed, tmp_path, PID, real_body(PID), T1)
    b = add_payload(db, seed, PayloadStore(tmp_path), real_body(PID, bump="0.05"), fixture=PID, fetched_at=T2)
    book_ask(db, PID, T2, b)
    ask(db, PID, KO + timedelta(minutes=5), a)          # after kick-off: not pre-match
    ask(db, PID, KO - timedelta(days=5), a)             # before the window of a pre-match answer
    before = writes(db)
    reader = book_price.read(db, PayloadStore(tmp_path), [fixture_id, 999_999_999])
    assert set(reader.fixtures) == {fixture_id}, "a match that does not exist is not read"
    assert [(x.kind, x.asked_at) for x in reader.asks[fixture_id]] == [(book_price.CAPTURE, T1), (book_price.REFRESH, T2)]
    assert set(reader.index) == {a, b} and reader.bookmakers, "the RAW index of both bodies and the bookmakers' ids"

    first = reader.answer_at(fixture_id, T1 + timedelta(minutes=1))
    assert (first.state, first.confirmed_by, first.checked_at, first.payload_hash) == ("priced", book_price.CAPTURE, T1, a)
    expected = stored_consensus(db, fixture_id, T1)
    assert expected and {k: (q.best_odds, q.p_fair, q.n_bookmakers, q.best_bookmaker_id) for k, q in first.prices.items()} == expected, (
        "the book prices a capture's body exactly as the capture's consensus")

    later = reader.answer_at(fixture_id, T2 + timedelta(minutes=1))
    assert (later.confirmed_by, later.checked_at, later.payload_hash) == (book_price.REFRESH, T2, b)
    home = ("1X2", "Home", Decimal("0.00"))
    assert later.prices[home].best_odds == pytest.approx(first.prices[home].best_odds + 0.05)
    close = book_price.closes(reader, [fixture_id])[(fixture_id, *home)]
    assert (close.confirmed_by, close.checked_at, close.minutes_to_kickoff) == (book_price.REFRESH, T2, (KO - T2).total_seconds() / 60)
    assert close.provider_minutes_to_kickoff == pytest.approx(26 * 60), "the provider's stamp of the answer (a day and two hours before)"
    assert writes(db) == before, "reading the book wrote nothing"


def test_the_replay_priced_by_the_book_reads_the_answer_in_force_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed,
                                                                                     tmp_path: Path) -> None:
    _, a, b = core_scene(db, seed)
    decision.decide(db, at=AT)
    plain = replay.replay_day(db, day=local_day(AT))
    pid_b, kickoff_b = db.execute("SELECT provider_fixture_id, kickoff_at FROM core.fixtures WHERE id = %s", (b,)).fetchone()  # type: ignore[misc]
    asked = AT - timedelta(minutes=30)
    hb = add_payload(db, seed, PayloadStore(tmp_path), real_body(int(pid_b), kickoff_b), fixture=int(pid_b), fetched_at=asked)
    ask(db, int(pid_b), asked, hb, kickoff=kickoff_b)

    before = writes(db)
    out = replay.replay_day(db, day=local_day(AT), price=engine.BOOK, store=PayloadStore(tmp_path))
    again = replay.replay_day(db, day=local_day(AT), price=engine.BOOK, store=PayloadStore(tmp_path))
    assert writes(db) == before, "the replay wrote nothing"
    assert json.dumps(out, default=str, sort_keys=True) == json.dumps(again, default=str, sort_keys=True), "and it is deterministic"

    assert plain["inputs"]["price"] == engine.CONSENSUS and out["inputs"]["price"] == engine.BOOK
    assert plain["agreement"]["rate"] == 1.0 and plain["price"]["without_age"] == 0, "the default is the evidence of P1, as it was"
    p = out["price"]
    rows_b = int(scalar(db.execute("SELECT count(*) FROM intel.decisions WHERE fixture_id = %s AND checkpoint <> 'selection'", (b,))))
    rows_a = int(scalar(db.execute("SELECT count(*) FROM intel.decisions WHERE fixture_id = %s AND checkpoint <> 'selection'", (a,))))
    assert p["confirmed_by"] == {"capture": rows_b} and p["missing"] == {"never_asked": rows_a}, "match a was never asked: no book price"
    assert p["without_age"] == 0 and p["age_minutes"]["p50"] == p["age_minutes"]["max"] == 30.0
    assert p["close"]["decisions"] == rows_b and p["close"]["minutes_to_kickoff"]["p50"] == (kickoff_b - asked).total_seconds() / 60
    assert p["reader"]["matches"] == 2 and p["reader"]["bodies_read"] == 1 and p["reader"]["unreadable"] == 0
    stages = {d["stage"] for d in out["disagreements"] if d["fixture_id"] == a}
    assert stages <= {"market"}, "without a book price match a is rejected at the market stage, and the replay says where"
