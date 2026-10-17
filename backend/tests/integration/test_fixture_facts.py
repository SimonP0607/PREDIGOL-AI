"""Fields the normalizers used to drop, now kept change-only: the referee, winner flags, half starts, and
each player's position played, offsides, dribbled past and penalties (field coverage audit, 4 Oct 2026)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.api.services import center
from fbi.ingestion.details import apply_fixture_details
from fbi.ingestion.fixture_facts import apply_fixture_facts
from fbi.providers.api_football.details import (
    iter_fixture_details,
    iter_fixture_facts,
    split_referee,
)
from tests.integration.conftest import Seed

T0 = datetime(2026, 9, 15, 17, 0, tzinfo=UTC)
FIRST_HALF = int(datetime(2026, 9, 15, 19, 0, tzinfo=UTC).timestamp())


def payload(db: psycopg.Connection, seed: Seed, h: str, at: datetime) -> None:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, '/fixtures', '{\"ids\": \"1001\"}', %s, 200, %s, 1)", (h, seed.run_id, at, h))


def body(*, referee: str | None, winner: bool | None = None, first: int | None = None,
         players: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "fixture": {"id": 1001, "referee": referee, "periods": {"first": first, "second": None}},
        "teams": {"home": {"id": 33, "winner": winner}, "away": {"id": 40, "winner": None if winner is None
                                                                  else not winner}}}
    if players is not None:
        entry["players"] = [{"team": {"id": 33}, "players": players}]
    return {"response": [entry]}


def test_referee_parsing() -> None:
    assert split_referee("Michael Oliver, England") == ("Michael Oliver", "England")
    assert split_referee("A. Rojas") == ("A. Rojas", None)
    assert split_referee("") == (None, None) and split_referee(None) == (None, None)


def test_facts_are_kept_change_only_and_never_rewritten_by_an_older_payload(db: psycopg.Connection,
                                                                           seed: Seed) -> None:
    for i, h in enumerate(("ff0", "ff1", "ff2", "ff3")):
        payload(db, seed, h, T0 + timedelta(hours=i))

    def apply(b: dict[str, Any], h: str, at: datetime) -> int:
        return apply_fixture_facts(db, iter_fixture_facts(b), payload_hash=h, observed_at=at)

    assert apply(body(referee=None), "ff0", T0) == 0, "a payload that says nothing adds nothing"
    assert apply(body(referee="Michael Oliver, England", first=FIRST_HALF), "ff1", T0 + timedelta(hours=1)) == 1
    assert apply(body(referee="Michael Oliver, England", first=FIRST_HALF), "ff2", T0 + timedelta(hours=2)) == 0
    assert apply(body(referee="Michael Oliver, England", first=FIRST_HALF, winner=True), "ff3",
                 T0 + timedelta(hours=3)) == 1
    assert apply(body(referee="Anthony Taylor, England"), "ff0", T0) == 0, "older than the newest row: ignored"
    rows = db.execute("SELECT referee, referee_country, home_winner, away_winner, first_half_at, payload_hash "
                      "FROM core.fixture_facts WHERE fixture_id = %s ORDER BY observed_at", (seed.fixture_id,)
                      ).fetchall()
    assert rows == [("Michael Oliver", "England", None, None, datetime.fromtimestamp(FIRST_HALF, UTC), "ff1"),
                    ("Michael Oliver", "England", True, False, datetime.fromtimestamp(FIRST_HALF, UTC), "ff3")]
    mc = center.match_center(db, seed.fixture_id).data
    assert mc is not None and mc.facts is not None
    assert (mc.facts.referee, mc.facts.home_winner, mc.facts.payload_hash) == ("Michael Oliver", True, "ff3")


def test_player_extras_reach_the_match_center(db: psycopg.Connection, seed: Seed) -> None:
    payload(db, seed, "fp1", T0)
    stats = {"games": {"minutes": 90, "position": "F", "rating": "7.1"}, "offsides": 2,
             "dribbles": {"attempts": 3, "success": 1, "past": 1},
             "penalty": {"won": 1, "commited": None, "scored": 1, "missed": 0, "saved": None}}
    b = body(referee=None, players=[{"player": {"id": 909, "name": "A. Striker"}, "statistics": [stats]}])
    rep = apply_fixture_details(db, iter_fixture_details(b), payload_hash="fp1", fetched_at=T0)
    assert rep.player_extras == 1
    again = apply_fixture_details(db, iter_fixture_details(b), payload_hash="fp1", fetched_at=T0)
    assert again.player_extras == 0
    mc = center.match_center(db, seed.fixture_id).data
    assert mc is not None and mc.players.data is not None
    line = next(p for p in mc.players.data if p.provider_player_id == 909)
    assert (line.position_played, line.offsides, line.dribbled_past, line.penalties_won, line.penalties_committed) \
        == ("F", 2, 1, 1, None)


def test_the_raw_replay_fills_the_history_beside_live_rows_and_a_second_run_adds_nothing(
        db: psycopg.Connection, seed: Seed) -> None:
    from scripts.backfill_from_raw import Replay, flush

    for i, h in enumerate(("rp0", "rp1", "rp2")):
        payload(db, seed, h, T0 + timedelta(hours=i))
    # the live writer saw the newest payload first (the table was empty when it was deployed)
    assert apply_fixture_facts(db, iter_fixture_facts(body(referee="Michael Oliver, England", winner=True)),
                               payload_hash="rp2", observed_at=T0 + timedelta(hours=2)) == 1
    fixtures = {1001: (seed.fixture_id, 33, 40)}

    def run() -> tuple[int, int]:
        r = Replay(fixtures=fixtures)
        r.feed(0, "rp0", T0, body(referee="Michael Oliver, England"), ())
        r.feed(1, "rp1", T0 + timedelta(hours=1), body(referee="Michael Oliver, England"), ())
        r.feed(2, "rp2", T0 + timedelta(hours=2), body(referee="Michael Oliver, England", winner=True), ())
        return flush(db, r, commit=False)

    assert run() == (1, 0), "the older change is added; the newest one is the live row already"
    assert run() == (0, 0)
    rows = db.execute("SELECT observed_at, home_winner, payload_hash FROM core.fixture_facts WHERE fixture_id = %s "
                      "ORDER BY observed_at", (seed.fixture_id,)).fetchall()
    assert rows == [(T0, None, "rp0"), (T0 + timedelta(hours=2), True, "rp2")]
