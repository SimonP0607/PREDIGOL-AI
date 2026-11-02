"""THE MATRIX OF MARKETS (plan F9, section 9), generated from the database instead of written by hand.

One row per market of the provider (or group of bets that are one market for a modeller): is it offered, how many matches ended with the
figure that grades it, since when and how deep we keep its prices, how many houses quote it, how many matches have a price, whether a
model exists - and the VERDICT those facts earn. The verdict is a function (``judge``) of the facts and of nothing else, except for the
few rows whose verdict is a documented judgement the data cannot give (``curated``: a rejected backtest, a market of no information).

    LISTO ............ a model, a calibrator and an edge validated against the closing line (no market has one)
    PARCIAL .......... a model prices it and the pipeline runs it; the edge is NOT validated (the five markets of today)
    POR INVESTIGAR ... it can be graded and there is a price to measure against, but no model yet; the priority says where to start
    NO VIABLE ........ nothing to grade it on, no price anyone could be measured against, or judged not worth it

The facts are measured over two windows: the PRICES of the last ``PRICE_DAYS`` days (``market.odds_quotes``, the price clock of F1 -
``market.fixture_outcomes`` for the results of the last ``OUTCOME_DAYS`` days and, for the depth, of all time). The rows are stored
(``market.catalogue_runs``) so the admin page and the owner's guide show numbers that were measured at a stated time, and the price
columns of the bets the price clock does not extract come from the newest discovery run (``intel.market_registry``), marked as such.

Nothing here writes outside ``market.catalogue_runs`` and nothing asks the provider for anything.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.core.decision_versions import DECISION_CORE
from fbi.market.catalogue import DEFINITIONS_SQL, market_key_for, spec_from_row
from fbi.market.rules import NO_DATA, OK, OUTCOMES_VIEW, RULES, RULES_BY_MEASURE, Rule, explain
from fbi.odds.quote_taxonomy import PROVIDER, SCOPE, TAXONOMY_VERSION, BetSpec

MATRIX_VERSION: Final = "matrix-v1"
PRICE_DAYS: Final = 8
OUTCOME_DAYS: Final = 365
DEPTH_TIMEOUT_MS: Final = 90_000

# verdicts and priorities
LISTO, PARCIAL, INVESTIGAR, NO_VIABLE = "LISTO", "PARCIAL", "POR INVESTIGAR", "NO VIABLE"
HIGH, MEDIUM, LOW = "alta", "media", "baja"
MIN_HOUSES: Final = 2
"""A price needs at least two houses to be measured against anything: one house is the price, not a reference for it."""
HIGH_PRICE_COVERAGE: Final = 0.80
MEDIUM_PRICE_COVERAGE: Final = 1 / 3
HIGH_RESULTS: Final = 5_000
MEDIUM_RESULTS: Final = 1_000
"""Priority = how many matches have a price this week and how many results we keep to train on (last 365 days)."""

GROUPS: Final = {"A": "Resultado", "B": "Goles", "C": "Córners", "D": "Tarjetas", "E": "Jugadores", "F": "Porteros",
                 "G": "Tiros, faltas y fueras de juego", "H": "Futuros", "Z": "Otros"}


@dataclass(frozen=True, slots=True)
class RowDef:
    key: str
    group: str
    label: str
    label_en: str
    bets: tuple[int, ...] = ()
    families: tuple[str, ...] = ()
    rest_of: str | None = None
    """The bets of this family that no other row claims (so a bet the taxonomy parks tomorrow is still in the matrix)."""
    parent: str | None = None
    """The row that is measured first ("after the total")."""
    curated: tuple[str, str, str] | None = None
    """(verdict, priority or "", reason): a judgement the data cannot give; shown as such."""


_BACKTEST_REJECTED = (NO_VIABLE, "", "rejected_backtest")
_LOW_INFO = (NO_VIABLE, "", "low_information")

ROWS: Final[tuple[RowDef, ...]] = (
    RowDef("result.1x2", "A", "1X2", "Match winner", bets=(1,)),
    RowDef("result.double_chance", "A", "Doble oportunidad", "Double chance", bets=(12,)),
    RowDef("result.asian_handicap", "A", "Hándicap asiático", "Asian handicap", bets=(4,)),
    RowDef("result.draw_no_bet", "A", "Draw no bet", "Draw no bet", bets=(2,)),
    RowDef("result.handicap", "A", "Hándicap europeo y sin empate por equipo", "European handicap, team no bet", bets=(9, 206, 207)),
    RowDef("goals.over_under", "B", "Over/Under total", "Total goals", bets=(5,)),
    RowDef("goals.btts", "B", "Ambos marcan", "Both teams to score", bets=(8,)),
    RowDef("goals.team_total", "B", "Total por equipo", "Team totals", bets=(16, 17), curated=_BACKTEST_REJECTED),
    RowDef("goals_half.over_under", "B", "Goles 1.ª / 2.ª parte: Over/Under", "Half goals: over/under", bets=(6, 26)),
    RowDef("goals_half.result", "B", "Goles por mitad: ganador, doble oportunidad y sin empate", "Half result, double chance, draw no bet",
           bets=(13, 3, 20, 33, 109, 182), parent="goals_half.over_under"),
    RowDef("goals_half.btts", "B", "Ambos marcan por mitad", "Both teams to score by half", bets=(34, 35), parent="goals_half.over_under"),
    RowDef("goals_half.htft", "B", "HT/FT y mitad con más goles", "HT/FT and highest scoring half", bets=(7, 11, 192, 193),
           parent="goals_half.over_under"),
    RowDef("goals_half.handicap", "B", "Hándicap asiático por mitad", "Asian handicap by half", bets=(19, 104),
           parent="goals_half.over_under"),
    RowDef("goals_half.team_total", "B", "Total por equipo y mitad", "Team totals by half", bets=(105, 106, 107, 108),
           parent="goals_half.over_under"),
    RowDef("goals_half.rest", "B", "Otros de goles por mitad (impar/par, marcador de mitad, ganar ambas mitades...)",
           "Other half-goal markets", rest_of="goals_half", parent="goals_half.over_under"),
    RowDef("goals.exact_score", "B", "Marcador exacto", "Correct score", bets=(10,), curated=_LOW_INFO),
    RowDef("goals.rest", "B", "Par/impar, goles exactos y otros de goles", "Odd/even, exact goals and other goal markets",
           rest_of="goals", curated=_LOW_INFO),
    RowDef("corners.total", "C", "Córners: total (Over/Under, hándicap, rangos)", "Corners: total", bets=(45, 56, 85, 295, 338)),
    RowDef("corners.team", "C", "Córners por equipo", "Team corners", bets=(57, 58), parent="corners.total"),
    RowDef("corners.result", "C", "Córners 1x2, hándicap europeo y doble oportunidad", "Corners 1x2, European handicap, double chance",
           bets=(55, 239, 307, 339), parent="corners.total"),
    RowDef("corners.half", "C", "Córners 1.ª / 2.ª parte", "Corners by half", bets=(77, 84, 125, 126, 127, 128, 130, 131, 132, 133, 134, 135)),
    RowDef("cards.total", "D", "Tarjetas: total (Over/Under, hándicap)", "Cards: total", bets=(80, 79, 81)),
    RowDef("cards.team", "D", "Tarjetas por equipo", "Team cards", bets=(82, 83), parent="cards.total"),
    RowDef("cards.yellow", "D", "Amarillas: total, por equipo, 1x2 y doble oportunidad", "Yellow cards", bets=(153, 150, 151, 154, 158, 152, 157),
           parent="cards.total"),
    RowDef("cards.half", "D", "Amarillas por mitad e intervalos", "Yellow cards by half", bets=(155, 156, 159, 160, 161, 162, 203, 204, 309, 310, 299),
           parent="cards.total"),
    RowDef("cards.red", "D", "Rojas", "Red cards", bets=(335, 342, 86), parent="cards.total"),
    RowDef("cards.events", "D", "Primera tarjeta y ambos equipos reciben tarjeta", "First card, both teams booked", bets=(250, 252, 300),
           parent="cards.total"),
    RowDef("cards.rest", "D", "Otras de tarjetas", "Other card markets", rest_of="cards", parent="cards.total"),
    RowDef("players", "E", "Goleador, tiros, tiros a puerta, asistencia y tarjeta de jugador", "Player props", families=("players",)),
    RowDef("saves", "F", "Atajadas", "Goalkeeper saves", families=("saves",)),
    RowDef("shots.total", "G", "Tiros totales (equipo)", "Team shots", bets=(211, 220, 221, 340, 78)),
    RowDef("shots.on_target", "G", "Tiros a puerta (equipo)", "Team shots on target", bets=(87, 88, 89, 176, 177, 178, 243, 244)),
    RowDef("shots.rest", "G", "Otras de tiros", "Other shot markets", rest_of="shots"),
    RowDef("fouls", "G", "Faltas", "Fouls", families=("fouls",)),
    RowDef("offsides", "G", "Fueras de juego", "Offsides", families=("offsides",)),
    RowDef("tackles", "G", "Entradas", "Tackles", families=("tackles",)),
    RowDef("futures", "H", "Campeón, descenso y otros futuros", "Futures"),
    RowDef("timing", "Z", "Tiempos (primer gol, minuto del gol...)", "Timing", families=("timing",)),
    RowDef("special", "Z", "Especiales", "Specials", families=("special",)),
    RowDef("advance", "Z", "Quién pasa de ronda", "To qualify", families=("advance",)),
    RowDef("other_sport", "Z", "Apuestas de otros deportes", "Other sports", families=("other_sport",)),
    RowDef("unclassified", "Z", "Sin clasificar", "Unclassified", families=("unclassified",)),
)
ROW_KEYS: Final = tuple(r.key for r in ROWS)

# Rows with a curated verdict that the data does not give; the reason is a code the page translates.
CURATED_NOTES: Final = {
    "rejected_backtest": "backtest P5 B3 (oct 2026): the goals model does not beat the market on team totals",
    "low_information": "high margin and little information beyond the goals markets",
    "not_offered": "the provider offers no futures among its pre-match markets",
}


@dataclass
class DefRow:
    id: int
    spec: BetSpec
    settle_rule: str | None


@dataclass
class MeasureStats:
    window: int = 0
    total: int | None = None
    first: datetime | None = None
    by_type: dict[str, int] = field(default_factory=dict)
    by_competition: dict[int, int] = field(default_factory=dict)


@dataclass
class Facts:
    at: datetime
    price_days: int
    outcome_days: int
    defs: dict[int, DefRow]
    prices: dict[int, dict[int, int]]
    first_seen: dict[int, datetime]
    fixture_competition: dict[int, int]
    finished_window: int
    finished_by_type: dict[str, int]
    finished_by_competition: dict[int, int]
    measures: dict[str, MeasureStats]
    competitions: dict[int, dict[str, Any]]
    keys_enabled: dict[str, bool]
    edge: dict[str, str]
    calibrated: dict[str, int]
    decisions: dict[str, int]
    discovery: dict[int, dict[str, float]]
    cards: dict[str, Any]


def _counts_sql(rules: list[Rule]) -> str:
    parts = ["count(*) AS finished"]
    for r in rules:
        cond = " AND ".join(f"{c} IS NOT NULL" for c in r.columns)
        parts.append(f"count(*) FILTER (WHERE {cond}) AS m_{r.measure}")
    return ", ".join(parts)


def collect(conn: psycopg.Connection[Any], *, at: datetime, price_days: int = PRICE_DAYS,
            outcome_days: int = OUTCOME_DAYS) -> Facts:
    since_prices = at - timedelta(days=price_days)
    since_results = at - timedelta(days=outcome_days)
    liquid = [r for r in RULES if r.liquidable]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DEFINITIONS_SQL, (PROVIDER, SCOPE))
        defs = {int(r["id"]): DefRow(int(r["id"]), spec_from_row(r), r["settle_rule"]) for r in cur.fetchall()}

        cur.execute("SELECT q.definition_id, q.fixture_id, count(DISTINCT q.bookmaker_id) AS houses FROM market.odds_quotes q "
                    "WHERE q.captured_at >= %(since)s AND q.captured_at < %(at)s GROUP BY 1, 2", {"since": since_prices, "at": at})
        prices: dict[int, dict[int, int]] = {}
        for r in cur.fetchall():
            prices.setdefault(int(r["definition_id"]), {})[int(r["fixture_id"])] = int(r["houses"])
        cur.execute("SELECT d.id, (SELECT min(q.captured_at) FROM market.odds_quotes q WHERE q.definition_id = d.id) AS first "
                    "FROM market.market_definitions d WHERE d.extract")
        first_seen = {int(r["id"]): r["first"] for r in cur.fetchall() if r["first"] is not None}
        fixtures = sorted({f for per in prices.values() for f in per})
        cur.execute("SELECT f.id, cs.competition_id FROM core.fixtures f JOIN core.competition_seasons cs ON "
                    "cs.id = f.competition_season_id WHERE f.id = ANY(%s)", (fixtures,))
        fixture_competition = {int(r["id"]): int(r["competition_id"]) for r in cur.fetchall()}

        # results in the window: followed competitions only, per competition (type and id) and per measure
        cur.execute(f"SELECT competition_id, competition_type, {_counts_sql(liquid)} FROM {OUTCOMES_VIEW} "
                    "WHERE is_tracked AND kickoff_at >= %(since)s AND kickoff_at < %(at)s GROUP BY 1, 2",
                    {"since": since_results, "at": at})
        measures = {r.measure: MeasureStats() for r in liquid}
        finished_by_type: dict[str, int] = {}
        finished_by_competition: dict[int, int] = {}
        finished_window = 0
        for r in cur.fetchall():
            comp, ctype, n = int(r["competition_id"]), str(r["competition_type"]), int(r["finished"])
            finished_window += n
            finished_by_type[ctype] = finished_by_type.get(ctype, 0) + n
            finished_by_competition[comp] = finished_by_competition.get(comp, 0) + n
            for rule in liquid:
                k = int(r[f"m_{rule.measure}"])
                st = measures[rule.measure]
                st.window += k
                st.by_type[ctype] = st.by_type.get(ctype, 0) + k
                st.by_competition[comp] = st.by_competition.get(comp, 0) + k
        # depth: every finished match of the followed competitions, all time (a long scan; bounded, absent when it times out)
        try:
            with conn.transaction():
                conn.execute(f"SET LOCAL statement_timeout = {DEPTH_TIMEOUT_MS}")
                firsts = ", ".join(f"min(kickoff_at) FILTER (WHERE {' AND '.join(c + ' IS NOT NULL' for c in r.columns)}) "
                                   f"AS f_{r.measure}" for r in liquid)
                cur.execute(f"SELECT {_counts_sql(liquid)}, {firsts} FROM {OUTCOMES_VIEW} WHERE is_tracked AND kickoff_at < %s", (at,))
                row = cur.fetchone() or {}
            for rule in liquid:
                measures[rule.measure].total = int(row[f"m_{rule.measure}"])
                measures[rule.measure].first = row[f"f_{rule.measure}"]
        except psycopg.errors.QueryCanceled:
            pass

        comp_ids = sorted(set(fixture_competition.values()) | set(finished_by_competition))
        cur.execute("SELECT id, name, country, competition_type FROM core.competitions WHERE id = ANY(%s)", (comp_ids,))
        competitions = {int(r["id"]): dict(r) for r in cur.fetchall()}

        keys = sorted({mk for d in defs.values() if (mk := d.spec.market_key or market_key_for(d.spec))})
        cur.execute("SELECT key, is_model_enabled FROM market.markets WHERE key = ANY(%s)", (keys,))
        keys_enabled = {str(r["key"]): bool(r["is_model_enabled"]) for r in cur.fetchall()}
        cur.execute("SELECT DISTINCT ON (market_key, model_name) market_key, model_name, to_role FROM intel.promotions "
                    "WHERE entity = 'market_edge' ORDER BY market_key, model_name, at DESC")
        edge: dict[str, str] = {}
        for r in cur.fetchall():
            if r["market_key"] is not None and (r["to_role"] == "VALIDATED" or str(r["market_key"]) not in edge):
                edge[str(r["market_key"])] = str(r["to_role"])
        cur.execute("SELECT market_key, count(DISTINCT model_name) AS models FROM intel.calibrators GROUP BY 1")
        calibrated = {str(r["market_key"]): int(r["models"]) for r in cur.fetchall()}
        cur.execute("SELECT market_key, count(*) AS n FROM intel.decisions WHERE decision_version = %s AND known_at >= %s GROUP BY 1",
                    (DECISION_CORE, at - timedelta(days=14)))
        decisions = {str(r["market_key"]): int(r["n"]) for r in cur.fetchall()}

        cur.execute("SELECT provider_bet_id, (metrics->>'fixtures')::float AS fixtures, (metrics->>'median_books')::float AS houses "
                    "FROM intel.market_registry WHERE run_id = (SELECT max(run_id) FROM intel.market_registry)")
        discovery = {int(r["provider_bet_id"]): {"fixtures": float(r["fixtures"] or 0), "houses": float(r["houses"] or 0)}
                     for r in cur.fetchall()}

        cur.execute(f"SELECT count(*) FILTER (WHERE cards_source = 'events') AS with_events, "
                    f"count(*) FILTER (WHERE cards_source = 'events' AND red_ft_home + red_ft_away > 0) AS with_dismissal, "
                    f"count(*) FILTER (WHERE cards_consistent IS NOT NULL) AS compared, "
                    f"count(*) FILTER (WHERE cards_consistent) AS consistent FROM {OUTCOMES_VIEW} "
                    "WHERE is_tracked AND kickoff_at >= %(since)s AND kickoff_at < %(at)s", {"since": since_results, "at": at})
        cards = dict(cur.fetchone() or {})
    return Facts(at=at, price_days=price_days, outcome_days=outcome_days, defs=defs, prices=prices, first_seen=first_seen,
                 fixture_competition=fixture_competition, finished_window=finished_window, finished_by_type=finished_by_type,
                 finished_by_competition=finished_by_competition, measures=measures, competitions=competitions,
                 keys_enabled=keys_enabled, edge=edge, calibrated=calibrated, decisions=decisions, discovery=discovery, cards=cards)


# ── the verdict ───────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Verdict:
    verdict: str
    priority: str
    reason: str


def judge(*, curated: tuple[str, str, str] | None, n_bets: int, in_principle: bool, dominant_reason: str, n_extracted: int,
          price_fixtures: int, houses_median: float | None, price_coverage: float | None, results_n: int,
          model_enabled: bool, edge_validated: bool, parent_viable: bool) -> Verdict:
    """The verdict a row earns from its facts. Pure: the same facts, the same verdict."""
    if curated is not None:
        return Verdict(*curated)
    if model_enabled:
        return Verdict(LISTO, "", "edge_validated") if edge_validated else Verdict(PARCIAL, "", "edge_not_validated")
    if n_bets == 0:
        return Verdict(NO_VIABLE, "", "not_offered")
    if not in_principle:
        return Verdict(NO_VIABLE, "", dominant_reason)
    if n_extracted == 0:
        if houses_median is not None and houses_median < MIN_HOUSES:
            return Verdict(NO_VIABLE, "", "thin_price")
        return Verdict(INVESTIGAR, LOW, "not_extracted")
    if price_fixtures == 0:
        return Verdict(NO_VIABLE, "", "no_prices_in_window")
    if houses_median is None or houses_median < MIN_HOUSES:
        return Verdict(INVESTIGAR, LOW, "after_parent") if parent_viable else Verdict(NO_VIABLE, "", "thin_price")
    cov = price_coverage or 0.0
    if cov >= HIGH_PRICE_COVERAGE and results_n >= HIGH_RESULTS:
        return Verdict(INVESTIGAR, HIGH, "priced")
    if cov >= MEDIUM_PRICE_COVERAGE and results_n >= MEDIUM_RESULTS:
        return Verdict(INVESTIGAR, MEDIUM, "priced")
    return Verdict(INVESTIGAR, LOW, "priced")


def _row_bets(facts: Facts) -> dict[str, list[DefRow]]:
    """Every definition in exactly one row: the explicit bets, the whole families, then the rest of a family."""
    by_bet = {d.spec.bet_id: d for d in facts.defs.values()}
    claimed: set[int] = set()
    out: dict[str, list[DefRow]] = {r.key: [] for r in ROWS}
    for row in ROWS:
        for b in row.bets:
            if b in by_bet and b not in claimed:
                out[row.key].append(by_bet[b])
                claimed.add(b)
        for d in by_bet.values():
            if d.spec.family in row.families and d.spec.bet_id not in claimed:
                out[row.key].append(d)
                claimed.add(d.spec.bet_id)
    for row in ROWS:
        if row.rest_of:
            for d in by_bet.values():
                if d.spec.family == row.rest_of and d.spec.bet_id not in claimed:
                    out[row.key].append(d)
                    claimed.add(d.spec.bet_id)
    return out


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def build_rows(facts: Facts) -> list[dict[str, Any]]:
    """The matrix: one dict per row of ``ROWS``, in order."""
    bets_by_row = _row_bets(facts)
    base = {f for per in facts.prices.values() for f in per}
    out: list[dict[str, Any]] = []
    verdicts: dict[str, str] = {}
    for row in ROWS:
        defs = bets_by_row[row.key]
        extracted = [d for d in defs if d.spec.extract]
        decisions = [explain(d.spec) for d in defs]
        reasons = Counter(dc.reason for dc in decisions)
        in_principle = [dc for dc in decisions if dc.measure is not None and RULES_BY_MEASURE[dc.measure].liquidable]
        no_rule_reasons = Counter(dc.reason for dc in decisions if dc.reason != OK)
        dominant = no_rule_reasons.most_common(1)[0][0] if no_rule_reasons else NO_DATA
        # prices: the price clock for the extracted bets, the newest discovery for the others
        per_fixture: dict[int, int] = {}
        for d in extracted:
            for fx, houses in facts.prices.get(d.id, {}).items():
                per_fixture[fx] = max(per_fixture.get(fx, 0), houses)
        source = "price_clock"
        houses_median: float | None = float(statistics.median(per_fixture.values())) if per_fixture else None
        price_fixtures = len(per_fixture)
        if not extracted and defs:
            known = [facts.discovery[d.spec.bet_id] for d in defs if d.spec.bet_id in facts.discovery]
            if known:
                source = "discovery"
                houses_median = max(k["houses"] for k in known)
                price_fixtures = int(max(k["fixtures"] for k in known))
        price_coverage = (len(per_fixture) / len(base)) if (base and extracted) else None
        # results: the least covered measure among the rule-bearing bets of the row (the conservative reading)
        measures = sorted({dc.measure for dc in in_principle if dc.measure})
        stats = [facts.measures[m] for m in measures if m in facts.measures]
        worst = min(stats, key=lambda s: s.window) if stats else None
        results_n = worst.window if worst else 0
        totals = [s.total for s in stats if s.total is not None]
        firsts = [s.first for s in stats if s.first is not None]
        keys = sorted({k for d in defs if (k := d.spec.market_key or market_key_for(d.spec))})
        enabled = any(facts.keys_enabled.get(k, False) for k in keys)
        validated = any(facts.edge.get(k) == "VALIDATED" for k in keys)
        parent = row.parent
        verdict = judge(
            curated=row.curated, n_bets=len(defs) if (defs or row.key != "futures") else 0, in_principle=bool(in_principle),
            dominant_reason=dominant, n_extracted=len(extracted), price_fixtures=price_fixtures, houses_median=houses_median,
            price_coverage=price_coverage, results_n=results_n, model_enabled=enabled, edge_validated=validated,
            parent_viable=parent is not None and verdicts.get(parent) in (INVESTIGAR, PARCIAL, LISTO))
        if row.key == "futures":
            verdict = Verdict(NO_VIABLE, "", "not_offered")
        verdicts[row.key] = verdict.verdict
        firsts_price = [facts.first_seen[d.id] for d in extracted if d.id in facts.first_seen]
        out.append({
            "key": row.key, "group": row.group, "label": row.label, "label_en": row.label_en, "parent": parent,
            "bets": sorted(d.spec.bet_id for d in defs), "extracted_bets": sorted(d.spec.bet_id for d in extracted),
            "api": len(defs) > 0, "rules": sorted({d.settle_rule or "" for d in defs if d.settle_rule} |
                                                  {r.key for r in (RULES_BY_MEASURE[m] for m in measures)}),
            "reasons": dict(reasons),
            "results": None if worst is None else {
                "measures": measures, "n_window": results_n, "pct": round(results_n / facts.finished_window, 4) if facts.finished_window else None,
                "pct_by_type": {t: round(worst.by_type.get(t, 0) / n, 4) for t, n in sorted(facts.finished_by_type.items()) if n},
                "n_total": min(totals) if len(totals) == len(stats) and totals else None,
                "since": _iso(max(firsts)) if len(firsts) == len(stats) and firsts else None},
            "price": {"source": source, "fixtures": price_fixtures, "base_fixtures": len(base), "coverage": None if price_coverage is None else round(price_coverage, 4),
                      "houses_median": houses_median, "since": _iso(min(firsts_price)) if firsts_price else None,
                      "extracted": len(extracted)},
            "model": {"keys": keys, "enabled": enabled, "calibrated": sum(facts.calibrated.get(k, 0) for k in keys),
                      "decisions_14d": sum(facts.decisions.get(k, 0) for k in keys),
                      "edge": "VALIDATED" if validated else ("NOT_VALIDATED" if any(k in facts.edge for k in keys) else None)},
            "verdict": verdict.verdict, "priority": verdict.priority, "reason": verdict.reason,
            "curated": row.curated is not None or row.key == "futures"})
    return out


def coverage_doc(facts: Facts) -> dict[str, Any]:
    """Coverage by competition: results (the last ``outcome_days``) and prices (the last ``price_days``), per family group."""
    groups = {"goals_half": ("goals_1h", "goals_2h"), "corners": ("corners_ft",), "cards": ("cards_lines_ft", "cards_lines_1h"),
              "shots": ("shots_ft", "shots_on_target_ft")}
    by_family: dict[str, dict[int, set[int]]] = {g: {} for g in groups}
    any_price: dict[int, set[int]] = {}
    for did, per in facts.prices.items():
        d = facts.defs.get(did)
        if d is None:
            continue
        for fx in per:
            comp = facts.fixture_competition.get(fx)
            if comp is None:
                continue
            any_price.setdefault(comp, set()).add(fx)
            fam = {"goals_half": "goals_half", "corners": "corners", "cards": "cards", "shots": "shots"}.get(d.spec.family)
            if fam:
                by_family[fam].setdefault(comp, set()).add(fx)
    comps = sorted(set(facts.finished_by_competition) | set(any_price))
    rows = []
    for c in comps:
        info = facts.competitions.get(c, {})
        rows.append({
            "competition_id": c, "name": info.get("name"), "country": info.get("country"), "type": info.get("competition_type"),
            "finished": facts.finished_by_competition.get(c, 0),
            "results": {m: facts.measures[m].by_competition.get(c, 0) for g in groups.values() for m in g if m in facts.measures},
            "priced": len(any_price.get(c, ())), "price": {g: len(by_family[g].get(c, ())) for g in groups}})
    return {"results_days": facts.outcome_days, "price_days": facts.price_days, "competitions": rows,
            "totals": {"finished": facts.finished_window, "priced": len({f for s in any_price.values() for f in s})}}


def summary_doc(facts: Facts, rows: list[dict[str, Any]]) -> dict[str, Any]:
    cards = facts.cards
    with_events = int(cards.get("with_events") or 0)
    compared = int(cards.get("compared") or 0)
    defs = list(facts.defs.values())
    return {
        "by_verdict": dict(Counter(r["verdict"] for r in rows)),
        "by_priority": dict(Counter(r["priority"] for r in rows if r["priority"])),
        "definitions": len(defs), "extracted": sum(1 for d in defs if d.spec.extract),
        "with_rule": sum(1 for d in defs if d.settle_rule), "rules": len(RULES), "liquidable_rules": sum(1 for r in RULES if r.liquidable),
        "cards": {"matches_with_events": with_events, "matches_with_a_dismissal": int(cards.get("with_dismissal") or 0),
                  "convention_sensitive_pct": round(int(cards.get("with_dismissal") or 0) / with_events, 4) if with_events else None,
                  "events_vs_statistics_compared": compared,
                  "events_equal_statistics_pct": round(int(cards.get("consistent") or 0) / compared, 4) if compared else None},
    }


def generate(conn: psycopg.Connection[Any], *, at: datetime | None = None, price_days: int = PRICE_DAYS,
             outcome_days: int = OUTCOME_DAYS) -> dict[str, Any]:
    t0 = time.monotonic()
    at = at or datetime.now(UTC)
    facts = collect(conn, at=at, price_days=price_days, outcome_days=outcome_days)
    rows = build_rows(facts)
    return {"at": _iso(at), "matrix_version": MATRIX_VERSION, "taxonomy_version": TAXONOMY_VERSION, "window_days": facts.price_days,
            "rows": rows, "coverage": coverage_doc(facts), "summary": summary_doc(facts, rows),
            "duration_ms": int((time.monotonic() - t0) * 1000)}


def store(conn: psycopg.Connection[Any], matrix: dict[str, Any]) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO market.catalogue_runs (generated_at, matrix_version, taxonomy_version, window_days, duration_ms, rows, "
                    "coverage, summary) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (matrix["at"], matrix["matrix_version"], matrix["taxonomy_version"], matrix["window_days"], matrix["duration_ms"],
                     Jsonb(matrix["rows"]), Jsonb(matrix["coverage"]), Jsonb(matrix["summary"])))
        row = cur.fetchone()
    return int(row[0]) if row else 0


def latest(conn: psycopg.Connection[Any]) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, generated_at, matrix_version, taxonomy_version, window_days, duration_ms, rows, coverage, summary "
                    "FROM market.catalogue_runs ORDER BY generated_at DESC, id DESC LIMIT 1")
        return cur.fetchone()
