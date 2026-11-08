"""CI-012: the release precheck accepts the owner's two words for ``FBI_AI_MODE`` (shadow, enforce) and refuses any other.

The case of the precheck is run as it is written, on each word, so a deploy is not refused because the owner chose ``enforce``
(``fbi.ai.gating`` still applies the AI to users only while the shadow gate of ``combined`` passes)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

PRECHECK = Path(__file__).resolve().parents[2] / "deploy" / "release" / "templates" / "server" / "step_precheck.sh"


def _the_case() -> str:
    text = PRECHECK.read_text(encoding="utf-8")
    m = re.search(r'^  case "\$\{MODE_NOW:-shadow\}" in\n.*?^  esac\n', text, flags=re.S | re.M)
    assert m, "the case on FBI_AI_MODE was not found in the precheck"
    return m.group(0)


def _run(mode: str) -> tuple[str, str]:
    script = 'BAD=0\ngood() { echo "OK: $*"; }\nbad() { BAD=$((BAD + 1)); echo "NOT OK: $*"; }\nMODE_NOW="$1"\n' + _the_case() + 'echo "BAD=$BAD"\n'
    out = subprocess.run(["bash", "-c", script, "precheck", mode], capture_output=True, text=True, check=True).stdout
    return out, out.strip().splitlines()[-1]


@pytest.mark.parametrize("mode", ["shadow", "", "enforce"])
def test_the_owners_words_pass(mode: str) -> None:
    out, last = _run(mode)
    assert last == "BAD=0" and out.startswith("OK: FBI_AI_MODE"), out


@pytest.mark.parametrize("mode", ["off", "on", "live", "enforced"])
def test_any_other_word_is_refused(mode: str) -> None:
    out, last = _run(mode)
    assert last == "BAD=1" and f"FBI_AI_MODE = {mode}, expected shadow or enforce" in out, out
