"""A match of a competition PrediGol does not follow is not a match PrediGol models (plan F4): nothing that trains, predicts or decides reads it.

``core.calendar_matches`` holds what the provider lists for a team beyond the competitions PrediGol follows - a cup, a continental tie, a
friendly - so that rest and congestion can be told whole. It is kept in a table of its own, and not as a mark on ``core.fixtures``, precisely so
that it cannot reach the Elo, the features, the backtests, the picks or the settlement by being left out of a query nobody remembered to
change: those read ``core.fixtures`` and never see it. What reads the calendar, and what writes it, is listed here, with why. A new reader fails
the test until someone decides it may read."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
SCRIPTS = ROOT / "scripts"

TABLES = re.compile(r"\bcore\.(?:calendar_matches|calendar_fetches|calendar_matches_latest|team_calendar)\b")

NAMES_THE_TABLES = {
    "ingestion/team_calendar.py": "the writer: the only module that inserts (the feed's normalizer)",
    "competitions/team_calendar.py": "the reader: the calendar of a team as of a moment, for whoever may know it",
    "intel/leakage.py": "the nightly proof: the rule calendar_known holds a stored packet to these tables (it reads, it never writes)",
}

IMPORTS_THE_READER = {
    "competitions/team_calendar.py": "itself",
    "ai/packet.py": "the packet: the schedule block of what the AI may know about a match (rest, congestion, next matches) as of its moment",
    "api/services/match_calendar.py": "the page of a match: the calendar of each team, for users once the owner decides and for the preview",
    "research/rest_features.py": "the experiments (F4.4): turns the calendar of a team into the numbers of rest and congestion; the experiment "
                                 "itself (research/rest_ab.py) takes the numbers and never sees the calendar",
    "scripts/calendar_features.py": "the experiments' command (F4.4): loads the calendars, reports how much of them there is, exports and "
                                    "runs the pre-registered test; it reads and trains nothing production reads",
    "intel/factors.py": "the registry of context factors (F6): the VERSION of the reader, which a validation of rest and congestion is "
                        "about, so that changing the reader sends the factor back to DESCRIPTIVE; it reads that constant and nothing else",
}
"""The modules that import ``fbi.competitions.team_calendar``. They are added here as the packet, the page and the experiments take the
calendar in (each with its reason); a file that decides - a model, a pick, a settlement - never is."""

DECIDING = {"models", "predictions", "picks", "domain", "backtesting", "intel", "parlays", "market", "odds", "datasets"}
"""The packages that train a model, predict, decide or settle. ``intel`` is allowed two files: the nightly proof that no packet read the
future, and the registry of context factors (it names the reader's version, to say which code a validation is about, and reads nothing)."""
NOT_DECIDING = {"intel/leakage.py", "intel/factors.py"}


def python_files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else f"scripts/{path.name}"


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_only_the_listed_files_name_the_tables() -> None:
    naming = {rel(p) for p in python_files(SRC, SCRIPTS) if TABLES.search(p.read_text(encoding="utf-8"))}
    allowed = set(NAMES_THE_TABLES)
    assert naming == allowed, (
        f"files naming the calendar's tables that are not listed: {sorted(naming - allowed)}; "
        f"listed files that no longer do: {sorted(allowed - naming)}")


def test_only_the_listed_files_import_the_reader() -> None:
    importing = {rel(p) for p in python_files(SRC, SCRIPTS) if "fbi.competitions.team_calendar" in imports_of(p)}
    allowed = set(IMPORTS_THE_READER) - {"competitions/team_calendar.py"}
    assert importing == allowed, (
        f"files importing fbi.competitions.team_calendar that are not listed: {sorted(importing - allowed)}; "
        f"listed files that no longer do: {sorted(allowed - importing)}")


def test_only_the_experiments_command_imports_the_rest_features() -> None:
    """The rest and congestion numbers are for experiments: no model, pick, page or packet takes them as an input (the packet and the page
    read the calendar itself, as it was, to say it - not to compute with it)."""
    importing = {rel(p) for p in python_files(SRC, SCRIPTS) if any(name.startswith("fbi.research.rest_features") for name in imports_of(p))}
    assert importing == {"scripts/calendar_features.py"}, sorted(importing)


def test_only_the_feed_imports_the_writer() -> None:
    importing = {rel(p) for p in python_files(SRC, SCRIPTS) if "fbi.ingestion.team_calendar" in imports_of(p)}
    assert importing == {"ingestion/reference.py"}, "the feed registry runs the writer; nothing else may"


def test_nothing_that_trains_predicts_decides_or_settles_names_or_imports_the_calendar() -> None:
    deciding = [p for p in python_files(SRC) if rel(p).split("/")[0] in DECIDING and rel(p) not in NOT_DECIDING]
    assert deciding, "the packages that decide are where the test looks"
    for path in deciding:
        text = path.read_text(encoding="utf-8")
        name = rel(path)
        assert not TABLES.search(text), f"{name} reads the calendar of competitions PrediGol does not follow"
        assert "team_calendar" not in text, f"{name} must not take the team calendar as an input: it is context, not a model feature"
        assert "calendar_matches" not in text, name


def test_the_feature_engine_the_elo_and_the_backtests_do_not_see_it_either() -> None:
    """The features of a model are built from ``core.fixtures``: the engine that builds them, the Elo and the walk-forward evaluation."""
    for relative in ("features/engine.py", "features/elo.py"):
        path = SRC / relative
        if path.exists():
            assert "team_calendar" not in path.read_text(encoding="utf-8"), relative
    assert (SRC / "features" / "engine.py").exists()
