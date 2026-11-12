"""OPS-005 - when a deploy may take the chain's restore-tested dump as its pre-deploy backup (deploy/vps/bin/reuse-dump.sh).

Every condition that fails means «make your own dump», as the deploy always did: the script can only remove a dump that
adds nothing, never one that protects.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "bin"
SCRIPT = BIN / "reuse-dump.sh"
NAME = "predigol-20261111T163354Z-auto-fa598f6"
STARTED = int(datetime(2026, 11, 11, 16, 33, 54, tzinfo=UTC).timestamp())
REV = "0134_period_annulment"


def _world(tmp_path: Path, *, result: dict[str, object] | None = None, manifest: dict[str, object] | None = None,
           body: bytes = b"a dump") -> tuple[Path, Path]:
    backups = tmp_path / "db"
    backups.mkdir()
    (backups / f"{NAME}.dump").write_bytes(body)
    described = {"bytes": len(b"a dump"), "sha256": hashlib.sha256(b"a dump").hexdigest(), "alembic_revision": REV}
    (backups / f"{NAME}.json").write_text(json.dumps({**described, **(manifest or {})}))
    tested = {"dump": NAME, "tested_at": "2026-11-11T17:19:00Z", "seconds": 1609, "passed": True, "failures": []}
    state = tmp_path / "restore-test.json"
    state.write_text(json.dumps({**tested, **(result or {})}))
    return backups, state


def _ask(backups: Path, state: Path, *, current: str = REV, head: str = REV, max_min: str = "120",
         minutes_later: int = 66) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), str(backups), str(state), current, head, max_min,
                           str(STARTED + minutes_later * 60)], capture_output=True, text=True, check=False, timeout=30)


def test_the_chains_proved_dump_of_the_same_schema_and_minutes_old_is_the_pre_deploy_backup(tmp_path: Path) -> None:
    out = _ask(*_world(tmp_path))
    assert out.returncode == 0 and out.stdout.strip() == NAME


@pytest.mark.parametrize(("result", "why"), [
    ({"passed": False, "failures": ["picks: 3 rows fewer"]}, "did not pass"),
    ({"passed": True, "failures": ["one"]}, "did not pass"),
    ({"passed": None, "skipped": "not enough disk"}, "did not pass"),
    ({"dump": "predigol-20261111T150110Z-auto-de1e29d"}, "no longer on the disk"),
    ({"dump": "../../etc/passwd"}, "names no dump"),
    ({"tested_at": "2026-11-11T16:00:00Z"}, "older than the dump"),
])
def test_a_restore_test_that_does_not_prove_this_dump_means_a_dump_of_its_own(
        tmp_path: Path, result: dict[str, object], why: str) -> None:
    out = _ask(*_world(tmp_path, result=result))
    assert out.returncode == 1 and why in out.stdout


def test_a_pending_migration_always_gets_its_own_dump(tmp_path: Path) -> None:
    out = _ask(*_world(tmp_path), head="0135_next")
    assert out.returncode == 1 and "a migration is pending" in out.stdout


def test_a_database_that_moved_since_the_dump_gets_its_own(tmp_path: Path) -> None:
    out = _ask(*_world(tmp_path), current="0135_next", head="0135_next")
    assert out.returncode == 1 and "moved to revision" in out.stdout


@pytest.mark.parametrize(("current", "head"), [("", REV), (REV, ""), ("", "")])
def test_a_revision_that_could_not_be_read_is_never_a_yes(tmp_path: Path, current: str, head: str) -> None:
    out = _ask(*_world(tmp_path), current=current, head=head)
    assert out.returncode == 1 and "could not be read" in out.stdout


def test_an_old_dump_is_not_reused_and_the_limit_is_the_callers(tmp_path: Path) -> None:
    backups, state = _world(tmp_path)
    assert _ask(backups, state, minutes_later=120).returncode == 0
    late = _ask(backups, state, minutes_later=121)
    assert late.returncode == 1 and "more than 120" in late.stdout
    assert _ask(backups, state, max_min="60", minutes_later=66).returncode == 1
    assert _ask(backups, state, minutes_later=-5).returncode == 1, "a dump dated in the future is not trusted"


@pytest.mark.parametrize("max_min", ["0", "", "soon", "-5"])
def test_the_reuse_can_be_switched_off_and_a_bad_limit_never_reuses(tmp_path: Path, max_min: str) -> None:
    assert _ask(*_world(tmp_path), max_min=max_min).returncode == 1


def test_a_file_that_is_not_the_one_that_was_tested_is_not_reused(tmp_path: Path) -> None:
    truncated = _ask(*_world(tmp_path, body=b"a du"))
    assert truncated.returncode == 1 and "size" in truncated.stdout
    other = tmp_path / "other"
    other.mkdir()
    changed = _ask(*_world(other, body=b"A dump"))
    assert changed.returncode == 1 and "sha256" in changed.stdout


def test_without_a_restore_test_on_record_the_deploy_makes_its_dump(tmp_path: Path) -> None:
    backups, state = _world(tmp_path)
    state.unlink()
    out = _ask(backups, state)
    assert out.returncode == 1 and "no restore test" in out.stdout


def test_the_deploy_asks_before_its_dump_and_still_makes_one_on_any_no() -> None:
    ctl = (BIN / "predigolctl").read_text(encoding="utf-8")
    ask = ctl.index('"$BIN/reuse-dump.sh"')
    own = ctl.index('"$BIN/backup.sh" --label "pre-deploy-$new_be"')
    migrate = ctl.index("ops alembic upgrade head")
    assert ask < own < migrate, "the question, then the deploy's own dump on a no, both before any migration"
    assert "PREDEPLOY_REUSE_MAX_MIN:-120" in ctl
    block = ctl[ask:own]
    assert "else" in block and "reusing" in block, "a yes is logged with the dump's name; a no falls through to backup.sh"


def test_the_backup_tells_the_rotation_which_dump_is_proved() -> None:
    backup = (BIN / "backup.sh").read_text(encoding="utf-8")
    assert "restore-test.json" in backup and '"$proved")"' in backup
