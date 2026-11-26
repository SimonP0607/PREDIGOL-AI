"""RP-0.2: the registry of shadow switches is complete, generated from its data, and agrees with the code."""

from __future__ import annotations

import re
from pathlib import Path

from scripts import shadow_registry as reg

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"
SHADOW_WORDING = re.compile(r"(FBI_[A-Z0-9_]+)(?![A-Z0-9_])[^\n]{0,60}?\bshadow\b")
TUNING = re.compile(r"(MINUTES|HOURS|SECONDS|MAX_PER_DAY|TRIGGERS|LIMIT|DAILY|CAP|BUDGET|MAX)")
PRODUCTION_SHADOW = 26
"""How many switches production held in shadow on 26 Nov 2026 (the count the registry was written against)."""


def _rows() -> list[dict[str, object]]:
    return list(reg.load()["sombras"])


def test_every_row_is_complete_and_the_count_is_the_measured_one() -> None:
    assert reg.problems(reg.load()) == []
    assert len(_rows()) == PRODUCTION_SHADOW


def test_the_document_is_what_the_data_renders() -> None:
    assert reg.DOC.read_text(encoding="utf-8") == reg.render(reg.load())


def test_every_switch_of_the_registry_exists_in_the_code() -> None:
    code = "\n".join(p.read_text(errors="ignore") for p in SRC.rglob("*.py"))
    missing = [str(r["interruptor"]) for r in _rows() if str(r["interruptor"]) not in code]
    assert missing == [], f"registered switches the code does not read: {missing}"


def test_every_switch_the_code_documents_with_a_shadow_mode_is_registered_or_accounted_for() -> None:
    """A new ``FBI_*`` switch with a shadow mode cannot appear in the code without a row (or an explained exception)."""
    doc = reg.load()
    known = {str(r["interruptor"]) for r in doc["sombras"]} | {str(r["interruptor"]) for r in doc["fuera_de_sombra"]}
    found: set[str] = set()
    for p in SRC.rglob("*.py"):
        for m in SHADOW_WORDING.finditer(p.read_text(errors="ignore")):
            found.add(m.group(1))
    candidates = {k for k in found if not TUNING.search(k) or k == "FBI_AI_MODE"}
    assert sorted(candidates - known) == [], "document the new shadow switch in docs/intelligence/sombras.json"


def test_a_row_without_criteria_says_so() -> None:
    for r in _rows():
        if not r["definida"]:
            assert "ninguna" in str(r["condicion"]).lower() or "ninguna" in str(r["comparacion"]).lower()
