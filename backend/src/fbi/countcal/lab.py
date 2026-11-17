"""The LAB run of the protocol ``AD-B07`` from exported files (IA-095): the windows the protocol fixes, the statements that export the
data read-only, and the run over the files. No database here: the files are what ``statements`` exported.

    corners.csv / cards.csv / yellow.csv   ``fbi.families.history.export_statement`` (the door family-v1 reads through)
    referees.csv                           ``fbi.countcal.market.referee_statement``
    market.csv                             ``fbi.countcal.market.market_statement``
    nulls.csv                              ``fbi.countcal.market.nulls_statement``
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from fbi.countcal import market, walkforward
from fbi.families import history
from fbi.families.fit import OUTCOME_KNOWN_AFTER, Match
from fbi.research import protocol

PROTOCOL: Final = "AD-B07"
HISTORY_FROM: Final = datetime(2023, 11, 1, tzinfo=UTC)
WARMUP: Final = datetime(2025, 8, 18, tzinfo=UTC)
START: Final = datetime(2025, 11, 10, tzinfo=UTC)
END: Final = datetime(2026, 11, 10, tzinfo=UTC)
MARKET_FROM: Final = datetime(2026, 9, 1, tzinfo=UTC)
"""The price clock keeps the books' prices from 25-sep-2026: before it there is nothing to read."""
FILES: Final = ("corners.csv", "cards.csv", "yellow.csv", "referees.csv", "market.csv", "nulls.csv")

if START - timedelta(days=3 * walkforward.STEP_DAYS) != WARMUP:  # pragma: no cover - import-time guard of the protocol's windows
    raise RuntimeError("the warm-up is three blocks before the start (protocol AD-B07)")


def statements() -> dict[str, str]:
    """The read-only statements of the LAB, by the file each one fills."""
    cutoff = END + OUTCOME_KNOWN_AFTER
    return {
        "corners.csv": history.export_statement("corners_ft", since=HISTORY_FROM, cutoff=cutoff),
        "cards.csv": history.export_statement("cards_lines_ft", since=HISTORY_FROM, cutoff=cutoff, with_referee=True),
        "yellow.csv": history.export_statement("yellow_ft", since=START, cutoff=cutoff),
        "referees.csv": market.referee_statement(start=WARMUP, end=END),
        "market.csv": market.market_statement(start=max(START, MARKET_FROM), end=END),
        "nulls.csv": market.nulls_statement(start=max(START, MARKET_FROM), end=END),
    }


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_history(path: Path) -> dict[int, list[Match]]:
    out: dict[int, list[Match]] = {}
    for r in _rows(path):
        ref = r.get("referee_id") or ""
        out.setdefault(int(r["competition_id"]), []).append(Match(
            int(r["fixture_id"]), datetime.fromisoformat(r["kickoff_at"]), int(r["home_id"]), int(r["away_id"]), int(r["home"]),
            int(r["away"]), False, int(ref) if ref else None))
    return out


def read_market(path: Path) -> list[walkforward.MarketPrice]:
    return [walkforward.MarketPrice(int(r["fixture_id"]), r["market_key"], float(r["line"]), float(r["p_over"]), int(r["books"]))
            for r in _rows(path)]


def read_referees(path: Path) -> dict[int, int]:
    return {int(r["fixture_id"]): int(r["referee_id"]) for r in _rows(path) if r.get("referee_id")}


def read_yellow(path: Path) -> dict[int, tuple[int, int]]:
    return {int(r["fixture_id"]): (int(r["home"]), int(r["away"])) for r in _rows(path)}


def _markets_summary(prices: list[walkforward.MarketPrice]) -> dict[str, Any]:
    by_key: dict[str, dict[str, Any]] = {}
    for p in prices:
        e = by_key.setdefault(p.market_key, {"rows": 0, "matches": set(), "matches_3plus": set()})
        e["rows"] += 1
        e["matches"].add(p.fixture_id)
        if p.books >= 3:
            e["matches_3plus"].add(p.fixture_id)
    return {k: {"rows": v["rows"], "matches": len(v["matches"]), "matches_3plus_books": len(v["matches_3plus"])}
            for k, v in sorted(by_key.items())}


def run(directory: Path, *, measured_at: datetime) -> dict[str, Any]:
    """The whole LAB over the exported files: both measures, every family, the verdicts, stamped with the protocol."""
    spec = protocol.require(PROTOCOL)
    prices = read_market(directory / "market.csv")
    referees = read_referees(directory / "referees.csv")
    yellow = read_yellow(directory / "yellow.csv")
    nulls: Mapping[str, Any] = {r["family"]: {"priced_finished": int(r["priced_finished"]), "without_count": int(r["without_count"])}
                                for r in _rows(directory / "nulls.csv")}
    corners = read_history(directory / "corners.csv")
    cards = read_history(directory / "cards.csv")
    out: dict[str, Any] = {
        "stamp": protocol.stamp(PROTOCOL), "seed": spec.seed, "measured_at": measured_at.isoformat(),
        "windows": {"history_from": HISTORY_FROM.isoformat(), "warmup": WARMUP.isoformat(), "start": START.isoformat(),
                    "end": END.isoformat()},
        "inputs": {"corners_matches": sum(len(v) for v in corners.values()), "cards_matches": sum(len(v) for v in cards.values()),
                   "competitions": {"corners": len(corners), "cards": len(cards)},
                   "referees_known_before_kickoff": len(referees), "market": _markets_summary(prices), "without_count": dict(nulls)},
    }
    out["corners_ft"] = walkforward.run(corners, measure="corners_ft", warmup=WARMUP, start=START, end=END, seed=spec.seed,
                                        market=prices)
    out["cards_lines_ft"] = walkforward.run(cards, measure="cards_lines_ft", warmup=WARMUP, start=START, end=END, seed=spec.seed,
                                            referee_known=referees, market=prices, yellow=yellow)
    out["verdicts"] = {fam: res["verdict"] for m in ("corners_ft", "cards_lines_ft") for fam, res in out[m]["families"].items()}
    return out
