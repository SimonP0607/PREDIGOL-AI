"""The alert "the configuration changed" (security plan S3, alert 32) needs a baseline, and someone has to take it.

bin/alerts_checks.sh compares the sha256 of the Caddyfile, compose, the env files, sshd's configuration and the units with state/config.sha256. Until a
baseline exists the alert says nothing, so it must be taken when a planned change ends: `predigolctl deploy` and `rollback` do it, and the person who
edits an env file by hand does it as the last step (`predigolctl config-baseline`). These tests read predigolctl and the documents; the behaviour of the
script is in tests/vps_shell/test_config_baseline.sh.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
VPS = BACKEND / "deploy" / "vps"
BIN = VPS / "bin"
CTL = (BIN / "predigolctl").read_text(encoding="utf-8")
BASELINE_CALL = '"$BIN/config-baseline.sh"'


def _function(name: str) -> str:
    """The text of a shell function of predigolctl, from its first line to the closing brace at the start of a line."""
    found = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}$", CTL, flags=re.M | re.S)
    assert found, f"{name}() not found in predigolctl"
    return found.group(1)


def test_the_script_is_executable_and_in_the_gate_of_shellcheck() -> None:
    script = BIN / "config-baseline.sh"
    assert script.is_file()
    assert script.stat().st_mode & 0o111, "git mode 100755"
    units = (BACKEND / "tests" / "unit" / "test_vps_units.py").read_text(encoding="utf-8")
    assert '"config-baseline.sh"' in units, (
        "shellcheck must read it as it reads the other S3 scripts"
    )


def test_a_deploy_takes_the_baseline_after_it_has_finished_and_before_its_own_check() -> None:
    body = _function("cmd_deploy")
    written = body.index('>> "$STATE/deploys.log"')
    taken = body.index(BASELINE_CALL)
    checked = body.index('"$BIN/healthcheck.sh"')
    assert written < taken < checked, (
        "deploys.log line, then the baseline, then the post-deploy check: the files of the new "
        "release must not look like a surprise to the check that runs right after them"
    )


def test_the_baseline_never_fails_a_deploy_or_a_rollback() -> None:
    for name in ("cmd_deploy", "cmd_rollback"):
        calls = [line for line in _function(name).splitlines() if BASELINE_CALL in line]
        assert len(calls) == 1, f"{name}: the baseline is taken once"
        assert "|| log " in calls[0], f"{name}: a baseline that cannot be taken is told, not fatal"


def test_a_deploy_that_stops_half_way_does_not_move_the_baseline() -> None:
    """Every `exit 1` of cmd_deploy comes before the line that records the deploy: a failed one must leave the alert able to say the files changed."""
    body = _function("cmd_deploy")
    recorded = body.index('>> "$STATE/deploys.log"')
    assert "exit 1" in body[:recorded]
    assert BASELINE_CALL not in body[:recorded]
    assert "exit 1" not in body[recorded:]


def test_a_rollback_takes_it_after_it_has_written_its_line() -> None:
    body = _function("cmd_rollback")
    assert body.index('>> "$STATE/deploys.log"') < body.index(BASELINE_CALL)


def test_the_dispatcher_and_the_usage_know_the_command() -> None:
    assert re.search(
        r'^  config-baseline\) shift; exec "\$BIN/config-baseline\.sh" "\$@" ;;$', CTL, flags=re.M
    )
    header = CTL.split("set -Eeuo pipefail", 1)[0]
    assert "predigolctl config-baseline [--status]" in header
    shown = re.search(r"sed -n '2,(\d+)p' \"\$0\"", CTL)
    assert shown, "the usage text is the header of the file"
    assert int(shown.group(1)) >= header.count("\n"), "the usage text must reach the last command"


@pytest.mark.parametrize(
    ("document", "needles"),
    [
        (
            VPS / "README.md",
            ("predigolctl config-baseline", "config-baseline.sh", "línea base"),
        ),
        (
            BACKEND / "docs" / "owner" / "GUIAS_RESPUESTA_INCIDENTES.md",
            ("predigolctl config-baseline", "config.drift"),
        ),
    ],
    ids=["README", "incident-guides"],
)
def test_the_documents_say_who_takes_the_baseline(document: Path, needles: tuple[str, ...]) -> None:
    text = document.read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text, f"{document.name} does not say {needle!r}"
