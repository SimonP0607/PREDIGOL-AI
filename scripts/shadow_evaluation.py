"""How the shadow picks did, judged the way a pick must be judged: not by ROI alone.

    python -m scripts.shadow_evaluation            # 0 provider requests; writes data/evaluation/<stamp>/

For the settled shadow picks (never shown to a user): ROI with a 95% interval from a bootstrap that resamples
FIXTURES, not picks (several lines of one match win or lose together, so 1,500 picks are far fewer independent
bets); the same split by market, odds band and selection side; calibration (the model's probability, the market's
de-vigged probability and what happened, per market and side); and closing-line value: the price taken against the
same bookmaker's last pre-match price and against Pinnacle's, both read after the match
(market.final_prematch_odds). A model that beats the market should take prices that the close moves against
(positive CLV) - consistently, not in one lucky week.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings
from fbi.core.version import code_version

OUT_ROOT = Path("data/evaluation")
BOOTSTRAP = 2000
SEED = 20261005

PICKS_SQL = """
SELECT p.id, p.fixture_id, p.market_key, p.selection, p.line, p.market_odds, p.p_calibrated, p.p_market_fair,
       p.p_push, p.model_version_id, p.bookmaker_id, b.name AS bookmaker, p.created_at, f.kickoff_at,
       c.name AS competition, pr.result_status, pr.profit_units, p.stake_units,
       (SELECT o.odds_decimal FROM market.final_prematch_odds o
         WHERE o.fixture_id = p.fixture_id AND o.bookmaker_id = p.bookmaker_id AND o.market_key = p.market_key
           AND o.selection = p.selection AND o.line = p.line) AS close_same_book,
       (SELECT o.odds_decimal FROM market.final_prematch_odds o JOIN market.bookmakers pb ON pb.id = o.bookmaker_id
         WHERE pb.name = 'Pinnacle' AND o.fixture_id = p.fixture_id AND o.market_key = p.market_key
           AND o.selection = p.selection AND o.line = p.line) AS close_pinnacle
  FROM picks.picks p
  JOIN picks.pick_results pr ON pr.pick_id = p.id
  JOIN core.fixtures f ON f.id = p.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN market.bookmakers b ON b.id = p.bookmaker_id
 WHERE p.status = 'settled' AND pr.result_status <> 'pending'
"""


PINNACLE_CLOSE_SQL = """
SELECT o.fixture_id, o.market_key, o.selection, o.line, o.odds_decimal
  FROM market.final_prematch_odds o JOIN market.bookmakers b ON b.id = o.bookmaker_id
 WHERE b.name = 'Pinnacle' AND o.fixture_id = ANY(%s)
"""

EXCLUSIVE = {"1X2": ("Home", "Draw", "Away"), "OU": ("Over", "Under"), "BTTS": ("Yes", "No")}
MAX_TWO_WAY_BOOK = 1.25
"""As in fbi.market.consensus: a two-way book above this margin is two prices that merely share a number."""

Book = dict[tuple[str, str, Decimal], float]


def fair_close(book: Book, market: str, selection: str, line: Decimal) -> float | None:
    """Pinnacle's de-vigged probability for one pick, from its final pre-match book (proportional de-vig).

    1X2, Over/Under and BTTS: the selections at the same line. Asian Handicap: (Home, h) pairs with (Away, -h), as
    the consensus pairs them, and only a believable two-way book counts. Double Chance and an incomplete book:
    None - not guessed."""
    if market in EXCLUSIVE:
        sides = EXCLUSIVE[market]
        odds = [book.get((market, s, line)) for s in sides]
        if selection not in sides or any(o is None or o <= 1 for o in odds):
            return None
        inv = [1 / o for o in odds if o is not None]
        return inv[sides.index(selection)] / sum(inv)
    if market == "AH" and selection in ("Home", "Away"):
        mine = book.get((market, selection, line))
        if mine is None or mine <= 1:
            return None
        other = "Away" if selection == "Home" else "Home"
        books = [1 / mine + 1 / c for c in (book.get((market, other, -line)), book.get((market, other, line)))
                 if c is not None and c > 1]
        believable = [b for b in books if 1 < b <= MAX_TWO_WAY_BOOK]
        return (1 / mine) / min(believable) if believable else None
    return None


def clustered_mean(values: list[tuple[int, float]], rng: random.Random) -> dict[str, Any]:
    """Mean of per-pick values and a 95% interval from resampling fixtures (picks on one match move together)."""
    if not values:
        return {"n": 0, "fixtures": 0, "mean": None, "ci95": None}
    by_fixture: dict[int, list[float]] = defaultdict(list)
    for fixture, v in values:
        by_fixture[fixture].append(v)
    groups = list(by_fixture.values())
    samples = []
    for _ in range(BOOTSTRAP):
        draw = [groups[rng.randrange(len(groups))] for _ in groups]
        n = sum(len(g) for g in draw)
        samples.append(sum(sum(g) for g in draw) / n)
    samples.sort()
    return {"n": len(values), "fixtures": len(groups), "mean": round(statistics.mean(v for _, v in values), 4),
            "ci95": [round(samples[int(0.025 * BOOTSTRAP)], 4), round(samples[int(0.975 * BOOTSTRAP) - 1], 4)]}


def ev_at_pinnacle_close(rows: list[dict[str, Any]], books: dict[int, Book], rng: random.Random) -> dict[str, Any]:
    """EV of the price taken against Pinnacle's de-vigged final pre-match price: odds x p_fair - 1.

    The raw ratio to Pinnacle's price (``clv_pinnacle``) compares the best of several books with one book that keeps
    a margin, so it flatters every pick; this is the figure a sharp close says the pick was worth."""
    values = []
    for r in rows:
        p = fair_close(books.get(r["fixture_id"], {}), r["market_key"], r["selection"],
                       Decimal(str(r.get("line") or 0)))
        if p is not None:
            values.append((r["fixture_id"], float(r["market_odds"]) * p - 1))
    return clustered_mean(values, rng)


def roi_with_interval(rows: list[dict[str, Any]], rng: random.Random) -> dict[str, Any]:
    """ROI = profit / stake, and a 95% interval from resampling fixtures with replacement."""
    if not rows:
        return {"picks": 0, "fixtures": 0, "roi": None, "ci95": None}
    by_fixture: dict[int, tuple[float, float]] = {}
    for r in rows:
        profit, stake = by_fixture.get(r["fixture_id"], (0.0, 0.0))
        by_fixture[r["fixture_id"]] = (profit + float(r["profit_units"]), stake + float(r["stake_units"]))
    groups = list(by_fixture.values())
    total_profit = sum(p for p, _ in groups)
    total_stake = sum(s for _, s in groups)
    samples = []
    for _ in range(BOOTSTRAP):
        draw = [groups[rng.randrange(len(groups))] for _ in groups]
        stake = sum(s for _, s in draw)
        samples.append(sum(p for p, _ in draw) / stake if stake else 0.0)
    samples.sort()
    return {"picks": len(rows), "fixtures": len(groups), "roi": round(total_profit / total_stake, 4),
            "ci95": [round(samples[int(0.025 * BOOTSTRAP)], 4), round(samples[int(0.975 * BOOTSTRAP) - 1], 4)]}


def clv(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Closing-line value: taken / close - 1, over the picks with a close for that reference."""
    values = [float(r["market_odds"]) / float(r[key]) - 1 for r in rows if r.get(key)]
    if not values:
        return {"n": 0, "mean": None, "median": None, "positive_share": None}
    return {"n": len(values), "mean": round(statistics.mean(values), 4), "median": round(statistics.median(values), 4),
            "positive_share": round(sum(1 for v in values if v > 0) / len(values), 3)}


def calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Model probability, market probability and observed rate of winning (pushes and halves excluded)."""
    decided = [r for r in rows if r["result_status"] in ("win", "loss")]
    if not decided:
        return {"n": 0}
    won = sum(1 for r in decided if r["result_status"] == "win")
    return {"n": len(decided), "model_p": round(statistics.mean(float(r["p_calibrated"]) for r in decided), 4),
            "market_p": round(statistics.mean(float(r["p_market_fair"]) for r in decided), 4),
            "observed": round(won / len(decided), 4)}


def edge_reliability(rows: list[dict[str, Any]], rng: random.Random) -> dict[str, Any]:
    """lambda in y - q = lambda (p - q): how much of the model's disagreement with the market came true.

    1 means the model's edge was real, 0 that the market was right all along, below 0 that the model pointed the
    wrong way. Decided bets only (win / loss); interval from resampling fixtures. Selecting the bets with the
    largest p - q selects the model's errors too (the optimizer's curse), which is what this measures."""
    decided = [(r["fixture_id"], 1.0 if r["result_status"] == "win" else 0.0, float(r["p_calibrated"]),
                float(r["p_market_fair"])) for r in rows if r["result_status"] in ("win", "loss")]
    if not decided:
        return {"n": 0, "lambda": None, "ci95": None}

    def fit(sample: list[tuple[int, float, float, float]]) -> float:
        den = sum((p - q) ** 2 for _, _, p, q in sample)
        return sum((y - q) * (p - q) for _, y, p, q in sample) / den if den else 0.0

    by_fixture: dict[int, list[tuple[int, float, float, float]]] = defaultdict(list)
    for d in decided:
        by_fixture[d[0]].append(d)
    groups = list(by_fixture.values())
    samples = sorted(fit([x for _ in groups for x in groups[rng.randrange(len(groups))]]) for _ in range(BOOTSTRAP))
    return {"n": len(decided), "fixtures": len(groups), "lambda": round(fit(decided), 3),
            "ci95": [round(samples[int(0.025 * BOOTSTRAP)], 3), round(samples[int(0.975 * BOOTSTRAP) - 1], 3)]}


def band(odds: float) -> str:
    for hi, label in ((1.6, "<1.60"), (2.0, "1.60-1.99"), (2.5, "2.00-2.49"), (3.5, "2.50-3.49"), (6.0, "3.50-5.99")):
        if odds < hi:
            return label
    return ">=6.00"


def evaluate(rows: list[dict[str, Any]], books: dict[int, Book] | None = None) -> dict[str, Any]:
    rng = random.Random(SEED)
    books = books or {}
    out: dict[str, Any] = {"overall": {**roi_with_interval(rows, rng), "clv_same_book": clv(rows, "close_same_book"),
                                       "clv_pinnacle": clv(rows, "close_pinnacle"),
                                       "ev_at_pinnacle_close": ev_at_pinnacle_close(rows, books, rng),
                                       "edge_reliability": edge_reliability(rows, rng)}}
    for name, key in (("by_market", lambda r: r["market_key"]), ("by_odds_band", lambda r: band(float(r["market_odds"]))),
                      ("by_market_side", lambda r: f"{r['market_key']} {r['selection']}"),
                      ("by_bookmaker", lambda r: r["bookmaker"])):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[key(r)].append(r)
        out[name] = {g: {**roi_with_interval(v, rng), "clv_same_book": clv(v, "close_same_book"),
                         "ev_at_pinnacle_close": ev_at_pinnacle_close(v, books, rng),
                         "calibration": calibration(v), "edge_reliability": edge_reliability(v, rng)}
                     for g, v in sorted(groups.items())}
    days = sorted({r["kickoff_at"].date().isoformat() for r in rows})
    out["period"] = {"first_kickoff": days[0] if days else None, "last_kickoff": days[-1] if days else None,
                     "days": len(days)}
    return out


def main() -> int:
    at = datetime.now(UTC)
    with psycopg.connect(settings.database.psycopg_url) as conn, conn.cursor(row_factory=dict_row) as cur:
        conn.read_only = True
        cur.execute(PICKS_SQL)
        rows = cur.fetchall()
        cur.execute(PINNACLE_CLOSE_SQL, (sorted({r["fixture_id"] for r in rows}),))
        books: dict[int, Book] = defaultdict(dict)
        for b in cur.fetchall():
            books[b["fixture_id"]][(b["market_key"], b["selection"], Decimal(str(b["line"])))] = float(b["odds_decimal"])
    report = {"at": at.isoformat(), "code_version": code_version(), "bootstrap": BOOTSTRAP, "seed": SEED,
              "note": "shadow picks only; none was shown to a user", **evaluate(rows, books)}
    folder = OUT_ROOT / at.strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shadow_evaluation.json").write_text(json.dumps(report, indent=2, default=str))
    o = report["overall"]
    print(folder / "shadow_evaluation.json")
    print(f"picks {o['picks']} fixtures {o['fixtures']} roi {o['roi']} ci95 {o['ci95']} "
          f"clv_same_book {o['clv_same_book']} clv_pinnacle {o['clv_pinnacle']} "
          f"ev_at_pinnacle_close {o['ev_at_pinnacle_close']} "
          f"edge_reliability {o['edge_reliability']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
