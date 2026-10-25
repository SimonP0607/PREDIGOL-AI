"""What a selection turned out to be, and what has been learned from it, is not an input of what is said about the next match (plan F8): no
pre-match reader reads the post-mortem, the memory or the notes learned from them.

THE post-mortem (``fbi.intel.postmortem``, pm-v6) judges a selection AFTER its match: the verdict, the price it was taken at against the close,
what the AI said and what was missed. It lives in ``intel.postmortems`` (append-only; ``intel.selection_postmortems`` is the view the readers use,
which carries the history of pm-v2 until the cut-over), the match's own in ``intel.match_postmortems`` and the optional narratives of a language
model in ``ai.postmortem_narratives``; the two older writers (``ai.pick_postmortems``, ``ai.postmortems``) are frozen behind
``FBI_AI_LEGACY_POSTMORTEMS``. The memory (``fbi.intel.memory``, memory-v4: ``intel.entity_memory``, its newest state in
``intel.entity_memory_latest``) accumulates those verdicts and the facts of the finished matches by team, league, market, referee, coach and
player; the AI's own log is ``ai.memory_events`` and what it learned each day is ``ai.learning_notes``.

All of it is, by construction, the future of the match it describes, and all of it is DERIVED: a rule that changes rebuilds it (a new version of
the post-mortem, ``scripts.memory rebuild``), so even a read "as of" a moment would see today's reading of the past and not the one that was
known then. The dossier, the AI's packet, the models, the forecast, the decision layer and the pick engine work with what was known BEFORE a
kick-off: if any of them could read this, a model trained on it, or a packet that cites it, would know the answer to the question it asks - and
the nightly proof of ``intel/leakage.py`` would have nothing to tell it by.

The families of counts (plan F11: corners, cards, the goals of the halves; in shadow) learn from their own decisions in tables apart -
``intel.family_postmortems`` and ``intel.family_memory`` with its view ``intel.family_memory_latest`` (migration 0094; ``fbi.familydecisions``) -
so that a research layer with forecasts that are not calibrated does not move the sample sizes, the verdicts or the confidence of the layer that
acts. They are held to the same rule: they are the future of the match they describe, they are derived, and nothing that is said before a kick-off
reads them.

The memory is NOT in the AI's packet, and that is a decision, not an omission: whether PrediGol's own history of a team, a referee or a market
goes into what the AI reads before a match is the owner's (plan F8, decision 17). When it does, that change adds its files here with the reason
and a leak-audit rule (``memory_known``: ``built_at`` not after the packet's moment and ``as_of_day`` before the match day), as ``calendar_known``
did for the calendar.

What reads it, what writes it, which module may import which and where the cycles bring it in are listed here, each with why. A new reader fails
the test until someone decides it may read - and decides it here, in the open."""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path

import pytest

from fbi.core.version import MODEL_PACKAGES

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
SCRIPTS = ROOT / "scripts"
APPS = ROOT / "apps"
MIGRATIONS = ROOT / "migrations" / "versions"

WORDS = re.compile(
    r"\b(?:intel\.(?:postmortems|selection_postmortems|match_postmortems|entity_memory(?:_latest)?|family_postmortems|family_memory(?:_latest)?)"
    r"|ai\.(?:postmortem_narratives|learning_notes|pick_postmortems|postmortems|memory_events))\b")
"""How the objects are named: the post-mortem (``intel.postmortems``, the view ``intel.selection_postmortems``, ``intel.match_postmortems``, the
narratives ``ai.postmortem_narratives`` and the two frozen tables), the memory (``intel.entity_memory`` and its view, the events
``ai.memory_events``), the notes (``ai.learning_notes``) and what the families of counts learned (``intel.family_postmortems``,
``intel.family_memory`` and its view). Always with their schema: that is how every query of the platform writes them."""

NAMES_IT: dict[str, str] = {
    "intel/postmortem.py": "THE post-mortem (pm-v6): the only writer of intel.postmortems (it reads the selections already studied, to write each once)",
    "intel/match_review.py": "the post-mortem BY MATCH (what pm-v1.1 held, without the narrative): the only writer of intel.match_postmortems",
    "intel/memory.py": "the memory (memory-v4): the only writer of intel.entity_memory, and the reader of the post-mortems it rests on",
    "intel/pm_questions.py": "the questions and verdicts of the post-mortem (pure): it names the frozen column ai.pick_postmortems.clv in a docstring",
    "intel/report.py": "the daily report of PrediGol Intelligence: what yesterday's post-mortems and the memory say, written for the owner",
    "ai/pm_narratives.py": "the narratives a language model may write (ai.postmortem_narratives): optional, paid for and kept apart, one per post-mortem",
    "ai/memory.py": "the writer of the AI's memory events (ai.memory_events), the log the patterns count",
    "ai/learning.py": "the learning cycle: reads the day's post-mortems and writes the notes (ai.learning_notes); the frozen tables are named "
                      "for the history before plan F8",
    "ai/patterns.py": "the patterns over the memory events and the post-mortems of the matches: hypotheses for the owner, never a rule",
    "ai/daily_review.py": "the close of the day (a report): the day's post-mortems, memory events and notes; it changes no pick, probability or rule",
    "ai/pick_postmortem.py": "pm-v2, FROZEN: writes ai.pick_postmortems only behind FBI_AI_LEGACY_POSTMORTEMS, after the one post-mortem",
    "ai/postmortem.py": "pm-v1.1, FROZEN: writes ai.postmortems only behind FBI_AI_LEGACY_POSTMORTEMS, after the one post-mortem",
    "knowledge/layers.py": "Match Knowledge (plan F7), layer c9: the pure layer that turns the post-mortems of a finished match into facts",
    "knowledge/reader.py": "Match Knowledge (plan F7): reads the post-mortems of the finished matches it puts together (layer c9)",
    "api/services/intelligence.py": "the Admin Console's PrediGol Intelligence: the post-mortem of a decision and the memory (GET /admin/intelligence/memory)",
    "api/services/ai_v2.py": "the Admin Console's post-mortems, learning and sources: the selections of a day with their narratives and notes",
    "api/services/ai_layer.py": "the Admin Console's AI pages: the dashboard of errors, the day's counts and the log of memory events (the card a "
                                "user is shown, match_analysis, reaches none of it: held below)",
    "api/services/match_memory.py": "the Memory page: the matches PrediGol looked at, by team, league, coach, player and market",
    "scripts/postmortems.py": "the owner's command for the post-mortem: status, coverage, closes (the two closes a price is judged against) and "
                              "build (a dry run until --apply)",
    "scripts/memory.py": "the owner's command for the memory: status, coverage, rebuild (a dry run until --apply) and audit",
}
"""Every file under ``src/fbi``, ``scripts`` and ``apps`` that names the objects and sits after a kick-off, with why."""

EXCEPTIONS: dict[str, str] = {
    "picks/resettlement.py": "re-settlement of a corrected result: it COUNTS the rows built on the old result (STALE_SQL: how many post-mortems "
                             "would be stale) to tell the owner; it reads nothing of their content and decides nothing before a kick-off",
    "market/closing_value.py": "its docstring says that ai.pick_postmortems.clv held a price move before clv-v1: a note about history, no query",
}
"""The only files of the pre-match packages that name the objects, each with why. They may count or remember; they may not read."""

IMPORTS: dict[str, dict[str, str]] = {
    "fbi.intel.postmortem": {
        "intel/cycle.py": "the nightly: the post-mortems step (study, then the match review)",
        "intel/report.py": "the daily report names the version of the post-mortem it read",
        "ai/cycle.py": "the learning cycle: the same function, so that whichever of the two jobs runs first writes the day",
        "ai/pm_narratives.py": "the narratives wait as long as the post-mortem does before a selection counts as settled (SETTLE_DELAY)",
        "scripts/postmortems.py": "the owner's command: build (a dry run until --apply), status, coverage and closes",
    },
    "fbi.intel.match_review": {
        "intel/cycle.py": "the nightly: the post-mortems step reviews the matches after the selections",
        "intel/postmortem.py": "the analysis of a match is the base of the post-mortem of its selections",
        "ai/cycle.py": "the learning cycle: the same functions",
        "ai/learning.py": "the notes name the version of the match review they read",
        "ai/patterns.py": "the patterns name the version of the match review they count",
        "ai/postmortem.py": "pm-v1.1, frozen: it still writes its events with the match review's analysis",
        "scripts/postmortems.py": "the owner's command: build, status and coverage of the post-mortem by match",
    },
    "fbi.intel.pm_questions": {
        "intel/pm_facts.py": "the facts of a selection are what the questions are asked of",
        "intel/postmortem.py": "the questions, the class of a loss and the verdicts",
        "intel/match_review.py": "the log loss of a forecast against the close",
        "ai/learning.py": "the CLV the notes quote is read the way the post-mortem stored it (stored_clv)",
        "ai/pick_postmortem.py": "pm-v2, frozen: it asks the same ten questions through the same functions",
        "api/services/ai_v2.py": "the Admin Console reads the CLV the way the post-mortem stored it (stored_clv)",
    },
    "fbi.intel.pm_facts": {
        "intel/postmortem.py": "the facts a selection is judged from",
        "ai/daily_review.py": "which roles belong to the AI (AI_ROLES)",
        "ai/learning.py": "which roles belong to the AI (AI_ROLES)",
        "ai/pick_postmortem.py": "pm-v2, frozen: who a report was about",
        "ai/pm_narratives.py": "which roles belong to the AI (AI_ROLES)",
        "api/services/ai_v2.py": "which roles belong to the AI (AI_ROLES)",
        "scripts/postmortems.py": "which roles belong to the AI (AI_ROLES)",
    },
    "fbi.intel.memory": {
        "intel/cycle.py": "the nightly: the memory step, which waits until its own lineage begins",
        "scripts/memory.py": "the owner's command: status, coverage, rebuild (a dry run until --apply) and audit",
    },
    "fbi.intel.report": {
        "intel/cycle.py": "the nightly: the report of the day, written last",
    },
    "fbi.ai.memory": {
        "intel/postmortem.py": "the memory events of a selection, under the keys the first version used",
        "intel/match_review.py": "the memory events of a match, under the keys the first version used",
        "ai/pick_postmortem.py": "pm-v2, frozen: its events",
    },
    "fbi.ai.postmortem": {
        "ai/cycle.py": "the frozen writer, called only behind FBI_AI_LEGACY_POSTMORTEMS",
        "ai/pick_postmortem.py": "pm-v2, frozen: the analysis of the match it builds on",
    },
    "fbi.ai.pick_postmortem": {
        "ai/cycle.py": "the frozen writer, called only behind FBI_AI_LEGACY_POSTMORTEMS",
    },
    "fbi.ai.pm_narratives": {
        "ai/cycle.py": "the learning cycle: the narratives, after the post-mortems, when a model is configured",
    },
    "fbi.ai.learning": {
        "ai/cycle.py": "the learning cycle: the notes of the day",
    },
    "fbi.ai.patterns": {
        "ai/cycle.py": "the learning cycle: the patterns that become hypotheses",
    },
    "fbi.ai.daily_review": {
        "apps/worker/scheduler.py": "the clock: the close of the day at 23:59 Bogotá and the revisions that follow",
    },
    "fbi.api.services.intelligence": {
        "api/routers/intelligence.py": "the routes of PrediGol Intelligence, all of the Admin Console",
    },
    "fbi.api.services.match_memory": {
        "api/routers/ai_layer.py": "GET /admin/ai/match-memory",
    },
    "fbi.api.services.ai_v2": {
        "api/routers/ai_layer.py": "the admin routes of the AI pages: post-mortems, learning, sources",
        "api/services/ai_layer.py": "the AI overview quotes the day's counts of the pages beside it",
    },
    "fbi.api.services.ai_layer": {
        "api/routers/ai_layer.py": "the admin routes of the AI pages and, beside them, the card of a match (held below)",
        "api/routers/evolution.py": "the dashboard of the evolution loop: errors and findings",
    },
}
"""Module -> the files that may import it (a path under ``src/fbi``, ``apps/..`` or ``scripts/..``), each with why. Inside its own file a module is
free to use itself; its neighbours are listed."""

WRITERS: dict[str, set[str]] = {
    "intel/postmortem.py": {"intel.postmortems"},
    "intel/match_review.py": {"intel.match_postmortems"},
    "intel/memory.py": {"intel.entity_memory"},
    "ai/pm_narratives.py": {"ai.postmortem_narratives"},
    "ai/memory.py": {"ai.memory_events"},
    "ai/pick_postmortem.py": {"ai.pick_postmortems"},
    "ai/postmortem.py": {"ai.postmortems"},
    "ai/learning.py": {"ai.learning_notes", "ai.source_stats"},
    "ai/daily_review.py": {"ai.daily_reviews"},
    "intel/report.py": {"intel.daily_reports"},
    "ai/patterns.py": set(),
    "intel/pm_facts.py": set(),
    "intel/pm_questions.py": set(),
}
"""File -> the only tables its SQL writes to. A post-mortem, a memory or a note is built FROM the facts of a match - fixtures, events, statistics,
players, prices, picks, settlements - and never into them (``ai.source_stats`` is the day's tally of the sources the notes quote)."""

READ_ONLY = ("api/services/intelligence.py", "api/services/ai_v2.py", "api/services/match_memory.py", "scripts/postmortems.py", "scripts/memory.py")
"""The pages and commands that look at the post-mortem and the memory write nothing themselves: what a command builds, the builders write."""

CYCLES: dict[str, dict[str, set[str]]] = {
    "ai/cycle.py": {
        "_postmortems": {"fbi.ai.pm_narratives", "fbi.intel.match_review", "fbi.intel.postmortem"},
        "_legacy_postmortems": {"fbi.ai.pick_postmortem", "fbi.ai.postmortem"},
        "run_learning_cycle": {"fbi.ai.learning", "fbi.ai.patterns"},
    },
    "intel/cycle.py": {
        "versions": {"fbi.intel.memory", "fbi.intel.postmortem", "fbi.intel.report"},
        "memory_step": {"fbi.intel.memory"},
        "postmortems_step": {"fbi.intel.match_review", "fbi.intel.postmortem"},
        "run_nightly": {"fbi.intel.report"},
    },
}
"""The two cycles run both sides - the AI's passes before a kick-off (``ai/cycle.py``), the decisions and the scores (``intel/cycle.py``) - and
what is learned after one. They bring the post-mortem, the memory and the notes in only inside these functions, which is where the day is learned
and not where the packet, the review or the decision are made."""

PREMATCH_PACKAGES = set(MODEL_PACKAGES) | {
    "forecasting", "picks", "parlays", "market", "odds", "datasets", "validation", "research", "analyst", "notify",
    "competitions", "people", "catalog",
}
"""The packages that train a model, predict, price, decide, pick or describe a match that has not been played. A package is here whole."""

PREMATCH_FILES = {
    "intel/dossier.py", "intel/decision.py", "intel/score.py", "intel/stake.py", "intel/calibration.py", "intel/discovery.py",
    "intel/narrative.py", "intel/national.py", "intel/h2h.py", "intel/scenarios.py", "intel/tactics.py", "intel/factors.py", "intel/stats.py",
    "ai/packet.py", "ai/views.py", "ai/brief.py", "ai/review.py", "ai/context.py", "ai/evidence.py", "ai/analysis.py", "ai/absences.py",
    "ai/claims.py", "ai/prompts.py", "ai/gating.py", "ai/research.py", "ai/day.py", "ai/collectors.py",
    "familydecisions/decide.py",
}
"""The files of the two packages that mix both sides (``intel`` and ``ai`` also hold the post-mortems, the memory and the learning) which build or
judge what is said before a kick-off: the dossier, the decision layer and its steps, the AI's packet, its prompts, what it asks to research and
what reads it."""


@cache
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


def imports_in(node: ast.AST, package: list[str]) -> set[str]:
    """Every module a piece of code imports, as an absolute dotted name: the lazy imports inside a function count and the relative ones are resolved."""
    found: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.ImportFrom):
            module = inner.module or ""
            if inner.level:
                module = ".".join([*package[: len(package) - (inner.level - 1)], *([module] if module else [])])
            if module:
                found.add(module)
                found.update(f"{module}.{a.name}" for a in inner.names)
        elif isinstance(inner, ast.Import):
            found.update(a.name for a in inner.names)
    return found


@cache
def imports_of(path: Path) -> set[str]:
    return imports_in(ast.parse(path.read_text(encoding="utf-8")), package_of(path))


def takes(names: set[str], module: str) -> bool:
    return any(n == module or n.startswith(module + ".") for n in names)


def docstring_ids(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


@cache
def code_strings(path: Path) -> list[str]:
    """The string constants of a file that are not docstrings: where SQL lives, and where prose cannot reach."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = docstring_ids(tree)
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


WRITES = re.compile(r"(?<!DO )\b(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE|TRUNCATE(?:\s+TABLE)?)\s+([A-Za-z_][A-Za-z_0-9.]*)")


def writes_of(path: Path) -> set[str]:
    """The tables the SQL of a file writes to (``ON CONFLICT .. DO UPDATE`` writes to the table it inserts into, so it is not counted twice)."""
    return {m.group(1) for s in code_strings(path) for m in WRITES.finditer(" ".join(s.split()))}


def inside(file: str, module: str) -> bool:
    """Is ``file`` (a path under src/fbi) the module ``fbi.x.y`` or a file of the package of that name?"""
    stem = "/".join(module.split(".")[1:])
    return file == f"{stem}.py" or file.startswith(f"{stem}/")


def reach(path: Path, function: str) -> list[str]:
    """Every string a function of a module can put in a query: its own, those of the constants it uses (SQL kept apart) and, going on, those of the
    functions of the same module it calls. Docstrings are prose and are not counted."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = docstring_ids(tree)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    constants: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            constants.update({t.id: node.value for t in node.targets if isinstance(t, ast.Name)})
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            constants[node.target.id] = node.value
    found: list[str] = []
    seen: set[str] = set()

    def visit(code: ast.AST) -> None:
        for inner in ast.walk(code):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str) and id(inner) not in skip:
                found.append(inner.value)
            elif isinstance(inner, ast.Name) and inner.id not in seen and (inner.id in constants or inner.id in functions):
                seen.add(inner.id)
                visit(constants.get(inner.id) or functions[inner.id])

    seen.add(function)
    visit(functions[function])
    return found


def lessons_in(code: ast.AST, package: list[str]) -> set[str]:
    """The modules of ``IMPORTS`` that are the post-mortem, the memory and what learns from them (not the pages that show them) which a piece of code takes."""
    names = imports_in(code, package)
    return {m for m in IMPORTS if m.startswith(("fbi.intel.", "fbi.ai.")) and takes(names, m)}


def lessons_by_function(tree: ast.AST, package: list[str]) -> dict[str, set[str]]:
    """Where a file takes the lessons in: for each function that holds an import of one of them (``<module>`` for an import at the top), which."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom) and (took := lessons_in(node, package)):
            holder: ast.AST = node
            owner = "<module>"
            while holder in parents:
                holder = parents[holder]
                if isinstance(holder, ast.FunctionDef | ast.AsyncFunctionDef):
                    owner = holder.name
                    break
            found.setdefault(owner, set()).update(took)
    return found


# ── who names it, who imports it ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_only_the_listed_files_name_the_objects() -> None:
    naming = {rel(p) for p in python_files(SRC, SCRIPTS, APPS) if WORDS.search(p.read_text(encoding="utf-8"))}
    listed = set(NAMES_IT) | set(EXCEPTIONS)
    assert naming == listed, (
        f"files naming the post-mortem, the memory or the notes that are not listed: {sorted(naming - listed)}; "
        f"listed files that no longer do: {sorted(listed - naming)}")


@pytest.mark.parametrize("module", sorted(IMPORTS))
def test_only_the_listed_files_import_each_module(module: str) -> None:
    allowed = IMPORTS[module]
    importing = {rel(p) for p in python_files(SRC, SCRIPTS, APPS) if takes(imports_of(p), module) and not inside(rel(p), module)}
    assert importing == set(allowed), (
        f"{module}: imported by files that are not listed: {sorted(importing - set(allowed))}; "
        f"listed files that no longer import it: {sorted(set(allowed) - importing)}")


def test_the_listed_modules_and_files_exist() -> None:
    """A rename would otherwise leave the lists above guarding a name nothing has."""
    for module in IMPORTS:
        stem = SRC.joinpath(*module.split(".")[1:])
        assert stem.with_suffix(".py").exists() or (stem / "__init__.py").exists(), f"{module} is listed and does not exist"
    listed = set(NAMES_IT) | set(EXCEPTIONS) | set(WRITERS) | set(READ_ONLY) | {f for files in IMPORTS.values() for f in files}
    for name in listed:
        base = SCRIPTS / name.removeprefix("scripts/") if name.startswith("scripts/") else (
            APPS / name.removeprefix("apps/") if name.startswith("apps/") else SRC / name)
        assert base.is_file(), f"{name} is listed and does not exist"


def test_only_its_own_migrations_name_the_tables() -> None:
    """A view, a function or a foreign key over the tables is made by a migration: the one that makes it is the one that must be listed here, so
    that no pre-match reader reaches the post-mortem or the memory through an object that does not carry its name. 0072, 0073 and 0076 made the
    tables, 0079 only comments a column, 0091 made the one post-mortem and memory-v4 (their two views are the ones the readers use) and 0094 made
    what the families of counts learn, apart from all of them (it names the pipeline's tables to say why)."""
    naming = {p.name for p in MIGRATIONS.glob("*.py") if WORDS.search(p.read_text(encoding="utf-8"))}
    assert naming == {
        "0072_ai_decision_layer.py", "0073_ai_v2_day_passes_learning.py", "0076_predigol_intelligence.py", "0079_promoted_forecast_spec.py",
        "0091_single_postmortem_memory_v4.py", "0094_family_learning.py"}, (
        f"migrations naming the post-mortem, the memory or the notes: {sorted(naming)}. A migration that adds an object over them (a view, a "
        "function, a key) opens a second way in: decide here, with the reason, whether the pre-match side may reach it")


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
    assert "models" in PREMATCH_PACKAGES and "picks" in PREMATCH_PACKAGES and "intel/dossier.py" in PREMATCH_FILES
    assert {"ai/packet.py", "intel/decision.py", "picks/pipeline.py", "forecasting/match_forecast.py", "market/closing_value.py"} <= {
        rel(p) for p in prematch_files()}
    assert set(EXCEPTIONS) <= {rel(p) for p in prematch_files()}, "the exceptions are files of the pre-match side: that is why they are exceptions"
    assert len(prematch_files()) > 100, len(prematch_files())


def test_nothing_before_a_kickoff_names_or_imports_it() -> None:
    """The names, in words: whatever else changes, none of these appears in a file that builds or judges what is said before a match - but the
    two files of ``EXCEPTIONS``, held by the next test."""
    for path in prematch_files():
        name = rel(path)
        names = imports_of(path)
        for module in IMPORTS:
            assert not takes(names, module), f"{name} imports {module}: what a match turned out to be is not an input of what is said before it"
        if name in EXCEPTIONS:
            continue
        assert not WORDS.search(path.read_text(encoding="utf-8")), (
            f"{name} names the post-mortem, the memory or the notes: what was learned from a match is not an input of what is said before another")


def test_the_two_prematch_files_that_name_it_only_count_or_remember() -> None:
    """``picks/resettlement.py`` counts rows (``SELECT count(*)``) and ``market/closing_value.py`` has the name in a docstring: there is no query of
    theirs that returns what a post-mortem says."""
    label = re.compile(r"^[a-z_]+\.[a-z_]+$")  # "intel.postmortems" as the name a count is reported under: a word, not a query
    counted: dict[str, int] = {}
    for name in EXCEPTIONS:
        queries = [" ".join(s.split()) for s in code_strings(SRC / name) if WORDS.search(s) and not label.match(s.strip())]
        stray = [q[:90] for q in queries if not q.upper().startswith("SELECT COUNT(*)")]
        assert not stray, f"{name} does more than count the post-mortem, the memory or the notes: {stray}"
        counted[name] = len(queries)
    assert counted == {"picks/resettlement.py": 4, "market/closing_value.py": 0}, (
        f"{counted}: the re-settlement counts the four tables built on a result (the test must see those queries) and the other file has none")


def test_no_file_allowed_to_read_it_is_a_prematch_reader() -> None:
    """The lists above are how a reader is let in; this is what stops one being let in by editing them."""
    allowed = set(NAMES_IT) | {f for files in IMPORTS.values() for f in files} | set(WRITERS) | set(CYCLES)
    for name in sorted(allowed):
        top = name.split("/")[0]
        assert name not in PREMATCH_FILES and top not in PREMATCH_PACKAGES, (
            f"{name} may read the post-mortem or the memory and is a pre-match reader: move it out of the lists, not the file into them")
    for module in IMPORTS:
        top = module.split(".")[1]
        assert (top not in PREMATCH_PACKAGES) and ("/".join(module.split(".")[1:]) + ".py") not in PREMATCH_FILES, (
            f"{module} is the post-mortem, the memory or what reads them and is a pre-match module")


def test_the_cycles_bring_them_in_only_where_they_learn() -> None:
    """``ai/cycle.py`` makes the packet, the brief and the review and ``intel/cycle.py`` the decisions: neither imports what was learned outside
    the functions that learn, so that a pass that prepares a match cannot be handed the lessons of another."""
    for name, functions in CYCLES.items():
        path = SRC / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert set(functions) <= defined, f"{name}: functions {sorted(set(functions) - defined)} are listed and do not exist"
        found = lessons_by_function(tree, package_of(path))
        assert found == functions, (
            f"{name} takes the post-mortem, the memory or the notes in at {dict(sorted(found.items()))}; listed: {dict(sorted(functions.items()))}. "
            "The passes that prepare a match must not take them in: list a function only if it is where the day is learned")


# ── what writes it ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_each_builder_writes_its_own_tables_and_no_fact_of_a_match(name: str) -> None:
    """The facts of a match - fixtures, events, statistics, players, prices, picks, settlements - are only read: the post-mortem and the memory are
    built from them, never into them."""
    assert writes_of(SRC / name) == WRITERS[name], f"{name} writes {sorted(writes_of(SRC / name))}; it may write {sorted(WRITERS[name])}"


@pytest.mark.parametrize("name", READ_ONLY)
def test_the_pages_and_commands_that_look_write_nothing_themselves(name: str) -> None:
    path = SCRIPTS / name.removeprefix("scripts/") if name.startswith("scripts/") else SRC / name
    assert not writes_of(path), f"{name} writes to {sorted(writes_of(path))}: what a command builds, the builders write"


def test_the_post_mortem_and_the_memory_are_not_model_code() -> None:
    """The version of every model is the fingerprint of the model packages (``fbi.core.version``): a rule of the post-mortem or of the memory
    changes with every lesson and must not renew it."""
    assert {"intel", "ai", "knowledge", "api"}.isdisjoint(MODEL_PACKAGES)


# ── what a user can reach ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_card_a_user_is_shown_reaches_none_of_it() -> None:
    """``GET /matches/{id}/analysis`` is the one route of the AI pages a user may call, and it lives in the module that also serves the Admin
    Console's error dashboard and log of memory events. What it can put in a query is read here, through the constants and the functions it uses."""
    path = SRC / "api" / "services" / "ai_layer.py"
    mine = reach(path, "match_analysis")
    assert any("ai.match_analyses" in s for s in mine), "the walk must see the queries of the card, or it proves nothing"
    assert not [s for s in mine if WORDS.search(s)], "the card a user is shown reads the post-mortem, the memory or the notes"
    for admin in ("memory", "dashboard"):
        assert any(WORDS.search(s) for s in reach(path, admin)), f"the walk must see through the constants: {admin}() does read them"


def test_the_routes_that_read_it_are_the_admin_console_and_one_card() -> None:
    """Every route of the three routers that serve the post-mortem, the memory and the notes is the Admin Console's (``/api/v1/admin``, which a
    user is refused on every route: test_auth_rbac) except the card of a match, which the previous test holds."""
    from fbi.api.app import create_app

    tagged: dict[str, list[tuple[str, str]]] = {}
    for path, operations in create_app().openapi()["paths"].items():
        for method, operation in operations.items():
            for tag in operation.get("tags", []):
                tagged.setdefault(tag, []).append((method.upper(), path))
    for tag in ("admin: ai decision layer", "admin: predigol intelligence", "evolution loop"):
        assert tagged.get(tag), f"{tag}: no route found, the test would prove nothing"
        outside = [r for r in tagged[tag] if not r[1].startswith("/api/v1/admin/")]
        assert not outside, f"{tag}: routes outside the Admin Console: {outside}"
    assert tagged["predigol analysis"] == [("GET", "/api/v1/matches/{fixture_id}/analysis")], tagged["predigol analysis"]
