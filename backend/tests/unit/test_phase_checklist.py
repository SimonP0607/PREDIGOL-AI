"""Plan F14: the checklist of each phase is whole, and what it names is in the code.

``docs/owner/CHECKLIST_POR_FASE_F14.md`` is the signed list the plan asks for: nine checks, and for every release the datum that proves each (or
the reason it does not apply, or a dash for "nobody wrote it down then"). A list nobody keeps whole is a list nobody reads, so this file holds
its shape - the nine checks, one row for every release in both registers, no empty cell, the template with its nine lines - and ties the part that can
be tied to the code: every rule of the nightly leak audit and every isolation test the register names exists, and the newest audit version it
names is the one the code runs, with the number of rules the code has. The numbers of a past gate (tests that passed, seconds a restore took) are history
and are not compared. A release that is built and not deployed yet is the only row that may say ``pendiente: <what it waits for>``, and a release is never
deployed with the numbers of its gate still pending."""

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

RELEASES = ("F0 + F1", "F0.1", "F2", "F3 + F1.1", "F3.2 + F5", "F4", "F6", "F7", "F8", "F9", "F10", "F11 + F12 + F13", "F14 (con F11.5 a F13.12)",
            "F11.7 a F11.12 (con F10.17)")
"""One row per release of the plan, oldest first (F5 shipped with F3.2, F13 with F11 and F12, the rest of F11 to F13 with F14, and the cycle of the families
in shadow - F11.7 to F11.12, with the admin page F10.17 - after it)."""
PENDING = "pendiente"
"""How a cell of a release that is built and not deployed yet begins: what only exists after the deploy is filled in with the real datum then."""
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
    """Check 6 ('Restauración') says what the restore test took before every migration - or that there was no migration - or, for a release that is
    not deployed yet, that the test is still to be done. A deployed release is never pending."""
    table = {row[0]: (row[2], row[3]) for row in rows(section(4))}
    for release, (restore, deploy) in table.items():
        assert deploy.startswith(("✔", PENDING)), (release, deploy[:40])
        allowed = (PENDING,) if deploy.startswith(PENDING) else ("✔", "n/a")
        assert restore.startswith(allowed), (release, restore[:40])


def test_only_the_newest_release_may_be_pending_and_it_says_what_it_waits_for() -> None:
    """A release that is built and not deployed has no datum of the deploy to write: its cells say ``pendiente: <what is awaited>``. Only the last row may,
    in either register: an older row that still waits for its datum is a release nobody closed."""
    pending: set[str] = set()
    for number in (3, 4):
        for row in rows(section(number)):
            for position, cell in enumerate(row[1:], start=1):
                if cell.startswith(PENDING):
                    assert re.match(rf"{PENDING}: \S", cell), (row[0], number, position, cell[:40])
                    pending.add(row[0])
    assert pending <= {RELEASES[-1]}, sorted(pending - {RELEASES[-1]})
    not_deployed = {row[0] for row in rows(section(4)) if row[3].startswith(PENDING)}
    for row in rows(section(4)):
        if row[0] in not_deployed:  # neither the restart of the worker nor the restore has happened if the deploy has not
            assert row[1].startswith(PENDING) and row[2].startswith(PENDING), row[0]
    waiting_for_numbers = {row[0] for row in rows(section(3)) if any(cell.startswith(PENDING) for cell in row[1:])}
    assert waiting_for_numbers <= not_deployed, "a release was deployed with the numbers of its gate still pending"


def test_the_register_names_leak_rules_and_isolation_tests_that_exist() -> None:
    register = section(3)
    named_rules = set(re.findall(r"`([a-z0-9_]+_known)`", register))
    assert {"tie_legs_known", "referee_known", "forecast_known", "calendar_known", "h2h_known", "factors_known", "family_forecast_known",
            "family_price_known"} <= named_rules
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


def test_the_register_says_how_many_rules_the_newest_audit_has() -> None:
    """'`leak-audit-vN`, M reglas' for the version the code runs: a rule added to the audit without the row of its release is seen here."""
    found = re.search(rf"`{re.escape(leakage.VERSION)}`, (\d+) reglas", section(3))
    assert found, f"the register does not say how many rules {leakage.VERSION} has"
    assert int(found.group(1)) == len(leakage.RULES), (found.group(1), len(leakage.RULES))


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
