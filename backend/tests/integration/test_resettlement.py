"""Plan F0, defect 5, second half: what was settled on a result the provider later corrects is settled again - with a trail.

The world is the one of ``test_daily_records`` (seven matches with picks, a day set, parlays, a user's bets), settled
on a first result and then corrected. AT is 2032-08-01 12:00 UTC. The revisions are stamped by the database clock, so
the tests pass ``since`` explicitly; the routine window is tested apart. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.parlays.persist import build_parlays
from fbi.picks import resettlement as rs
from fbi.picks.daily import build_daily_sets, product_day
from fbi.picks.engine import settle_open_picks
from fbi.picks.product_settlement import PARLAY_RULE_VERSION, settle_products
from fbi.userdata import records as userdata

from .conftest import Seed
from .helpers import scalar
from .test_daily_records import AT, World

EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
FIRST = AT + timedelta(hours=14)
"""When the first results are settled: after every match of the day."""
LATER = AT + timedelta(hours=20)
"""When the corrections are re-settled: after the first settlement and the corrections."""


def settle_all(w: World, at: datetime = FIRST) -> None:
    settle_open_picks(w.db, run_id=w.seed.run_id, at=at)
    settle_products(w.db, at=at)


def correct(w: World, name: str, home: int, away: int) -> None:
    """The provider corrects the result of a match (the first read stays in the history of revisions)."""
    w.db.execute("UPDATE core.fixture_results SET goals_home = %s, goals_away = %s WHERE fixture_id = %s",
                 (home, away, w.fixtures[name]))


def pick_result(w: World, name: str) -> tuple[Any, ...]:
    row = w.db.execute("SELECT result_status, profit_units, settled_at, settled_by, settlement_basis, rule_version "
                       "FROM picks.pick_results WHERE pick_id = %s", (w.picks[name],)).fetchone()
    assert row is not None
    return tuple(row)


def trail(w: World, kind: str | None = None) -> list[tuple[Any, ...]]:
    return w.db.execute(
        "SELECT record_kind, record_key, fixture_id, from_status, from_profit, to_status, to_profit, rule_version, "
        "reason, revision_id, at FROM picks.resettlements WHERE (%s::text IS NULL OR record_kind = %s) "
        "ORDER BY id", (kind, kind)).fetchall()


class _Spy:
    """Stands in for the module's logger."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


def product_world(db: psycopg.Connection[Any], seed: Seed) -> World:
    """The day's set and parlays built and F1, F3 settled (F1 won, F3 drawn so the home bet lost), the parlay LOST."""
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    build_parlays(db, at=AT)
    w.result("F1", 2, 0)
    w.result("F3", 1, 1)
    settle_all(w)
    return w


def item(w: World, name: str) -> tuple[Any, ...]:
    row = w.db.execute("SELECT i.status, i.profit_units, i.settled_at FROM picks.daily_set_items i "
                       "JOIN picks.daily_sets s ON s.id = i.set_id WHERE s.source = 'qualified' AND s.day = %s "
                       "AND i.fixture_id = %s", (product_day(AT), w.fixtures[name])).fetchone()
    assert row is not None
    return tuple(row)


def daily_parlay(w: World) -> tuple[int, str, Decimal | None, datetime | None]:
    row = w.db.execute("SELECT id, status, profit_units, settled_at FROM picks.parlays WHERE kind = 'daily' "
                       "AND source = 'qualified' AND day = %s", (product_day(AT),)).fetchone()
    assert row is not None
    return int(row[0]), row[1], row[2], row[3]


# ---------------------------------------------------------------------------------------------------------- picks

def test_a_corrected_score_settles_the_pick_again_and_leaves_the_trail(db: psycopg.Connection[Any],
                                                                      seed: Seed) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    first = pick_result(w, "F1")
    assert first[:2] == ("win", Decimal("1.3000")) and first[5] == "settle-v4"
    events_before = scalar(db.execute("SELECT count(*) FROM picks.pick_events WHERE pick_id = %s", (w.picks["F1"],)))

    correct(w, "F1", 0, 1)  # the goal was disallowed, and the other team scored
    report = rs.resettle(db, at=LATER, since=EPOCH)

    assert report.applied and [(c.kind, c.key, c.from_status, c.to_status) for c in report.changes] == [
        ("pick", str(w.picks["F1"]), "win", "loss")]
    after = pick_result(w, "F1")
    assert after[:2] == ("loss", Decimal("-1.0000"))
    assert after[2] == first[2], "the record keeps the moment it was first settled; the trail has each correction"
    assert after[3:] == ("worker:settle-v4:resettled", "regulation_90", "settle-v4")
    assert db.execute("SELECT status FROM picks.picks WHERE id = %s", (w.picks["F1"],)).fetchone() == ("settled",)

    [(kind, key, fixture, was, was_profit, now, now_profit, version, reason, revision, at)] = trail(w)
    assert (kind, key, fixture) == ("pick", str(w.picks["F1"]), w.fixtures["F1"])
    assert (was, was_profit, now, now_profit, version, at) == ("win", Decimal("1.3000"), "loss",
                                                               Decimal("-1.0000"), "settle-v4", LATER)
    assert "2-0 -> 0-1" in reason and "provider corrected" in reason
    assert revision == scalar(db.execute("SELECT max(id) FROM core.fixture_result_revisions WHERE fixture_id = %s",
                                         (w.fixtures["F1"],)))
    assert db.execute("SELECT from_settled_at FROM picks.resettlements").fetchone() == (first[2],), (
        "(what it had, including when it was settled)")

    events = db.execute("SELECT event_kind, from_status, to_status, at, reason FROM picks.pick_events "
                        "WHERE pick_id = %s ORDER BY id", (w.picks["F1"],)).fetchall()
    assert len(events) == events_before + 1
    assert events[-1][:4] == ("resettlement", "settled", "settled", LATER) and "win -> loss" in events[-1][4]
    assert {e[0] for e in events[:-1]} == {"status"}, "the earlier events are the pick's status changes"


def test_a_second_pass_finds_nothing_and_a_correction_of_the_correction_moves_it_back(db: psycopg.Connection[Any],
                                                                                    seed: Seed) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    assert len(rs.resettle(db, at=LATER, since=EPOCH).changes) == 1
    again = rs.resettle(db, at=LATER + timedelta(minutes=30), since=EPOCH)
    assert again.changes == [] and again.held == [] and again.examined["pick"] == 1, (
        "the record already shows what the result gives: examined, and nothing to do")
    assert len(trail(w)) == 1

    correct(w, "F1", 3, 1)  # corrected back: the first reading was right after all
    back = rs.resettle(db, at=LATER + timedelta(hours=1), since=EPOCH)
    assert [(c.from_status, c.to_status) for c in back.changes] == [("loss", "win")]
    assert pick_result(w, "F1")[:2] == ("win", Decimal("1.3000"))
    rows = trail(w)
    assert [(r[3], r[5]) for r in rows] == [("win", "loss"), ("loss", "win")], "a chain, each row from the last one"
    assert rows[1][8] and "0-1 -> 3-1" in rows[1][8]


def test_a_correction_that_changes_nothing_a_bet_settles_on_is_not_a_resettlement(db: psycopg.Connection[Any],
                                                                                  seed: Seed) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 3, 0)  # 3-0, not 2-0: still a home win
    report = rs.resettle(db, at=LATER, since=EPOCH)
    assert report.fixtures == [w.fixtures["F1"]] and report.changes == [] and report.held == []
    assert trail(w) == [] and pick_result(w, "F1")[:2] == ("win", Decimal("1.3000"))
    assert db.execute("SELECT count(*) FROM picks.pick_events WHERE pick_id = %s AND event_kind = 'resettlement'",
                      (w.picks["F1"],)).fetchone() == (0,)


def test_a_dry_run_says_exactly_what_applying_does_and_writes_nothing(db: psycopg.Connection[Any],
                                                                      seed: Seed) -> None:
    w = product_world(db, seed)
    correct(w, "F3", 1, 0)
    before = (pick_result(w, "F3"), item(w, "F3"), daily_parlay(w))
    dry = rs.resettle(db, at=LATER, since=EPOCH, apply=False)
    assert not dry.applied and dry.changes
    assert (pick_result(w, "F3"), item(w, "F3"), daily_parlay(w)) == before, "nothing was written"
    assert trail(w) == [] and scalar(db.execute("SELECT count(*) FROM picks.pick_events "
                                                "WHERE event_kind = 'resettlement'")) == 0
    done = rs.resettle(db, at=LATER, since=EPOCH)
    assert done.applied and done.changes == dry.changes, "the dry run is the same pass, rolled back"
    assert len(trail(w)) == len(done.changes)
    assert "Nothing was written" in "\n".join(dry.render()) and "Nothing was written" not in "\n".join(done.render())


def test_the_end_to_end_path_through_the_result_repository(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The writers of results are not changed: a newer payload that corrects the score is all it takes."""
    from fbi.ingestion.fixtures import PayloadLineage
    from fbi.ingestion.results import ResultRepository
    from fbi.providers.base import FixtureResultRef

    w = World(db, seed)
    provider_id = scalar(db.execute("SELECT provider_fixture_id FROM core.fixtures WHERE id = %s",
                                    (w.fixtures["F1"],)))
    repo = ResultRepository(db)

    def read(tag: str, home: int, away: int, minutes: int) -> None:
        at = AT + timedelta(hours=2, minutes=minutes)
        db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                   "file_path, bytes) VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1)", (tag, seed.run_id, at, tag))
        repo.apply([FixtureResultRef(provider_id, "FT", home, away)], lineage=PayloadLineage(tag, at))

    read("rs-first", 2, 0, 110)
    settle_all(w)
    assert pick_result(w, "F1")[:2] == ("win", Decimal("1.3000"))
    read("rs-same", 2, 0, 260)  # the re-read at +150 minutes: nothing to correct
    assert rs.resettle(db, at=LATER, since=EPOCH).changes == []
    read("rs-fixed", 1, 1, 1500)  # the re-read at +26 hours: the provider changed its mind
    report = rs.resettle(db, at=LATER, since=EPOCH)
    assert [(c.kind, c.from_status, c.to_status) for c in report.changes] == [("pick", "win", "loss")]
    assert db.execute("SELECT result_payload_hash FROM picks.pick_results WHERE pick_id = %s",
                      (w.picks["F1"],)).fetchone() == ("rs-fixed",), "the result now rests on the payload that corrected it"


# -------------------------------------------------------------------------- the product's records, parlays included

def test_the_picks_of_the_day_its_parlay_and_the_legs_follow_a_correction(db: psycopg.Connection[Any],
                                                                         seed: Seed) -> None:
    w = product_world(db, seed)
    parlay_id, status, profit, parlay_settled = daily_parlay(w)
    assert (status, profit) == ("LOST", Decimal("-1.0000")) and item(w, "F3")[:2] == ("LOSS", Decimal("-1.0000"))
    f3_item_settled = item(w, "F3")[2]

    correct(w, "F3", 1, 0)  # F3's home win was there all along: the parlay (F1 and F3) won
    report = rs.resettle(db, at=LATER, since=EPOCH)

    changes = {(c.kind, c.key): c for c in report.changes}
    set_id = scalar(db.execute("SELECT i.set_id FROM picks.daily_set_items i WHERE i.fixture_id = %s AND i.status "
                               "= 'WIN' AND i.odds = 2.1", (w.fixtures["F3"],)))
    rank = scalar(db.execute("SELECT rank FROM picks.daily_set_items WHERE set_id = %s AND fixture_id = %s",
                             (set_id, w.fixtures["F3"])))
    leg_no = scalar(db.execute("SELECT leg_no FROM picks.parlay_legs WHERE parlay_id = %s AND fixture_id = %s",
                               (parlay_id, w.fixtures["F3"])))
    assert {("pick", str(w.picks["F3"])), ("daily_item", f"{set_id}/{rank}"),
            ("parlay_leg", f"{parlay_id}/{leg_no}"), ("parlay", str(parlay_id))} <= set(changes)
    assert {c.fixture_id for c in report.changes} == {w.fixtures["F3"]}, (
        "the evaluation records (the owner's preview) follow too; every change is about the corrected match")
    for c in report.changes:
        if c.kind == "parlay":
            assert db.execute("SELECT status, profit_units FROM picks.parlays WHERE id = %s",
                              (int(c.key),)).fetchone() == (c.to_status, c.to_profit)
    assert (changes["daily_item", f"{set_id}/{rank}"].from_status, changes["daily_item", f"{set_id}/{rank}"].to_status,
            changes["daily_item", f"{set_id}/{rank}"].to_profit) == ("LOSS", "WIN", Decimal("1.1000"))
    assert item(w, "F3") == ("WIN", Decimal("1.1000"), f3_item_settled), "settled_at stays: first settled then"
    legs = dict(db.execute("SELECT fixture_id, status FROM picks.parlay_legs WHERE parlay_id = %s",
                           (parlay_id,)).fetchall())
    assert legs == {w.fixtures["F1"]: "WIN", w.fixtures["F3"]: "WIN"}
    now = daily_parlay(w)
    assert now[:3] == (parlay_id, "WON", Decimal("3.8300")) and now[3] == parlay_settled
    parlay_change = changes["parlay", str(parlay_id)]
    assert (parlay_change.from_status, parlay_change.from_profit, parlay_change.rule_version) == (
        "LOST", Decimal("-1.0000"), PARLAY_RULE_VERSION)
    assert "leg" in parlay_change.reason and "LOSS -> WIN" in parlay_change.reason
    assert changes["pick", str(w.picks["F3"])].rule_version == "settle-v4"
    assert report.examined["parlay"] >= 1
    assert rs.resettle(db, at=LATER, since=EPOCH).changes == [], "and a second pass has nothing left to do"


def test_a_parlay_a_corrected_leg_no_longer_decides_goes_back_to_active(db: psycopg.Connection[Any],
                                                                       seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    build_parlays(db, at=AT)
    w.result("F1", 0, 1)  # F1 lost: the parlay is lost at once, F3 has not been played
    settle_all(w, AT + timedelta(hours=4))
    parlay_id, status, profit, _ = daily_parlay(w)
    assert (status, profit) == ("LOST", Decimal("-1.0000"))
    assert db.execute("SELECT status FROM picks.parlay_legs WHERE parlay_id = %s AND fixture_id = %s",
                      (parlay_id, w.fixtures["F3"])).fetchone() == ("PENDING",)

    correct(w, "F1", 2, 0)  # the first loss was wrong: with F3 still to play, nothing decides the parlay
    report = rs.resettle(db, at=AT + timedelta(hours=5), since=EPOCH)
    assert daily_parlay(w) == (parlay_id, "ACTIVE", None, None), "un-settled: no result, no profit, not settled"
    [change] = [c for c in report.changes if c.kind == "parlay" and c.key == str(parlay_id)]
    assert (change.from_status, change.from_profit, change.to_status, change.to_profit) == (
        "LOST", Decimal("-1.0000"), "ACTIVE", None)
    assert rs.resettle(db, at=AT + timedelta(hours=6), since=EPOCH).changes == []

    w.result("F3", 1, 1)  # F3 is played and lost: the normal pass settles the parlay again, as it settles any
    settle_all(w, AT + timedelta(hours=9))
    assert daily_parlay(w)[1:3] == ("LOST", Decimal("-1.0000")) and daily_parlay(w)[3] is not None


def test_a_users_picks_and_parlays_are_settled_again_at_the_price_they_took(db: psycopg.Connection[Any],
                                                                           seed: Seed) -> None:
    w = World(db, seed)
    user = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                      "('resettle@test.local', 'Resettle', '$argon2id$x') RETURNING id").fetchone()
    assert user is not None
    uid, f = int(user[0]), w.fixtures
    userdata.save_pick(db, user_id=uid, fixture_id=f["F4"], market_key="1X2", selection="Home", line=Decimal(0),
                       at=AT, user_odds=Decimal("2.45"))
    parlay = userdata.create_parlay(db, user_id=uid, name="Mi combinada", at=AT, legs=[
        userdata.LegIn(f["F4"], "1X2", "Home", Decimal(0)), userdata.LegIn(f["F5"], "1X2", "Home", Decimal(0))])
    w.result("F4", 1, 0)
    w.result("F5", 0, 0)
    settle_all(w)
    assert db.execute("SELECT status FROM picks.user_parlays WHERE id = %s", (parlay["id"],)).fetchone() == ("LOST",)

    correct(w, "F4", 0, 2)  # F4's home win was a mistake
    correct(w, "F5", 3, 1)  # and F5 was won
    report = rs.resettle(db, at=LATER, since=EPOCH)

    got = {(c.kind, c.key): (c.from_status, c.to_status, c.to_profit) for c in report.changes}
    assert got["user_pick", str(scalar(db.execute("SELECT id FROM picks.user_picks WHERE user_id = %s", (uid,))))] == (
        "WIN", "LOSS", Decimal("-1.0000"))
    assert got["user_parlay_leg", f"{parlay['id']}/1"] == ("WIN", "LOSS", None)
    assert got["user_parlay_leg", f"{parlay['id']}/2"] == ("LOSS", "WIN", None)
    assert ("user_parlay", str(parlay["id"])) not in got, "lost before, lost now with the same loss: not a change"
    assert db.execute("SELECT status, profit_units FROM picks.user_parlays WHERE id = %s",
                      (parlay["id"],)).fetchone() == ("LOST", Decimal("-1.0000"))
    other = rs.resettle(db, at=LATER, since=EPOCH, fixture_ids=[f["F4"]])
    assert other.changes == [], "settled twice is settled once"


# --------------------------------------------------------------------------- what is held, and never decided here

def test_a_void_by_rule_stands_when_the_match_later_has_a_result(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    db.execute("UPDATE core.fixtures SET status_short = 'CANC', status_group = 'cancelled' WHERE id = %s",
               (w.fixtures["F1"],))
    settle_all(w, AT + timedelta(hours=3))
    assert pick_result(w, "F1")[:2] == ("void", Decimal("0.0000")) and pick_result(w, "F1")[4] == "not_played"
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
               (w.fixtures["F1"],))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 2, 0)",
               (w.fixtures["F1"],))
    report = rs.resettle(db, at=LATER, fixture_ids=[w.fixtures["F1"]])
    assert report.changes == []
    assert [(h.kind, h.code) for h in report.held] == [("pick", "void_by_rule_stands")]
    assert pick_result(w, "F1")[:2] == ("void", Decimal("0.0000")) and trail(w) == []


@pytest.mark.parametrize(("status", "group", "at_hours", "code"), [
    ("PST", "postponed", 20, "no_longer_settles"),
    ("PST", "postponed", 80, "settles_by_rule_now"),
    ("CANC", "cancelled", 20, "settles_by_rule_now"),
], ids=["postponed", "postponed for more than 72 hours", "cancelled"])
def test_a_settled_pick_on_a_match_that_no_longer_reads_finished_is_held_not_decided(
        db: psycopg.Connection[Any], seed: Seed, status: str, group: str, at_hours: int, code: str) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    db.execute("UPDATE core.fixtures SET status_short = %s, status_group = %s WHERE id = %s",
               (status, group, w.fixtures["F1"]))
    report = rs.resettle(db, at=AT + timedelta(hours=at_hours), since=EPOCH)
    assert report.changes == []
    assert [(h.kind, h.code, h.status) for h in report.held] == [("pick", code, "win")]
    assert pick_result(w, "F1")[:2] == ("win", Decimal("1.3000")), "the money is not rewritten on a status alone"
    assert trail(w) == []
    assert any("HELD pick" in line for line in report.render())


def test_a_match_that_loses_its_regulation_score_is_held(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    db.execute("UPDATE core.fixtures SET status_short = 'AET', status_group = 'finished' WHERE id = %s",
               (w.fixtures["F1"],))
    w.cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, ft_goals_away, "
                  "et_goals_home, et_goals_away) VALUES (%s, 2, 1, 1, 1, 1, 0)", (w.fixtures["F1"],))
    settle_all(w)
    assert pick_result(w, "F1")[:2] == ("loss", Decimal("-1.0000")), "1-1 after 90 minutes: the home bet lost"
    db.execute("UPDATE core.fixture_results SET ft_goals_home = NULL, ft_goals_away = NULL, et_goals_home = NULL, "
               "et_goals_away = NULL WHERE fixture_id = %s", (w.fixtures["F1"],))
    report = rs.resettle(db, at=LATER, since=EPOCH)
    assert report.changes == [] and [h.code for h in report.held] == ["no_longer_settles"]
    assert "regulation result cannot be derived" in report.held[0].detail


# ------------------------------------------------------------------------------------------------ the guards

def test_more_corrections_than_the_guard_allows_are_reported_and_not_written(db: psycopg.Connection[Any],
                                                                            seed: Seed) -> None:
    w = World(db, seed)
    for name in ("F1", "F2", "F3", "F4"):
        w.result(name, 2, 0)
    settle_all(w)
    for name in ("F1", "F2", "F3", "F4"):
        correct(w, name, 0, 1)
    refused = rs.resettle(db, at=LATER, since=EPOCH, max_fixtures=3)
    assert not refused.applied and refused.refused is not None and "4 matches" in refused.refused
    assert len(refused.changes) == 4, "the list is there to be read"
    assert all(pick_result(w, n)[0] == "win" for n in ("F1", "F2", "F3", "F4")) and trail(w) == []
    assert "REFUSED" in refused.summary() and scalar(db.execute(
        "SELECT count(*) FROM picks.pick_events WHERE event_kind = 'resettlement'")) == 0
    allowed = rs.resettle(db, at=LATER, since=EPOCH, max_fixtures=4)
    assert allowed.applied and allowed.refused is None and len(allowed.changes) == 4
    assert all(pick_result(w, n)[0] == "loss" for n in ("F1", "F2", "F3", "F4"))


def test_a_record_another_pass_changed_in_between_is_a_conflict_not_an_overwrite(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    real = rs.settlement.settle
    done: list[bool] = []

    def another_pass_writes_first(*args: Any, **kwargs: Any) -> Any:
        outcome = real(*args, **kwargs)
        if not done:  # the pick is read, evaluated, and only then does somebody else touch its result
            done.append(True)
            db.execute("UPDATE picks.pick_results SET profit_units = profit_units + 0.0001 WHERE pick_id = %s",
                       (w.picks["F1"],))
        return outcome

    monkeypatch.setattr(rs.settlement, "settle", another_pass_writes_first)
    spy = _Spy()
    monkeypatch.setattr(rs, "log", spy)
    report = rs.resettle(db, at=LATER, since=EPOCH)
    assert report.conflicts == 1 and report.changes == []
    assert [(name, fields["conflicts"]) for name, fields in spy.events] == [("resettlement.done", 1)], (
        "a pass that only met a conflict says so in the log")
    assert pick_result(w, "F1")[:2] == ("win", Decimal("1.3001")), "the other writer's value stands"
    assert trail(w) == [] and scalar(db.execute(
        "SELECT count(*) FROM picks.pick_events WHERE event_kind = 'resettlement'")) == 0
    monkeypatch.undo()
    assert [c.kind for c in rs.resettle(db, at=LATER, since=EPOCH).changes] == ["pick"], "and the next pass does it"


def test_two_passes_at_once_the_second_one_waits_its_turn(db: psycopg.Connection[Any], seed: Seed,
                                                          migrated_database: str) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    with psycopg.connect(migrated_database, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(hashtext(%s))", (rs.LOCK,))
        try:
            report = rs.resettle(db, at=LATER, since=EPOCH)
            assert report.busy and not report.applied and report.changes == []
        finally:
            other.execute("SELECT pg_advisory_unlock(hashtext(%s))", (rs.LOCK,))
    assert not rs.resettle(db, at=LATER, since=EPOCH).busy


# ---------------------------------------------------------------------------------- which matches, and the audit

def test_the_routine_pass_looks_at_recent_corrections_and_the_audit_at_everything(db: psycopg.Connection[Any],
                                                                                 seed: Seed) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    w.result("F2", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    correct(w, "F2", 0, 1)
    now = datetime.now(UTC)
    old = db.execute("SELECT id FROM core.fixture_result_revisions WHERE fixture_id = %s", (w.fixtures["F2"],))
    old_id = scalar(old)
    db.execute("SELECT set_config('fbi.history_maintenance', 'on', true)")  # the documented escape, to age one
    db.execute("UPDATE core.fixture_result_revisions SET observed_at = %s WHERE id = %s",
               (now - timedelta(days=8), old_id))
    db.execute("SELECT set_config('fbi.history_maintenance', '', true)")

    assert rs.revised_fixtures(db, since=now - rs.RECHECK_WINDOW) == [w.fixtures["F1"]]
    dry = rs.resettle(db, at=now, apply=False)
    assert dry.fixtures == [w.fixtures["F1"]] and [c.key for c in dry.changes] == [str(w.picks["F1"])], (
        "the default window: F1's correction is days old at most, F2's is eight days old")
    audit = rs.resettle(db, at=now, audit=True, apply=False)
    assert audit.audit and audit.fixtures == [] and {c.key for c in audit.changes} == {
        str(w.picks["F1"]), str(w.picks["F2"])}, "the audit reads every settled record, corrected recently or not"
    explicit = rs.resettle(db, at=now, fixture_ids=[w.fixtures["F2"]], apply=False)
    assert [c.key for c in explicit.changes] == [str(w.picks["F2"])]


def test_a_stored_result_the_current_one_contradicts_is_found_even_with_no_recorded_correction(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    """What was corrected before revision 0080 left no revision: the audit finds the record, says so, and a person
    sees 'audit' where a revision would be."""
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    db.execute("DELETE FROM core.fixture_result_revisions WHERE fixture_id = %s", (w.fixtures["F1"],))
    report = rs.resettle(db, at=LATER, audit=True)
    [change] = report.changes
    assert change.revision_id is None and change.reason.startswith("audit: ") and "predates revision 0080" in change.reason
    assert trail(w)[0][9] is None and pick_result(w, "F1")[:2] == ("loss", Decimal("-1.0000"))


def test_a_parlay_settled_under_the_old_formula_is_found_by_the_audit(db: psycopg.Connection[Any],
                                                                     seed: Seed) -> None:
    """Until parlay-settle-v2 a half win paid at the full odds. The legs here are settled right; the parlay is not."""
    w = World(db, seed)
    user = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                      "('old-formula@test.local', 'Old', '$argon2id$x') RETURNING id").fetchone()
    assert user is not None
    w.result("F4", 0, 0)  # Home +0.25 on a draw: half the stake wins
    w.result("F5", 1, 0)
    parlay = scalar(db.execute(
        "INSERT INTO picks.user_parlays (user_id, created_at, combined_odds, validation, status, profit_units, "
        "settled_at) VALUES (%s, %s, 6.000, '{}', 'WON', 5.0000, %s) RETURNING id", (user[0], AT, FIRST)))
    for n, (fixture, market, selection, line, odds, status) in enumerate((
            ("F4", "AH", "Home", "0.25", "2.000", "HALF_WIN"), ("F5", "1X2", "Home", "0", "3.000", "WIN")), start=1):
        db.execute("INSERT INTO picks.user_parlay_legs (user_parlay_id, leg_no, fixture_id, market_key, selection, "
                   "line, odds, snapshot, status, settled_at) VALUES (%s, %s, %s, %s, %s, %s, %s, '{}', %s, %s)",
                   (parlay, n, w.fixtures[fixture], market, selection, line, odds, status, FIRST))
    routine = rs.resettle(db, at=LATER, since=EPOCH, apply=False)
    assert routine.changes == [], "nothing was corrected: the routine pass has no reason to look"
    elsewhere = rs.resettle(db, at=LATER, fixture_ids=[w.fixtures["F6"]], apply=False)
    assert elsewhere.examined["user_parlay"] == 0 and elsewhere.changes == [], "a pass reads the matches it was given"
    here = rs.resettle(db, at=LATER, fixture_ids=[w.fixtures["F5"]], apply=False)
    assert here.examined["user_parlay"] == 1 and [c.key for c in here.changes] == [str(parlay)], (
        "one leg on the match is enough to decide the whole parlay again")
    audit = rs.resettle(db, at=LATER, audit=True)
    [change] = audit.changes
    assert (change.kind, change.key, change.from_status, change.from_profit, change.to_status, change.to_profit,
            change.rule_version) == ("user_parlay", str(parlay), "WON", Decimal("5.0000"), "PARTIAL_VOID",
                                     Decimal("3.5000"), PARLAY_RULE_VERSION), "(2 + 1) / 2 * 3 - 1 = 3.5, not 2 * 3 - 1"
    assert "audit" in change.reason and PARLAY_RULE_VERSION in change.reason and change.revision_id is None


def test_what_was_built_on_the_old_results_is_counted_not_rewritten(db: psycopg.Connection[Any], seed: Seed,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    assert rs._stale(db, [w.fixtures["F1"]]) == {}, "the real queries run against the schema (and find nothing yet)"
    monkeypatch.setattr(rs, "STALE_SQL", {"core.fixtures (a stand-in)": "SELECT count(*) FROM core.fixtures "
                                                                       "WHERE id = ANY(%s)"})
    nothing = rs.resettle(db, at=LATER, since=EPOCH)
    assert nothing.stale == {}, "no change, no count"
    correct(w, "F1", 0, 1)
    report = rs.resettle(db, at=LATER, since=EPOCH)
    assert report.stale == {"core.fixtures (a stand-in)": 1}
    assert "built on the old results" in "\n".join(report.render())


# ----------------------------------------------------------------------------------- where it runs and how it shows

def test_the_pipeline_pass_settles_a_corrected_result_again_and_a_failure_there_costs_nothing(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.picks import pipeline

    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    now = datetime.now(UTC)  # the revision is stamped by the database clock: the routine window is "the last 7 days"
    report = pipeline.run_pipeline(db, at=now, code_version="test", apply=False)
    assert report.resettlement is not None
    assert [(c.kind, c.from_status, c.to_status) for c in report.resettlement.changes] == [("pick", "win", "loss")]
    assert report.settlement is not None and report.product is not None, "the rest of the pass ran as always"

    # (apply=False rolled the whole pass back, the world included: build it again)
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a defect in the re-settlement")

    monkeypatch.setattr(pipeline, "resettle", broken)
    survived = pipeline.run_pipeline(db, at=now, code_version="test", apply=False)
    assert survived.resettlement is not None and survived.resettlement.changes == []
    assert survived.settlement is not None and survived.daily is not None and survived.product is not None, (
        "a defect in the re-settlement is recorded and does not cost the forecasts, the candidates, the settlement "
        "or the product's records")


# ------------------------------------------------------------------------------------------ the command line

def test_the_command_runs_dry_by_default_and_writes_only_for_a_named_person(db: psycopg.Connection[Any],
                                                                           seed: Seed) -> None:
    from scripts.resettle import resettle_command

    w = World(db, seed)
    for name in ("F1", "F2"):
        w.result(name, 2, 0)
    settle_all(w)
    for name in ("F1", "F2"):
        correct(w, name, 0, 1)

    def run(**kw: Any) -> tuple[int, list[str]]:
        args: dict[str, Any] = {"at": LATER, "audit": False, "fixtures": [], "days": 36500, "apply": False,
                                "by": None, "max_fixtures": 25}
        return resettle_command(db, **(args | kw))

    code, lines = run()
    assert code == 0 and lines[0].startswith("DRY RUN") and lines[-1].startswith("Nothing was written")
    assert trail(w) == [] and pick_result(w, "F1")[0] == "win"
    assert run(apply=True)[0] == 2 and trail(w) == [], "writing is a person's decision: --by NAME"
    assert run(audit=True, fixtures=[1])[0] == 2 and run(audit=True, days=3)[0] == 2
    code, lines = run(apply=True, by="simon", fixtures=[w.fixtures["F1"]])
    assert code == 0 and lines[0].startswith("APPLIED") and len(trail(w)) == 1
    assert trail(w)[0][8].endswith("[manual run by simon]"), "who ran it is in the reason of the row"
    code, lines = run(apply=True, by="simon", max_fixtures=0)
    assert code == 3 and any("REFUSED" in line for line in lines) and len(trail(w)) == 1, "the guard stops the CLI too"


@pytest.fixture()
def committed_world(migrated_database: str, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The command line commits, so its test runs on committed rows and takes them away afterwards: a user's pick, settled
    on a match whose result is then corrected."""
    from fbi.core.config import reset_cache

    monkeypatch.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    ids: dict[str, int] = {}

    def clean(conn: psycopg.Connection[Any]) -> None:
        with conn.transaction():
            conn.execute("DELETE FROM auth.users WHERE email = 'cli-resettle@test.local'")  # cascades its picks
            conn.execute("DELETE FROM core.fixtures WHERE provider_fixture_id = 7349901")  # and the history of it
            conn.execute("DELETE FROM core.teams WHERE provider_team_id IN (979001, 979002)")

    with psycopg.connect(migrated_database, autocommit=True) as conn:
        clean(conn)
        ko = datetime(2026, 10, 1, 18, tzinfo=UTC)
        teams = [scalar(conn.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                     (pid, f"Cli {pid}"))) for pid in (979001, 979002)]
        ids["fixture"] = scalar(conn.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
            "kickoff_at, status_short, status_group) VALUES (7349901, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
            (seed.season_id, teams[0], teams[1], ko)))
        conn.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 1, 0)",
                     (ids["fixture"],))
        ids["user"] = scalar(conn.execute(
            "INSERT INTO auth.users (email, display_name, password_hash) VALUES ('cli-resettle@test.local', 'Cli', "
            "'$argon2id$x') RETURNING id"))
        ids["pick"] = scalar(conn.execute(
            "INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, odds, user_odds, "
            "snapshot, saved_at, status, profit_units, settled_at) VALUES (%s, %s, '1X2', 'Home', 0, 'market', 2.300, "
            "2.450, '{}', %s, 'WIN', 1.4500, %s) RETURNING id",
            (ids["user"], ids["fixture"], ko - timedelta(hours=3), ko + timedelta(hours=3))))
        try:
            yield conn, ids
        finally:
            clean(conn)
            reset_cache()


def test_the_command_line_commits_what_it_was_told_to_and_only_that(
        committed_world: Any, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import resettle as cli

    conn, ids = committed_world
    conn.execute("UPDATE core.fixture_results SET goals_home = 0, goals_away = 2 WHERE fixture_id = %s",
                 (ids["fixture"],))
    base = ["--fixture", str(ids["fixture"])]

    def run(*argv: str) -> tuple[int, str, str]:
        code = cli.main(list(argv))
        out, err = capsys.readouterr()
        return code, out, err

    def state() -> tuple[Any, ...]:
        row = conn.execute("SELECT status, profit_units FROM picks.user_picks WHERE id = %s", (ids["pick"],)).fetchone()
        assert row is not None
        rows = scalar(conn.execute("SELECT count(*) FROM picks.resettlements WHERE record_key = %s "
                                   "AND record_kind = 'user_pick'", (str(ids["pick"]),)))
        return (row[0], row[1], rows)

    code, out, _ = run(*base)
    assert code == 0 and "DRY RUN" in out and "user_pick" in out and state() == ("WIN", Decimal("1.4500"), 0)
    code, _, err = run(*base, "--apply")
    assert code == 2 and "--by NAME" in err and state()[2] == 0
    code, _, err = run(*base, "--apply", "--by", "simon", "--max-fixtures", "0")
    assert code == 3 and "REFUSED" in err and state() == ("WIN", Decimal("1.4500"), 0), "refused: nothing committed"
    code, out, _ = run(*base, "--apply", "--by", "simon")
    assert code == 0 and "APPLIED" in out
    assert state() == ("LOSS", Decimal("-1.0000"), 1), "seen from another connection than the command's: committed"
    code, out, _ = run(*base, "--apply", "--by", "simon")
    assert code == 0 and "re-settled 0 record(s)" in out and state()[2] == 1


def test_a_resettlement_is_not_a_change_of_status_for_the_views_that_read_the_timeline(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    """The pick's record and the started-picks page ask what status a pick had before it was settled: the first event
    that settled it. A correction stamped with an earlier clock (it is the application's, not the database's) must not
    become that answer."""
    from fbi.api.repositories import product as products

    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    assert len(rs.resettle(db, at=long_ago, since=EPOCH).changes) == 1
    record = db.execute("SELECT status, status_before_settlement, result_status, resettlements "
                        "FROM picks.v_pick_record WHERE pick_id = %s", (w.picks["F1"],)).fetchone()
    assert record == ("settled", "qualified", "loss", 1)
    started = [r for r in products.started_picks(db, now=LATER, since=EPOCH, include_shadow=True,
                                                 fixture_id=w.fixtures["F1"]) if r["pick_id"] == w.picks["F1"]]
    assert [(r["pick_status"], r["result_status"], r["profit_units"]) for r in started] == [
        ("qualified", "loss", Decimal("-1.0000"))]
    other = db.execute("SELECT resettlements FROM picks.v_pick_record WHERE pick_id = %s", (w.picks["F3"],)).fetchone()
    assert other == (0,), "the count is the pick's own"


# ----------------------------------------------------------------------- more of what is held, and what is left alone

def test_a_users_void_by_rule_stands_too(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    user = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                      "('void-stands@test.local', 'Void', '$argon2id$x') RETURNING id").fetchone()
    assert user is not None
    userdata.save_pick(db, user_id=int(user[0]), fixture_id=w.fixtures["F4"], market_key="1X2", selection="Home",
                       line=Decimal(0), at=AT, user_odds=Decimal("2.45"))
    db.execute("UPDATE core.fixtures SET status_short = 'CANC', status_group = 'cancelled' WHERE id = %s",
               (w.fixtures["F4"],))
    settle_all(w, AT + timedelta(hours=10))
    read = "SELECT status, profit_units FROM picks.user_picks WHERE user_id = %s"
    assert db.execute(read, (user[0],)).fetchone() == ("VOID", Decimal("0.0000"))
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
               (w.fixtures["F4"],))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 1, 0)",
               (w.fixtures["F4"],))
    report = rs.resettle(db, at=LATER, fixture_ids=[w.fixtures["F4"]])
    held = {(h.kind, h.code) for h in report.held}
    # The world's own shadow pick on F4 went void by the same rule: it is held for the same reason.
    assert report.changes == [] and held == {("pick", "void_by_rule_stands"), ("user_pick", "void_by_rule_stands")}
    assert db.execute(read, (user[0],)).fetchone() == ("VOID", Decimal("0.0000")) and trail(w) == []


def test_a_parlay_still_being_played_is_left_to_the_normal_pass(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Only a SETTLED parlay is decided again here. One still being played follows its legs in the pass that already
    does that - after the legs were settled again, in the same pipeline pass."""
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    build_parlays(db, at=AT)
    w.result("F1", 2, 0)
    settle_all(w, AT + timedelta(hours=4))
    parlay_id = daily_parlay(w)[0]
    assert daily_parlay(w)[1] == "ACTIVE", "one leg won, the other is still to be played"
    correct(w, "F1", 0, 1)
    report = rs.resettle(db, at=AT + timedelta(hours=5), since=EPOCH)
    leg_no = scalar(db.execute("SELECT leg_no FROM picks.parlay_legs WHERE parlay_id = %s AND fixture_id = %s",
                               (parlay_id, w.fixtures["F1"])))
    legs = {(c.kind, c.key) for c in report.changes if c.kind == "parlay_leg"}
    assert ("parlay_leg", f"{parlay_id}/{leg_no}") in legs, "the leg is settled again..."
    assert all(c.kind != "parlay" for c in report.changes), "...a parlay still being played is not decided here"
    assert daily_parlay(w)[1] == "ACTIVE", "the legs say lost now; deciding it is settle_products' job, next"
    settle_products(db, at=AT + timedelta(hours=5))
    assert daily_parlay(w)[1:3] == ("LOST", Decimal("-1.0000"))


def test_a_parlay_whose_profit_cannot_be_known_is_held_never_guessed(db: psycopg.Connection[Any],
                                                                    seed: Seed) -> None:
    w = World(db, seed)
    user = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                      "('unknown-profit@test.local', 'Unknown', '$argon2id$x') RETURNING id").fetchone()
    assert user is not None
    w.result("F4", 0, 0)  # Home -0.25 on a draw: half the stake is lost
    w.result("F5", 1, 0)
    parlay = scalar(db.execute(
        "INSERT INTO picks.user_parlays (user_id, created_at, combined_odds, validation, status, profit_units, "
        "settled_at) VALUES (%s, %s, NULL, '{}', 'PARTIAL_VOID', NULL, %s) RETURNING id", (user[0], AT, FIRST)))
    for n, (fixture, market, selection, line, odds, status) in enumerate((
            ("F4", "AH", "Home", "-0.25", "2.000", "HALF_LOSS"), ("F5", "1X2", "Home", "0", None, "WIN")), start=1):
        db.execute("INSERT INTO picks.user_parlay_legs (user_parlay_id, leg_no, fixture_id, market_key, selection, "
                   "line, odds, snapshot, status, settled_at) VALUES (%s, %s, %s, %s, %s, %s, %s, '{}', %s, %s)",
                   (parlay, n, w.fixtures[fixture], market, selection, line, odds, status, FIRST))
    report = rs.resettle(db, at=LATER, audit=True)
    assert report.changes == [] and [(h.kind, h.key, h.code) for h in report.held] == [
        ("user_parlay", str(parlay), "profit_unknown")]
    assert db.execute("SELECT status, profit_units FROM picks.user_parlays WHERE id = %s",
                      (parlay,)).fetchone() == ("PARTIAL_VOID", None)


# ------------------------------------------------------------------ what the mutation check asked to be pinned down

def payload(db: psycopg.Connection[Any], seed: Seed, tag: str) -> str:
    """A stored payload a result can point at."""
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1)", (tag, seed.run_id, AT, tag))
    return tag


def user_of(db: psycopg.Connection[Any], email: str) -> int:
    row = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES (%s, 'Test', '$argon2id$x') "
                     "RETURNING id", (email,)).fetchone()
    assert row is not None
    return int(row[0])


def user_parlay(w: World, email: str, status: str, profit: str, legs: list[tuple[str, str, str]]) -> int:
    """A user's settled parlay as an older version left it. ``legs``: (match, odds, status) of a home win each."""
    parlay = scalar(w.db.execute(
        "INSERT INTO picks.user_parlays (user_id, created_at, combined_odds, validation, status, profit_units, "
        "settled_at) VALUES (%s, %s, 6.000, '{}', %s, %s, %s) RETURNING id",
        (user_of(w.db, email), AT, status, profit, FIRST)))
    for n, (fixture, odds, leg_status) in enumerate(legs, start=1):
        w.db.execute("INSERT INTO picks.user_parlay_legs (user_parlay_id, leg_no, fixture_id, market_key, selection, "
                     "line, odds, snapshot, status, settled_at) VALUES (%s, %s, %s, '1X2', 'Home', 0, %s, '{}', %s, %s)",
                     (parlay, n, w.fixtures[fixture], odds, leg_status, FIRST))
    return int(parlay)


def test_a_pick_settled_under_an_older_version_is_stamped_with_the_current_one(db: psycopg.Connection[Any],
                                                                              seed: Seed) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    db.execute("UPDATE picks.pick_results SET rule_version = 'settle-v3', settled_by = 'worker:settle-v3' "
               "WHERE pick_id = %s", (w.picks["F1"],))
    correct(w, "F1", 0, 1)
    assert len(rs.resettle(db, at=LATER, since=EPOCH).changes) == 1
    now = pick_result(w, "F1")
    assert now[3] == "worker:settle-v4:resettled" and now[5] == "settle-v4", "the rules that settled it are said"


def test_the_payload_a_pick_was_settled_on_follows_the_correction_and_is_not_lost_without_one(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    first = payload(db, seed, "settled-on-this")
    db.execute("UPDATE picks.pick_results SET result_payload_hash = %s WHERE pick_id = %s", (first, w.picks["F1"]))

    def settled_on() -> Any:
        return scalar(db.execute("SELECT result_payload_hash FROM picks.pick_results WHERE pick_id = %s",
                                 (w.picks["F1"],)))

    correct(w, "F1", 0, 1)  # a correction whose payload was not recorded
    assert len(rs.resettle(db, at=LATER, since=EPOCH).changes) == 1
    assert settled_on() == first, "no payload on the corrected result: the one it was settled on is not forgotten"

    second = payload(db, seed, "the-correction")
    db.execute("UPDATE core.fixture_results SET goals_home = 3, goals_away = 0, source_payload_hash = %s, "
               "source_fetched_at = %s WHERE fixture_id = %s", (second, AT, w.fixtures["F1"]))
    assert len(rs.resettle(db, at=LATER + timedelta(hours=1), since=EPOCH).changes) == 1
    assert settled_on() == second, "and a correction with its own payload is what the pick points at"


def test_a_pick_another_pass_settled_differently_in_between_is_a_conflict_too(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard is the stored result as read - its status as much as its profit."""
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    real = rs.settlement.settle
    done: list[bool] = []

    def another_pass_settles_it_as_a_push(*args: Any, **kwargs: Any) -> Any:
        outcome = real(*args, **kwargs)
        if not done:
            done.append(True)
            db.execute("UPDATE picks.pick_results SET result_status = 'push' WHERE pick_id = %s", (w.picks["F1"],))
        return outcome

    monkeypatch.setattr(rs.settlement, "settle", another_pass_settles_it_as_a_push)
    report = rs.resettle(db, at=LATER, since=EPOCH)
    assert report.conflicts == 1 and report.changes == [] and trail(w) == []
    assert pick_result(w, "F1")[:2] == ("push", Decimal("1.3000")), "only its status moved, and the guard saw it"


def test_a_users_parlay_follows_its_corrected_legs_and_says_which(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.result("F4", 1, 0)
    w.result("F5", 1, 0)
    parlay = user_parlay(w, "legs-say@test.local", "WON", "5.0000", [("F4", "2.000", "WIN"), ("F5", "3.000", "WIN")])
    correct(w, "F5", 0, 0)  # the second leg was a draw after all
    report = rs.resettle(db, at=LATER, since=EPOCH)
    [change] = [c for c in report.changes if c.kind == "user_parlay"]
    assert (change.key, change.from_status, change.to_status, change.to_profit) == (
        str(parlay), "WON", "LOST", Decimal("-1.0000"))
    assert change.reason.startswith("leg 2: WIN -> LOSS - the provider corrected the result")
    assert change.fixture_id == w.fixtures["F5"], "the parlay is about the match that was corrected"
    assert db.execute("SELECT status, profit_units FROM picks.user_parlays WHERE id = %s",
                      (parlay,)).fetchone() == ("LOST", Decimal("-1.0000"))


def test_a_parlay_paid_a_profit_the_rules_do_not_give_is_corrected_with_the_same_status(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.result("F4", 1, 0)
    w.result("F5", 1, 0)
    parlay = user_parlay(w, "profit-only@test.local", "WON", "4.0000", [("F4", "2.000", "WIN"), ("F5", "3.000", "WIN")])
    [change] = rs.resettle(db, at=LATER, audit=True).changes
    assert (change.kind, change.key, change.from_status, change.from_profit, change.to_status, change.to_profit) == (
        "user_parlay", str(parlay), "WON", Decimal("4.0000"), "WON", Decimal("5.0000")), "2 x 3 - 1, not 4"
    assert rs.resettle(db, at=LATER, audit=True).changes == []


def test_a_users_pick_is_settled_again_at_the_price_they_got_not_the_one_shown(db: psycopg.Connection[Any],
                                                                               seed: Seed) -> None:
    w = World(db, seed)
    uid = user_of(db, "own-price@test.local")
    userdata.save_pick(db, user_id=uid, fixture_id=w.fixtures["F4"], market_key="1X2", selection="Home",
                       line=Decimal(0), at=AT, user_odds=Decimal("2.45"))
    w.result("F4", 0, 1)
    settle_all(w)
    correct(w, "F4", 1, 0)
    [change] = [c for c in rs.resettle(db, at=LATER, since=EPOCH).changes if c.kind == "user_pick"]
    assert (change.from_status, change.to_status, change.to_profit) == ("LOSS", "WIN", Decimal("1.4500")), (
        "2.45 less the stake: the price the user took, whatever the board showed")


def test_a_pick_of_the_day_not_settled_yet_is_not_this_modules_to_settle(db: psycopg.Connection[Any],
                                                                         seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    w.result("F1", 2, 0)  # the match has a result, and the settlement of the product's records has not run yet
    correct(w, "F1", 0, 1)
    report = rs.resettle(db, at=LATER, since=EPOCH)
    assert report.examined["daily_item"] == 0 and report.changes == [] and report.held == []
    assert item(w, "F1")[0] == "PENDING", "it waits for the normal settlement, which reads the result as it stands"
    settle_products(db, at=LATER)
    assert item(w, "F1")[:2] == ("LOSS", Decimal("-1.0000"))


def test_the_routine_window_starts_exactly_where_it_says(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    correct(w, "F1", 0, 1)
    start = datetime(2032, 8, 1, 6, tzinfo=UTC)
    db.execute("SELECT set_config('fbi.history_maintenance', 'on', true)")  # the documented escape, to age one
    db.execute("UPDATE core.fixture_result_revisions SET observed_at = %s WHERE fixture_id = %s",
               (start, w.fixtures["F1"]))
    db.execute("SELECT set_config('fbi.history_maintenance', '', true)")
    fixture = w.fixtures["F1"]
    assert rs.revised_fixtures(db, since=start) == [fixture], "a correction observed at the start of the window is in"
    assert rs.revised_fixtures(db, since=start + timedelta(microseconds=1)) == []
    assert rs.resettle(db, at=start + rs.RECHECK_WINDOW, apply=False).fixtures == [fixture]
    assert rs.resettle(db, at=start + rs.RECHECK_WINDOW + timedelta(seconds=1), apply=False).fixtures == []


def test_a_pass_that_found_something_says_so_in_the_log_and_a_quiet_one_does_not(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _Spy()
    monkeypatch.setattr(rs, "log", spy)
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    assert rs.resettle(db, at=LATER, since=EPOCH).changes == [] and spy.events == [], "nothing to say"
    # only held: a cancelled match that now has a result (nothing is changed, a person is told)
    db.execute("UPDATE core.fixtures SET status_short = 'CANC', status_group = 'cancelled' WHERE id = %s",
               (w.fixtures["F2"],))
    settle_all(w, AT + timedelta(hours=3))
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
               (w.fixtures["F2"],))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 1, 0)",
               (w.fixtures["F2"],))
    held = rs.resettle(db, at=LATER, fixture_ids=[w.fixtures["F2"]])
    assert held.changes == [] and held.held
    assert [name for name, _ in spy.events] == ["resettlement.done"] and spy.events[0][1]["held"] == len(held.held)


class _NoCommit:
    """The test's connection with ``commit()`` turned into nothing: the pipeline commits when it is done and the
    fixture rolls everything back instead."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def commit(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def test_the_run_of_the_pipeline_says_what_it_settled_again(db: psycopg.Connection[Any], seed: Seed,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.picks import pipeline

    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    now = datetime.now(UTC)
    conn: Any = _NoCommit(db)
    report = pipeline.run_pipeline(conn, at=now, code_version="test", apply=True)
    assert report.run_id is not None and report.settlement is not None and report.resettlement is not None
    rows_updated, notes, errors = db.execute("SELECT rows_updated, notes, errors FROM raw.ingestion_runs WHERE id = %s",
                                             (report.run_id,)).fetchone() or (None, None, None)
    assert rows_updated == report.settlement.settled + 1, "the record settled again is a row updated by the run"
    assert "re-settled 1 record(s) on 1 match(es)" in notes and errors == 0
    assert pick_result(w, "F1")[:2] == ("loss", Decimal("-1.0000"))

    # a pass the guard stops says so in the run's notes; one that fails is recorded as an error, and costs nothing
    correct(w, "F1", 2, 0)
    monkeypatch.setattr(pipeline, "resettle", lambda c, **kw: rs.resettle(c, max_fixtures=0, **kw))
    refused = pipeline.run_pipeline(conn, at=now, code_version="test", apply=True)
    notes = scalar(db.execute("SELECT notes FROM raw.ingestion_runs WHERE id = %s", (refused.run_id,)))
    assert "REFUSED" in notes and pick_result(w, "F1")[0] == "loss", "nothing was written, and the run says why"

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a defect in the re-settlement")

    monkeypatch.setattr(pipeline, "resettle", broken)
    failed = pipeline.run_pipeline(conn, at=now, code_version="test", apply=True)
    errors, last_error = db.execute("SELECT errors, last_error FROM raw.ingestion_runs WHERE id = %s",
                                    (failed.run_id,)).fetchone() or (None, None)
    assert errors == 1 and last_error.startswith("resettlement: RuntimeError"), "recorded on the run, not hidden"


def test_the_switch_stops_the_routine_pass_and_the_run_says_so(db: psycopg.Connection[Any], seed: Seed,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """FBI_RESETTLE=0 is the owner's way to stop the pass without a deploy. The corrections keep being recorded (the
    database does that); the records are settled again when the pass is back on - or by hand."""
    from fbi.picks import pipeline

    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    conn: Any = _NoCommit(db)

    monkeypatch.setenv("FBI_RESETTLE", "0")
    off = pipeline.run_pipeline(conn, at=datetime.now(UTC), code_version="test", apply=True)
    assert off.resettlement is not None and off.resettlement.changes == []
    notes, errors = db.execute("SELECT notes, errors FROM raw.ingestion_runs WHERE id = %s",
                               (off.run_id,)).fetchone() or (None, None)
    assert "re-settlement OFF (FBI_RESETTLE=0)" in notes and errors == 0, "switched off in the open, not silently"
    assert pick_result(w, "F1")[:2] == ("win", Decimal("1.3000")), "nothing was settled again"
    assert scalar(db.execute("SELECT count(*) FROM core.fixture_result_revisions WHERE fixture_id = %s",
                             (w.fixtures["F1"],))) == 1, "but the correction itself was recorded"

    monkeypatch.setenv("FBI_RESETTLE", "1")
    on = pipeline.run_pipeline(conn, at=datetime.now(UTC), code_version="test", apply=True)
    notes = scalar(db.execute("SELECT notes FROM raw.ingestion_runs WHERE id = %s", (on.run_id,)))
    assert "OFF" not in notes and "re-settled 1 record(s)" in notes
    assert pick_result(w, "F1")[:2] == ("loss", Decimal("-1.0000")), "back on: the correction is settled"


@pytest.mark.parametrize(("value", "enabled"), [("0", False), ("off", False), (" False ", False), ("no", False),
                                                ("1", True), ("on", True), ("", True)])
def test_what_the_switch_reads_as_off(monkeypatch: pytest.MonkeyPatch, value: str, enabled: bool) -> None:
    from fbi.picks import pipeline

    monkeypatch.setenv("FBI_RESETTLE", value)
    assert pipeline.resettle_enabled() is enabled
