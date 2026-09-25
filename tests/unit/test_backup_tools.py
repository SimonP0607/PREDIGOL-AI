"""Where pg_dump comes from: the host's own binary, or the database container's
through docker - and in neither case does the password reach a command line."""

from __future__ import annotations

import pytest

from fbi.ops import backup

URL = "postgresql://fbi:s3cret-value@localhost:5433/fbi"


def test_the_host_binary_gets_the_password_through_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fbi.ops.backup.shutil.which", lambda name: f"/usr/bin/{name}" if name == "pg_dump" else None)
    argv, env = backup.pg_command("pg_dump", URL)
    assert argv == ["/usr/bin/pg_dump", "--host=localhost", "--port=5433", "--username=fbi"]
    assert env["PGPASSWORD"] == "s3cret-value"
    assert not any("s3cret" in a for a in argv)


def test_without_client_tools_the_container_runs_them(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = {"docker.exe": "/mnt/c/Docker/docker.exe"}
    monkeypatch.setattr("fbi.ops.backup.shutil.which", lambda name: tools.get(name))
    monkeypatch.setenv(backup.PG_CONTAINER_ENV, "fbi-postgres")
    argv, _ = backup.pg_command("pg_restore", URL)
    assert argv == ["/mnt/c/Docker/docker.exe", "exec", "-i", "fbi-postgres", "pg_restore", "--username=fbi"]
    assert not any("s3cret" in a for a in argv), "the container's local socket needs no password"


def test_no_tools_and_no_container_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fbi.ops.backup.shutil.which", lambda name: None)
    monkeypatch.delenv(backup.PG_CONTAINER_ENV, raising=False)
    with pytest.raises(FileNotFoundError, match="FBI_PG_CONTAINER"):
        backup.pg_command("pg_dump", URL)
