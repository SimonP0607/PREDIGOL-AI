"""The shell suites of the server's alerts (tests/vps_shell/*.sh) run under pytest, so that `make check` holds them.

Each suite tests one script of deploy/vps/bin with fakes for everything outside it (the channel, Docker, curl, the database), prints one
line per check ("ok ..." or "FAIL ...") and ends with "RESULT: N ok, M failed". Here a suite passes when it exits 0 and says at least
as many ok as it did when it was written: a suite that quietly lost half of its checks is a failure too.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.unit._vps_sandbox import tools_present

SUITES = Path(__file__).resolve().parents[1] / "vps_shell"

# suite -> the script(s) it holds, and how many checks it had when it was written (26 Oct 2026)
EXPECTED = {
    "test_alerts_lib.sh": (
        "alerts_lib.sh: one message per change, reminders, retries, the register",
        75,
    ),
    "test_alerts_checks.sh": (
        "alerts_checks.sh: restart loops, /auth/me, drift, unsettled picks, a deploy a moment ago",
        74,
    ),
    "test_config_baseline.sh": (
        "config-baseline.sh: the baseline of the alert 'the configuration changed', who takes it",
        63,
    ),
    "test_security_alerts.sh": ("security-alerts.sh: sign-in records and Caddy's log", 46),
    "test_weekly_summary.sh": ("weekly-summary.sh: the Monday message", 9),
    "test_notify.sh": (
        "lib.sh: notify_ok / notify, the host's bot first, and alert_channel in step with them",
        30,
    ),
    "test_alert_test.sh": ("alert-test.sh: the owner's test message, which bot took it", 27),
    "test_alert_drill.sh": (
        "alert-drill.sh: an alert's message, or the whole record's, through the real bot, on a scratch register",
        198,
    ),
    "test_incident_pen.sh": ("incident.sh: the owner's pen", 64),
}

needs_tools = pytest.mark.skipif(
    not tools_present(), reason="bash, jq, flock and sha256sum are needed"
)


def test_every_suite_in_the_folder_is_run_here() -> None:
    on_disk = {p.name for p in SUITES.glob("test_*.sh")}
    assert on_disk == set(EXPECTED), "a suite that no test runs checks nothing"


@needs_tools
@pytest.mark.parametrize("suite", sorted(EXPECTED))
def test_the_suite_passes_with_all_its_checks(suite: str) -> None:
    result = subprocess.run(
        ["bash", str(SUITES / suite)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    failed = [ln for ln in result.stdout.splitlines() if ln.startswith("FAIL")]
    summary = re.search(r"^RESULT: (\d+) ok, (\d+) failed", result.stdout, flags=re.M)
    assert summary is not None, f"{suite} did not reach its RESULT line:\n{result.stderr[-2000:]}"
    ok, bad = int(summary.group(1)), int(summary.group(2))
    assert bad == 0 and not failed and result.returncode == 0, "\n".join(failed[:20])
    assert ok >= EXPECTED[suite][1], f"{suite} used to run {EXPECTED[suite][1]} checks, now {ok}"
