"""A reading the live table cannot hold costs its match that reading, never its batch (25 Oct 2026), on a real database.

At 01:00 UTC on 25 Oct 2026, when the clocks changed, the provider sent minutes 59 short: -2 in a second half, -38, -37 and
-44 in first halves, one match per minute. ``core.fixture_live_states`` refuses a negative minute (CHECK
live_state_minute_is_possible), the refused row aborted the batch's transaction, and the fixtures, details, states and
the payload's own index row of all 19 matches followed went with it - four minutes running, 'partial' each time. These
tests replay that shape through the live follow and check what the database holds after each pass. Every test runs in a
transaction that is rolled back."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import psycopg.errors
import pytest

from fbi.ingestion import live_match
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.live_match import MINUTE_MAX, SMALLINT_MAX, LiveMatchState, capture_live_matches
from fbi.providers.api_football.details import iter_fixture_details
from fbi.providers.base import RawResponse
from tests.integration.neutral_world import World, make_world, one
from tests.integration.test_ai_decision_layer import Savepoints
from tests.integration.test_premature_final import (
    BLUES,
    KICKOFF,
    LEAGUE,
    MATCH,
    REDS,
    LogSpy,
    Parsers,
    apply,
    goal,
    reading,
    register,
    stored,
    with_detail,
)

pytestmark = pytest.mark.integration

OTHER = MATCH + 1  # a second match of the same world, in the same batch


@pytest.fixture()
def world(db: psycopg.Connection[Any]) -> World:
    return make_world(db)


class Passes(Parsers):
    """/fixtures?ids= as the live follow asks it: one prepared body per request, each answered at ``moment`` with a
    payload hash of its own."""

    def __init__(self, bodies: list[dict[str, Any]]) -> None:
        self.bodies = bodies
        self.moment = KICKOFF
        self.asked = 0

    async def fetch_fixture_details(self, *, provider_fixture_ids: list[int]) -> Any:
        self.asked += 1
        body = self.bodies.pop(0)
        raw = RawResponse(endpoint="/fixtures", params={}, fetched_at=self.moment, http_status=200,
                          results_count=len(body["response"]), payload_hash=f"pass-{self.asked}", file_path="x",
                          bytes_written=1, body=body)
        return list(iter_fixture_details(body)), raw


def both(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """One answer carrying two matches, as the provider's /fixtures?ids= does."""
    return {"response": [first["response"][0], second["response"][0]], "errors": [], "paging": {"current": 1, "total": 1}}


def known_and_followed(db: psycopg.Connection[Any], world: World) -> tuple[int, int]:
    """Both matches known and not started, in a tracked competition (the follow's own condition); returns our ids."""
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = "
               "(SELECT competition_id FROM core.competition_seasons WHERE id = %s)", (world.league_season,))
    for k, provider_id in enumerate((MATCH, OTHER)):
        apply(db, world, reading("NS", 0, fid=provider_id), digest=f"ns-{k}", minutes_after_kickoff=-30)
    return (one(db, "SELECT id FROM core.fixtures WHERE provider_fixture_id = %s", (MATCH,)),
            one(db, "SELECT id FROM core.fixtures WHERE provider_fixture_id = %s", (OTHER,)))


def states(db: psycopg.Connection[Any], fixture: int) -> list[tuple[Any, ...]]:
    return db.execute("SELECT status_short, elapsed, goals_home, goals_away FROM core.fixture_live_states "
                      "WHERE fixture_id = %s ORDER BY observed_at", (fixture,)).fetchall()


def events(db: psycopg.Connection[Any], fixture: int) -> int:
    return int(one(db, "SELECT count(*) FROM core.fixture_events WHERE fixture_id = %s", (fixture,)))


def run_row(db: psycopg.Connection[Any], run_id: int | None) -> tuple[Any, ...]:
    row = db.execute("SELECT status, errors, notes, last_error FROM raw.ingestion_runs WHERE id = %s",
                     (run_id,)).fetchone()
    assert row is not None
    return row


# -- the day it happened ---------------------------------------------------------------------------------------------


async def test_a_negative_minute_costs_that_match_its_reading_and_not_its_batch(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    mine, other = known_and_followed(db, world)
    provider = Passes([
        both(with_detail(reading("1H", 19, goals=(0, 0))), with_detail(reading("1H", 19, goals=(0, 0), fid=OTHER))),
        # the minute is 59 short, as it came: the true one is 22 (the first match) and 20 (the second, which is fine)
        both(with_detail(reading("1H", -38, goals=(1, 0)), goal(21, BLUES[0], 11)),
             with_detail(reading("1H", 20, goals=(0, 1), fid=OTHER), goal(20, REDS[0], 99))),
        both(with_detail(reading("1H", 22, goals=(1, 0)), goal(21, BLUES[0], 11)),
             with_detail(reading("1H", 21, goals=(0, 1), fid=OTHER))),
    ])
    spy = LogSpy()
    monkeypatch.setattr(live_match, "log", spy)
    conn: Any = Savepoints(db)

    async def follow(minutes_after_kickoff: int) -> live_match.LiveMatchReport:
        provider.moment = KICKOFF + timedelta(minutes=minutes_after_kickoff)
        return await capture_live_matches(conn, provider, at=provider.moment)

    first = await follow(20)
    assert (first.impossible_states, first.batches_failed, first.states_written) == (0, 0, 2)

    glitch = await follow(21)
    assert glitch.impossible_states == 1
    assert (glitch.batches_failed, glitch.errors) == (0, []), "nothing failed: the reading was told apart, not refused"
    assert glitch.states_written == 1 and glitch.detail_fixtures == 1, "the other match of the batch was stored"
    assert states(db, mine) == [("1H", 19, 0, 0)], "the match with the impossible minute stays what it was"
    assert states(db, other) == [("1H", 19, 0, 0), ("1H", 20, 0, 1)], "the other one is on the board as usual"
    assert events(db, mine) == 0, "no goal of a snapshot whose own clock is wrong"
    assert events(db, other) == 1
    status, errors, notes, last_error = run_row(db, glitch.run_id)
    assert (status, errors, last_error) == ("completed", 0, None), "like a premature final: said in the notes, not an error"
    assert "1 impossible reading(s) declined" in notes, "the ledger keeps the evidence, not only the log"
    level, event, fields = next(s for s in spy.said if s[1] == "live_match.impossible_state")
    assert level == "warning"
    assert fields["payload_hash"] == "pass-2"
    assert fields["fixtures"] == [{"provider_fixture_id": MATCH, "status": "1H", "reading": "elapsed -38"}]

    third = await follow(22)  # the provider is right again: the match catches up and nothing was lost for good
    assert (third.impossible_states, third.states_written) == (0, 2)
    assert states(db, mine) == [("1H", 19, 0, 0), ("1H", 22, 1, 0)]
    assert events(db, mine) == 1
    assert [e for e in spy.said if e[1] == "live_match.impossible_state"] == [(level, event, fields)], "said once"


async def test_what_the_minute_cannot_be_is_declined_for_the_score_too(
        db: psycopg.Connection[Any], world: World) -> None:
    """The same for a score below nothing and a minute past the table's 200: any reading the table would refuse."""
    mine, other = known_and_followed(db, world)
    provider = Passes([
        both(with_detail(reading("2H", 201, goals=(1, 0))), with_detail(reading("2H", 60, goals=(-1, 0), fid=OTHER))),
    ])
    provider.moment = KICKOFF + timedelta(minutes=70)
    conn: Any = Savepoints(db)
    report = await capture_live_matches(conn, provider, at=provider.moment)
    assert (report.impossible_states, report.states_written, report.batches_failed) == (2, 0, 0)
    assert states(db, mine) == [] and states(db, other) == []
    assert stored(db) == ("NS", None), "the status the glitch carried was not applied either"


# -- what the check did not foresee --------------------------------------------------------------------------------------


async def test_a_batch_the_database_refuses_costs_only_itself(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fault the check does not foresee - here a refused INSERT made by hand, inside the first batch - rolls back that
    batch to its savepoint, is recorded on the run, and the next batch is stored. Before, it ended the pass."""
    mine, other = known_and_followed(db, world)
    monkeypatch.setattr(live_match, "MAX_IDS", 1)  # one match per request: two batches
    provider = Passes([with_detail(reading("1H", 20, goals=(1, 0)), goal(20, BLUES[0], 11)),
                       with_detail(reading("1H", 20, goals=(0, 1), fid=OTHER), goal(20, REDS[0], 99))])
    provider.moment = KICKOFF + timedelta(minutes=20)
    spy = LogSpy()
    monkeypatch.setattr(live_match, "log", spy)
    real_write_states = live_match.write_states
    refused: list[str] = []

    def write_states(on: Any, readings: Any, *, observed_at: datetime, payload_hash: str) -> int:
        if not refused:
            refused.append(payload_hash)
            on.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, "
                         "payload_hash) VALUES (%s, %s, '1H', -5, %s)", (mine, observed_at, payload_hash))
        return real_write_states(on, readings, observed_at=observed_at, payload_hash=payload_hash)

    monkeypatch.setattr(live_match, "write_states", write_states)
    conn: Any = Savepoints(db)
    report = await capture_live_matches(conn, provider, at=provider.moment)

    assert refused == ["pass-1"], "the refusal happened in the first batch"
    assert (report.requests, report.batches_failed, report.impossible_states) == (2, 1, 0)
    assert len(report.errors) == 1 and report.errors[0].startswith("batch of 1 fixtures not applied: CheckViolation")
    assert "live_state_minute_is_possible" in report.errors[0], "the database's own words are kept"
    assert (report.states_written, report.detail_fixtures) == (1, 1), "the second batch went on"
    assert states(db, mine) == [] and events(db, mine) == 0, "the first batch is back to where it was"
    assert stored(db) == ("NS", None)
    assert states(db, other) == [("1H", 20, 0, 1)] and events(db, other) == 1
    status, errors, notes, last_error = run_row(db, report.run_id)
    assert (status, errors) == ("partial", 1)
    assert "1 batch(es) not applied" in notes
    assert last_error is not None and last_error.startswith("batch of 1 fixtures not applied")
    assert one(db, "SELECT count(*) FROM raw.ingestion_payloads WHERE run_id = %s", (report.run_id,)) == 2, (
        "both payloads are indexed, the refused one too: it can be looked at and replayed")
    level, _event, fields = next(s for s in spy.said if s[1] == "live_match.batch_not_applied")
    assert (level, fields["payload_hash"], fields["fixtures"], fields["error"]) == ("error", "pass-1", 1, "CheckViolation")


# -- the sink and the table ------------------------------------------------------------------------------------------------


def test_the_sink_leaves_out_the_matches_the_caller_declined(db: psycopg.Connection[Any], world: World) -> None:
    apply(db, world, reading("NS", 0), digest="ns", minutes_after_kickoff=-30)  # known, not started
    at = KICKOFF + timedelta(minutes=20)
    register(db, "glitch", at)
    out = apply_fixtures_payload(db, Parsers(), reading("1H", -38, goals=(1, 0)), payload_hash="glitch",  # type: ignore[arg-type]
                                 fetched_at=at, season_ids={LEAGUE: world.league_season}, skip_ids={MATCH})
    assert (out.seen, out.ours, out.fixtures_updated, out.results_written) == (1, 0, 0, 0)
    assert out.premature_ids == frozenset(), "left out by the caller, not a premature final"
    assert stored(db) == ("NS", None)
    register(db, "truth", at + timedelta(minutes=1))
    clean = apply_fixtures_payload(db, Parsers(), reading("1H", 21, goals=(1, 0)), payload_hash="truth",  # type: ignore[arg-type]
                                   fetched_at=at + timedelta(minutes=1), season_ids={LEAGUE: world.league_season})
    assert clean.fixtures_updated == 1
    assert stored(db) == ("1H", None)


def test_the_writer_itself_skips_what_the_table_would_refuse(db: psycopg.Connection[Any], world: World) -> None:
    """Whoever calls ``write_states`` - the follow filters before it, but the writer does not rely on that."""
    apply(db, world, reading("NS", 0), digest="ns", minutes_after_kickoff=-30)
    register(db, "writer", KICKOFF)
    fixture = one(db, "SELECT id FROM core.fixtures WHERE provider_fixture_id = %s", (MATCH,))
    at = KICKOFF + timedelta(minutes=22)
    assert live_match.write_states(db, [LiveMatchState(MATCH, "1H", -38, None, 1, 0)], observed_at=at,
                                   payload_hash="writer") == 0
    assert states(db, fixture) == [], "nothing stored, nothing raised"
    assert live_match.write_states(db, [LiveMatchState(MATCH, "1H", 22, None, 1, 0)], observed_at=at,
                                   payload_hash="writer") == 1
    assert states(db, fixture) == [("1H", 22, 1, 0)]


def table_takes(db: psycopg.Connection[Any], fixture: int, digest: str, at: datetime, reading_: LiveMatchState) -> bool:
    """Does core.fixture_live_states take this reading? Asked of the database itself, in a savepoint."""
    try:
        with db.transaction():
            db.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, extra, "
                       "goals_home, goals_away, payload_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                       (fixture, at, reading_.status_short, reading_.elapsed, reading_.extra, reading_.goals_home,
                        reading_.goals_away, digest))
    except (psycopg.errors.CheckViolation, psycopg.errors.NumericValueOutOfRange):
        return False
    return True


def test_the_limits_of_a_reading_are_the_limits_of_the_table(db: psycopg.Connection[Any], world: World) -> None:
    """``LiveMatchState.impossible`` mirrors the table's own CHECKs and column types (migration 0041). If a later
    migration moves one of them, this fails and says which: the check and the table must move together."""
    apply(db, world, reading("NS", 0), digest="ns", minutes_after_kickoff=-30)
    register(db, "limits", KICKOFF)
    fixture = one(db, "SELECT id FROM core.fixtures WHERE provider_fixture_id = %s", (MATCH,))
    kinds = dict(db.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'core' "
                            "AND table_name = 'fixture_live_states' AND column_name IN "
                            "('elapsed', 'extra', 'goals_home', 'goals_away')").fetchall())
    assert kinds == dict.fromkeys(("elapsed", "extra", "goals_home", "goals_away"), "smallint")
    probes = ([("elapsed", v) for v in (-1, 0, 45, MINUTE_MAX, MINUTE_MAX + 1, SMALLINT_MAX, SMALLINT_MAX + 1)]
              + [("goals_home", v) for v in (-1, 0, 9, SMALLINT_MAX, SMALLINT_MAX + 1)]
              + [("goals_away", v) for v in (-1, 0, 9, SMALLINT_MAX, SMALLINT_MAX + 1)]
              + [("extra", v) for v in (0, 8, SMALLINT_MAX, SMALLINT_MAX + 1)])
    for k, (name, value) in enumerate(probes):
        fields: dict[str, int | None] = {"elapsed": 10, "extra": None, "goals_home": 0, "goals_away": 0, name: value}
        probe = LiveMatchState(MATCH, "1H", fields["elapsed"], fields["extra"], fields["goals_home"],
                               fields["goals_away"])
        assert (probe.impossible() is None) == table_takes(db, fixture, "limits", KICKOFF + timedelta(seconds=k), probe), (
            f"{name} = {value}: the check and the table disagree")
