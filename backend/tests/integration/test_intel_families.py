"""The page of the families in shadow, in a real database (plan F10.17 and F11.11, ``fbi.api.services.families``): what the Admin Console reads of
the cycle of a family - its decision, the rule that grades it, what became of it, the post-mortem and the memory.

The pure parts are in tests/unit/test_api_families.py. Here: an empty database answers with the four families and nothing in them; a family that
completed the cycle in shadow, through the very steps the worker hands to the nightly job, is read whole (the numbers of the page are the numbers of the
tables); only the LAST word of a selection counts, whatever state it ended in, and the revisions are counted; the filters of the list leave the cards
as they are; the pipeline's own decisions are not read; the steps are read from the runs the jobs recorded, a step that raised with its error; the route
answers the owner and refuses everyone else; and the page of a decision shows a family's post-mortem."""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from apps.worker import scheduler
from psycopg.rows import dict_row

from fbi.api.services import families as svc
from fbi.api.services import intelligence
from fbi.familydecisions import decide as fd
from fbi.familydecisions import outcomes as fo
from fbi.familydecisions import postmortem as pm
from fbi.intel import cycle
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT, catalogue, played, run, upcoming
from .test_families_score import play
from .test_familydecisions_decide import NOW, Market, scene
from .test_familydecisions_memory import AFTER, NIGHT, switch
from .test_familydecisions_outcomes import LATER, decided
from .test_intel_api import client_for, env  # noqa: F401  (a fixture)
from .test_leak_audit_families import forged
from .test_migration_0094_family_learning import DAY, MEMORY, POSTMORTEMS, insert, post_mortem
from .test_migration_0094_family_learning import memory as a_snapshot

pytestmark = pytest.mark.integration

ROUTE = "/api/v1/admin/intelligence/families"


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.families import forecast

    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def learn(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, w: World) -> int:
    """A family completes the cycle in shadow, through the steps the worker hands to the nightly job: the decision of the corners of a match, the match
    played, and the settlement, the post-mortem and the memory. Returns the match."""
    switch(monkeypatch, "shadow")
    fid, _, _ = decided(db, w)
    play(w, fid)  # 11 corners: the over of 10.5 won
    steps = scheduler.family_nightly_steps(db, NIGHT)
    for key in ("outcomes", "postmortems", "memory"):
        for _, fn in steps[key]:
            fn()
    return fid


def stored_postmortem(db: psycopg.Connection[Any]) -> dict[str, Any]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intel.family_postmortems")
        [row] = cur.fetchall()
        return row


# ── what there is to read ────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_empty_database_answers_with_the_four_families_and_nothing_in_them(db: psycopg.Connection[Any]) -> None:
    envelope = svc.overview(db, at=NIGHT)
    assert envelope.status == "ok"
    data = envelope.data
    assert set(data) == {"versions", "window", "mode", "steps", "families", "items", "total", "rules", "memory"}
    assert data["versions"] == {"forecast": "family-v1", "decision": "decision-fam-v1", "outcome": "outcome-fam-v1", "postmortem": "pm-fam-v1",
                                "memory": "memory-fam-v1"}
    assert data["window"] == {"days": 14, "from": (NIGHT - timedelta(days=14)).isoformat(), "to": NIGHT.isoformat()}
    assert (data["mode"], data["steps"], data["items"], data["total"], data["memory"]) == (None, [], [], 0, []), "while the switch is off there is nothing"
    assert [c["family"] for c in data["families"]] == ["GOALS_HALF", "CORNERS", "CARDS", "YELLOW"]
    assert all((c["selections"], c["rejected"], c["settled"], c["open"], c["results"], c["verdicts"], c["memory"]) == (0, 0, 0, 0, {}, {}, None)
               for c in data["families"])
    assert sorted(data["rules"]) == ["cards_lines_ft@v1", "corners_ft@v1", "goals_1h@v1", "goals_2h@v1", "goals_halves@v1", "yellow_ft@v1"]


def test_a_family_that_completed_the_cycle_in_shadow_is_read_whole(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid = learn(db, monkeypatch, w)
    p = stored_postmortem(db)
    data = svc.overview(db, at=NIGHT).data

    corners = next(c for c in data["families"] if c["family"] == "CORNERS")
    assert (corners["selections"], corners["rejected"], corners["settled"], corners["open"]) == (1, 0, 1, 0)
    assert corners["results"] == {"win": 1} and corners["verdicts"] == {"SUERTE": 1}, "won at a price worse than the close: luck"
    assert corners["rules"] == ["corners_ft@v1"]
    assert corners["memory"]["entity_key"] == "CORNERS" and corners["memory"]["version"] == "memory-fam-v1"
    n_eff = math.pow(0.5, 1 / 60)  # the match was played the day before
    assert corners["memory"]["stats"]["all"]["n"] == 1 and corners["memory"]["confidence"] == round(n_eff / (n_eff + 30), 4)
    assert all(c["selections"] == 0 for c in data["families"] if c["family"] != "CORNERS")

    assert data["total"] == 1 and len(data["items"]) == 1
    [item] = data["items"]
    assert (item["fixture_id"], item["family"], item["model_name"], item["market_key"], item["selection"], item["line"]) == (
        fid, "CORNERS", "family-corners_ft", "CORNERS_OU", "Over", 10.5)
    assert item["state"] == "INVESTIGACION" and item["stake_units"] == 0.0 and item["revisions"] == 1 and item["checkpoint"] == "T-24h"
    assert {"not_calibrated", fd.REASON_RESEARCH} <= set(item["reasons"])
    assert item["match"] == f"{item['home']} - {item['away']}" and item["competition"] == "Knowledge League" and "country" in item
    assert item["rule"] == "corners_ft@v1" and data["rules"]["corners_ft@v1"]["columns"] == ["corners_ft_home", "corners_ft_away"]
    assert item["odds"] == float(p["odds"]) and item["p_model"] == float(p["p_model"]) and item["p_market"] == float(p["p_decision"])
    assert item["forecast"]["calibration"] == "UNCALIBRATED" and item["forecast"]["forecast_id"] and item["forecast"]["known_at"]
    o = item["outcome"]
    assert (o["result"], o["profit_flat"], o["close_p_fair"], o["close_minutes_to_ko"], o["clv"]) == (
        "win", float(p["profit_flat"]), float(p["p_close"]), 23 * 60 + 30, float(p["clv"]))
    assert o["close_odds"] > 1
    assert item["postmortem"]["verdict"] == p["verdict"] == "SUERTE" and item["postmortem"]["quality"] == p["quality"] == "BAD"
    assert item["postmortem"]["causes"] == [c["text"] for c in p["causes"]] and item["postmortem"]["actual"] == 11.0
    assert item["postmortem"]["margin"] == 0.5

    assert [(m["entity_type"], m["entity_key"]) for m in data["memory"]] == [("family", "CORNERS"), ("market", "CORNERS_OU")], (
        "a competition or a referee is remembered from three post-mortems")
    assert data["memory"][0]["stats"]["models"] == {"family-corners_ft": data["memory"][0]["stats"]["all"]} and data["memory"][1]["entity_name"] is None
    assert data["mode"] is None, "the steps were called by hand: no job recorded them"


def test_only_the_last_word_of_a_selection_counts_whatever_state_it_ended_in(db: psycopg.Connection[Any], w: World,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """A selection that a later pass refused (a fourth book with an absurd price) is a rejection: it is the family's last word, the post-mortem does
    not study it, and the revisions that came before are counted, not listed."""
    switch(monkeypatch, "shadow")
    fid, market, _ = scene(db, w)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [book] = w.books(4)[3:]
    market.quote(book, 9.00, 1.10, AT + timedelta(hours=2))
    market.read(AT + timedelta(hours=2, minutes=5))
    assert fd.decide_families(db, at=AT + timedelta(hours=3))[0].written == 1
    play(w, fid)
    assert fo.settle(db, at=LATER).settled == 2, "both revisions are settled"
    assert pm.study(db, at=AFTER).written == 0, "and none is studied: the last word was a rejection"

    data = svc.overview(db, at=NIGHT).data
    [item] = data["items"]
    assert (item["state"], item["revisions"], item["stake_units"]) == ("RECHAZADO", 2, 0.0)
    assert "price_outlier" in item["reasons"] and fd.REASON_RESEARCH in item["reasons"]
    assert item["outcome"]["result"] == "win" and item["postmortem"] is None
    corners = next(c for c in data["families"] if c["family"] == "CORNERS")
    assert (corners["selections"], corners["rejected"], corners["settled"], corners["open"], corners["results"], corners["verdicts"]) == (0, 1, 0, 0, {}, {}), (
        "what became of a rejection is not what the family chose")
    assert data["total"] == 1
    assert svc.overview(db, state="INVESTIGACION", at=NIGHT).data["items"] == []
    assert svc.overview(db, state="RECHAZADO", at=NIGHT).data["total"] == 1


def test_a_selection_that_waits_for_its_match_is_open(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    switch(monkeypatch, "shadow")
    fid, _, _ = decided(db, w)
    data = svc.overview(db, at=NOW).data
    corners = next(c for c in data["families"] if c["family"] == "CORNERS")
    assert (corners["selections"], corners["settled"], corners["open"], corners["results"]) == (1, 0, 1, {})
    [item] = data["items"]
    assert item["fixture_id"] == fid and item["outcome"] is None and item["postmortem"] is None and item["state"] == "INVESTIGACION"


def test_two_words_known_at_the_same_instant_are_told_apart_by_the_order_they_were_written(db: psycopg.Connection[Any], w: World,
                                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """The last word is the one known last and, of two known at the very same instant, the one written last: the same row the post-mortem studies
    (``STOOD_SQL`` orders by ``known_at DESC, id DESC``), so that the page and the post-mortem never call different rows the last word."""
    switch(monkeypatch, "shadow")
    decided(db, w)
    [(first,)] = db.execute("SELECT id FROM intel.decisions").fetchall()
    later = forged(db, int(first), state="RECHAZADO")  # a copy at the same known_at, written after
    assert later > first
    assert db.execute("SELECT count(DISTINCT known_at) FROM intel.decisions").fetchone() == (1,)
    data = svc.overview(db, at=NOW).data
    [item] = data["items"]
    assert (item["id"], item["state"], item["revisions"]) == (later, "RECHAZADO", 2)
    assert next(c for c in data["families"] if c["family"] == "CORNERS")["rejected"] == 1


def test_the_filters_of_the_list_leave_the_cards_as_they_are(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    learn(db, monkeypatch, w)
    everything = svc.overview(db, at=NIGHT).data
    only_cards = svc.overview(db, family="CARDS", at=NIGHT).data
    assert only_cards["items"] == [] and only_cards["total"] == 0
    assert only_cards["families"] == everything["families"], "a card is the family's whole record, not what the list shows"
    only_corners = svc.overview(db, family="CORNERS", at=NIGHT).data
    assert only_corners["items"] == everything["items"] and only_corners["total"] == 1
    assert only_cards["memory"] == [], "the memory of another family is not listed under CARDS"
    assert only_corners["memory"] == everything["memory"]
    assert svc.overview(db, limit=1, at=NIGHT).data["total"] == 1


def test_the_window_is_counted_from_the_kickoff(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    learn(db, monkeypatch, w)
    [(kickoff,)] = db.execute("SELECT kickoff_at FROM intel.decisions").fetchall()
    exactly = svc.overview(db, days=2, at=kickoff + timedelta(days=2)).data
    assert exactly["total"] == 1 and exactly["window"]["days"] == 2 and exactly["window"]["from"] == kickoff.isoformat(), "the window includes its first instant"
    after = svc.overview(db, days=2, at=kickoff + timedelta(days=2, minutes=1)).data
    assert after["total"] == 0 and after["items"] == [], "a match that kicked off before the window is not in it"
    assert svc.overview(db, days=1, at=kickoff + timedelta(days=2)).data["total"] == 0
    assert next(c for c in after["families"] if c["family"] == "CORNERS")["selections"] == 0
    assert svc.overview(db, days=3, at=kickoff + timedelta(days=2, minutes=1)).data["total"] == 1


def test_the_pipelines_own_decisions_are_not_read(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A row of the core layer's version is never a family's, even one that looks like it: the page reads the version of the families and nothing else."""
    switch(monkeypatch, "shadow")
    decided(db, w)
    [(decision,)] = db.execute("SELECT id FROM intel.decisions").fetchall()
    forged(db, int(decision), decision_version="decision-v1")
    assert db.execute("SELECT count(*) FROM intel.decisions").fetchone() == (2,)
    data = svc.overview(db, at=NOW).data
    assert data["total"] == 1 and [i["id"] for i in data["items"]] == [decision]


def another_family(db: psycopg.Connection[Any], source: int, family: str, market_key: str) -> int:
    """A decision written by hand: the one ``source`` as the model of another family took it."""
    [(filters,)] = db.execute("SELECT filters FROM intel.decisions WHERE id = %s", (source,)).fetchall()
    for f in filters:
        if f["key"] == "model":
            f["data"]["family"] = family
    return forged(db, source, market_key=market_key, filters=filters)


def test_the_list_is_the_newest_match_first_cut_at_the_limit_and_filtered_by_family(db: psycopg.Connection[Any], w: World,
                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    switch(monkeypatch, "shadow")
    catalogue(db)
    played(w)
    first, second = upcoming(w, 0, 1), upcoming(w, 2, 3, when=timedelta(days=1, hours=2))
    run(db, [first, second])
    one = Market(db, w, first)
    one.pays(0.10)
    one.read(AT + timedelta(minutes=30))
    two = Market(db, w, second, like=one)
    two.pays(0.10)
    two.read(AT + timedelta(minutes=30))
    assert fd.decide_families(db, at=NOW)[0].written == 2

    data = svc.overview(db, at=NOW).data
    assert [i["fixture_id"] for i in data["items"]] == [second, first] and data["total"] == 2, "the match that kicks off last is the first of the list"
    cut = svc.overview(db, limit=1, at=NOW).data
    assert [i["fixture_id"] for i in cut["items"]] == [second] and cut["total"] == 2, "the total is what matches, not what is shown"

    [(decision,)] = db.execute("SELECT id FROM intel.decisions WHERE fixture_id = %s", (first,)).fetchall()
    cards = another_family(db, int(decision), "CARDS", "CARDS_OU")
    everything = svc.overview(db, at=NOW).data
    assert everything["total"] == 3 and {i["family"] for i in everything["items"]} == {"CORNERS", "CARDS"}
    assert {(i["fixture_id"], i["market_key"]): i["revisions"] for i in everything["items"]} == {
        (first, "CORNERS_OU"): 1, (first, "CARDS_OU"): 1, (second, "CORNERS_OU"): 1}, (
        "the revisions of a bet are counted among that bet's own words, not among everything said about its match")
    only_cards = svc.overview(db, family="CARDS", at=NOW).data
    assert [i["id"] for i in only_cards["items"]] == [cards] and only_cards["total"] == 1
    assert only_cards["items"][0]["rule"] == "cards_lines_ft@v1" and only_cards["items"][0]["market_key"] == "CARDS_OU"
    corners = svc.overview(db, family="CORNERS", at=NOW).data
    assert {i["fixture_id"] for i in corners["items"]} == {first, second} and corners["total"] == 2
    assert svc.overview(db, family="YELLOW", at=NOW).data["items"] == []
    by_family = {c["family"]: c["selections"] for c in everything["families"]}
    assert by_family == {"GOALS_HALF": 0, "CORNERS": 2, "CARDS": 1, "YELLOW": 0}


def test_rows_of_another_version_are_not_what_the_page_reads(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """An outcome, a post-mortem or a memory of a version the page does not know are another reading of the same facts: they are neither shown nor
    counted."""
    switch(monkeypatch, "shadow")
    fid, _, _ = decided(db, w)
    [(decision,)] = db.execute("SELECT id FROM intel.decisions").fetchall()
    db.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, version, computed_at) "
               "VALUES (%s, %s, 'win', 1.1, 0, 'outcome-fam-v0', %s)", (decision, LATER, LATER))
    insert(db, POSTMORTEMS, post_mortem(int(decision), fid, version="pm-fam-v0"))
    insert(db, MEMORY, a_snapshot(version="memory-fam-v0", entity_key="CARDS"))
    data = svc.overview(db, at=NIGHT).data
    [item] = data["items"]
    assert item["outcome"] is None and item["postmortem"] is None and data["memory"] == []
    corners = next(c for c in data["families"] if c["family"] == "CORNERS")
    assert (corners["selections"], corners["settled"], corners["open"], corners["results"], corners["verdicts"]) == (1, 0, 1, {}, {})
    assert next(c for c in data["families"] if c["family"] == "CARDS")["memory"] is None


def test_the_memory_is_the_newest_snapshot_of_each_entity_the_biggest_first_and_a_few_of_the_many(db: psycopg.Connection[Any],
                                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "MEMORY_TOP", 2)

    def snap(kind: str, key: str, n: int, *, day: int = 0, **changes: Any) -> None:
        insert(db, MEMORY, a_snapshot(entity_type=kind, entity_key=key, entity_name=f"name of {key}", stats={"all": {"n": n}}, as_of_day=DAY + timedelta(days=day),
                                      **changes))

    snap("family", "CORNERS", 3, day=-1)
    snap("family", "CORNERS", 5)  # the newest of CORNERS
    snap("family", "CARDS", 9)
    snap("family", "CARDS", 99, day=3, version="memory-fam-v0")  # of a version the page does not read
    snap("market", "CORNERS_OU", 5)
    snap("market", "CARDS_OU", 3)
    snap("market", "YELLOW_OU", 2)  # a third market, with the top at two: the markets are not cut
    snap("competition", "11", 4)
    snap("competition", "12", 7)
    snap("competition", "13", 2)
    snap("referee", "5", 1)
    snap("referee", "6", 6)
    shown = svc.overview(db, at=NIGHT).data["memory"]
    assert [(m["entity_type"], m["entity_key"], m["stats"]["all"]["n"]) for m in shown] == [
        ("family", "CARDS", 9), ("family", "CORNERS", 5), ("market", "CORNERS_OU", 5), ("market", "CARDS_OU", 3), ("market", "YELLOW_OU", 2),
        ("competition", "12", 7), ("competition", "11", 4), ("referee", "6", 6), ("referee", "5", 1)], (
        "the families and the markets in full, the competitions and the referees with the most evidence, each kind biggest first")
    assert shown[0]["entity_name"] == "name of CARDS" and shown[0]["confidence"] == pytest.approx(0.2857, abs=1e-6) and shown[0]["as_of_day"] == DAY.isoformat()
    assert shown[0]["version"] == "memory-fam-v1"
    cards = next(c for c in svc.overview(db, at=NIGHT).data["families"] if c["family"] == "CARDS")
    assert cards["memory"]["entity_key"] == "CARDS" and cards["memory"]["stats"]["all"]["n"] == 9, "the card holds the newest snapshot of its family"
    corners = next(c for c in svc.overview(db, at=NIGHT).data["families"] if c["family"] == "CORNERS")
    assert corners["memory"]["stats"]["all"]["n"] == 5, "of the two snapshots of CORNERS, the later day"


# ── the steps ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def jobs(migrated_database: str, seed: Seed) -> Iterator[psycopg.Connection[Any]]:
    """A connection that commits (a run records itself, as in production), and leaves no run behind."""
    conn = psycopg.connect(migrated_database)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.execute("DELETE FROM intel.runs")
        conn.commit()
        conn.close()


def test_the_steps_are_read_from_the_runs_the_jobs_recorded(jobs: psycopg.Connection[Any]) -> None:
    def worked() -> dict[str, Any]:
        return {"mode": "shadow", "forecasts": 12, "fixtures": 3, "priced": 8, "candidates": 2, "evaluated": 2, "written": 2, "failed": 0,
                "by_family": {"CORNERS": 2}, "by_state": {"INVESTIGACION": 2}, "by_reason": {fd.REASON_RESEARCH: 2}, "errors": []}

    def waited() -> dict[str, Any]:
        return {"mode": "shadow", "waiting": 1}

    def boom() -> dict[str, Any]:
        raise ValueError("the post-mortem could not be written")

    # the decide job comes every quarter of an hour and works once an hour: the runs that waited come after the one that worked
    cycle._run(jobs, "decide", AT - timedelta(hours=1), [("families", lambda: {**worked(), "written": 9})])
    cycle._run(jobs, "decide", AT, [("families", worked)])
    for minutes in (15, 30, 45):
        cycle._run(jobs, "decide", AT + timedelta(minutes=minutes), [("families", waited)])
    cycle._run(jobs, "nightly", AT + timedelta(hours=4), [
        ("family_outcomes", lambda: {"mode": "shadow", "open": 2, "settled": 2, "by_result": {"win": 2}}),
        ("family_postmortems", boom),
        ("family_memory", lambda: {"mode": "shadow", "postmortems": 2, "written": 1, "waiting": 0})])

    data = svc.overview(jobs, at=AT + timedelta(days=1)).data
    assert [s["step"] for s in data["steps"]] == ["families", "family_outcomes", "family_postmortems", "family_memory"]
    families, outcomes, postmortems, memory = data["steps"]
    assert families["job"] == "decide" and families["status"] == "ok" and families["result"]["written"] == 2 and families["started_at"] == AT.isoformat()
    assert families["error"] is None and isinstance(families["ms"], int) and families["finished_at"]
    assert outcomes["job"] == "nightly" and outcomes["result"] == {"mode": "shadow", "open": 2, "settled": 2, "by_result": {"win": 2}}
    assert postmortems["result"] == {} and postmortems["error"] == "family_postmortems: ValueError: the post-mortem could not be written"
    assert postmortems["status"] == "partial"
    assert memory["result"]["waiting"] == 0 and memory["result"]["written"] == 1, "the memory always reports waiting: it is not a wait"
    assert data["mode"] == "shadow"
    assert svc.overview(jobs, at=AT + timedelta(days=9)).data["steps"] == [], "a run older than the lookback says nothing of now"
    assert svc.overview(jobs, at=AT + timedelta(days=9)).data["mode"] is None


# ── over HTTP ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_route_answers_the_owner_and_refuses_everyone_else(env: Seed) -> None:  # noqa: F811
    owner = client_for("SUPER_ADMIN")
    r = owner.get(ROUTE)
    assert r.status_code == 200 and r.json()["status"] == "ok"
    body = r.json()["data"]
    assert [c["family"] for c in body["families"]] == ["GOALS_HALF", "CORNERS", "CARDS", "YELLOW"] and body["items"] == [] and body["mode"] is None
    assert owner.get(ROUTE, params={"family": "CORNERS", "state": "RECHAZADO", "days": 30, "limit": 10}).status_code == 200
    for params in ({"family": "SHOTS"}, {"state": "APROBADO"}, {"days": 0}, {"days": 121}, {"limit": 0}, {"limit": 501}):
        assert owner.get(ROUTE, params=params).status_code == 422, params
    for role in ("USER", "ANALYST"):
        assert client_for(role).get(ROUTE).status_code in (401, 403), role


# ── the page of a decision ───────────────────────────────────────────────────────────────────────────────────────────────

def test_the_page_of_a_decision_of_a_family_shows_the_post_mortem_the_family_made_of_it(db: psycopg.Connection[Any], w: World,
                                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    learn(db, monkeypatch, w)
    p = stored_postmortem(db)
    detail = intelligence.decision_detail(db, int(p["decision_id"])).data
    assert detail["pick"] is None and detail["decision"]["pick_id"] is None and detail["outcome"]["result_status"] == "win"
    shown = detail["postmortem"]
    assert shown["version"] == "pm-fam-v1" and shown["verdict"] == "SUERTE" and shown["decision_quality"] == "BAD" == shown["quality"]
    assert shown["causes"] == p["causes"] and shown["answers"]["aprendizaje"]
    assert detail["decision"]["state"] == "INVESTIGACION"


def test_a_decision_of_a_family_without_a_post_mortem_has_none(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    switch(monkeypatch, "shadow")
    decided(db, w)
    [(decision,)] = db.execute("SELECT id FROM intel.decisions").fetchall()
    assert intelligence.decision_detail(db, int(decision)).data["postmortem"] is None
