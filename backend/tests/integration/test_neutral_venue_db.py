"""The neutral-venue verdicts and their switch on a real database (plan F0, defect 1).

A small world built by hand: a league whose four clubs each play six home matches at their own ground, a cup with a final
at a ground that is nobody's, two national sides meeting in a third country and in one of theirs. The verdicts are decided
from the database by ``fbi.catalog.neutral_store`` (the facts are SQL, the decision is ``fbi.catalog.neutral``), stored,
and read by the models only through the switch - which is off until a person promotes a rule whose before/after backtest
came out justified on the very verdicts that are stored. The transaction is rolled back after every test."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.catalog import neutral_store as ns
from fbi.catalog.neutral import RULE_VERSION
from tests.integration.neutral_world import (
    EXPECTED,
    NOW,
    World,
    justified_run,
    make_world,
    neutral_ids,
    one,
    read,
    verdicts,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def world(db: psycopg.Connection[Any]) -> World:
    return make_world(db)


# ----------------------------------------------------------------------------------------------------------- the verdicts


def test_the_verdicts_are_decided_from_what_the_database_holds(db: psycopg.Connection[Any], world: World) -> None:
    counts = ns.classify_everything(db, at=NOW)
    assert counts.seen == len(EXPECTED) and counts.written == len(EXPECTED) and counts.neutral == 3
    got = verdicts(db)
    assert got == {world.ids[name]: want for name, want in EXPECTED.items()}
    evidence = db.execute("SELECT evidence FROM core.fixture_venue_class WHERE fixture_id = %s",
                          (world.ids["final"],)).fetchone()
    assert evidence is not None
    final = evidence[0]
    assert final["round_kind"] == "final" and final["legs"] == 1
    assert final["home"]["presence"] == final["away"]["presence"] == "elsewhere"
    assert final["home"]["matches_read"] == 6, "the six league home matches of the club, read before the final"
    third = db.execute("SELECT evidence FROM core.fixture_venue_class WHERE fixture_id = %s",
                       (world.ids["third"],)).fetchone()
    assert third is not None
    assert third[0]["ground"]["country"] == "Chile"
    assert (third[0]["home_country"], third[0]["away_country"]) == ("Brazil", "Argentina")


def test_a_league_match_has_no_verdict(db: psycopg.Connection[Any], world: World,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    ns.classify_everything(db, at=NOW)
    assert world.ids["league_match"] not in verdicts(db)

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the reference (every venue, every league ground) is loaded to decide nothing")

    monkeypatch.setattr(ns, "load_reference", refuse)  # the ingestion asks about league payloads all day
    skipped = ns.classify_fixtures(db, [world.ids["league_match"]], at=NOW)
    assert (skipped.seen, skipped.written) == (0, 0), "never neutral by rule: not even a row to say so"


def test_a_verdict_is_written_once_and_rewritten_only_when_its_facts_change(db: psycopg.Connection[Any],
                                                                            world: World) -> None:
    ns.classify_everything(db, at=NOW)
    again = ns.classify_fixtures(db, list(world.ids.values()), at=NOW + timedelta(hours=1))
    assert again.seen == len(EXPECTED) and again.written == 0, "nothing new: no row is touched"
    stamp = one(db, "SELECT max(classified_at) FROM core.fixture_venue_class")
    assert stamp == NOW, "and the time of the decision is the time it was made, not the time it was repeated"
    # the payload now names a ground that is the home side's own: the verdict is rewritten
    db.execute("UPDATE core.fixtures SET venue_name = 'Blues Park', venue_city = 'London' WHERE id = %s",
               (world.ids["r16_arena"],))
    changed = ns.classify_fixtures(db, [world.ids["r16_arena"]], at=NOW + timedelta(hours=2))
    assert changed.written == 1
    assert verdicts(db)[world.ids["r16_arena"]] == (False, "home_ground")
    assert one(db, "SELECT classified_at FROM core.fixture_venue_class WHERE fixture_id = %s",
               (world.ids["r16_arena"],)) == NOW + timedelta(hours=2)


def test_deciding_one_fixture_at_a_time_gives_the_verdicts_of_deciding_them_together(db: psycopg.Connection[Any],
                                                                                   world: World) -> None:
    ns.classify_everything(db, at=NOW)
    together = db.execute("SELECT fixture_id, neutral, basis, evidence FROM core.fixture_venue_class "
                          "ORDER BY fixture_id").fetchall()
    db.execute("DELETE FROM core.fixture_venue_class")
    for fid in world.ids.values():
        ns.classify_fixtures(db, [fid], at=NOW)
    apart = db.execute("SELECT fixture_id, neutral, basis, evidence FROM core.fixture_venue_class "
                       "ORDER BY fixture_id").fetchall()
    assert apart == together, "a verdict never depends on which other fixtures are decided in the same pass"


def test_the_backfill_picks_up_only_what_has_no_verdict_and_can_decide_everything_again(db: psycopg.Connection[Any],
                                                                                         world: World) -> None:
    first = ns.classify_everything(db, since=NOW - timedelta(days=45), at=NOW)
    assert first.seen == 4, "final, ahead, third and host: the ones from 45 days ago on"
    assert len(ns.unclassified_ids(db)) == 3
    rest = ns.classify_everything(db, at=NOW)
    assert rest.seen == 3 and not ns.unclassified_ids(db)
    everything = ns.classify_everything(db, only_missing=False, at=NOW)
    assert (everything.seen, everything.written) == (7, 0), "all of them again: the same verdicts, nothing rewritten"


def test_a_verdict_belongs_to_the_rule_that_made_it(db: psycopg.Connection[Any], world: World) -> None:
    ns.classify_everything(db, at=NOW)
    db.execute("INSERT INTO core.fixture_venue_class (fixture_id, rule_version, neutral, basis) "
               "VALUES (%s, 'neutral-v2', false, 'no_evidence')", (world.ids["final"],))
    assert verdicts(db, "neutral-v2") == {world.ids["final"]: (False, "no_evidence")}
    assert verdicts(db)[world.ids["final"]] == (True, "decider_ground"), "the other rule's verdict is untouched"
    assert ns.unclassified_ids(db) == [], "neutral-v1 has decided all of them"
    assert set(ns.unclassified_ids(db, rule_version="neutral-v2")) == {world.ids[n] for n in EXPECTED} - {
        world.ids["final"]}, "and neutral-v2 has decided only the final: a verdict is missing per rule"
    assert read(db, neutral_rule=RULE_VERSION)[world.ids["final"]] is True
    assert read(db, neutral_rule="neutral-v2")[world.ids["final"]] is False


# ------------------------------------------------------------------------------------------- what the models read


def test_the_models_read_no_verdict_until_a_rule_is_promoted(db: psycopg.Connection[Any], world: World) -> None:
    before = read(db)
    assert not any(before.values()), "nothing ever wrote the flag: every match is a home match"
    ns.classify_everything(db, at=NOW)
    assert ns.rule_in_force(db) is None
    assert read(db) == before, "verdicts stored, switch off: the models read exactly what they read before"
    assert read(db, neutral_rule=None) == before
    ours = {fid for fid, flag in read(db, neutral_rule=RULE_VERSION).items() if flag}
    assert ours == neutral_ids(world), "a backtest asks for the rule by name and gets its verdicts"


def test_the_flag_of_the_fixture_and_of_its_competition_are_still_read(db: psycopg.Connection[Any],
                                                                      world: World) -> None:
    db.execute("UPDATE core.fixtures SET is_neutral = true WHERE id = %s", (world.ids["quarter_home"],))
    db.execute("UPDATE core.competitions SET neutral_venue = true WHERE id = (SELECT competition_id "
               "FROM core.competition_seasons WHERE id = %s)", (world.intl_season,))
    flags = read(db)
    assert flags[world.ids["quarter_home"]] is True
    assert flags[world.ids["third"]] is True and flags[world.ids["host"]] is True, "a competition played at neutral grounds"
    assert flags[world.ids["final"]] is False


def test_only_a_justified_run_can_be_promoted(db: psycopg.Connection[Any], world: World) -> None:
    ns.classify_everything(db, at=NOW)
    for verdict in ("inconclusive", "not_justified"):
        run = justified_run(db, verdict=verdict)
        with pytest.raises(PermissionError, match=f"says '{verdict}'"):
            ns.promote(db, run.id, by="owner", reason="a perfectly good reason to try")
    assert ns.promoted(db) is None and ns.history(db) == []
    with pytest.raises(LookupError, match="no backtest run"):
        ns.promote(db, 999_999, by="owner", reason="a perfectly good reason to try")
    with pytest.raises(ValueError, match="a verdict is one of"):
        ns.record_run(db, rule_version=RULE_VERSION, protocol="x", verdict="maybe", labels={}, params={}, result={})


def test_promoting_switches_the_models_on_and_retiring_switches_them_off_again(db: psycopg.Connection[Any],
                                                                            world: World) -> None:
    ns.classify_everything(db, at=NOW)
    run = justified_run(db)
    first = ns.promote(db, run.id, by="owner", reason="the backtest justified the rule: better, nowhere worse",
                       who="simon", at=NOW)
    assert first.changed and first.promotion.previous_id is None and first.promotion.evidence["who"] == "simon"
    assert first.promotion.evidence["run"] == run.id and first.promotion.evidence["labels"] == run.labels
    assert ns.rule_in_force(db) == RULE_VERSION
    on = {fid for fid, flag in read(db).items() if flag}
    assert on == neutral_ids(world), "the default read is now the promoted rule's"

    again = ns.promote(db, run.id, by="owner", reason="the same run, a second time")
    assert not again.changed and len(ns.history(db)) == 1, "promoting what is in force writes nothing"

    off = ns.retire(db, by="owner", reason="a model got worse in production: back to the old reading", who="simon",
                    at=NOW + timedelta(days=3))
    assert off.promotion.previous_id == first.promotion.id and off.promotion.rule_version is None
    assert ns.rule_in_force(db) is None and not any(read(db).values()), "the models read what they read before"
    assert len(verdicts(db)) == len(EXPECTED), "the verdicts stay stored"
    with pytest.raises(PermissionError, match="nothing to retire"):
        ns.retire(db, by="owner", reason="there is nothing in force any more")

    back = ns.promote(db, run.id, by="owner", reason="the first retirement was a mistake: it is back")
    assert back.changed and back.promotion.previous_id == off.promotion.id
    assert [p.action for p in ns.history(db)] == ["promote", "retire", "promote"], "newest first; nothing was rewritten"
    assert {fid for fid, flag in read(db).items() if flag} == neutral_ids(world)


def test_a_run_goes_stale_when_the_verdicts_it_is_about_change(db: psycopg.Connection[Any], world: World) -> None:
    ns.classify_everything(db, at=NOW)
    run = justified_run(db)
    # a venue named later: the final is now played at the home side's own ground, so one verdict turns non-neutral
    db.execute("UPDATE core.fixtures SET venue_name = 'Blues Park', venue_city = 'London' WHERE id = %s",
               (world.ids["final"],))
    ns.classify_fixtures(db, [world.ids["final"]], at=NOW + timedelta(hours=1))
    with pytest.raises(PermissionError, match="verdicts changed since"):
        ns.promote(db, run.id, by="owner", reason="a perfectly good reason to try")
    assert ns.promoted(db) is None
    fresh = justified_run(db)
    assert ns.promote(db, fresh.id, by="owner", reason="the backtest was run again on the new verdicts").changed


def test_verdicts_of_matches_after_the_run_do_not_invalidate_it(db: psycopg.Connection[Any], world: World) -> None:
    """The ingestion keeps deciding new fixtures all day; a run is about the labels up to its own cut-off."""
    cutoff = NOW - timedelta(days=1)
    ns.classify_everything(db, until=cutoff + timedelta(microseconds=1), at=NOW)
    run = justified_run(db, through=cutoff)
    ns.classify_everything(db, at=NOW + timedelta(hours=1))  # the match still to play is decided afterwards
    assert world.ids["ahead"] in verdicts(db)
    assert ns.promote(db, run.id, by="owner", reason="the later verdicts are not what the run measured").changed
    assert ns.label_state(db, through=cutoff) == run.labels
    assert ns.label_state(db)["neutral"] == 3 and run.labels["neutral"] == 2


def test_a_reason_must_say_something_and_is_kept_without_its_padding(db: psycopg.Connection[Any],
                                                                     world: World) -> None:
    ns.classify_everything(db, at=NOW)
    run = justified_run(db)
    least = ns.MIN_REASON
    assert ns.check_reason("owner", "x" * least) == "x" * least, "exactly the minimum is enough"
    for short in ("x" * (least - 1), "   " + "x" * (least - 1) + "  \n"):
        with pytest.raises(ValueError, match=f"at least {least} characters"):
            ns.check_reason("owner", short)  # and padding is not words
    promotion = ns.promote(db, run.id, by="owner", reason="   " + "y" * least + "  \n")
    assert promotion.promotion.reason == "y" * least, "what is kept is what was said"


def test_a_decision_needs_a_reason_and_a_known_decider(db: psycopg.Connection[Any], world: World) -> None:
    ns.classify_everything(db, at=NOW)
    run = justified_run(db)
    with pytest.raises(ValueError, match="at least 10 characters"):
        ns.promote(db, run.id, by="owner", reason="because")
    with pytest.raises(ValueError, match="promoted_by"):
        ns.promote(db, run.id, by="research_v2", reason="a perfectly good reason to try")
    assert ns.promoted(db) is None


# ------------------------------------------------------------------------------------- what the database refuses


def refused(db: psycopg.Connection[Any], sql: str, params: tuple[Any, ...], error: type[Exception]) -> None:
    with pytest.raises(error), db.transaction():
        db.execute(sql, params)


def test_the_tables_refuse_malformed_rows(db: psycopg.Connection[Any], world: World) -> None:
    check = psycopg.errors.CheckViolation
    ok = world.ids["final"]
    base = "INSERT INTO core.fixture_venue_class (fixture_id, rule_version, neutral, basis, evidence) VALUES (%s,%s,%s,%s,%s)"
    refused(db, base, (ok, "  ", True, "third_country", "{}"), check)
    refused(db, base, (ok, "neutral-v1", True, "", "{}"), check)
    refused(db, base, (ok, "neutral-v1", True, "third_country", "[1]"), check)
    refused(db, base, (987_654_321, "neutral-v1", True, "third_country", "{}"), psycopg.errors.ForeignKeyViolation)
    db.execute(base, (ok, "neutral-v1", True, "third_country", "{}"))
    refused(db, base, (ok, "neutral-v1", False, "no_evidence", "{}"), psycopg.errors.UniqueViolation)

    runs = ("INSERT INTO analytics.neutral_rule_runs (rule_version, protocol, verdict, labels, params, result) "
            "VALUES ('neutral-v1', 'neutral-ab-v1', %s, %s, '{}', '{}')")
    refused(db, runs, ("maybe", "{}"), check)
    refused(db, runs, ("justified", "[]"), check)
    run = one(db, runs + " RETURNING id", ("justified", "{}"))

    promo = ("INSERT INTO analytics.neutral_rule_promotion (promoted_by, action, rule_version, reason, run_id) "
             "VALUES (%s,%s,%s,%s,%s)")
    reason = "long enough to be a reason"
    refused(db, promo, ("bot", "promote", "neutral-v1", reason, run), check)
    refused(db, promo, ("owner", "promote", "neutral-v1", "short", run), check)
    refused(db, promo, ("owner", "promote", "neutral-v1", reason, None), check)  # a promotion cites a run
    refused(db, promo, ("owner", "promote", None, reason, run), check)
    refused(db, promo, ("owner", "retire", "neutral-v1", reason, None), check)  # a retirement names no rule
    refused(db, promo, ("owner", "retire", None, reason, run), check)
    refused(db, promo, ("owner", "promote", "neutral-v1", reason, run + 999), psycopg.errors.ForeignKeyViolation)
    db.execute(promo, ("owner", "promote", "neutral-v1", reason, run))


def test_decisions_and_backtests_cannot_be_edited_or_deleted_afterwards(db: psycopg.Connection[Any],
                                                                       world: World) -> None:
    ns.classify_everything(db, at=NOW)
    run = justified_run(db)
    ns.promote(db, run.id, by="owner", reason="the backtest justified the rule: better, nowhere worse")
    for sql in ("UPDATE analytics.neutral_rule_runs SET verdict = 'inconclusive'",
                "DELETE FROM analytics.neutral_rule_runs",
                "UPDATE analytics.neutral_rule_promotion SET reason = 'edited quietly, after the fact'",
                "DELETE FROM analytics.neutral_rule_promotion"):
        with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), db.transaction():
            db.execute(sql)
    db.execute("DELETE FROM core.fixtures WHERE id = %s", (world.ids["final"],))
    assert world.ids["final"] not in verdicts(db), "a deleted fixture takes its derived verdicts with it"
