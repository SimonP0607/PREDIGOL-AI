"""``intel.decisions`` holds the decisions of more than one layer, and nothing a layer of research decides may reach a reader that is not about it.

The pipeline's decision layer (``decision-v1``) and the families' (``decision-fam-v1``, plan F11: corners, cards and the goals of the halves, in shadow,
off by default) write to the same table and the same outcomes table. Every page a user can open, every post-mortem, the memory, the report of the day,
the cost per candidate, the picks of the day and Match Knowledge read ``intel.decisions``: a reader that forgot to say WHICH layer it reads would show
a family's selection as if the pipeline had made it, count it in the calibration, spend a review on it. This test holds every statement in the code that
reads one of the two tables to say so - a comparison on ``decision_version`` - or to be on the list below with the reason it reads another way.

* a statement that reads ``intel.decisions`` compares ``decision_version`` as many times as it reads the table, or is on ``READS_BY_ID`` / ``READS_ALL``;
* a statement that reads ``intel.decision_outcomes`` without the decisions beside it (so it cannot say the layer) is on the list too;
* only the files on ``WRITERS`` write the two tables;
* the versions are the ones of ``fbi.core.decision_versions`` wherever they are written, and the one copy of the core version that ``fbi.knowledge`` is
  allowed to keep (it may import nothing of ours) is held equal to it;
* only the worker and the commands import the families' decision and settlement modules, so the pipeline's code cannot call them.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from fbi.core import decision_versions as dv

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
APPS = ROOT / "apps"
SCRIPTS = ROOT / "scripts"

READ = re.compile(r"\b(?:FROM|JOIN)\s+intel\.(decisions|decision_outcomes)\b", re.IGNORECASE)
WRITE = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+intel\.(decisions|decision_outcomes)\b", re.IGNORECASE)
COMPARES = re.compile(r"\bdecision_version\s*(?:=|<>|!=|\bIN\b)", re.IGNORECASE)

BY_ID = "reads one decision (or its outcome) by its id: an id belongs to one layer, and the page or the step that holds it knows which"

READS_BY_ID: dict[tuple[str, str], str] = {
    ("api/services/intelligence.py", "FROM intel.decisions d JOIN core.fixtures f ON f.id = d.fixture_id"):
        "the detail of one decision, asked for by id from the day's list or (F10.17) from the list of the families; its history below is held to its layer",
    ("api/services/intelligence.py", "SELECT * FROM intel.decision_outcomes WHERE decision_id"): BY_ID,
    ("intel/decision.py", "FROM intel.decisions WHERE id = %s ON CONFLICT DO NOTHING"):
        "the copy of a decision as a selection of the day: it carries the version of the decision it copies",
    ("intel/decision.py", "WHERE d.id = ANY(%s)"):
        "the competitions of the decisions the day's picks already chose, which were chosen from the core layer's own rows",
}
"""Statements that name no layer because the thing they read is one row, asked for by id."""

READS_ALL: dict[tuple[str, str], str] = {
    ("picks/resettlement.py", "SELECT count(*) FROM intel.decision_outcomes o JOIN intel.decisions d"):
        "counts the outcomes built on the result of a match that was corrected: those of every layer are as stale as each other",
    ("intel/leakage.py", "FROM intel.decisions d WHERE d.known_at"):
        "the audit of leakage reads every layer on purpose: it is the check that none of them wrote what it could not have known",
}
"""Statements that read every layer, with why."""

WRITERS: dict[str, set[str]] = {
    "intel/decision.py": {"decisions"},
    "intel/outcomes.py": {"decision_outcomes"},
    "familydecisions/outcomes.py": {"decision_outcomes"},
}
"""The files that write the two tables (a path under ``src/fbi``): the decision layer writes ``intel.decisions`` - for every layer, ``families.decide``
hands it the rows - and each settlement writes the outcomes of its own decisions."""


@dataclass(frozen=True)
class Statement:
    file: str
    line: int
    text: str


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def strings(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Every string literal of the code that is not a docstring (an expression statement that is only a string), an f-string as one piece with ``{}``
    where a value goes, and a literal inside an f-string only as part of it."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            skip.add(id(node.value))
        if isinstance(node, ast.JoinedStr):
            skip.update(id(v) for v in node.values)
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            yield node.lineno, "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}" for v in node.values)


@cache
def statements() -> tuple[Statement, ...]:
    out: list[Statement] = []
    for root in (SRC, APPS, SCRIPTS):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for line, text in strings(ast.parse(path.read_text(encoding="utf-8"))):
                if READ.search(text) or WRITE.search(text):
                    out.append(Statement(rel(path), line, text))
    return tuple(out)


def listed(table: dict[tuple[str, str], str], s: Statement) -> bool:
    return any(file == s.file and snippet in s.text for file, snippet in table)


def test_the_scan_finds_the_statements_it_is_meant_to_hold() -> None:
    """A scan that finds nothing would pass for ever: it must see the readers it is written for."""
    files = {s.file for s in statements()}
    assert {"intel/decision.py", "intel/outcomes.py", "intel/report.py", "intel/memory.py", "intel/postmortem.py", "knowledge/reader.py",
            "api/services/intelligence.py", "api/services/forecast.py", "familydecisions/outcomes.py", "picks/resettlement.py", "intel/leakage.py",
            "research/trace.py", "research/pattern_search.py", "market/matrix.py"} <= files
    assert len([s for s in statements() if READ.search(s.text)]) >= 25


def test_every_statement_that_reads_the_decisions_says_which_layer_it_reads() -> None:
    loose = []
    for s in statements():
        reads = [m for m in READ.finditer(s.text) if m.group(1).lower() == "decisions"]
        if not reads or listed(READS_BY_ID, s) or listed(READS_ALL, s):
            continue
        if len(COMPARES.findall(s.text)) < len(reads):
            loose.append(f"{s.file}:{s.line}: reads intel.decisions {len(reads)} time(s) and compares decision_version "
                         f"{len(COMPARES.findall(s.text))}: {' '.join(s.text.split())[:140]}")
    assert not loose, ("these statements would show the decisions of a layer of research as the pipeline's - compare decision_version "
                       "(fbi.core.decision_versions) or list them with the reason:\n" + "\n".join(loose))


def test_a_statement_that_reads_the_outcomes_alone_cannot_say_the_layer_and_is_listed() -> None:
    loose = [f"{s.file}:{s.line}: {' '.join(s.text.split())[:140]}" for s in statements()
             if any(m.group(1).lower() == "decision_outcomes" for m in READ.finditer(s.text))
             and not any(m.group(1).lower() == "decisions" for m in READ.finditer(s.text))
             and not listed(READS_BY_ID, s) and not listed(READS_ALL, s)]
    assert not loose, "an outcome read without its decision cannot be held to a layer; join the decisions or list it:\n" + "\n".join(loose)


def test_the_lists_hold_only_statements_that_still_exist() -> None:
    """A list that outlives its statement would excuse the next statement that happens to look like it."""
    for table in (READS_BY_ID, READS_ALL):
        for file, snippet in table:
            assert any(s.file == file and snippet in s.text for s in statements()), f"{file}: no statement contains {snippet!r} any more"


def test_every_entry_of_the_lists_has_a_reason_that_says_something() -> None:
    for table in (READS_BY_ID, READS_ALL):
        for key, reason in table.items():
            assert len(reason.split()) >= 8, f"{key}: say why"


def test_only_the_files_that_own_the_tables_write_them() -> None:
    wrong = []
    for s in statements():
        for m in WRITE.finditer(s.text):
            if m.group(1).lower() not in WRITERS.get(s.file, set()):
                wrong.append(f"{s.file}:{s.line} writes intel.{m.group(1)}")
    assert not wrong, "a table written from a new place is a layer nobody listed:\n" + "\n".join(wrong)
    for file, tables in WRITERS.items():
        assert any(s.file == file and any(m.group(1).lower() in tables for m in WRITE.finditer(s.text)) for s in statements()), (
            f"{file} is listed as a writer and writes nothing")


def test_the_versions_are_distinct_and_the_layers_say_which_is_which() -> None:
    layers: list[str] = [dv.DECISION_CORE, dv.DECISION_FAMILIES]
    results: list[str] = [dv.OUTCOME_CORE, dv.OUTCOME_FAMILIES]
    assert len(set(layers)) == 2 and len(set(results)) == 2, "two layers, two versions of each"
    assert dv.LAYERS == {"core": dv.DECISION_CORE, "families": dv.DECISION_FAMILIES}
    assert dv.DECISION_FAMILIES.startswith("decision-fam-") and dv.OUTCOME_FAMILIES.startswith("outcome-fam-")


def test_each_module_takes_its_version_from_the_one_place_that_defines_them() -> None:
    from fbi.familydecisions import decide
    from fbi.familydecisions import outcomes as family_outcomes
    from fbi.intel import decision
    from fbi.intel import outcomes as core_outcomes
    from fbi.knowledge import reader

    assert decision.VERSION == dv.DECISION_CORE and decide.VERSION == dv.DECISION_FAMILIES
    assert core_outcomes.VERSION == dv.OUTCOME_CORE and family_outcomes.VERSION == dv.OUTCOME_FAMILIES
    assert decide.CORE_VERSION == dv.DECISION_CORE
    assert reader.DECISION_LAYER == dv.DECISION_CORE, (
        "fbi.knowledge may import nothing of ours but itself, so it keeps a copy of the core version; the copy must not drift")


def test_no_statement_writes_a_decision_version_by_hand() -> None:
    """The versions are written where the code names them (``fbi.core.decision_versions``), not copied into a statement: a copy is a version that
    is not renamed the day the layer is."""
    literal = re.compile(r"decision-(?:fam-)?v\d+|outcome-(?:fam-)?v\d+")
    found = [f"{s.file}:{s.line}: {' '.join(s.text.split())[:120]}" for s in statements() if literal.search(s.text)]
    assert not found, "write the version as a parameter:\n" + "\n".join(found)


PACKAGE = "fbi.familydecisions"
MAY_IMPORT_THE_PACKAGE = {
    "apps/worker/scheduler.py": "the clock hands the steps of the families to the intelligence jobs",
    "scripts/families.py": "the owner's command: the decision of the families, read-only until asked",
}
"""The files outside ``fbi.familydecisions`` that import it (and why). ``fbi.intel`` must not: the package sits above it and above ``fbi.families``
(``tests/unit/test_architecture.py`` holds the import cycle at its size) and the pipeline's code has no business calling research. Nor may ``fbi.families``:
a file added there renews the version of every family (``fbi.families.versioning``)."""


def test_only_the_clock_and_the_commands_import_the_package_of_the_decisions_of_the_families() -> None:
    importers: dict[str, set[str]] = {}
    for root in (SRC, APPS, SCRIPTS):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or rel(path).startswith("familydecisions/"):
                continue
            found: set[str] = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    if node.module == PACKAGE or node.module.startswith(PACKAGE + "."):
                        found.add(node.module)
                elif isinstance(node, ast.Import):
                    found.update(a.name for a in node.names if a.name == PACKAGE or a.name.startswith(PACKAGE + "."))
            if found:
                importers[rel(path)] = found
    assert set(importers) <= set(MAY_IMPORT_THE_PACKAGE), (
        f"the decision of the families reaches code that is not the clock or a command: "
        f"{ {k: sorted(v) for k, v in importers.items() if k not in MAY_IMPORT_THE_PACKAGE} }")
    assert "apps/worker/scheduler.py" in importers, "the worker is how the families' steps run"


def test_the_package_is_not_a_file_of_the_family_models() -> None:
    """The fingerprint of the sources of ``fbi.families`` is the version of a family's model: what is decided with a forecast is not part of it, so
    nothing of the decision, its settlement or what is learned from them may live in that package."""
    from fbi.families import versioning

    fingerprinted = {p.relative_to(SRC).as_posix() for p in (SRC / "families").rglob("*.py")}
    assert not {name for name in fingerprinted if name.rsplit("/", 1)[-1] in {"decide.py", "outcomes.py", "postmortem.py", "memory.py"}}, (
        "the decision of a family and what is learned from it live in fbi.familydecisions, outside the fingerprint of the models")
    assert versioning.fingerprint().isalnum()
