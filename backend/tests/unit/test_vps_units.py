"""The server's systemd units (deploy/vps/systemd), the scripts they start and install.sh agree with each other.

A timer that install.sh does not enable never fires on a fresh server; a unit that starts a script that is not there, or not executable, fails
the first time it is due, at night, and nobody is watching. None of that needs a server to find out.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

VPS = Path(__file__).resolve().parents[2] / "deploy" / "vps"
BIN = VPS / "bin"
UNITS = VPS / "systemd"
INSTALL = BIN / "install.sh"
EXEC_START = re.compile(r"^ExecStart=/opt/predigol/backend/deploy/vps/bin/([\w.-]+)(?: .*)?$", re.M)

# The scripts of security plan S3 (the alerts and the incident register): they must also be clean for shellcheck when it is installed.
S3_SCRIPTS = (
    "alert-drill.sh",
    "alert-test.sh",
    "alerts_lib.sh",
    "alerts_checks.sh",
    "config-baseline.sh",
    "incident.sh",
    "incident-dump.sh",
    "security-alerts.sh",
    "security_alerts_sql.sh",
    "weekly-summary.sh",
)
needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is needed")


def _services() -> list[Path]:
    return sorted(UNITS.glob("*.service"))


def _timers() -> list[Path]:
    return sorted(UNITS.glob("*.timer"))


def _enabled_by_install() -> set[str]:
    """The units install.sh enables: the words of its `systemctl enable` commands (a command may continue on the next line)."""
    text = INSTALL.read_text(encoding="utf-8").replace("\\\n", " ")
    units: set[str] = set()
    for line in text.splitlines():
        if line.strip().startswith("systemctl enable"):
            units |= {w for w in line.split() if w.endswith((".timer", ".service"))}
    return units


def test_every_timer_has_the_service_it_starts() -> None:
    assert _timers(), "no timers found: the folder moved?"
    for timer in _timers():
        assert timer.with_suffix(".service").is_file(), f"{timer.name} starts nothing"


def test_every_timer_is_enabled_by_install_sh() -> None:
    """install.sh copies every unit by glob but enables a fixed list: a new timer must be added to it."""
    enabled = _enabled_by_install()
    missing = [t.name for t in _timers() if t.name not in enabled]
    assert not missing, f"never enabled on a fresh server: {missing}"
    assert "predigol-security-alerts.timer" in enabled, "the parser of install.sh found nothing"


def test_every_service_starts_a_script_that_exists_and_is_executable() -> None:
    started = 0
    for service in _services():
        match = EXEC_START.search(service.read_text(encoding="utf-8"))
        assert match, f"{service.name}: no ExecStart in /opt/predigol/backend/deploy/vps/bin"
        script = BIN / match.group(1)
        assert script.is_file(), f"{service.name} starts {script.name}, which is not there"
        assert os.access(script, os.X_OK), f"{script.name} is not executable (git mode 100755)"
        started += 1
    assert started >= 13


def test_a_timer_that_runs_often_does_not_start_with_the_health_check() -> None:
    """The health check, the security alerts and the register copy all run every few minutes; they start at different offsets after boot."""
    boot = {}
    for name in ("health", "security-alerts", "incident-dump"):
        text = (UNITS / f"predigol-{name}.timer").read_text(encoding="utf-8")
        found = re.search(r"^OnBootSec=(\d+)min$", text, flags=re.M)
        assert found, f"predigol-{name}.timer: OnBootSec in minutes"
        boot[name] = int(found.group(1))
    assert len(set(boot.values())) == len(boot), f"two timers start together after boot: {boot}"


@needs_bash
def test_every_script_of_the_server_parses() -> None:
    scripts = [*sorted(BIN.glob("*.sh")), BIN / "predigolctl"]
    assert len(scripts) >= 25
    for script in scripts:
        result = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
@pytest.mark.parametrize("script", S3_SCRIPTS)
def test_the_scripts_of_the_s3_alerts_are_clean_for_shellcheck(script: str) -> None:
    result = subprocess.run(
        ["shellcheck", "-x", "-S", "warning", script],
        cwd=BIN,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
