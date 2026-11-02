"""Plan S3: the queries of Annex A of the owner's incident-response guides run on the real schema and answer what their comment says.

``tests/unit/test_owner_incident_guides.py`` holds the shape of ``docs/owner/GUIAS_RESPUESTA_INCIDENTES.md``. This file holds its SQL: every query of Annex A
runs in a READ ONLY transaction on the schema the migrations build - a renamed column or a moved table fails here, not in the middle of an incident - and the
ones on the audit trail and on the ingestion runs answer the question they ask on rows seeded for it. The owner pastes them into ``predigolctl psql``, which
is a read-only session, so a query that tried to write would fail there too; the unit test already refuses any write keyword."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "owner" / "GUIAS_RESPUESTA_INCIDENTES.md"

if not GUIDE.is_file():
    pytest.skip(f"no {GUIDE.name} next to the code", allow_module_level=True)


def queries() -> dict[str, str]:
    """The SQL blocks of the guide by id: A1 ... A12, with A5 in two parts (A5_1, A5_2). Each ends without its ';'."""
    found: dict[str, str] = {}
    text = GUIDE.read_text(encoding="utf-8")
    for body in re.findall(r"^```sql\n(.*?)^```", text, flags=re.M | re.S):
        for part in re.split(r"(?m)^(?=-- A\d+)", body):
            head = re.match(r"-- (A\d+)(?: \((\d)/(\d)\))?", part)
            if head:
                found[head[1] + (f"_{head[2]}" if head[2] else "")] = part.strip().rstrip(";")
    return found


QUERIES = queries()


def rows(db: psycopg.Connection, name: str, **variables: int) -> list[tuple]:
    sql = QUERIES[name]
    for key, value in variables.items():
        sql = sql.replace(f":{key}", str(value))
    return db.execute(sql).fetchall()


def test_the_guide_holds_every_query_of_annex_a() -> None:
    assert set(QUERIES) == {f"A{n}" for n in (1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12)} | {
        "A5_1",
        "A5_2",
    }


@pytest.mark.parametrize("name", sorted(QUERIES))
def test_each_query_runs_read_only_on_the_real_schema(db: psycopg.Connection, name: str) -> None:
    db.execute("SET TRANSACTION READ ONLY")
    rows(db, name, cuenta=1)


def test_a_write_is_refused_in_that_same_kind_of_transaction(db: psycopg.Connection) -> None:
    """The control of the test above: the read-only transaction really refuses to write, so "it ran" means "it only read"."""
    db.execute("SET TRANSACTION READ ONLY")
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        db.execute("UPDATE auth.users SET status = status")


# --- what they answer, on seeded rows --------------------------------------------------------------------------------------------------------------


@pytest.fixture()
def seeded(db: psycopg.Connection) -> dict[str, int]:
    """Three accounts and what happened around them: a sweep from one address, a targeted attack on Ana, admin writes, privilege changes, sessions,
    failed ingestion runs and a provider near its quota. Everything stays inside the test's transaction and is rolled back."""
    ids: dict[str, int] = {}
    for key, email, role, status in (
        ("owner", "owner@guide.test", "SUPER_ADMIN", "active"),
        ("ana", "ana@guide.test", "USER", "active"),
        ("beto", "beto@guide.test", "USER", "active"),
    ):
        ids[key] = db.execute(
            "INSERT INTO auth.users (email, display_name, password_hash, role, status) VALUES (%s, %s, '$argon2id$test', %s, %s) RETURNING id",
            (email, key.title(), role, status),
        ).fetchone()[0]  # type: ignore[index]
    owner, ana, beto = ids["owner"], ids["ana"], ids["beto"]
    # a sweep: 25 failures from one address against 12 different e-mails, none of them an account
    db.execute(
        "INSERT INTO auth.audit_events (at, action, email, ip, detail) "
        "SELECT now() - (i || ' minutes')::interval, 'login.failed', 'persona' || (i % 12) || '@guide.test', '203.0.113.7', '{\"reason\":\"unknown_email\"}'::jsonb "
        "FROM generate_series(1, 25) i"
    )
    # 18 failures against Ana from 9 addresses, then a success
    db.execute(
        "INSERT INTO auth.audit_events (at, action, target_user_id, email, ip, detail) "
        "SELECT now() - (i || ' minutes')::interval, 'login.failed', %s, 'ana@guide.test', '198.51.100.' || (i %% 9), '{\"reason\":\"wrong_password\"}'::jsonb "
        "FROM generate_series(1, 18) i",
        (ana,),
    )
    db.execute(
        "INSERT INTO auth.audit_events (at, action, actor_user_id, target_user_id, email, ip) VALUES (now() - interval '30 seconds', 'login.succeeded', %s, %s, 'ana@guide.test', '203.0.113.7')",
        (ana, ana),
    )
    # three admin writes this week and one old one
    db.execute(
        "INSERT INTO auth.audit_events (at, action, actor_user_id, ip, detail) "
        "SELECT now() - (i || ' hours')::interval, 'admin.write', %s, '192.0.2.10', jsonb_build_object('method', 'POST', 'path', '/api/v1/admin/users', 'status', 200) "
        "FROM generate_series(1, 3) i",
        (owner,),
    )
    db.execute(
        'INSERT INTO auth.audit_events (at, action, actor_user_id, ip, detail) VALUES (now() - interval \'10 days\', \'admin.write\', %s, \'192.0.2.10\', \'{"method":"POST","path":"/api/v1/admin/old","status":200}\'::jsonb)',
        (owner,),
    )
    # privilege changes: four inside 30 days, three that must not appear (40 days old; a plain USER created; a login)
    for days, action, actor, target, detail in (
        (2, "user.role_changed", owner, beto, '{"from":"USER","to":"SUPER_ADMIN"}'),
        (5, "mfa.reset", None, ana, '{"by":"command_line"}'),
        (1, "password.reset", owner, ana, "{}"),
        (20, "user.created", owner, beto, '{"role":"SUPER_ADMIN"}'),
        (40, "user.role_changed", owner, ana, "{}"),
        (3, "user.created", owner, ana, '{"role":"USER"}'),
    ):
        db.execute(
            "INSERT INTO auth.audit_events (at, action, actor_user_id, target_user_id, detail) VALUES (now() - make_interval(days => %s), %s, %s, %s, %s::jsonb)",
            (days, action, actor, target, detail),
        )
    # sessions: two open, one revoked, one expired
    for tag, user, created, expires, seen, revoked in (
        ("s1", ana, "2 hours", "+1 day", "1 minute", False),
        ("s2", owner, "3 hours", "+1 day", "30 minutes", False),
        ("s3", ana, "3 hours", "+1 day", "2 hours", True),
        ("s4", ana, "3 days", "-1 day", "2 days", False),
    ):
        db.execute(
            "INSERT INTO auth.sessions (id, user_id, created_at, expires_at, last_seen_at, ip, user_agent, revoked_at, revoked_reason) "
            "VALUES (md5(%s) || md5(%s), %s, now() - %s::interval, now() + %s::interval, now() - %s::interval, '203.0.113.7', 'Mozilla/5.0 (test)', "
            "CASE WHEN %s THEN now() END, CASE WHEN %s THEN 'test' END)",
            (tag, tag + "b", user, created, expires.replace("+", ""), seen, revoked, revoked),
        )
    # ingestion: five failures of one job inside the hour, and one success; a provider at 92 % of its budget
    db.execute(
        "INSERT INTO raw.ingestion_runs (job_name, started_at, status, last_error) "
        "SELECT 'zz_annex_job', now() - (i || ' minutes')::interval, 'failed', 'HTTP 429 quota exhausted (test)' FROM generate_series(1, 5) i"
    )
    db.execute(
        "INSERT INTO raw.ingestion_runs (job_name, started_at, status) VALUES ('zz_annex_job', now() - interval '2 minutes', 'completed')"
    )
    db.execute(
        "INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) VALUES ('zz_annex_provider', current_date, 55, 60)"
    )
    db.execute("SET TRANSACTION READ ONLY")
    return ids


def test_a1_is_the_week_of_one_account(db: psycopg.Connection, seeded: dict[str, int]) -> None:
    got = rows(db, "A1", cuenta=seeded["ana"])
    # 18 failures + 1 success + her mfa.reset, password.reset and user.created; the 40-day-old role change is left out
    assert len(got) == 22


def test_a2_is_the_privilege_changes_of_the_month_newest_first(
    db: psycopg.Connection, seeded: dict[str, int]
) -> None:
    mine = {seeded["ana"], seeded["beto"]}
    got = [row for row in rows(db, "A2") if row[3] in mine]
    assert [row[1] for row in got] == [
        "password.reset",
        "user.role_changed",
        "mfa.reset",
        "user.created",
    ]
    assert [row[4] for row in got if row[1] == "mfa.reset"] == ["command_line"]


def test_a3_is_what_an_account_wrote_in_the_console_this_week(
    db: psycopg.Connection, seeded: dict[str, int]
) -> None:
    got = rows(db, "A3", cuenta=seeded["owner"])
    assert [(row[1], row[2], row[3]) for row in got] == [("POST", "/api/v1/admin/users", "200")] * 3


def test_a4_lists_the_open_sessions_with_a_short_identifier(
    db: psycopg.Connection, seeded: dict[str, int]
) -> None:
    mine = [row for row in rows(db, "A4") if row[0] in (seeded["ana"], seeded["owner"])]
    assert len(mine) == 2, "the revoked session and the expired one are not open"
    assert mine[0][0] == seeded["ana"], "the most recently seen first"
    assert all(len(row[1]) == 8 for row in mine)


def test_a5_tells_a_sweep_from_a_targeted_attack(
    db: psycopg.Connection, seeded: dict[str, int]
) -> None:
    by_address = {row[0]: row for row in rows(db, "A5_1")}
    sweep = by_address["203.0.113.7"]
    assert (sweep[1], sweep[2]) == (25, 12), "one address, 25 failures, 12 different e-mails"
    by_account = {row[0]: row for row in rows(db, "A5_2")}
    ana = by_account[seeded["ana"]]
    assert (ana[1], ana[2]) == (18, 9), "one account, 18 failures, from 9 addresses"


def test_a6_translates_ids_into_e_mails(db: psycopg.Connection, seeded: dict[str, int]) -> None:
    emails = {row[1] for row in rows(db, "A6")}
    assert {"owner@guide.test", "ana@guide.test", "beto@guide.test"} <= emails


def test_a7_and_a8_show_the_failing_job_and_the_provider_near_its_budget(
    db: psycopg.Connection, seeded: dict[str, int]
) -> None:
    job = [row for row in rows(db, "A7") if row[0] == "zz_annex_job"]
    assert [(row[1], row[2], row[4]) for row in job] == [
        ("failed", 5, "HTTP 429 quota exhausted (test)")
    ]
    quota = [row for row in rows(db, "A8") if row[0] == "zz_annex_provider"]
    assert [(row[2], row[3], row[4]) for row in quota] == [(55, 60, 92)]


def test_a9_counts_the_connections_to_the_database_predigolctl_opens(
    db: psycopg.Connection,
) -> None:
    """A9 filters on the production database's name, ``fbi`` (the one ``predigolctl psql`` opens); the test database has another, so the filter is
    swapped for the current database to see that the rest of the query works."""
    assert "datname = 'fbi'" in QUERIES["A9"]
    assert "psql -U fbi -d fbi" in (
        Path(__file__).resolve().parents[2] / "deploy" / "vps" / "bin" / "predigolctl"
    ).read_text(encoding="utf-8")
    sql = QUERIES["A9"].replace("datname = 'fbi'", "datname = current_database()")
    got = db.execute(sql).fetchall()
    limit = db.execute("SHOW max_connections").fetchone()
    assert limit is not None
    assert got and all(row[3] == str(limit[0]) for row in got)


def test_a10_shows_the_schema_revision_and_the_key_counts(
    db: psycopg.Connection, seeded: dict[str, int]
) -> None:
    revision, _fixtures, _picks, accounts = rows(db, "A10")[0]
    assert revision == db.execute("SELECT version_num FROM public.alembic_version").fetchone()[0]  # type: ignore[index]
    assert accounts >= 3


def test_a12_is_the_register_of_incidents_with_what_the_owner_noted(db: psycopg.Connection) -> None:
    """A12 reads ``audit.incidents``, the view over the register that ``bin/incident-dump.sh`` fills from ``state/incidents.jsonl``. Seeded: a closed incident
    that a check opened, raised to SEV1 and closed, with the owner's notes (the newest answer of a field is the one shown); an open one; and one older than
    the 90 days, which stays out. The register's own tests are in ``test_migration_*_incident_register.py``; this one holds the columns A12 names."""
    events = (
        # incident, event, how long ago, alert key, service, severity, text, note field, minutes, who
        ("INC-2026-901", "open", "3 hours", "svc.api", "api", "SEV2", "api is down", None, None, "system"),
        ("INC-2026-901", "update", "170 minutes", "svc.api", "api", "SEV1", "api is down", None, None, "system"),
        ("INC-2026-901", "close", "2 hours", "svc.api", "api", "SEV1", "recuperado", None, 60, "system"),
        ("INC-2026-901", "note", "150 minutes", None, None, None, "no", "personal_data", None, "owner"),
        ("INC-2026-901", "note", "110 minutes", None, None, None, "disco lleno", "cause", None, "owner"),
        ("INC-2026-901", "note", "100 minutes", None, None, None, "12", "affected_users", None, "owner"),
        ("INC-2026-901", "note", "90 minutes", None, None, None, "si: correos de 12 titulares", "personal_data", None, "owner"),
        ("INC-2026-901", "note", "80 minutes", None, None, None, "volcados antiguos borrados", "repair", None, "owner"),
        ("INC-2026-901", "note", "70 minutes", None, None, None, "alerta de disco al 80 %", "prevention", None, "owner"),
        ("INC-2026-902", "open", "1 hour", "svc.api", "api", "SEV1", "api is down again", None, None, "owner"),
        ("INC-2026-800", "open", "100 days", "disk.root", "host", "SEV2", "disk at 82%", None, None, "system"),
        ("INC-2026-800", "close", "99 days", "disk.root", "host", "SEV2", "recuperado", None, 1440, "system"),
    )  # fmt: skip
    for number, row in enumerate(
        events
    ):  # the columns of a row are the placeholders after the two that make the hash
        db.execute(
            "INSERT INTO audit.incident_events (line_sha256, incident_id, event, at, alert_key, service, severity, body, field, minutes, actor, raw) "
            "VALUES (md5(%s) || md5(%s), %s, %s, now() - %s::interval, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)",
            (f"a{number}", f"b{number}", *row),
        )
    db.execute("SET TRANSACTION READ ONLY")
    got = {
        row[0]: row for row in rows(db, "A12") if row[0].startswith(("INC-2026-9", "INC-2026-8"))
    }
    assert list(got) == ["INC-2026-902", "INC-2026-901"], (
        "newest first, and the one of 100 days ago is outside the 90"
    )
    closed = got["INC-2026-901"]
    assert closed[1:3] == ("closed", "SEV1"), "the severity NOW: the update raised it"
    assert closed[4] == timedelta(hours=1)
    assert closed[5:] == (
        "svc.api",
        "api is down",
        "disco lleno",
        "12",
        "si: correos de 12 titulares",
        "volcados antiguos borrados",
        "alerta de disco al 80 %",
    ), "the newest note of each field: personal data was 'no' first and 'si' after"
    still_open = got["INC-2026-902"]
    assert still_open[1:3] == ("open", "SEV1") and still_open[4] is None
    assert still_open[7:] == (None,) * 5, (
        "nothing noted yet: the columns are empty, which is what the guide says to look for"
    )
