"""A final whistle that cannot be true is not stored (plan F0.1, defect 13), on a real database.

On 11 Oct 2026 the provider answered "FT, 90 minutes, 1-1" for Gwangju - Ulsan at 05:03:57, four minutes after its kick-off
(05:00), and one minute earlier had said "1H, minute 3, 0-0". The match ended 4-3. The ingestion wrote the result and the
fast settlement settled 132 picks on it; nothing looked again. These tests replay that sequence through the one place that
applies a /fixtures payload (``apply_fixtures_payload``) and through the live follow that calls it, and check what the database
holds after each answer. Every test runs in a transaction that is rolled back."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ingestion import apply as ingestion_apply
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.live_match import capture_live_matches
from fbi.providers.api_football.details import iter_fixture_details
from fbi.providers.api_football.normalize import iter_fixture_results, iter_fixtures
from fbi.providers.base import RawResponse
from tests.integration.neutral_world import World, make_world, one
from tests.integration.test_ai_decision_layer import Savepoints

pytestmark = pytest.mark.integration

LEAGUE = (98_701, 2025)  # the world's league: the provider's league id and season
BLUES, REDS = (987_101, "Blues"), (987_102, "Reds")
KICKOFF = datetime(2026, 10, 11, 5, 0, tzinfo=UTC)
MATCH = 1_507_081  # Gwangju - Ulsan's id at the provider, which this world borrows for Blues - Reds


@pytest.fixture()
def world(db: psycopg.Connection[Any]) -> World:
    return make_world(db)


class LogSpy:
    """Stands in for the module's logger and keeps what it was told, as (level, event, fields).

    structlog's own ``capture_logs`` depends on the process-wide configuration, which an earlier test of the same run may
    have fixed (a logger that has already been used keeps the processors it first met), so it is not a reliable way to ask
    "was it said?" in a full run. The spy is."""

    def __init__(self) -> None:
        self.said: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        def record(event: str, **fields: Any) -> None:
            self.said.append((level, event, fields))
        return record


class Parsers:
    """The two pure parsing methods of the provider: all ``apply_fixtures_payload`` asks of it. No client, no network."""

    def parse_fixtures(self, body: dict[str, Any]) -> list[Any]:
        return list(iter_fixtures(body))

    def parse_results(self, body: dict[str, Any]) -> list[Any]:
        return list(iter_fixture_results(body))


def _pair(scores: tuple[int | None, int | None]) -> dict[str, int | None]:
    return {"home": scores[0], "away": scores[1]}


def reading(status: str, elapsed: int, *, goals: tuple[int | None, int | None] = (None, None),
            halftime: tuple[int | None, int | None] = (None, None),
            fulltime: tuple[int | None, int | None] = (None, None),
            extratime: tuple[int | None, int | None] = (None, None),
            fid: int = MATCH) -> dict[str, Any]:
    """What /fixtures?ids= answers for the match at one moment, in the provider's own shape."""
    entry = {
        "fixture": {"id": fid, "date": KICKOFF.isoformat(), "status": {"short": status, "elapsed": elapsed},
                    "venue": {}},
        "league": {"id": LEAGUE[0], "season": LEAGUE[1], "round": "Regular Season - 31"},
        "teams": {"home": {"id": BLUES[0], "name": BLUES[1]}, "away": {"id": REDS[0], "name": REDS[1]}},
        "goals": _pair(goals),
        "score": {"halftime": _pair(halftime), "fulltime": _pair(fulltime), "extratime": _pair(extratime),
                  "penalty": _pair((None, None))},
    }
    return {"response": [entry], "errors": [], "paging": {"current": 1, "total": 1}}


def register(db: psycopg.Connection[Any], digest: str, fetched_at: datetime) -> None:
    """The payload as the ledger holds it: a fixture names the payload that wrote it, and that is a foreign key."""
    run = one(db, "INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                  "VALUES ('t', 'premature_final_test', 'completed', now()) RETURNING id")
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
               "results_count, file_path, bytes) VALUES (%s, %s, '/fixtures', '{}'::jsonb, %s, 200, 1, %s, 1) "
               "ON CONFLICT (hash) DO NOTHING", (digest, run, fetched_at, f"test/{digest}.json.gz"))


def apply(db: psycopg.Connection[Any], world: World, body: dict[str, Any], *, digest: str,
          minutes_after_kickoff: float) -> ingestion_apply.PayloadOutcome:
    fetched_at = KICKOFF + timedelta(minutes=minutes_after_kickoff)
    register(db, digest, fetched_at)
    return apply_fixtures_payload(db, Parsers(), body, payload_hash=digest, fetched_at=fetched_at,  # type: ignore[arg-type]
                                  season_ids={LEAGUE: world.league_season})


def stored(db: psycopg.Connection[Any]) -> tuple[str | None, tuple[int, int] | None]:
    """(status, final score) of the match as the database holds them; the score is None while there is no result row."""
    status = db.execute("SELECT status_short FROM core.fixtures WHERE provider_fixture_id = %s", (MATCH,)).fetchone()
    result = db.execute("SELECT r.goals_home, r.goals_away FROM core.fixture_results r JOIN core.fixtures f "
                        "ON f.id = r.fixture_id WHERE f.provider_fixture_id = %s", (MATCH,)).fetchone()
    return (None if status is None else str(status[0])), (None if result is None else (int(result[0]), int(result[1])))


def test_the_day_it_happened_the_glitch_settles_nothing_and_the_truth_still_arrives(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The three answers of 11 Oct 2026, in the order they came (minutes are after the 05:00 kick-off)."""
    apply(db, world, reading("1H", 3, goals=(0, 0), halftime=(0, 0)), digest="05:02", minutes_after_kickoff=3)
    assert stored(db) == ("1H", None)

    spy = LogSpy()
    monkeypatch.setattr(ingestion_apply, "log", spy)
    glitch = apply(db, world, reading("FT", 90, goals=(1, 1), halftime=(0, 1), fulltime=(1, 1)),
                   digest="05:03", minutes_after_kickoff=4)
    assert glitch.premature_finals == 1, "the outcome says the answer was declined"
    assert glitch.premature_ids == {MATCH}
    assert (glitch.fixtures_updated, glitch.results_written, glitch.finished_seen) == (0, 0, 1)
    assert stored(db) == ("1H", None), "no result, no 'finished': nothing for the settlement to start from"
    level, event, fields = next(s for s in spy.said if s[1] == "fixture.premature_final")
    assert level == "warning", "said out loud: a person can find the day the provider contradicted itself"
    assert fields["payload_hash"] == "05:03"
    assert fields["fixtures"] == [{"provider_fixture_id": MATCH, "status": "FT", "minutes_after_kickoff": 4.0}]

    live = apply(db, world, reading("1H", 26, goals=(0, 0), halftime=(0, 0)), digest="05:24",
                 minutes_after_kickoff=24)
    assert live.premature_finals == 0
    assert stored(db) == ("1H", None)

    final = apply(db, world, reading("FT", 90, goals=(4, 3), halftime=(2, 2), fulltime=(4, 3)), digest="07:00",
                  minutes_after_kickoff=120)
    assert final.premature_finals == 0 and final.results_written == 1
    assert stored(db) == ("FT", (4, 3)), "the real final whistle is stored the moment it is real"
    assert [e for e in spy.said if e[1] == "fixture.premature_final"] == [(level, event, fields)], "said once"


def test_a_true_final_is_not_held_back(db: psycopg.Connection[Any], world: World) -> None:
    apply(db, world, reading("FT", 90, goals=(2, 0), halftime=(1, 0), fulltime=(2, 0)), digest="ft",
          minutes_after_kickoff=98)
    assert stored(db) == ("FT", (2, 0))


def test_a_match_that_has_never_been_seen_is_not_created_by_a_premature_final(
        db: psycopg.Connection[Any], world: World) -> None:
    """The first sighting of a match is the glitch: it is declined too, and the next read creates the fixture."""
    out = apply(db, world, reading("FT", 90, goals=(1, 1), halftime=(0, 1), fulltime=(1, 1)), digest="first",
                minutes_after_kickoff=4)
    assert (out.premature_finals, out.fixtures_inserted, out.results_written) == (1, 0, 0)
    assert stored(db) == (None, None)
    again = apply(db, world, reading("1H", 7, goals=(0, 0), halftime=(0, 0)), digest="next", minutes_after_kickoff=6)
    assert again.fixtures_inserted == 1 and stored(db) == ("1H", None)


def test_extra_time_needs_longer_than_ninety_minutes(db: psycopg.Connection[Any], world: World) -> None:
    apply(db, world, reading("2H", 80, goals=(1, 1), halftime=(0, 0)), digest="2h", minutes_after_kickoff=88)
    early = apply(db, world, reading("AET", 120, goals=(2, 1), halftime=(0, 0), fulltime=(1, 1), extratime=(1, 0)),
                  digest="aet-early", minutes_after_kickoff=95)
    assert early.premature_finals == 1 and stored(db) == ("2H", None)
    late = apply(db, world, reading("AET", 120, goals=(2, 1), halftime=(0, 0), fulltime=(1, 1), extratime=(1, 0)),
                 digest="aet-late", minutes_after_kickoff=128)
    assert late.premature_finals == 0 and stored(db) == ("AET", (2, 1))


@pytest.mark.parametrize("status", ["CANC", "PST", "ABD", "AWD", "WO", "SUSP", "INT"])
def test_only_a_finished_code_can_be_too_early(db: psycopg.Connection[Any], world: World, status: str) -> None:
    """A cancellation, a postponement or an abandonment can come the minute after kick-off: those are stored."""
    out = apply(db, world, reading(status, 0), digest=f"early-{status}", minutes_after_kickoff=1)
    assert out.premature_finals == 0 and out.fixtures_inserted == 1
    assert stored(db)[0] == status


def test_one_match_declined_does_not_hold_back_the_others_of_the_same_payload(
        db: psycopg.Connection[Any], world: World) -> None:
    """A /fixtures?ids= answer carries up to 20 matches. The guard declines per match: the glitch of one is not a
    reason to drop the true reading of another."""
    other = 1_507_082
    body = reading("FT", 90, goals=(1, 1), halftime=(0, 1), fulltime=(1, 1))
    second = reading("2H", 70, goals=(2, 0), halftime=(1, 0), fid=other)
    body["response"].append(second["response"][0])
    out = apply(db, world, body, digest="two", minutes_after_kickoff=4)
    assert (out.seen, out.premature_finals, out.fixtures_inserted) == (2, 1, 1)
    assert one(db, "SELECT status_short FROM core.fixtures WHERE provider_fixture_id = %s", (other,)) == "2H"
    assert stored(db) == (None, None)


# -- the live follow: everything it writes from the same answer ----------------------------------------------------------


class Answers(Parsers):
    """/fixtures?ids= as the live follow asks it: one prepared body per call, answered at ``moment`` - the time of the pass."""

    def __init__(self, bodies: list[dict[str, Any]]) -> None:
        self.bodies = bodies
        self.moment = KICKOFF

    async def fetch_fixture_details(self, *, provider_fixture_ids: list[int]) -> Any:
        body = self.bodies.pop(0)
        raw = RawResponse(endpoint="/fixtures", params={}, fetched_at=self.moment, http_status=200, results_count=1,
                          payload_hash=f"follow-{self.moment:%H%M}", file_path="x", bytes_written=1, body=body)
        return list(iter_fixture_details(body)), raw


def with_detail(body: dict[str, Any], *events: dict[str, Any]) -> dict[str, Any]:
    """The four detail blocks the live follow reads from the same answer; only the events carry anything here."""
    body["response"][0].update({"events": list(events), "lineups": [], "statistics": [], "players": []})
    return body


def goal(minute: int, team: int, player: int) -> dict[str, Any]:
    return {"time": {"elapsed": minute, "extra": None}, "team": {"id": team}, "player": {"id": player, "name": f"P{player}"},
            "assist": {"id": None, "name": None}, "type": "Goal", "detail": "Normal Goal", "comments": None}


async def test_the_live_follow_keeps_the_glitch_out_of_every_table_and_says_so(
        db: psycopg.Connection[Any], world: World) -> None:
    """The same four answers as the day it happened, read by the live follow. What the glitch must leave behind: nothing -
    no result, no 'finished' status, no 'FT 90' on the live board, no goal that never happened - and a note in the run."""
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = "
               "(SELECT competition_id FROM core.competition_seasons WHERE id = %s)", (world.league_season,))
    apply(db, world, reading("NS", 0), digest="ns", minutes_after_kickoff=-30)  # known, not started
    fixture = one(db, "SELECT id FROM core.fixtures WHERE provider_fixture_id = %s", (MATCH,))
    answers = Answers([
        with_detail(reading("1H", 3, goals=(0, 0), halftime=(0, 0))),
        with_detail(reading("FT", 90, goals=(1, 1), halftime=(0, 1), fulltime=(1, 1)), goal(38, REDS[0], 99)),
        with_detail(reading("1H", 26, goals=(0, 0), halftime=(0, 0))),
        with_detail(reading("FT", 90, goals=(4, 3), halftime=(2, 2), fulltime=(4, 3)), goal(12, BLUES[0], 11)),
    ])
    conn: Any = Savepoints(db)

    async def follow(minutes_after_kickoff: float) -> Any:
        answers.moment = KICKOFF + timedelta(minutes=minutes_after_kickoff)
        return await capture_live_matches(conn, answers, at=answers.moment)

    def states() -> list[tuple[Any, ...]]:
        return db.execute("SELECT status_short, elapsed, goals_home, goals_away FROM core.fixture_live_states "
                          "WHERE fixture_id = %s ORDER BY observed_at", (fixture,)).fetchall()

    def events() -> int:
        return int(one(db, "SELECT count(*) FROM core.fixture_events WHERE fixture_id = %s", (fixture,)))

    first = await follow(3)
    assert (first.premature_finals, first.ended) == (0, [])
    assert states() == [("1H", 3, 0, 0)]

    glitch = await follow(4)
    assert glitch.premature_finals == 1
    assert glitch.ended == [], "nothing for the fast settlement to start from"
    assert (glitch.fixtures_updated, glitch.results_written, glitch.states_written, glitch.detail_fixtures) == (0, 0, 0, 0)
    assert stored(db) == ("1H", None)
    assert states() == [("1H", 3, 0, 0)], "no 'FT 90 1-1' on the live board"
    assert events() == 0, "no goal of a snapshot the provider has just contradicted"
    notes = one(db, "SELECT notes FROM raw.ingestion_runs WHERE id = %s", (glitch.run_id,))
    assert "1 premature final(s) declined" in notes, "the ledger keeps the evidence, not only the log"

    third = await follow(24)
    assert (third.premature_finals, third.ended) == (0, [])
    assert states()[-1] == ("1H", 26, 0, 0)

    final = await follow(120)
    assert (final.premature_finals, final.ended) == (0, [fixture]), "the real whistle is handed to the settlement"
    assert stored(db) == ("FT", (4, 3))
    assert states() == [("1H", 3, 0, 0), ("1H", 26, 0, 0), ("FT", 90, 4, 3)]
    assert events() == 1
