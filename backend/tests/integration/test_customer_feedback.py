"""What readers think of PrediGol against the migrated database (plan UX, B6 and section 40), signed in for real.

* The monthly survey: never in the account's first week; owed to a reader who never answered; answered once (the comment without an address or a long number,
  the context only where it was asked) and then not owed for 30 days - neither answered again (409) nor skipped; closing it
  keeps it away for those 30 days too; owed again after them.
* «¿Te sirvió?»: one answer per reader and thing read, the last one counts; each reader has their own; the subjects and the
  daily ceiling refused.
* FBI_FEEDBACK=0: no survey and no vote (404), the answers stay.
* Novedades read: one mark, the newest entry, beside the reader's other hints.
* The owner's view (/admin/product/feedback) counts exactly what SQL written here counts - the survey's n, mean,
  distribution, low answers and skips, «¿Te sirvió?» per kind, the newest comments without who wrote them, the readers at
  risk - and a reader cannot open it.
* What the account keeps: the answers are in the reader's copy of their data and go when the account is anonymised;
  past 24 months the retention counts them (dry) or deletes them (on).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.auth import anonymize, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import feedback, privacy
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration

READER = "lectora.b6@example.org"
OTHER = "otro.b6@example.org"
OWNER = "owner.b6@predigol.test"
PASSWORD = "Calm-estuary-2026-long"  # gitleaks:allow - the password of the test accounts this module creates


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM customer.feedback")
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.messages_outbox", "customer.preferences", "customer.favorites",
                          "customer.ticket_messages", "customer.support_tickets", "customer.consents"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM picks.user_picks")
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users")


def since(dsn: str, *, days: int, email: str | None = None) -> None:
    """The accounts (or one) created ``days`` ago."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET created_at = now() - make_interval(days => %s) "
                     "WHERE %s::text IS NULL OR email = %s", (days, email, email))


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    reset_cache()
    reset_session_settings()
    wipe(migrated_database)
    for email, role in ((READER, "USER"), (OTHER, "USER"), (OWNER, "SUPER_ADMIN")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role=role, password=PASSWORD,
                                       language="es", timezone="America/Bogota")
    since(migrated_database, days=8)  # accounts past their first week: the survey can be owed to them
    yield migrated_database
    wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    throttle.reset_all()
    forget_sign_in_failures()
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DELETE FROM customer.feedback")
        conn.execute("UPDATE customer.preferences SET hints_seen = '{}'")
    monkeypatch.delenv(feedback.SWITCH, raising=False)
    yield database


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def uid(dsn: str, email: str) -> int:
    with psycopg.connect(dsn) as conn:
        return int(scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,))))


def code(r: Any) -> str:
    body = r.json()
    return str(body.get("error", {}).get("code") or body.get("code") or body.get("detail"))


def rows(dsn: str, user: int) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT kind, score, comment, subject, subject_id, helpful, context FROM customer.feedback "
                            "WHERE user_id = %s ORDER BY id", (user,)).fetchall()


def age(dsn: str, user: int, days: int) -> None:
    """The reader's answers moved ``days`` into the past (the 30 days of the rule, the 24 months of the retention)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("UPDATE customer.feedback SET created_at = created_at - make_interval(days => %s), "
                     "updated_at = updated_at - make_interval(days => %s) WHERE user_id = %s", (days, days, user))


# ── the survey ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_survey_is_owed_at_most_once_every_30_days(fresh: str) -> None:
    reader, me = client(READER), uid(fresh, READER)
    state = reader.get("/api/v1/me/feedback/survey").json()
    assert (state["enabled"], state["due"], state["last_at"], state["next_at"]) == (True, True, None, None)
    answered = reader.post("/api/v1/me/feedback/survey", json={
        "score": 4, "comment": "Muy útil la lectura; escríbanme a lectora@example.org o al 300 123 4567",
        "context": {"trigger": "analysis_opened", "route": "/matches/123?tab=analysis"}})
    assert answered.status_code == 201, answered.text
    assert rows(fresh, me) == [("csat", 4, f"Muy útil la lectura; escríbanme a {feedback.REMOVED} o al {feedback.REMOVED}",
                                None, None, None, {"trigger": "analysis_opened", "route": "/matches/123"})]
    state = reader.get("/api/v1/me/feedback/survey").json()
    assert state["due"] is False and state["last_at"] is not None
    assert datetime.fromisoformat(state["next_at"]) - datetime.fromisoformat(state["last_at"]) == timedelta(days=30)
    again = reader.post("/api/v1/me/feedback/survey", json={"score": 5})
    assert (again.status_code, code(again)) == (409, "survey_not_due"), "one answer per 30 days"
    assert reader.post("/api/v1/me/feedback/survey/skip", json={}).status_code == 204, "a skip when not owed: nothing"
    assert len(rows(fresh, me)) == 1
    age(fresh, me, 31)
    assert reader.get("/api/v1/me/feedback/survey").json()["due"] is True, "owed again after 30 days"
    skipped = reader.post("/api/v1/me/feedback/survey/skip", json={"context": {"trigger": "result_seen", "route": "/my-picks"}})
    assert skipped.status_code == 204
    assert rows(fresh, me)[-1] == ("csat_skipped", None, None, None, None, None,
                                   {"trigger": "result_seen", "route": "/my-picks"})
    assert reader.get("/api/v1/me/feedback/survey").json()["due"] is False, "closed: not again for 30 days"
    assert reader.post("/api/v1/me/feedback/survey", json={"score": 3}).status_code == 409
    for bad in ({"score": 0}, {"score": 6}, {"score": 3, "comment": "x" * 2001}, {"score": 3, "extra": 1},
                {"score": 3, "context": {"trigger": "login"}}):
        assert reader.post("/api/v1/me/feedback/survey", json=bad).status_code == 422, bad
    # each reader has their own month
    other = client(OTHER)
    assert other.get("/api/v1/me/feedback/survey").json()["due"] is True
    assert other.post("/api/v1/me/feedback/survey", json={"score": 2}).status_code == 201


def test_the_first_survey_waits_for_the_accounts_first_week(fresh: str) -> None:
    reader, me = client(READER), uid(fresh, READER)
    since(fresh, days=2, email=READER)
    try:
        state = reader.get("/api/v1/me/feedback/survey").json()
        assert (state["enabled"], state["due"], state["last_at"]) == (True, False, None)
        with psycopg.connect(fresh) as conn:
            created = scalar(conn.execute("SELECT created_at FROM auth.users WHERE id = %s", (me,)))
        assert datetime.fromisoformat(state["next_at"]) == created + feedback.FIRST_AFTER, "owed from its eighth day"
        refused = reader.post("/api/v1/me/feedback/survey", json={"score": 5})
        assert (refused.status_code, code(refused)) == (409, "survey_not_due")
        assert reader.post("/api/v1/me/feedback/survey/skip", json={}).status_code == 204
        assert rows(fresh, me) == [], "neither an answer nor a close in the first week"
        since(fresh, days=7, email=READER)
        assert reader.get("/api/v1/me/feedback/survey").json()["due"] is True, "the first week is over"
    finally:
        since(fresh, days=8, email=READER)


# ── «¿Te sirvió?» ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_one_answer_per_reader_and_thing_read_the_last_one_counts(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reader, other, me = client(READER), client(OTHER), uid(fresh, READER)
    url = "/api/v1/me/feedback/helpful"
    assert reader.get(url, params={"subject": "reading", "subject_id": 42}).json() == {
        "subject": "reading", "subject_id": 42, "helpful": None}
    yes = reader.put(url, json={"subject": "reading", "subject_id": 42, "helpful": True,
                                "context": {"route": "/matches/42"}})
    assert yes.status_code == 200 and yes.json()["helpful"] is True
    no = reader.put(url, json={"subject": "reading", "subject_id": 42, "helpful": False})
    assert no.json()["helpful"] is False
    assert reader.get(url, params={"subject": "reading", "subject_id": 42}).json()["helpful"] is False, "the last counts"
    assert reader.put(url, json={"subject": "explanation", "subject_id": 9, "helpful": True}).status_code == 200
    assert [(r[0], r[3], r[4], r[5]) for r in rows(fresh, me)] == [("helpful", "reading", 42, False),
                                                                   ("helpful", "explanation", 9, True)]
    assert other.get(url, params={"subject": "reading", "subject_id": 42}).json()["helpful"] is None, "their own"
    for bad in ({"subject": "rumour", "subject_id": 1, "helpful": True}, {"subject": "reading", "subject_id": 0,
                                                                           "helpful": True},
                {"subject": "reading", "subject_id": 1}):
        assert reader.put(url, json=bad).status_code == 422, bad
    monkeypatch.setattr(feedback, "VOTES_PER_DAY", 3)
    assert reader.put(url, json={"subject": "narrative", "subject_id": 5, "helpful": True}).status_code == 200
    ceiling = reader.put(url, json={"subject": "narrative", "subject_id": 6, "helpful": True})
    assert (ceiling.status_code, code(ceiling)) == (429, "too_many_votes"), "three answers today: no more until tomorrow"


def test_with_feedback_off_there_is_no_survey_and_no_vote_and_the_answers_stay(fresh: str,
                                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    reader, me = client(READER), uid(fresh, READER)
    assert reader.put("/api/v1/me/feedback/helpful", json={"subject": "reading", "subject_id": 1,
                                                           "helpful": True}).status_code == 200
    monkeypatch.setenv(feedback.SWITCH, "0")
    state = reader.get("/api/v1/me/feedback/survey").json()
    assert (state["enabled"], state["due"]) == (False, False)
    off = reader.post("/api/v1/me/feedback/survey", json={"score": 5})
    assert (off.status_code, code(off)) == (404, "feedback_off")
    vote = reader.put("/api/v1/me/feedback/helpful", json={"subject": "reading", "subject_id": 2, "helpful": True})
    assert (vote.status_code, code(vote)) == (404, "feedback_off")
    assert reader.post("/api/v1/me/feedback/survey/skip", json={}).status_code == 204
    assert len(rows(fresh, me)) == 1, "the answer given before stays"


# ── Novedades ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_novedades_read_is_one_mark_beside_the_readers_other_hints(fresh: str) -> None:
    reader, me = client(READER), uid(fresh, READER)
    assert reader.get("/api/v1/me/updates/seen").json() == {"last_seen": None}
    assert reader.post("/api/v1/me/hints", json={"hint": "picks"}).status_code == 200
    first = reader.post("/api/v1/me/updates/seen", json={"id": "2026-10-27-mis-picks"})
    assert first.status_code == 200 and first.json() == {"last_seen": "2026-10-27-mis-picks"}
    assert reader.post("/api/v1/me/updates/seen", json={"id": "2026-10-27-mis-picks"}).status_code == 200, "idempotent"
    assert reader.post("/api/v1/me/updates/seen", json={"id": "2026-11-02-novedades"}).json()["last_seen"] == (
        "2026-11-02-novedades")
    with psycopg.connect(fresh) as conn:
        seen = scalar(conn.execute("SELECT hints_seen FROM customer.preferences WHERE user_id = %s", (me,)))
    assert seen == ["picks", "updates:2026-11-02-novedades"], "one mark, the newest, beside the hint"
    assert reader.get("/api/v1/me/updates/seen").json() == {"last_seen": "2026-11-02-novedades"}
    wrong = reader.post("/api/v1/me/updates/seen", json={"id": "no-es-una-entrada"})
    assert (wrong.status_code, code(wrong)) == (422, "unknown_update")
    assert reader.post("/api/v1/me/updates/seen", json={"id": "2026"}).status_code == 422
    assert client(OTHER).get("/api/v1/me/updates/seen").json() == {"last_seen": None}, "each reader their own"


# ── the owner's view ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_owners_view_counts_what_sql_counts_and_never_says_who(fresh: str) -> None:
    me, them = uid(fresh, READER), uid(fresh, OTHER)
    now = datetime.now(UTC)
    with psycopg.connect(fresh, autocommit=True) as conn:
        insert = ("INSERT INTO customer.feedback (user_id, kind, score, comment, subject, subject_id, helpful, context, "
                  "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)")
        for user, kind, score, comment, subject, sid, helpful, ctx, days in (
                (me, "csat", 5, "Lo más útil: el Postpartido", None, None, None, '{"trigger": "result_seen"}', 80),
                (me, "csat", 2, "Faltó la Liga BetPlay", None, None, None, '{"trigger": "analysis_opened"}', 10),
                (them, "csat", 4, None, None, None, None, "{}", 5),
                (them, "csat", 1, "nada", None, None, None, "{}", 100),  # outside the 90 days
                (them, "csat_skipped", None, None, None, None, None, "{}", 40),
                (me, "helpful", None, None, "reading", 1, True, "{}", 3),
                (them, "helpful", None, None, "reading", 1, False, "{}", 3),
                (them, "helpful", None, None, "narrative", 2, True, "{}", 2),
                (me, "helpful", None, None, "explanation", 3, True, "{}", 120)):  # outside the 90 days
            at = now - timedelta(days=days)
            conn.execute(insert, (user, kind, score, comment, subject, sid, helpful, ctx, at, at))
        since = now - timedelta(days=90)
        found = conn.execute(
            "SELECT count(*), round(avg(score), 2), count(*) FILTER (WHERE score <= 2) FROM customer.feedback "
            "WHERE kind = 'csat' AND created_at >= %s", (since,)).fetchone()
        assert found is not None
        sql_n, sql_mean, sql_low = found
        sql_skipped = scalar(conn.execute("SELECT count(*) FROM customer.feedback WHERE kind = 'csat_skipped' "
                                          "AND created_at >= %s", (since,)))
    assert client(READER).get("/api/v1/admin/product/feedback").status_code == 403, "a reader cannot open it"
    view = client(OWNER).get("/api/v1/admin/product/feedback").json()
    s = view["survey"]
    assert (s["n"], s["mean"], s["low"], s["skipped"]) == (sql_n, float(sql_mean), sql_low, sql_skipped) == (3, 3.67, 1, 1)
    assert s["scores"] == {"1": 0, "2": 1, "3": 0, "4": 1, "5": 1}
    assert view["votes"] == [{"subject": "reading", "yes": 1, "no": 1}, {"subject": "narrative", "yes": 1, "no": 0},
                             {"subject": "explanation", "yes": 0, "no": 0}, {"subject": "explain", "yes": 0, "no": 0}]
    assert [(c["score"], c["comment"], c["trigger"]) for c in view["comments"]] == [
        (2, "Faltó la Liga BetPlay", "analysis_opened"), (5, "Lo más útil: el Postpartido", "result_seen")]
    assert all(set(c) == {"at", "score", "comment", "trigger"} for c in view["comments"]), "never who wrote it"
    assert view["at_risk"] == 1, "the reader whose last survey of the 30 days is a 2 (the other's 4 is not)"
    with psycopg.connect(fresh) as conn:
        assert feedback.at_risk(conn, at=now) == [me]
    longer = client(OWNER).get("/api/v1/admin/product/feedback", params={"days": 365}).json()
    assert longer["survey"]["n"] == 4 and longer["survey"]["scores"]["1"] == 1


# ── what the account keeps ────────────────────────────────────────────────────────────────────────────────────────────


def test_the_answers_go_with_the_anonymised_account_and_past_24_months(fresh: str) -> None:
    reader, other = client(READER), client(OTHER)
    me, them, owner = uid(fresh, READER), uid(fresh, OTHER), uid(fresh, OWNER)
    assert reader.post("/api/v1/me/feedback/survey", json={"score": 5, "comment": "Gracias"}).status_code == 201
    assert other.post("/api/v1/me/feedback/survey", json={"score": 3}).status_code == 201
    assert other.put("/api/v1/me/feedback/helpful", json={"subject": "reading", "subject_id": 7,
                                                          "helpful": True}).status_code == 200
    # retention: dry counts, on deletes, off does nothing - only what is past its 24 months
    age(fresh, them, 731)
    with psycopg.connect(fresh) as conn:
        assert feedback.purge(conn, at=datetime.now(UTC), mode="off") == feedback.PurgeReport("off", 0)
        assert feedback.purge(conn, at=datetime.now(UTC), mode="dry") == feedback.PurgeReport("dry", 2)
        assert feedback.purge(conn, at=datetime.now(UTC), mode="on") == feedback.PurgeReport("on", 2)
        conn.commit()
    assert rows(fresh, them) == [] and len(rows(fresh, me)) == 1, "only the old answers went"
    # the reader's copy of their data carries their answers (A4) and no one else's
    with psycopg.connect(fresh) as conn:
        mine = privacy.export(conn, me)["feedback"]
    assert [(x["kind"], x["score"], x["comment"], x["helpful"]) for x in mine] == [("csat", 5, "Gracias", None)]
    # the account anonymised at its reader's request: its answers go with what it keeps
    anonymize.anonymise(principal("SUPER_ADMIN", user_id=owner), me, confirm=READER, ip=None)
    assert rows(fresh, me) == []
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET email = %s, status = 'active' WHERE id = %s", (READER, me))
        conn.execute("UPDATE auth.users SET password_hash = (SELECT password_hash FROM auth.users WHERE id = %s) "
                     "WHERE id = %s", (them, me))  # the module's next tests sign in as the reader again
