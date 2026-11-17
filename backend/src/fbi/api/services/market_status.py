"""The catalogue of markets WITH A STATE (AD-E01, IA-070): for every market the provider prices, whether PrediGol can evaluate it, and
why not when it cannot - by explicit, measurable rules and nothing else.

Decision n.º 7 of the owner (16-nov-2026): corners and cards first, keep what is already evaluable, players only once the line-up
evaluation is reliable, and NOTHING is offered without data, prices and a settlement rule that can be checked. This module turns that
sentence into a function (``judge``) of facts measured in the database (``collect``, read only), and serves the result as data
(``market_states.json`` beside this module, read by ``load_catalogue``) for the Intelligence contracts (C-01, C-02).

    evaluable ........ a settlement rule, results to settle it, prices from >= 3 houses, a model with forecasts and a VALIDATED
                       calibrator (a CHAMPION of ``calib-gate-v1`` in ``intel.promotions``). Evaluable is not "has an edge": the
                       edge is AD-K02's verdict, and today no market has one.
    en_calibracion ... everything but the validated calibrator.
    necesita_datos ... it could be evaluated one day, but a measurable piece is missing (houses, settled results, a model,
                       line-ups).
    no_ofrecer ....... out of scope, no settlement rule, a rule that is not registered, no prices at all, or results for less than
                       half of the priced matches. Never evaluated.

The checks run in a fixed order and the FIRST that fails gives the state and its reason (``REASONS``, a closed list; every reason
belongs to exactly one state). A market without a liquidable rule can never be ``evaluable`` whatever its other facts, and neither can
one priced by fewer than three houses: both are tested over every combination of facts.

The unit is the catalogue key (``market.markets.key``: ``CORNERS_OU``, ``OU_1H``...; the five of the pipeline keep theirs), which
groups the provider's bets that are one market (307 and 339). A bet with no key - every parked bet: players, timing, corners by half,
handicaps not mapped - is its own unit, ``bet_<id>`` (the same fallback ``fbi.odds.quote_current.market_code`` uses).

Served as data, not as a table (no migration): ``scripts/ia_market_states.py`` measures (read only) and writes the snapshot; a change of
state reaches the product only through a reviewed commit of that file, with the catalogue version and the time it was measured. The
reader re-judges every market from the facts stored with it under the CURRENT code, so a rule removed in code demotes a market at once
even if the snapshot is old; a test fails while the stored state and the re-judged one disagree. Nothing here writes, picks or shows.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal, get_args

import psycopg
from psycopg.rows import dict_row
from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import IntelligenceModel, UtcDatetime
from fbi.api.contracts.intelligence.vocab import MarketState
from fbi.market.catalogue import DEFINITIONS_SQL, market_key_for, spec_from_row
from fbi.market.rules import RULES, RULES_BY_KEY, explain
from fbi.odds.quote_taxonomy import PROVIDER, SCOPE, BetSpec, spec_for

CATALOG_VERSION: Final = "market-states-v1"
"""The version of the RULES below (checks, order, thresholds). A new threshold or check is a new version, never an edit."""

SNAPSHOT: Final = Path(__file__).resolve().parent / "market_states.json"

# ── thresholds (market-states-v1) ─────────────────────────────────────────────────────────────────────────────────────

MIN_BOOKS: Final = 3
"""Houses that must price the market, at the median over the priced matches of the window: fewer is «una sola casa» (TESIS §E)."""
PRICE_DAYS: Final = 14
"""Recent prices: the captures of the last 14 days (``market.odds_quotes``)."""
MODEL_DAYS: Final = 14
"""A model counts if it wrote forecasts for matches of the last 14 days (or of the next 3)."""
NO_SETTLEMENT: Final = 0.50
"""Share of the priced, finished matches of the window whose result carries the figure the rule reads: below half, the market is
not offered (TESIS §E: «cobertura de estadística < 50 %»). Above it, a match without the figure is settled as ``None`` (never a
loss) and leaves the sample; the share travels with the state (``settleable_pct``) so the gap is seen, not hidden."""
MIN_SETTLE_SAMPLE: Final = 30
"""Priced, finished matches needed before the settlement is called verified on real results."""
LINEUP_EVALUATION_RELIABLE: Final = False
"""Decision 7: player markets wait for a reliable line-up evaluation (E3, AD-D07, verdict in AD-K02). Not reached on 16-nov-2026;
only a reviewed change of this constant (a new catalogue version) moves it."""
OUT_OF_SCOPE_FAMILIES: Final = frozenset({"timing", "special", "advance", "other_sport", "unclassified"})
"""Families outside the plan (``fbi.market.rules`` OUT_OF_SCOPE): «to advance» needs the scenario engine first."""

States: Final[tuple[str, ...]] = get_args(MarketState)

Reason = Literal["completo", "sin_calibrador_validado", "sin_modelo", "pendiente_alineaciones", "liquidacion_sin_muestra",
                 "menos_de_3_casas", "sin_datos_de_resultado", "sin_cuotas", "regla_no_registrada", "sin_regla_liquidacion",
                 "fuera_de_alcance", "fuera_del_catalogo"]
"""Why a market is in its state. Closed: adding one is a new catalogue version."""

REASONS: Final[dict[str, str]] = {
    "completo": "evaluable",
    "sin_calibrador_validado": "en_calibracion",
    "sin_modelo": "necesita_datos",
    "pendiente_alineaciones": "necesita_datos",
    "liquidacion_sin_muestra": "necesita_datos",
    "menos_de_3_casas": "necesita_datos",
    "sin_datos_de_resultado": "no_ofrecer",
    "sin_cuotas": "no_ofrecer",
    "regla_no_registrada": "no_ofrecer",
    "sin_regla_liquidacion": "no_ofrecer",
    "fuera_de_alcance": "no_ofrecer",
    "fuera_del_catalogo": "no_ofrecer",
}
"""Every reason and the one state it gives."""
if tuple(REASONS) != get_args(Reason) or not set(REASONS.values()) <= set(States):  # pragma: no cover - import-time guard
    raise RuntimeError("REASONS and Reason disagree, or a reason gives a state outside MarketState")


# ── the unit: a market of the catalogue ───────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One market: its key, what it is about, the provider's bets it groups and the rule that grades it (or why none does)."""

    key: str
    name: str
    family: str
    period: str
    subject: str
    kind: str
    bet_ids: tuple[int, ...]
    extracted: bool
    rule_key: str | None
    rule_reason: str
    """``fbi.market.rules`` reason: ``ok`` with a liquidable rule, otherwise why no rule grades it (player_level, no_period_data...)."""


def unit_key(spec: BetSpec) -> str:
    """The catalogue key of a bet, or ``bet_<id>`` when it has none."""
    return spec.market_key or market_key_for(spec) or f"bet_{spec.bet_id}"


def entries(specs: Iterable[BetSpec]) -> list[CatalogEntry]:
    """The catalogue: one entry per key, the bets of a key in id order (the lowest names it). Bets under one key share their rule
    (``fbi.market.catalogue.key_defs`` refuses anything else), so the entry takes its rule from the first."""
    grouped: dict[str, list[BetSpec]] = defaultdict(list)
    for spec in sorted(specs, key=lambda s: s.bet_id):
        grouped[unit_key(spec)].append(spec)
    out: list[CatalogEntry] = []
    for key, group in sorted(grouped.items()):
        lead = group[0]
        decision = explain(lead)
        out.append(CatalogEntry(
            key=key, name=lead.name, family=lead.family, period=lead.period, subject=lead.subject, kind=lead.kind,
            bet_ids=tuple(s.bet_id for s in group), extracted=any(s.extract for s in group),
            rule_key=decision.rule.key if decision.liquidable and decision.rule else None, rule_reason=decision.reason))
    return out


# ── the evidence and the judgement ────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Evidence:
    """What was measured of one market. Every figure has its window (``Facts``); ``None`` is "not measured", never zero."""

    priced_fixtures: int = 0
    """Matches with at least one price of the market in the window (the price clock, extracted bets only)."""
    books_median: float | None = None
    """Houses per priced match, median."""
    fixtures_3_books: int = 0
    books_max: int = 0
    priced_finished: int = 0
    """Priced matches of the window that are finished."""
    settleable: int = 0
    """...of which the result carries the figure the rule reads (``market.fixture_outcomes``)."""
    model_fixtures: int = 0
    """Matches with a forecast of the market in the model window (``models.predictions``, ``models.match_forecasts``)."""
    champions: tuple[str, ...] = ()
    """Models of the market with a CHAMPION calibrator that has not been retired."""
    rule_registered: bool = False
    """The rule is in ``market.settlement_rules`` and liquidable there too (what settlement reads)."""
    discovery_fixtures: float | None = None
    discovery_books: float | None = None
    """For a bet whose prices are not extracted: the newest discovery run (``intel.market_registry``). Reported, never judged."""

    @property
    def settleable_share(self) -> float | None:
        return None if self.priced_finished == 0 else self.settleable / self.priced_finished


def judge(entry: CatalogEntry, ev: Evidence, *, lineup_reliable: bool = LINEUP_EVALUATION_RELIABLE) -> tuple[str, str]:
    """(state, reason) of one market. Pure: the same entry and facts, the same answer. The first check that fails decides."""
    rule = RULES_BY_KEY.get(entry.rule_key) if entry.rule_key else None
    if entry.family in OUT_OF_SCOPE_FAMILIES:
        reason = "fuera_de_alcance"
    elif rule is None or not rule.liquidable:
        reason = "sin_regla_liquidacion"
    elif not ev.rule_registered:
        reason = "regla_no_registrada"
    elif ev.priced_fixtures == 0:
        reason = "sin_cuotas"
    elif ev.priced_finished >= MIN_SETTLE_SAMPLE and ev.settleable < NO_SETTLEMENT * ev.priced_finished:
        reason = "sin_datos_de_resultado"
    elif ev.books_median is None or ev.books_median < MIN_BOOKS:
        reason = "menos_de_3_casas"
    elif ev.priced_finished < MIN_SETTLE_SAMPLE:
        reason = "liquidacion_sin_muestra"
    elif entry.subject in ("player", "keeper") and not lineup_reliable:
        reason = "pendiente_alineaciones"
    elif ev.model_fixtures == 0:
        reason = "sin_modelo"
    elif not ev.champions:
        reason = "sin_calibrador_validado"
    else:
        reason = "completo"
    return REASONS[reason], reason


# ── the measurement (read only) ───────────────────────────────────────────────────────────────────────────────────────

def _settle_case() -> str:
    whens = " ".join(f"WHEN '{r.key}' THEN ({' AND '.join(f'oc.{c} IS NOT NULL' for c in r.columns)})"
                     for r in RULES if r.liquidable)
    return f"CASE pf.rule {whens} ELSE false END"


PRICES_SQL: Final = f"""
WITH pf AS (
    SELECT coalesce(d.market_key, 'bet_' || d.provider_bet_id) AS key, q.fixture_id,
           count(DISTINCT q.bookmaker_id) AS books, min(d.settle_rule) AS rule
      FROM market.odds_quotes q JOIN market.market_definitions d ON d.id = q.definition_id
     WHERE q.captured_at >= %(since)s AND q.captured_at < %(at)s AND d.provider = %(provider)s AND d.scope = %(scope)s
     GROUP BY 1, 2),
fx AS MATERIALIZED (SELECT DISTINCT fixture_id FROM pf),
oc AS MATERIALIZED (SELECT o.* FROM market.fixture_outcomes o
                     WHERE o.fixture_id IN (SELECT fixture_id FROM fx) AND o.kickoff_at < %(at)s)
SELECT pf.key, count(*) AS priced, percentile_disc(0.5) WITHIN GROUP (ORDER BY pf.books) AS books_median,
       count(*) FILTER (WHERE pf.books >= {MIN_BOOKS}) AS priced_3, max(pf.books) AS books_max,
       count(oc.fixture_id) AS finished, count(*) FILTER (WHERE oc.fixture_id IS NOT NULL AND {_settle_case()}) AS settleable,
       (SELECT count(*) FROM fx) AS base
  FROM pf LEFT JOIN oc ON oc.fixture_id = pf.fixture_id
 GROUP BY pf.key ORDER BY pf.key
"""
"""Per market: matches priced in the window, houses per match (median, >= 3, max), and how many of the finished ones can be settled
by the market's rule. ``base``: every match priced in any market (the denominator of the coverage)."""

MODELS_SQL: Final = """
SELECT market_key, count(DISTINCT fixture_id) AS fixtures FROM (
    SELECT f.market_key, f.fixture_id FROM models.match_forecasts f WHERE f.known_at >= %(since)s AND f.known_at < %(at)s
    UNION ALL
    SELECT p.market_key, p.fixture_id FROM core.fixtures x JOIN models.predictions p ON p.fixture_id = x.id
     WHERE x.kickoff_at >= %(since)s AND x.kickoff_at < %(at)s + interval '3 days') m
 GROUP BY 1
"""

CHAMPIONS_SQL: Final = """
SELECT DISTINCT ON (p.market_key, p.model_name) p.market_key, p.model_name
  FROM intel.promotions p
 WHERE p.entity = 'calibrator' AND p.to_role = 'CHAMPION' AND p.at <= %(at)s AND p.market_key IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM intel.promotions q
                    WHERE q.entity = 'calibrator' AND q.entity_id = p.entity_id AND q.to_role = 'RETIRED'
                      AND q.at >= p.at AND q.at <= %(at)s)
 ORDER BY p.market_key, p.model_name, p.at DESC, p.id DESC
"""
"""The champions in force at ``at`` - the same reading as ``fbi.intel.calibration.ROLES_SQL``."""

RULES_SQL: Final = "SELECT rule_key, liquidable FROM market.settlement_rules"

DISCOVERY_SQL: Final = """
SELECT provider_bet_id, (metrics->>'fixtures')::float8 AS fixtures, (metrics->>'median_books')::float8 AS books
  FROM intel.market_registry WHERE run_id = (SELECT max(run_id) FROM intel.market_registry)
"""


@dataclass
class Facts:
    """Everything ``collect`` read. ``definitions`` are the rows of ``market.market_definitions`` (or, in an export, just
    ``provider_bet_id`` and ``name``: the rest is then the taxonomy's, which is what the database holds when it shows no drift)."""

    measured_at: datetime
    definitions: list[dict[str, Any]]
    prices: dict[str, dict[str, Any]] = field(default_factory=dict)
    base_fixtures: int = 0
    models: dict[str, int] = field(default_factory=dict)
    champions: dict[str, list[str]] = field(default_factory=dict)
    rules: dict[str, bool] = field(default_factory=dict)
    discovery: dict[int, dict[str, float | None]] = field(default_factory=dict)


def facts_from_rows(measured_at: datetime, raw: Mapping[str, Any]) -> Facts:
    """The facts from the rows of the six queries (``collect``) or from the same rows exported as JSON (``json_agg`` of each
    query; a definition may then be the list ``[provider_bet_id, name, market_key, settle_rule]``)."""
    definitions: list[dict[str, Any]] = []
    for d in raw.get("definitions") or ():
        if isinstance(d, Mapping):
            definitions.append(dict(d))
        else:
            definitions.append({"provider_bet_id": int(d[0]), "name": str(d[1])})
    prices: dict[str, dict[str, Any]] = {}
    base = 0
    for r in raw.get("prices") or ():
        base = max(base, int(r["base"]))
        prices[str(r["key"])] = {"priced": int(r["priced"]), "books_median": float(r["books_median"]),
                                 "priced_3": int(r["priced_3"]), "books_max": int(r["books_max"]),
                                 "finished": int(r["finished"]), "settleable": int(r["settleable"])}
    champions: dict[str, list[str]] = defaultdict(list)
    for r in raw.get("champions") or ():
        champions[str(r["market_key"])].append(str(r["model_name"]))
    discovery: dict[int, dict[str, float | None]] = {}
    for r in raw.get("discovery") or ():
        bet, fixtures, books = (r["provider_bet_id"], r["fixtures"], r["books"]) if isinstance(r, Mapping) else r
        discovery[int(bet)] = {"fixtures": None if fixtures is None else float(fixtures),
                               "books": None if books is None else float(books)}
    return Facts(measured_at=measured_at, definitions=definitions, prices=prices, base_fixtures=base,
                 models={str(r["market_key"]): int(r["fixtures"]) for r in raw.get("models") or ()},
                 champions={k: sorted(v) for k, v in champions.items()},
                 rules={str(r["rule_key"]): bool(r["liquidable"]) for r in raw.get("rules") or ()}, discovery=discovery)


def queries(at: datetime) -> list[tuple[str, str, dict[str, Any] | tuple[Any, ...] | None]]:
    """The six read-only queries of a measurement at ``at``: (name, SQL, parameters)."""
    return [
        ("definitions", DEFINITIONS_SQL, (PROVIDER, SCOPE)),
        ("prices", PRICES_SQL, {"since": at - timedelta(days=PRICE_DAYS), "at": at, "provider": PROVIDER, "scope": SCOPE}),
        ("models", MODELS_SQL, {"since": at - timedelta(days=MODEL_DAYS), "at": at}),
        ("champions", CHAMPIONS_SQL, {"at": at}),
        ("rules", RULES_SQL, None),
        ("discovery", DISCOVERY_SQL, None),
    ]


def collect(conn: psycopg.Connection[Any], *, at: datetime | None = None) -> Facts:
    """Read the facts. Read only (open the connection with ``default_transaction_read_only``); every query is bounded by its
    window, the price one by the captures of ``PRICE_DAYS`` days."""
    at = at or datetime.now(UTC)
    raw: dict[str, list[dict[str, Any]]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for name, sql, params in queries(at):
            cur.execute(sql, params)
            raw[name] = [dict(r) for r in cur.fetchall()]
    return facts_from_rows(at, raw)


def evidence_for(entry: CatalogEntry, facts: Facts) -> Evidence:
    p = facts.prices.get(entry.key, {})
    disc = [facts.discovery[b] for b in entry.bet_ids if b in facts.discovery]
    disc_fixtures = [f for d in disc if (f := d.get("fixtures")) is not None]
    disc_books = [b for d in disc if (b := d.get("books")) is not None]
    return Evidence(
        priced_fixtures=int(p.get("priced", 0)), books_median=p.get("books_median"), fixtures_3_books=int(p.get("priced_3", 0)),
        books_max=int(p.get("books_max", 0)), priced_finished=int(p.get("finished", 0)), settleable=int(p.get("settleable", 0)),
        model_fixtures=facts.models.get(entry.key, 0), champions=tuple(sorted(facts.champions.get(entry.key, ()))),
        rule_registered=entry.rule_key is not None and facts.rules.get(entry.rule_key, False),
        discovery_fixtures=max(disc_fixtures) if disc_fixtures else None, discovery_books=max(disc_books) if disc_books else None)


# ── the result, the snapshot and the reader ───────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class MarketStatus:
    entry: CatalogEntry
    evidence: Evidence
    state: str
    reason: str

    @property
    def key(self) -> str:
        return self.entry.key


def build(facts: Facts) -> list[MarketStatus]:
    """The state of every market of the catalogue, judged from the facts."""
    specs = [spec_from_row(r) if "family" in r else spec_for(int(r["provider_bet_id"]), str(r["name"]))
             for r in facts.definitions]
    out = []
    for e in entries(specs):
        ev = evidence_for(e, facts)
        state, reason = judge(e, ev)
        out.append(MarketStatus(e, ev, state, reason))
    return out


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def snapshot(facts: Facts, statuses: Sequence[MarketStatus]) -> dict[str, Any]:
    """The data the product reads: the version, when it was measured, the windows and thresholds, and per market its entry, its
    evidence and its state. The evidence travels so that the reader (and the test) can judge it again."""
    return {
        "catalog_version": CATALOG_VERSION, "measured_at": _iso(facts.measured_at),
        "windows": {"price_days": PRICE_DAYS, "model_days": MODEL_DAYS},
        "thresholds": {"min_books": MIN_BOOKS, "no_settlement": NO_SETTLEMENT,
                       "min_settle_sample": MIN_SETTLE_SAMPLE, "lineup_evaluation_reliable": LINEUP_EVALUATION_RELIABLE},
        "base_fixtures": facts.base_fixtures,
        "counts": {s: sum(1 for m in statuses if m.state == s) for s in States},
        "markets": [{**asdict(m.entry), "evidence": asdict(m.evidence), "state": m.state, "reason": m.reason} for m in statuses],
    }


def dump_snapshot(snap: Mapping[str, Any]) -> str:
    """The snapshot as it is committed: the head indented, one market per line (a change of state is a one-line diff)."""
    head = {k: v for k, v in snap.items() if k != "markets"}
    body = json.dumps(head, ensure_ascii=False, indent=1)[:-2]
    rows = ",\n".join("  " + json.dumps(m, ensure_ascii=False, separators=(",", ":")) for m in snap["markets"])
    return f"{body},\n \"markets\": [\n{rows}\n ]\n}}\n"


class MarketStatusView(IntelligenceModel):
    """What a contract carries of a market's state (C-01, C-02). Until AD-J03 it travels in the PRIVATE projection only."""

    market_key: str = Field(min_length=1)
    state: MarketState
    reason: Reason
    catalog_version: str = Field(min_length=1)
    measured_at: UtcDatetime
    books_median: float | None = Field(description="Houses per priced match, median over the price window; null: no price.")
    priced_fixtures: int = Field(ge=0)
    settleable_pct: float | None = Field(ge=0, le=100, description="Priced finished matches the rule can settle; null: none yet.")
    validated_calibrator: bool
    rule_key: str | None = Field(description="The settlement rule (``market.settlement_rules``); null: none grades it.")

    @model_validator(mode="after")
    def _coherent(self) -> MarketStatusView:
        if REASONS[self.reason] != self.state:
            raise ValueError(f"reason {self.reason} gives {REASONS[self.reason]}, not {self.state}")
        if self.state == "evaluable" and (self.rule_key is None or self.books_median is None or self.books_median < MIN_BOOKS
                                          or not self.validated_calibrator):
            raise ValueError("evaluable needs a settlement rule, prices of >= 3 houses and a validated calibrator")
        return self


@dataclass(frozen=True)
class MarketCatalogue:
    """The snapshot as the product reads it."""

    catalog_version: str
    measured_at: datetime
    statuses: Mapping[str, MarketStatus]
    by_bet: Mapping[int, str]

    def status(self, market_key: str) -> MarketStatus:
        """The state of a key (``CORNERS_OU``, ``bet_92``); a key the catalogue does not know is ``no_ofrecer`` (fuera_del_catalogo)."""
        found = self.statuses.get(market_key)
        if found is not None:
            return found
        unknown = CatalogEntry(key=market_key, name="", family="unclassified", period="FT", subject="match", kind="unspecified",
                               bet_ids=(), extracted=False, rule_key=None, rule_reason="out_of_scope")
        return MarketStatus(unknown, Evidence(), "no_ofrecer", "fuera_del_catalogo")

    def for_bet(self, bet_id: int) -> MarketStatus:
        """The state of the market a provider bet belongs to."""
        return self.status(self.by_bet.get(bet_id, f"bet_{bet_id}"))

    def for_market(self, market_key: str | None, bet_ids: Sequence[int] = ()) -> MarketStatus:
        """For a market of ``/matches/{id}/markets/catalog`` (its ``market_key`` when it has one, else its bets)."""
        if market_key:
            return self.status(market_key)
        return self.for_bet(min(bet_ids)) if bet_ids else self.status("")

    def view(self, market_key: str) -> MarketStatusView:
        m = self.status(market_key)
        share = m.evidence.settleable_share
        return MarketStatusView(
            market_key=market_key, state=m.state, reason=m.reason,  # type: ignore[arg-type]  # REASONS/States are the Literals
            catalog_version=self.catalog_version, measured_at=self.measured_at, books_median=m.evidence.books_median,
            priced_fixtures=m.evidence.priced_fixtures, settleable_pct=None if share is None else round(100 * share, 1),
            validated_calibrator=bool(m.evidence.champions), rule_key=m.entry.rule_key)


def parse_snapshot(data: Mapping[str, Any]) -> MarketCatalogue:
    """The catalogue from a snapshot, every market JUDGED AGAIN under the code that reads it (the stored state is not trusted): a
    rule the code no longer has, or a stricter check, demotes the market whatever the file says."""
    statuses: dict[str, MarketStatus] = {}
    by_bet: dict[int, str] = {}
    for row in data["markets"]:
        ev_raw = dict(row["evidence"])
        ev_raw["champions"] = tuple(ev_raw.get("champions", ()))
        entry = CatalogEntry(key=row["key"], name=row["name"], family=row["family"], period=row["period"], subject=row["subject"],
                             kind=row["kind"], bet_ids=tuple(row["bet_ids"]), extracted=row["extracted"], rule_key=row["rule_key"],
                             rule_reason=row["rule_reason"])
        ev = Evidence(**ev_raw)
        state, reason = judge(entry, ev)
        statuses[entry.key] = MarketStatus(entry, ev, state, reason)
        for b in entry.bet_ids:
            by_bet[b] = entry.key
    measured = datetime.fromisoformat(str(data["measured_at"]).replace("Z", "+00:00"))
    return MarketCatalogue(catalog_version=str(data["catalog_version"]), measured_at=measured, statuses=statuses, by_bet=by_bet)


@lru_cache(maxsize=4)
def load_catalogue(path: str | None = None) -> MarketCatalogue:
    """The catalogue the contracts read: the snapshot beside this module (or ``path``), parsed once per process."""
    with open(path or SNAPSHOT, encoding="utf-8") as fh:
        return parse_snapshot(json.load(fh))


def summary(statuses: Sequence[MarketStatus]) -> dict[str, Any]:
    """Counts by state, by reason and by family (the owner's report)."""
    by_family: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(States, 0))
    for m in statuses:
        by_family[m.entry.family][m.state] += 1
    priced = [m for m in statuses if m.evidence.priced_fixtures > 0]
    return {
        "markets": len(statuses), "priced_markets": len(priced),
        "by_state": {s: sum(1 for m in statuses if m.state == s) for s in States},
        "by_reason": {r: n for r in REASONS if (n := sum(1 for m in statuses if m.reason == r))},
        "by_family": dict(sorted(by_family.items())),
        "priced_books_median": statistics.median(m.evidence.books_median or 0 for m in priced) if priced else None,
    }
