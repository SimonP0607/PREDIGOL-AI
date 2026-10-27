"""The server's 5-minute health check (deploy/vps/bin/healthcheck.sh) raises an alarm only when it is true."""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fbi.core import match_state
from tests.unit._vps_sandbox import BIN, Sandbox, tools_present

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "bin" / "healthcheck.sh"


def test_a_match_the_provider_left_interrupted_for_days_is_not_in_play() -> None:
    """Regression (22 Oct 2026): the in-play check counted every fixture whose stored group is 'live'. The provider leaves
    some matches at INT for days (Rayo Vallecano - Athletic on 10 Oct; two more by 22 Oct, one since 31 Aug), so the verdict
    read "2 matches in play, last in-play capture 27133s ago" - 'problem' - for days, while there was nothing to capture.
    An alarm that is always on hides the day it is true."""
    text = SCRIPT.read_text(encoding="utf-8")
    query = re.search(
        r'playing="\$\(psql_q "(SELECT count\(\*\) FROM core\.fixtures WHERE [^"]*)"', text
    )
    assert query is not None, "the in-play count is a query on core.fixtures"
    where = query.group(1)
    assert "status_group = 'live'" in where
    window = re.search(r"kickoff_at > now\(\) - interval '(\d+) minutes'", where)
    assert window is not None, "a stored in-play code only counts for a while after kick-off"
    assert int(window.group(1)) * 60 == match_state.LIVE_STALE_AFTER.total_seconds(), (
        "the same window the application believes (match_state.LIVE_STALE_AFTER), not another one"
    )


# ---- the copies off the server -----------------------------------------------------------------------------------------
# The block of healthcheck.sh that reads state/*.json and the manifests runs for real (its own text, not a copy of it) with
# say/problem/warning replaced by lines a test can read.

needs_tools = pytest.mark.skipif(
    not tools_present(), reason="bash, jq, flock and sha256sum are needed"
)


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def _ago(**delta: float) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _put(sb: Sandbox, name: str, data: dict) -> None:
    sb.state.mkdir(parents=True, exist_ok=True)
    (sb.state / name).write_text(json.dumps(data))


def _dump(sb: Sandbox, verified_ago: dict | None) -> None:
    sb.backups.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"name": "predigol-20261025T041900Z"}
    if verified_ago is not None:
        manifest["offsite"] = {"verified_at": _ago(**verified_ago)}
    (sb.backups / "predigol-20261025T041900Z.json").write_text(json.dumps(manifest))


def _raw(sb: Sandbox, synced: dict, full: dict | None, empty: int = 0) -> None:
    state: dict = {
        "synced_at": _ago(**synced),
        "mode": "recent",
        "remote": "r2:bucket/raw",
        "seconds": 3,
        "copied": 10,
        "empty_recent_files": empty,
    }
    if full is not None:
        state["full_at"] = _ago(**full)
    _put(sb, "raw-sync.json", state)


def _offsite_verdict(sb: Sandbox) -> list[str]:
    text = SCRIPT.read_text(encoding="utf-8")
    block = text[
        text.index("# Off the server (only once configured") : text.index("# 7. The certificate")
    ]
    harness = (
        f"set -Euo pipefail\n. {BIN / 'lib.sh'}\n"
        'say() { echo "ok:      $*"; }\nproblem() { echo "PROBLEM: $*"; }\nwarning() { echo "warning: $*"; }\n'
        'alert_set() { echo "ALERT:   $1 $2 $3"; }\n' + block
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        env=sb.env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.splitlines()


def _says(lines: list[str], kind: str, fragment: str) -> bool:
    return any(ln.startswith(kind) and fragment in ln for ln in lines)


def _alerts(lines: list[str], key_prefix: str = "") -> list[str]:
    """What the block asked alerts_lib.sh to raise: 'KEY SEV text', in the order it asked (only the keys that start with key_prefix)."""
    asked = [ln.removeprefix("ALERT:").strip() for ln in lines if ln.startswith("ALERT:")]
    return [a for a in asked if a.startswith(key_prefix)]


# Each verdict that is a PROBLEM (or a warning that deserves a message) also asks alerts_lib.sh for an alert: the owner hears of it once,
# with its key and severity (security plan S3). The alert is asserted with the verdict so that neither can change without the other.
OFFSITE_30H = "backup.offsite SEV2 la copia más reciente fuera del servidor tiene 30 h"


@needs_tools
@pytest.mark.parametrize(
    ("verified", "kind", "fragment", "alerts"),
    [
        ({"hours": 2}, "ok:", "off-server copy 2 h old", []),
        (
            {"hours": 30},
            "PROBLEM",
            "the newest dump copied off the server is 30 h old",
            [OFFSITE_30H],
        ),
        (
            {"hours": 80},
            "PROBLEM",
            "the newest dump copied off the server is 80 h old",
            [
                "backup.offsite SEV2 la copia más reciente fuera del servidor tiene 80 h",
                "backup.offsite SEV1 la copia más reciente fuera del servidor tiene más de 3 días",
            ],
        ),
        (
            None,
            "warning",
            "no dump has been copied off the server yet",
            ["backup.offsite SEV3 todavía no hay ninguna copia verificada fuera del servidor"],
        ),
    ],
)
def test_the_newest_verified_copy_off_the_server_must_be_under_26_hours_old(
    sb: Sandbox, verified: dict | None, kind: str, fragment: str, alerts: list[str]
) -> None:
    _dump(sb, verified)
    lines = _offsite_verdict(sb)
    assert _says(lines, kind, fragment)
    assert _alerts(lines) == alerts


@needs_tools
@pytest.mark.parametrize(
    ("state", "kind", "fragment", "alerts"),
    [
        ({"passed": True, "checked_at": _ago(days=2)}, "ok:", "bucket locks proven 2 days ago", []),
        (
            {"passed": True, "checked_at": _ago(days=12)},
            "warning",
            "last proven 12 days ago",
            ["backup.locks SEV3 los candados del cubo se comprobaron por última vez hace 12 días"],
        ),
        (
            {"passed": False, "checked_at": _ago(days=1)},
            "PROBLEM",
            "lock check FAILED",
            [
                "backup.locks SEV1 falló la última comprobación de los candados del cubo: "
                "las copias fuera del servidor podrían borrarse"
            ],
        ),
        (None, "warning", "have not been proven yet", []),
    ],
)
def test_the_bucket_locks_must_have_been_proven_in_the_last_ten_days(
    sb: Sandbox, state: dict | None, kind: str, fragment: str, alerts: list[str]
) -> None:
    _dump(sb, {"hours": 1})
    if state is not None:
        _put(sb, "lock-check.json", state)
    lines = _offsite_verdict(sb)
    assert _says(lines, kind, fragment)
    assert _alerts(lines) == alerts


@needs_tools
@pytest.mark.parametrize(
    ("synced", "kind", "fragment", "alerts"),
    [
        ({"minutes": 20}, "ok:", "RAW synced 20 min ago", []),
        ({"hours": 4}, "warning", "the RAW sync has not run for 4 h", []),
        (
            {"hours": 13},
            "PROBLEM",
            "last copied off the server 13 h ago",
            ["raw.sync SEV2 el almacén RAW se copió fuera del servidor por última vez hace 13 h"],
        ),
    ],
)
def test_the_raw_sync_must_have_run_in_the_last_hours(
    sb: Sandbox, synced: dict, kind: str, fragment: str, alerts: list[str]
) -> None:
    _raw(sb, synced, {"hours": 2})
    lines = _offsite_verdict(sb)
    assert _says(lines, kind, fragment)
    assert _alerts(lines, "raw.") == alerts


@needs_tools
@pytest.mark.parametrize(
    ("full", "kind", "fragment", "alerts"),
    [
        ({"hours": 5}, "ok:", "full RAW pass 5 h ago", []),
        ({"hours": 40}, "warning", "the last full RAW pass was 40 h ago", []),
        (
            {"days": 6},
            "PROBLEM",
            "the last full RAW pass was 6 days ago",
            ["raw.full SEV2 la última pasada completa del RAW fue hace 6 días"],
        ),
        (None, "warning", "no full RAW pass has finished yet", []),
    ],
)
def test_the_daily_full_raw_pass_is_watched_because_the_hourly_one_does_not_look_everywhere(
    sb: Sandbox, full: dict | None, kind: str, fragment: str, alerts: list[str]
) -> None:
    _raw(sb, {"minutes": 10}, full)
    lines = _offsite_verdict(sb)
    assert _says(lines, kind, fragment)
    assert _alerts(lines, "raw.") == alerts


@needs_tools
def test_empty_raw_files_of_the_last_week_are_a_warning_and_none_is_silent(sb: Sandbox) -> None:
    _raw(sb, {"minutes": 10}, {"hours": 2}, empty=2)
    assert _says(_offsite_verdict(sb), "warning", "2 empty file(s) written to the RAW store")
    _raw(sb, {"minutes": 10}, {"hours": 2}, empty=0)
    assert not any("empty file" in ln for ln in _offsite_verdict(sb))


@needs_tools
def test_nothing_is_said_about_the_bucket_until_one_is_configured(sb: Sandbox) -> None:
    sb.set_env(BACKUP_RCLONE_REMOTE=None, RAW_RCLONE_REMOTE=None)
    assert _offsite_verdict(sb) == []


@needs_tools
def test_a_healthy_bucket_raises_no_alert_at_all(sb: Sandbox) -> None:
    """The alerts of this block close by silence: a pass that raises nothing is what tells alerts_lib.sh 'recuperado'."""
    _dump(sb, {"hours": 2})
    _put(sb, "lock-check.json", {"passed": True, "checked_at": _ago(days=1)})
    _raw(sb, {"minutes": 10}, {"hours": 2})
    assert _alerts(_offsite_verdict(sb)) == []


# ---- what visitors got: server errors in the last five minutes, and a deploy that just ran ------------------------------
# A deploy (or a rollback) recreates the API: Caddy answers 502 for those seconds and they stay in the count of the last five minutes for the next
# five. Rehearsed on Staging on 26 Oct 2026: a rollback and a deploy within five minutes left 49 server errors, a SEV2 alert and an incident in the
# register after a deploy that had worked. Block 11 of healthcheck.sh runs for real over a Caddy log.


def _errors_verdict(
    sb: Sandbox, errors: int, deploy_ago: float | None, rollback: bool = False
) -> list[str]:
    text = SCRIPT.read_text(encoding="utf-8")
    block = text[text.index("# 11. What visitors got") : text.index("# 12. Disk forecast")]
    access = sb.data / "caddy" / "data" / "access.log"
    access.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rows = [{"ts": now - 30, "status": 502, "request": {"uri": "/api/v1/matches"}}] * errors
    rows += [{"ts": now - 20, "status": 200, "request": {"uri": "/"}}] * 30
    rows += [
        {"ts": now - 900, "status": 502, "request": {"uri": "/api/v1/old"}}
    ] * 40  # outside the window: never counted
    access.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    sb.state.mkdir(parents=True, exist_ok=True)
    deploys = sb.state / "deploys.log"
    deploys.unlink(missing_ok=True)
    if deploy_ago is not None:
        when = _ago(seconds=deploy_ago)
        deploys.write_text(
            f"{when}\told\tweb\t-\t-\trollback\n" if rollback else f"{when}\tnew\tweb\told\tweb\n"
        )
    harness = (
        f"set -Euo pipefail\n. {BIN / 'lib.sh'}\n. {BIN / 'alerts_checks.sh'}\n"
        'say() { echo "ok:      $*"; }\nproblem() { echo "PROBLEM: $*"; }\nwarning() { echo "warning: $*"; }\n'
        'alert_set() { echo "ALERT:   $1 $2 $3"; }\nalerts_hold() { echo "HOLD:    $*"; }\n' + block
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        env=sb.env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.splitlines()


ALERT_25 = "ALERT:   web.errors5xx SEV2 25 errores 5xx en 5 min"
ALERT_60 = "ALERT:   web.errors5xx SEV2 60 errores 5xx en 5 min"
GRACE = "(a deploy or a rollback finished in the last few minutes)"


@needs_tools
@pytest.mark.parametrize(
    ("errors", "deploy_ago", "rollback", "expected"),
    [
        (5, None, False, ["ok:      ok   5 server errors in 5 min"]),
        (
            25,
            None,
            False,
            ["warning: 25 server errors (5xx) in 5 min", ALERT_25],
        ),
        (60, None, False, ["PROBLEM: 60 server errors (5xx) in 5 min", ALERT_60]),
        # a deploy finished a minute ago: the 502 of its seconds are in the count - no problem, no alert, an open one stays as it is
        (
            60,
            60,
            False,
            [f"warning: 60 server errors (5xx) in 5 min {GRACE}", "HOLD:    web.errors5xx"],
        ),
        (
            25,
            60,
            False,
            [f"warning: 25 server errors (5xx) in 5 min {GRACE}", "HOLD:    web.errors5xx"],
        ),
        (5, 60, False, ["ok:      ok   5 server errors in 5 min"]),
        # a rollback writes its line right after starting the containers, and the API still needs its seconds
        (
            60,
            100,
            True,
            [f"warning: 60 server errors (5xx) in 5 min {GRACE}", "HOLD:    web.errors5xx"],
        ),
        # the window is over: the count is judged as always
        (60, 400, False, ["PROBLEM: 60 server errors (5xx) in 5 min", ALERT_60]),
    ],
    ids=[
        "calm",
        "25-errors",
        "60-errors",
        "60-errors-after-a-deploy",
        "25-errors-after-a-deploy",
        "calm-after-a-deploy",
        "60-errors-after-a-rollback",
        "60-errors-long-after-a-deploy",
    ],
)
def test_the_502_of_a_deploy_are_not_a_problem_but_the_same_errors_later_are(
    sb: Sandbox, errors: int, deploy_ago: float | None, rollback: bool, expected: list[str]
) -> None:
    assert _errors_verdict(sb, errors, deploy_ago, rollback) == expected
