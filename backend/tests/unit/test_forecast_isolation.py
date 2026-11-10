"""A forecast is not a value and not a pick (plan F5): nothing that decides reads it.

PrediGol's forecast (``models.match_forecasts``) is what it expects of a match - a probability and the interval around it. The decision
layer (``intel.decisions``: edge, expected value, the ten filters) needs a price and the pick engine freezes what passed; neither may
take the forecast as an input, or the "probable" and the "well paid" would mix again in the numbers that decide, and a forecast that
moves for a reason of its own (a refit, a calibrator promoted, a price that went stale) would move a pick. The forecast is written by
one module, read by the page, by the AI's packet (a probability a review or a brief may cite - they can confirm, lower or reject, never
raise a probability or create a pick), by the AI's package (the forecasts of the counts, for the Statistics Agent in shadow: same
rule) and by the nightly proof that no packet read the future.

This file holds the door shut: the files that name the table, and the files that import the module that writes it, are listed here, with
why. A new reader fails the test until someone decides it may read."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
SCRIPTS = ROOT / "scripts"

TABLE = re.compile(r"\bmodels\.match_forecasts\b|\bFROM\s+match_forecasts\b|\bJOIN\s+match_forecasts\b")

NAMES_THE_TABLE = {
    "forecasting/match_forecast.py": "the writer: the only module that inserts, and the one that reads back its own rows",
    "api/services/forecast.py": "the page of a match: the product's forecast (`forecast-v1`) and the Admin Console's preview, which also reads `family-v1` for a section of its own",
    "ai/packet.py": "the packet's `forecast` block: context a review or a brief may cite, never an input of a computation",
    "ai/package.py": "the `families` block of the `mcp-v1` package (IA phase 1): the forecasts of the counts (`family-v1`), read as of the pass's moment, that the Statistics Agent may cite in shadow - context, never an input of a computation",
    "intel/leakage.py": "the nightly proof (`forecast_known`) that no packet cited a forecast from after its moment",
    "families/score.py": "the scoreboard of the family forecasts (`family-v1`) after the matches: read-only, a measure of the research, never an input",
    "familydecisions/decide.py": "the decision layer for a family (F11, shadow): reads the last `family-v1` forecast of each selection to see which the model finds valuable; "
                          "the rows it writes are research under their own decision version, and the pipeline's decision layer does not import it",
    "research/trace.py": "the trace of the model code's promotions (F12): counts the stored forecasts per model version to say which code production used; read-only, never an input",
    "api/services/transparency.py": "«Cómo le va a PrediGol» (plan UX, A12): the forecast's calibration after the matches - the last forecast before kick-off against the result; read-only, never an input",
    "scripts/transparency_check.py": "the contrast of that page (A12): the same calibration counted by an independent query at each deploy; read-only",
    "scripts/compare_probabilities.py": "PICKS F3 (BE-021): puts the page's forecast beside the board's and Intelligence's probability, selection by selection, over a READ ONLY connection; "
                                        "a measure of whether the two agree, printed for a person - never an input of a pick or a decision",
}

IMPORTS_THE_WRITER = {
    "picks/pipeline.py": "runs the writer as a step of its own, in a savepoint, after the forecasts of the models",
    "families/forecast.py": "the counts of F10 (halves, corners, cards): same table, version `family-v1` that the forecast of the page of the match never reads (only the Admin Console's preview does, apart)",
}
"""(``api/services/forecast.py``, ``ai/packet.py`` and ``ai/package.py`` do not import it: they duplicate its constants and a test holds
them equal, so that neither the API nor the AI layer depends on the worker's package.)"""


def python_files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else f"scripts/{path.name}"


def test_only_the_listed_files_name_the_table() -> None:
    naming = {rel(p) for p in python_files(SRC, SCRIPTS) if TABLE.search(p.read_text(encoding="utf-8"))}
    # the script prints what the writer wrote through the writer's own module and the table's name in its queries
    allowed = set(NAMES_THE_TABLE) | {"scripts/match_forecast.py"}
    assert naming == allowed, (
        f"files naming models.match_forecasts that are not listed: {sorted(naming - allowed)}; "
        f"listed files that no longer do: {sorted(allowed - naming)}")


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


def test_only_the_listed_files_import_the_module_that_writes_it() -> None:
    importing = {rel(p) for p in python_files(SRC, SCRIPTS) if "fbi.forecasting.match_forecast" in imports_of(p)}
    allowed = set(IMPORTS_THE_WRITER) | {"scripts/match_forecast.py"}
    assert importing == allowed, (
        f"files importing fbi.forecasting.match_forecast that are not listed: {sorted(importing - allowed)}; "
        f"listed files that no longer do: {sorted(allowed - importing)}")


def test_the_decision_layer_and_the_pick_engine_do_not_read_it() -> None:
    """The names, in words: whatever else changes, these never appear in a file that decides."""
    deciding = [p for p in python_files(SRC) if rel(p).split("/")[0] in {"intel", "picks", "domain"} and rel(p) != "intel/leakage.py"]
    assert deciding, "the decision layer and the pick engine are where the test looks"
    for path in deciding:
        text = path.read_text(encoding="utf-8")
        name = rel(path)
        if name == "picks/pipeline.py":
            # it runs the writer; it does not read the table nor take a forecast as an input to a pick
            assert not TABLE.search(text), name
            continue
        assert "match_forecast" not in text, f"{name} must not take PrediGol's forecast as an input: a forecast is not a value"


def test_the_probability_view_is_pure_and_reads_neither_the_forecast_nor_the_writer() -> None:
    """``market_view`` (the computation the forecast is written from, and decision-v2 measures against) takes rows and reads nothing; ``market_reader``
    reads the models' numbers and the market's consensus, never the stored forecast. Neither imports the writer (that would let a decision reach it)."""
    for name in ("market_view", "market_reader"):
        path = SRC / "forecasting" / f"{name}.py"
        text = path.read_text(encoding="utf-8")
        assert not TABLE.search(text), f"{name} must not name the forecast table"
        assert not [i for i in imports_of(path) if "match_forecast" in i], f"{name} must not import the writer"
    pure = imports_of(SRC / "forecasting" / "market_view.py")
    assert not [i for i in pure if i.startswith(("psycopg", "fbi.api", "fbi.picks", "fbi.db"))], "the view takes rows: it opens no connection"
    assert "execute" not in (SRC / "forecasting" / "market_view.py").read_text(encoding="utf-8")
