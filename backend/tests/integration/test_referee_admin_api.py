"""The referees in the Admin Console (plan F3): the list, the queue of doubts, a referee's page and the decisions of a person - through
the service on the test's own connection (nothing is committed) and over HTTP (what the routes answer, who may call them)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from fbi.api.contracts.referees import ActionResult
from fbi.api.errors import ApiError
from fbi.api.services import referees as svc
from fbi.core.config import reset_cache
from fbi.people import referees as store
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, principal
from tests.integration.test_db_roles import granted  # noqa: F401  (the roles and their grants)
from tests.integration.test_referee_identity_store import T0, World, small_world, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration

OWNER = "owner@predigol.test"


@pytest.fixture()
def on_the_test_connection(world: World, monkeypatch: pytest.MonkeyPatch) -> World:  # noqa: F811
    """The decisions run on the connection of the test, inside its transaction: nothing reaches the database for good."""
    @contextmanager
    def write() -> Iterator[psycopg.Connection[Any]]:
        yield world.db

    monkeypatch.setattr(svc, "write", write)
    return world


def people(w: World) -> dict[str, int]:
    """Michael Oliver (two matches: 'Michael Oliver' and 'M. Oliver' in England) and the Dutch 'M. Oliver' (a doubt): the ids of the
    two referees (``michael``, ``dutch``)."""
    fixtures = small_world(w)
    store.build(w.db, apply=True)
    michael, dutch = w.referee_of(fixtures["full"]), w.referee_of(fixtures["dutch"])
    assert michael is not None and dutch is not None and michael != dutch
    return {"michael": michael, "dutch": dutch}


def wrote(w: World, result: ActionResult) -> tuple[str, int | None, int | None]:
    """What the event an action says it wrote really is: (action, referee, other)."""
    row = w.db.execute("SELECT action, referee_id, other_id FROM core.referee_events WHERE id = %s", (result.event_id,)).fetchone()
    assert row is not None, f"the event {result.event_id} does not exist"
    return row


def refused(status: int, code: str) -> Any:
    return pytest.raises(ApiError, check=lambda e: (e.status, e.code) == (status, code))


# ── reads ────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_list_gives_the_busiest_first_and_the_health_of_the_identity(on_the_test_connection: World) -> None:
    w = on_the_test_connection
    ids = people(w)
    body = svc.referees(w.db, q=None, limit=50, offset=0).data
    assert [(r.id, r.name, r.matches) for r in body.items] == [(ids["michael"], "Michael Oliver", 2), (ids["dutch"], "M. Oliver", 1)]
    first = body.items[0]
    assert (first.country, first.status, first.merged_into, first.name_locked) == ("England", "active", None, False)
    assert (first.first_match, first.last_match) == (T0 + timedelta(days=1, hours=3), T0 + timedelta(days=8, hours=3))
    assert body.total == 2 and body.queue_open == 1
    c = body.counts
    assert (c.referees_active, c.aliases, c.fixtures_with_referee, c.candidates_open, c.matches_with_a_doubt) == (2, 3, 3, 1, 1)
    assert c.settled_share == pytest.approx(2 / 3, abs=1e-3) and c.problems == []


def test_with_no_referee_placed_the_list_is_empty_and_healthy(on_the_test_connection: World) -> None:
    w = on_the_test_connection
    body = svc.referees(w.db, q=None, limit=50, offset=0).data
    assert (body.items, body.total, body.queue_open) == ([], 0, 0)
    c = body.counts
    assert (c.referees_active, c.fixtures_with_referee, c.matches_with_a_doubt, c.settled_share, c.problems) == (0, 0, 0, 1.0, [])


def test_the_list_pages_and_searches_under_any_spelling(on_the_test_connection: World) -> None:
    w = on_the_test_connection
    people(w)
    paged = svc.referees(w.db, q=None, limit=1, offset=1)
    page = paged.data
    assert [r.name for r in page.items] == ["M. Oliver"] and page.total == 2
    assert (paged.meta.count, paged.meta.total, paged.meta.limit, paged.meta.offset) == (1, 2, 1, 1)
    found = svc.referees(w.db, q="oliver", limit=10, offset=0).data
    assert len(found.items) == 2
    assert svc.referees(w.db, q="oliver", limit=10, offset=5).meta.offset == 0, "a search is not paged: it gives the best matches"
    one = svc.referees(w.db, q="Michael", limit=10, offset=0).data
    assert [r.name for r in one.items] == ["Michael Oliver"] and one.total == 1
    assert svc.referees(w.db, q="  zzz  ", limit=10, offset=0).data.items == []


def test_the_queue_shows_the_doubt_with_both_sides_and_what_it_touches(on_the_test_connection: World) -> None:
    w = on_the_test_connection
    ids = people(w)
    queue = svc.queue(w.db, status="open", reason=None, limit=50, offset=0).data
    assert queue.total == 1 and queue.status == "open"
    pair = queue.items[0]
    assert {pair.a.id, pair.b.id} == {ids["michael"], ids["dutch"]} and pair.status == "open"
    sides = {pair.a.id: pair.a, pair.b.id: pair.b}
    assert (sides[ids["michael"]].name, sides[ids["michael"]].matches, sides[ids["michael"]].country) == ("Michael Oliver", 2, "England")
    assert sides[ids["dutch"]].matches == 1 and sides[ids["dutch"]].country == "Netherlands"
    assert pair.impact >= 1 and pair.reason and isinstance(pair.evidence, dict)
    assert svc.queue(w.db, status="rejected", reason=None, limit=50, offset=0).data.total == 0
    nothing = svc.queue(w.db, status="open", reason="no-such-reason", limit=50, offset=0).data
    assert (nothing.items, nothing.total, nothing.reason) == ([], 0, "no-such-reason")
    assert svc.queue(w.db, status="open", reason=pair.reason, limit=50, offset=0).data.total == 1


def test_the_queue_total_is_the_whole_queue_and_a_page_is_a_part_of_it(on_the_test_connection: World) -> None:
    w = on_the_test_connection
    people(w)
    w.match("Spain", 22, "Michael Oliver")  # the same name in a third scope: more doubts
    store.build(w.db, apply=True)
    whole = svc.queue(w.db, status="open", reason=None, limit=50, offset=0).data
    assert whole.total >= 2 and len(whole.items) == whole.total
    first = svc.queue(w.db, status="open", reason=None, limit=1, offset=0)
    second = svc.queue(w.db, status="open", reason=None, limit=1, offset=1)
    assert first.data.total == second.data.total == whole.total and len(first.data.items) == len(second.data.items) == 1
    assert [first.data.items[0].id, second.data.items[0].id] == [p.id for p in whole.items[:2]], "the queue keeps its order from page to page"
    assert (first.meta.count, first.meta.total, first.meta.limit, first.meta.offset) == (1, whole.total, 1, 0)
    assert (second.meta.count, second.meta.offset) == (1, 1)
    reason = whole.items[0].reason
    only = svc.queue(w.db, status="open", reason=reason, limit=50, offset=0).data
    assert only.total == sum(1 for p in whole.items if p.reason == reason) and {p.reason for p in only.items} == {reason}


def test_a_referees_page_has_his_spellings_matches_doubts_and_history(on_the_test_connection: World) -> None:
    w = on_the_test_connection
    ids = people(w)
    w.match("England", 3, "Michael Oliver", "England")  # a third match, the second under his full name
    store.build(w.db, apply=True)
    page = svc.referee(w.db, ids["michael"]).data
    assert (page.referee.id, page.referee.name, page.referee.matches) == (ids["michael"], "Michael Oliver", 3)
    assert [(a.display, a.matches) for a in page.aliases] == [("Michael Oliver", 2), ("M. Oliver", 1)], "the busiest spelling first"
    seen = {a.display: (a.name_key, a.country, a.first, a.last) for a in page.aliases}
    assert seen == {"Michael Oliver": ("michael oliver", "England", T0 + timedelta(days=1, hours=3), T0 + timedelta(days=3, hours=3)),
                    "M. Oliver": ("m oliver", "England", T0 + timedelta(days=8, hours=3), T0 + timedelta(days=8, hours=3))}
    assert {a.basis for a in page.aliases} == {"identity", "initial"} and all(a.placed_by == "rules" for a in page.aliases)
    assert [m.spelling for m in page.recent_matches] == ["M. Oliver", "Michael Oliver", "Michael Oliver"], "the newest match first"
    assert all(m.home and m.away and m.competition for m in page.recent_matches)
    assert [c.other.id for c in page.candidates] == [ids["dutch"]] and page.events == []
    with refused(404, "not_found"):
        svc.referee(w.db, 999_999)


# ── decisions ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_merge_is_reversible_and_leaves_who_did_it(on_the_test_connection: World) -> None:
    w = on_the_test_connection
    ids = people(w)
    from fbi.api.contracts.referees import MergeIn

    merged = svc.merge(ids["michael"], MergeIn(merge_id=ids["dutch"], note="the same man"), actor=f"admin:{OWNER}").data
    assert merged.action == "merge" and merged.event_id is not None and (merged.referee_id, merged.other_id) == (ids["michael"], ids["dutch"])
    assert merged.referee.matches == 3 and merged.referee.name == "Michael Oliver"
    assert wrote(w, merged) == ("merge", ids["michael"], ids["dutch"])
    kept = svc.referee(w.db, ids["michael"]).data
    assert [(e.action, e.actor, e.referee_id, e.other_id) for e in kept.events] == [("merge", f"admin:{OWNER}", ids["michael"], ids["dutch"])]
    assert kept.events[0].detail["note"] == "the same man" and kept.events[0].undone_by is None
    assert kept.events[0].alias_ids == [w.alias("m oliver", "netherlands")], "the event keeps the spellings it moved"
    gone = svc.referee(w.db, ids["dutch"]).data.referee
    assert (gone.status, gone.merged_into, gone.matches) == ("merged", ids["michael"], 0)
    assert svc.queue(w.db, status="open", reason=None, limit=50, offset=0).data.total == 0
    done = svc.queue(w.db, status="merged", reason=None, limit=50, offset=0).data
    assert done.total == 1 and (done.items[0].status, done.items[0].decided_by) == ("merged", f"admin:{OWNER}") and done.items[0].decided_at
    listed = svc.referees(w.db, q=None, limit=10, offset=0).data
    assert [r.id for r in listed.items] == [ids["michael"]] and listed.total == 1, "a merged referee leaves the list"
    c = listed.counts
    assert (c.referees_active, c.referees_merged, c.candidates_open, c.candidates_merged, c.candidates_rejected) == (1, 1, 0, 1, 0)
    assert (c.matches_with_a_doubt, c.settled_share, c.problems) == (0, 1.0, [])

    undone = svc.undo(merged.event_id, actor=f"admin:{OWNER}").data
    assert undone.action == "undo" and (undone.referee_id, undone.other_id) == (ids["michael"], ids["dutch"])
    assert undone.referee.matches == 2 and wrote(w, undone) == ("undo", ids["michael"], ids["dutch"])
    assert svc.referee(w.db, ids["dutch"]).data.referee.status == "active"
    events = {e.action: e for e in svc.referee(w.db, ids["michael"]).data.events}
    assert set(events) == {"merge", "undo"} and events["undo"].undone_by is None
    assert events["merge"].undone_by == events["undo"].id
    assert svc.queue(w.db, status="rejected", reason=None, limit=50, offset=0).data.total == 1, "an undone merge is not suggested again"
    c = svc.referees(w.db, q=None, limit=10, offset=0).data.counts
    assert (c.referees_active, c.referees_merged, c.candidates_open, c.candidates_merged, c.candidates_rejected) == (2, 0, 0, 0, 1)


def test_two_men_at_the_same_time_cannot_be_merged_unless_forced(on_the_test_connection: World) -> None:
    from fbi.api.contracts.referees import MergeIn

    w = on_the_test_connection
    a = w.match("England", 40, "Alan Whistle", "England", hour=15)
    b = w.match("England", 40, "Bruno Whistle", "England", hour=15)  # the same afternoon: not the same man
    store.build(w.db, apply=True)
    ra, rb = w.referee_of(a), w.referee_of(b)
    assert ra is not None and rb is not None and ra != rb
    with refused(409, "collision"):
        svc.merge(ra, MergeIn(merge_id=rb), actor=f"admin:{OWNER}")
    forced = svc.merge(ra, MergeIn(merge_id=rb, force=True), actor=f"admin:{OWNER}").data
    assert forced.referee.matches == 2


def test_what_the_store_refuses_the_api_refuses_with_its_status(on_the_test_connection: World) -> None:
    from fbi.api.contracts.referees import MergeIn, PairIn, RenameIn, SplitIn

    w = on_the_test_connection
    ids = people(w)
    actor = f"admin:{OWNER}"
    with refused(422, "invalid"):
        svc.merge(ids["michael"], MergeIn(merge_id=ids["michael"]), actor=actor)
    with refused(404, "not_found"):
        svc.merge(ids["michael"], MergeIn(merge_id=999_999), actor=actor)
    with refused(404, "not_found"):
        svc.undo(999_999, actor=actor)
    with refused(422, "invalid"):
        svc.reject(ids["michael"], PairIn(other_id=ids["michael"]), actor=actor)
    with refused(404, "not_found"):
        svc.reopen(ids["michael"], PairIn(other_id=ids["dutch"]), actor=actor)  # nothing rejected yet
    with refused(422, "invalid"):
        svc.rename(ids["michael"], RenameIn(name="   "), actor=actor)
    with refused(422, "invalid"):
        svc.split(ids["dutch"], SplitIn(alias_ids=[w.alias("m oliver", "netherlands")]), actor=actor)  # the only spelling he has
    first = svc.merge(ids["michael"], MergeIn(merge_id=ids["dutch"]), actor=actor).data
    assert first.event_id is not None
    svc.undo(first.event_id, actor=actor)
    with refused(409, "conflict"):
        svc.undo(first.event_id, actor=actor)  # already undone


def test_a_split_makes_a_new_person_and_a_rejection_and_its_reopening_move_the_pair(on_the_test_connection: World) -> None:
    from fbi.api.contracts.referees import MergeIn, PairIn, SplitIn

    w = on_the_test_connection
    ids = people(w)
    actor = f"admin:{OWNER}"
    svc.merge(ids["michael"], MergeIn(merge_id=ids["dutch"]), actor=actor)
    split = svc.split(ids["michael"], SplitIn(alias_ids=[w.alias("m oliver", "netherlands")], name="Marc Oliver", note="two men"),
                     actor=actor).data
    assert split.action == "split" and split.referee.id != ids["michael"] and split.other_id == ids["michael"]
    assert (split.referee.name, split.referee.name_locked, split.referee.matches) == ("Marc Oliver", True, 1)
    assert wrote(w, split) == ("split", ids["michael"], split.referee.id)
    assert svc.referee(w.db, split.referee.id).data.events[0].detail["note"] == "two men"
    pair = (min(ids["michael"], split.referee.id), max(ids["michael"], split.referee.id))
    assert svc.referee(w.db, ids["michael"]).data.referee.matches == 2

    rejected = svc.queue(w.db, status="rejected", reason=None, limit=50, offset=0).data
    assert rejected.total >= 1 and all(p.status == "rejected" for p in rejected.items)
    again = svc.reopen(ids["michael"], PairIn(other_id=split.referee.id), actor=actor).data
    assert again.action == "reopen" and wrote(w, again) == ("reopen", *pair)
    assert (again.referee_id, again.other_id) == (ids["michael"], split.referee.id)
    assert svc.queue(w.db, status="open", reason=None, limit=50, offset=0).data.total == 1
    out = svc.reject(ids["michael"], PairIn(other_id=split.referee.id, note="still two men"), actor=actor).data
    assert out.action == "reject" and wrote(w, out) == ("reject", *pair)
    assert (out.referee_id, out.other_id) == (ids["michael"], split.referee.id)
    assert svc.referee(w.db, ids["michael"]).data.events[0].detail["note"] == "still two men"
    assert svc.queue(w.db, status="open", reason=None, limit=50, offset=0).data.total == 0


def test_a_rename_is_kept_and_giving_the_name_back_to_the_rules_restores_it(on_the_test_connection: World) -> None:
    from fbi.api.contracts.referees import RenameIn

    w = on_the_test_connection
    ids = people(w)
    actor = f"admin:{OWNER}"
    named = svc.rename(ids["michael"], RenameIn(name="Michael L. Oliver"), actor=actor).data
    assert (named.referee.name, named.referee.name_locked, named.action) == ("Michael L. Oliver", True, "rename")
    assert wrote(w, named) == ("rename", ids["michael"], None) and (named.referee_id, named.other_id) == (ids["michael"], None)
    store.build(w.db, apply=True)
    assert svc.referee(w.db, ids["michael"]).data.referee.name == "Michael L. Oliver", "the pass keeps an owner's name"
    back = svc.rename(ids["michael"], RenameIn(name=None), actor=actor).data
    assert (back.referee.name, back.referee.name_locked) == ("Michael Oliver", False) and wrote(w, back) == ("rename", ids["michael"], None)
    assert [e.action for e in svc.referee(w.db, ids["michael"]).data.events] == ["rename", "rename"]


@pytest.mark.parametrize("error", [errors.LockNotAvailable, errors.QueryCanceled])
def test_a_pass_that_is_writing_makes_the_decision_wait_and_then_say_so(on_the_test_connection: World, monkeypatch: pytest.MonkeyPatch,
                                                                       error: type[Exception]) -> None:
    """The lock the pass holds (``lock timeout``) and the statement that took too long (``statement timeout``) are both the same
    answer: try again in a minute."""
    from fbi.api.contracts.referees import MergeIn

    w = on_the_test_connection
    ids = people(w)

    def busy(*_: Any, **__: Any) -> int:
        raise error("canceling statement")

    monkeypatch.setattr(store, "merge", busy)
    with refused(409, "busy"):
        svc.merge(ids["michael"], MergeIn(merge_id=ids["dutch"]), actor=f"admin:{OWNER}")


def test_a_scope_is_shown_as_a_country_even_if_the_list_does_not_know_it_and_as_nothing_when_there_is_none(
        on_the_test_connection: World) -> None:
    w = on_the_test_connection
    league = scalar(w.db.execute(
        "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, country) "
        "VALUES (990001, 'Zedland league', 'league', 'club', 'domestic_league', 'Zedland') RETURNING id"))
    w.seasons["Zedland"] = int(scalar(w.db.execute(
        "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (league,))))
    far = w.match("Zedland", 20, "Pat Zed")  # a country the list of countries has not heard of: still a scope (its plain name)
    nowhere = w.match("World", 21, "Ana Nobody")  # a continental cup says no country
    store.build(w.db, apply=True)
    a, b = w.referee_of(far), w.referee_of(nowhere)
    assert a is not None and b is not None
    near = svc.referee(w.db, a).data
    assert [x.country for x in near.aliases] == ["Zedland"] and near.referee.country == "Zedland"
    lost = svc.referee(w.db, b).data
    assert [x.country for x in lost.aliases] == [None] and lost.referee.country is None


def test_a_broken_invariant_is_named_in_the_problems_of_the_list(on_the_test_connection: World) -> None:
    w = on_the_test_connection
    ids = people(w)
    assert svc.referees(w.db, q=None, limit=10, offset=0).data.counts.problems == []
    # a merged referee that still holds his spellings and a doubt, and an active one with no spelling at all
    w.db.execute("UPDATE core.referees SET status = 'merged', merged_into = %s WHERE id = %s", (ids["michael"], ids["dutch"]))
    w.db.execute("INSERT INTO core.referees (name, name_key, origin, version) VALUES ('Bare', 'bare', 'manual', 'test')")
    problems = svc.referees(w.db, q=None, limit=10, offset=0).data.counts.problems
    assert problems == ["aliases_on_merged_referee", "active_without_alias", "candidates_on_merged_referee"]


# ── over HTTP ────────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def env(migrated_database: str, seed: Seed) -> Iterator[Seed]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    yield seed
    mp.undo()
    reset_cache()


def client_for(role: str, *, headers: dict[str, str] | None = SAME_SITE) -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.security import optional_principal

    app = create_app()
    who = dataclasses.replace(principal(role, user_id=1))
    app.dependency_overrides[optional_principal] = lambda: who
    return TestClient(app, headers=headers or {})


def test_the_owner_reads_the_list_the_queue_and_a_page_and_a_missing_one_is_404(env: Seed) -> None:
    admin = client_for("SUPER_ADMIN")
    listed = admin.get("/api/v1/admin/referees")
    assert listed.status_code == 200, listed.text[:300]
    data = listed.json()["data"]
    assert {"items", "total", "queue_open", "counts"} <= set(data) and "problems" in data["counts"]
    assert admin.get("/api/v1/admin/referees?q=oliver&limit=5").status_code == 200
    queue = admin.get("/api/v1/admin/referees/queue?status=open")
    assert queue.status_code == 200 and queue.json()["data"]["status"] == "open"
    assert admin.get("/api/v1/admin/referees/queue?status=nonsense").status_code == 422
    assert admin.get("/api/v1/admin/referees/queue").json()["data"]["status"] == "open", "the queue is the open doubts unless asked otherwise"
    for bad in ("limit=0", "limit=201", "offset=-1", "offset=100001", "q=" + "x" * 81):
        assert admin.get(f"/api/v1/admin/referees?{bad}").status_code == 422, bad
    for bad in ("limit=0", "limit=201", "offset=-1", "offset=100001", "reason=" + "x" * 41):
        assert admin.get(f"/api/v1/admin/referees/queue?{bad}").status_code == 422, bad
    assert admin.get("/api/v1/admin/referees?limit=200&offset=100000").status_code == 200
    missing = admin.get("/api/v1/admin/referees/999999999")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def test_the_decisions_over_http_are_refused_in_the_api_s_own_words(env: Seed) -> None:
    admin = client_for("SUPER_ADMIN")
    itself = admin.post("/api/v1/admin/referees/5/merge", json={"merge_id": 5})
    assert itself.status_code == 422 and itself.json()["error"]["code"] == "invalid"
    nobody = admin.post("/api/v1/admin/referees/999999998/merge", json={"merge_id": 999999999})
    assert nobody.status_code == 404 and nobody.json()["error"]["code"] == "not_found"
    event = admin.post("/api/v1/admin/referees/events/999999999/undo")
    assert event.status_code == 404
    assert admin.post("/api/v1/admin/referees/1/merge", json={}).status_code == 422, "the body names who is merged"
    assert admin.post("/api/v1/admin/referees/1/split", json={"alias_ids": []}).status_code == 422
    assert admin.post("/api/v1/admin/referees/1/rename", json={"name": "x" * 500}).status_code == 422
    assert admin.post("/api/v1/admin/referees/1/reject", json={"other_id": 0}).status_code == 422
    assert admin.post("/api/v1/admin/referees/0/rename", json={"name": "x"}).status_code == 422, "an id starts at 1"
    assert admin.get("/api/v1/admin/referees/99999999999999999999").status_code == 422, "an id that does not fit the database is refused"


def test_a_decision_needs_the_same_site_header_and_a_user_reaches_none_of_it(env: Seed) -> None:
    open_client = client_for("SUPER_ADMIN", headers=None)
    r = open_client.post("/api/v1/admin/referees/1/rename", json={"name": "Nobody"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    user = client_for("USER")
    for method, path in (("get", "/api/v1/admin/referees"), ("get", "/api/v1/admin/referees/queue"), ("get", "/api/v1/admin/referees/1"),
                         ("post", "/api/v1/admin/referees/1/merge"), ("post", "/api/v1/admin/referees/events/1/undo"),
                         ("post", "/api/v1/admin/referees/1/split"), ("post", "/api/v1/admin/referees/1/reject"),
                         ("post", "/api/v1/admin/referees/1/reopen"), ("post", "/api/v1/admin/referees/1/rename")):
        got = user.request(method.upper(), path, json={} if method == "post" else None)
        assert got.status_code in (401, 403), (method, path, got.status_code)


@pytest.fixture()
def stored(migrated_database: str, seed: Seed) -> Iterator[dict[str, int]]:
    """Two referees written for good (a connection of their own, autocommit) - the way the pass writes them - and removed with
    everything a decision wrote about them once the test is over."""
    ids: list[int] = []
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for name in ("Zz Probe Alpha", "Zz Probe Beta"):
            key = name.lower()
            row = conn.execute("INSERT INTO core.referees (name, name_key, country_key, origin, version) "
                               "VALUES (%s, %s, 'england', 'rules', 'probe') RETURNING id", (name, key)).fetchone()
            assert row is not None
            ids.append(int(row[0]))
            conn.execute("INSERT INTO core.referee_aliases (referee_id, name_key, scope, display, basis, placed_by, version) "
                         "VALUES (%s, %s, 'england', %s, 'identity', 'rules', 'probe')", (ids[-1], key, name))
    yield {"alpha": ids[0], "beta": ids[1]}
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM core.referee_events WHERE referee_id = ANY(%(ids)s) OR other_id = ANY(%(ids)s)", {"ids": ids})
        conn.execute("DELETE FROM core.referee_candidates WHERE referee_a = ANY(%(ids)s) OR referee_b = ANY(%(ids)s)", {"ids": ids})
        conn.execute("DELETE FROM core.referee_aliases WHERE name_key LIKE 'zz probe %'")
        conn.execute("DELETE FROM core.referees WHERE id = ANY(%s)", (ids,))


def row_of(url: str, sql: str, *args: Any) -> tuple[Any, ...] | None:
    """What a OTHER connection sees: only what was committed."""
    with psycopg.connect(url) as other:
        return other.execute(sql, args).fetchone()


def test_a_decision_over_http_is_committed_and_signed_by_who_took_it(env: Seed, stored: dict[str, int],
                                                                          migrated_database: str) -> None:
    alpha, beta = stored["alpha"], stored["beta"]
    admin = client_for("SUPER_ADMIN")
    done = admin.post(f"/api/v1/admin/referees/{alpha}/merge", json={"merge_id": beta, "note": "probe"})
    assert done.status_code == 200, done.text[:300]
    body = done.json()["data"]
    assert (body["action"], body["referee_id"], body["other_id"]) == ("merge", alpha, beta) and body["referee"]["name"] == "Zz Probe Alpha"
    event = body["event_id"]
    assert row_of(migrated_database, "SELECT status, merged_into FROM core.referees WHERE id = %s", beta) == ("merged", alpha)
    assert row_of(migrated_database, "SELECT actor, action FROM core.referee_events WHERE id = %s", event) == (
        "admin:super_admin@test.local", "merge"), "the decision carries the e-mail of the signed-in owner"

    page = admin.get(f"/api/v1/admin/referees/{alpha}").json()["data"]
    assert [a["display"] for a in page["aliases"]] == ["Zz Probe Alpha", "Zz Probe Beta"], "the read side sees what was committed"
    assert [e["id"] for e in page["events"]] == [event]

    undone = admin.post(f"/api/v1/admin/referees/events/{event}/undo")
    assert undone.status_code == 200 and undone.json()["data"]["action"] == "undo"
    assert row_of(migrated_database, "SELECT status FROM core.referees WHERE id = %s", beta) == ("active",)
    again = admin.post(f"/api/v1/admin/referees/events/{event}/undo")
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict"


def test_the_connection_of_a_decision_commits_what_went_well_and_undoes_what_did_not(env: Seed, stored: dict[str, int],
                                                                                    migrated_database: str) -> None:
    alpha = stored["alpha"]
    with svc.write() as conn:
        conn.execute("UPDATE core.referees SET name = 'Zz Probe Renamed' WHERE id = %s", (alpha,))  # opens a transaction of its own
    assert row_of(migrated_database, "SELECT name FROM core.referees WHERE id = %s", alpha) == ("Zz Probe Renamed",)
    with pytest.raises(RuntimeError, match="boom"), svc.write() as conn:
        conn.execute("UPDATE core.referees SET name = 'Zz Probe Lost' WHERE id = %s", (alpha,))
        raise RuntimeError("boom")
    assert row_of(migrated_database, "SELECT name FROM core.referees WHERE id = %s", alpha) == ("Zz Probe Renamed",)


def test_a_decision_that_is_refused_after_writing_leaves_nothing_behind(env: Seed, stored: dict[str, int], migrated_database: str,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    alpha = stored["alpha"]

    def writes_then_refuses(conn: psycopg.Connection[Any], *_: Any, **__: Any) -> int:
        conn.execute("UPDATE core.referees SET name = 'Changed On The Way' WHERE id = %s", (alpha,))
        raise store.ActionError("conflict", "no after all")

    monkeypatch.setattr(store, "merge", writes_then_refuses)
    refused_ = client_for("SUPER_ADMIN").post(f"/api/v1/admin/referees/{alpha}/merge", json={"merge_id": stored["beta"]})
    assert refused_.status_code == 409 and refused_.json()["error"]["code"] == "conflict"
    assert row_of(migrated_database, "SELECT name FROM core.referees WHERE id = %s", alpha) == ("Zz Probe Alpha",)


# ── with the API's own database role ─────────────────────────────────────────────────────────────────────────────────────


def test_every_decision_works_with_the_privileges_of_the_api_role(granted: str, on_the_test_connection: World) -> None:  # noqa: F811
    """The API connects as ``predigol_api``, which has no more than the grants of ``deploy/vps/db/grants.sql``: a decision that needs
    a privilege the file does not give would work in every test and fail in production."""
    from fbi.api.contracts.referees import MergeIn, PairIn, RenameIn, SplitIn

    w = on_the_test_connection
    ids = people(w)
    alias = w.alias("m oliver", "netherlands")
    actor = f"admin:{OWNER}"
    try:
        w.db.execute("SET LOCAL ROLE predigol_api")
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("the owner of the test cluster cannot SET ROLE to the API role")
    try:
        merged = svc.merge(ids["michael"], MergeIn(merge_id=ids["dutch"], note="same man"), actor=actor).data
        assert merged.event_id is not None
        svc.undo(merged.event_id, actor=actor)
        svc.merge(ids["michael"], MergeIn(merge_id=ids["dutch"]), actor=actor)
        created = svc.split(ids["michael"], SplitIn(alias_ids=[alias], name="Marc Oliver"), actor=actor).data
        svc.reopen(ids["michael"], PairIn(other_id=created.referee.id), actor=actor)
        svc.reject(ids["michael"], PairIn(other_id=created.referee.id), actor=actor)
        svc.rename(ids["michael"], RenameIn(name="Michael J. Oliver"), actor=actor)
        svc.rename(ids["michael"], RenameIn(name=None), actor=actor)
        assert svc.referees(w.db, q=None, limit=10, offset=0).data.total == 2
        assert svc.referee(w.db, ids["michael"]).data.events
        with pytest.raises(psycopg.errors.InsufficientPrivilege), w.db.transaction():
            w.db.execute("DELETE FROM core.referees WHERE id = %s", (created.referee.id,))
    finally:
        w.db.execute("RESET ROLE")
