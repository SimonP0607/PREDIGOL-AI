"""The two pipelines cannot be crossed, and the proof is structural.

These assert what each side is even ABLE to reach, not what it happens to do. A
behavioural test would keep passing until somebody added one import.

The SQL checks read the modules' string literals through the AST rather than
grepping their text: these modules explain at length WHY they never touch
market.odds_snapshots, and a text search cannot tell an explanation from a query.
"""

from __future__ import annotations

import ast
import inspect
import re
from types import ModuleType

import pytest

from fbi.odds import capture as prematch_capture
from fbi.odds import live_capture, live_repository
from fbi.odds.schedule import CaptureTask
from fbi.providers.api_football import live as live_normalize
from fbi.providers.api_football import provider as api_provider
from fbi.providers.base import FootballDataProvider

PREMATCH_TABLES = (
    "market.odds_snapshots",
    "market.near_close_snapshots",
    "market.market_consensus",
)


def sql_literals(module: ModuleType) -> list[str]:
    """Every string constant in the module that is not a docstring.

    SQL lives in string literals, so this is where a query to a forbidden table
    would have to appear - and prose cannot reach it.
    """
    tree = ast.parse(inspect.getsource(module))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def executable_source(obj: object) -> str:
    """Source with docstrings and comments stripped, so only code is searched."""
    src = inspect.getsource(obj)  # type: ignore[arg-type]
    src = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
    src = re.sub(r"'''.*?'''", "", src, flags=re.DOTALL)
    return "\n".join(
        line.split("#", 1)[0] if "#" in line and not line.strip().startswith("#") else
        ("" if line.strip().startswith("#") else line)
        for line in src.splitlines()
    )


# --- what each side can reach ----------------------------------------------


def test_the_prematch_provider_protocol_has_no_inplay_method() -> None:
    """So the backfill, the migration and the pre-match capture - everything that
    takes a FootballDataProvider - has no way to reach an in-play price at all."""
    assert not hasattr(FootballDataProvider, "fetch_live_odds_all")
    assert not hasattr(FootballDataProvider, "fetch_live_odds")


def test_the_live_source_protocol_offers_only_the_inplay_call() -> None:
    methods = {
        name
        for name, _ in inspect.getmembers(live_capture.LiveOddsSource, inspect.isfunction)
        if not name.startswith("_")
    }
    assert methods == {"fetch_live_odds_all"}


@pytest.mark.parametrize("module", [live_capture, live_repository])
def test_the_live_pipeline_queries_no_prematch_table(module: ModuleType) -> None:
    """A live price in market.odds_snapshots would make every backtest a lie."""
    blob = " ".join(sql_literals(module))
    for table in PREMATCH_TABLES:
        assert table not in blob, f"{module.__name__} has SQL naming {table}"


def test_the_live_pipeline_writes_only_its_own_two_tables() -> None:
    """Two tables, and no third. The catalogue is not written from here either:
    catalog.provider_markets owns market.provider_markets, so an observation
    cannot acquire a second writer with a second policy."""
    blob = " ".join(sql_literals(live_repository))
    inserted = set(re.findall(r"INSERT INTO\s+([\w.]+)", blob))
    assert inserted == {
        "market.live_fixture_states",
        "market.live_odds_snapshots",
    }


def test_the_live_service_holds_no_prematch_repository() -> None:
    code = executable_source(live_capture.LiveCaptureService)
    assert "OddsRepository(" not in code.replace("LiveOddsRepository(", "")
    assert "recompute_from_snapshots" not in code
    assert "upsert_near_close" not in code


# --- the near-close path is gone, not merely unused ------------------------


def test_the_prematch_capture_cannot_fetch_an_inplay_price() -> None:
    """It used to serve a near_close task from /odds/live, which was then measured
    to return only matches already in play - so those rows would have been
    in-play prices filed as pre-match."""
    code = executable_source(prematch_capture.OddsCaptureService._capture_one)
    assert "fetch_live_odds" not in code
    assert "upsert_near_close" not in code


def test_a_near_close_task_raises_rather_than_fetching() -> None:
    import asyncio
    from datetime import UTC, datetime

    task = CaptureTask(
        provider_fixture_id=1,
        kickoff_at=datetime(2026, 10, 1, tzinfo=UTC),
        kind="near_close",
        window_minutes=12,
        minutes_to_ko=12,
    )
    service = object.__new__(prematch_capture.OddsCaptureService)
    report = prematch_capture.CaptureReport(run_id=1)
    with pytest.raises(ValueError, match="not served by the pre-match capture"):
        asyncio.run(service._capture_one(task, report))


# --- the DTOs stay distinct ------------------------------------------------


def test_the_provider_returns_different_types_from_the_two_calls() -> None:
    """Sharing the HTTP client, the quota ledger and the raw store is fine - that
    is infrastructure. What must not be shared is the DTO, so a caller cannot
    pass one series' prices where the other's are expected."""
    p = api_provider.ApiFootballProvider
    assert hasattr(p, "fetch_prematch_odds")
    assert hasattr(p, "fetch_live_odds_all")
    assert not hasattr(p, "fetch_live_odds")

    live_types = str(inspect.signature(p.fetch_live_odds_all).return_annotation)
    prematch_types = str(inspect.signature(p.fetch_prematch_odds).return_annotation)
    # \b stops LiveOddsQuote from matching as OddsQuote.
    assert not re.search(r"\bOddsQuote\b", live_types), live_types
    assert re.search(r"\bOddsQuote\b", prematch_types)
    assert "LiveOddsQuote" in live_types


def test_the_live_normaliser_does_not_reuse_the_prematch_selection_parser() -> None:
    """Reusing it would negate every away Asian Handicap line: pre-match repeats
    the home team's handicap on both rows, live signs each row itself. Measured
    - read the pre-match way, real live pairs devig below 1.0."""
    code = executable_source(live_normalize)
    assert not re.search(r"\bnormalize\._selection\b", code)
    assert "normalize import" not in code or "_selection," not in code
    assert "LIVE_SELECTION_ALIASES" in code


def test_the_live_bet_map_is_the_inplay_one() -> None:
    code = executable_source(live_normalize.live_market_of)
    assert "INPLAY_BETS" in code
    assert "PREMATCH_BETS" not in code
