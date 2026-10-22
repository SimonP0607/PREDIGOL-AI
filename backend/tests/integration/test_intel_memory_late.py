"""Plan F0, defect 3, on a real database: memory (v2, and so v3) books what a day learns after its row was written.

memory-v1 wrote with ``ON CONFLICT DO NOTHING``: a match that settled, a statistic that arrived, a post-mortem written after
the entity's row for that day existed was thrown away. A row is never rewritten, so memory-v2 books the news in the row of
the day it was learned, under ``delta["late"][<day>]``, and the cumulative state is what a recomputation would give.

The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.intel import cycle, memory
from fbi.people import referees

from .conftest import Seed
from .helpers import scalar

DAY = date(2032, 10, 4)                             # a Bogotá day
KICKOFF = datetime(2032, 10, 4, 18, tzinfo=UTC)     # 13:00 in Bogotá


def _night(day: date) -> datetime:
    """The nightly build of the day after ``day``: 07:50 Bogotá."""
    return datetime(day.year, day.month, day.day, 12, 50, tzinfo=UTC) + timedelta(days=1)


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed, self.n = db, seed, 0

    def match(self, kickoff: datetime, *, result: tuple[int, int] | None = None, referee: str | None = None) -> int:
        self.n += 1
        teams = [scalar(self.db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                        (991000 + 2 * self.n + side, f"Late {self.n}-{side}"))) for side in (0, 1)]
        status = ("FT", "finished") if result else ("NS", "scheduled")
        fid = int(scalar(self.db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
            "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (9910000 + self.n, self.seed.season_id, teams[0], teams[1], kickoff, *status))))
        if result:
            self.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)",
                            (fid, *result))
        if referee:
            self.db.execute("INSERT INTO core.fixture_facts (fixture_id, observed_at, referee, payload_hash, "
                            "normalizer_version) VALUES (%s, %s, %s, %s, 'test')",
                            (fid, kickoff + timedelta(hours=3), referee, self.seed.payload_hash))
        return fid

    def decision(self, fid: int, kickoff: datetime, selection: str, *, market: str = "1X2") -> int:
        return int(scalar(self.db.execute(
            "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, "
            "selection, line, model_name, odds, p_model, p_cal, p_market, filters, state, context_status, input_hash) "
            "VALUES ('decision-v1', %s, 'T-3h', %s, %s, %s, %s, 0, 'dixon_coles', 3.40, 0.30, 0.30, 0.28, '[]', "
            "'INVESTIGACION', 'PENDING', %s) RETURNING id",
            (kickoff - timedelta(hours=3), fid, kickoff, market, selection, f"late-{fid}-{selection}"))))

    def outcome(self, decision: int, status: str, at: datetime) -> None:
        profit = {"win": 2.4, "loss": -1.0}[status]
        self.db.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, "
                        "profit_staked, close_p_fair, close_odds, close_as_of, clv, version, computed_at) "
                        "VALUES (%s, %s, %s, %s, 0, 0.28, 3.30, %s, 0.02, 'outcome-v1', %s)",
                        (decision, at - timedelta(hours=1), status, profit, KICKOFF, at))

    def stats(self, fid: int, side: str, *, yellow: int, red: int, fouls: int, at: datetime) -> None:
        self.db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, yellow_cards, red_cards, "
                        "fouls, payload_hash, fetched_at) VALUES (%s, %s, 'api-football', %s, %s, %s, %s, %s)",
                        (fid, side, yellow, red, fouls, self.seed.payload_hash, at))


def _rows(db: psycopg.Connection[Any], day: date, *, entity_type: str | None = None) -> dict[tuple[str, str, str], Any]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intel.entity_memory WHERE as_of_day = %s AND (%s::text IS NULL OR entity_type = %s)",
                    (day, entity_type, entity_type))
        return {(r["entity_type"], r["entity_id"], r["aspect"]): r for r in cur.fetchall()}


def _recomputed(db: psycopg.Connection[Any], key: memory.EKey, days: list[date]) -> dict[str, Any]:
    """The cumulative state of one key computed from scratch, day by day, from what the data say now."""
    state: dict[str, Any] | None = None
    for day in days:
        deltas, _, _ = memory.day_deltas(db, day)
        if key in deltas:
            state = memory.merge(state, deltas[key])
    assert state is not None
    return state


MARKET: memory.EKey = ("market", "1X2", "decisions")


def test_a_decision_settled_after_its_day_was_written_is_booked_the_next_day(db: psycopg.Connection[Any],
                                                                              seed: Seed) -> None:
    w = World(db, seed)
    early = w.decision(w.match(KICKOFF, result=(1, 0)), KICKOFF, "Home")
    late_fixture = w.match(KICKOFF + timedelta(hours=1), result=(0, 1))
    late = w.decision(late_fixture, KICKOFF + timedelta(hours=1), "Away")
    w.outcome(early, "win", KICKOFF + timedelta(hours=3))

    assert memory.build_memory(db, day=DAY, at=_night(DAY)) >= 4
    written = _rows(db, DAY)[MARKET]
    assert written["stats"]["decisions"] == 1 and written["stats"]["wins"] == 1, "the second decision had no outcome yet"

    # The second one settles after the day was written (a match played late, a result confirmed on the second pass).
    w.outcome(late, "loss", _night(DAY) + timedelta(hours=1))
    nxt = DAY + timedelta(days=1)
    assert memory.build_memory(db, day=nxt, at=_night(nxt)) >= 1

    row = _rows(db, nxt)[MARKET]
    booked = row["delta"]["late"][DAY.isoformat()]
    assert booked["decisions"] == 1 and booked["settled"] == 1 and booked["losses"] == 1
    assert booked["results"] == ["L"] and booked["by_selection"] == {"Away": 1} and "wins" not in booked
    assert row["stats"]["decisions"] == 2 and row["stats"]["wins"] == 1 and row["stats"]["losses"] == 1
    assert row["stats"]["last10"] == ["W", "L"] and row["stats"]["hit_rate"] == 0.5
    assert row["stats"] == _recomputed(db, MARKET, [DAY]), "the cumulative state is what a recomputation gives"
    assert late in row["sources"] and early not in row["sources"], "the row names the decision it learned"

    # No hindsight: the row of the day stays as it was written, and so does its state "as of" that day.
    again = _rows(db, DAY)[MARKET]
    assert again["stats"] == written["stats"] and again["delta"] == written["delta"] and again["id"] == written["id"]

    # The entity that never had a row before gets its first one, with the news booked in it.
    first = _rows(db, nxt, entity_type="team")
    names = {r["entity_name"] for r in first.values()}
    assert {"Late 2-0", "Late 2-1"} <= names, names


def test_reconciling_again_books_nothing_twice(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    first = w.decision(w.match(KICKOFF, result=(1, 0)), KICKOFF, "Home")
    second = w.decision(w.match(KICKOFF, result=(0, 0)), KICKOFF, "Draw")
    w.outcome(first, "win", KICKOFF + timedelta(hours=3))
    memory.build_memory(db, day=DAY, at=_night(DAY))
    w.outcome(second, "loss", _night(DAY) + timedelta(hours=1))
    d1, d2, d3 = (DAY + timedelta(days=n) for n in (1, 2, 3))

    assert memory.build_memory(db, day=d1, at=_night(d1)) >= 1
    assert memory.build_memory(db, day=d1, at=_night(d1)) == 0, "a day's rows are written once"
    before = db.execute("SELECT count(*) FROM intel.entity_memory").fetchone()
    assert memory.build_memory(db, day=d2, at=_night(d2)) == 0, "the news was booked yesterday: nothing is new"
    assert memory.build_memory(db, day=d3, at=_night(d3)) == 0
    assert db.execute("SELECT count(*) FROM intel.entity_memory").fetchone() == before
    assert _rows(db, d2) == {} and _rows(db, d3) == {}


def test_a_day_with_its_own_activity_carries_both(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    nxt = DAY + timedelta(days=1)
    day_one = w.decision(w.match(KICKOFF, result=(1, 0)), KICKOFF, "Home")
    straggler = w.decision(w.match(KICKOFF, result=(2, 2)), KICKOFF, "Draw")
    w.outcome(day_one, "win", KICKOFF + timedelta(hours=3))
    memory.build_memory(db, day=DAY, at=_night(DAY))

    own = w.decision(w.match(KICKOFF + timedelta(days=1), result=(0, 2)), KICKOFF + timedelta(days=1), "Home")
    w.outcome(own, "loss", KICKOFF + timedelta(days=1, hours=3))
    w.outcome(straggler, "win", KICKOFF + timedelta(days=1, hours=1))     # learned on the 5th, about the 4th
    memory.build_memory(db, day=nxt, at=_night(nxt))

    row = _rows(db, nxt)[MARKET]
    assert row["delta"]["decisions"] == 1 and row["delta"]["losses"] == 1, "its own delta is the day's own"
    assert row["delta"]["late"][DAY.isoformat()]["wins"] == 1
    state = row["stats"]
    assert (state["decisions"], state["settled"], state["wins"], state["losses"]) == (3, 3, 2, 1)
    expected = _recomputed(db, MARKET, [DAY, nxt])
    for field in ("decisions", "settled", "wins", "losses", "voids", "profit_flat", "clv_sum", "clv_n", "by_selection",
                  "by_state", "hit_rate", "roi_flat", "clv_mean"):
        assert state[field] == expected[field], field
    assert sorted(state["last10"]) == sorted(expected["last10"])


def test_a_night_the_worker_missed_is_caught_up_as_late_news(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    skipped, last = DAY + timedelta(days=1), DAY + timedelta(days=2)
    a = w.decision(w.match(KICKOFF, result=(1, 0)), KICKOFF, "Home")
    b = w.decision(w.match(KICKOFF + timedelta(days=1), result=(0, 1)), KICKOFF + timedelta(days=1), "Away")
    c = w.decision(w.match(KICKOFF + timedelta(days=2), result=(1, 1)), KICKOFF + timedelta(days=2), "Draw")
    w.outcome(a, "win", KICKOFF + timedelta(hours=3))
    w.outcome(b, "loss", KICKOFF + timedelta(days=1, hours=3))
    w.outcome(c, "win", KICKOFF + timedelta(days=2, hours=3))

    memory.build_memory(db, day=DAY, at=_night(DAY))
    # the night of the 5th never ran; the next one builds the 6th and finds the 5th empty
    memory.build_memory(db, day=last, at=_night(last))

    assert _rows(db, skipped) == {}, "the day that was not built is not written afterwards"
    row = _rows(db, last)[MARKET]
    assert row["delta"]["decisions"] == 1
    assert row["delta"]["late"][skipped.isoformat()]["decisions"] == 1
    assert row["delta"]["late"][skipped.isoformat()]["losses"] == 1
    assert row["stats"]["decisions"] == 3 and row["stats"]["wins"] == 2 and row["stats"]["losses"] == 1
    assert row["stats"]["last10"] == ["W", "W", "L"] or sorted(row["stats"]["last10"]) == ["L", "W", "W"]
    assert row["stats"]["decisions"] == _recomputed(db, MARKET, [DAY, skipped, last])["decisions"]


def test_the_current_memory_continues_the_state_an_older_version_left(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    nxt = DAY + timedelta(days=1)
    first = w.decision(w.match(KICKOFF, result=(1, 0)), KICKOFF, "Home")
    second = w.decision(w.match(KICKOFF, result=(0, 3)), KICKOFF, "Away")
    w.outcome(first, "win", KICKOFF + timedelta(hours=3))

    # What memory-v1 wrote for the day: the same rows, by its version, with the state it had then.
    deltas, names, sources = memory.day_deltas(db, DAY)
    for key, delta in deltas.items():
        db.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, built_at, "
                   "version, stats, delta, sources) VALUES (%s,%s,%s,%s,%s,%s,'memory-v1',%s,%s,%s)",
                   (*key[:2], names.get(key), key[2], DAY, _night(DAY), Jsonb(memory.merge(None, delta)), Jsonb(delta),
                    Jsonb(sources.get(key, []))))
    v1 = _rows(db, DAY)[MARKET]
    assert v1["version"] == "memory-v1"

    w.outcome(second, "loss", _night(DAY) + timedelta(hours=1))
    assert memory.build_memory(db, day=nxt, at=_night(nxt)) >= 1
    row = _rows(db, nxt)[MARKET]
    assert row["version"] == memory.VERSION == "memory-v3"
    assert row["stats"]["decisions"] == 2 and row["stats"]["wins"] == 1 and row["stats"]["losses"] == 1
    assert row["delta"]["late"][DAY.isoformat()]["decisions"] == 1, "what v1 never saw is booked on its row"
    stored = _rows(db, DAY)[MARKET]
    assert stored["version"] == "memory-v1" and stored["stats"] == v1["stats"], "the v1 row is history: untouched"


def test_an_entity_that_already_has_a_row_for_the_day_is_not_written_twice(db: psycopg.Connection[Any],
                                                                            seed: Seed) -> None:
    w = World(db, seed)
    nxt = DAY + timedelta(days=1)
    first = w.decision(w.match(KICKOFF, result=(1, 0)), KICKOFF, "Home")
    w.outcome(first, "win", KICKOFF + timedelta(hours=3))
    memory.build_memory(db, day=DAY, at=_night(DAY))
    second = w.decision(w.match(KICKOFF, result=(0, 3)), KICKOFF, "Away")
    w.outcome(second, "loss", _night(DAY) + timedelta(hours=1))

    # a row of the next day exists already (written by the previous version of the code) for this one entity
    existing = _rows(db, DAY)[MARKET]
    db.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, built_at, "
               "version, stats, delta, sources) VALUES ('market', '1X2', '1X2', 'decisions', %s, %s, 'memory-v1', %s, "
               "'{}', '[]')", (nxt, _night(DAY), Jsonb(existing["stats"])))
    memory.build_memory(db, day=nxt, at=_night(nxt))
    rows = db.execute("SELECT version FROM intel.entity_memory WHERE entity_type = 'market' AND entity_id = '1X2' "
                      "AND as_of_day = %s", (nxt,)).fetchall()
    assert rows == [("memory-v1",)], "one row per entity, aspect and day, whatever the version"

    # ... and the news it could not book that night is booked the following one, while it is still inside the window
    after = DAY + timedelta(days=2)
    assert memory.build_memory(db, day=after, at=_night(after)) >= 1
    row = _rows(db, after)[MARKET]
    assert row["delta"]["late"][DAY.isoformat()]["decisions"] == 1
    assert row["stats"]["decisions"] == 2 and row["stats"]["losses"] == 1


def test_a_statistic_that_arrives_late_reaches_the_referee(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    nxt = DAY + timedelta(days=1)
    fid = w.match(KICKOFF, result=(2, 1), referee="A. Referee")
    referees.build(db, apply=True)  # the identity places the match: the entity is the person (memory-v3), not the string
    person = db.execute("SELECT referee_id FROM core.fixture_referees WHERE fixture_id = %s", (fid,)).fetchone()
    assert person is not None
    key: memory.EKey = ("referee", str(person[0]), "discipline")

    memory.build_memory(db, day=DAY, at=_night(DAY))
    written = _rows(db, DAY)[key]["stats"]
    assert written["matches"] == 1 and written["cards"] == 0 and "cards_per_match" in written

    w.stats(fid, "home", yellow=3, red=1, fouls=12, at=_night(DAY) + timedelta(hours=2))
    w.stats(fid, "away", yellow=2, red=0, fouls=10, at=_night(DAY) + timedelta(hours=2))
    assert memory.build_memory(db, day=nxt, at=_night(nxt)) >= 1

    row = _rows(db, nxt)[key]
    booked = row["delta"]["late"][DAY.isoformat()]
    assert booked == {"cards": 6, "cards_home": 4, "cards_away": 2, "reds": 1, "fouls": 22, "fouls_matches": 1}
    assert row["stats"]["matches"] == 1, "the match is not counted again"
    assert row["stats"]["cards"] == 6 and row["stats"]["cards_per_match"] == 6.0
    assert row["stats"]["fouls_per_match"] == 22.0
    assert row["stats"] == _recomputed(db, key, [DAY])
    assert fid in row["sources"]


def test_the_nightly_step_builds_yesterday_only(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    d = w.decision(w.match(KICKOFF, result=(1, 0)), KICKOFF, "Home")
    w.outcome(d, "win", KICKOFF + timedelta(hours=3))
    counts = cycle.memory_step(db, at=_night(DAY))
    assert list(counts) == [DAY.isoformat()] and counts[DAY.isoformat()] >= 4
    assert cycle.memory_step(db, at=_night(DAY)) == {DAY.isoformat(): 0}
    assert {r["as_of_day"] for r in db.cursor(row_factory=dict_row).execute(
        "SELECT as_of_day FROM intel.entity_memory").fetchall()} == {DAY}


def test_the_cumulative_state_equals_a_recomputation_whenever_the_news_arrives(db: psycopg.Connection[Any],
                                                                              seed: Seed) -> None:
    """Four days of decisions that settle 0 to 3 nights after their day, built night by night: whatever the order in
    which the news arrived, the last row of every entity says what a recomputation from scratch says."""
    import random

    rng = random.Random(20261022)
    w = World(db, seed)
    days = [DAY + timedelta(days=n) for n in range(4)]
    learned: dict[date, list[tuple[int, str]]] = {}
    for day in days:
        kickoff = KICKOFF + (day - DAY)
        for market, selections in (("1X2", ("Home", "Draw", "Away")), ("OU", ("Over", "Under"))):
            for _ in range(2):
                fixture = w.match(kickoff, result=(1, 0))
                decision = w.decision(fixture, kickoff, rng.choice(selections), market=market)
                night = day + timedelta(days=rng.randint(0, 3))
                learned.setdefault(night, []).append((decision, rng.choice(("win", "loss"))))
    for built in [DAY + timedelta(days=n) for n in range(7)]:
        for decision, status in learned.get(built, []):
            w.outcome(decision, status, _night(built) - timedelta(hours=2))
        memory.build_memory(db, day=built, at=_night(built))

    latest: dict[memory.EKey, dict[str, Any]] = {}
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intel.entity_memory ORDER BY as_of_day, id")
        for r in cur.fetchall():
            latest[(r["entity_type"], r["entity_id"], r["aspect"])] = r
    assert len(latest) > 20
    numbers = ("decisions", "settled", "wins", "losses", "voids", "profit_flat", "clv_sum", "clv_n", "by_state",
               "by_selection")
    for key, row in latest.items():
        expected = _recomputed(db, key, days)
        for field in numbers:   # a counter the news never touched is absent from the row: absent means 0
            assert (row["stats"].get(field) or 0) == (expected.get(field) or 0), (key, field, row["stats"], expected)
        assert sorted(row["stats"].get("last10", [])) == sorted(expected.get("last10", [])), key
