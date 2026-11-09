"""CI-013 - the workflows follow the supply-chain rules that zizmor also checks in CI: every action is pinned to a commit and no checkout keeps the token."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[3] / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _uses(path: Path) -> list[tuple[int, str]]:
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = USES.match(line)
        if match and not match["ref"].startswith("./"):
            found.append((number, match["ref"]))
    return found


def test_there_are_workflows_to_check() -> None:
    assert {p.name for p in WORKFLOWS} >= {"backend.yml", "web.yml", "deploy-auto.yml", "workflows-lint.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_full_commit_sha(path: Path) -> None:
    loose = [f"{path.name}:{n} {ref}" for n, ref in _uses(path) if not PINNED.match(ref)]
    assert not loose, f"actions not pinned to a 40-character SHA (a moving tag can change under us): {loose}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_checkout_keeps_the_token_in_the_workspace(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        match = USES.match(line)
        if not (match and match["ref"].startswith("actions/checkout@")):
            continue
        indent = len(line) - len(line.lstrip()) + (2 if line.lstrip().startswith("- ") else 0)
        block = []
        for follower in lines[index + 1 :]:
            if follower.strip() and len(follower) - len(follower.lstrip()) < indent:
                break
            if follower.strip() and len(follower) - len(follower.lstrip()) == indent and not follower.lstrip().startswith(("with:", "#")):
                break
            block.append(follower)
        assert any(re.match(r"\s*persist-credentials:\s*false\s*$", b) for b in block), f"{path.name}:{index + 1} checkout without persist-credentials: false"


def test_the_lint_workflow_pins_its_tools_and_checks_the_actionlint_download() -> None:
    text = (Path(__file__).resolve().parents[3] / ".github" / "workflows" / "workflows-lint.yml").read_text(encoding="utf-8")
    assert re.search(r"ACTIONLINT_SHA256: '[0-9a-f]{64}'", text)
    assert "sha256sum -c -" in text
    assert re.search(r"zizmor==\d+\.\d+\.\d+", text)
