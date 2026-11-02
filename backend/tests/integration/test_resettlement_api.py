"""Plan F0, defect 5, what the API says about it: a record settled again shows the result it has now AND the one it had.

The product's screens (the day's picks and parlays, a person's own picks and parlays) carry ``corrections`` - one entry
per time the record was settled again, with the cause as a code (never the trail's own text, which names internal
revisions and whoever ran a manual pass). The owner's views carry the rest: the pick's timeline marks a re-settlement
apart from a change of status, and the match's audit lists the corrections of the result and the records settled again
(a person's own only counted). The world is the one of ``test_resettlement``; the transaction is rolled back."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.api.contracts.records import ResultCorrection
from fbi.api.services import analytics
from fbi.api.services.audit import match_audit
from fbi.api.services.records import daily_board, user_parlays, user_picks
from fbi.parlays.persist import build_parlays
from fbi.picks import resettlement as rs
from fbi.picks.daily import build_daily_sets, product_day
from fbi.userdata import records as userdata

from .conftest import Seed
from .helpers import scalar
from .test_daily_records import AT, World
from .test_resettlement import (
    EPOCH,
    LATER,
    correct,
    daily_parlay,
    payload,
    product_world,
    settle_all,
    user_of,
    user_parlay,
)


def board(w: World, *, owner: bool = False) -> Any:
    return daily_board(w.db, day=product_day(AT), include_shadow=owner, at=LATER).data


def item_of(w: World, name: str, *, owner: bool = False) -> Any:
    [found] = [i for i in board(w, owner=owner).set.items if i.match.fixture_id == w.fixtures[name]]
    return found


def save(db: psycopg.Connection[Any], uid: int, w: World, name: str, odds: str) -> int:
    userdata.save_pick(db, user_id=uid, fixture_id=w.fixtures[name], market_key="1X2", selection="Home",
                       line=Decimal(0), at=AT, user_odds=Decimal(odds))
    return int(scalar(db.execute("SELECT id FROM picks.user_picks WHERE user_id = %s AND fixture_id = %s",
                                 (uid, w.fixtures[name]))))


# ------------------------------------------------------------------------------------------- the day's picks and parlays

def test_the_day_shows_the_result_it_has_and_the_one_it_had(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = product_world(db, seed)  # F1 won, F3 drawn (the home bet lost), the parlay of both lost
    assert item_of(w, "F3").corrections == [] and board(w).daily_parlay.corrections == []

    correct(w, "F3", 1, 0)  # the home win was there all along
    rs.resettle(db, at=LATER, since=EPOCH)

    shown = item_of(w, "F3")
    assert (shown.status, shown.profit_units) == ("WIN", Decimal("1.1000")), "the record shows the result it has now"
    assert shown.corrections == [ResultCorrection(
        at=LATER, leg_no=None, from_status="LOSS", to_status="WIN", from_profit=Decimal("-1.0000"),
        to_profit=Decimal("1.1000"), cause="result_corrected")]
    assert item_of(w, "F1").corrections == [], "a match nobody corrected says nothing"

    parlay = board(w).daily_parlay
    parlay_id = daily_parlay(w)[0]
    leg_no = scalar(db.execute("SELECT leg_no FROM picks.parlay_legs WHERE parlay_id = %s AND fixture_id = %s",
                               (parlay_id, w.fixtures["F3"])))
    assert (parlay.status, parlay.profit_units) == ("WON", Decimal("3.8300"))
    assert [(c.leg_no, c.from_status, c.to_status) for c in parlay.corrections] == [
        (leg_no, "LOSS", "WIN"), (None, "LOST", "WON")], "the leg that moved, then the parlay it decided"
    assert parlay.corrections[-1].from_profit == Decimal("-1.0000") and parlay.corrections[-1].to_profit == Decimal("3.8300")
    assert all(c.cause == "result_corrected" and c.at == LATER for c in parlay.corrections)


def test_the_owners_preview_of_shadow_records_says_it_too(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = product_world(db, seed)
    correct(w, "F3", 1, 0)
    rs.resettle(db, at=LATER, since=EPOCH)
    preview = board(w, owner=True)
    assert preview.evaluation_mode and preview.set is not None
    on_f3 = [i for i in preview.set.items if i.match.fixture_id == w.fixtures["F3"]]
    assert on_f3 and all(i.corrections and i.corrections[0].to_status == i.status for i in on_f3), (
        "each evaluation record on the corrected match carries its own trail")


def test_the_record_does_not_say_who_ran_the_pass_nor_the_trails_own_words(db: psycopg.Connection[Any],
                                                                          seed: Seed) -> None:
    """The trail's reason names internal revisions and, in a manual pass, the person who ran it: that is the
    owner's. What a person reads is the cause as a code."""
    w = product_world(db, seed)
    correct(w, "F3", 1, 0)
    rs.resettle(db, at=LATER, since=EPOCH, note="manual run by simon")
    assert "manual run by simon" in str(scalar(db.execute(
        "SELECT string_agg(reason, ' ') FROM picks.resettlements"))), "(it is in the trail)"
    assert "reason" not in ResultCorrection.model_fields
    text = board(w).model_dump_json() + board(w, owner=True).model_dump_json()
    assert "simon" not in text and "revision" not in text and "manual" not in text
    assert "result_corrected" in text


def test_a_correction_found_by_a_review_or_by_a_status_change_has_its_own_cause(db: psycopg.Connection[Any],
                                                                               seed: Seed) -> None:
    w = World(db, seed)
    uid = user_of(db, "causes@test.local")
    first, second = save(db, uid, w, "F4", "2.00"), save(db, uid, w, "F5", "2.00")
    w.result("F4", 1, 0)
    w.result("F5", 1, 0)
    revision = scalar(db.execute(
        "INSERT INTO core.fixture_result_revisions (fixture_id, kind, old_state, new_state, changed) VALUES "
        "(%s, 'status', '{\"status_short\": \"FT\"}', '{\"status_short\": \"AET\"}', ARRAY['status_short']) "
        "RETURNING id", (w.fixtures["F4"],)))
    for pick, fixture, rev in ((first, "F4", revision), (second, "F5", None)):
        db.execute("INSERT INTO picks.resettlements (at, record_kind, record_key, fixture_id, revision_id, "
                   "from_status, from_profit, to_status, to_profit, rule_version, reason) VALUES "
                   "(%s, 'user_pick', %s, %s, %s, 'WIN', 1.0000, 'LOSS', -1.0000, 'settle-v4', 'seeded')",
                   (LATER, str(pick), w.fixtures[fixture], rev))
    causes = {p.id: [c.cause for c in p.corrections] for p in user_picks(db, user_id=uid, status=None, limit=50).data}
    assert causes == {first: ["status_changed"], second: ["audit"]}


# ------------------------------------------------------------------------------------------ a person's own picks and parlays

def test_a_person_sees_the_corrections_of_their_own_picks_and_only_theirs(db: psycopg.Connection[Any],
                                                                         seed: Seed) -> None:
    w = World(db, seed)
    ana, ben, cai = user_of(db, "ana@test.local"), user_of(db, "ben@test.local"), user_of(db, "cai@test.local")
    anas, bens = save(db, ana, w, "F4", "2.45"), save(db, ben, w, "F4", "1.90")
    save(db, cai, w, "F5", "2.00")  # on another match: nothing to see
    w.result("F4", 1, 0)
    w.result("F5", 1, 0)
    settle_all(w)
    correct(w, "F4", 0, 2)
    rs.resettle(db, at=LATER, since=EPOCH)

    def mine(uid: int) -> dict[int, list[ResultCorrection]]:
        return {p.id: p.corrections for p in user_picks(db, user_id=uid, status=None, limit=50).data}

    [(shown, corrections)] = mine(ana).items()
    assert shown == anas and [(c.from_status, c.to_status, c.from_profit, c.to_profit, c.cause) for c in corrections] == [
        ("WIN", "LOSS", Decimal("1.4500"), Decimal("-1.0000"), "result_corrected")], "the price Ana took"
    [(shown, corrections)] = mine(ben).items()
    assert shown == bens and [(c.from_profit, c.to_profit) for c in corrections] == [
        (Decimal("0.9000"), Decimal("-1.0000"))], "and Ben's own, on the same match, not Ana's"
    assert list(mine(cai).values()) == [[]], "a match that was not corrected: no corrections"
    assert mine(user_of(db, "nobody@test.local")) == {}


def test_a_users_parlay_lists_its_own_and_its_legs_corrections(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.result("F4", 1, 0)
    w.result("F5", 1, 0)
    parlay = user_parlay(w, "plegs@test.local", "WON", "5.0000", [("F4", "2.000", "WIN"), ("F5", "3.000", "WIN")])
    uid = int(scalar(db.execute("SELECT user_id FROM picks.user_parlays WHERE id = %s", (parlay,))))
    assert user_parlays(db, user_id=uid, limit=10).data[0].corrections == []

    correct(w, "F5", 0, 0)
    rs.resettle(db, at=LATER, since=EPOCH)
    [shown] = user_parlays(db, user_id=uid, limit=10).data
    assert (shown.status, shown.profit_units) == ("LOST", Decimal("-1.0000"))
    assert [(c.leg_no, c.from_status, c.to_status, c.from_profit, c.to_profit) for c in shown.corrections] == [
        (2, "WIN", "LOSS", None, None), (None, "WON", "LOST", Decimal("5.0000"), Decimal("-1.0000"))]

    correct(w, "F5", 2, 0)  # and the correction of the correction: the whole story, oldest first
    rs.resettle(db, at=LATER + timedelta(hours=1), since=EPOCH)
    [again] = user_parlays(db, user_id=uid, limit=10).data
    assert [(c.leg_no, c.to_status) for c in again.corrections] == [(2, "LOSS"), (None, "LOST"), (2, "WIN"),
                                                                    (None, "WON")]
    assert again.corrections[2].at == LATER + timedelta(hours=1) and again.corrections[0].at == LATER
    other = user_of(db, "other@test.local")
    assert user_parlays(db, user_id=other, limit=10).data == [], "a parlay is its owner's"


# ---------------------------------------------------------------------------------------------------- the owner's views

def test_the_pick_timeline_marks_a_resettlement_apart_from_a_change_of_status(db: psycopg.Connection[Any],
                                                                             seed: Seed) -> None:
    w = World(db, seed)
    w.result("F1", 2, 0)
    settle_all(w)
    correct(w, "F1", 0, 1)
    rs.resettle(db, at=LATER, since=EPOCH)
    rows = analytics.picks(db, limit=50, offset=0).data.picks.data
    [pick] = [p for p in rows if p.id == w.picks["F1"]]
    kinds = [e.event_kind for e in pick.events]
    assert kinds[-1] == "resettlement" and set(kinds[:-1]) == {"status"}
    assert (pick.events[-1].from_status, pick.events[-1].to_status) == ("settled", "settled")
    assert "win -> loss" in pick.events[-1].reason
    assert (pick.result_status, pick.profit_units) == ("loss", Decimal("-1.0000"))


def test_the_match_audit_lists_the_correction_and_the_records_settled_again(db: psycopg.Connection[Any],
                                                                           seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    build_parlays(db, at=AT)
    uid = user_of(db, "audited@test.local")
    pick = save(db, uid, w, "F3", "2.20")  # saved while the match is still to be played
    w.result("F1", 2, 0)
    w.result("F3", 1, 1)  # a draw: the home bets lost
    fixture = w.fixtures["F3"]
    first, second = payload(db, seed, "first-read"), payload(db, seed, "the-correction")
    db.execute("UPDATE core.fixture_results SET source_payload_hash = %s, source_fetched_at = %s WHERE fixture_id = %s",
               (first, AT, fixture))
    settle_all(w)
    db.execute("UPDATE core.fixture_results SET goals_home = 1, goals_away = 0, source_payload_hash = %s, "
               "source_fetched_at = %s WHERE fixture_id = %s", (second, AT, fixture))
    rs.resettle(db, at=LATER, since=EPOCH)

    audit = match_audit(db, fixture).data
    steps = {s.key: s for s in audit.steps}

    revisions = [i for i in steps["normalized"].items if i.kind == "result_revision"]
    [revision] = revisions
    assert (revision.facts["revision"], revision.facts["regulation_before"], revision.facts["regulation_after"]) == (
        "score", "1-1", "1-0")
    assert revision.facts["changed"] == "goals_away, reg_goals_away", "what moved: the away goal, 1-1 to 1-0"
    assert revision.links == [f"payload:{first}", f"payload:{second}"], "the payload either side of the correction"
    assert "1 correction(s) of the result" in steps["normalized"].detail
    assert [i for i in steps["normalized"].items if i.kind == "result"], "(the result itself is still listed)"
    assert "detail block" not in steps["normalized"].detail, "a correction is not a block of match detail"
    roles = {i.ref: i.facts["roles"] for i in steps["raw"].items}
    assert roles[first] == "result (replaced by a correction)" and "result (a correction)" in str(roles[second]), (
        "the payload a correction replaced is still referenced: it is how the first result can be shown")

    again = [i for i in steps["settlement"].items if i.kind == "resettlement"]
    named = {(i.facts["record"], i.facts["status_before"], i.facts["status_after"]) for i in again
             if i.facts.get("listed") is not False}
    assert {("pick", "loss", "win"), ("daily_item", "LOSS", "WIN"), ("parlay_leg", "LOSS", "WIN"),
            ("parlay", "LOST", "WON")} <= named
    one = next(i for i in again if i.facts["record"] == "pick")
    assert one.links == [f"result_revision:{revision.ref}"] and one.source == "settle-v4" and one.at == LATER
    assert "provider corrected" in str(one.facts["reason"])
    assert len({i.ref for i in again}) == len(again), "(the page keys its rows by kind and ref)"

    counted = [i for i in again if i.facts.get("listed") is False]
    assert [(i.facts["record"], i.facts["records"], i.facts["times"]) for i in counted] == [("user_pick", 1, 1)]
    assert str(pick) not in {str(i.facts.get("key")) for i in again}, "a person's own record is counted, never named"
    assert "audited@test.local" not in audit.model_dump_json()
    assert "settled again after the match was corrected" in steps["settlement"].detail
    assert "(a user's own are counted, not listed)" in steps["settlement"].detail


def test_a_match_nobody_corrected_has_an_audit_as_before(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = product_world(db, seed)
    steps = {s.key: s for s in match_audit(db, w.fixtures["F1"]).data.steps}
    assert not [i for i in steps["normalized"].items if i.kind == "result_revision"]
    assert not [i for i in steps["settlement"].items if i.kind == "resettlement"]
    assert "correction" not in steps["normalized"].detail and "settled again" not in steps["settlement"].detail


def test_a_record_settled_again_twice_is_counted_once_and_its_two_changes_are_both_listed(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    uid = user_of(db, "twice@test.local")
    save(db, uid, w, "F4", "2.00")
    w.result("F4", 1, 0)
    settle_all(w)
    correct(w, "F4", 0, 1)
    rs.resettle(db, at=LATER, since=EPOCH)
    correct(w, "F4", 2, 0)  # corrected back
    rs.resettle(db, at=LATER + timedelta(hours=1), since=EPOCH)

    steps = {s.key: s for s in match_audit(db, w.fixtures["F4"]).data.steps}
    revisions = [i for i in steps["normalized"].items if i.kind == "result_revision"]
    assert [(i.facts["regulation_before"], i.facts["regulation_after"]) for i in revisions] == [
        ("1-0", "0-1"), ("0-1", "2-0")], "oldest first, each from what it was to what it became"
    assert "2 correction(s) of the result" in steps["normalized"].detail
    again = [i for i in steps["settlement"].items if i.kind == "resettlement"]
    [counted] = [i for i in again if i.facts.get("listed") is False]
    assert (counted.facts["record"], counted.facts["records"], counted.facts["times"]) == ("user_pick", 1, 2)
    assert counted.at == LATER + timedelta(hours=1), "the newest of them"
    assert [i.facts["record"] for i in again if i is not counted] == ["pick", "pick"], (
        "the shadow pick on the match, listed once for each of its two changes")
    assert "4 record(s) settled again" in steps["settlement"].detail, "(the detail counts each change)"


def test_a_change_of_the_matchs_status_is_listed_as_what_it_is(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.result("F4", 1, 0)
    db.execute("UPDATE core.fixtures SET status_short = 'AET' WHERE id = %s", (w.fixtures["F4"],))
    steps = {s.key: s for s in match_audit(db, w.fixtures["F4"]).data.steps}
    [revision] = [i for i in steps["normalized"].items if i.kind == "result_revision"]
    assert revision.facts == {"revision": "status", "changed": "status_short", "status_before": "FT",
                              "status_after": "AET"}, "a status is not a score: no goals are quoted"
