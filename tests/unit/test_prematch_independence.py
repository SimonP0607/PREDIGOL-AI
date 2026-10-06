"""No pre-match model, feature, pick, parlay, backtest, settlement, consensus or validation reads an in-play price.

This is the evidence behind revision 0068 (in-play odds kept as the current book only) and 0069 (the in-play history
dropped): if anything that decides or judges a pick could read the in-play tables, removing their history would
change it. The check is structural - it reads what each module CAN reach, its SQL string literals and its imports -
so it keeps holding when someone adds a query, not only for the code that exists today.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from types import ModuleType

import pytest

from fbi.truth.gate import MODEL_NEEDS, Need, dataset_role

INPLAY_RELATIONS = (
    "live_odds_current", "live_fixture_current", "live_odds_snapshots", "live_fixture_states",
    "live_market_movement", "live_odds_at_instant",
)
INPLAY_MODULES = ("fbi.odds.live_capture", "fbi.odds.live_repository", "fbi.odds.live_cadence",
                  "fbi.odds.live_archive", "fbi.providers.api_football.live")

PREMATCH_PACKAGES = (
    "fbi.features", "fbi.models", "fbi.picks", "fbi.parlays", "fbi.backtesting", "fbi.predictions",
    "fbi.research", "fbi.datasets", "fbi.market", "fbi.validation", "fbi.analyst", "fbi.notify",
)
PREMATCH_ODDS_MODULES = ("fbi.odds.capture", "fbi.odds.repository", "fbi.odds.schedule", "fbi.odds.final_prematch",
                         "fbi.odds.horizons", "fbi.odds.partitions")


def _modules() -> list[str]:
    names: list[str] = []
    for package in PREMATCH_PACKAGES:
        pkg = importlib.import_module(package)
        names.append(package)
        if hasattr(pkg, "__path__"):
            names += [m.name for m in pkgutil.walk_packages(pkg.__path__, prefix=f"{package}.")]
    for name in PREMATCH_ODDS_MODULES:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        names.append(name)
    return sorted(set(names))


MODULES = _modules()


def _tree(module: ModuleType) -> ast.Module | None:
    try:
        return ast.parse(inspect.getsource(module))
    except (OSError, TypeError):
        return None


def _code_strings(tree: ast.Module) -> list[str]:
    """String constants that are not docstrings: where SQL lives, and where prose cannot reach."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{a.name}" for a in node.names}
    return found


def test_the_scan_covers_the_code_that_decides_and_judges_picks() -> None:
    """A scan of nothing would pass: it must reach the models, the pick engine, the backtest and the settlement."""
    for must in ("fbi.picks.engine", "fbi.backtesting", "fbi.market.consensus", "fbi.validation.historical",
                 "fbi.odds.capture", "fbi.research.pick_audit"):
        assert any(m == must or m.startswith(must + ".") for m in MODULES), must
    assert len(MODULES) > 40, len(MODULES)


@pytest.mark.parametrize("name", MODULES)
def test_no_prematch_module_queries_an_inplay_table(name: str) -> None:
    tree = _tree(importlib.import_module(name))
    if tree is None:
        pytest.skip("no source")
    blob = " ".join(_code_strings(tree))
    named = [r for r in INPLAY_RELATIONS if r in blob]
    assert not named, f"{name} has SQL naming {named}"


@pytest.mark.parametrize("name", MODULES)
def test_no_prematch_module_imports_the_inplay_pipeline(name: str) -> None:
    tree = _tree(importlib.import_module(name))
    if tree is None:
        pytest.skip("no source")
    reached = {i for i in _imports(tree) if any(i == m or i.startswith(m + ".") for m in INPLAY_MODULES)}
    assert not reached, f"{name} imports {sorted(reached)}"


def test_no_model_needs_the_live_dataset() -> None:
    """The model data gate: every family's requirements, and 'live' is in none of them."""
    for model, needs in MODEL_NEEDS.items():
        assert "live" not in needs, model
    assert dataset_role("live") is Need.NOT_USED


def test_model_readiness_counts_only_prematch_prices() -> None:
    """MODEL_READY needs 60 % of a season's matches priced - by pre-match prices only."""
    from fbi.validation import historical

    priced = historical.FLAGS_SQL[historical.FLAGS_SQL.index("priced AS"):historical.FLAGS_SQL.index("rated AS")]
    assert "final_prematch_odds" in priced and "historical_odds" in priced and "odds_snapshots" in priced
    assert "source = 'prematch'" in priced
    assert not any(r in priced for r in INPLAY_RELATIONS)
