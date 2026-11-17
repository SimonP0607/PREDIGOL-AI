"""AD-A07 (IA-059): the backups and their restore test cover every schema - the new ones of the plan included - and every append-only
trigger. pg_dump is given no list of schemas, so a new schema is in the dump; the backup now NAMES them all, with every ``*_append_only``
trigger, and the restore test proves each came back (a restore that lost a trigger would give back an audit table that can be rewritten).

The server's scripts run for real (deploy/vps/bin/backup.sh and restore-test.sh) against stand-ins for docker; the module of the dev
machine (``fbi.ops.backup``) is checked through its pure comparison."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from fbi.ops import backup
from tests.unit._vps_sandbox import BIN, Sandbox, tools_present

pytestmark = pytest.mark.skipif(not tools_present(), reason="needs bash, jq, flock and sha256sum")

CATALOG = {"schemas": ["ai", "intel", "news", "public"],
           "append_only": ["ai.evidence:evidence_append_only", "intel.capability_transitions:capability_transitions_append_only"]}
NOW = "2026-10-26 04:19:00 UTC"


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def test_the_backup_names_every_schema_and_append_only_trigger(sb: Sandbox) -> None:
    sb.set_env(BACKUP_RCLONE_REMOTE=None, BACKUP_AGE_RECIPIENT=None)
    sb.set_docker(catalog=CATALOG)
    result = sb.run("backup.sh", FAKE_NOW=NOW)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads(next(sb.backups.glob("predigol-*.json")).read_text())
    assert manifest["catalog"] == CATALOG


def test_a_database_that_does_not_answer_the_catalog_leaves_a_valid_manifest(sb: Sandbox) -> None:
    """The backup never fails for want of the catalog (a deploy's backup is the first step of the chain): the manifest says null."""
    sb.set_env(BACKUP_RCLONE_REMOTE=None, BACKUP_AGE_RECIPIENT=None)
    result = sb.run("backup.sh", FAKE_NOW=NOW)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads(next(sb.backups.glob("predigol-*.json")).read_text())
    assert manifest["catalog"] is None and manifest["counts_before"]


# ---- restore-test.sh ------------------------------------------------------------------------------------------------------------------

RESTORE_DOCKER = """#!/usr/bin/env bash
# a stand-in for the throwaway restore server: what restore-test.sh asks of docker
case "$1" in
  rm|run) exit 0 ;;
  logs) echo "PostgreSQL init process complete"; exit 0 ;;
  compose) echo 1000; exit 0 ;;
  exec)
    shift 2
    case "$1" in
      pg_isready|pg_restore) exit 0 ;;
      psql)
        sql="${@: -1}"
        case "$sql" in
          *alembic_version*) echo 0138 ;;
          *pg_trigger*) printf '%s\\n' $RESTORED_TRIGGERS ;;
          *pg_namespace*) printf '%s\\n' $RESTORED_SCHEMAS pg_catalog information_schema ;;
          *count*) echo 10 ;;
        esac
        exit 0 ;;
    esac ;;
esac
exit 0
"""
DF = """#!/usr/bin/env bash
printf 'Filesystem 1024-blocks Used Available Capacity Mounted\\nstand-in 999999999 1 999999999 1%% /\\n'
"""


def _restore(sb: Sandbox, manifest: dict, *, schemas: list[str], triggers: list[str]) -> tuple[subprocess.CompletedProcess[str], dict]:
    for name, body in (("docker", RESTORE_DOCKER), ("df", DF)):
        path = sb.stubs / name
        path.write_text(body)
        path.chmod(0o755)
    sb.backups.mkdir(parents=True, exist_ok=True)
    dump = sb.backups / "predigol-20261026T041900Z.dump"
    dump.write_bytes(b"PGDMP-stand-in")
    sha = subprocess.run(["sha256sum", str(dump)], capture_output=True, text=True, check=True).stdout.split()[0]
    (sb.backups / "predigol-20261026T041900Z.json").write_text(json.dumps(
        {"sha256": sha, "alembic_revision": "0138", "counts_before": {"core.fixtures": 10}, "counts_after": {"core.fixtures": 10},
         **manifest}))
    result = subprocess.run(["bash", str(BIN / "restore-test.sh")], env=sb.env(RESTORED_SCHEMAS=" ".join(schemas),
                                                                              RESTORED_TRIGGERS=" ".join(triggers)),
                            capture_output=True, text=True, timeout=120, check=False)
    return result, json.loads((sb.state / "restore-test.json").read_text())


def test_a_restore_with_every_schema_and_trigger_passes(sb: Sandbox) -> None:
    result, outcome = _restore(sb, {"catalog": CATALOG}, schemas=CATALOG["schemas"], triggers=CATALOG["append_only"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome["passed"] is True and outcome["failures"] == []
    assert "schemas: 4 back" in result.stdout and "append-only triggers: 2 back" in result.stdout


def test_a_restore_that_lost_a_new_schema_fails(sb: Sandbox) -> None:
    result, outcome = _restore(sb, {"catalog": CATALOG}, schemas=["ai", "intel", "public"], triggers=CATALOG["append_only"])
    assert result.returncode == 1
    assert outcome["passed"] is False and outcome["failures"] == ["schemas missing after the restore: news"]


def test_a_restore_that_lost_an_append_only_trigger_fails(sb: Sandbox) -> None:
    result, outcome = _restore(sb, {"catalog": CATALOG}, schemas=CATALOG["schemas"], triggers=CATALOG["append_only"][:1])
    assert result.returncode == 1
    assert outcome["failures"] == ["append-only triggers missing after the restore: "
                                   "intel.capability_transitions:capability_transitions_append_only"]


@pytest.mark.parametrize("manifest", [{}, {"catalog": None}])
def test_a_backup_from_before_ad_a07_is_tested_as_before(sb: Sandbox, manifest: dict) -> None:
    result, outcome = _restore(sb, manifest, schemas=[], triggers=[])
    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome["passed"] is True
    assert "a backup from before AD-A07" in result.stdout


# ---- fbi.ops.backup (the dev machine's backups) ----------------------------------------------------------------------------------------


def test_the_module_compares_schemas_and_triggers_when_the_manifest_names_them() -> None:
    manifest = {"schemas": ["ai", "news"], "append_only": ["ai.evidence:evidence_append_only", "news.items:items_append_only"]}
    checks = backup._compare_catalog(manifest, ["ai", "news", "public"], ["ai.evidence:evidence_append_only"])
    assert [(c.name.split(":")[0], c.passed) for c in checks] == [("SCHEMAS", True), ("APPEND-ONLY", False)]
    assert "news.items:items_append_only" in checks[1].detail
    assert backup._compare_catalog({}, [], []) == [], "an older manifest adds no check"
