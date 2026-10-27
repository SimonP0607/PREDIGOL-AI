"""What a finished match turned out to be is not an input of what is said about the next one (plan F7): no pre-match reader reads Match Knowledge.

Match Knowledge is a match that is OVER, put together in layers (``fbi.knowledge``): its result, its figures, its events, its players, its
tactics, the market from its opening to the provider's last price, and the picks and post-mortems made about it. It lives in
``intel.match_knowledge`` (append-only; ``intel.match_knowledge_latest`` is its newest row) and what each line of the provider's list of events
IS - a goal, an own goal, a second yellow, a VAR decision - in ``core.fixture_event_kinds``. All of it is, by construction, the future of the
match it describes. The dossier, the AI's packet, the models, the forecast, the decision layer and the pick engine work with what was known
BEFORE a kick-off: if any of them could read this, a model trained on it, or a packet that cites it, would know the answer to the question it
asks - and the nightly proof of ``intel/leakage.py`` would have nothing to tell it by.

It is also DERIVED: a row is rebuilt when a rule changes (the ``supersedes`` chain) and ``core.fixture_event_kinds`` is rewritten when the
reading of the events changes, so even a read "as of" a moment would see today's reading of the past and not the one that was known then.
That is why it is shut to the pre-match side, and not "open with a date filter".

The door is shut in both directions: what the package imports, what its builder writes (its own two tables, and no fact of a match it reads) and
what the page of a match can reach (a read of the pure layers, and nothing that writes) are held here too.

What reads it, what writes it and which module may import which is listed here, each with why. A new reader fails the test until someone decides
it may read - and decides it here, in the open. When the post-mortem and the memory take it in (plan F8) that change adds its files with the
reason; when a PRE-match block of the packet is ever allowed to say how the last matches of a team turned out, the same change adds a leak-audit
rule (``knowledge_known``: ``known_at`` not after the packet's moment), as ``calendar_known`` did for the calendar."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from fbi.core.version import MODEL_PACKAGES

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
SCRIPTS = ROOT / "scripts"
APPS = ROOT / "apps"
MIGRATIONS = ROOT / "migrations" / "versions"

WORDS = re.compile(r"match_knowledge|fixture_event_kinds")
"""How the objects are named: the tables ``intel.match_knowledge`` and ``core.fixture_event_kinds``, the view ``intel.match_knowledge_latest``,
the ledger's job type ``match_knowledge`` and the worker's module ``fbi.ingestion.match_knowledge``."""

OWN_TABLES = {"intel.match_knowledge", "core.fixture_event_kinds"}
"""The only tables the builder writes to. It reads the facts of a match from the tables that hold them and never writes one."""

NAMES_IT = {
    "knowledge/__init__.py": "the package's docstring: says where the builder writes, and holds this very door shut",
    "knowledge/builder.py": "the writer: the only module that inserts a row of intel.match_knowledge, and the one that rewrites the lines of "
                            "core.fixture_event_kinds in the same transaction as the row they belong to",
    "knowledge/layers.py": "the pure part: it names core.fixture_event_kinds in a docstring (where the lines of the events are kept) and reads no table",
    "ingestion/match_knowledge.py": "the worker's job: one pass of the builder as a run of the ledger",
    "ops/run_watchdog.py": "the watchdog: how long a run of the job may stay open before it is closed (the job's name, nothing else)",
    "api/services/knowledge.py": "the page of a match: reads the newest row of intel.match_knowledge, for users once the owner decides and for the preview",
    "api/routers/knowledge.py": "the route of the page: GET /matches/{id}/knowledge, which calls the service",
    "apps/worker/scheduler.py": "the clock: the pass every half hour and the daily sweep, switched off with FBI_MATCH_KNOWLEDGE=0",
    "scripts/match_knowledge.py": "the owner's command: build (a dry run until --apply), coverage, audit and show",
}
"""Every file under ``src/fbi``, ``scripts`` and ``apps`` that names the objects, with why."""

IMPORTS: dict[str, dict[str, str]] = {
    "fbi.knowledge": {
        "api/services/knowledge.py": "the page of a match: only the pure layers (the names of the layers, the version of the rules, the wait "
                                     "before a match is put together) - it imports nothing that writes",
        "ingestion/match_knowledge.py": "the worker's job: a pass of the builder as a run of the ledger",
        "scripts/match_knowledge.py": "the owner's command: it builds (a dry run until --apply), counts, audits and shows",
    },
    "fbi.ingestion.match_knowledge": {
        "apps/worker/scheduler.py": "the clock: the pass every half hour and the daily sweep (imported inside the function the clock runs)",
    },
    "fbi.api.services.knowledge": {
        "api/routers/knowledge.py": "the route of the page",
        "api/services/postmatch.py": "the Postpartido (plan UX, B4) is shown while the knowledge of a finished match is: the same switch "
                                     "(users_may_see), and nothing else of the page",
    },
    "fbi.api.contracts.knowledge": {
        "api/routers/knowledge.py": "the route of the page: the model of its answer",
        "api/services/knowledge.py": "the page of a match: it answers through the models that name every field a user may see",
    },
    "fbi.api.routers.knowledge": {
        "api/app.py": "mounts the route",
    },
}
"""Module -> the files that may import it (a path under ``src/fbi``, ``apps/..`` or ``scripts/..``), each with why. Inside its own package a
module is free to import its neighbours."""

PREMATCH_PACKAGES = set(MODEL_PACKAGES) | {
    "forecasting", "picks", "parlays", "market", "odds", "datasets", "validation", "research", "analyst", "notify",
    "competitions", "people", "catalog", "families",
}
"""The packages that train a model, predict, price, decide, pick or describe a match that has not been played. A package is here whole."""

PREMATCH_FILES = {
    "intel/dossier.py", "intel/decision.py", "intel/score.py", "intel/stake.py", "intel/calibration.py", "intel/discovery.py",
    "intel/narrative.py", "intel/national.py", "intel/h2h.py", "intel/scenarios.py", "intel/tactics.py", "intel/factors.py", "intel/stats.py",
    "ai/packet.py", "ai/views.py", "ai/brief.py", "ai/review.py", "ai/context.py", "ai/evidence.py", "ai/analysis.py", "ai/absences.py",
    "ai/claims.py",
}
"""The files of the two packages that mix both sides (``intel`` and ``ai`` also hold the post-mortems, the memory and the learning of what
happened) which build or judge what is said before a kick-off: the dossier, the decision layer and its steps, the AI's packet and what reads it.
The post-mortems and the memory are the ones plan F8 may bring in, one by one, with their reason above."""


def python_files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def rel(path: Path) -> str:
    if SRC in path.parents:
        return path.relative_to(SRC).as_posix()
    if APPS in path.parents:
        return f"apps/{path.relative_to(APPS).as_posix()}"
    return f"scripts/{path.relative_to(SCRIPTS).as_posix()}"


def package_of(path: Path) -> list[str]:
    """The dotted package a file sits in, to resolve a relative import."""
    return ["fbi", *path.relative_to(SRC).parts[:-1]] if SRC in path.parents else list(path.relative_to(ROOT).parts[:-1])


def imports_of(path: Path) -> set[str]:
    """Every module a file imports, as an absolute dotted name: the lazy imports inside a function count and the relative ones are resolved."""
    package = package_of(path)
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = ".".join([*package[: len(package) - (node.level - 1)], *([module] if module else [])])
            if module:
                found.add(module)
                found.update(f"{module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def takes(names: set[str], module: str) -> bool:
    return any(n == module or n.startswith(module + ".") for n in names)


def strays(path: Path, *allowed: str) -> list[str]:
    """The ``fbi`` modules a file imports that are neither inside one of ``allowed`` nor the package that holds one of them."""
    return sorted(
        n for n in imports_of(path)
        if n.split(".")[0] == "fbi" and not any(n == a or n.startswith(a + ".") or a.startswith(n + ".") for a in allowed))


def code_strings(path: Path) -> list[str]:
    """The string constants of a file that are not docstrings: where SQL lives, and where prose cannot reach."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


WRITES = re.compile(r"(?<!DO )\b(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE|TRUNCATE(?:\s+TABLE)?)\s+([A-Za-z_][A-Za-z_0-9.]*)")


def writes_of(path: Path) -> set[str]:
    """The tables the SQL of a file writes to (``ON CONFLICT .. DO UPDATE`` writes to the table it inserts into, so it is not counted twice)."""
    return {m.group(1) for s in code_strings(path) for m in WRITES.finditer(" ".join(s.split()))}


def inside(file: str, module: str) -> bool:
    """Is ``file`` (a path under src/fbi) the module ``fbi.x.y`` or a file of the package of that name?"""
    stem = "/".join(module.split(".")[1:])
    return file == f"{stem}.py" or file.startswith(f"{stem}/")


# ── who names it, who imports it ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_only_the_listed_files_name_the_objects() -> None:
    naming = {rel(p) for p in python_files(SRC, SCRIPTS, APPS) if WORDS.search(p.read_text(encoding="utf-8"))}
    assert naming == set(NAMES_IT), (
        f"files naming Match Knowledge's tables, view or job that are not listed: {sorted(naming - set(NAMES_IT))}; "
        f"listed files that no longer do: {sorted(set(NAMES_IT) - naming)}")


@pytest.mark.parametrize("module", sorted(IMPORTS))
def test_only_the_listed_files_import_each_module(module: str) -> None:
    allowed = IMPORTS[module]
    importing = {rel(p) for p in python_files(SRC, SCRIPTS, APPS) if takes(imports_of(p), module) and not inside(rel(p), module)}
    assert importing == set(allowed), (
        f"{module}: imported by files that are not listed: {sorted(importing - set(allowed))}; "
        f"listed files that no longer import it: {sorted(set(allowed) - importing)}")


def test_the_listed_modules_exist() -> None:
    """A rename would otherwise leave the lists above guarding a name nothing has."""
    for module in IMPORTS:
        stem = SRC.joinpath(*module.split(".")[1:])
        assert stem.with_suffix(".py").exists() or (stem / "__init__.py").exists(), f"{module} is listed and does not exist"


def test_only_its_own_migrations_name_the_tables() -> None:
    """A view, a function or a foreign key over the tables is made by a migration: the one that makes it is the one that must be listed here, so
    that no pre-match reader reaches Match Knowledge through an object that does not carry its name."""
    naming = {p.name for p in MIGRATIONS.glob("*.py") if WORDS.search(p.read_text(encoding="utf-8"))}
    # 0092 (plan F9) adds market.fixture_outcomes: a view of how FINISHED matches ended, whose cards by period are counted from the classified
    # events. It is a dataset of OUTCOMES - the labels that grade a bet and, one day, train a model - not a pre-match input, and the next test
    # holds the door: the model packages never name it (F10 opens that door by deciding it here, with its own leakage tests).
    assert naming == {"0089_event_kinds.py", "0090_match_knowledge.py", "0092_market_catalogue.py"}, (
        f"migrations naming Match Knowledge's tables: {sorted(naming)}. A migration that adds an object over them (a view, a function, a key) opens "
        "a second way in: decide here, with the reason, whether the pre-match side may reach it")


def test_the_view_of_outcomes_is_not_named_by_the_models() -> None:
    """``market.fixture_outcomes`` holds what finished matches turned out to be (plan F9). It is read by the catalogue (the matrix and the
    discovery: weekly, offline, to say what could be graded) and by nobody that makes a statement before a kick-off."""
    forbidden = ("models", "features", "predictions", "backtesting", "domain")
    naming = sorted(rel(p) for p in python_files(SRC) if rel(p).split("/")[0] in forbidden and "fixture_outcomes" in p.read_text(encoding="utf-8"))
    assert naming == [], f"model code naming the view of outcomes: {naming}. Deciding that it may is F10's, with its leakage tests"


def test_the_families_read_the_outcomes_through_one_door_that_waits_for_the_result() -> None:
    """Plan F10 opens the door F9 kept shut, in ONE module: ``families/history.py``. It reads the view, it waits for the result to be known
    (``OUTCOME_KNOWN_AFTER``) and the rest of the families get their matches from it."""
    naming = sorted(rel(p) for p in python_files(SRC) if rel(p).split("/")[0] == "families" and "fixture_outcomes" in p.read_text(encoding="utf-8"))
    assert naming == ["families/history.py"], f"modules of the families naming the view of outcomes: {naming}"
    door = (SRC / "families" / "history.py").read_text(encoding="utf-8")
    assert "OUTCOME_KNOWN_AFTER" in door and "latest_kickoff(cutoff)" in door
    fit = (SRC / "families" / "fit.py").read_text(encoding="utf-8")
    assert "known_at(m) <= at" in fit, "and the fit applies the rule again: two guards, because a future leaks here"


# ── the pre-match side ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def prematch_files() -> list[Path]:
    packages = [p for p in python_files(SRC) if rel(p).split("/")[0] in PREMATCH_PACKAGES]
    files = [SRC / name for name in sorted(PREMATCH_FILES)]
    return sorted(set(packages) | set(files))


def test_the_test_looks_where_the_readers_are() -> None:
    """A search of nothing passes: the packages and the files named above must be there, and be many."""
    for package in PREMATCH_PACKAGES:
        assert (SRC / package).is_dir(), f"{package} is listed as a pre-match package and is not one"
    for name in PREMATCH_FILES:
        assert (SRC / name).is_file(), f"{name} is listed as a pre-match file and is not one"
    assert "models" in PREMATCH_PACKAGES and "forecasting" in PREMATCH_PACKAGES and "intel/dossier.py" in PREMATCH_FILES
    assert {"ai/packet.py", "intel/decision.py", "picks/pipeline.py", "forecasting/match_forecast.py"} <= {rel(p) for p in prematch_files()}
    assert len(prematch_files()) > 100, len(prematch_files())


def test_nothing_before_a_kickoff_names_or_imports_it() -> None:
    """The names, in words: whatever else changes, none of these appears in a file that builds or judges what is said before a match."""
    for path in prematch_files():
        text = path.read_text(encoding="utf-8")
        name = rel(path)
        assert not WORDS.search(text), f"{name} names Match Knowledge: what a match turned out to be is not an input of what is said before it"
        assert "fbi.knowledge" not in text, f"{name} names the package of Match Knowledge"
        names = imports_of(path)
        for module in IMPORTS:
            assert not takes(names, module), f"{name} imports {module}: a match that is over is the future of the one it describes"


def test_no_file_allowed_to_read_it_is_a_prematch_reader() -> None:
    """The lists above are how a reader is let in; this is what stops one being let in by editing them."""
    allowed = set(NAMES_IT) | {f for files in IMPORTS.values() for f in files}
    for name in sorted(allowed):
        top = name.split("/")[0]
        assert name not in PREMATCH_FILES and top not in PREMATCH_PACKAGES, (
            f"{name} may read Match Knowledge and is a pre-match reader: move it out of the lists, not the file into them")


# ── what the package may reach ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_package_depends_on_nothing_of_ours_but_the_sides() -> None:
    """It is read by the page, the job and the command and must never need them back: no model, no pick, no packet, no provider."""
    files = python_files(SRC / "knowledge")
    assert len(files) >= 5, files
    for path in files:
        assert not strays(path, "fbi.knowledge", "fbi.people.sides"), f"{rel(path)} imports {strays(path, 'fbi.knowledge', 'fbi.people.sides')}"


def test_the_job_reaches_the_ledger_and_the_package_and_nothing_else() -> None:
    path = SRC / "ingestion" / "match_knowledge.py"
    assert not strays(path, "fbi.ingestion.ledger", "fbi.knowledge"), strays(path, "fbi.ingestion.ledger", "fbi.knowledge")


def test_the_package_and_its_job_are_not_model_code() -> None:
    """The version of every model is the fingerprint of the model packages (``fbi.core.version``): a change to Match Knowledge must not renew it."""
    assert "knowledge" not in MODEL_PACKAGES and "ingestion" not in MODEL_PACKAGES


# ── what it writes, what the page reaches ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_builder_writes_its_own_tables_and_no_fact_of_a_match() -> None:
    """The facts of a match - fixtures, events, statistics, players, prices, picks - are only read: Match Knowledge is built from them, never into them."""
    files = [*python_files(SRC / "knowledge"), SRC / "ingestion" / "match_knowledge.py", SCRIPTS / "match_knowledge.py"]
    written: set[str] = set()
    for path in files:
        written |= writes_of(path)
    assert written == OWN_TABLES, f"the builder writes {sorted(written)}; it may write {sorted(OWN_TABLES)} and nothing else"


def test_the_page_of_a_match_reads_and_builds_nothing() -> None:
    """``GET /matches/{id}/knowledge`` cannot put a match together, call the provider or touch a pick: it reaches the pure layers, the API's own
    modules and the platform's, and no module that writes (not the builder, not the reader of the facts, not the job)."""
    for name in ("api/services/knowledge.py", "api/routers/knowledge.py", "api/contracts/knowledge.py"):
        path = SRC / name
        assert not writes_of(path), f"{name} writes to {sorted(writes_of(path))}"
        stray = strays(path, "fbi.api", "fbi.core", "fbi.auth", "fbi.knowledge.layers")
        assert not stray, f"{name} imports {stray}: the page may read the pure layers and nothing that builds"
