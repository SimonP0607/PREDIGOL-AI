"""BOOKMAKER_COVERAGE_REPORT: which bookmakers price which competitions and markets for us.

Measured from what we captured, never from what a catalogue promises. API-Football lists 33
bookmakers; whether one of them prices a given league is something only the stored prices
can answer, and "the provider has it" is not the same claim as "the provider gave it to us".

Two populations, judged differently:

* **Played matches** (kicked off in the last ``days``, bounded below by the first stored
  pre-match price): every capture window has passed, so "priced or not" is final. These
  give the per-competition, per-bookmaker, per-market and per-country figures.
* **Upcoming matches** (next 72 h): judged by the capture plan instead
  (``truth.freshness.price_state``) - a match no window has reached is not yet due.

A competition's state, in this order:

  NOT_ASKED            fixtures in the window, not one asked for: OUR gap (critical)
  NOT_COVERED          the provider's coverage flag says no odds and nothing was priced
  UNPRICED_BY_PROVIDER asked, and the provider answered with no prices at all
  THIN                 priced, but the typical match had fewer than MIN_BOOKMAKERS books
  PARTIAL              fewer than COVERED_SHARE of its matches priced
  COVERED              at least COVERED_SHARE priced, typically by MIN_BOOKMAKERS or more

Nothing here spends a provider request.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.market.local_operators import COLJUEGOS_OPERATORS, LIST_AS_OF, LIST_SOURCE, provider_match
from fbi.truth.freshness import Freshness, price_state
from fbi.truth.gate import MIN_BOOKMAKERS

COVERED_SHARE = 0.8
DEFAULT_DAYS = 14
UPCOMING_HOURS = 72


class CompetitionState(StrEnum):
    NOT_ASKED = "NOT_ASKED"
    NOT_COVERED = "NOT_COVERED"
    UNPRICED_BY_PROVIDER = "UNPRICED_BY_PROVIDER"
    THIN = "THIN"
    PARTIAL = "PARTIAL"
    COVERED = "COVERED"


class BookmakerState(StrEnum):
    ACTIVE = "ACTIVE"
    """Priced at least one match in the window."""
    DORMANT = "DORMANT"
    """Priced before the window, not in it."""
    CATALOGUE_ONLY = "CATALOGUE_ONLY"
    """Listed by /odds/bookmakers, never seen in a stored price."""


class LocalState(StrEnum):
    PRICED_BY_PROVIDER_BRAND = "PRICED_BY_PROVIDER_BRAND"
    """A provider bookmaker of the same brand prices our matches - not confirmed to be the
    Colombian book."""
    CATALOGUE_ONLY = "CATALOGUE_ONLY"
    NOT_IN_PROVIDER = "NOT_IN_PROVIDER"


FIXTURES_SQL = """
SELECT f.id, f.provider_fixture_id, c.id AS competition_id, c.name AS competition, c.country, cs.season,
       c.provider_league_id, lc.odds AS flag_odds
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND f.status_group IN ('finished', 'live')
"""

ASKED_SQL = """
SELECT DISTINCT (p.params->>'fixture')::bigint AS provider_fixture_id
  FROM raw.ingestion_payloads p
 WHERE p.endpoint = '/odds' AND p.params ? 'fixture' AND p.params->>'fixture' ~ '^[0-9]+$'
   AND p.fetched_at >= %(asked_since)s
"""

PRICES_SQL = """
SELECT s.fixture_id, b.provider_bookmaker_id, s.market_key, max(s.captured_at) AS last_seen
  FROM market.odds_snapshots s JOIN market.bookmakers b ON b.id = s.bookmaker_id
  JOIN core.fixtures f ON f.id = s.fixture_id
 WHERE s.source = 'prematch' AND s.captured_at >= %(asked_since)s
   AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
 GROUP BY 1, 2, 3
"""

BOOKMAKERS_SQL = """
SELECT b.provider_bookmaker_id, b.name, b.is_active,
       (SELECT min(s.captured_at) FROM market.odds_snapshots s WHERE s.bookmaker_id = b.id) AS first_seen,
       (SELECT max(s.captured_at) FROM market.odds_snapshots s WHERE s.bookmaker_id = b.id) AS last_seen
  FROM market.bookmakers b
 ORDER BY b.provider_bookmaker_id
"""

FIRST_CAPTURE_SQL = "SELECT min(captured_at) FROM market.odds_snapshots WHERE source = 'prematch'"

UPCOMING_SQL = """
WITH asked AS (
    SELECT (p.params->>'fixture')::bigint AS provider_fixture_id, max(p.fetched_at) AS last_asked
      FROM raw.ingestion_payloads p
     WHERE p.endpoint = '/odds' AND p.params ? 'fixture' AND p.params->>'fixture' ~ '^[0-9]+$'
       AND p.fetched_at >= %(at)s - interval '4 days'
     GROUP BY 1
)
SELECT c.id AS competition_id, f.kickoff_at, lc.odds AS covered, a.last_asked,
       (SELECT max(o.captured_at) FROM market.odds_snapshots o WHERE o.fixture_id = f.id) AS last_capture
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
  LEFT JOIN asked a ON a.provider_fixture_id = f.provider_fixture_id
 WHERE c.is_tracked AND f.status_group = 'scheduled'
   AND f.kickoff_at BETWEEN %(at)s AND %(at)s + make_interval(hours => %(hours)s)
"""


@dataclass
class CompetitionCoverage:
    competition_id: int
    competition: str
    country: str | None
    season: int
    provider_league_id: int | None
    flag_odds: bool | None
    fixtures: int = 0
    asked: int = 0
    priced: int = 0
    priced_two_plus: int = 0
    """Matches whose 1X2 was priced by at least MIN_BOOKMAKERS bookmakers."""
    median_bookmakers: float | None = None
    bookmakers: dict[str, int] = field(default_factory=dict)
    markets: dict[str, int] = field(default_factory=dict)
    upcoming: dict[str, int] = field(default_factory=dict)
    """Next 72 h by capture-plan state (FRESH / STALE / UNAVAILABLE)."""
    state: CompetitionState = CompetitionState.NOT_ASKED
    reason: str = ""

    @property
    def priced_share(self) -> float:
        return self.priced / self.fixtures if self.fixtures else 0.0


@dataclass
class BookmakerCoverage:
    provider_bookmaker_id: int
    name: str
    state: BookmakerState
    fixtures: int = 0
    share: float = 0.0
    """Of the matches priced by anyone in the window."""
    competitions: int = 0
    countries: int = 0
    markets: dict[str, int] = field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    name_missing: bool = False


@dataclass
class MarketCoverage:
    market_key: str
    fixtures: int
    share: float
    bookmakers: int
    median_bookmakers: float | None


@dataclass
class CountryCoverage:
    country: str
    competitions: int
    fixtures: int
    priced: int
    bookmakers: int


@dataclass
class LocalCoverage:
    brand: str
    domain: str
    company: str
    state: LocalState
    provider_ids: list[int]
    provider_names: list[str]
    priced_fixtures: int
    colombian_edition_confirmed: bool = False
    note: str = ""


@dataclass
class CoverageReport:
    measured_at: datetime
    since: datetime
    until: datetime
    days: int
    first_capture: datetime | None
    fixtures: int = 0
    asked: int = 0
    priced: int = 0
    competitions: list[CompetitionCoverage] = field(default_factory=list)
    bookmakers: list[BookmakerCoverage] = field(default_factory=list)
    markets: list[MarketCoverage] = field(default_factory=list)
    countries: list[CountryCoverage] = field(default_factory=list)
    local: list[LocalCoverage] = field(default_factory=list)
    local_source: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        states = Counter(c.state.value for c in self.competitions)
        books = Counter(b.state.value for b in self.bookmakers)
        local = Counter(x.state.value for x in self.local)
        return {
            "fixtures": self.fixtures, "asked": self.asked, "priced": self.priced,
            "priced_share": round(self.priced / self.fixtures, 4) if self.fixtures else None,
            "competition_states": dict(states), "bookmaker_states": dict(books), "local_states": dict(local),
            "bookmakers_active": [b.name for b in self.bookmakers if b.state is BookmakerState.ACTIVE],
        }

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["summary"] = self.summary()
        for c in d["competitions"]:
            c["priced_share"] = round(c["priced"] / c["fixtures"], 4) if c["fixtures"] else 0.0
        return d


def _median(values: list[int]) -> float | None:
    return float(statistics.median(values)) if values else None


def _competition_state(c: CompetitionCoverage) -> tuple[CompetitionState, str]:
    if c.asked == 0:
        if c.flag_odds is False:
            return CompetitionState.NOT_COVERED, "the provider's coverage flag says no odds; never asked"
        return CompetitionState.NOT_ASKED, f"{c.fixtures} played matches, none asked for"
    if c.priced == 0:
        if c.flag_odds is False:
            return CompetitionState.NOT_COVERED, "the provider's coverage flag says no odds, and it had none"
        return CompetitionState.UNPRICED_BY_PROVIDER, f"asked for {c.asked} of {c.fixtures}; no price came back"
    if (c.median_bookmakers or 0) < MIN_BOOKMAKERS:
        return CompetitionState.THIN, f"the typical match had {c.median_bookmakers:g} bookmaker(s)"
    if c.priced_share < COVERED_SHARE:
        return CompetitionState.PARTIAL, f"{c.priced} of {c.fixtures} played matches priced"
    return CompetitionState.COVERED, f"{c.priced} of {c.fixtures} priced, typically by {c.median_bookmakers:g} books"


def build_report(conn: psycopg.Connection[Any], *, at: datetime, days: int = DEFAULT_DAYS,
                 upcoming_hours: int = UPCOMING_HOURS) -> CoverageReport:
    with conn.cursor() as cur:
        cur.execute(FIRST_CAPTURE_SQL)
        row = cur.fetchone()
    first_capture: datetime | None = row[0] if row else None
    since = at - timedelta(days=days)
    if first_capture is not None and first_capture > since:
        since = first_capture
    params = {"since": since, "until": at, "asked_since": since - timedelta(days=15), "at": at,
              "hours": upcoming_hours}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, params)
        fixtures = list(cur.fetchall())
        cur.execute(ASKED_SQL, params)
        asked = {int(r["provider_fixture_id"]) for r in cur.fetchall()}
        cur.execute(PRICES_SQL, params)
        prices = list(cur.fetchall())
        cur.execute(BOOKMAKERS_SQL)
        catalogue = list(cur.fetchall())
        cur.execute(UPCOMING_SQL, params)
        upcoming = list(cur.fetchall())

    report = CoverageReport(measured_at=at, since=since, until=at, days=days, first_capture=first_capture,
                            local_source={"as_of": LIST_AS_OF, "url": LIST_SOURCE})
    names = {int(b["provider_bookmaker_id"]): str(b["name"] or "").strip() for b in catalogue}

    def book_name(pid: int) -> str:
        return names.get(pid) or f"#{pid}"

    # fixture -> {market -> {bookmaker}}
    by_fixture: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    last_seen: dict[int, datetime] = {}
    for p in prices:
        pid = int(p["provider_bookmaker_id"])
        by_fixture[int(p["fixture_id"])][str(p["market_key"])].add(pid)
        if pid not in last_seen or p["last_seen"] > last_seen[pid]:
            last_seen[pid] = p["last_seen"]

    comps: dict[int, CompetitionCoverage] = {}
    comp_books: dict[int, list[int]] = defaultdict(list)
    book_fixtures: dict[int, set[int]] = defaultdict(set)
    book_comps: dict[int, set[int]] = defaultdict(set)
    book_countries: dict[int, set[str]] = defaultdict(set)
    book_markets: dict[int, Counter[str]] = defaultdict(Counter)
    market_fixtures: dict[str, list[int]] = defaultdict(list)
    country_books: dict[str, set[int]] = defaultdict(set)
    for f in fixtures:
        cid = int(f["competition_id"])
        c = comps.get(cid)
        if c is None:
            c = comps[cid] = CompetitionCoverage(cid, str(f["competition"]), f["country"], int(f["season"]),
                                                 f["provider_league_id"], f["flag_odds"])
        c.fixtures += 1
        report.fixtures += 1
        if int(f["provider_fixture_id"]) in asked:
            c.asked += 1
            report.asked += 1
        markets = by_fixture.get(int(f["id"]))
        if not markets:
            continue
        c.priced += 1
        report.priced += 1
        books = set().union(*markets.values())
        comp_books[cid].append(len(books))
        if len(markets.get("1X2", ())) >= MIN_BOOKMAKERS:
            c.priced_two_plus += 1
        for mk, ids in markets.items():
            c.markets[mk] = c.markets.get(mk, 0) + 1
            market_fixtures[mk].append(len(ids))
            for pid in ids:
                book_markets[pid][mk] += 1
        for pid in books:
            c.bookmakers[book_name(pid)] = c.bookmakers.get(book_name(pid), 0) + 1
            book_fixtures[pid].add(int(f["id"]))
            book_comps[pid].add(cid)
            if f["country"]:
                book_countries[pid].add(str(f["country"]))
                country_books[str(f["country"])].add(pid)

    upcoming_states: dict[int, Counter[str]] = defaultdict(Counter)
    for u in upcoming:
        pstate, _ = price_state(kickoff=u["kickoff_at"], at=at, last_capture=u["last_capture"],
                                last_asked=u["last_asked"], covered=u["covered"])
        upcoming_states[int(u["competition_id"])][pstate.value] += 1

    for cid, c in comps.items():
        c.median_bookmakers = _median(comp_books.get(cid, []))
        c.state, c.reason = _competition_state(c)
        c.upcoming = dict(upcoming_states.get(cid, {}))
        c.bookmakers = dict(sorted(c.bookmakers.items(), key=lambda kv: (-kv[1], kv[0])))
    order = list(CompetitionState)
    report.competitions = sorted(comps.values(), key=lambda c: (order.index(c.state), -c.fixtures, c.competition))

    for b in catalogue:
        pid = int(b["provider_bookmaker_id"])
        n = len(book_fixtures.get(pid, ()))
        bstate = (BookmakerState.ACTIVE if n else
                  BookmakerState.DORMANT if b["last_seen"] is not None else BookmakerState.CATALOGUE_ONLY)
        report.bookmakers.append(BookmakerCoverage(
            pid, book_name(pid), bstate, fixtures=n, share=round(n / report.priced, 4) if report.priced else 0.0,
            competitions=len(book_comps.get(pid, ())), countries=len(book_countries.get(pid, ())),
            markets=dict(book_markets.get(pid, {})), first_seen=b["first_seen"],
            last_seen=last_seen.get(pid, b["last_seen"]), name_missing=not names.get(pid)))
    report.bookmakers.sort(key=lambda b: (-b.fixtures, b.provider_bookmaker_id))

    for mk, counts in sorted(market_fixtures.items(), key=lambda kv: -len(kv[1])):
        books = {pid for pid, m in book_markets.items() if m.get(mk)}
        report.markets.append(MarketCoverage(mk, len(counts), round(len(counts) / report.priced, 4)
                                             if report.priced else 0.0, len(books), _median(counts)))

    countries: dict[str, CountryCoverage] = {}
    for c in comps.values():
        key = c.country or "?"
        cc = countries.setdefault(key, CountryCoverage(key, 0, 0, 0, 0))
        cc.competitions += 1
        cc.fixtures += c.fixtures
        cc.priced += c.priced
    for key, cc in countries.items():
        cc.bookmakers = len(country_books.get(key, ()))
    report.countries = sorted(countries.values(), key=lambda x: (-x.fixtures, x.country))

    for op in COLJUEGOS_OPERATORS:
        op_ids = provider_match(op, names)
        priced = len(set().union(*(book_fixtures.get(i, set()) for i in op_ids))) if op_ids else 0
        ever = any(b["last_seen"] is not None for b in catalogue if int(b["provider_bookmaker_id"]) in op_ids)
        lstate: LocalState
        if priced or ever:
            lstate, note = (LocalState.PRICED_BY_PROVIDER_BRAND,
                            "the provider's feed of this brand prices our matches; that it is the Colombian "
                            "book (same prices, same markets) is not confirmed")
        elif op_ids:
            lstate, note = LocalState.CATALOGUE_ONLY, "listed by the provider, never priced a match for us"
        else:
            lstate, note = LocalState.NOT_IN_PROVIDER, "not offered by API-Football"
        report.local.append(LocalCoverage(op.brand, op.domain, op.company, lstate, op_ids,
                                          [book_name(i) for i in op_ids], priced, note=note))
    return report


def is_critical(report: CoverageReport) -> list[str]:
    """What, in this report, is our fault rather than the provider's."""
    return [f"{c.competition} {c.season}: {c.reason}" for c in report.competitions
            if c.state is CompetitionState.NOT_ASKED]


def upcoming_unavailable_share(report: CoverageReport) -> float | None:
    total = sum(sum(c.upcoming.values()) for c in report.competitions)
    if not total:
        return None
    return sum(c.upcoming.get(Freshness.UNAVAILABLE.value, 0) for c in report.competitions) / total


def _pct(x: float) -> str:
    return f"{x:.0%}"


def render_markdown(report: CoverageReport) -> str:
    s = report.summary()
    out = [
        "# BOOKMAKER_COVERAGE_REPORT",
        "",
        f"Measured {report.measured_at:%Y-%m-%d %H:%M} UTC from stored pre-match prices. Played matches of tracked "
        f"competitions that kicked off between {report.since:%Y-%m-%d %H:%M} and {report.until:%Y-%m-%d %H:%M} UTC "
        f"(the last {report.days} days, bounded by the first stored price, "
        f"{report.first_capture:%Y-%m-%d %H:%M} UTC)." if report.first_capture else
        f"Measured {report.measured_at:%Y-%m-%d %H:%M} UTC: no pre-match price stored yet.",
        "",
        f"**{report.priced} of {report.fixtures} played matches priced** "
        f"({_pct(report.priced / report.fixtures) if report.fixtures else '-'}); {report.asked} asked for. "
        f"Active bookmakers: {', '.join(s['bookmakers_active']) or 'none'}.",
        "",
        "## Bookmakers",
        "",
        "| Bookmaker | API id | State | Matches | Share of priced | Competitions | Countries | Markets |",
        "|---|---:|---|---:|---:|---:|---:|---|",
    ]
    for b in report.bookmakers:
        markets = ", ".join(f"{k} {v}" for k, v in sorted(b.markets.items(), key=lambda kv: -kv[1])) or "-"
        name = b.name + (" (no name in the provider's catalogue)" if b.name_missing else "")
        out.append(f"| {name} | {b.provider_bookmaker_id} | {b.state.value} | {b.fixtures} | {_pct(b.share)} | "
                   f"{b.competitions} | {b.countries} | {markets} |")
    out += ["", "## Markets", "", "| Market | Matches priced | Share | Bookmakers | Median books per match |",
            "|---|---:|---:|---:|---:|"]
    for m in report.markets:
        out.append(f"| {m.market_key} | {m.fixtures} | {_pct(m.share)} | {m.bookmakers} | "
                   f"{m.median_bookmakers if m.median_bookmakers is not None else '-'} |")
    out += ["", "## Competitions", "",
            "| Competition | Country | State | Played | Asked | Priced | 1X2 by >= 2 books | Median books | "
            "Next 72 h | Why |",
            "|---|---|---|---:|---:|---:|---:|---:|---|---|"]
    for c in report.competitions:
        up = ", ".join(f"{k} {v}" for k, v in sorted(c.upcoming.items())) or "-"
        out.append(f"| {c.competition} {c.season} | {c.country or '-'} | {c.state.value} | {c.fixtures} | {c.asked} | "
                   f"{c.priced} | {c.priced_two_plus} | "
                   f"{c.median_bookmakers if c.median_bookmakers is not None else '-'} | {up} | {c.reason} |")
    out += ["", "## Countries", "", "| Country | Competitions | Played | Priced | Bookmakers |",
            "|---|---:|---:|---:|---:|"]
    for cc in report.countries:
        out.append(f"| {cc.country} | {cc.competitions} | {cc.fixtures} | {cc.priced} | {cc.bookmakers} |")
    out += ["", "## Colombian licensed operators (Coljuegos)", "",
            f"List as of {report.local_source.get('as_of')} ({report.local_source.get('url')}).", "",
            "| Brand | Domain | State | Provider bookmaker | Matches priced | Note |", "|---|---|---|---|---:|---|"]
    for x in report.local:
        out.append(f"| {x.brand} | {x.domain} | {x.state.value} | {', '.join(x.provider_names) or '-'} | "
                   f"{x.priced_fixtures} | {x.note} |")
    critical = is_critical(report)
    out += ["", "## Our gaps (critical)", ""]
    out += [f"- {c}" for c in critical] or ["- none: every competition with played matches was asked for"]
    return "\n".join(out) + "\n"
