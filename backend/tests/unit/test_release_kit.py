"""The release toolkit (deploy/release, plan CI/CD C3): the server-side scripts are templates, and a template that does not parse or that names a
token build_kit.sh does not fill would only fail on the server, in the middle of a release. These tests fail it here, in the CI."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "release"
TEMPLATES = sorted((ROOT / "templates" / "server").glob("*"))
EXTRAS = sorted((ROOT / "extras").rglob("*.sh"))
TOKENS = {"__STAMP__", "__REL__", "__PARTS__", "__BE_FROM__", "__BE_WANT__", "__WEB_FROM__", "__WEB_WANT__", "__MODEL_FP__"}

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def test_there_are_templates() -> None:
    names = {p.name for p in TEMPLATES}
    assert {"chain.sh", "step_deploy.sh", "step_precheck.sh", "step_backup.sh", "step_smoke.sh", "step_verify.sh", "quiet.sh"} <= names


@pytest.mark.parametrize("path", [*TEMPLATES, *EXTRAS, ROOT / "build_kit.sh", ROOT / "ship.sh", ROOT / "gate.sh"], ids=lambda p: p.name)
def test_every_script_parses(path: Path) -> None:
    out = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr


def test_a_template_only_names_tokens_the_builder_fills() -> None:
    seen = {"__" + m.lstrip("_") for p in TEMPLATES for m in re.findall(r"__[A-Z_]+__", p.read_text(encoding="utf-8"))}  # backend___REL__ = backend_ + token
    assert seen <= TOKENS, seen - TOKENS
    builder = (ROOT / "build_kit.sh").read_text(encoding="utf-8")
    for token in seen:
        assert token in builder, f"build_kit.sh does not fill {token}"


def test_no_template_keeps_a_release_of_the_past() -> None:
    """A template that still says ia-p04, a stamp or a commit of the release it was cut from would deploy the wrong thing."""
    for p in TEMPLATES:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"ia-p04|\b2026\d{4}T\d{4}Z\b|\b[0-9a-f]{12}\b(?=\" \"(backend|web) checkout)", text), p.name


def test_the_chain_never_starts_a_deploy_without_the_owners_word() -> None:
    ship = (ROOT / "ship.sh").read_text(encoding="utf-8")
    assert "--owner-ok" in ship and "needs --owner-ok" in ship


def test_the_parts_reach_the_templates_as_words_not_as_a_comma_list() -> None:
    """The templates ask ``case " $PARTS " in *" backend "*``: a list written ``backend,web`` made the first real deploy say that the backend was
    not released (it stopped, nothing moved). The builder takes the commas out when it fills ``__PARTS__``."""
    build = (ROOT / "build_kit.sh").read_text(encoding="utf-8")
    assert "s|__PARTS__|${PARTS//,/ }|g" in build
    for p in TEMPLATES:
        text = p.read_text(encoding="utf-8")
        if "__PARTS__" in text:
            assert 'case " $PARTS " in' in text, f"{p.name} matches the parts some other way than the builder fills them"