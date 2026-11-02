"""Migration 0117 (the incident register): additive, empty, append-only and reversible.

Deploying must change nothing the system does: it adds one table, one view and one function, alters nothing that existed, writes no row,
refuses every edit of what is written later, and leaves as it came. Run on a scratch database at revision 0116, the way production does."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import errors

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0117"
TABLE = "audit.incident_events"
VIEW = "audit.incidents"
FUNCTION = "audit.refuse_incident_change()"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Every column of every table and view the migration must leave alone (all but its own two)."""
    own = {name.split(".")[1] for name in (TABLE, VIEW)}
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'raw', 'audit') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "audit" and r[1] in own)]


def _event(c: psycopg.Connection[Any], **kw: Any) -> None:
    """One line of state/incidents.jsonl as the host writes it, stored the way bin/incident-dump.sh stores it."""
    line = json.dumps(kw, sort_keys=True)
    c.execute(
        "INSERT INTO audit.incident_events (line_sha256, incident_id, event, at, alert_key, service, severity, body, field, minutes, actor, raw) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
        (hashlib.sha256(line.encode()).hexdigest(), kw["incident"], kw["event"], kw["at"], kw.get("key"), kw.get("service"), kw.get("severity"),
         kw.get("value", kw.get("text", "")), kw.get("field"), kw.get("minutes"), kw.get("actor", "system"), line))


def test_0117_adds_the_register_and_nothing_else_refuses_every_edit_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0116")
        with psycopg.connect(dsn) as c:
            assert not _exists(c, TABLE) and not _exists(c, VIEW)
            before = _shape(c)

        command.upgrade(_cfg(), "0117")
        with psycopg.connect(dsn) as c:
            assert _exists(c, TABLE) and _exists(c, VIEW)
            assert _shape(c) == before, "nothing that existed was changed"
            assert c.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,), "the migration writes no row"
            assert c.execute(f"SELECT count(*) FROM {VIEW}").fetchone() == (0,)
            indexes = {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'audit' AND tablename = 'incident_events'").fetchall()}
            assert {"incident_events_pkey", "incident_events_incident", "incident_events_openings", "incident_events_at"} <= indexes
            triggers = {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal", (TABLE,)).fetchall()}
            assert triggers == {"incident_events_append_only", "incident_events_no_truncate"}, "an event is never edited, deleted or truncated afterwards"
            for name in (TABLE, VIEW):
                comment = c.execute("SELECT obj_description(%s::regclass)", (name,)).fetchone()
                assert comment is not None and comment[0], f"{name} says what it is"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0117",)

        with psycopg.connect(dsn, autocommit=True) as c:
            # an alert that opens, changes severity and closes; the same alert again later (recurrence); a manual incident with the owner's notes
            _event(c, at="2026-10-20T10:00:00Z", event="open", incident="INC-2026-001", key="disk.usage", service="disk", severity="SEV2", text="disco al 81 %")
            _event(c, at="2026-10-20T10:20:00Z", event="update", incident="INC-2026-001", key="disk.usage", service="disk", severity="SEV1", text="disco al 91 %")
            _event(c, at="2026-10-20T12:00:00Z", event="close", incident="INC-2026-001", key="disk.usage", service="disk", severity="SEV1", text="recuperado", minutes=120)
            _event(c, at="2026-10-22T08:00:00Z", event="open", incident="INC-2026-002", key="disk.usage", service="disk", severity="SEV2", text="disco al 82 %")
            _event(c, at="2026-10-22T09:00:00Z", event="note", incident="INC-2026-001", key="disk.usage", service="disk", severity="SEV1", field="cause",
                   value="un volcado viejo", actor="owner")
            _event(c, at="2026-10-22T09:05:00Z", event="note", incident="INC-2026-001", key="disk.usage", service="disk", severity="SEV1", field="cause",
                   value="volumenes huerfanos de la base", actor="owner")
            _event(c, at="2026-10-22T09:06:00Z", event="note", incident="INC-2026-001", key="disk.usage", service="disk", severity="SEV1", field="affected_users",
                   value="0", actor="owner")
            # personal data: what bin/incident.sh writes ("si: ..." with a colon, "si ...", "no") is accepted; the newest answer is the one the view shows
            _event(c, at="2026-10-22T09:07:00Z", event="note", incident="INC-2026-001", key="disk.usage", service="disk", severity="SEV1", field="personal_data",
                   value="si: correos de 12 titulares", actor="owner")
            _event(c, at="2026-10-22T09:08:00Z", event="note", incident="INC-2026-001", key="disk.usage", service="disk", severity="SEV1", field="personal_data",
                   value="no", actor="owner")
            assert c.execute("SELECT personal_data FROM audit.incidents WHERE incident_id = 'INC-2026-001'").fetchone() == ("no",)
            row = c.execute("SELECT state, duration, severity, first_severity, symptom, cause, affected_users, detection, earlier_same_alert "
                            "FROM audit.incidents WHERE incident_id = 'INC-2026-001'").fetchone()
            assert row is not None
            assert row[0] == "closed" and str(row[1]) == "2:00:00"
            assert (row[2], row[3], row[4]) == ("SEV1", "SEV2", "disco al 81 %"), "severity now is the newest; the symptom is the opening's"
            assert (row[5], row[6]) == ("volumenes huerfanos de la base", "0"), "the newest note of a field wins"
            assert row[7] == "server check" and row[8] is None
            row2 = c.execute("SELECT state, duration, earlier_same_alert FROM audit.incidents WHERE incident_id = 'INC-2026-002'").fetchone()
            assert row2 == ("open", None, ["INC-2026-001"]), "an open incident has no closing and points at the earlier ones of its alert"

            # the same line twice adds nothing: the key of the mirror
            with pytest.raises(errors.UniqueViolation):
                _event(c, at="2026-10-22T08:00:00Z", event="open", incident="INC-2026-002", key="disk.usage", service="disk", severity="SEV2", text="disco al 82 %")

            # nothing is edited, deleted or truncated, by anybody
            with pytest.raises(errors.CheckViolation):
                c.execute("UPDATE audit.incident_events SET body = 'x' WHERE incident_id = 'INC-2026-001'")
            with pytest.raises(errors.CheckViolation):
                c.execute("DELETE FROM audit.incident_events WHERE incident_id = 'INC-2026-001'")
            with pytest.raises(errors.CheckViolation):
                c.execute("TRUNCATE audit.incident_events")

            # what the table refuses to hold
            base: dict[str, Any] = {"at": "2026-10-23T00:00:00Z", "event": "open", "incident": "INC-2026-003", "key": "x.y", "service": "x",
                                    "severity": "SEV3", "text": "x"}
            note: dict[str, Any] = {**base, "event": "note", "actor": "owner", "field": "cause", "value": "x"}
            bad: list[dict[str, Any]] = [
                {**base, "severity": None},                                         # an opening says its severity
                {**base, "incident": "INC-26-3"},                                    # the id has a year and three digits at least
                {**base, "key": "Not A Key"},                                        # service.check, lower case
                {**note, "field": None},                                             # a note names its field
                {**note, "actor": "system"},                                         # and is the owner's
                {**note, "field": "affected_users", "value": "Ana, Luis"},           # users are a number, never a list of people
                {**note, "field": "personal_data", "value": "quizas"},               # yes or no
                {**note, "field": "personal_data", "value": "sin datos"},            # "si" or "no" as a word of its own, not the start of another one
                {**note, "field": "nickname"},                                       # a field the register knows
                {**base, "event": "close", "severity": "SEV9"},                      # three severities
                {**base, "event": "reopen"},                                         # four kinds of event
            ]
            for kw in bad:
                with pytest.raises(errors.CheckViolation):
                    _event(c, **kw)
            c.execute("SELECT 1")

        command.downgrade(_cfg(), "0116")
        with psycopg.connect(dsn) as c:
            assert not _exists(c, TABLE) and not _exists(c, VIEW)
            assert c.execute("SELECT to_regprocedure(%s)", (FUNCTION,)).fetchone() == (None,), "the function goes with it"
            assert _shape(c) == before, "and the rest is as it was"
        command.upgrade(_cfg(), "0117")
        with psycopg.connect(dsn) as c:
            assert _exists(c, TABLE) and _exists(c, VIEW), "it can be applied again"
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
