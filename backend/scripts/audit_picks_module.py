"""The PICKS module's starting point, measured (plan PICKS, F1): the figures of section 2 of the plan, from the database.

    python -m scripts.audit_picks_module               # read-only; the owner's preview of the next 24 hours, now
    python -m scripts.audit_picks_module --hours 72
    python -m scripts.audit_picks_module --json        # the same figures, for docs/owner/PICKS_LINEA_BASE.md

It reads through a connection the server keeps READ ONLY, with a two-minute statement timeout, and calls the same
services the API answers with (``picks_board``, ``started_board``, ``daily_board``): what it counts is what the owner's
preview shows. It reports:

* the engine's totals: prices evaluated, shadow picks, qualified and published (none may be published: the database
  refuses it);
* the board (S1, S2, S3, C4, C5): cards and matches, the cards outside the value rule now and why, the same idea
  repeated on another line, the cards above 3.00, the direction of goals and both-teams-score, the age of each price;
* the started list (L2): candidates, matches and the most on one match;
* the two «picks del día» (D1): the page's set and Intelligence's decisions of the Bogotá day, by state.

It changes nothing and needs no provider call.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings

BOG = ZoneInfo("America/Bogota")
ODDS_CAP = Decimal("3.00")
READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=120000 -c TimeZone=UTC"
GOALS_MARKETS = frozenset({"OU"})

TOTALS_SQL = """
SELECT (SELECT count(*) FROM picks.pick_candidates) AS prices_evaluated,
       (SELECT count(*) FROM picks.picks) AS picks,
       (SELECT count(*) FROM picks.picks WHERE status = 'qualified') AS qualified,
       (SELECT count(*) FROM picks.picks WHERE status = 'published' OR published_at IS NOT NULL) AS published,
       (SELECT count(*) FROM picks.pick_results WHERE result_status NOT IN ('pending')) AS settled
"""
INTEL_DAY_SQL = """
SELECT state, count(*)::int AS n FROM (
  SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.state
    FROM intel.decisions d
   WHERE d.kickoff_at >= %(start)s AND d.kickoff_at < %(end)s
   ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC) last
 GROUP BY state ORDER BY state
"""
INTEL_SET_SQL = """
SELECT rule_version, count(*)::int AS n FROM intel.day_selections
 WHERE day = %(day)s AND kind = 'pick' GROUP BY rule_version ORDER BY rule_version
"""


def _get(card: Any, key: str) -> Any:
    return card[key] if isinstance(card, Mapping) else getattr(card, key)


def _side(card: Any) -> tuple[Any, str, str]:
    """A card's idea without its line: the same match, market and side."""
    return (_get(card, "fixture_id"), str(_get(card, "market_key")), str(_get(card, "selection")))


def board_figures(cards: Iterable[Any], now: datetime) -> dict[str, Any]:
    """S1, S2, S3, C4 and C5 over the cards of the owner's preview (dicts or ``PickCard``)."""
    cards = list(cards)
    per_fixture = Counter(_get(c, "fixture_id") for c in cards)
    ideas = Counter(_side(c) for c in cards)
    reasons = Counter(str(_get(c, "value_reason") or "") for c in cards if not _get(c, "value_now"))
    over_cap = sum(1 for c in cards if _get(c, "best_odds") is not None and Decimal(_get(c, "best_odds")) > ODDS_CAP)
    ages = [(now - _get(c, "price_at")).total_seconds() / 3600 for c in cards if _get(c, "price_at") is not None]
    goals = Counter(str(_get(c, "selection")) for c in cards if _get(c, "market_key") in GOALS_MARKETS)
    btts = Counter(str(_get(c, "selection")) for c in cards if _get(c, "market_key") == "BTTS")
    n = len(cards)
    return {
        "cards": n,
        "fixtures": len(per_fixture),
        "outside_rule_now": sum(reasons.values()),
        "outside_rule_reasons": dict(reasons.most_common()),
        "repeated_on_another_line": n - len(ideas),
        "cards_per_fixture_median": statistics.median(per_fixture.values()) if per_fixture else 0,
        "cards_per_fixture_max": max(per_fixture.values(), default=0),
        "above_3_00": over_cap,
        "goals_under": goals.get("Under", 0),
        "goals_over": goals.get("Over", 0),
        "btts_no": btts.get("No", 0),
        "btts_yes": btts.get("Yes", 0),
        "price_age_hours": {
            "under_1": sum(1 for a in ages if a < 1),
            "1_to_3": sum(1 for a in ages if 1 <= a <= 3),
            "over_3": sum(1 for a in ages if a > 3),
            "no_price": n - len(ages),
            "newest_minutes": round(min(ages) * 60) if ages else None,
        },
    }


def started_figures(started: Iterable[Any]) -> dict[str, Any]:
    """L2: what «Ya empezaron hoy» holds in the preview."""
    per_fixture = Counter(_get(s, "fixture_id") for s in started)
    return {"candidates": sum(per_fixture.values()), "fixtures": len(per_fixture),
            "max_per_fixture": max(per_fixture.values(), default=0)}


def bogota_day(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(BOG).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def share(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "-"


def collect(conn: psycopg.Connection[Any], *, hours: int, now: datetime) -> dict[str, Any]:
    from fbi.api.services import product, records

    out: dict[str, Any] = {"at": now.isoformat(), "hours": hours}
    out["totals"] = {k: int(v) for k, v in (conn.execute(TOTALS_SQL).fetchone() or {}).items()}
    board = product.picks_board(conn, include_shadow=True, competition_id=None, market=None, min_odds=None,
                                max_odds=None, hours=hours, at=now)
    out["board"] = board_figures(board.data.picks if board.data else [], now)
    out["started"] = started_figures(product.started_board(conn, include_shadow=True, at=now).data or [])
    start, end = bogota_day(now)
    daily = records.daily_board(conn, day=None, include_shadow=True, at=now)
    the_set = daily.data.set if daily.data else None
    items = the_set.items if the_set else []
    out["daily_page"] = {"rule": the_set.rule_version if the_set else None, "items": len(items),
                         "statuses": dict(Counter(str(i.status) for i in items))}
    out["intelligence_day"] = {
        "by_state": {r["state"]: r["n"] for r in conn.execute(INTEL_DAY_SQL, {"start": start, "end": end})},
        "day_set": {r["rule_version"]: r["n"] for r in conn.execute(INTEL_SET_SQL, {"day": start.date()})},
    }
    return out


def report(f: Mapping[str, Any]) -> None:
    t, b, s = f["totals"], f["board"], f["started"]
    print(f"Línea base de PICKS · {f['at']} · ventana {f['hours']} h (vista previa del dueño)\n")
    print(f"Motor: {t['prices_evaluated']:,} precios evaluados · {t['picks']:,} picks en sombra · "
          f"{t['qualified']:,} calificados · {t['published']:,} publicados · {t['settled']:,} liquidados")
    n = b["cards"]
    print(f"\nTablero: {n:,} tarjetas de {b['fixtures']:,} partidos")
    print(f"  S1 fuera de la regla ahora: {b['outside_rule_now']:,} ({share(b['outside_rule_now'], n)}) "
          f"{b['outside_rule_reasons']}")
    print(f"  S2 misma idea en otra línea: {b['repeated_on_another_line']:,} ({share(b['repeated_on_another_line'], n)});"
          f" por partido, mediana {b['cards_per_fixture_median']} y máximo {b['cards_per_fixture_max']}")
    print(f"  S3 por encima de 3,00: {b['above_3_00']:,} ({share(b['above_3_00'], n)})")
    goals = b["goals_under"] + b["goals_over"]
    btts = b["btts_no"] + b["btts_yes"]
    print(f"  C4 goles: {b['goals_under']:,} menos de / {b['goals_over']:,} más de ({share(b['goals_under'], goals)});"
          f" ambos marcan: {b['btts_no']:,} no / {b['btts_yes']:,} sí ({share(b['btts_no'], btts)})")
    a = b["price_age_hours"]
    print(f"  C5 edad del precio: <1 h {a['under_1']:,} · 1-3 h {a['1_to_3']:,} · >3 h {a['over_3']:,} "
          f"({share(a['over_3'], n)}) · sin precio {a['no_price']:,} · el más nuevo hace {a['newest_minutes']} min")
    print(f"\nYa empezaron (L2): {s['candidates']:,} candidatos de {s['fixtures']:,} partidos; "
          f"hasta {s['max_per_fixture']} en uno")
    d, i = f["daily_page"], f["intelligence_day"]
    print(f"\nD1 picks del día de la página ({d['rule']}): {d['items']} {d['statuses']}")
    print(f"   Intelligence, último estado de cada selección del día: {i['by_state']}; su set: {i['day_set']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=24, help="the board's window (default 24)")
    parser.add_argument("--json", action="store_true", help="print the figures as JSON")
    args = parser.parse_args(argv)
    from fbi.core.clock import now as clock_now

    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY, row_factory=dict_row) as conn:
        figures = collect(conn, hours=args.hours, now=clock_now())
    if args.json:
        print(json.dumps(figures, ensure_ascii=False, indent=2, default=str))
    else:
        report(figures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
