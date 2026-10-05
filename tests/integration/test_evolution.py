"""GATE I: results become memory and proposals; only the owner decides; nothing changes a rule.
The library part runs in a rolled-back transaction; the HTTP part commits under a test owner
and removes what it wrote."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.core.config import reset_cache
from fbi.research.evolution import (
    DecisionError,
    decide,
    learn_from_audit,
    learn_from_v2,
    propose,
    remember,
)
from fbi.research.pick_audit import AuditResult
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_records_api import client_for

AT = datetime(2032, 9, 1, 12, tzinfo=UTC)


def _owner(db: psycopg.Connection[Any]) -> int:
    row = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                     "('owner-evolution@test.local', 'Owner', '$argon2id$x') RETURNING id").fetchone()
    assert row is not None
    return int(row[0])


def test_memory_is_superseded_never_overwritten(db: psycopg.Connection[Any], seed: Seed) -> None:
    first = remember(db, topic="t:x", finding="A", evidence={"n": 1}, source="audit", at=AT)
    assert first is not None
    assert remember(db, topic="t:x", finding="A", evidence={"n": 2}, source="audit", at=AT) is None, \
        "the same finding is not written twice"
    second = remember(db, topic="t:x", finding="B", evidence={"n": 3}, source="audit", at=AT + timedelta(days=1))
    rows = db.execute("SELECT id, finding, superseded_by FROM analytics.research_memory WHERE topic = 't:x' "
                      "ORDER BY id").fetchall()
    assert rows == [(first, "A", second), (second, "B", None)], "the old finding is kept, pointing at the new"
    with pytest.raises(ValueError):
        remember(db, topic="t:y", finding="C", evidence={}, source="the model's opinion", at=AT)


def test_only_the_owner_decides_and_only_once(db: psycopg.Connection[Any], seed: Seed) -> None:
    owner = _owner(db)
    key = propose(db, key="test:k1", title="A keyed proposal", hypothesis="h", rationale="r", evidence={},
                  proposed_by="system", at=AT)
    assert key is not None
    assert propose(db, key="test:k1", title="A keyed proposal", hypothesis="h", rationale="r", evidence={},
                   proposed_by="system", at=AT) is None, "the same evidence proposes once"
    ai = propose(db, title="An AI idea", hypothesis="h", rationale="r", evidence={}, proposed_by="ai", at=AT)
    assert ai is not None
    assert propose(db, title="an  AI idea", hypothesis="h2", rationale="r2", evidence={}, proposed_by="ai",
                   at=AT) is None, "the AI repeating itself is one proposal"
    assert decide(db, key, accept=True, user_id=owner, note="worth a look", at=AT) == "ACCEPTED"
    with pytest.raises(DecisionError, match="already ACCEPTED"):
        decide(db, key, accept=False, user_id=owner, note=None, at=AT)
    with pytest.raises(DecisionError, match="no such hypothesis"):
        decide(db, 2**40, accept=True, user_id=owner, note=None, at=AT)
    row = db.execute("SELECT status, decided_by, decision_note FROM analytics.research_hypotheses WHERE id = %s",
                     (key,)).fetchone()
    assert row == ("ACCEPTED", owner, "worth a look")


def _audit(ev_pick: float, se: float, minutes: float) -> AuditResult:
    overall = {"n": 925, "fixtures": 128, "roi": -0.223, "claimed_ev": 0.239, "ev_at_pick": ev_pick,
               "ev_at_pick_se": se, "movement": 0.0002, "ev_at_close": -0.047, "luck": -0.176, "luck_z": -1.0}
    return AuditResult(AT, [], overall, {}, {}, {}, {}, minutes)


def test_the_audit_becomes_memory_and_two_proposals_once(db: psycopg.Connection[Any], seed: Seed) -> None:
    first = learn_from_audit(db, _audit(-0.047, 0.0024, 719), at=AT)
    assert len(first.memory) == 1 and len(first.proposals) == 2
    titles = {r[0] for r in db.execute("SELECT dedup_key FROM analytics.research_hypotheses WHERE id = ANY(%s)",
                                       (first.proposals,)).fetchall()}
    assert titles == {"audit:price_only:v1", "audit:close_capture:v1"}
    again = learn_from_audit(db, _audit(-0.047, 0.0024, 719), at=AT + timedelta(days=1))
    assert again.memory == [] and again.proposals == [], "nothing new to say, nothing written"
    quiet = learn_from_audit(db, _audit(-0.001, 0.01, 30), at=AT + timedelta(days=2))
    assert quiet.proposals == [] and len(quiet.memory) == 1, "a new finding is remembered; no proposal without z"


def test_a_run_without_a_challenger_proposes_the_plan(db: psycopg.Connection[Any], seed: Seed) -> None:
    roles = {"poisson": ("REJECTED", "worse than the champion"), "elo_ologit": ("RESEARCH", "cannot tell")}
    learned = learn_from_v2(db, run="research-v2-test", champion="pinnacle/closing/power", roles=roles, at=AT)
    keys = {r[0] for r in db.execute("SELECT dedup_key FROM analytics.research_hypotheses WHERE id = ANY(%s)",
                                     (learned.proposals,)).fetchall()}
    assert keys == {"plan:E4:shots", "plan:E6:lineups", "plan:totals_history"}
    assert len(learned.memory) == 3, "the champion and each model's role"
    challenger = learn_from_v2(db, run="research-v2-test-2", champion="pinnacle/closing/power",
                               roles={"hgb": ("CHALLENGER", "beats the close")}, at=AT)
    keys = {r[0] for r in db.execute("SELECT dedup_key FROM analytics.research_hypotheses WHERE id = ANY(%s)",
                                     (challenger.proposals,)).fetchall()}
    assert keys == {"v2:challenger:hgb:research-v2-test-2"}, "a challenger is proposed for review, never promoted"
    assert db.execute("SELECT count(*) FROM analytics.experiments WHERE research_status = 'PRODUCTION'"
                      ).fetchone() == (0,)


@pytest.fixture()
def owner_api(migrated_database: str, seed: Seed) -> Iterator[tuple[TestClient, int]]:
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                    "('owner-api-evolution@test.local', 'Owner', '$argon2id$x') RETURNING id")
        user = scalar(cur)
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    yield client_for(user, role="SUPER_ADMIN"), user
    mp.undo()
    reset_cache()
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM analytics.research_hypotheses WHERE decided_by = %s OR title LIKE 'API test%%'",
                    (user,))
        cur.execute("DELETE FROM auth.users WHERE id = %s", (user,))


def test_the_owner_proposes_and_decides_over_http(owner_api: tuple[TestClient, int]) -> None:
    c, user = owner_api
    overview = c.get("/api/v1/admin/evolution").json()
    assert overview["status"] == "ok" and len(overview["data"]["loop"]) == 5
    assert overview["data"]["v2_due"] == "no research-V2 run is stored"
    assert overview["data"]["v2_due_code"] == "no_run" and overview["data"]["v2_due_vars"] == {}
    assert "research_frozen" in overview["data"], "frozen or not, the page is told (null when not frozen)"
    made = c.post("/api/v1/admin/evolution/hypotheses",
                  json={"title": "API test: a proposal", "hypothesis": "something", "rationale": "because"})
    assert made.status_code == 200, made.text
    hid = made.json()["data"]["id"]
    listed = {h["id"]: h for h in c.get("/api/v1/admin/evolution").json()["data"]["hypotheses"]}
    assert listed[hid]["status"] == "PROPOSED" and listed[hid]["proposed_by"] == "owner"
    ok = c.post(f"/api/v1/admin/evolution/hypotheses/{hid}/decision", json={"decision": "reject", "note": "no"})
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "REJECTED"
    again = c.post(f"/api/v1/admin/evolution/hypotheses/{hid}/decision", json={"decision": "accept"})
    assert again.status_code == 409
    assert c.post("/api/v1/admin/evolution/hypotheses/99999999/decision",
                  json={"decision": "accept"}).status_code == 404
    listed = {h["id"]: h for h in c.get("/api/v1/admin/evolution").json()["data"]["hypotheses"]}
    assert listed[hid]["decided_by"] == "owner-api-evolution@test.local"
    user_client = client_for(user, role="USER")
    assert user_client.get("/api/v1/admin/evolution").status_code == 403


def test_the_daily_monitor_commits_whole_and_records_its_run(migrated_database: str, seed: Seed) -> None:
    from fbi.research.loop import run_monitor, v2_due

    with psycopg.connect(migrated_database) as conn:
        r = run_monitor(conn, at=AT)
        run = conn.execute("SELECT status, notes FROM raw.ingestion_runs WHERE job_type = 'research_monitor' "
                           "ORDER BY id DESC LIMIT 1").fetchone()
        assert run is not None and run[0] == "completed" and "0 requests" in run[1]
        assert r.prospective_played >= 0 and r.settled_picks >= 0
        assert v2_due(conn, at=AT, version="abc") == "no research-V2 run is stored"
        conn.execute("DELETE FROM analytics.research_hypotheses WHERE id = ANY(%s)", (r.proposals,))
        conn.execute("UPDATE analytics.research_memory SET superseded_by = NULL WHERE superseded_by = ANY(%s)",
                     (r.memory,))
        conn.execute("DELETE FROM analytics.research_memory WHERE id = ANY(%s)", (r.memory,))
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'research_monitor'")
        conn.commit()
