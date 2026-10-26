"""The server's storage report (deploy/vps/bin/storage-report.sh) measures, never changes, and says only sizes.

The script runs here against a throw-away data folder with stand-ins for `docker` and `df` on the PATH: the stand-ins answer the
few questions it asks (Docker's own accounting, the database's size and largest tables) and record every call, so a test can also
prove it asked nothing that changes anything.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "vps" / "bin" / "storage-report.sh"
GIB = 1024**3

pytestmark = pytest.mark.skipif(shutil.which("jq") is None or shutil.which("bash") is None, reason="needs bash and jq")

DOCKER = r"""#!/usr/bin/env bash
echo "docker $*" >> "$CALLS"
case "$*" in
  "system df --format {{json .}}")
    echo '{"Active":"5","Reclaimable":"3.506GB (21%)","Size":"16.02GB","TotalCount":"65","Type":"Images"}'
    echo '{"Active":"6","Reclaimable":"0B (0%)","Size":"167.9kB","TotalCount":"6","Type":"Containers"}'
    echo '{"Active":"1","Reclaimable":"54.22GB (92%)","Size":"58.92GB","TotalCount":"6","Type":"Local Volumes"}'
    echo '{"Active":"0","Reclaimable":"11.98GB","Size":"17.44GB","TotalCount":"254","Type":"Build Cache"}' ;;
  "images -q") printf 'a\nb\nb\nc\n' ;;
  "volume ls -q -f dangling=true") printf 'v1\nv2\nv3\nv4\nv5\n' ;;
  *pg_database_size*) echo 23200000000 ;;
  *json_agg*) echo '[{"name":"raw.odds","bytes":9000000000},{"name":"models.predictions","bytes":3000000000}]' ;;
  *) echo "unexpected docker call: $*" >&2; exit 3 ;;
esac
"""

DF = r"""#!/usr/bin/env bash
echo "Filesystem 1-blocks Used Available Capacity Mounted"
echo "/dev/sda1 $DF_SIZE $DF_USED $(( DF_SIZE - DF_USED )) x% /"
"""


@pytest.fixture
def server(tmp_path: Path) -> dict[str, Path]:
    data = tmp_path / "srv"
    for d in ("raw/2026/10", "backups/db", "pgdata", "state"):
        (data / d).mkdir(parents=True)
    (data / "raw/2026/10/a.json").write_bytes(b"x" * 5000)
    (data / "raw/2026/10/b.json").write_bytes(b"y" * 3000)
    (data / "pgdata/base").write_bytes(b"z" * 7000)
    dump = data / "backups/db/predigol-20261026T030000Z.dump"
    dump.write_bytes(b"d" * 4096)
    (data / "backups/db/predigol-20261026T030000Z.json").write_text(json.dumps(
        {"bytes": 4096, "sha256": "ab" * 32, "offsite": {"remote": "r2:b/dumps/daily/x.age", "bytes": 4300,
                                                          "verified_at": "2026-10-26T03:01:00Z"}}))
    (data / "state/restore-test.json").write_text(json.dumps(
        {"dump": "predigol-20261026T030000Z", "at": "2026-10-26T04:00:00Z", "passed": True, "seconds": 812}))
    env = tmp_path / "predigol.env"
    env.write_text(f"PREDIGOL_DATA={data}\nPOSTGRES_PASSWORD=sup3r-secret-value\nBACKUP_KEEP_DAILY=3\n"
                   "BACKUP_KEEP_WEEKLY=2\nBACKUP_RCLONE_REMOTE=r2:predigol-backups\n")
    app_env = tmp_path / "app.env"
    app_env.write_text("FBI_SECRET_THING=another-secret-value\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", DOCKER), ("df", DF)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    return {"data": data, "env": env, "app_env": app_env, "bin": bin_dir, "calls": tmp_path / "calls.log"}


def run(server: dict[str, Path], *, size: int = 200 * GIB, used: int = 120 * GIB) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{server['bin']}:{os.environ['PATH']}", "PREDIGOL_ENV_FILE": str(server["env"]),
           "PREDIGOL_APP_ENV_FILE": str(server["app_env"]), "CALLS": str(server["calls"]),
           "DF_SIZE": str(size), "DF_USED": str(used)}
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60, check=False)


def report(server: dict[str, Path]) -> dict[str, object]:
    return json.loads((server["data"] / "state/storage/report.json").read_text())


def test_it_writes_the_report_with_the_sizes_it_measured(server: dict[str, Path]) -> None:
    out = run(server)
    assert out.returncode == 0, out.stderr
    r = report(server)
    assert r["version"] == "storage-report-v1"
    assert r["disk"] == {"size_bytes": 200 * GIB, "used_bytes": 120 * GIB, "avail_bytes": 80 * GIB, "pct": 60, "level": "ok"}
    parts = r["parts"]
    assert isinstance(parts, dict)
    assert parts["raw_files"] == 2 and parts["raw_bytes"] >= 8000
    assert parts["backups_count"] == 1
    docker = r["docker"]
    assert docker == {"images_bytes": 16_020_000_000, "images_reclaimable_bytes": 3_506_000_000, "images_count": 3,
                      "volumes_bytes": 58_920_000_000, "volumes_orphan_bytes": 54_220_000_000, "volumes_orphan_count": 5,
                      "build_cache_bytes": 17_440_000_000, "build_cache_reclaimable_bytes": 11_980_000_000}
    assert r["database"] == {"bytes": 23_200_000_000, "top_tables": [
        {"name": "raw.odds", "bytes": 9_000_000_000}, {"name": "models.predictions", "bytes": 3_000_000_000}]}
    backups = r["backups"]
    assert isinstance(backups, dict)
    assert backups["latest"]["sha256"] == "ab" * 32
    assert backups["last_offsite_at"] == "2026-10-26T03:01:00Z"
    assert backups["offsite_configured"] is True
    assert backups["restore_test"] == {"dump": "predigol-20261026T030000Z", "at": "2026-10-26T04:00:00Z",
                                       "passed": True, "seconds": 812}
    assert (backups["keep_daily"], backups["keep_weekly"]) == (3, 2)
    assert r["cleanup"] is None


@pytest.mark.parametrize(("pct", "level"), [(69, "ok"), (70, "warning"), (79, "warning"), (80, "high"), (89, "high"),
                                            (90, "critical"), (97, "critical")])
def test_the_level_of_the_disk(server: dict[str, Path], pct: int, level: str) -> None:
    assert run(server, size=100 * GIB, used=pct * GIB).returncode == 0
    assert report(server)["disk"]["level"] == level  # type: ignore[index]


def test_it_never_writes_or_prints_a_secret_or_asks_docker_to_change_anything(server: dict[str, Path]) -> None:
    out = run(server)
    text = (server["data"] / "state/storage/report.json").read_text() + out.stdout + out.stderr
    for secret in ("sup3r-secret-value", "another-secret-value"):
        assert secret not in text
    calls = server["calls"].read_text()
    for verb in ("rm", "prune", "kill", "stop", "restart", "pull", "build", "up", "down", "volume rm", "image rm"):
        assert f"docker {verb} " not in calls
    assert "default_transaction_read_only = on" in calls, "the database is read in a read-only session"


def test_one_line_a_day_in_the_history(server: dict[str, Path]) -> None:
    assert run(server, used=100 * GIB).returncode == 0
    assert run(server, used=101 * GIB).returncode == 0
    lines = (server["data"] / "state/storage/history.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["used_bytes"] == 101 * GIB, "the day keeps its latest measure"


def seed_history(server: dict[str, Path], deltas: list[int], start: int = 100 * GIB) -> int:
    today = datetime.now(UTC).date()
    days = len(deltas) + 1
    used = start
    rows = []
    for i in range(days):
        if i:
            used += deltas[i - 1]
        rows.append({"date": (today - timedelta(days=days - i)).isoformat(), "used_bytes": used, "db_bytes": 0,
                     "raw_bytes": 0, "docker_bytes": 0, "backups_bytes": 0})
    (server["data"] / "state/storage").mkdir(parents=True, exist_ok=True)
    (server["data"] / "state/storage/history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return used


def test_a_day_that_grows_far_beyond_the_usual_is_an_anomaly(server: dict[str, Path]) -> None:
    last = seed_history(server, [300 * 1024**2] * 14)
    assert run(server, used=last + 5 * GIB).returncode == 0
    growth = report(server)["growth"]
    assert growth["anomaly"] is True  # type: ignore[index]
    assert growth["median_delta_bytes"] == 300 * 1024**2  # type: ignore[index]
    assert (server["data"] / "state/storage/anomaly").read_text().strip() == "true"


def test_a_usual_day_or_a_small_absolute_jump_is_not(server: dict[str, Path]) -> None:
    last = seed_history(server, [300 * 1024**2] * 14)
    assert run(server, used=last + 1 * GIB).returncode == 0, "5 x the median, but under the 2 GiB floor"
    assert report(server)["growth"]["anomaly"] is False  # type: ignore[index]


def test_with_too_little_history_there_is_no_verdict(server: dict[str, Path]) -> None:
    assert run(server).returncode == 0
    growth = report(server)["growth"]
    assert growth["anomaly"] is False and growth["median_delta_bytes"] is None  # type: ignore[index]


def test_the_timer_runs_it_idle_and_away_from_the_provider_sync() -> None:
    unit = (ROOT / "deploy/vps/systemd/predigol-storage.service").read_text()
    timer = (ROOT / "deploy/vps/systemd/predigol-storage.timer").read_text()
    assert "storage-report.sh" in unit and "IOSchedulingClass=idle" in unit
    assert ":41:00" in timer, "never on the minute of fixtures_sync (:03)"
    install = (ROOT / "deploy/vps/bin/install.sh").read_text()
    assert "predigol-storage.timer" in install
    compose = (ROOT / "deploy/vps/docker-compose.yml").read_text()
    assert "/state/storage:/storage:ro" in compose, "the API reads the report through a read-only mount"
