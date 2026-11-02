"""Who may write the promotion of an agent (Plan Maestro IA, sections 25 and 32): the database decides, not a prompt.

The worker runs every agent, so what the worker can write is what an agent could write if it were mistaken or manipulated. The plan's answer is
not a rule in a prompt: the table refuses. Here the roles are the ones the server has (db/roles.sql and db/grants.sql run as the operator runs
them), and each test acts as a role - the worker, the API, the rollback role the worker reaches with SET ROLE, the owner - and shows what it
may and may not write:

* the worker still writes every other entity exactly as before (the statements the existing code runs are replayed as they are);
* nobody but the owner writes an agent promotion, the worker included;
* the rollback role writes ONE kind of row - the demotion, by the system, of the champion the family has right now - and has no other
  privilege anywhere;
* the shape of an agent promotion is a CHECK that binds the owner too.
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

from fbi.ai.agents import registry
from fbi.ai.contracts import base
from fbi.intel.calibration import promote
from tests.integration.agent_tables import (
    HASH,
    OTHER,
    insert,
    match_values,
    refuses,
    run_values,
    shaped,
    task_values,
    update,
)
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

DEPLOY_DB = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "db"
FAMILY = "1X2"
CHAMPION = "council@council-v1+match-v1"
SUCCESSOR = "council@council-v2+match-v1"
OTHER_AGENT = "match@match-v1"
RLS = "row-level security"


def ago(**delta: float) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


def promotion(**over: Any) -> dict[str, Any]:
    """An agent promotion as the owner signs it, with every field the shape asks for."""
    values: dict[str, Any] = {
        "at": ago(hours=48), "entity": "agent", "market_key": FAMILY, "model_name": CHAMPION, "entity_id": None, "from_role": None,
        "to_role": "CHAMPION", "gate_version": "ma-gate-v1", "criteria": Jsonb({"report_hash": HASH, "families": [FAMILY]}),
        "reason": "passed the gate of the family with 312 selections in 41 days", "decided_by": "owner",
    }
    return values | over


def demotion(**over: Any) -> dict[str, Any]:
    """The one row the system may write: the champion goes back to challenger, as the guard of its family says it must."""
    return promotion(at=ago(), from_role="CHAMPION", to_role="CHALLENGER", decided_by="system",
                     criteria=Jsonb({"report_hash": OTHER, "trigger": "guard"}),
                     reason="automatic roll-back: the guard of the family was broken twice in a week") | over


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
        for role in ("predigol_rollback", "predigol_worker", "predigol_api"):
            conn.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
                         f"EXECUTE 'DROP OWNED BY {role}'; EXECUTE 'DROP ROLE {role}'; END IF; END $$")


@contextmanager
def logged_in_as(db: psycopg.Connection[Any], user: str, *, then_set: str | None = None) -> Iterator[None]:
    """The statements inside run as ``user`` - what a login of that role would be - and, if asked, after SET ROLE ``then_set``."""
    db.execute(f"SET SESSION AUTHORIZATION {user}")
    if then_set is not None:
        db.execute(f"SET ROLE {then_set}")
    assert db.execute("SELECT current_user").fetchone() == (then_set or user,), "the statements inside run as the role they say"
    try:
        yield
    finally:
        db.execute("RESET ROLE")
        db.execute("RESET SESSION AUTHORIZATION")


def champion_of(db: psycopg.Connection[Any], family: str = FAMILY) -> list[tuple[str, datetime, int]]:
    return [tuple(r) for r in db.execute("SELECT model_name, since, promotion_id FROM intel.agent_champion(%s)", (family,)).fetchall()]


def count(db: psycopg.Connection[Any]) -> int:
    return int(scalar(db.execute("SELECT count(*) FROM intel.promotions")))


# ── the roles the scripts make ────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_rollback_role_logs_in_nowhere_and_bypasses_nothing(db: psycopg.Connection[Any], cluster: str) -> None:
    flags = db.execute("SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles "
                       "WHERE rolname = 'predigol_rollback'").fetchone()
    assert flags == (False, False, False, False, False, False)


def test_only_the_worker_can_become_it_and_it_inherits_nothing_for_that(db: psycopg.Connection[Any], cluster: str) -> None:
    members = db.execute("SELECT m.rolname, a.inherit_option, a.set_option, a.admin_option FROM pg_auth_members a "
                         "JOIN pg_roles r ON r.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
                         "WHERE r.rolname = 'predigol_rollback' ORDER BY 1").fetchall()
    assert members == [("predigol_worker", False, True, False)]
    can = db.execute("SELECT pg_has_role('predigol_worker', 'predigol_rollback', 'SET'), "
                     "pg_has_role('predigol_worker', 'predigol_rollback', 'USAGE'), "
                     "pg_has_role('predigol_api', 'predigol_rollback', 'SET'), "
                     "pg_has_role('predigol_api', 'predigol_rollback', 'MEMBER')").fetchone()
    assert can == (True, False, False, False), "the worker may ask for the role; it does not hold its privileges until it does"


def test_the_rollback_role_can_read_and_insert_in_one_table_and_nothing_else_anywhere(db: psycopg.Connection[Any], cluster: str) -> None:
    reached = db.execute("""
        SELECT n.nspname || '.' || c.relname || ':' || c.relkind::text
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public')
           AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege('predigol_rollback', c.oid, 'USAGE,SELECT,UPDATE')
                    ELSE has_table_privilege('predigol_rollback', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') END
         ORDER BY 1""").fetchall()
    assert reached == [("intel.promotions:r",), ("intel.promotions_id_seq:S",)]
    held = {p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
            if scalar(db.execute("SELECT has_table_privilege('predigol_rollback', 'intel.promotions', %s)", (p,)))}
    assert held == {"SELECT", "INSERT"}
    sequence = {p for p in ("USAGE", "SELECT", "UPDATE")
                if scalar(db.execute("SELECT has_sequence_privilege('predigol_rollback', 'intel.promotions_id_seq', %s)", (p,)))}
    assert sequence == {"USAGE", "SELECT"}
    schemas = db.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' AND nspname NOT IN ('information_schema', 'public') "
                         "AND has_schema_privilege('predigol_rollback', oid, 'USAGE') ORDER BY 1").fetchall()
    assert schemas == [("intel",)]
    assert scalar(db.execute("SELECT has_table_privilege('predigol_rollback', 'public.alembic_version', 'SELECT')")) is False


def test_the_rollback_role_reaches_nothing_but_the_table(db: psycopg.Connection[Any], cluster: str) -> None:
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        for statement in ("SELECT 1 FROM core.fixtures", "SELECT 1 FROM ai.usage", "SELECT 1 FROM ai.agent_tasks", "SELECT 1 FROM picks.picks",
                          "INSERT INTO ai.agent_runs DEFAULT VALUES", "UPDATE intel.promotions SET reason = 'x'",
                          "DELETE FROM intel.promotions", "TRUNCATE intel.promotions"):
            with refuses(db, psycopg.errors.InsufficientPrivilege, saying="permission denied"):
                db.execute(statement)
        assert scalar(db.execute("SELECT count(*) FROM intel.promotions")) >= 0


# ── the code that is running today writes what it always wrote ─────────────────────────────────────────────────────────────

TRACE_RETIRE = ("INSERT INTO intel.promotions (at, entity, to_role, from_role, gate_version, criteria, reason, decided_by) "
                "VALUES (%s, 'model', 'RETIRED', 'CHAMPION', %s, %s, %s, %s)")
TRACE_PROMOTE = ("INSERT INTO intel.promotions (at, entity, to_role, from_role, gate_version, criteria, reason, decided_by) "
                 "VALUES (%s, 'model', 'CHAMPION', %s, %s, %s, %s, %s)")


def test_the_worker_writes_every_other_entity_as_it_always_did(db: psycopg.Connection[Any], cluster: str) -> None:
    before = count(db)
    with logged_in_as(db, "predigol_worker"):
        for entity in ("calibrator", "market_edge", "selection_rule"):
            promote(db, at=ago(), entity=entity, market="1X2", model="dixon_coles", entity_id=None, from_role=None, to_role="CHAMPION",
                    gate_version="cal-gate-v1", criteria={"n": 300}, reason=f"the {entity} passed its gate")
        promote(db, at=ago(), entity="calibrator", market="OU", model="dixon_coles", entity_id=7, from_role="CHAMPION", to_role="RETIRED",
                gate_version="cal-gate-v1", criteria={"n": 300}, reason="replaced")
        db.execute(TRACE_PROMOTE, (ago(), None, "model-ledger-v1", Jsonb({"model_code": "mc9a7bec97ca"}), "first entry", "owner"))
        db.execute(TRACE_RETIRE, (ago(), "model-ledger-v1", Jsonb({"model_code": "mc9a7bec97ca"}), "replaced by mc2", "owner"))
        assert scalar(db.execute("SELECT count(*) FROM intel.promotions")) == before + 6, "and reads them back"
    assert count(db) == before + 6


def test_the_worker_still_cannot_rewrite_a_promotion_but_the_trigger_says_so(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(entity="model", market_key=None, model_name=None))
    with logged_in_as(db, "predigol_worker"):
        with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
            db.execute("UPDATE intel.promotions SET reason = 'rewritten'")
        with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
            db.execute("DELETE FROM intel.promotions")


# ── nobody but the owner writes an agent ──────────────────────────────────────────────────────────────────────────────────────

SIGNATURES = [
    ("the owner's champion", {"decided_by": "owner"}),
    ("the owner's demotion", {"decided_by": "owner", "from_role": "CHAMPION", "to_role": "RETIRED"}),
    ("a challenger", {"decided_by": "owner", "to_role": "CHALLENGER"}),
    ("a validation", {"decided_by": "owner", "to_role": "VALIDATED"}),
    ("a rejection", {"decided_by": "owner", "to_role": "REJECTED"}),
    ("a champion the system promotes", {"decided_by": "system", "to_role": "CHAMPION", "from_role": "CHALLENGER"}),
    ("a demotion by the system", {"decided_by": "system", "from_role": "CHAMPION", "to_role": "RETIRED"}),
    ("a row that is not even well formed", {"decided_by": "system", "reason": "x", "model_name": "who knows"}),
]


@pytest.mark.parametrize(("label", "over"), SIGNATURES, ids=[s[0] for s in SIGNATURES])
def test_the_worker_signs_no_agent_whatever_the_row_says(db: psycopg.Connection[Any], cluster: str, label: str, over: dict[str, Any]) -> None:
    insert(db, "intel.promotions", promotion())  # there is a champion to demote
    before = count(db)
    with logged_in_as(db, "predigol_worker"):
        with refuses(db, psycopg.errors.InsufficientPrivilege, saying=RLS):
            insert(db, "intel.promotions", promotion(at=ago(), **over))
        assert count(db) == before


def test_the_api_reads_the_promotions_and_writes_none(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion())
    with logged_in_as(db, "predigol_api"):
        assert scalar(db.execute("SELECT count(*) FROM intel.promotions WHERE entity = 'agent'")) == 1
        assert champion_of(db)[0][0] == CHAMPION
        for entity in ("agent", "model"):
            with refuses(db, psycopg.errors.InsufficientPrivilege, saying="permission denied"):
                insert(db, "intel.promotions", promotion(entity=entity, decided_by="owner"))


def test_the_owner_who_is_not_a_superuser_signs_an_agent_and_is_still_bound_by_its_shape(db: psycopg.Connection[Any], cluster: str) -> None:
    """As on the server: the migrations' role owns the table, is subject to no row policy, and is NOT a superuser."""
    db.execute("CREATE ROLE zz_owner_0111 NOLOGIN")
    db.execute("GRANT USAGE ON SCHEMA intel TO zz_owner_0111")
    db.execute("ALTER TABLE intel.promotions OWNER TO zz_owner_0111")
    assert scalar(db.execute("SELECT rolsuper FROM pg_roles WHERE rolname = 'zz_owner_0111'")) is False
    with logged_in_as(db, "zz_owner_0111"):
        insert(db, "intel.promotions", promotion())
        insert(db, "intel.promotions", promotion(at=ago(hours=1), model_name=SUCCESSOR, decided_by="owner"))
        with refuses(db, psycopg.errors.CheckViolation, constraint="promotions_agent_shape"):
            insert(db, "intel.promotions", promotion(market_key="MONEYLINE"))
        with refuses(db, psycopg.errors.CheckViolation, constraint="promotions_agent_shape"):
            insert(db, "intel.promotions", promotion(decided_by="system"))
        assert count(db) >= 2


# ── the roll-back: one row, for one champion ──────────────────────────────────────────────────────────────────────────────────

def test_the_rollback_role_demotes_the_champion_of_a_family(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion())
    assert [row[0] for row in champion_of(db)] == [CHAMPION]
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        insert(db, "intel.promotions", demotion())
    assert champion_of(db) == [], "the family goes back to the engine of today: nobody reads an agent that has no champion"
    row = db.execute("SELECT entity, market_key, model_name, from_role, to_role, decided_by FROM intel.promotions ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("agent", FAMILY, CHAMPION, "CHAMPION", "CHALLENGER", "system")


def test_it_can_retire_the_champion_instead(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion())
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        insert(db, "intel.promotions", demotion(to_role="RETIRED"))
    assert champion_of(db) == []


def test_a_champion_is_demoted_once(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion())
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        insert(db, "intel.promotions", demotion())
        with refuses(db, psycopg.errors.InsufficientPrivilege, saying=RLS):
            insert(db, "intel.promotions", demotion(reason="automatic roll-back, written a second time for the same champion"))


REFUSED_TO_THE_ROLLBACK = [
    ("a promotion", {"to_role": "CHAMPION", "from_role": None}),
    ("a promotion from challenger", {"to_role": "CHAMPION", "from_role": "CHALLENGER"}),
    ("a demotion signed by the owner", {"decided_by": "owner"}),
    ("a demotion from nothing", {"from_role": None, "to_role": "RETIRED"}),
    ("a demotion from challenger", {"from_role": "CHALLENGER", "to_role": "RETIRED"}),
    ("a rejection", {"to_role": "REJECTED"}),
    ("a validation", {"to_role": "VALIDATED"}),
    ("a failed validation", {"to_role": "NOT_VALIDATED"}),
    ("a model", {"entity": "model"}),
    ("a calibrator", {"entity": "calibrator"}),
    ("a selection rule", {"entity": "selection_rule"}),
    ("another agent than the champion", {"model_name": "council@council-v9+match-v1"}),
    ("the same agent in another version", {"model_name": SUCCESSOR}),
    ("a family that has no champion", {"market_key": "OU"}),
    ("no family", {"market_key": None}),
    ("a demotion dated before the promotion it undoes", {"at": ago(hours=72)}),
    ("a demotion dated in the future", {"at": ago(hours=-1)}),
]


@pytest.mark.parametrize(("label", "over"), REFUSED_TO_THE_ROLLBACK, ids=[r[0] for r in REFUSED_TO_THE_ROLLBACK])
def test_the_rollback_role_writes_nothing_but_the_demotion_of_a_champion(db: psycopg.Connection[Any], cluster: str, label: str,
                                                                        over: dict[str, Any]) -> None:
    insert(db, "intel.promotions", promotion())
    before = count(db)
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"), refuses(db, psycopg.errors.InsufficientPrivilege, saying=RLS):
        insert(db, "intel.promotions", demotion(**over))
    assert count(db) == before and [row[0] for row in champion_of(db)] == [CHAMPION], "the champion is where it was"


ACCEPTED_BY_THE_ROLLBACK = [
    ("a demotion dated the moment of the promotion", {"at": "the promotion"}),
    ("a demotion dated a few minutes ahead", {"at": ago(minutes=-3)}),
    ("a retirement", {"to_role": "RETIRED"}),
]


@pytest.mark.parametrize(("label", "over"), ACCEPTED_BY_THE_ROLLBACK, ids=[r[0] for r in ACCEPTED_BY_THE_ROLLBACK])
def test_the_limits_of_the_rollback_are_where_the_plan_puts_them(db: psycopg.Connection[Any], cluster: str, label: str,
                                                                over: dict[str, Any]) -> None:
    insert(db, "intel.promotions", promotion())
    if over.get("at") == "the promotion":
        over = {**over, "at": scalar(db.execute("SELECT at FROM intel.promotions WHERE entity = 'agent'"))}
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        insert(db, "intel.promotions", demotion(**over))
    assert champion_of(db) == []


def test_the_rollback_role_can_not_write_the_other_entities_even_in_the_shape_of_a_demotion(db: psycopg.Connection[Any], cluster: str) -> None:
    before = count(db)
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        with refuses(db, psycopg.errors.InsufficientPrivilege, saying=RLS):
            db.execute(TRACE_RETIRE, (ago(), "model-ledger-v1", Jsonb({"model_code": "mc1"}), "replaced", "system"))
        with refuses(db, psycopg.errors.InsufficientPrivilege, saying=RLS):
            promote(db, at=ago(), entity="calibrator", market="1X2", model="dixon_coles", entity_id=None, from_role="CHAMPION",
                    to_role="RETIRED", gate_version="cal-gate-v1", criteria={"n": 3}, reason="not its business")
    assert count(db) == before


def test_after_the_worker_returns_to_itself_it_has_none_of_the_roles_powers(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion())
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        insert(db, "intel.promotions", demotion())
        db.execute("RESET ROLE")  # the worker is itself again
        insert(db, "intel.promotions", promotion(entity="calibrator", market_key=None, model_name=None))
        with refuses(db, psycopg.errors.InsufficientPrivilege, saying=RLS):
            insert(db, "intel.promotions", demotion(reason="and now it tries as itself, with the shape of a demotion"))


# ── who is the champion of a family ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_family_with_no_promotion_has_no_champion(db: psycopg.Connection[Any], cluster: str) -> None:
    assert champion_of(db) == []
    insert(db, "intel.promotions", promotion(to_role="VALIDATED", reason="validated, waiting for the owner to sign the champion"))
    assert champion_of(db) == [], "a validation is a report: it names no champion"


def test_the_champion_is_the_agent_of_the_newest_champion_row_of_the_family(db: psycopg.Connection[Any], cluster: str) -> None:
    first = insert(db, "intel.promotions", promotion(at=ago(hours=72)))
    second = insert(db, "intel.promotions", promotion(at=ago(hours=24), model_name=SUCCESSOR, from_role="CHALLENGER"))
    insert(db, "intel.promotions", promotion(at=ago(hours=1), market_key="OU", model_name=OTHER_AGENT))
    found = champion_of(db)
    assert [(row[0], row[2]) for row in found] == [(SUCCESSOR, second)] and first != second
    assert [row[0] for row in champion_of(db, "OU")] == [OTHER_AGENT], "each family has its own"


def test_what_is_written_after_the_champion_ends_it_only_when_it_is_about_the_champion(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(at=ago(hours=72)))
    insert(db, "intel.promotions", promotion(at=ago(hours=60), model_name=SUCCESSOR, to_role="CHALLENGER"))
    insert(db, "intel.promotions", promotion(at=ago(hours=50), model_name=OTHER_AGENT, to_role="REJECTED"))
    insert(db, "intel.promotions", promotion(at=ago(hours=40), model_name=SUCCESSOR, to_role="VALIDATED"))
    insert(db, "intel.promotions", promotion(at=ago(hours=30), to_role="NOT_VALIDATED"))
    assert [row[0] for row in champion_of(db)] == [CHAMPION], "a challenger, a rejection of another agent, a report: the champion stays"
    for n, role in enumerate(("CHALLENGER", "RETIRED", "REJECTED")):
        with db.transaction(force_rollback=True):
            insert(db, "intel.promotions", promotion(at=ago(hours=20 - n), from_role=None, to_role=role))
            assert champion_of(db) == [], f"{role} ends it, whoever wrote it and whatever it says it came from"


def test_the_newest_is_the_newest_by_date_and_not_by_the_order_it_was_written(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(at=ago(hours=24)))
    insert(db, "intel.promotions", promotion(at=ago(hours=72), model_name=SUCCESSOR))  # written later, dated earlier
    assert [row[0] for row in champion_of(db)] == [CHAMPION]


def test_a_family_ends_the_champion_of_that_family_only(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(at=ago(hours=72)))
    insert(db, "intel.promotions", promotion(at=ago(hours=72), market_key="OU"))
    insert(db, "intel.promotions", promotion(at=ago(hours=24), market_key="OU", from_role="CHAMPION", to_role="RETIRED"))
    assert [row[0] for row in champion_of(db)] == [CHAMPION] and champion_of(db, "OU") == []
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        insert(db, "intel.promotions", demotion())  # the same agent is not the champion of OU any more: that does not matter here
    assert champion_of(db) == []


def test_a_champion_who_is_retired_does_not_bring_back_the_one_before(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(at=ago(hours=72)))  # A, never demoted by a row of its own
    insert(db, "intel.promotions", promotion(at=ago(hours=24), model_name=SUCCESSOR))  # B replaces it
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        with refuses(db, psycopg.errors.InsufficientPrivilege, saying=RLS):
            insert(db, "intel.promotions", demotion())  # A is no longer the champion: it cannot be demoted
        insert(db, "intel.promotions", demotion(model_name=SUCCESSOR))
    assert champion_of(db) == [], "no fallback to A: the family goes back to the engine of today until the owner signs another"


def test_a_challenger_registered_after_the_champion_does_not_stop_its_rollback(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(at=ago(hours=72)))
    insert(db, "intel.promotions", promotion(at=ago(hours=24), model_name=SUCCESSOR, to_role="CHALLENGER"))
    insert(db, "intel.promotions", promotion(at=ago(hours=12), to_role="VALIDATED"))
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        insert(db, "intel.promotions", demotion())
    assert champion_of(db) == []


def test_an_agent_that_was_a_challenger_first_is_the_champion_once_promoted(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(at=ago(hours=72), to_role="CHALLENGER"))
    insert(db, "intel.promotions", promotion(at=ago(hours=24), from_role="CHALLENGER"))
    assert [row[0] for row in champion_of(db)] == [CHAMPION], "what came before the promotion does not end it"
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"):
        insert(db, "intel.promotions", demotion())
    assert champion_of(db) == []


def test_the_promotions_of_the_other_entities_are_not_those_of_an_agent(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(at=ago(hours=72)))
    insert(db, "intel.promotions", promotion(at=ago(hours=2), entity="calibrator", model_name="dixon_coles", gate_version="cal-gate-v1"))
    insert(db, "intel.promotions", promotion(at=ago(hours=1), entity="model", from_role="CHAMPION", to_role="RETIRED"))  # the same name, another entity
    assert [row[0] for row in champion_of(db)] == [CHAMPION]


def test_a_champion_the_owner_already_retired_cannot_be_demoted_again(db: psycopg.Connection[Any], cluster: str) -> None:
    insert(db, "intel.promotions", promotion(at=ago(hours=72)))
    insert(db, "intel.promotions", promotion(at=ago(hours=24), from_role="CHAMPION", to_role="RETIRED"))
    with logged_in_as(db, "predigol_worker", then_set="predigol_rollback"), refuses(db, psycopg.errors.InsufficientPrivilege, saying=RLS):
        insert(db, "intel.promotions", demotion())


# ── the shape of an agent promotion binds everybody ───────────────────────────────────────────────────────────────────────────

BAD_SHAPES = [
    ("a market that is not a family", {"market_key": "MONEYLINE"}),
    ("no market", {"market_key": None}),
    ("a family in lower case", {"market_key": "btts"}),
    ("a name in capitals", {"model_name": "Council@council-v1"}),
    ("a name without a version", {"model_name": "council"}),
    ("no name", {"model_name": None}),
    ("an upstream without a version", {"model_name": "council@council-v1+match"}),
    ("a promotion that names an entity id", {"entity_id": 5}),
    ("a role nobody has", {"from_role": "KING"}),
    ("a promotion from itself", {"from_role": "CHAMPION", "to_role": "CHAMPION"}),
    ("a gate that is not a version", {"gate_version": "GATE"}),
    ("criteria that are a list", {"criteria": Jsonb([HASH])}),
    ("criteria without the report", {"criteria": Jsonb({"gate": "ma-gate-v1"})}),
    ("a report hash that is null", {"criteria": Jsonb({"report_hash": None})}),
    ("a report hash that is not one", {"criteria": Jsonb({"report_hash": "abc"})}),
    ("a report hash in capitals", {"criteria": Jsonb({"report_hash": "A" * 64})}),
    ("a reason too short to be read back", {"reason": "ok"}),
    ("a blank reason", {"reason": " " * 30}),
    ("a promotion signed by the system", {"decided_by": "system"}),
    ("a system row that retires from nothing", {"decided_by": "system", "from_role": None, "to_role": "RETIRED"}),
    ("a system row that rejects a champion", {"decided_by": "system", "from_role": "CHAMPION", "to_role": "REJECTED"}),
    ("a system row that validates", {"decided_by": "system", "from_role": "CHAMPION", "to_role": "VALIDATED"}),
]


@pytest.mark.parametrize(("label", "over"), BAD_SHAPES, ids=[b[0] for b in BAD_SHAPES])
def test_an_agent_promotion_of_a_bad_shape_is_refused_to_the_owner_too(db: psycopg.Connection[Any], cluster: str, label: str,
                                                                      over: dict[str, Any]) -> None:
    with refuses(db, psycopg.errors.CheckViolation, constraint="promotions_agent_shape"):
        insert(db, "intel.promotions", promotion(**over))


GOOD_SHAPES = [
    ("the first champion", {}),
    ("a champion that replaces a challenger", {"from_role": "CHALLENGER"}),
    ("a retirement by the owner", {"from_role": "CHAMPION", "to_role": "RETIRED"}),
    ("a challenger", {"to_role": "CHALLENGER"}),
    ("a rejection", {"to_role": "REJECTED"}),
    ("a validation", {"to_role": "VALIDATED"}),
    ("a failed validation", {"to_role": "NOT_VALIDATED"}),
    ("a demotion by the system", {"decided_by": "system", "from_role": "CHAMPION", "to_role": "CHALLENGER"}),
    ("a retirement by the system", {"decided_by": "system", "from_role": "CHAMPION", "to_role": "RETIRED"}),
    ("an agent that reads two others", {"model_name": "council@council-v1+match-v1+stats-v1"}),
    ("an agent of the learning cycle", {"model_name": "learning_analyst@la-v12"}),
]


@pytest.mark.parametrize(("label", "over"), GOOD_SHAPES, ids=[g[0] for g in GOOD_SHAPES])
def test_an_agent_promotion_of_the_right_shape_is_taken(db: psycopg.Connection[Any], cluster: str, label: str, over: dict[str, Any]) -> None:
    insert(db, "intel.promotions", promotion(**over))


def test_every_family_of_the_contracts_and_no_other_can_have_a_champion(db: psycopg.Connection[Any], cluster: str) -> None:
    for family in base.FAMILIES:
        insert(db, "intel.promotions", promotion(market_key=family))
        assert [row[0] for row in champion_of(db, family)] == [CHAMPION]
    assert count(db) >= len(base.FAMILIES)


def test_the_agents_the_registry_names_are_names_the_table_takes(db: psycopg.Connection[Any], cluster: str) -> None:
    for plan in registry.REGISTRY.planned:
        name = registry.promotion_name(plan.agent, plan.version, ())
        insert(db, "intel.promotions", promotion(model_name=name, market_key=FAMILY))
    assert count(db) >= len(registry.REGISTRY.planned)


NAMES = [
    "council@council-v1", "council@council-v1+match-v1", "council@council-v1+match-v1+stats-v1", "match@match-v1", "post_match_reviewer@pmr-v1",
    "learning_analyst@la-v12", "council@council-v999",
    "", "council", "council@", "@council-v1", "Council@council-v1", "council@council", "council@council-v0", "council@council-v1000",
    "council@council-v1+", "council@council-v1+match", "council@council-v1 +match-v1", "council @council-v1", "council@council-v1,match-v1",
    "council@council_v1", "1council@council-v1", "council@1council-v1", "council@council-v1+Match-v1", "council@council-v1++match-v1",
    "co@un@council-v1", "council-v1", "ñ@council-v1",
]


@pytest.mark.parametrize("name", NAMES)
def test_the_table_names_an_agent_as_the_registry_does(db: psycopg.Connection[Any], cluster: str, name: str) -> None:
    """PostgreSQL's regular expressions and Python's must agree on every name: the registry makes the names and the table checks them."""
    if registry.PROMOTION_NAME.fullmatch(name):
        insert(db, "intel.promotions", promotion(model_name=name))
    else:
        with refuses(db, psycopg.errors.CheckViolation, constraint="promotions_agent_shape"):
            insert(db, "intel.promotions", promotion(model_name=name))


# ── the other roles on the new tables ─────────────────────────────────────────────────────────────────────────────────────────

NEW = ("ai.agent_tasks", "ai.agent_runs", "ai.match_runs", "ai.match_state")


@pytest.mark.parametrize("table", NEW)
def test_the_api_reads_what_the_agents_leave_and_writes_none_of_it(db: psycopg.Connection[Any], cluster: str, table: str) -> None:
    held = {p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
            if scalar(db.execute("SELECT has_table_privilege('predigol_api', %s, %s)", (table, p)))}
    assert held == {"SELECT"}


def test_the_worker_runs_the_queue_and_writes_the_record_and_the_trigger_holds_it_to_the_rules(db: psycopg.Connection[Any], cluster: str,
                                                                                               seed: Seed) -> None:
    with logged_in_as(db, "predigol_worker"):
        run = insert(db, "ai.agent_runs", run_values(seed))
        task = insert(db, "ai.agent_tasks", task_values(seed))
        update(db, "ai.agent_tasks", task, **shaped("queued", run))
        insert(db, "ai.match_runs", match_values(seed))
        assert scalar(db.execute("SELECT count(*) FROM ai.match_state WHERE fixture_id = %s", (seed.fixture_id,))) == 1
        with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
            update(db, "ai.agent_runs", run, reason="rewritten")
        with refuses(db, psycopg.errors.CheckViolation, saying="never deleted"):
            db.execute("DELETE FROM ai.agent_tasks WHERE id = %s", (task,))
        with refuses(db, psycopg.errors.CheckViolation, saying="never changes"):
            update(db, "ai.agent_tasks", task, agent="somebody-else")


# ── the scripts are safe to run again, and on a cluster that lacks the role ─────────────────────────────────────────────────

def test_the_scripts_can_be_run_again_and_change_nothing(db: psycopg.Connection[Any], cluster: str) -> None:
    def snapshot() -> list[Any]:
        return [db.execute("SELECT m.rolname, a.inherit_option, a.set_option FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid "
                           "JOIN pg_roles m ON m.oid = a.member WHERE r.rolname = 'predigol_rollback'").fetchall(),
                db.execute("SELECT p FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) AS p "
                           "WHERE has_table_privilege('predigol_rollback', 'intel.promotions', p) ORDER BY p").fetchall(),
                db.execute("SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = 'predigol_rollback'").fetchall()]

    before = snapshot()
    db.execute((DEPLOY_DB / "roles.sql").read_text())
    db.execute((DEPLOY_DB / "grants.sql").read_text())
    assert snapshot() == before
    assert before[1] == [("INSERT",), ("SELECT",)]
    assert before[2][0][0] is not None, "the role says what it is for"


def test_the_grants_leave_a_cluster_that_lacks_the_role_alone(db: psycopg.Connection[Any], cluster: str) -> None:
    notices: list[str] = []

    def keep(diag: Any) -> None:
        notices.append(diag.message_primary or "")

    db.add_notice_handler(keep)
    try:
        with db.transaction(force_rollback=True):
            db.execute("DROP OWNED BY predigol_rollback")
            db.execute("DROP ROLE predigol_rollback")
            db.execute((DEPLOY_DB / "grants.sql").read_text())
            assert scalar(db.execute("SELECT count(*) FROM pg_roles WHERE rolname = 'predigol_rollback'")) == 0, "the grants do not make it"
    finally:
        db.remove_notice_handler(keep)
    assert any("predigol_rollback does not exist" in n for n in notices), notices


def test_the_roles_script_refuses_a_cluster_that_is_not_predigols(db: psycopg.Connection[Any], cluster: str) -> None:
    with refuses(db, psycopg.errors.RaiseException, saying="not a PrediGol cluster"):
        db.execute("DROP OWNED BY predigol_worker")
        db.execute("DROP ROLE predigol_worker")
        db.execute((DEPLOY_DB / "roles.sql").read_text())
