"""ANÁLISIS PREDIGOL: at most three selections per match, each with the model, the market, the edge and the
review's verdict - stored once per input, read by the product, never computed on a user's request.

How the three are chosen (rule ``match-analysis-v1``):

1. Selections that pass the value gate at the current price (the same gate the picks of the day use,
   ``fbi.picks.daily.passing``), best pessimistic growth first;
2. then the model's view of the main markets (1X2, Over/Under 2.5, BTTS) against the de-vigged market,
   biggest edge first - shown so the analysis can say why a market is NOT recommended;
3. at most one selection per market, at most three in all.

Each card's verdict:

    recommended      passes the value gate AND the combined review APPROVES it
    caution          passes the gate, the review DOWNGRADES it
    not_recommended  the review REJECTS it, or there is no value at the current price
    no_market        no bookmaker of ours prices it: the model's probability, fair odds and the MINIMUM
                     odds at which it would be worth it - "market not observed, value cannot be confirmed"

Who sees what is decided when it is read (``fbi.api.services.analysis``): a user sees a card's verdict only
when its pick is QUALIFIED (its model beat the market in its own backtest) - shadow numbers stay with the
owner's evaluation mode - and the model's view of unpriced markets, labelled evaluation, as the match page
already shows it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.packet import CORE_KEYS, Packet, canonical, content_hash
from fbi.ai.review import MIN_EV, Reviewed

RULE_VERSION = "match-analysis-v1"
MAX_CARDS = 3
MAIN = ("1X2", "OU", "BTTS")
PREFERRED_MODEL = "dixon_coles"


def _q(x: float | Decimal | None, places: str = "0.01") -> str | None:
    if x is None:
        return None
    return str(Decimal(str(x)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class ValueOption:
    """A selection that passed the value gate now (from ``fbi.picks.daily.passing``)."""

    market_key: str
    selection: str
    line: Decimal
    odds: Decimal
    bookmaker: str | None
    p_model: Decimal
    p_low: Decimal
    p_market: Decimal
    ev: Decimal
    elg: float
    model: str | None
    pick_id: int
    qualified: bool


def _risks(review: dict[str, Any] | None, n: int = 2) -> list[dict[str, Any]]:
    if not review:
        return []
    out = []
    for group in ("negative_evidence", "contradictions", "uncertainties"):
        for c in review.get(group, []):
            out.append({k: c.get(k) for k in ("text", "type", "code", "params", "refs")})
    return out[:n]


def _positives(review: dict[str, Any] | None, n: int = 2) -> list[dict[str, Any]]:
    if not review:
        return []
    return [{k: c.get(k) for k in ("text", "type", "code", "params", "refs")}
            for c in review.get("positive_evidence", [])][:n]


def _model_view(packet: Packet, key: tuple[str, str, Decimal]) -> dict[str, Any] | None:
    models = packet.content.get("models") or {}
    for name in (PREFERRED_MODEL, *sorted(models)):
        for s in (models.get(name) or {}).get("selections", []):
            if (s["market"], s["selection"], Decimal(s["line"])) == key and s.get("p"):
                return dict(s) | {"model": name}
    return None


def build_cards(packet: Packet, options: list[ValueOption],
                reviews: Mapping[tuple[str, str, Decimal], Reviewed | dict[str, Any]]) -> list[dict[str, Any]]:
    """The cards of one match. ``reviews`` maps (market, selection, line) to the combined review (a stored row's
    output or a fresh ``Reviewed``)."""
    def review_of(key: tuple[str, str, Decimal]) -> tuple[str | None, dict[str, Any] | None, int | None]:
        r = reviews.get(key)
        if r is None:
            return None, None, None
        if isinstance(r, Reviewed):
            return r.decision, r.combined_output, r.combined_id
        return str(r["decision"]), dict(r.get("output") or {}), int(r["id"])

    cards: list[dict[str, Any]] = []
    used_markets: set[str] = set()
    for o in sorted(options, key=lambda x: (-x.elg, -float(x.ev))):
        if o.market_key in used_markets or len(cards) >= MAX_CARDS:
            continue
        key = (o.market_key, o.selection, o.line)
        decision, output, review_id = review_of(key)
        verdict = {"APPROVE": "recommended", "DOWNGRADE": "caution", "REJECT": "not_recommended"}.get(decision or "",
                                                                                                      "recommended")
        if decision in (None, "ABSTAIN"):
            verdict = "recommended"  # no review: the value gate alone (the review is shown as missing)
        cards.append({
            "market": o.market_key, "selection": o.selection, "line": str(o.line), "kind": "value",
            "odds": _q(o.odds, "0.001"), "bookmaker": o.bookmaker, "p_model": _q(o.p_model, "0.0001"),
            "p_low": _q(o.p_low, "0.0001"), "p_market": _q(o.p_market, "0.0001"),
            "fair_odds": _q(1 / o.p_model) if o.p_model > 0 else None,
            "minimum_odds": _q((1 + MIN_EV) / o.p_low) if o.p_low > 0 else None,
            "edge": _q(o.p_model - o.p_market, "0.0001"), "ev": _q(o.ev, "0.0001"), "model": o.model,
            "pick_id": o.pick_id, "qualified": o.qualified, "verdict": verdict,
            "verdict_reason": "context_negative" if decision == "REJECT" else
                              "context_caution" if decision == "DOWNGRADE" else "value",
            "ai": None if decision is None else {"decision": decision, "review_id": review_id,
                                                 "confidence": (output or {}).get("confidence"),
                                                 "reason": (output or {}).get("reason"),
                                                 "positives": _positives(output), "risks": _risks(output),
                                                 "engines": [e.get("engine") for e in (output or {}).get("engines", [])]},
        })
        used_markets.add(o.market_key)
    market = {(s["market"], s["selection"], Decimal(s["line"])): s
              for s in packet.content.get("market", {}).get("selections", [])}
    if len(cards) < MAX_CARDS:
        views = []
        for m, sel, line in CORE_KEYS:
            if m in used_markets:
                continue
            mv = _model_view(packet, (m, sel, line))
            ms = market.get((m, sel, line))
            if mv is None or ms is None or ms.get("p_fair") is None:
                continue
            edge = float(mv["p"]) - float(ms["p_fair"])
            views.append((edge, m, sel, line, mv, ms))
        best_per_market: dict[str, tuple[float, str, str, Decimal, dict[str, Any], dict[str, Any]]] = {}
        for v in views:
            if v[1] not in best_per_market or v[0] > best_per_market[v[1]][0]:
                best_per_market[v[1]] = v
        for edge, m, sel, line, mv, ms in sorted(best_per_market.values(), key=lambda v: -v[0]):
            if len(cards) >= MAX_CARDS:
                break
            p = Decimal(str(mv["p"]))
            odds = Decimal(str(ms["best_odds"])) if ms.get("best_odds") else None
            ev = None if odds is None else p * odds - 1
            decision, output, review_id = review_of((m, sel, line))
            cards.append({
                "market": m, "selection": sel, "line": str(line), "kind": "evaluated",
                "odds": _q(odds, "0.001"), "bookmaker": ms.get("bookmaker"), "p_model": _q(p, "0.0001"),
                "p_low": _q(mv.get("p_lo"), "0.0001"), "p_market": _q(ms["p_fair"], "0.0001"),
                "fair_odds": _q(1 / p) if p > 0 else None,
                "minimum_odds": _q((1 + MIN_EV) / Decimal(str(mv["p_lo"]))) if mv.get("p_lo") else None,
                "edge": _q(edge, "0.0001"), "ev": _q(ev, "0.0001"), "model": mv.get("model"), "pick_id": None,
                "qualified": False, "verdict": "not_recommended",
                "verdict_reason": "context_negative" if decision == "REJECT" else "edge_insufficient",
                "ai": None if decision is None else {"decision": decision, "review_id": review_id,
                                                     "confidence": (output or {}).get("confidence"),
                                                     "reason": (output or {}).get("reason"),
                                                     "positives": _positives(output), "risks": _risks(output)},
            })
            used_markets.add(m)
    if not cards and not packet.content.get("market", {}).get("observed"):
        cards = no_market_cards(packet)
    return cards


def no_market_cards(packet: Packet) -> list[dict[str, Any]]:
    """No price at all: the model's most likely outcome per main market, its fair odds and the minimum odds
    at which the rule would take it - never a value claim."""
    out: list[dict[str, Any]] = []
    for m in MAIN:
        best: dict[str, Any] | None = None
        for key in CORE_KEYS:
            if key[0] != m:
                continue
            mv = _model_view(packet, key)
            if mv is not None and mv.get("p_lo") and (best is None or float(mv["p"]) > float(best["p"])):
                best = mv
        if best is None:
            continue
        p, p_lo = Decimal(str(best["p"])), Decimal(str(best["p_lo"]))
        out.append({
            "market": m, "selection": best["selection"], "line": best["line"], "kind": "no_market",
            "odds": None, "bookmaker": None, "p_model": _q(p, "0.0001"), "p_low": _q(p_lo, "0.0001"),
            "p_market": None, "fair_odds": _q(1 / p), "minimum_odds": _q((1 + MIN_EV) / p_lo) if p_lo > 0 else None,
            "edge": None, "ev": None, "model": best.get("model"), "pick_id": None, "qualified": False,
            "verdict": "no_market", "verdict_reason": "market_unobserved", "ai": None,
        })
    return out[:MAX_CARDS]


def store_analysis(conn: psycopg.Connection[Any], packet: Packet, packet_id: int, cards: list[dict[str, Any]], *,
                   at: datetime, engines: list[str]) -> tuple[int, bool]:
    summary = {"recommended": sum(c["verdict"] == "recommended" for c in cards),
               "caution": sum(c["verdict"] == "caution" for c in cards),
               "not_recommended": sum(c["verdict"] == "not_recommended" for c in cards),
               "no_market": sum(c["verdict"] == "no_market" for c in cards),
               "missing": packet.missing}
    h = content_hash({"rule": RULE_VERSION, "packet": packet.hash, "cards": cards, "engines": sorted(set(engines))})
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id, input_hash FROM ai.match_analyses WHERE fixture_id = %s "
                    "ORDER BY built_at DESC, id DESC LIMIT 1", (packet.fixture_id,))
        newest = cur.fetchone()
        if newest is not None and newest[1] == h:
            return int(newest[0]), False
        cur.execute("INSERT INTO ai.match_analyses (fixture_id, built_at, rule_version, input_hash, packet_id, "
                    "market_observed, cards, summary, engines) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (packet.fixture_id, at, RULE_VERSION, h, packet_id,
                     bool(packet.content.get("market", {}).get("observed")),
                     Jsonb(_jsonable(cards)), Jsonb(_jsonable(summary)), sorted(set(engines))))
        row = cur.fetchone()
    assert row is not None
    return int(row[0]), True


def _jsonable(value: Any) -> Any:
    import json

    return json.loads(canonical(value))
