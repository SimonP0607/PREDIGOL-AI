"""Where pg_dump comes from: the host's own binary, or the database container's
through docker - and in neither case does the password reach a command line."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

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


def test_a_docker_stub_that_cannot_reach_the_daemon_is_passed_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """WSL with Docker Desktop's integration off: `docker` is a stub that only prints advice,
    `docker.exe` works. A backup taken with the stub wrote that advice as the dump."""
    tools = {"docker": "/mnt/c/Docker/resources/bin/docker", "docker.exe": "/mnt/c/Docker/resources/bin/docker.exe"}
    monkeypatch.setattr("fbi.ops.backup.shutil.which", lambda name: tools.get(name))
    monkeypatch.setattr("fbi.ops.backup._docker_works", lambda path: path.endswith(".exe"))
    monkeypatch.setenv(backup.PG_CONTAINER_ENV, "fbi-postgres")
    argv, _ = backup.pg_command("pg_dump", URL)
    assert argv[0] == "/mnt/c/Docker/resources/bin/docker.exe"


def test_when_no_docker_client_answers_the_first_is_kept_for_its_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = {"docker": "/usr/bin/docker", "docker.exe": "/mnt/c/Docker/docker.exe"}
    monkeypatch.setattr("fbi.ops.backup.shutil.which", lambda name: tools.get(name))
    monkeypatch.setattr("fbi.ops.backup._docker_works", lambda path: False)
    monkeypatch.setenv(backup.PG_CONTAINER_ENV, "fbi-postgres")
    argv, _ = backup.pg_command("pg_dump", URL)
    assert argv[0] == "/usr/bin/docker"


class _Calls:
    """Records every subprocess.run of the backup module and answers like a working docker."""

    def __init__(self) -> None:
        self.argv: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.argv.append(list(argv))
        text = bool(kwargs.get("text"))
        out: Any = "C:\\Users\\me\\backup\\db.dump\n" if argv[0] == "wslpath" else ("" if text else b"")
        return subprocess.CompletedProcess(argv, 0, out, "" if text else b"")


def _container(monkeypatch: pytest.MonkeyPatch, docker: str) -> _Calls:
    monkeypatch.setattr("fbi.ops.backup.shutil.which", lambda name: docker if name.startswith("docker") else None)
    monkeypatch.setattr("fbi.ops.backup._docker_works", lambda path: True)
    monkeypatch.setenv(backup.PG_CONTAINER_ENV, "fbi-postgres")
    calls = _Calls()
    monkeypatch.setattr("fbi.ops.backup.subprocess.run", calls)
    return calls


def test_a_container_dump_is_written_inside_and_copied_out(monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: Path) -> None:
    """Streaming a multi-GB dump back through `docker exec` stalls under WSL interop and
    never ends; the dump goes to a file in the container and `docker cp` brings it out."""
    calls = _container(monkeypatch, "/usr/bin/docker")
    proc = backup.run_dump(URL, tmp_path / "db.dump")
    assert proc.returncode == 0
    dump, copy, drop = calls.argv
    assert dump[:5] == ["/usr/bin/docker", "exec", "-i", "fbi-postgres", "pg_dump"]
    inner = next(a for a in dump if a.startswith("--file=")).removeprefix("--file=")
    assert inner.startswith("/tmp/") and "--dbname=fbi" in dump
    assert copy == ["/usr/bin/docker", "cp", f"fbi-postgres:{inner}", str(tmp_path / "db.dump")]
    assert drop == ["/usr/bin/docker", "exec", "fbi-postgres", "rm", "-f", inner]
    assert not any("s3cret" in a for argv in calls.argv for a in argv)


def test_the_windows_docker_client_gets_a_windows_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _container(monkeypatch, "/mnt/c/Docker/docker.exe")
    backup.run_dump(URL, tmp_path / "db.dump")
    assert ["wslpath", "-w", str(tmp_path / "db.dump")] in calls.argv
    copy = next(a for a in calls.argv if a[1:2] == ["cp"])
    assert copy[-1] == "C:\\Users\\me\\backup\\db.dump"


def test_a_container_restore_copies_the_dump_in_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _container(monkeypatch, "/usr/bin/docker")
    dump = tmp_path / "db.dump"
    dump.write_bytes(b"PGDMP")
    proc = backup.run_restore(URL, "fbi_restore_x", dump)
    assert proc.returncode == 0
    copy, restore, drop = calls.argv
    inner = copy[-1].removeprefix("fbi-postgres:")
    assert copy == ["/usr/bin/docker", "cp", str(dump), f"fbi-postgres:{inner}"]
    assert restore[:5] == ["/usr/bin/docker", "exec", "-i", "fbi-postgres", "pg_restore"]
    assert restore[-1] == inner and "--dbname=fbi_restore_x" in restore
    assert drop[-1] == inner


def test_no_tools_and_no_container_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fbi.ops.backup.shutil.which", lambda name: None)
    monkeypatch.delenv(backup.PG_CONTAINER_ENV, raising=False)
    with pytest.raises(FileNotFoundError, match="FBI_PG_CONTAINER"):
        backup.pg_command("pg_dump", URL)


# ── a gate that always fails on a live system is a gate people ignore ───────


def _restored_like(
    manifest_tables: dict[str, dict[str, Any]], **overrides: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """What the restored database fingerprints to: the manifest, with the named tables
    carrying different numbers because they were written to after the dump."""
    restored = {k: dict(v) for k, v in manifest_tables.items()}
    restored.update(overrides)
    return restored


def test_a_table_written_to_during_the_dump_is_not_a_failure() -> None:
    """The manifest fingerprints the database AFTER the dump, so a table that grew in
    between legitimately differs from what the dump holds - the dump is a consistent
    snapshot of an earlier moment. The backup already lists those tables; failing on them
    reported "the database was live" as a corrupt backup, and that FAIL fired on every
    run against a working system."""
    from fbi.ops.backup import _compare_tables

    tables: dict[str, dict[str, Any]] = {"core.fixtures": {"rows": 10, "fp": "a"},
                                         "core.fixture_events": {"rows": 100, "fp": "b"}}
    manifest: dict[str, Any] = {"tables": tables,
                                "changed_during_dump": ["core.fixture_events"]}
    restored = _restored_like(tables,
                              **{"core.fixture_events": {"rows": 90, "fp": "c"}})

    check = _compare_tables(manifest, restored)

    assert check.passed, "the only difference is in a table the dump itself flagged"
    assert "not comparable" in check.detail
    assert "core.fixture_events" in check.detail


def test_a_table_nobody_wrote_to_that_differs_is_still_a_failure() -> None:
    """The check must keep its teeth: a quiescent table that does not come back the same
    is a real fault in the backup."""
    from fbi.ops.backup import _compare_tables

    tables: dict[str, dict[str, Any]] = {"core.fixtures": {"rows": 10, "fp": "a"}}
    manifest: dict[str, Any] = {"tables": tables,
                                "changed_during_dump": ["core.fixture_events"]}
    restored = _restored_like(tables,
                              **{"core.fixtures": {"rows": 9, "fp": "z"}})

    check = _compare_tables(manifest, restored)

    assert not check.passed
    assert "DIFFER" in check.detail and "core.fixtures" in check.detail


def test_a_quiescent_dump_still_compares_every_table() -> None:
    from fbi.ops.backup import _compare_tables

    tables: dict[str, dict[str, Any]] = {"core.fixtures": {"rows": 10, "fp": "a"}}
    manifest: dict[str, Any] = {"tables": tables, "changed_during_dump": []}

    check = _compare_tables(manifest, _restored_like(tables))

    assert check.passed and "identical" in check.detail
