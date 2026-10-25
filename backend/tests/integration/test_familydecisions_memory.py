"""What the families remember, in a real database (plan F11, ``memory-fam-v1``): the post-mortems of their decisions added up.

The pure parts are in tests/unit/test_familydecisions_memory.py. Here: a family completes the cycle in shadow - a decision, its settlement, its
post-mortem and its memory - through the very steps the worker hands to the nightly job; the memory rests on the post-mortems of its version written by
the moment it is built and on no others; a night with nothing new writes nothing, and new evidence is a new row that leaves the old one as it was;
a second pass the same day waits for the next; one entity the database refuses costs only itself; the memory writes its own table and no other."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from apps.worker import scheduler
from psycopg.rows import dict_row

from fbi.familydecisions import decide as fd
from fbi.familydecisions import memory as mem
from fbi.familydecisions import outcomes as fo
from fbi.familydecisions import postmortem as pm
from fbi.intel.postmortem import verdict_of
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import referees
from .test_families_score import play
from .test_familydecisions_outcomes import LATER, decided
from .test_leak_audit_families import forged
from .test_migration_0094_family_learning import MEMORY, POSTMORTEMS, insert, post_mortem
from .test_migration_0094_family_learning import memory as a_snapshot

pytestmark = pytest.mark.integration

AFTER = LATER + timedelta(hours=1)
"""The pass of the post-mortem."""
NIGHT = AFTER + timedelta(hours=1)
"""The pass of the memory: 21:00 UTC, 4 p.m. of 3 March 2035 in Bogotá."""
TODAY = date(2035, 3, 3)
OTHER_TABLES = ("intel.postmortems", "intel.entity_memory", "ai.memory_events", "models.match_forecasts", "intel.decisions", "intel.decision_outcomes",
                "intel.family_postmortems")


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.families import forecast

    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def switch(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(fd, "environment", lambda: {} if value is None else {fd.SWITCH: value})


def snapshots(db: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intel.family_memory ORDER BY id")
        return cur.fetchall()


def by_entity(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["entity_type"], r["entity_key"]): r for r in rows}


def postmortems(db: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intel.family_postmortems ORDER BY id")
        return cur.fetchall()


def counts(db: psycopg.Connection[Any], tables: tuple[str, ...] = OTHER_TABLES) -> dict[str, int]:
    return {t: int(db.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]) for t in tables}


def studied(db: psycopg.Connection[Any], w: World) -> tuple[int, int]:
    """A decision of a family, its match played, settled and studied: (the decision, the post-mortem)."""
    fid, _, _ = decided(db, w)
    play(w, fid)
    assert fo.settle(db, at=LATER).settled == 1
    assert pm.study(db, at=AFTER).written == 1
    [(decision, postmortem)] = db.execute("SELECT decision_id, id FROM intel.family_postmortems").fetchall()
    return int(decision), int(postmortem)


def learned(db: psycopg.Connection[Any], source: int, fixture: int, *, result: str = "win", quality: str = "GOOD", **changes: Any) -> int:
    """One more post-mortem of ``pm-fam-v1``, for a decision of its own (a copy of ``source``), whose quality and verdict follow the rule."""
    decision = forged(db, source)
    return insert(db, POSTMORTEMS, post_mortem(decision, fixture, result=result, quality=quality, verdict=verdict_of(result, quality), **changes))


# ── the cycle ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_family_completes_the_cycle_in_shadow_decision_settlement_post_mortem_memory(db: psycopg.Connection[Any], w: World,
                                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """The plan's end of F11: one family, from a decision to what it remembers, through the steps the worker hands to the nightly job."""
    switch(monkeypatch, "shadow")
    fid, _, _ = decided(db, w)  # the decision, taken 23 hours before the kick-off
    assert counts(db, ("intel.decisions", "intel.decision_outcomes", "intel.family_postmortems", "intel.family_memory")) == {
        "intel.decisions": 1, "intel.decision_outcomes": 0, "intel.family_postmortems": 0, "intel.family_memory": 0}
    play(w, fid)  # 11 corners: the over of 10.5 won

    steps = scheduler.family_nightly_steps(db, NIGHT)
    assert list(steps) == ["outcomes", "postmortems", "memory"], "after the steps of the core layer they follow, in the order they depend on each other"
    results = {name: fn() for key in ("outcomes", "postmortems", "memory") for name, fn in steps[key]}
    assert list(results) == ["family_outcomes", "family_postmortems", "family_memory"]
    assert results["family_outcomes"]["settled"] == 1 and results["family_postmortems"]["written"] == 1
    assert results["family_memory"] == {"mode": "shadow", "postmortems": 1, "entities": 2, "written": 2, "unchanged": 0, "waiting": 0, "failed": 0,
                                        "by_type": {"family": 1, "market": 1}, "errors": []}

    [p] = postmortems(db)
    by = by_entity(snapshots(db))
    assert set(by) == {("family", "CORNERS"), ("market", "CORNERS_OU")}, (
        "one decision is a family and a market; its competition has one, and the match has no referee the identity layer placed")
    family = by["family", "CORNERS"]
    assert (family["version"], family["as_of_day"], family["built_at"], family["entity_name"]) == ("memory-fam-v1", TODAY, NIGHT, "córners")
    everything = family["stats"]["all"]
    assert (everything["n"], everything["decided"], everything["wins"], everything["hit"]) == (1, 1, 1, 1.0)
    assert everything["claimed"] == pytest.approx(float(p["p_model"]), abs=1e-4) and everything["profit"] == float(p["profit_flat"])
    assert everything["clv_mean"] == pytest.approx(float(p["clv"]), abs=1e-6) and everything["quality"]["BAD"] == 1, (
        "the 6 % margin of the scene did not move: the price was worse than the close")
    assert everything["verdicts"]["SUERTE"] == 1 and sum(everything["verdicts"].values()) == 1, "won at a price worse than the close: luck"
    assert family["stats"]["recent"] == everything and family["stats"]["recent_days"] == 28
    assert family["stats"]["models"] == {"family-corners_ft": everything}
    assert family["delta"] == {"hit": 0.0, "claimed": 0.0, "gap": 0.0, "clv_mean": 0.0, "roi": 0.0}, "everything is recent: nothing differs"
    assert family["evidence_ref"]["source_version"] == "pm-fam-v1" and family["evidence_ref"]["postmortems"] == 1
    assert family["evidence_ref"]["through"] == {"id": p["id"], "created_at": p["created_at"].isoformat()}
    assert family["evidence_ref"]["sample"] == [{"postmortem": p["id"], "decision": p["decision_id"]}]
    n_eff = math.pow(0.5, 1 / 60)  # the match was played the day before
    assert float(family["confidence"]) == round(n_eff / (n_eff + 30), 4) and family["evidence_ref"]["n_eff"] == round(n_eff, 2)
    assert by["market", "CORNERS_OU"]["entity_name"] is None and by["market", "CORNERS_OU"]["stats"]["all"] == everything
    assert "models" not in by["market", "CORNERS_OU"]["stats"]

    latest = db.execute("SELECT entity_type, entity_key, as_of_day, version FROM intel.family_memory_latest ORDER BY entity_type").fetchall()
    assert latest == [("family", "CORNERS", TODAY, "memory-fam-v1"), ("market", "CORNERS_OU", TODAY, "memory-fam-v1")], "what the families know of themselves today"


def test_with_the_switch_off_the_worker_hands_over_no_memory_and_the_step_itself_does_nothing(db: psycopg.Connection[Any], w: World,
                                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    studied(db, w)
    switch(monkeypatch, "off")
    assert scheduler.family_nightly_steps(db, NIGHT) == {}
    assert mem.run_step(db, at=NIGHT) == {"mode": "off"} and snapshots(db) == [], "off is off even for a step that is called by hand"
    switch(monkeypatch, "shadow")
    out = mem.run_step(db, at=NIGHT)
    assert out["mode"] == "shadow" and out["written"] == 2 and len(snapshots(db)) == 2


def test_the_memory_of_nothing_is_nothing(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    switch(monkeypatch, "shadow")
    assert mem.run_step(db, at=NIGHT) == {"mode": "shadow", "postmortems": 0, "entities": 0, "written": 0, "unchanged": 0, "waiting": 0, "failed": 0,
                                          "by_type": {}, "errors": []}
    assert snapshots(db) == []


# ── when it writes ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_night_with_nothing_new_writes_nothing_and_a_row_is_never_rewritten(db: psycopg.Connection[Any], w: World) -> None:
    studied(db, w)
    first = mem.remember(db, at=NIGHT)
    assert (first.written, first.unchanged) == (2, 0)
    rows = snapshots(db)
    same_day = mem.remember(db, at=NIGHT + timedelta(hours=2))
    assert (same_day.postmortems, same_day.entities, same_day.written, same_day.unchanged, same_day.waiting) == (1, 2, 0, 2, 0)
    next_night = mem.remember(db, at=NIGHT + timedelta(days=1))
    assert (next_night.written, next_night.unchanged) == (0, 2), "a day later with the same post-mortems: still nothing new, so nothing written"
    assert snapshots(db) == rows


def test_new_evidence_is_a_new_row_the_next_day_and_the_first_stays_as_it_was(db: psycopg.Connection[Any], w: World) -> None:
    decision, first = studied(db, w)
    mem.remember(db, at=NIGHT)
    before = snapshots(db)
    [p] = postmortems(db)
    second = learned(db, decision, p["fixture_id"], result="loss", quality="BAD", created_at=NIGHT + timedelta(hours=3))

    again = mem.remember(db, at=NIGHT + timedelta(days=1))
    assert (again.postmortems, again.written, again.unchanged, again.waiting) == (2, 2, 0, 0), "both entities rest on a post-mortem they did not"
    rows = snapshots(db)
    assert rows[:2] == before, "yesterday's snapshots are as they were written"
    new = by_entity(rows[2:])
    assert {r["as_of_day"] for r in new.values()} == {TODAY + timedelta(days=1)}
    family = new["family", "CORNERS"]
    assert family["stats"]["all"]["n"] == 2 and family["stats"]["all"]["wins"] == 1 and family["stats"]["all"]["hit"] == 0.5
    assert family["evidence_ref"]["through"]["id"] == second and family["evidence_ref"]["postmortems"] == 2
    assert [s["postmortem"] for s in family["evidence_ref"]["sample"]] == [second, first], "the newest first"
    latest = db.execute("SELECT stats -> 'all' ->> 'n' FROM intel.family_memory_latest WHERE entity_key = 'CORNERS'").fetchall()
    assert latest == [("2",)], "the view gives the newest day's snapshot"
    after = mem.remember(db, at=NIGHT + timedelta(days=2))
    assert (after.written, after.unchanged) == (0, 2), "and it is the newest snapshot, not the first, that the next night compares with"
    assert len(snapshots(db)) == 4


def test_new_evidence_the_same_day_waits_for_the_next_day(db: psycopg.Connection[Any], w: World) -> None:
    """A snapshot is as of a Bogotá day and there is one of an entity per day: the post-mortems written after the pass of the day are in the
    snapshot of the day that follows, not in the one of the day."""
    decision, _ = studied(db, w)
    mem.remember(db, at=NIGHT)
    before = snapshots(db)
    [p] = postmortems(db)
    learned(db, decision, p["fixture_id"], created_at=NIGHT + timedelta(hours=1))

    late = mem.remember(db, at=NIGHT + timedelta(hours=2))
    assert (late.postmortems, late.entities, late.written, late.waiting, late.failed) == (2, 2, 0, 2, 0)
    assert snapshots(db) == before, "nothing was written, and nothing was lost: the post-mortem is still there for the next pass"
    tomorrow = mem.remember(db, at=NIGHT + timedelta(days=1))
    assert (tomorrow.written, tomorrow.waiting) == (2, 0)
    assert len(snapshots(db)) == 4


def test_what_another_version_wrote_is_not_what_this_version_last_wrote(db: psycopg.Connection[Any], w: World) -> None:
    _, postmortem = studied(db, w)
    for kind, key in (("family", "CORNERS"), ("market", "CORNERS_OU")):
        insert(db, MEMORY, a_snapshot(version="memory-fam-v2", as_of_day=TODAY, entity_type=kind, entity_key=key,
                                      evidence_ref={"postmortems": 1, "through": {"id": postmortem}}))
    report = mem.remember(db, at=NIGHT)
    assert (report.written, report.unchanged) == (2, 0), "a snapshot of another version rests on its own rule: this version has still to write its own"
    assert sorted(r["version"] for r in snapshots(db)) == ["memory-fam-v1", "memory-fam-v1", "memory-fam-v2", "memory-fam-v2"]


def test_the_day_a_snapshot_is_as_of_is_the_day_of_bogota_not_the_one_of_utc(db: psycopg.Connection[Any], w: World) -> None:
    studied(db, w)
    late_evening = datetime(2035, 3, 4, 3, 0, tzinfo=NIGHT.tzinfo)  # 3 a.m. UTC of the 4th: 10 p.m. of the 3rd in Bogotá
    assert mem.remember(db, at=late_evening).written == 2
    assert {r["as_of_day"] for r in snapshots(db)} == {date(2035, 3, 3)}


# ── what it rests on ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_only_the_post_mortems_of_its_version_written_by_the_moment_are_summed(db: psycopg.Connection[Any], w: World) -> None:
    decision, _ = studied(db, w)
    [p] = postmortems(db)
    fixture = p["fixture_id"]
    learned(db, decision, fixture, version="pm-fam-v2", result="loss", quality="BAD")  # a later version of the post-mortem: not summed under v1
    learned(db, decision, fixture, created_at=NIGHT + timedelta(hours=5))  # written after the pass that builds the memory
    report = mem.remember(db, at=NIGHT)
    assert (report.postmortems, report.written) == (1, 2), "the one of v1 written by then"
    family = by_entity(snapshots(db))["family", "CORNERS"]
    assert family["stats"]["all"]["n"] == 1 and family["evidence_ref"]["postmortems"] == 1

    later = mem.remember(db, at=NIGHT + timedelta(days=1))
    assert later.postmortems == 2 and later.written == 2, "the next pass sees it"


def test_a_competition_and_a_referee_are_remembered_from_three_decisions_with_the_names_the_database_has(db: psycopg.Connection[Any], w: World) -> None:
    decision, _ = studied(db, w)
    [p] = postmortems(db)
    fixture = p["fixture_id"]
    competition = p["competition_id"]
    [alias] = referees(db, "Mateu L.")
    referee = int(db.execute("SELECT referee_id FROM core.referee_aliases WHERE id = %s", (alias,)).fetchall()[0][0])
    other = int(db.execute("INSERT INTO core.referees (name, name_key, origin, version) VALUES ('Taylor A.', 'taylor a.', 'rules', 'test') RETURNING id")
                .fetchall()[0][0])
    for _ in range(2):
        learned(db, decision, fixture, competition_id=competition, referee_id=referee)
    for _ in range(2):
        learned(db, decision, fixture, competition_id=987654321, referee_id=other)  # a competition the database does not know, twice

    mem.remember(db, at=NIGHT)
    by = by_entity(snapshots(db))
    assert ("competition", str(competition)) in by and by["competition", str(competition)]["stats"]["all"]["n"] == 3, "the first and two more"
    assert ("referee", str(referee)) not in by, "two decisions are an anecdote"
    assert ("competition", "987654321") not in by and ("referee", str(other)) not in by

    learned(db, decision, fixture, competition_id=competition, referee_id=referee)  # the third of the referee, the fourth of the competition
    learned(db, decision, fixture, competition_id=987654321, referee_id=other)  # the third of the unknown competition and of the other referee
    mem.remember(db, at=NIGHT + timedelta(days=1))
    by = by_entity([r for r in snapshots(db) if r["as_of_day"] == TODAY + timedelta(days=1)])
    assert by["referee", str(referee)]["entity_name"] == "Mateu L." and by["referee", str(referee)]["stats"]["all"]["n"] == 3
    assert by["competition", str(competition)]["stats"]["all"]["n"] == 4
    assert by["competition", str(competition)]["entity_name"] == db.execute("SELECT name FROM core.competitions WHERE id = %s",
                                                                           (competition,)).fetchall()[0][0]
    assert by["competition", "987654321"]["entity_name"] is None, "a competition nobody named is no name"
    assert by["competition", "987654321"]["stats"]["all"]["n"] == 3
    assert by["referee", str(other)]["entity_name"] == "Taylor A." and by["referee", str(other)]["stats"]["all"]["n"] == 3


def test_each_entity_sums_only_what_belongs_to_it(db: psycopg.Connection[Any], w: World) -> None:
    decision, _ = studied(db, w)
    [p] = postmortems(db)
    fixture = p["fixture_id"]
    learned(db, decision, fixture, result="loss", quality="BAD", family="CARDS", model_name="family-cards", market_key="CARDS_OU")
    learned(db, decision, fixture, result="loss", quality="NEUTRAL", market_key="CORNERS_1X2")
    mem.remember(db, at=NIGHT)
    by = by_entity(snapshots(db))
    assert {k for k in by if k[0] in ("family", "market")} == {
        ("family", "CORNERS"), ("family", "CARDS"), ("market", "CORNERS_OU"), ("market", "CARDS_OU"), ("market", "CORNERS_1X2")}
    assert by["family", "CORNERS"]["stats"]["all"]["n"] == 2 and by["family", "CARDS"]["stats"]["all"]["n"] == 1
    assert by["family", "CARDS"]["stats"]["all"]["verdicts"]["ERROR"] == 1 and by["family", "CARDS"]["entity_name"] == "tarjetas"
    assert by["market", "CORNERS_1X2"]["stats"]["all"]["wins"] == 0 and by["market", "CORNERS_OU"]["stats"]["all"]["wins"] == 1
    assert sorted(by["family", "CORNERS"]["stats"]["models"]) == ["family-corners_ft"]


# ── what it writes ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_it_writes_its_own_table_and_no_other(db: psycopg.Connection[Any], w: World) -> None:
    studied(db, w)
    before = counts(db)
    assert mem.remember(db, at=NIGHT).written == 2
    assert counts(db) == before, "the pipeline's post-mortem and memory, the AI's log, the forecasts, the decisions and the post-mortems are as they were"
    assert counts(db, ("intel.family_memory",)) == {"intel.family_memory": 2}


def test_a_dry_run_builds_and_writes_nothing(db: psycopg.Connection[Any], w: World) -> None:
    studied(db, w)
    report = mem.remember(db, at=NIGHT, write=False)
    assert (report.postmortems, report.entities, report.written, report.by_type) == (1, 2, 2, {"family": 1, "market": 1}), "what it would write"
    assert snapshots(db) == []
    assert mem.remember(db, at=NIGHT).written == 2, "and the real pass still has everything to do"


def test_one_entity_the_database_refuses_costs_only_itself(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    studied(db, w)
    real = mem._insert

    def flaky(conn: psycopg.Connection[Any], e: mem.Entity, *, as_of: date, at: datetime) -> bool:
        if e.type == "market":
            raise RuntimeError("the disk said no")
        return real(conn, e, as_of=as_of, at=at)

    monkeypatch.setattr(mem, "_insert", flaky)
    report = mem.remember(db, at=NIGHT)
    assert (report.written, report.failed, report.by_type) == (1, 1, {"family": 1})
    assert report.errors == ["market/CORNERS_OU: RuntimeError: the disk said no"]
    assert [r["entity_type"] for r in snapshots(db)] == ["family"]
    monkeypatch.setattr(mem, "_insert", real)
    retry = mem.remember(db, at=NIGHT + timedelta(hours=1))
    assert (retry.written, retry.unchanged) == (1, 1), "the one that failed is written by the next pass"


def test_the_constraints_of_the_table_are_the_last_line_and_cost_only_the_entity(db: psycopg.Connection[Any], w: World,
                                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    studied(db, w)
    real = mem.confidence_of
    monkeypatch.setattr(mem, "confidence_of", lambda n_eff: 1.5)  # a confidence above one: the table refuses it
    report = mem.remember(db, at=NIGHT)
    assert (report.written, report.failed) == (0, 2) and len(report.errors) == 2 and "CheckViolation" in report.errors[0]
    assert snapshots(db) == []
    db.execute("SELECT 1")  # the connection is still usable: each entity is its own savepoint
    monkeypatch.setattr(mem, "confidence_of", real)
    assert mem.remember(db, at=NIGHT).written == 2, "and the next pass writes what the table refused"
