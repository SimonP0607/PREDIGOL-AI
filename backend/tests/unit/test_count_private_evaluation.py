"""IA-096 (AD-E03): which corners and cards selection enters the private evaluation, and the walls around the package.

* the admission asks, in order, a verifiable settlement rule, a VALIDADO calibrator signed by the owner, a price and three books;
* its reasons are blockers of the cycle of states, so a selection that stays out says why in the cycle's words;
* the package lives outside every package with a model fingerprint and writes only its two tables (and, through the cycle's own
  statement, the cycle under its own writer); nothing that decides, publishes or serves a reader imports it;
* migration 0152 makes two append-only tables, refuses a CHAMPION without VALIDADO and writes no row.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from fbi.core import version as core_version
from fbi.countcal import admission, private, store
from fbi.countcal import calibrator as cc
from fbi.families import versioning
from fbi.lifecycle import machine

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = SRC / "countcal"


def _facts(**over: object) -> admission.Facts:
    base: dict[str, object] = {"market_key": "CORNERS_OU", "line": Decimal("9.5"), "books": 5, "validated": True, "signed": True}
    base.update(over)
    return admission.Facts(**base)  # type: ignore[arg-type]


def test_a_selection_enters_only_with_rule_calibrator_signature_and_three_books() -> None:
    ok = admission.admit(_facts())
    assert ok.admitted and ok.reason == admission.ADMITTED and ok.rule == "corners_ft@v1" and ok.family == "corners_total"
    assert admission.admit(_facts(line=Decimal("10"))).reason == admission.NO_RULE
    assert admission.admit(_facts(line=Decimal("9.25"))).reason == admission.NO_RULE
    assert admission.admit(_facts(validated=False)).reason == admission.NOT_CALIBRATED
    unsigned = admission.admit(_facts(signed=False))
    assert unsigned.reason == admission.NOT_CALIBRATED and "firma" in unsigned.detail
    assert admission.admit(_facts(books=0)).reason == admission.NO_PRICE
    assert admission.admit(_facts(books=2)).reason == admission.THIN
    assert admission.admit(_facts(books=3)).admitted


def test_the_order_of_the_checks_is_the_documented_one() -> None:
    worst = admission.admit(_facts(line=Decimal("10"), validated=False, books=0))
    assert worst.reason == admission.NO_RULE
    assert admission.admit(_facts(validated=False, books=0)).reason == admission.NOT_CALIBRATED


def test_the_cards_are_settled_by_the_rule_the_catalogue_links_and_each_key_has_its_family() -> None:
    cards = admission.admit(_facts(market_key="CARDS_OU_HOME", line=Decimal("1.5")))
    assert cards.admitted and cards.rule == "cards_lines_ft@v1" and cards.family == "cards_side"
    assert {admission.family_of(k) for k in cc.FAMILY_OF_KEY} == set(cc.FAMILIES)
    with pytest.raises(ValueError):
        admission.admit(_facts(market_key="OU"))


def test_every_reason_is_a_blocker_of_the_cycle() -> None:
    for reason in admission.REASONS:
        assert reason == admission.ADMITTED or reason in machine.BLOCKERS, reason
    assert admission.WRITER == private.WRITER
    assert re.fullmatch(r"[a-z][a-z0-9.-]{2,40}", admission.WRITER), "the cycle's CHECK on the writer"


def test_the_switches_are_born_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(private.SWITCH, raising=False)
    monkeypatch.delenv(store.SWITCH, raising=False)
    assert private.mode() == "off" and store.mode() == "off"
    monkeypatch.setenv(private.SWITCH, "on")
    assert private.mode() == "off", "only the word shadow writes"
    monkeypatch.setenv(private.SWITCH, "shadow")
    assert private.mode() == "shadow"


def test_a_write_pass_refuses_while_the_switch_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(private.SWITCH, raising=False)

    class Conn:
        def execute(self, *_: object) -> Conn:
            return self

        def fetchone(self) -> tuple[bool]:
            return (True,)

    with pytest.raises(RuntimeError, match="FBI_COUNT_EVAL"):
        private.run_pass(Conn(), now=datetime(2026, 11, 17, tzinfo=UTC), dry_run=False)  # type: ignore[arg-type]


# ── the walls ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
    return out


WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+TABLE)\s+([a-z_]+\.[a-z_]+)?",
                   re.IGNORECASE)


def test_the_package_is_outside_every_model_fingerprint() -> None:
    assert "countcal" not in core_version.MODEL_PACKAGES
    assert not any(name.startswith("countcal") for name in versioning.REUSED)
    assert versioning.fingerprint() == versioning.fingerprint(SRC), "family-v1's fingerprint reads families/ and models/goals.py only"


def test_the_package_writes_only_its_own_tables() -> None:
    writes = sorted({(p.name, m.group(1).upper().split()[0], (m.group(2) or "").lower())
                     for p in PACKAGE.glob("*.py") for s in _strings(p) for m in WRITE.finditer(s)})
    assert writes == [("store.py", "INSERT", "intel.count_calibrator_signatures"), ("store.py", "INSERT", "intel.count_calibrators")]
    text = (PACKAGE / "private.py").read_text(encoding="utf-8")
    assert "lstore.INSERT_SQL" in text and "WRITER" in text, "the cycle is written with its own statement, under count-eval-v1"


def test_nothing_that_decides_publishes_or_serves_a_reader_is_imported_by_or_imports_the_package() -> None:
    forbidden = ("fbi.decision", "fbi.picks", "fbi.parlays", "fbi.api", "fbi.notify", "fbi.customer", "fbi.narrative",
                 "fbi.familydecisions", "fbi.intel")
    found = {p.name: sorted(n for n in _imports(p) if n.startswith(forbidden) and not n.startswith("fbi.decision_"))
             for p in PACKAGE.glob("*.py")}
    assert all(not v for v in found.values()), found
    importers = set()
    for root in (SRC, ROOT / "apps", ROOT / "scripts"):
        for p in root.rglob("*.py"):
            if PACKAGE in p.parents or "__pycache__" in p.parts:
                continue
            if any(n == "fbi.countcal" or n.startswith("fbi.countcal.") for n in _imports(p)):
                importers.add(p.relative_to(ROOT).as_posix())
    assert importers == {"scripts/count_calibration.py"}, importers


# ── migration 0152 ───────────────────────────────────────────────────────────────────────────────────────────────────

MIGRATION = ROOT / "migrations" / "versions" / "0152_count_calibrators.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0152", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(sql)


def _render(direction: str) -> list[str]:
    module = _load()
    rec = _Recorder()
    vars(module)["op"] = rec
    getattr(module, direction)()
    return rec.statements


def test_0152_chains_on_the_highest_revision_of_this_tree() -> None:
    m = _load()
    assert (m.revision, m.down_revision) == ("0152", "0151")
    assert m.FAMILIES == cc.FAMILIES and m.ROLES == (store.CHAMPION, store.RETIRED)


def test_0152_makes_two_append_only_tables_and_writes_no_row() -> None:
    statements = _render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = "\n".join(statements)
    assert sql.count("CREATE TABLE") == 2
    assert "CREATE TABLE intel.count_calibrators" in sql and "CREATE TABLE intel.count_calibrator_signatures" in sql
    assert sql.count("ai.refuse_change()") == 2 and "count_signature_needs_validated" in sql
    assert "c.verdict = 'VALIDADO'" in sql and "method = 'survival-logit'" in sql
    for verb in ("INSERT INTO", "UPDATE intel.", "DELETE FROM", "TRUNCATE", "ALTER TABLE"):
        assert verb not in sql, verb
    assert "intel.calibrators " not in sql and "intel.promotions" not in sql


def test_0152_goes_back_by_dropping_only_what_it_made() -> None:
    assert _render("downgrade") == ["SET LOCAL lock_timeout = '10s'", "DROP TABLE IF EXISTS intel.count_calibrator_signatures",
                                    "DROP TABLE IF EXISTS intel.count_calibrators",
                                    "DROP FUNCTION IF EXISTS intel.count_signature_needs_validated()"]
