"""The Admin Console's list of backups (fbi.api.services.center.backups) on a server.

There the backups belong to root and the API runs as an unprivileged user: a folder it may not read lists
nothing - it must never turn the System page into a 500 (found in the VPS rehearsal of 7 Oct 2026).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from fbi.api.services import center


def test_dumps_and_backup_folders_are_listed_newest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "predigol-20261006T041500Z.dump").write_bytes(b"x" * 10)
    (tmp_path / "predigol-20261006T041500Z.json").write_text("{}")
    folder = tmp_path / "20261007T041500Z"
    folder.mkdir()
    (folder / "db.dump").write_bytes(b"y" * 7)
    os.utime(tmp_path / "predigol-20261006T041500Z.dump", (1_000_000_000, 1_000_000_000))
    monkeypatch.setenv("FBI_BACKUP_DIRS", str(tmp_path))
    found = center.backups()
    assert [(b.name, b.bytes) for b in found] == [("20261007T041500Z", 7), ("predigol-20261006T041500Z.dump", 10)]


def test_a_folder_the_api_may_not_read_lists_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    readable = tmp_path / "readable"
    readable.mkdir()
    (readable / "a.dump").write_bytes(b"z")
    closed = tmp_path / "closed"
    closed.mkdir()
    real_iterdir = Path.iterdir

    def iterdir(self: Path) -> Iterator[Path]:
        if self == closed:
            raise PermissionError(13, "Permission denied", str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    monkeypatch.setenv("FBI_BACKUP_DIRS", os.pathsep.join([str(closed), str(readable)]))
    assert [b.name for b in center.backups()] == ["a.dump"]
