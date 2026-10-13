"""The server's weekly restore test (deploy/vps/bin/restore-test.sh) leaves nothing behind."""

from __future__ import annotations

import re
from pathlib import Path

BIN = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "bin"
SCRIPT = BIN / "restore-test.sh"


def test_the_restore_test_removes_its_throwaway_database() -> None:
    """Regression (13 Oct 2026): the throwaway container was removed with `docker rm -f`, which keeps the anonymous
    volume the postgres image declares for its data folder - every restored copy of the database stayed on the disk
    (seven of them, 78 GB, 40 % of the server's disk in five days), on the way to a full disk under the live one."""
    text = SCRIPT.read_text(encoding="utf-8")
    cleanup = re.search(r"^cleanup\(\) \{(.*?)\}$", text, flags=re.MULTILINE)
    assert cleanup is not None
    assert re.search(r"docker rm (-f -v|-fv|-vf|-v -f)\b", cleanup.group(1)), cleanup.group(1)
    assert "trap cleanup EXIT" in text, "removed on every way out, failures included"


def test_the_r2_restore_drill_removes_its_throwaway_database_too() -> None:
    text = (BIN / "r2-restore-drill.sh").read_text(encoding="utf-8")
    trap = re.search(r"^trap '(.*?)' EXIT$", text, flags=re.MULTILINE)
    assert trap is not None and re.search(r"docker rm (-f -v|-fv|-vf|-v -f)\b", trap.group(1)), text[:400]
