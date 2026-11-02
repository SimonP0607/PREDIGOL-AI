"""bin/incident-dump.sh: the mirror of state/incidents.jsonl into audit.incident_events (security plan S3).

The FILE is the truth (the checks write it, so it works with the database down); the table is its mirror, filled in whenever the database
answers, so that the register of incidents travels inside the dumps and the point-in-time copies. These tests run the real scripts of
deploy/vps/bin (the owner's pen, the library of alerts, the mirror) in a folder that plays the host, against a scratch database built by
the migrations up to the one that creates the register: idempotency by the sha256 of the exact line, counts only in the log, the lines a
table refuses, text that tries to be SQL, a database that does not answer, and one restored from an older copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import conninfo_to_dict

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn
from tests.unit._vps_sandbox import BIN, tools_present

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (tools_present() and shutil.which("psql")),
        reason="bash, jq, flock, sha256sum and psql are needed",
    ),
]
SCRATCH = "fbi_test_incdump"
NOW = int(datetime(2026, 10, 26, 16, 0, tzinfo=UTC).timestamp())


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _register_revision() -> tuple[str, str]:
    """(the revision that creates the register, the one before it): found by the name of its file, whatever number it gets when it is packaged."""
    scripts = [
        rev
        for rev in ScriptDirectory.from_config(_cfg()).walk_revisions()
        if rev.path and rev.path.endswith("_incident_register.py")
    ]
    assert len(scripts) == 1, "exactly one migration creates the incident register"
    assert isinstance(scripts[0].down_revision, str)
    return scripts[0].revision, scripts[0].down_revision


@contextmanager
def _migrating(dsn: str) -> Iterator[None]:
    previous = os.environ.get("FBI_DATABASE_URL")
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous


def _uri(dsn: str, port: int | None = None) -> str:
    """The DSN as a URI without spaces (INCIDENT_PSQL is split into words), optionally with another port: a database that does not answer."""
    parts = conninfo_to_dict(dsn)
    user = quote(str(parts.get("user", "postgres")))
    password = f":{quote(str(parts['password']))}" if parts.get("password") else ""
    host = parts.get("host", "127.0.0.1")
    return (
        f"postgresql://{user}{password}@{host}:{port or parts.get('port', 5432)}/{parts['dbname']}"
    )


@pytest.fixture(scope="module")
def scratch_dsn(migrated_database: str) -> Iterator[str]:
    """A scratch database at the revision that creates the register (the dump needs nothing later)."""
    revision, _ = _register_revision()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (SCRATCH,),
        )
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    try:
        with _migrating(dsn):
            command.upgrade(_cfg(), revision)
        yield dsn
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (SCRATCH,),
            )
            admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


@pytest.fixture
def table(scratch_dsn: str) -> Iterator[psycopg.Connection[Any]]:
    """The scratch database with an EMPTY register (it refuses DELETE; the owner of the table may switch its trigger off to clear it between tests)."""
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("ALTER TABLE audit.incident_events DISABLE TRIGGER USER")
        c.execute("DELETE FROM audit.incident_events")
        c.execute("ALTER TABLE audit.incident_events ENABLE TRIGGER USER")
        yield c


class Host:
    """A folder that plays the server: bin/ with the real scripts and a stand-in lib.sh (STATE, log, a channel that writes down what it is given)."""

    def __init__(self, root: Path, dsn: str) -> None:
        self.root, self.dsn = root, dsn
        self.bin, self.state = root / "bin", root / "state"
        self.bin.mkdir()
        self.state.mkdir()
        for name in ("alerts_lib.sh", "incident.sh", "incident-dump.sh"):
            shutil.copy(BIN / name, self.bin / name)
        (self.bin / "lib.sh").write_text(
            f'STATE="{self.state}"; PREDIGOL_DATA="{root}"\n'
            f'log() {{ printf \'%s\\n\' "$*" >> "{root}/log"; }}\n'
            f'notify_ok() {{ printf \'%s\\n\' "$*" >> "{root}/sent"; return 0; }}\n'
        )
        self.file = self.state / "incidents.jsonl"

    def _env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("INCIDENT_", "ALERTS_"))}
        env.update(
            INCIDENT_NOW=str(NOW), INCIDENT_NO_DUMP="1", INCIDENT_PSQL=f"psql {_uri(self.dsn)}"
        )
        env.update(extra)
        return env

    def pen(self, *args: str) -> subprocess.CompletedProcess[str]:
        """One command of the owner's pen (predigolctl incident ...)."""
        result = subprocess.run(
            ["bash", str(self.bin / "incident.sh"), *args],
            env=self._env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    def check_pass(self, epoch: int, text: str | None = None) -> None:
        """One pass of a check of the server: disk.usage is open at SEV2 while there is a text, and recovers when there is none."""
        script = (
            f'set -u\n. "{self.bin}/lib.sh"; . "{self.bin}/alerts_lib.sh"\n'
            f"export ALERTS_NOW={epoch}\n"
            'alerts_begin; if [[ -n "${1:-}" ]]; then alert_set disk.usage SEV2 "$1"; fi; alerts_end\n'
        )
        subprocess.run(
            ["bash", "-c", script, "check", *([text] if text else [])],
            env=self._env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )

    def dump(self, *args: str, port: int | None = None, now: int = NOW) -> int:
        """One run of the mirror; port= points it at a port where no database listens. Returns the exit status."""
        extra = {"INCIDENT_DUMP_NOW": str(now), "ALERTS_NOW": str(now)}
        if port is not None:
            extra["INCIDENT_PSQL"] = f"psql {_uri(self.dsn, port)} -w"
        return subprocess.run(
            ["bash", str(self.bin / "incident-dump.sh"), *args],
            env=self._env(**extra),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        ).returncode

    def story(self) -> int:
        """The register of a bad afternoon: one incident the owner opened and closed with notes, one a check opened and the owner made SEV1. Returns its lines."""
        self.pen(
            "open", "web", "SEV1", "la web no responde desde fuera", "--at", "2026-10-26T15:02Z"
        )
        self.pen(
            "note",
            "INC-2026-001",
            "cause",
            "falta de memoria del servidor por un pico de peticiones",
        )
        self.pen("note", "INC-2026-001", "affected_users", "12")
        self.pen("severity", "INC-2026-001", "SEV2", "ya funciona desde dentro")
        self.check_pass(
            int(datetime(2026, 10, 26, 15, 30, tzinfo=UTC).timestamp()), "disco al 82 %"
        )
        self.pen("severity", "INC-2026-002", "SEV1", "el disco crece rápido")
        self.check_pass(int(datetime(2026, 10, 26, 15, 50, tzinfo=UTC).timestamp()))
        self.pen(
            "close",
            "INC-2026-001",
            "reiniciado el contenedor de Caddy",
            "--at",
            "2026-10-26T15:30Z",
        )
        self.pen("note", "INC-2026-001", "prevention", "vigilar la memoria de Caddy")
        return self.lines()

    def lines(self) -> int:
        return sum(1 for ln in self.file.read_text(encoding="utf-8").splitlines() if ln)

    def append(self, *lines: str) -> None:
        with self.file.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")

    @property
    def log(self) -> str:
        path = self.root / "log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @property
    def sent(self) -> list[str]:
        path = self.root / "sent"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    @property
    def mark(self) -> dict[str, Any]:
        return json.loads((self.state / "incident-dump.json").read_text())

    def open_alerts(self) -> set[str]:
        path = self.state / "alerts.json"
        return set(json.loads(path.read_text())) if path.exists() else set()


@pytest.fixture
def host(tmp_path: Path, scratch_dsn: str, table: psycopg.Connection[Any]) -> Host:
    return Host(tmp_path, scratch_dsn)


def _count(c: psycopg.Connection[Any]) -> int:
    row = c.execute("SELECT count(*) FROM audit.incident_events").fetchone()
    assert row is not None
    return int(row[0])


def _hashes(c: psycopg.Connection[Any]) -> set[str]:
    return {row[0] for row in c.execute("SELECT line_sha256 FROM audit.incident_events").fetchall()}


def _line(**kw: Any) -> str:
    return json.dumps(kw, separators=(",", ":"), ensure_ascii=False)


def test_a_dry_run_counts_the_lines_and_writes_nothing(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    n = host.story()
    assert host.dump("--dry-run") == 0
    assert _count(table) == 0
    assert not (host.state / "incident-dump.json").exists()
    assert host.log == "", "a dry run says nothing to the log"
    assert n >= 9


def test_the_first_run_copies_every_line_and_the_log_holds_counts_only(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    n = host.story()
    assert host.dump() == 0
    assert _count(table) == n
    assert host.log.splitlines() == [
        f"incident-dump: {n} line(s): {n} added, 0 already there, 0 refused"
    ], "one line, counts only: the text of the register never reaches the log"
    mark = host.mark
    assert (mark["lines"], mark["added"], mark["already"], mark["rejected"]) == (n, n, 0, 0)


def test_a_second_run_finds_the_same_file_and_does_not_even_log(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    n = host.story()
    assert host.dump() == 0
    (host.root / "log").write_text("")
    assert host.dump() == 0
    assert _count(table) == n
    assert host.log == "", "the file is the one already mirrored: nothing to do and nothing to say"
    assert host.dump("--force") == 0
    assert f"0 added, {n} already there" in host.log
    assert _count(table) == n


def test_the_view_tells_each_incident_with_what_the_owner_noted(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    host.story()
    assert host.dump() == 0
    rows = table.execute(
        "SELECT incident_id, state, severity, detection, cause, affected_users, prevention, duration::text "
        "FROM audit.incidents ORDER BY incident_id"
    ).fetchall()
    assert rows == [
        (
            "INC-2026-001",
            "closed",
            "SEV2",
            "owner",
            "falta de memoria del servidor por un pico de peticiones",
            "12",
            "vigilar la memoria de Caddy",
            "00:28:00",
        ),
        ("INC-2026-002", "closed", "SEV1", "server check", None, None, None, "00:20:00"),
    ]


def test_new_lines_are_added_and_old_ones_are_not(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    n = host.story()
    assert host.dump() == 0
    host.pen("open", "dns", "SEV3", "el registro MX tarda en propagarse")
    assert host.dump() == 0
    assert _count(table) == n + 1
    assert f"1 added, {n} already there" in host.log


def test_a_line_the_table_refuses_does_not_stop_the_rest_and_the_alert_is_for_new_refusals(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    host.story()
    assert host.dump() == 0
    before = _count(table)
    host.append(
        "esto no es json",
        "[1,2,3]",
        _line(
            at="2026-10-26T17:00:00Z",
            event="open",
            incident="INC-26-7",
            key="x.y",
            service="x",
            severity="SEV2",
            text="id mal formado",
        ),
        _line(
            at="2026-10-26T17:01:00Z",
            event="open",
            incident="INC-2026-050",
            key="x.y",
            service="x",
            severity="SEV2",
            text="esta sí",
        ),
    )
    assert host.dump() == 0
    assert _count(table) == before + 1, "the good line is in; the three bad ones are not"
    assert "3 refused" in host.log
    assert "incidents.dump" in host.open_alerts()
    assert "3 línea(s) nueva(s) del registro de incidentes no se pudieron copiar" in host.sent[-1]
    everything = host.log + "\n".join(host.sent)
    assert "esto no es json" not in everything and "id mal formado" not in everything
    # the next pass sees no NEW refused line: it closes the alert, and copies what the file gained meanwhile (the alert's own opening line)
    assert host.dump() == 0
    assert "incidents.dump" not in host.open_alerts()


def test_text_that_tries_to_be_sql_goes_in_as_data_and_comes_out_as_it_went_in(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    host.story()
    nasty = {
        "INC-2026-060": "a\\b \\. \\\\ \"q\" '$$' $x$ ; DROP TABLE audit.incident_events; -- ñ 日本 \t tab",
        "INC-2026-061": "\\.",
        "INC-2026-062": "fin\\nlinea \\r retorno",
    }
    written = {
        incident: _line(
            at="2026-10-26T18:00:00Z",
            event="open",
            incident=incident,
            key=f"web.{i}",
            service="web",
            severity="SEV2",
            text=text,
        )
        for i, (incident, text) in enumerate(nasty.items())
    }
    host.append(*written.values())
    assert host.dump() == 0
    for incident, text in nasty.items():
        row = table.execute(
            "SELECT line_sha256, body FROM audit.incident_events WHERE incident_id = %s",
            (incident,),
        ).fetchone()
        assert row is not None, f"{incident}: the line was refused"
        assert row[0] == hashlib.sha256(written[incident].encode()).hexdigest(), (
            "the hash is that of the exact line of the file"
        )
        assert row[1] == text, "the text came out as it went in"
    assert _count(table) == host.lines()


def test_a_database_that_does_not_answer_is_not_a_reason_to_bother_anyone_for_one_failure(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    host.story()
    assert host.dump() == 0
    good = host.mark
    (host.root / "log").write_text("")
    sent = len(host.sent)
    assert host.dump("--force", port=1) == 0, "exit 0: the timer must not flap"
    assert "the database did not take the register" in host.log
    assert len(host.sent) == sent, "one failure says nothing to the channel"
    assert host.mark["file_sha256"] == good["file_sha256"], (
        "the mark keeps the hash of the last good run"
    )


def test_a_day_without_a_copy_is_told_once_and_closes_when_the_database_is_back(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    host.story()
    assert host.dump() == 0
    mark = host.mark
    mark["ok_at"] = "2026-10-24T10:00:00Z"
    (host.state / "incident-dump.json").write_text(json.dumps(mark))
    assert host.dump("--force", port=1) == 0
    assert "lleva más de 24 h sin copiarse a la base de datos" in host.sent[-1]
    told = len(host.sent)
    assert host.dump("--force", port=1) == 0
    assert len(host.sent) == told, "once, not at every pass"
    assert "incidents.dump" in host.open_alerts()
    assert host.dump("--force") == 0, "the database is back"
    assert "incidents.dump" not in host.open_alerts()
    assert host.sent[-1].startswith("[recuperado] incidents.dump")


def test_a_mirror_that_has_never_worked_is_told_after_a_day_too(
    host: Host, table: psycopg.Connection[Any]
) -> None:
    """The table is missing, or a role is wrong: no copy was ever made. Counting from the last good copy alone would keep such a mirror silent for ever
    and the register would never travel with the database copies; so the first failed attempt starts the day."""
    n = host.story()
    before = len(host.sent)  # the story itself told the owner of its alerts
    assert host.dump(port=1) == 0
    assert len(host.sent) == before and "first_try_at" in host.mark and "ok_at" not in host.mark
    assert host.dump(port=1, now=NOW + 23 * 3600) == 0
    assert len(host.sent) == before, "23 hours: still nothing to say"
    assert host.mark["first_try_at"] == "2026-10-26T16:00:00Z", (
        "the day is counted from the first attempt, not from the last"
    )
    assert host.dump(port=1, now=NOW + 25 * 3600) == 0
    assert "lleva más de 24 h sin copiarse a la base de datos" in host.sent[-1]
    told = len(host.sent)
    assert host.dump(port=1, now=NOW + 26 * 3600) == 0
    assert len(host.sent) == told, "once, not at every pass"
    assert host.dump("--force", now=NOW + 27 * 3600) == 0, "the database is there at last"
    assert _count(table) == n + 1, (
        "the story and the opening of the alert (its closing comes after the copy)"
    )
    assert "ok_at" in host.mark and "first_try_at" not in host.mark
    assert "incidents.dump" not in host.open_alerts()
    assert host.sent[-1].startswith("[recuperado] incidents.dump")


# Ways a database can answer and still be unable to take the register AS A WHOLE (the cause is the database's, the same for every line), as opposed to refusing
# one bad line: what to do to the scratch database to make it so, what undoes it, and the state code the log must name.
UNABLE = {
    "table": (
        "ALTER TABLE audit.incident_events RENAME TO incident_events_away",
        "ALTER TABLE audit.incident_events_away RENAME TO incident_events",
        "42P01",  # undefined_table: the timer was enabled before the migration
    ),
    "column": (
        "ALTER TABLE audit.incident_events RENAME COLUMN raw TO raw_away",
        "ALTER TABLE audit.incident_events RENAME COLUMN raw_away TO raw",
        "42703",  # undefined_column: a table of another shape than the script expects
    ),
}


@pytest.mark.parametrize("shape", list(UNABLE))
def test_a_database_that_cannot_take_the_register_is_a_failed_mirror_not_a_pile_of_refused_lines(
    host: Host, table: psycopg.Connection[Any], shape: str
) -> None:
    """The table is not there (the timer was enabled before the migration) or has another shape: every line fails for the SAME reason, which is not the line's.
    Counting them as refused wrote down a good copy that never happened (ok_at), told the owner of 'new refused lines' at once and 'recovered' on the next pass,
    and stopped trying while the file stayed the same. It is a failed mirror: nothing is written down as good, one failure says nothing, a day of them says so
    once, and the copy is complete as soon as the database can take it."""
    away, back, code = UNABLE[shape]
    n = host.story()
    before = len(host.sent)  # the story itself told the owner of its alerts
    table.execute(away)
    try:
        assert host.dump() == 0
        assert host.log.splitlines() == [
            f"incident-dump: the database did not take the register (exit 3, SQLSTATE {code}); the file keeps every line, the next run tries again"
        ], (
            "one line: the exit status and the state code, never the message of the error (it can quote a row), and no line was refused: none could be taken"
        )
        assert "first_try_at" in host.mark and "ok_at" not in host.mark, (
            "no good copy is written down"
        )
        assert "rejected" not in host.mark, (
            "the counts of a copy that never happened are not written either"
        )
        assert "incidents.dump" not in host.open_alerts() and len(host.sent) == before, (
            "one failure says nothing"
        )
        assert host.dump(now=NOW + 23 * 3600) == 0
        assert len(host.sent) == before, "23 hours: still nothing to say"
        assert host.dump(now=NOW + 25 * 3600) == 0
        assert "lleva más de 24 h sin copiarse a la base de datos" in host.sent[-1]
        told = len(host.sent)
        assert host.dump(now=NOW + 26 * 3600) == 0
        assert len(host.sent) == told, "once, not at every pass"
    finally:
        table.execute(back)
    assert host.dump(now=NOW + 27 * 3600) == 0, "the database can take it at last"
    assert _count(table) == n + 1, (
        "the story and the opening of the alert (its closing comes after the copy)"
    )
    assert "ok_at" in host.mark and "first_try_at" not in host.mark
    assert "incidents.dump" not in host.open_alerts()
    assert host.sent[-1].startswith("[recuperado] incidents.dump")


@pytest.mark.parametrize(
    "mark",
    ["{}", "not json at all", '{"ok_at": ""}', '{"first_try_at": "garbage"}', '{"ok_at": "ayer"}'],
)
def test_a_mark_that_cannot_say_when_it_started_starts_its_day_at_the_next_failure(
    host: Host, table: psycopg.Connection[Any], mark: str
) -> None:
    """The mark is the script's own file, but a hand edit or a half written one must not turn the silence into a permanent one."""
    host.story()
    (host.state / "incident-dump.json").write_text(mark)
    before = len(host.sent)
    assert host.dump(port=1) == 0
    assert host.mark["first_try_at"] == "2026-10-26T16:00:00Z"
    assert len(host.sent) == before
    assert host.dump(port=1, now=NOW + 25 * 3600) == 0
    assert "lleva más de 24 h sin copiarse a la base de datos" in host.sent[-1]


def test_a_database_restored_from_an_older_copy_gets_every_line_back_and_none_twice(
    host: Host, table: psycopg.Connection[Any], scratch_dsn: str
) -> None:
    host.story()
    host.append(
        "esto no es json",
        "[1,2,3]",
        _line(
            at="2026-10-26T17:00:00Z",
            event="open",
            incident="INC-26-7",
            key="x.y",
            service="x",
            severity="SEV2",
            text="mal",
        ),
    )
    assert host.dump() == 0
    accepted = _hashes(table)
    assert host.mark["rejected"] == 3
    # a restore to a point before the register existed drops it; deploying again makes it again, empty
    revision, before = _register_revision()
    with _migrating(scratch_dsn):
        command.downgrade(_cfg(), before)
        command.upgrade(_cfg(), revision)
    assert _count(table) == 0
    assert host.dump("--force") == 0
    back = _hashes(table)
    # the first run raised its alert for the three refused lines AFTER copying, so the file gained one line since: the alert's own opening
    assert accepted < back and len(back - accepted) == 1, (
        "every line it took before is back, none twice"
    )
    opening = table.execute(
        "SELECT event, alert_key, severity FROM audit.incident_events WHERE line_sha256 = ANY(%s)",
        (list(back - accepted),),
    ).fetchall()
    assert opening == [("open", "incidents.dump", "SEV3")]
    assert "incidents.dump" not in host.open_alerts(), "the three lines it never took are not new"
