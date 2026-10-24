"""Plan F14: the checklist of each phase is whole, and what it names is in the code.

``docs/owner/CHECKLIST_POR_FASE_F14.md`` is the signed list the plan asks for: nine checks, and for every release the datum that proves each (or
the reason it does not apply, or a dash for "nobody wrote it down then"). A list nobody keeps whole is a list nobody reads, so this file holds
its shape - the nine checks, one row for every release in both registers, no empty cell, the template with its nine lines - and ties the part that can
be tied to the code: every rule of the nightly leak audit and every isolation test the register names exists, and the newest audit version it
names is the one the code runs. The numbers of a past gate (tests that passed, seconds a restore took) are history and are not compared."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fbi.intel import leakage

DOC = Path(__file__).resolve().parents[2] / "docs" / "owner" / "CHECKLIST_POR_FASE_F14.md"
UNIT = Path(__file__).resolve().parent

if not DOC.is_file():
    pytest.skip(f"no {DOC.name} next to the code", allow_module_level=True)

TEXT = DOC.read_text(encoding="utf-8")

RELEASES = ("F0 + F1", "F0.1", "F2", "F3 + F1.1", "F3.2 + F5", "F4", "F6", "F7", "F8", "F9", "F10", "F11 + F12 + F13")
"""One row per release of the plan, oldest first (F5 shipped with F3.2, F13 with F11 and F12)."""
CHECKS = ("Pruebas", "e2e", "Fuga", "Idempotencia", "Reinicio del worker", "Restauración", "Despliegue", "Shadow", "Dueño")


def section(number: int) -> str:
    """The body of ``## <number>.`` up to the next level-two heading."""
    found = re.search(rf"^## {number}\. .*?\n(.*?)(?=^## \d+\. |\Z)", TEXT, flags=re.S | re.M)
    assert found, f"the checklist has no section {number}"
    return found.group(1)


def rows(body: str) -> list[list[str]]:
    """The cells of every data row of the first table in ``body`` (the header and the rule are left out)."""
    table = [line for line in body.splitlines() if line.startswith("|")]
    assert len(table) > 2, "no table"
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in table[2:]]


def test_the_nine_checks_are_defined_in_order() -> None:
    table = rows(section(2))
    assert [row[0] for row in table] == [str(n) for n in range(1, 10)]
    for row, name in zip(table, CHECKS, strict=True):
        assert row[1].startswith(name), (row[1], name)
        assert all(row), f"check {row[0]} has an empty column"


@pytest.mark.parametrize(("number", "width"), [(3, 5), (4, 6)])
def test_every_release_has_a_whole_row_in_both_registers(number: int, width: int) -> None:
    table = rows(section(number))
    assert [row[0] for row in table] == list(RELEASES)
    for row in table:
        assert len(row) == width, (row[0], len(row))
        assert all(row), f"{row[0]} has an empty cell in register {number}"


def test_a_release_that_ships_a_migration_has_its_restore_test_in_the_register() -> None:
    """Check 6 ('Restauración') says what the restore test took before every migration - or that there was no migration."""
    table = {row[0]: row[2] for row in rows(section(4))}
    for release, cell in table.items():
        assert cell.startswith(("✔", "n/a")), (release, cell[:40])


def test_the_register_names_leak_rules_and_isolation_tests_that_exist() -> None:
    register = section(3)
    named_rules = set(re.findall(r"`([a-z0-9_]+_known)`", register))
    assert {"tie_legs_known", "referee_known", "forecast_known", "calendar_known", "h2h_known", "factors_known"} <= named_rules
    missing = sorted(rule for rule in named_rules if rule not in leakage.RULES)
    assert not missing, f"the checklist names leak-audit rules the code does not have: {missing}"

    named_tests = set(re.findall(r"`(test_[a-z_]+_isolation\.py)`", register))
    assert {"test_forecast_isolation.py", "test_knowledge_isolation.py", "test_postmortem_isolation.py"} <= named_tests
    absent = sorted(name for name in named_tests if not (UNIT / name).is_file())
    assert not absent, f"the checklist names isolation tests that do not exist: {absent}"


def test_the_newest_leak_audit_the_register_names_is_the_one_the_code_runs() -> None:
    versions = [int(n) for n in re.findall(r"`leak-audit-v(\d+)`", section(3))]
    assert versions, "the register names no audit version"
    assert max(versions) == int(leakage.VERSION.rsplit("-v", 1)[1]), (max(versions), leakage.VERSION)


def test_the_template_has_the_nine_lines_and_both_signatures() -> None:
    template = section(7)
    block = re.search(r"```\n(.*?)```", template, flags=re.S)
    assert block, "the template is not in a code block"
    lines = block.group(1).splitlines()
    for number, name in enumerate(CHECKS, start=1):
        assert any(line.startswith(f"{number} {name}") for line in lines), f"the template lacks line {number} ({name})"
    assert any(line.startswith("Ejecutor:") and "Dueño:" in line for line in lines), "the template lacks the two signatures"


def test_what_the_list_does_not_cover_is_written_down() -> None:
    gaps = section(6)
    for word in ("e2e", "Dependencias", "Copia de seguridad fuera del servidor", "huella", "Disco"):
        assert word in gaps, f"section 6 no longer mentions {word!r}"
