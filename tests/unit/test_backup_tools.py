"""Where pg_dump comes from: the host's own binary, or the database container's
through docker - and in neither case does the password reach a command line."""

from __future__ import annotations

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
