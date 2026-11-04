"""What the Learning Analyst's database role may write (Plan Maestro IA, phase 5; sections 13 and 25): hypotheses, and never a promotion.

The analyst proposes; the owner promotes. The plan's answer to "what if the analyst is mistaken or manipulated" is not a rule in a prompt: the role
the hypotheses are written as has no privilege on ``intel.promotions`` and the table's row policy (migration 0111) refuses an agent promotion to anyone
but the owner. The roles are the ones the server has (``db/roles.sql`` and ``db/grants.sql`` run as the operator runs them); each test acts as a role and shows
what it may and may not write.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.agents import analyst
from fbi.ai.contracts import learning
from tests.integration.agent_tables import HASH, refuses
from tests.integration.helpers import scalar

DEPLOY_DB = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "db"
ROLE = analyst.ROLE
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


@pytest.fixture(scope="module")
def cluster(migrated_database: str) -> Iterator[str]:
    """The roles of the server, made as the operator makes them: the two the initial script creates, then db/roles.sql, then db/grants.sql."""
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        me = conn.execute("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
        assert me is not None
        if me[0] != "fbi" or not me[1]:
            pytest.skip("the roles are made and impersonated by the cluster's superuser 'fbi', as on the test machine")
        for role in ("predigol_worker", "predigol_api"):
            conn.execute(f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
        conn.execute((DEPLOY_DB / "roles.sql").read_text())
        conn.execute((DEPLOY_DB / "grants.sql").read_text())
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for role in (ROLE, "predigol_rollback", "predigol_worker", "predigol_api"):
            conn.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
                         f"EXECUTE 'DROP OWNED BY {role}'; EXECUTE 'DROP ROLE {role}'; END IF; END $$")


@contextmanager
def logged_in_as(db: psycopg.Connection[Any], user: str, *, then_set: str | None = None) -> Iterator[None]:
    """The statements inside run as ``user`` - what a login of that role would be - and, if asked, after SET ROLE ``then_set``."""
    db.execute(f"SET SESSION AUTHORIZATION {user}")
    if then_set is not None:
        db.execute(f"SET ROLE {then_set}")
    assert db.execute("SELECT current_user").fetchone() == (then_set or user,)
    try:
        yield
    finally:
        db.execute("RESET ROLE")
        db.execute("RESET SESSION AUTHORIZATION")


def promotion(**over: Any) -> dict[str, Any]:
    """An agent promotion as the owner signs it."""
    values: dict[str, Any] = {
        "at": NOW - timedelta(hours=48), "entity": "agent", "market_key": "1X2", "model_name": "council@council-v1+match-v1", "entity_id": None,
        "from_role": None, "to_role": "CHAMPION", "gate_version": "ma-gate-v1", "criteria": Jsonb({"report_hash": HASH, "families": ["1X2"]}),
        "reason": "passed the gate", "decided_by": "owner"}
    return values | over


def promote(db: psycopg.Connection[Any], **over: Any) -> None:
    v = promotion(**over)
    db.execute(f"INSERT INTO intel.promotions ({', '.join(v)}) VALUES ({', '.join(['%s'] * len(v))})", list(v.values()))


def a_hypothesis(**over: Any) -> learning.Hypothesis:
    body: dict[str, Any] = {
        "title": "the Council over-trusts MARKET_MOVE", "hypothesis": "h", "rationale": "r", "agent": "council", "agent_version": "council-v1",
        "attribution_ids": [1], "experiment": {"design": "SHADOW_ARM", "metric": "CLV", "family": "1X2", "varies": "PROMPT", "required_sample": 300}}
    return learning.Hypothesis.model_validate(body | over)


# -- the role the scripts make -----------------------------------------------------------------------------------------------------

def test_the_role_logs_in_nowhere_and_bypasses_nothing(db: psycopg.Connection[Any], cluster: str) -> None:
    flags = db.execute("SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
                       (ROLE,)).fetchone()
    assert flags == (False, False, False, False, False, False)


def test_only_the_worker_can_become_it_and_it_inherits_nothing_for_that(db: psycopg.Connection[Any], cluster: str) -> None:
    members = db.execute("SELECT m.rolname, a.inherit_option, a.set_option, a.admin_option FROM pg_auth_members a "
                         "JOIN pg_roles r ON r.oid = a.roleid JOIN pg_roles m ON m.oid = a.member WHERE r.rolname = %s ORDER BY 1", (ROLE,)).fetchall()
    assert members == [("predigol_worker", False, True, False)]
    can = db.execute("SELECT pg_has_role('predigol_worker', %s, 'SET'), pg_has_role('predigol_worker', %s, 'USAGE'), "
                     "pg_has_role('predigol_api', %s, 'SET'), pg_has_role('predigol_api', %s, 'MEMBER')", (ROLE,) * 4).fetchone()
    assert can == (True, False, False, False)


def test_the_role_reaches_one_table_with_two_privileges_and_nothing_else_anywhere(db: psycopg.Connection[Any], cluster: str) -> None:
    reached = db.execute("""
        SELECT n.nspname || '.' || c.relname || ':' || c.relkind::text
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public')
           AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege(%s, c.oid, 'USAGE,SELECT,UPDATE')
                    ELSE has_table_privilege(%s, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') END
         ORDER BY 1""", (ROLE, ROLE)).fetchall()
    assert reached == [("analytics.research_hypotheses:r",), ("analytics.research_hypotheses_id_seq:S",)]
    held = {p for p in PRIVILEGES if scalar(db.execute("SELECT has_table_privilege(%s, 'analytics.research_hypotheses', %s)", (ROLE, p)))}
    assert held == {"SELECT", "INSERT"}
    for table in ("intel.promotions", "intel.agent_attributions", "analytics.experiments", "picks.picks"):
        assert not [p for p in PRIVILEGES if scalar(db.execute("SELECT has_table_privilege(%s, %s, %s)", (ROLE, table, p)))], table
    schemas = db.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%%' AND nspname NOT IN ('information_schema', 'public') "
                         "AND has_schema_privilege(%s, oid, 'USAGE') ORDER BY 1", (ROLE,)).fetchall()
    assert schemas == [("analytics",)], "the role cannot even name a table of intel"


# -- what the role cannot do --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("statement", [
    "INSERT INTO intel.promotions (at, entity, to_role, gate_version, criteria, reason, decided_by) VALUES (now(), 'model', 'CHAMPION', 'g', '{}', 'r', 'owner')",
    "SELECT 1 FROM intel.promotions",
    "UPDATE intel.promotions SET reason = 'x'",
    "DELETE FROM intel.promotions",
    "TRUNCATE intel.promotions",
    "INSERT INTO intel.agent_attributions DEFAULT VALUES",
    "SELECT 1 FROM intel.agent_attributions",
    "UPDATE analytics.research_hypotheses SET status = 'ACCEPTED'",
    "DELETE FROM analytics.research_hypotheses",
    "INSERT INTO analytics.experiments DEFAULT VALUES",
    "SELECT 1 FROM core.fixtures",
    "SELECT 1 FROM picks.picks",
    "SELECT 1 FROM ai.usage",
    "INSERT INTO ai.agent_runs DEFAULT VALUES",
])
def test_the_role_writes_no_promotion_and_reads_and_writes_nothing_but_hypotheses(db: psycopg.Connection[Any], cluster: str, statement: str) -> None:
    with logged_in_as(db, "predigol_worker", then_set=ROLE), refuses(db, psycopg.errors.InsufficientPrivilege, saying="permission denied"):
        db.execute(statement)


def test_the_worker_without_the_role_still_cannot_sign_an_agent_promotion_and_neither_can_the_role_with_the_owners_words(
        db: psycopg.Connection[Any], cluster: str) -> None:
    """Two walls: no privilege for the role, and the row policy of 0111 for the worker. A cluster without the role is as safe as one with it."""
    with logged_in_as(db, "predigol_worker"), refuses(db, psycopg.errors.InsufficientPrivilege):
        promote(db)
    with logged_in_as(db, "predigol_worker", then_set=ROLE), refuses(db, psycopg.errors.InsufficientPrivilege):
        promote(db, decided_by="system", from_role="CHAMPION", to_role="CHALLENGER")


def test_the_role_cannot_be_reached_by_the_api_or_by_anyone_else(db: psycopg.Connection[Any], cluster: str) -> None:
    with logged_in_as(db, "predigol_api"), refuses(db, psycopg.errors.InsufficientPrivilege):
        db.execute(f"SET ROLE {ROLE}")


# -- what it does -------------------------------------------------------------------------------------------------------------------

def test_the_analyst_writes_its_hypotheses_through_the_role_and_they_carry_the_agent_and_the_version(db: psycopg.Connection[Any], cluster: str) -> None:
    with logged_in_as(db, "predigol_worker"):
        ids, how = analyst.write(db, [a_hypothesis(), a_hypothesis(title="the Match Agent mixes FORM and H2H", agent="match", agent_version="match-v1")],
                                 week_from="2026-10-27", at=NOW)
        assert how == "role" and len(ids) == 2
        assert scalar(db.execute("SELECT current_user")) == "predigol_worker", "the role is put back when the writing ends"
    rows = db.execute("SELECT agent, agent_version, status, proposed_by, evidence->>'la_version' FROM analytics.research_hypotheses "
                      "WHERE id = ANY(%s) ORDER BY id", (ids,)).fetchall()
    assert rows == [("council", "council-v1", "PROPOSED", "ai", "la-v1"), ("match", "match-v1", "PROPOSED", "ai", "la-v1")]
    with logged_in_as(db, "predigol_worker"):
        again, _ = analyst.write(db, [a_hypothesis()], week_from="2026-10-27", at=NOW)
    assert again == [], "the same hypothesis of the same week is proposed once"


def test_a_cluster_without_the_role_writes_as_the_worker_and_says_so(db: psycopg.Connection[Any], cluster: str) -> None:
    db.execute(f"ALTER ROLE {ROLE} RENAME TO predigol_learning_away")
    try:
        with logged_in_as(db, "predigol_worker"):
            ids, how = analyst.write(db, [a_hypothesis()], week_from="2026-10-27", at=NOW)
        assert how == "no_role" and len(ids) == 1
    finally:
        db.rollback()
