"""Read-only probes of what the provider really covers (Plan Maestro PM, block 1: PM-01-05 and PM-01-04).

    python -m scripts.coverage_probe half plan                     # the finished matches a run would ask for (no request)
    python -m scripts.coverage_probe half run --max-requests 150   # /fixtures/statistics?half=true of each of them, once
    python -m scripts.coverage_probe half report                   # per competition: halves, empty types, xG (no request)
    python -m scripts.coverage_probe odds --max-requests 60        # /odds where the provider's flag and our base disagree

``half`` (PM-01-05) measures, during one week (one run a day, 20 to 26 Nov 2026), whether ``/fixtures/statistics?half=true``
answers the first and second half (``statistics_1h``, ``statistics_2h``) and which types come empty, for every finished match of
the twelve competitions of ``HALF_LEAGUES`` that kicked off in the window (``--since``/``--until``; by default 20 Oct to 26 Nov
2026: the week's matches plus the four weeks before, so that each competition has a sample and not a handful). A run asks each
finished match of the window once, oldest first, up to ``--max-requests``: a match whose answer is already in the RAW index is
never asked again, so a run a day works through the backlog and then catches up with whatever finished since the last one. The answers are written to RAW and indexed under one ``half_probe`` run
(``raw.ingestion_runs``); nothing is normalised, no other table is written and no job of the worker is touched. ``report`` reads
those answers back from RAW and spends nothing: run it any time, as often as wanted.

``odds`` (PM-01-04) takes the competitions of ``ODDS_LEAGUES`` - the 21 where the provider's ``odds`` flag and the share of
matches with prices in our base disagree (measured 19 Nov 2026) - and asks one ``/odds?league=&season=`` page of each plus
``/odds?fixture=`` of at most three matches that kick off within 48 h. With what the base already says (was each match asked
by the capture, and did the answer carry prices: ``market.odds_asks``) each competition gets one cause: the flag is wrong and
the provider publishes, we never asked, or the provider does not publish. The league pages go first (one per competition), then
the matches, one competition at a time in turn, so that a cap (``--max-requests``, 60 by default) cuts matches, never a
competition. These answers are NOT written to RAW
(``persist=False``): an indexed ``/odds`` body would be read by the quote extractor and become prices, and a probe must not
change what the capture leaves behind. The printed report is the evidence.

Every request goes through ``build_client``: our daily budget and the per-minute limit, shared with the worker, plus the run's
own ``--max-requests``. The key is in a header, never in a parameter, a log line or the report. Guide:
``docs/owner/PM_01_05_SONDA_MITADES_Y_CUOTAS.md``. Exit 0 done | 2 cannot run (no database, usage error).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

HALF_JOB = "half_probe"
ODDS_JOB = "odds_flag_probe"
ENDPOINT = "/fixtures/statistics"

# PM-01-05: Primera A, Champions and Libertadores (the ficha's three) and nine more of different levels, among those whose
# provider flag says "statistics": four top divisions (England, Brazil, Argentina, Mexico), Japan and South Korea (K League 1:
# statistics in only 56 % of its matches on 19 Nov 2026, the patchy case), two second divisions (Spain, England) and a third
# (League One).
HALF_LEAGUES = (239, 2, 13, 39, 71, 128, 262, 98, 292, 141, 40, 41)
HALF_SINCE = datetime(2026, 10, 20, tzinfo=UTC)
HALF_UNTIL = datetime(2026, 11, 26, tzinfo=UTC)
SETTLE = timedelta(hours=2, minutes=30)
"""A match is asked once it is finished in our base and its kick-off is this far behind: the provider's statistics settle."""

# The data PM-05-01 would store, in the provider's names. The report decides "construir" or "no construir" for each.
KEY_TYPES = ("Corner Kicks", "Yellow Cards", "Red Cards", "Total Shots", "Shots on Goal", "Fouls", "Offsides",
             "Ball Possession", "Goalkeeper Saves", "expected_goals")
BUILD_SHARE = 0.90
"""PM-05-01's own acceptance (90 % of the matches with halves): below it a datum is not worth a table."""
MIN_SAMPLE = 5

# PM-01-04: the 21 competitions of the 19 Nov 2026 reading (02_mediciones, section 4): 17 with ``odds: false`` and prices in
# half or more of their matches, 4 with ``odds: true`` and prices in fewer than half.
ODDS_LEAGUES = (479, 169, 45, 244, 81, 357, 383, 90, 94, 96, 288, 206, 18, 12, 20, 848, 3, 240, 66, 299, 667)
ODDS_DAYS = 30
ODDS_AHEAD = timedelta(hours=48)
ODDS_PER_LEAGUE = 3
MATCH_WINNER = 1
"""The provider's bet id of 1X2 ("Match Winner")."""


# --- half: judging one answer ---------------------------------------------------------------------------------------


def _block(team: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    """A team's statistics block as ``{type: value}``; None when the block is missing or empty."""
    rows = team.get(name)
    if not isinstance(rows, list) or not rows:
        return None
    return {str(r.get("type")): r.get("value") for r in rows if isinstance(r, Mapping)}


def _number(value: Any) -> float | None:
    """A count or ``"1.3"`` / ``"76%"`` as a number; None for an empty value."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class HalfAnswer:
    """What one ``/fixtures/statistics?half=true`` answer carries."""

    teams: int
    halves: bool
    """Both teams with a non-empty first-half and second-half block."""
    empty: frozenset[str]
    """Types of the full-match block that came empty (missing or null) in either half for either team."""
    present: frozenset[str]
    """Types of the full-match block (either team)."""
    sums: Mapping[str, bool] = field(default_factory=dict)
    """For counted types with all three values: does first half + second half equal the match, for both teams?"""

    @property
    def answered(self) -> bool:
        return self.teams > 0


COUNTED = ("Corner Kicks", "Yellow Cards", "Red Cards", "Total Shots", "Shots on Goal", "Shots off Goal", "Fouls",
           "Offsides", "Goalkeeper Saves", "Blocked Shots", "Shots insidebox", "Shots outsidebox")


def judge_half(body: Mapping[str, Any]) -> HalfAnswer:
    teams = [t for t in (body.get("response") or []) if isinstance(t, Mapping)]
    present: set[str] = set()
    empty: set[str] = set()
    halves = bool(teams)
    sums: dict[str, bool] = {}
    unsummed: set[str] = set()
    for team in teams:
        total = _block(team, "statistics") or {}
        present |= {k for k, v in total.items() if v is not None}
        first, second = _block(team, "statistics_1h"), _block(team, "statistics_2h")
        if first is None or second is None:
            halves = False
            continue
        for name in total:
            if first.get(name) is None or second.get(name) is None:
                empty.add(name)
        for name in COUNTED:
            whole, a, b = _number(total.get(name)), _number(first.get(name)), _number(second.get(name))
            if whole is None or a is None or b is None:
                unsummed.add(name)
                continue
            sums[name] = sums.get(name, True) and abs(a + b - whole) < 1e-9
    if not halves:
        empty = set(present)
        sums = {}
    sums = {k: v for k, v in sums.items() if k not in unsummed}
    return HalfAnswer(teams=len(teams), halves=halves, empty=frozenset(empty), present=frozenset(present), sums=sums)


@dataclass
class CompetitionHalves:
    league: int
    name: str
    finished: int = 0
    asked: int = 0
    answered: int = 0
    with_halves: int = 0
    present: Counter[str] = field(default_factory=Counter)
    filled: Counter[str] = field(default_factory=Counter)
    sum_checked: Counter[str] = field(default_factory=Counter)
    sum_ok: Counter[str] = field(default_factory=Counter)

    def add(self, answer: HalfAnswer) -> None:
        self.asked += 1
        self.answered += answer.answered
        self.with_halves += answer.halves
        for name in answer.present:
            self.present[name] += 1
            if answer.halves and name not in answer.empty:
                self.filled[name] += 1
        for name, ok in answer.sums.items():
            self.sum_checked[name] += 1
            self.sum_ok[name] += ok

    def share_halves(self) -> float | None:
        return self.with_halves / self.asked if self.asked else None

    def share_filled(self, name: str) -> float | None:
        """Of the matches asked, how many carry this type in both halves (the denominator is every match asked: a match
        without halves, or without the type at all, does not have it)."""
        return self.filled[name] / self.asked if self.asked else None

    def decision(self, name: str) -> str:
        if self.asked < MIN_SAMPLE:
            return "sin muestra"
        share = self.share_filled(name)
        return "construir" if share is not None and share >= BUILD_SHARE else "no construir"

    def as_dict(self) -> dict[str, Any]:
        return {"league": self.league, "name": self.name, "finished": self.finished, "asked": self.asked,
                "answered": self.answered, "with_halves": self.with_halves, "share_halves": self.share_halves(),
                "types": {n: {"present": self.present[n], "filled_both_halves": self.filled[n],
                              "share_filled": self.share_filled(n), "decision": self.decision(n),
                              "sum_checked": self.sum_checked[n], "sum_ok": self.sum_ok[n]}
                          for n in sorted(set(self.present) | set(KEY_TYPES))}}


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.0f} %"


def render_half(rows: Sequence[CompetitionHalves], *, since: datetime, until: datetime, at: datetime,
                pending: int) -> str:
    lines = [f"# PM-01-05 - half=true por competición ({at:%Y-%m-%d %H:%M} UTC)", "",
             f"Partidos con saque entre {since:%Y-%m-%d %H:%M} y {until:%Y-%m-%d %H:%M} UTC; pendientes de pedir: {pending}.",
             f"Decisión por dato: «construir» si ≥ {BUILD_SHARE:.0%} de los partidos pedidos lo trae en las dos mitades "
             f"(mínimo {MIN_SAMPLE} partidos).", "",
             "| Competición | Terminados | Pedidos | Con respuesta | Con 1T y 2T | " + " | ".join(KEY_TYPES) + " |",
             "|---|---:|---:|---:|---:|" + "---:|" * len(KEY_TYPES)]
    for r in rows:
        cells = [f"{_pct(r.share_filled(n))} {'C' if r.decision(n) == 'construir' else ('-' if r.decision(n) == 'sin muestra' else 'N')}"
                 for n in KEY_TYPES]
        lines.append(f"| {r.name} ({r.league}) | {r.finished} | {r.asked} | {r.answered} | {_pct(r.share_halves())} | "
                     + " | ".join(cells) + " |")
    total = CompetitionHalves(0, "Todas")
    for r in rows:
        total.finished += r.finished
        total.asked += r.asked
        total.answered += r.answered
        total.with_halves += r.with_halves
        total.present.update(r.present)
        total.filled.update(r.filled)
        total.sum_checked.update(r.sum_checked)
        total.sum_ok.update(r.sum_ok)
    lines.append(f"| **Todas** | {total.finished} | {total.asked} | {total.answered} | {_pct(total.share_halves())} | "
                 + " | ".join(_pct(total.share_filled(n)) for n in KEY_TYPES) + " |")
    lines += ["", "C = construir, N = no construir, - = sin muestra. Porcentaje = partidos pedidos con el dato en las dos mitades.",
              "", "## 1T + 2T = partido (tipos contados, ambos equipos)", ""]
    checked = [n for n in COUNTED if total.sum_checked[n]]
    lines += [f"* {n}: {total.sum_ok[n]} de {total.sum_checked[n]}" for n in checked] or ["* sin partidos con mitades"]
    return "\n".join(lines) + "\n"


# --- odds: classifying one competition ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OddsEvidence:
    """What our base says of a competition's last ``ODDS_DAYS`` days of finished matches."""

    finished: int
    asked: int
    """Matches the capture asked ``/odds`` for at least once (``market.odds_asks``)."""
    asked_with_prices: int
    """Of those, matches for which some answer carried prices."""
    with_closing: int
    """Matches with a final pre-match price (``market.final_prematch_odds``)."""


@dataclass(frozen=True, slots=True)
class OddsLive:
    """What the provider answered today: one league page and up to three matches within 48 h."""

    league_results: int | None = None
    league_pages: int | None = None
    fixtures_asked: int = 0
    fixtures_with_prices: int = 0
    fixtures_with_1x2: int = 0
    bookmakers: tuple[int, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def publishes(self) -> bool | None:
        """True when any answer carried prices; False when every request answered and none did; None without answers."""
        if (self.league_results or 0) > 0 or self.fixtures_with_prices > 0:
            return True
        if self.league_results is None and self.fixtures_asked == 0:
            return None
        return False


CAUSES = {
    "bandera_falsa_publica": "la bandera dice que no y el proveedor sí publica cuotas (se pidieron y llegaron)",
    "no_se_pidio": "el proveedor publica o no consta, pero la captura no pidió la mayoría de los partidos",
    "no_publica": "se pidieron y el proveedor respondió sin cuotas en la mayoría de los partidos",
    "coincide": "la base y la bandera ya no discrepan",
    "sin_evidencia": "sin partidos terminados en la ventana ni respuesta hoy",
}


def classify(flag: bool, db: OddsEvidence, live: OddsLive) -> tuple[str, str]:
    """One competition's cause and the sentence that justifies it, from the flag, the base and today's answers.

    The base decides when it has matches: of the finished ones, the share never asked is "no se pidió" and the share asked
    without prices is "no publica"; the larger one is the cause when prices cover fewer than half. Today's answers confirm it
    (and decide alone when the window has no finished match)."""
    live_txt = ("hoy: sin respuesta" if live.publishes is None else
                f"hoy: liga {live.league_results if live.league_results is not None else '-'} resultados, "
                f"{live.fixtures_with_prices}/{live.fixtures_asked} partidos a < 48 h con cuotas "
                f"({live.fixtures_with_1x2} con 1X2)")
    if db.finished == 0:
        if live.publishes is None:
            return "sin_evidencia", live_txt
        if live.publishes:
            return ("bandera_falsa_publica" if not flag else "coincide"), live_txt
        return "no_publica", live_txt
    covered = db.asked_with_prices / db.finished
    not_asked = (db.finished - db.asked) / db.finished
    not_published = (db.asked - db.asked_with_prices) / db.finished
    base_txt = (f"base {ODDS_DAYS} d: {db.finished} terminados, {db.asked} pedidos, {db.asked_with_prices} con cuotas, "
                f"{db.with_closing} con cierre")
    why = f"{base_txt}; {live_txt}"
    if covered >= 0.5:
        return ("bandera_falsa_publica" if not flag else "coincide"), why
    return ("no_se_pidio" if not_asked >= not_published else "no_publica"), why


def judge_odds_fixture(body: Mapping[str, Any]) -> tuple[bool, bool, set[int]]:
    """``/odds?fixture=``: (any price, a 1X2 price, the bookmakers)."""
    books: set[int] = set()
    has_1x2 = False
    for item in body.get("response") or []:
        for book in (item.get("bookmakers") or []) if isinstance(item, Mapping) else []:
            if not isinstance(book, Mapping):
                continue
            bets = [b for b in (book.get("bets") or []) if isinstance(b, Mapping)]
            if bets:
                books.add(int(book.get("id") or 0))
            has_1x2 = has_1x2 or any(int(b.get("id") or 0) == MATCH_WINNER for b in bets)
    return bool(books), has_1x2, books


def render_odds(rows: Sequence[Mapping[str, Any]], *, at: datetime, requests: int) -> str:
    lines = [f"# PM-01-04 - /odds donde la bandera del proveedor y la base discrepan ({at:%Y-%m-%d %H:%M} UTC)", "",
             f"{len(rows)} competiciones, {requests} peticiones (sin guardar en RAW).", "",
             "| Competición | Bandera `odds` | Causa | Evidencia |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} ({r['league']}) | {'sí' if r['flag'] else 'no'} | **{r['cause']}** | {r['why']} |")
    counts = Counter(str(r["cause"]) for r in rows)
    lines += ["", "## Causas", ""] + [f"* {c} ({counts[c]}): {CAUSES[c]}" for c in CAUSES if counts[c]]
    return "\n".join(lines) + "\n"


# --- database and provider ------------------------------------------------------------------------------------------

FINISHED_SQL = """
SELECT c.provider_league_id AS league, c.name, f.provider_fixture_id AS fixture, f.kickoff_at,
       EXISTS (SELECT 1 FROM raw.ingestion_payloads p
                WHERE p.endpoint = %(endpoint)s AND p.params->>'half' = 'true'
                  AND p.params->>'fixture' = f.provider_fixture_id::text) AS asked
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.provider_league_id = ANY(%(leagues)s) AND f.status_group = 'finished'
   AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
 ORDER BY f.kickoff_at, f.provider_fixture_id
"""

ANSWERS_SQL = """
SELECT DISTINCT ON (p.params->>'fixture') (p.params->>'fixture')::bigint AS fixture, p.file_path
  FROM raw.ingestion_payloads p
 WHERE p.endpoint = %(endpoint)s AND p.params->>'half' = 'true' AND p.params->>'fixture' = ANY(%(fixtures)s)
 ORDER BY p.params->>'fixture', p.fetched_at DESC
"""

NAMES_SQL = "SELECT provider_league_id AS league, name FROM core.competitions WHERE provider_league_id = ANY(%(leagues)s)"

ODDS_BASE_SQL = """
WITH f AS (
  SELECT c.provider_league_id AS league, f.id, f.provider_fixture_id AS pf
    FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
    JOIN core.competitions c ON c.id = cs.competition_id
   WHERE c.provider_league_id = ANY(%(leagues)s) AND f.status_group = 'finished'
     AND f.kickoff_at >= %(at)s - make_interval(days => %(days)s) AND f.kickoff_at < %(at)s)
SELECT league, count(*) AS finished,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM market.odds_asks a WHERE a.provider_fixture_id = f.pf)) AS asked,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM market.odds_asks a WHERE a.provider_fixture_id = f.pf AND a.results > 0))
         AS asked_with_prices,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM market.final_prematch_odds o WHERE o.fixture_id = f.id)) AS with_closing
  FROM f GROUP BY league
"""

ODDS_LEAGUES_SQL = """
SELECT c.provider_league_id AS league, c.name, lc.season, lc.odds
  FROM core.competitions c
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.is_current
 WHERE c.provider_league_id = ANY(%(leagues)s)
"""

ODDS_AHEAD_SQL = """
SELECT * FROM (
  SELECT c.provider_league_id AS league, f.provider_fixture_id AS fixture, f.kickoff_at,
         row_number() OVER (PARTITION BY c.provider_league_id ORDER BY f.kickoff_at, f.provider_fixture_id) AS n
    FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
    JOIN core.competitions c ON c.id = cs.competition_id
   WHERE c.provider_league_id = ANY(%(leagues)s) AND f.status_group = 'scheduled'
     AND f.kickoff_at > %(at)s AND f.kickoff_at <= %(at)s + %(ahead)s) x
 WHERE n <= %(per)s ORDER BY league, kickoff_at
"""


def _connect(read_only: bool) -> Any:
    import psycopg

    from fbi.core.config import settings

    conn = psycopg.connect(settings.database.psycopg_url)
    conn.execute("SET statement_timeout = '90s'")
    if read_only:
        conn.execute("SET default_transaction_read_only = on")
        conn.commit()
    return conn


def _rows(conn: Any, sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _parse_at(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def half_targets(rows: Iterable[Mapping[str, Any]], *, at: datetime) -> list[Mapping[str, Any]]:
    """The finished matches still to ask: not asked yet and with their kick-off ``SETTLE`` behind."""
    return [r for r in rows if not r["asked"] and r["kickoff_at"] <= at - SETTLE]


async def half_run(conn: Any, targets: Sequence[Mapping[str, Any]], *, max_requests: int, at: datetime) -> dict[str, Any]:
    from fbi.core.errors import CircuitOpenError, ProviderError, QuotaExhaustedError
    from fbi.ingestion.ledger import RunCounters, RunLedger
    from fbi.providers.api_football.build import build_client
    from fbi.providers.api_football.provider import _raw

    ledger = RunLedger(conn)
    run_id = ledger.open(HALF_JOB, params={"targets": len(targets), "max_requests": max_requests}, scheduled_for=at)
    counters = RunCounters()
    answers: Counter[str] = Counter()
    client = build_client(max_requests=max_requests)
    try:
        for row in targets:
            if counters.api_calls >= max_requests:
                counters.stopped_early = f"request cap {max_requests}: {len(targets) - max_requests} match(es) left"
                break
            counters.api_calls += 1
            try:
                raw = _raw(await client.get(ENDPOINT, {"fixture": str(row["fixture"]), "half": "true"}))
            except (QuotaExhaustedError, CircuitOpenError) as exc:  # our budget, or the provider down: stop here
                counters.errors.append(f"{row['fixture']}: {type(exc).__name__}")
                counters.stopped_early = f"{type(exc).__name__}: {len(targets) - counters.api_calls + 1} match(es) left"
                break
            except ProviderError as exc:  # one failed match must not lose the others' evidence
                counters.errors.append(f"{row['fixture']}: {type(exc).__name__}: {exc}"[:300])
                answers["error"] += 1
                continue
            counters.payloads_stored += ledger.record_payloads(run_id, [raw])
            conn.commit()
            answer = judge_half(raw.body)
            answers["with_halves" if answer.halves else ("without_halves" if answer.answered else "empty")] += 1
    finally:
        await client.aclose()
        ledger.close(run_id, counters, notes=f"PM-01-05: {counters.api_calls} request(s), {dict(answers)}")
        conn.commit()
    return {"run_id": run_id, "requests": counters.api_calls, "answers": dict(answers), "errors": counters.errors[:5],
            "stopped_early": counters.stopped_early}


def half_report(conn: Any, rows: Sequence[Mapping[str, Any]], leagues: Sequence[int]) -> list[CompetitionHalves]:
    from fbi.core.config import settings
    from fbi.storage.payload_store import PayloadStore

    names = {int(r["league"]): str(r["name"]) for r in _rows(conn, NAMES_SQL, {"leagues": list(leagues)})}
    out = {lg: CompetitionHalves(lg, names.get(lg, str(lg))) for lg in leagues}
    league_of = {int(r["fixture"]): int(r["league"]) for r in rows}
    for r in rows:
        out[int(r["league"])].finished += 1
    files = _rows(conn, ANSWERS_SQL, {"endpoint": ENDPOINT, "fixtures": [str(f) for f in league_of]})
    store = PayloadStore(settings.runtime.raw_store_dir)
    for f in files:
        envelope = store.load(str(f["file_path"]))
        out[league_of[int(f["fixture"])]].add(judge_half(envelope.get("body") or {}))
    return [out[lg] for lg in leagues]


def odds_calls(leagues: Sequence[int], meta: Mapping[int, Mapping[str, Any]],
               ahead: Mapping[int, Sequence[int]]) -> list[tuple[str, int, dict[str, str]]]:
    """The requests of the odds probe, in order: first one league page of each competition that has a current season, then
    the matches within 48 h, one competition at a time in turn (each one's first match, then each one's second...), so that a
    request cap leaves out matches, never a whole competition."""
    calls: list[tuple[str, int, dict[str, str]]] = [
        ("league", lg, {"league": str(lg), "season": str(meta[lg]["season"])})
        for lg in leagues if meta.get(lg, {}).get("season")]
    depth = max((len(ahead.get(lg, ())) for lg in leagues), default=0)
    for i in range(depth):
        calls += [("fixture", lg, {"fixture": str(ahead[lg][i])}) for lg in leagues if i < len(ahead.get(lg, ()))]
    return calls


async def odds_probe(conn: Any, *, leagues: Sequence[int], max_requests: int, at: datetime) -> tuple[list[dict[str, Any]], int]:
    from fbi.core.errors import CircuitOpenError, ProviderError, QuotaExhaustedError
    from fbi.ingestion.ledger import RunCounters, RunLedger
    from fbi.providers.api_football.build import build_client

    meta = {int(r["league"]): r for r in _rows(conn, ODDS_LEAGUES_SQL, {"leagues": list(leagues)})}
    base = {int(r["league"]): r for r in _rows(conn, ODDS_BASE_SQL, {"leagues": list(leagues), "at": at,
                                                                     "days": ODDS_DAYS})}
    ahead: dict[int, list[int]] = {}
    for r in _rows(conn, ODDS_AHEAD_SQL, {"leagues": list(leagues), "at": at, "ahead": ODDS_AHEAD,
                                          "per": ODDS_PER_LEAGUE}):
        ahead.setdefault(int(r["league"]), []).append(int(r["fixture"]))
    ledger = RunLedger(conn)
    run_id = ledger.open(ODDS_JOB, params={"leagues": len(leagues), "max_requests": max_requests}, scheduled_for=at)
    counters = RunCounters()
    client = build_client(max_requests=max_requests)
    out: list[dict[str, Any]] = []
    seen: dict[int, dict[str, Any]] = {lg: {"errors": [], "league_results": None, "league_pages": None, "fx_asked": 0,
                                            "fx_prices": 0, "fx_1x2": 0, "books": set()} for lg in leagues}
    try:
        for kind, lg, params in odds_calls(leagues, meta, ahead):
            if counters.stopped_early:
                break
            if counters.api_calls >= max_requests:
                counters.stopped_early = f"request cap {max_requests}"
                break
            s = seen[lg]
            counters.api_calls += 1
            try:
                response = await client.get("/odds", params, persist=False)
            except (QuotaExhaustedError, CircuitOpenError) as exc:
                s["errors"].append(f"{kind}: {type(exc).__name__}")
                counters.stopped_early = type(exc).__name__
                break
            except ProviderError as exc:
                s["errors"].append(f"{kind}: {type(exc).__name__}")
                continue
            body = response.body
            if kind == "league":
                s["league_results"] = int(body.get("results") or 0)
                s["league_pages"] = int((body.get("paging") or {}).get("total") or 0)
            else:
                s["fx_asked"] += 1
                prices, has_1x2, books = judge_odds_fixture(body)
                s["fx_prices"] += prices
                s["fx_1x2"] += has_1x2
                s["books"] |= books
        for lg in leagues:
            m, s, b = meta.get(lg, {}), seen[lg], base.get(lg, {})
            db = OddsEvidence(int(b.get("finished") or 0), int(b.get("asked") or 0), int(b.get("asked_with_prices") or 0),
                              int(b.get("with_closing") or 0))
            live = OddsLive(s["league_results"], s["league_pages"], s["fx_asked"], s["fx_prices"], s["fx_1x2"],
                            tuple(sorted(s["books"])), tuple(s["errors"]))
            flag = bool(m.get("odds"))
            cause, why = classify(flag, db, live)
            out.append({"league": lg, "name": m.get("name") or str(lg), "season": m.get("season"), "flag": flag,
                        "cause": cause, "why": why,
                        "base": {"finished": db.finished, "asked": db.asked, "asked_with_prices": db.asked_with_prices,
                                 "with_closing": db.with_closing},
                        "live": {"league_results": live.league_results, "league_pages": live.league_pages,
                                 "fixtures_asked": live.fixtures_asked, "fixtures_with_prices": live.fixtures_with_prices,
                                 "fixtures_with_1x2": live.fixtures_with_1x2, "bookmakers": len(live.bookmakers),
                                 "errors": list(live.errors)}})
            counters.errors.extend(f"{lg} {e}" for e in s["errors"])
    finally:
        await client.aclose()
        ledger.close(run_id, counters, notes=f"PM-01-04: {counters.api_calls} request(s), not stored in RAW")
        conn.commit()
    return out, counters.api_calls


# --- command line ---------------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="coverage_probe", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="probe", required=True)
    half = sub.add_parser("half", help="PM-01-05: /fixtures/statistics?half=true, one week")
    half.add_argument("command", choices=("plan", "run", "report"))
    half.add_argument("--league", type=int, action="append", help="only this competition (repeatable)")
    half.add_argument("--since", type=_parse_at, default=HALF_SINCE, help="kick-off from (UTC, default %(default)s)")
    half.add_argument("--until", type=_parse_at, default=HALF_UNTIL, help="kick-off before (UTC, default %(default)s)")
    half.add_argument("--max-requests", type=int, default=150, help="run: at most this many requests (default %(default)s)")
    half.add_argument("--json", action="store_true", help="report: JSON instead of the table")
    odds = sub.add_parser("odds", help="PM-01-04: /odds where the provider's flag and our base disagree")
    odds.add_argument("--league", type=int, action="append", help="only this competition (repeatable)")
    odds.add_argument("--max-requests", type=int, default=60, help="at most this many requests (default %(default)s)")
    odds.add_argument("--json", action="store_true", help="JSON instead of the table")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from fbi.core.clock import now
    from fbi.core.logging import configure as configure_logging

    configure_logging("WARNING")
    at = now()
    if getattr(args, "max_requests", 1) < 1:
        print("coverage_probe: --max-requests must be at least 1", file=sys.stderr)
        return 2
    try:
        conn = _connect(read_only=args.probe == "half" and args.command != "run")
    except Exception as exc:
        print(f"coverage_probe: no database: {type(exc).__name__}", file=sys.stderr)
        return 2
    with conn:
        if args.probe == "odds":
            rows, spent = asyncio.run(odds_probe(conn, leagues=args.league or ODDS_LEAGUES, max_requests=args.max_requests,
                                                 at=at))
            print(json.dumps(rows, indent=1, default=str) if args.json else render_odds(rows, at=at, requests=spent))
            return 0
        leagues = tuple(args.league or HALF_LEAGUES)
        rows = _rows(conn, FINISHED_SQL, {"endpoint": ENDPOINT, "leagues": list(leagues), "since": args.since,
                                          "until": args.until})
        targets = half_targets(rows, at=at)
        if args.command == "plan":
            by_league = Counter(int(r["league"]) for r in targets)
            print(json.dumps({"at": at.isoformat(), "finished": len(rows), "asked": sum(bool(r["asked"]) for r in rows),
                              "to_ask": len(targets), "by_league": dict(sorted(by_league.items()))}, default=str))
            return 0
        if args.command == "run":
            result = asyncio.run(half_run(conn, targets, max_requests=args.max_requests, at=at))
            print(json.dumps({"at": at.isoformat(), "to_ask": len(targets), **result}, default=str))
            return 0
        report = half_report(conn, rows, leagues)
        pending = len(targets)
        if args.json:
            print(json.dumps({"at": at.isoformat(), "since": args.since.isoformat(), "until": args.until.isoformat(),
                              "pending": pending, "competitions": [r.as_dict() for r in report]}, indent=1, default=str))
        else:
            print(render_half(report, since=args.since, until=args.until, at=at, pending=pending), end="")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
