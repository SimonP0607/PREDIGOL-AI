"""MARKET DISCOVERY ENGINE - ``discovery-v1`` (weekly): every pre-match market API-Football offers, what it would take
to model it, and the ten incorporation criteria - written down (``intel.market_registry``), never activated.

What it reads: the provider's catalogue (``market.provider_markets``) and, for the last ``DAYS`` days, the last
pre-match /odds answer stored before each match's kick-off (RAW, the same payload behind ``market.odds_snapshots``:
every bet of every bookmaker is kept there). Per provider bet: matches offering it, bookmakers quoting it (median per
match), lines, how often it was present in the match's own snapshot, and whether the stored data could settle it.

The ten criteria (``criteria``): coverage (offered for >= 30 % of the priced matches), history (seen for >= 28
days), real price (median >= 3 bookmakers), model (an existing model can price it, or derive it from the goals
score matrix), calibration (a calibrator exists - only the active five), backtest (one exists), against the market
(the backtest beat the market), shadow (it is in shadow), volume (>= 100 matches a week) and stability (present in
>= 80 % of a match's snapshots that carry any bet).

Status: ACTIVE (modelled today), RESEARCH (price, volume and settle-able data: worth a model and a backtest),
CANDIDATE (one of the two is missing), NOT_MODELABLE (specials, exotic or unsettleable). The activation path stays
Mercado -> Datos -> Features -> Modelo -> Calibración -> Backtest -> Shadow -> Producción, with the owner's approval.
"""

from __future__ import annotations

import gzip
import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

VERSION = "discovery-v1"
DAYS = 7
MAX_PAYLOADS = 3000

PRICED_SINCE_SQL = """
SELECT h.market_key, min(f.kickoff_at) AS since
  FROM market.historical_odds h JOIN core.fixtures f ON f.id = h.fixture_id
 WHERE f.kickoff_at <= %(at)s
 GROUP BY 1
"""

PAYLOADS_SQL = """
SELECT DISTINCT ON (s.fixture_id) s.fixture_id, f.provider_fixture_id, s.payload_hash, p.file_path,
       cs.competition_id
  FROM market.odds_snapshots s
  JOIN core.fixtures f ON f.id = s.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN raw.ingestion_payloads p ON p.hash = s.payload_hash
 WHERE s.source = 'prematch' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(at)s AND s.captured_at < f.kickoff_at
   AND s.captured_at >= %(since)s - interval '3 days'
 ORDER BY s.fixture_id, s.captured_at DESC
 LIMIT %(limit)s
"""

DATA_COVERAGE_SQL = """
SELECT count(*) AS finished,
       avg((s.corners IS NOT NULL)::int)::float8 AS corners, avg((s.yellow_cards IS NOT NULL)::int)::float8 AS cards,
       avg((s.shots_on_target IS NOT NULL)::int)::float8 AS shots, avg((s.saves IS NOT NULL)::int)::float8 AS saves,
       avg((s.fouls IS NOT NULL)::int)::float8 AS fouls, avg((s.offsides IS NOT NULL)::int)::float8 AS offsides,
       avg((r.ht_goals_home IS NOT NULL)::int)::float8 AS halftime
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  LEFT JOIN LATERAL (SELECT * FROM core.fixture_team_stats t WHERE t.fixture_id = f.id AND t.team_side = 'home'
                      ORDER BY (t.source = 'api-football') DESC LIMIT 1) s ON true
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(at)s AND f.status_group = 'finished'
"""

PLAYER_COVERAGE_SQL = """
SELECT avg((EXISTS (SELECT 1 FROM core.fixture_player_stats p WHERE p.fixture_id = f.id))::int)::float8 AS players
  FROM core.fixtures f
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(at)s AND f.status_group = 'finished'
"""

# What would settle a bet, and whether today's models can price it - by the bet's name (the provider names are
# stable English labels, e.g. "Total - Home", "Corners Over Under", "Cards Over/Under").
RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"player|scorer|goalscorer|assist|anytime|first goal|last goal", re.I), "players", "new_model"),
    (re.compile(r"corner", re.I), "corners", "new_model"),
    (re.compile(r"card|booking", re.I), "cards", "new_model"),
    (re.compile(r"shots? on target", re.I), "shots", "new_model"),
    (re.compile(r"shot", re.I), "shots", "new_model"),
    (re.compile(r"save", re.I), "saves", "new_model"),
    (re.compile(r"foul", re.I), "fouls", "new_model"),
    (re.compile(r"offside", re.I), "offsides", "new_model"),
    (re.compile(r"first half|second half|1st half|2nd half|half time|halftime|ht/ft|highest scoring half", re.I),
     "halftime", "new_model"),
    (re.compile(r"^total - (home|away)$|team total|exact score|correct score|odd/even|win to nil|clean sheet|"
                r"draw no bet|both teams|results?/|total goals|goals over/under|handicap|double chance|"
                r"match winner|home/away|winning margin|to score in both|win both|win either|"
                r"to win to nil|team to score", re.I), "goals", "goal_matrix"),
)
SPECIALS = re.compile(r"own goal|penalty|var|red card in|substitut|injury|method|minute|time of|first to|race to|"
                      r"specials|scorecast|wincast|chance mix|multi", re.I)
PRIOR_RESEARCH: dict[int, str] = {
    16: "backtest P5 B3 (oct 2026): el modelo de goles no supera al mercado en totales de equipo; rechazado",
    17: "backtest P5 B3 (oct 2026): el modelo de goles no supera al mercado en totales de equipo; rechazado",
}


@dataclass
class BetStats:
    name: str = ""
    fixtures: set[int] = field(default_factory=set)
    books_per_fixture: list[int] = field(default_factory=list)
    lines: set[str] = field(default_factory=set)
    present_in_snapshot: int = 0
    competitions: set[int] = field(default_factory=set)


def classify(name: str) -> tuple[str | None, str]:
    """(data the bet needs to settle, how it could be modelled) from its name."""
    if SPECIALS.search(name) and not re.search(r"handicap|double chance", name, re.I):
        return None, "not_modelable"
    for pattern, data, how in RULES:
        if pattern.search(name):
            return data, how
    return None, "not_modelable"


def scan_payloads(rows: list[dict[str, Any]], root: Path) -> tuple[dict[int, BetStats], dict[str, int]]:
    bets: dict[int, BetStats] = defaultdict(BetStats)
    stats: dict[str, int] = defaultdict(int)
    for r in rows:
        try:
            with gzip.open(root / str(r["file_path"]), "rt", encoding="utf-8") as fh:
                env = json.load(fh)
        except (OSError, ValueError):
            stats["files_missing"] += 1
            continue
        stats["files_read"] += 1
        body = env.get("body") or env.get("response") or env
        items = body.get("response", []) if isinstance(body, dict) else []
        for it in items:
            if int((it.get("fixture") or {}).get("id") or 0) != int(r["provider_fixture_id"]):
                continue
            stats["fixtures"] += 1
            per_bet_books: dict[int, int] = defaultdict(int)
            for book in it.get("bookmakers") or []:
                for bet in book.get("bets") or []:
                    try:
                        bid = int(bet.get("id"))
                    except (TypeError, ValueError):
                        continue
                    b = bets[bid]
                    b.name = str(bet.get("name") or b.name)
                    per_bet_books[bid] += 1
                    for v in (bet.get("values") or [])[:40]:
                        b.lines.add(str(v.get("value"))[:40])
            for bid, n in per_bet_books.items():
                bets[bid].fixtures.add(int(r["fixture_id"]))
                bets[bid].competitions.add(int(r["competition_id"]))
                bets[bid].books_per_fixture.append(n)
                bets[bid].present_in_snapshot += 1
    return dict(bets), dict(stats)


def criteria_for(bid: int, b: BetStats, *, catalogue: dict[str, Any] | None, active: dict[int, str],
                 n_fixtures: int, coverage: dict[str, float], at: datetime,
                 fixtures_by_competition: dict[int, int] | None = None,
                 priced_since: datetime | None = None) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    """``priced_since``: the oldest kick-off with stored prices of this market (``market.historical_odds``), known only
    for the markets the platform normalises. The catalogue's own date is when the catalogue was loaded (29 Sep 2026
    for all 338 bets), which alone read every market - the five active ones too, priced since 2022 - as 14 days old."""
    data, how = classify(b.name)
    share = len(b.fixtures) / n_fixtures if n_fixtures else 0.0
    seen = [d for d in (None if catalogue is None else catalogue.get("first_seen_at"), priced_since) if d is not None]
    first_seen = min(seen) if seen else None
    history_days = None if first_seen is None else (at - first_seen).days
    median_books = statistics.median(b.books_per_fixture) if b.books_per_fixture else 0
    data_cov = None if data is None else coverage.get(data)
    is_active = bid in active
    in_comps = sum((fixtures_by_competition or {}).get(c, 0) for c in b.competitions)
    stability = None if not in_comps else len(b.fixtures) / in_comps
    backtested = bid in PRIOR_RESEARCH or is_active
    crit: dict[str, dict[str, Any]] = {
        "coverage": {"ok": share >= 0.30, "value": round(share, 3)},
        "history": {"ok": history_days is not None and history_days >= 28, "value": history_days},
        "real_price": {"ok": median_books >= 3, "value": median_books},
        "model": {"ok": is_active or how == "goal_matrix", "value": how},
        "calibration": {"ok": is_active, "value": "calibrador por mercado" if is_active else None},
        "backtest": {"ok": backtested, "value": PRIOR_RESEARCH.get(bid) or ("producción" if is_active else None)},
        "vs_market": {"ok": False, "value": PRIOR_RESEARCH.get(bid) or
                      ("sin edge validado fuera de muestra" if is_active else None)},
        "shadow": {"ok": is_active, "value": "shadow-rule-v2" if is_active else None},
        "volume": {"ok": len(b.fixtures) * 7 / DAYS >= 100, "value": len(b.fixtures)},
        "stability": {"ok": stability is not None and stability >= 0.8,
                      "value": None if stability is None else round(stability, 3)},
        "settle_data": {"ok": data is not None and (data_cov or 0) >= 0.8, "value": None if data is None else
                        {"data": data, "coverage": None if data_cov is None else round(data_cov, 3)}},
    }
    metrics = {"fixtures": len(b.fixtures), "share": round(share, 4), "median_books": median_books,
               "lines": len(b.lines), "sample_lines": sorted(b.lines)[:8], "history_days": history_days,
               "data": data, "how": how}
    if is_active:
        status, proposal = "ACTIVE", f"activo como {active[bid]}; sin edge validado: se mide en investigación"
    elif how == "not_modelable":
        status, proposal = "NOT_MODELABLE", "especial o exótico: sin modelo ni datos de liquidación fiables"
    elif crit["real_price"]["ok"] and crit["coverage"]["ok"] and crit["volume"]["ok"] and crit["settle_data"]["ok"]:
        status = "RESEARCH"
        proposal = (PRIOR_RESEARCH.get(bid) or
                    ("derivable de la matriz de goles: backtest contra el cierre antes de cualquier shadow"
                     if how == "goal_matrix" else
                     f"necesita un modelo propio de {data}: features, modelo, calibración y backtest"))
    else:
        status = "CANDIDATE"
        missing = [k for k in ("real_price", "coverage", "volume", "settle_data") if not crit[k]["ok"]]
        proposal = "falta: " + ", ".join(missing)
    return status, crit, metrics, proposal


def run_discovery(conn: psycopg.Connection[Any], *, at: datetime, run_id: int, root: Path | None = None,
                  days: int = DAYS) -> dict[str, Any]:
    from fbi.core.config import settings

    root = root or Path(settings.runtime.raw_store_dir)
    since = at - timedelta(days=days)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PAYLOADS_SQL, {"since": since, "at": at, "limit": MAX_PAYLOADS})
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT provider_bet_id, name, market_key, first_seen_at, last_seen_at FROM market.provider_markets "
                    "WHERE scope = 'prematch'")
        catalogue = {int(r["provider_bet_id"]): dict(r) for r in cur.fetchall()}
        cur.execute("SELECT key, provider_bet_id FROM market.markets WHERE is_model_enabled AND provider_bet_id IS NOT NULL")
        active = {int(r["provider_bet_id"]): str(r["key"]) for r in cur.fetchall()}
        cur.execute(PRICED_SINCE_SQL, {"at": at})
        priced = {str(r["market_key"]): r["since"] for r in cur.fetchall()}
        cur.execute(DATA_COVERAGE_SQL, {"since": at - timedelta(days=90), "at": at})
        cov = dict(cur.fetchone() or {})
        cur.execute(PLAYER_COVERAGE_SQL, {"since": at - timedelta(days=30), "at": at})
        cov["players"] = (cur.fetchone() or {}).get("players")
    coverage = {k: float(v) for k, v in cov.items() if k != "finished" and v is not None}
    coverage["goals"] = 1.0
    bets, stats = scan_payloads(rows, root)
    n_fix = int(stats.get("fixtures", 0))
    by_comp: dict[int, int] = defaultdict(int)
    for r in rows:
        by_comp[int(r["competition_id"])] += 1
    for bid, c in catalogue.items():  # in the catalogue but not seen priced in the sample
        if bid not in bets:
            bets[bid] = BetStats(name=str(c["name"]))
    counts: dict[str, int] = defaultdict(int)
    with conn.cursor() as cur:
        for bid, b in sorted(bets.items()):
            status, crit, metrics, proposal = criteria_for(bid, b, catalogue=catalogue.get(bid), active=active,
                                                           n_fixtures=n_fix, coverage=coverage, at=at,
                                                           fixtures_by_competition=by_comp,
                                                           priced_since=priced.get(active.get(bid, "")))
            counts[status] += 1
            cur.execute("INSERT INTO intel.market_registry (run_id, provider_bet_id, name, market_key, status, criteria, "
                        "metrics, proposal, version, built_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (run_id, provider_bet_id) DO NOTHING",
                        (run_id, bid, b.name or str((catalogue.get(bid) or {}).get("name") or bid),
                         active.get(bid) or (catalogue.get(bid) or {}).get("market_key"), status, Jsonb(crit),
                         Jsonb(metrics), proposal, VERSION, at))
    return {"payloads": len(rows), "scan": stats, "markets": len(bets), "by_status": dict(counts),
            "data_coverage": {k: round(v, 3) for k, v in coverage.items()}}
