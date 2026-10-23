"""The referee of a match is a person in the AI packet and the dossier (plan F3, ``packet-v5`` / ``dossier-v3``): his matches are
counted under every spelling the provider used, homonyms are not mixed, the answer is the one the provider had given AS OF the
packet's moment, and a merge and its undo leave the aggregates as they were."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from fbi.ai.packet import PacketBuilder
from fbi.intel import dossier
from fbi.people import officials
from fbi.people import referees as store
from tests.integration.test_referee_identity_store import T0, World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration

AT = T0 + timedelta(days=100)


def settle(w: World, fixture_id: int, *, yellow: tuple[int, int] = (2, 3), fouls: tuple[int, int] = (10, 12), at: datetime | None = None) -> None:
    """The match is over: a result and the statistics, all known a few hours after the kick-off."""
    kickoff = w.one("SELECT kickoff_at FROM core.fixtures WHERE id = %s", fixture_id)
    done = at or kickoff + timedelta(hours=3)
    w.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fixture_id,))
    w.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 1, 0, %s)", (fixture_id, done))
    for side, yc, fo in (("home", yellow[0], fouls[0]), ("away", yellow[1], fouls[1])):
        w.db.execute(
            "INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, shots_on_target, corners, fouls, yellow_cards, "
            "red_cards, offsides, possession_pct, payload_hash, fetched_at) VALUES (%s, %s, 'api-football', 10, 4, 5, %s, %s, 0, 1, 50, %s, %s)",
            (fixture_id, side, fo, yc, w.seed.payload_hash, done))


def played(w: World, country: str, day: int, referee: str | None, referee_country: str | None = None, **stats: Any) -> int:
    fid = w.match(country, day, referee, referee_country)
    settle(w, fid, **stats)
    return fid


def upcoming(w: World, referee: str | None, referee_country: str | None = None, *, day: int = 100) -> int:
    """The match the packet is for: the referee is announced the day before."""
    fid = w.fixture("England", day)
    w.say(fid, referee, referee_country, at=AT - timedelta(hours=20))
    w.db.execute("UPDATE core.fixtures SET status_short = 'NS', status_group = 'scheduled' WHERE id = %s", (fid,))
    return fid


def packet(w: World, fixture_id: int, at: datetime = AT) -> dict[str, Any]:
    built = PacketBuilder(w.db).build(fixture_id, at=at)
    assert built is not None and built.version == "packet-v6"
    return built.content


def michael_and_the_dutchman(w: World) -> dict[str, int]:
    """Michael Oliver in England under two spellings, and a 'M. Oliver' in the Netherlands who is somebody else (a doubt)."""
    return {"full": played(w, "England", 1, "Michael Oliver", "England"), "initial": played(w, "England", 8, "M. Oliver"),
            "dutch": played(w, "Netherlands", 15, "M. Oliver")}


def test_a_referee_is_one_person_under_every_spelling_and_homonyms_are_not_mixed(world: World) -> None:  # noqa: F811
    michael_and_the_dutchman(world)
    store.build(world.db, apply=True)
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)

    content = packet(world, target)
    fixture, ref = content["fixture"], content["dossier"]["referee"]
    assert fixture["referee"] == "Michael Oliver" and isinstance(fixture["referee_id"], int)
    assert fixture["referee_seen_at"] is not None
    assert (ref["id"], ref["identity"], ref["name"]) == (fixture["referee_id"], "id", "Michael Oliver")
    assert ref["matches"] == 2, "the match he refereed as 'Michael Oliver' and the one written 'M. Oliver'; not the Dutch M. Oliver"
    assert ref["with_stats"] == 2 and ref["cards_per_match"] == 5.0 and ref["fouls_per_match"] == 22.0

    # what the string used to say: only the matches whose facts carried exactly 'Michael Oliver'
    with world.db.cursor() as cur:
        cur.execute(dossier.REFEREE_SQL, {"referee": "Michael Oliver", "at": AT, "kickoff": AT + timedelta(days=1), "since": AT - timedelta(days=400)})
        row = cur.fetchone()
    assert row is not None and row[0] == 1


def test_a_match_whose_referee_changed_counts_for_the_one_it_has_now_and_never_for_the_first(world: World) -> None:  # noqa: F811
    changed = world.fixture("England", 20)
    world.say(changed, "Michael Oliver", "England", at=T0 + timedelta(days=19))
    world.say(changed, "Anthony Taylor", "England", at=T0 + timedelta(days=19, hours=6))
    settle(world, changed)
    played(world, "England", 2, "Michael Oliver", "England")
    played(world, "England", 3, "Anthony Taylor", "England")
    store.build(world.db, apply=True)
    oliver = upcoming(world, "Michael Oliver", "England", day=101)
    taylor = upcoming(world, "Anthony Taylor", "England", day=102)
    store.build(world.db, apply=True)

    assert packet(world, oliver)["dossier"]["referee"]["matches"] == 1, "the changed match is Taylor's"
    assert packet(world, taylor)["dossier"]["referee"]["matches"] == 2
    with world.db.cursor() as cur:  # the text reading counted it for both
        for name, expected in (("Michael Oliver", 2), ("Anthony Taylor", 2)):
            cur.execute(dossier.REFEREE_SQL, {"referee": name, "at": AT, "kickoff": AT + timedelta(days=5), "since": AT - timedelta(days=400)})
            row = cur.fetchone()
            assert row is not None and row[0] == expected, name


def test_the_referee_is_the_one_the_provider_had_named_at_the_packets_moment(world: World) -> None:  # noqa: F811
    early = AT - timedelta(days=5)
    late = AT + timedelta(days=2)
    past = world.fixture("England", 30)
    world.say(past, "Michael Oliver", "England", at=T0 + timedelta(days=29))
    world.say(past, "Anthony Taylor", "England", at=late)  # corrected AFTER the packet's moment
    settle(world, past)
    target = world.fixture("England", 100)
    world.say(target, "Michael Oliver", "England", at=early)
    world.say(target, "Craig Pawson", "England", at=late)  # the provider changes the referee of the match itself, later
    world.db.execute("UPDATE core.fixtures SET status_short = 'NS', status_group = 'scheduled' WHERE id = %s", (target,))
    store.build(world.db, apply=True)

    then = packet(world, target, AT)
    assert then["fixture"]["referee"] == "Michael Oliver"
    assert then["fixture"]["referee_seen_at"] == early.isoformat()
    assert then["dossier"]["referee"]["matches"] == 1, "at AT the past match was still Oliver's"

    after = packet(world, target, late + timedelta(hours=1))
    assert after["fixture"]["referee"] == "Craig Pawson" and after["fixture"]["referee_seen_at"] == late.isoformat()

    before_anything = packet(world, target, early - timedelta(hours=1))
    assert before_anything["fixture"]["referee"] is None and before_anything["fixture"]["referee_id"] is None
    assert before_anything["dossier"]["referee"]["matches"] == 0


def test_nobody_is_named_when_the_provider_took_the_referee_off_and_nothing_is_made_up(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")
    world.say(target, None, at=AT - timedelta(hours=1))
    store.build(world.db, apply=True)
    content = packet(world, target)
    assert content["fixture"]["referee"] is None and content["fixture"]["referee_id"] is None
    assert content["fixture"]["referee_seen_at"] == (AT - timedelta(hours=1)).isoformat(), "the observation that took him off"
    assert content["dossier"]["referee"]["name"] is None and content["dossier"]["referee"]["matches"] == 0


def test_a_match_the_identity_has_not_seen_keeps_the_string(world: World) -> None:  # noqa: F811
    played(world, "England", 1, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    target = upcoming(world, "Michael Oliver", "England")  # its facts arrived after the last pass
    assert not officials.referee_as_of(world.db, target, AT).placed

    ref = packet(world, target)["dossier"]["referee"]
    assert (ref["id"], ref["identity"], ref["name"], ref["matches"]) == (None, "text", "Michael Oliver", 1)
    store.build(world.db, apply=True)
    assert officials.referee_as_of(world.db, target, AT).placed
    assert packet(world, target)["dossier"]["referee"]["identity"] == "id"


def test_a_merge_and_its_undo_leave_the_aggregates_as_they_were(world: World) -> None:  # noqa: F811
    ids = michael_and_the_dutchman(world)
    store.build(world.db, apply=True)
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    keep, other = world.referee_of(ids["full"]), world.referee_of(ids["dutch"])
    assert keep is not None and other is not None
    before = packet(world, target)["dossier"]["referee"]
    assert before["matches"] == 2

    event = store.merge(world.db, keep, other, actor="admin:test")
    merged = packet(world, target)["dossier"]["referee"]
    assert merged["matches"] == 3 and merged["id"] == keep, "the Dutch matches are his now"
    assert merged["name"] == before["name"]

    store.undo(world.db, event, actor="admin:test")
    assert packet(world, target)["dossier"]["referee"] == before
    assert packet(world, target)["fixture"]["referee_id"] == keep


def test_the_packet_of_a_referee_is_the_same_whatever_the_order_of_the_passes(world: World) -> None:  # noqa: F811
    """Placing the history in one pass or in two gives the same packet: the identity does not depend on when it was learned."""
    michael_and_the_dutchman(world)
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    once = packet(world, target)
    world.db.execute("DELETE FROM core.referee_events")
    again = packet(world, target)
    assert once == again


def test_the_reader_answers_by_moment(world: World) -> None:  # noqa: F811
    fid = world.fixture("England", 3)
    t1 = world.say(fid, "A. Taylor", at=T0 + timedelta(days=1))
    t2 = world.say(fid, "Anthony Taylor", "England", at=T0 + timedelta(days=2))
    t3 = world.say(fid, None, at=T0 + timedelta(days=3))
    store.build(world.db, apply=True)

    nothing = officials.referee_as_of(world.db, fid, t1 - timedelta(seconds=1))
    assert nothing.placed and nothing.identity is None and nothing.name is None and nothing.seen_at is None
    first = officials.referee_as_of(world.db, fid, t1)
    assert first.identity == "id" and first.spelling == "A. Taylor" and first.seen_at == t1
    assert first.name == "Anthony Taylor", "the name is the person's, the spelling is what the provider wrote"
    second = officials.referee_as_of(world.db, fid, t2 + timedelta(hours=1))
    assert second.identity == "id" and second.spelling == "Anthony Taylor" and second.country == "England"
    assert second.name == "Anthony Taylor" and second.referee_id == first.referee_id and second.seen_at == t2
    off = officials.referee_as_of(world.db, fid, t3)
    assert off.placed and off.identity is None and off.name is None and off.referee_id is None and off.seen_at == t3
    assert officials.referee_as_of(world.db, 999_999_999, t3) == officials.RefereeAsOf(None, None, None, None, None, None, False)


def test_a_change_the_pass_has_not_seen_yet_is_read_from_the_string_not_from_the_person_it_replaced(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")  # said at AT - 20 h
    store.build(world.db, apply=True)
    changed = world.say(target, "Craig Pawson", "England", at=AT - timedelta(hours=1))  # the pass has not run since

    then = packet(world, target)
    assert then["fixture"]["referee"] == "Craig Pawson" and then["fixture"]["referee_id"] is None
    assert then["fixture"]["referee_seen_at"] == changed.isoformat()
    assert then["dossier"]["referee"]["identity"] == "text" and then["dossier"]["referee"]["name"] == "Craig Pawson"

    store.build(world.db, apply=True)
    now = packet(world, target)
    assert now["fixture"]["referee"] == "Craig Pawson" and isinstance(now["fixture"]["referee_id"], int)
    assert now["fixture"]["referee_seen_at"] == changed.isoformat() and now["dossier"]["referee"]["identity"] == "id"


def test_a_referee_taken_off_is_read_before_the_pass_sees_it(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    off = world.say(target, None, at=AT - timedelta(hours=1))

    content = packet(world, target)
    assert content["fixture"]["referee"] is None and content["fixture"]["referee_id"] is None
    assert content["fixture"]["referee_seen_at"] == off.isoformat()
    assert content["dossier"]["referee"]["name"] is None and content["dossier"]["referee"]["matches"] == 0


def test_a_referee_named_again_after_being_taken_off_is_read_before_the_pass_sees_it(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")
    world.say(target, None, at=AT - timedelta(hours=3))  # taken off
    store.build(world.db, apply=True)
    assert packet(world, target)["fixture"]["referee"] is None
    named = world.say(target, "Craig Pawson", "England", at=AT - timedelta(hours=1))  # and somebody named, after the last pass

    content = packet(world, target)
    assert content["fixture"]["referee"] == "Craig Pawson" and content["fixture"]["referee_id"] is None
    assert content["fixture"]["referee_seen_at"] == named.isoformat()


def test_the_string_fallback_keeps_the_columns_as_the_provider_wrote_them(world: World) -> None:  # noqa: F811
    """The text dossier counts the matches whose facts carry the same string, so the fallback must hand it that string and not a
    version put in order ('Brooks' and 'John, England' are what the facts hold for 'Brooks, John, England')."""
    played(world, "England", 1, "Brooks", "John, England")
    target = upcoming(world, "Brooks", "John, England")
    content = packet(world, target)
    assert content["fixture"]["referee"] == "Brooks" and content["fixture"]["referee_id"] is None
    assert content["dossier"]["referee"]["identity"] == "text" and content["dossier"]["referee"]["matches"] == 1


def test_the_same_spelling_written_another_way_is_still_the_person(world: World) -> None:  # noqa: F811
    played(world, "England", 1, "Michael Oliver", "England")
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    world.say(target, "MICHAEL  oliver", "England", at=AT - timedelta(hours=1))  # a new observation, the same name
    assert not store.build(world.db, apply=True).changed, "the pass has nothing to write: the spelling did not change"

    content = packet(world, target)
    assert isinstance(content["fixture"]["referee_id"], int) and content["dossier"]["referee"]["identity"] == "id"
    assert content["dossier"]["referee"]["matches"] == 1
    assert content["fixture"]["referee_seen_at"] == (AT - timedelta(hours=20)).isoformat(), "the observation the person comes from"


def test_the_string_of_a_match_the_identity_has_not_seen_is_read_as_of_the_moment(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Anna Referee")  # said at AT - 20 h
    world.say(target, "Zed Referee", at=AT + timedelta(hours=2))  # said later: the packet of AT cannot know it
    content = packet(world, target)
    assert content["fixture"]["referee"] == "Anna Referee" and content["fixture"]["referee_seen_at"] == (AT - timedelta(hours=20)).isoformat()
    assert packet(world, target, AT + timedelta(hours=3))["fixture"]["referee"] == "Zed Referee"


def test_the_id_reading_goes_through_the_aliases_of_the_referee_and_not_the_whole_history(world: World) -> None:  # noqa: F811
    """The profile is asked once per match of the day: it has to start from the referee's aliases (a handful of rows) and follow
    the alias index of the officials, not walk the results of every match. A few thousand matches are enough for the planner to
    show which way it goes."""
    db = world.db
    db.execute("INSERT INTO core.referees (name, name_key, origin, version) SELECT 'Referee ' || g, 'referee ' || g, 'rules', 'refid-v1' "
               "FROM generate_series(1, 200) g")
    db.execute("INSERT INTO core.referee_aliases (referee_id, name_key, scope, display, basis, placed_by, version) "
               "SELECT id, name_key, 'england', name, 'identity', 'rules', 'refid-v1' FROM core.referees")
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
               "SELECT 800000000 + g, %s, %s, %s, %s::timestamptz + g * interval '1 hour' FROM generate_series(1, 6000) g",
               (world.seasons["England"], world.seed.home_team_id, world.seed.away_team_id, T0))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) "
               "SELECT id, 1, 0, kickoff_at + interval '3 hours' FROM core.fixtures WHERE provider_fixture_id >= 800000000")
    db.execute("INSERT INTO core.fixture_officials (fixture_id, observed_at, alias_id) "
               "SELECT f.id, f.kickoff_at - interval '1 day', a.id FROM core.fixtures f "
               "JOIN (SELECT id, row_number() OVER (ORDER BY id) AS n FROM core.referee_aliases) a ON a.n = 1 + (f.id % 200) "
               "WHERE f.provider_fixture_id >= 800000000")
    for table in ("core.referees", "core.referee_aliases", "core.fixtures", "core.fixture_results", "core.fixture_officials"):
        db.execute(f"ANALYZE {table}")
    first = db.execute("SELECT min(id) FROM core.referees").fetchone()
    assert first is not None
    plan = "\n".join(str(r[0]) for r in db.execute(
        "EXPLAIN " + dossier.REFEREE_BY_ID_SQL,
        {"referee_id": first[0], "at": AT, "kickoff": AT, "since": AT - timedelta(days=400)}).fetchall())
    assert "on referee_aliases a" in plan, plan
    # (by a plain index scan or by a bitmap one over the same index: which of the two the planner prefers depends on how much dead space
    # the tests that ran before left in the table, and both follow the alias index of the officials)
    assert "fixture_officials_alias on fixture_officials o" in plan or "Bitmap Index Scan on fixture_officials_alias" in plan, plan
    assert "Seq Scan on fixture_officials" not in plan and "Seq Scan on fixture_results" not in plan, plan
    assert "Seq Scan on fixtures" not in plan, plan


def test_the_profile_counts_only_what_was_known_at_the_moment_and_inside_the_window(world: World) -> None:  # noqa: F811
    """A match counts for the referee when it kicked off in the 400 days before this one, its result was recorded by the packet's
    moment and the provider had named him by then."""
    inside = played(world, "England", 5, "Michael Oliver", "England")
    played(world, "England", -320, "Michael Oliver", "England")  # 420 days before the target: outside the window
    late_result = world.match("England", 90, "Michael Oliver", "England")
    settle(world, late_result, at=AT + timedelta(hours=1))  # over, but nobody had recorded the result at AT
    late_news = world.fixture("England", 50)
    world.say(late_news, "Michael Oliver", "England", at=AT + timedelta(hours=1))  # the provider named him only after AT
    settle(world, late_news)
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)

    assert inside > 0 and packet(world, target)["dossier"]["referee"]["matches"] == 1
    later = packet(world, target, AT + timedelta(hours=2))["dossier"]["referee"]
    assert later["matches"] == 3, "the result recorded and the referee named after AT are known two hours later"
    assert packet(world, target)["dossier"]["referee"]["matches"] == 1, "and the packet of AT does not change"


def test_a_correction_after_the_moment_does_not_give_the_match_to_the_new_referee_before_it(world: World) -> None:  # noqa: F811
    past = world.fixture("England", 30)
    world.say(past, "Michael Oliver", "England", at=T0 + timedelta(days=29))
    world.say(past, "Anthony Taylor", "England", at=AT + timedelta(days=2))  # corrected after the packet's moment
    settle(world, past)
    played(world, "England", 31, "Anthony Taylor", "England")
    target = upcoming(world, "Anthony Taylor", "England")
    store.build(world.db, apply=True)

    assert packet(world, target)["dossier"]["referee"]["matches"] == 1, "at AT the corrected match was still Oliver's"
    assert packet(world, target, AT + timedelta(days=3))["dossier"]["referee"]["matches"] == 2
