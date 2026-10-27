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
    """Same rule for the drill on the owner's machine: the container goes with its anonymous volume, on every way out. Only an
    explicit --keep (to look at the restored database) leaves it, and then the drill says so."""
    text = (BIN / "r2-restore-drill.sh").read_text(encoding="utf-8")
    cleanup = re.search(r"^cleanup\(\) \{(.*?)\}$", text, flags=re.MULTILINE)
    assert cleanup is not None, text[:400]
    assert re.search(r"docker rm (-f -v|-fv|-vf|-v -f)\b", cleanup.group(1)), cleanup.group(1)
    assert "left in place" in cleanup.group(1), "--keep is announced, not silent"
    assert "trap cleanup EXIT" in text, "removed on every way out, failures included"


def test_the_r2_drill_gives_its_container_the_dump_as_a_stream_not_a_bind_mount() -> None:
    """The drill runs on the owner's laptop, where `docker` can be the Windows one reached from WSL (Docker Desktop's integration is
    off, so a shim calls docker.exe): a bind mount of a WSL folder (`-v "$work:/dump"`) is resolved by the Docker daemon on ITS side,
    finds nothing, and the restore would run on an empty folder. A tar stream on stdin (`docker cp -`) works with any docker."""
    text = (BIN / "r2-restore-drill.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert re.search(r"\|\s*docker cp - \"\$box:/dump\"", code), (
        "the dump goes in through `docker cp -`"
    )
    assert not re.search(r"\s-v\s+\"?\$work", code), "no bind mount of the working folder"
    assert not re.search(r"--volume\b|--mount\b", code), "no other way of sharing a folder either"
    # the readiness probe goes through the container's TCP loopback: the image's first, temporary server has no TCP listener
    assert "pg_isready -h 127.0.0.1" in code
    # the plain dump is the one thing that must not stay on the machine: it is removed as soon as the container has it
    assert re.search(r"docker cp -[^\n]*\n\s*rm -f \"\$work/\$name\.dump\"", code)


def test_the_r2_restore_drill_can_keep_the_encrypted_dump_for_the_monthly_offline_copy() -> None:
    """--save-encrypted DIR copies the downloaded (encrypted) dump and its manifest before anything is deleted; the plain dump never
    goes there. A failure to save is a failure of the drill, not a silent gap in the owner's offline copy."""
    text = (BIN / "r2-restore-drill.sh").read_text(encoding="utf-8")
    assert "--save-encrypted)" in text
    save = re.search(r"if \[\[ -n \"\$SAVE_DIR\" \]\]; then(.*?)\nfi\n", text, flags=re.DOTALL)
    assert save is not None, "the saving block"
    block = save.group(1)
    assert '"$work/$name.dump.age"' in block and '"$work/$name.json"' in block
    assert '"$work/$name.dump"' not in block.replace('"$work/$name.dump.age"', ""), (
        "the plain dump is never copied out"
    )
    assert "|| fail" in block
    assert text.index('SAVE_DIR" ]]; then') < text.index('rm -f "$work/$name.dump.age"'), (
        "saved before the encrypted file is removed"
    )
