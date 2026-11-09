"""Row by row: is it the same probability for the same selection? (plan PICKS, F3, test «Probabilidad calibrada y coherente»).

    python -m scripts.compare_probabilities               # read-only; the next 24 hours, now
    python -m scripts.compare_probabilities --hours 72 --top 30
    python -m scripts.compare_probabilities --json

For every selection (match, market, side, line) in the window it puts side by side the numbers the product shows for it:

* ``board_raw``     the pick engine's own probability, what the Picks board showed before F3 (``picks.picks.p_calibrated`` holds the RAW
                    one, the column's name notwithstanding);
* ``board_switch``  what the Picks board shows with ``FBI_PICKS_SOURCE=intelligence`` (``picks_decision.attach``: the card's ``p_model``);
* ``intel``         PrediGol Intelligence's newest calibrated probability (``decision-v1``, ``p_cal``) at its last checkpoint;
* ``forecast``      the Match Center's forecast (``forecast-v1``), the newest set known by now.

and measures the gaps, in percentage points, for each pair. The acceptance test of the plan is ONE reference for the same selection and
the same moment: 0 gaps above 0.5 points between what a reader sees on Picks and in the Match Center. ``verdict`` says whether it holds.
It also reports which checkpoint each Intelligence reading comes from and how old it is (the single moment of reference), and lists the
``--top`` widest gaps so a human can look at them.

It reads through a connection the server keeps READ ONLY, with a two-minute statement timeout, calls no provider and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings

READ_ONLY: Final = "-c default_transaction_read_only=on -c statement_timeout=120000 -c TimeZone=UTC"
TOLERANCE_PP: Final = Decimal("0.5")
"""The plan's criterion: no gap above half a percentage point for the same selection and the same moment."""
PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("board_raw", "intel"),
    ("board_switch", "intel"),
    ("forecast", "intel"),
    ("forecast", "board_raw"),
    ("forecast", "board_switch"),
)

FORECAST_SQL = """
WITH last AS (
    SELECT fixture_id, market_key, line, max(known_at) AS k
      FROM models.match_forecasts
     WHERE fixture_id = ANY(%(fixtures)s) AND version = %(version)s AND known_at <= %(now)s
     GROUP BY 1, 2, 3
)
SELECT x.fixture_id, x.market_key, x.selection, x.line, x.p, x.known_at, x.calibration
  FROM models.match_forecasts x
  JOIN last l ON l.fixture_id = x.fixture_id AND l.market_key = x.market_key AND l.line = x.line AND l.k = x.known_at
 WHERE x.version = %(version)s
"""
FORECAST_VERSION: Final = "forecast-v1"

Key = tuple[int, str, str, Decimal]


def key_of(r: Mapping[str, Any]) -> Key:
    return (int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(str(r["line"])))


def _pp(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b) * 100


def gaps(table: Mapping[Key, Mapping[str, Decimal | None]], left: str, right: str) -> list[tuple[Key, Decimal]]:
    """The gap in points for every selection that has both numbers, widest first."""
    out = [(k, _pp(v[left], v[right])) for k, v in table.items() if v.get(left) is not None and v.get(right) is not None]  # type: ignore[arg-type]
    out.sort(key=lambda kv: kv[1], reverse=True)
    return out


def summarize(found: Sequence[tuple[Key, Decimal]], *, tolerance: Decimal = TOLERANCE_PP) -> dict[str, Any]:
    """How wide the gaps of a pair are: how many selections, the median, the 90th percentile and the widest (in points)."""
    values = sorted(float(g) for _, g in found)
    n = len(values)
    over = sum(1 for _, g in found if g > tolerance)
    return {
        "selections": n,
        "median_pp": round(statistics.median(values), 3) if n else None,
        "p90_pp": round(values[min(n - 1, int(n * 0.9))], 3) if n else None,
        "max_pp": round(values[-1], 3) if n else None,
        "over_tolerance": over,
        "share_over_tolerance": round(over / n, 4) if n else None,
    }


def build_table(board: Iterable[Mapping[str, Any]], decisions: Iterable[Mapping[str, Any]],
                forecasts: Iterable[Mapping[str, Any]]) -> dict[Key, dict[str, Decimal | None]]:
    """One row per selection of the board, with the four numbers it can be read in (None where a source has none for it).

    ``board`` are the board's candidate rows AFTER ``picks_decision.attach``: ``p_model`` is the calibrated probability where
    Intelligence has one, and ``intel_p_raw`` is the engine's own."""
    from fbi.api.services.picks_decision import RAW_MARK

    by_decision = {key_of(d): d for d in decisions}
    by_forecast = {key_of(f): f for f in forecasts}
    table: dict[Key, dict[str, Decimal | None]] = {}
    for r in board:
        k = key_of(r)
        if k in table:  # several versions of the model may price a selection: the first is the board's (ordered by id)
            continue
        d = by_decision.get(k)
        f = by_forecast.get(k)
        table[k] = {
            "board_raw": Decimal(str(r[RAW_MARK])),
            "board_switch": Decimal(str(r["p_model"])),
            "intel": None if d is None or d["p_cal"] is None else Decimal(str(d["p_cal"])),
            "forecast": None if f is None else Decimal(str(f["p"])),
        }
    return table


def checkpoint_figures(decisions: Iterable[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    """The single moment of reference: which checkpoint each Intelligence reading comes from and how old it is."""
    ds = [d for d in decisions if d.get("p_cal") is not None]
    ages = sorted((now - d["known_at"]).total_seconds() / 3600 for d in ds)
    return {
        "readings": len(ds),
        "by_checkpoint": dict(Counter(str(d["checkpoint"]) for d in ds).most_common()),
        "age_hours_median": round(statistics.median(ages), 2) if ages else None,
        "age_hours_max": round(ages[-1], 2) if ages else None,
    }


def worst(table: Mapping[Key, Mapping[str, Decimal | None]], *, top: int) -> list[dict[str, Any]]:
    """The widest gaps between what a reader sees on Picks and in the Match Center, with every number of the selection."""
    found = gaps(table, "forecast", "board_switch")
    rows = []
    for k, g in found[:top]:
        fixture, market, selection, line = k
        rows.append({"fixture_id": fixture, "market": market, "selection": selection, "line": str(line), "gap_pp": round(float(g), 3),
                     **{name: None if v is None else round(float(v), 4) for name, v in table[k].items()}})
    return rows


def verdict(summaries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Whether the criterion holds: the switch makes the board agree with Intelligence AND with the Match Center."""
    board = summaries["board_switch~intel"]
    match_center = summaries["forecast~board_switch"]
    comparable = bool(board["selections"]) and bool(match_center["selections"])
    holds = comparable and board["over_tolerance"] == 0 and match_center["over_tolerance"] == 0
    return {"tolerance_pp": float(TOLERANCE_PP), "comparable": comparable, "holds": holds,
            "board_vs_intelligence_over": board["over_tolerance"], "match_center_vs_board_over": match_center["over_tolerance"]}


def collect(conn: psycopg.Connection[Any], *, hours: int, top: int, now: datetime) -> dict[str, Any]:
    from fbi.api.repositories import fetch_all
    from fbi.api.repositories import product as repo
    from fbi.api.services import picks_decision
    from fbi.api.services.product import CONSENSUS_LOOKBACK

    rows = repo.pick_candidates(conn, now=now, until=now + timedelta(hours=hours), since=now - CONSENSUS_LOOKBACK, include_shadow=True)
    fixtures = sorted({int(r["fixture_id"]) for r in rows})
    decisions = repo.intel_decisions(conn, fixture_ids=fixtures, now=now)
    attached = picks_decision.attach(list(rows), list(decisions))
    forecasts = fetch_all(conn, FORECAST_SQL, {"fixtures": fixtures or [0], "version": FORECAST_VERSION, "now": now})
    table = build_table(attached, decisions, forecasts)
    summaries = {f"{a}~{b}": summarize(gaps(table, a, b)) for a, b in PAIRS}
    return {
        "at": now.isoformat(), "hours": hours, "fixtures": len(fixtures), "selections": len(table),
        "with_intelligence": sum(1 for v in table.values() if v["intel"] is not None),
        "with_forecast": sum(1 for v in table.values() if v["forecast"] is not None),
        "pairs": summaries, "checkpoints": checkpoint_figures(decisions, now),
        "verdict": verdict(summaries), "widest": worst(table, top=top),
    }


def report(f: Mapping[str, Any]) -> None:
    print(f"Probabilidad de la misma selección, fila a fila · {f['at']} · ventana {f['hours']} h\n")
    print(f"{f['selections']:,} selecciones de {f['fixtures']:,} partidos · con lectura calibrada de Intelligence: {f['with_intelligence']:,} · "
          f"con pronóstico del Match Center: {f['with_forecast']:,}")
    names = {"board_raw": "tablero (cruda)", "board_switch": "tablero (con el interruptor)", "intel": "Intelligence (calibrada)",
             "forecast": "Match Center"}
    print("\nDiferencia en puntos entre dos lecturas de la misma selección:")
    for pair, s in f["pairs"].items():
        a, b = pair.split("~")
        if not s["selections"]:
            print(f"  {names[a]} / {names[b]}: sin selecciones comparables")
            continue
        print(f"  {names[a]} / {names[b]}: {s['selections']:,} selecciones · mediana {s['median_pp']} · p90 {s['p90_pp']} · "
              f"máximo {s['max_pp']} · por encima de {float(TOLERANCE_PP)} pp: {s['over_tolerance']:,} ({s['share_over_tolerance']:.1%})")
    c = f["checkpoints"]
    print(f"\nMomento de referencia de Intelligence: {c['readings']:,} lecturas · puntos de control {c['by_checkpoint']} · "
          f"edad mediana {c['age_hours_median']} h, máxima {c['age_hours_max']} h")
    v = f["verdict"]
    if not v["comparable"]:
        print("\nVEREDICTO: no hay selecciones comparables todavía (falta lectura de Intelligence o pronóstico).")
    else:
        word = "SE CUMPLE" if v["holds"] else "NO SE CUMPLE"
        print(f"\nVEREDICTO: {word} el criterio de 0 diferencias de más de {v['tolerance_pp']} pp "
              f"(tablero con interruptor vs Intelligence: {v['board_vs_intelligence_over']}; Match Center vs tablero: {v['match_center_vs_board_over']}).")
    if f["widest"]:
        print("\nLas diferencias más anchas entre el Match Center y el tablero con el interruptor:")
        for w in f["widest"]:
            print(f"  partido {w['fixture_id']} {w['market']} {w['selection']} {w['line']}: {w['gap_pp']} pp · "
                  f"cruda {w['board_raw']} · tablero {w['board_switch']} · Intelligence {w['intel']} · Match Center {w['forecast']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=24, help="the window of matches to compare (default 24)")
    parser.add_argument("--top", type=int, default=15, help="how many of the widest gaps to list (default 15)")
    parser.add_argument("--json", action="store_true", help="print the figures as JSON")
    args = parser.parse_args(argv)
    from fbi.core.clock import now as clock_now

    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY, row_factory=dict_row) as conn:
        figures = collect(conn, hours=args.hours, top=args.top, now=clock_now())
    if args.json:
        print(json.dumps(figures, ensure_ascii=False, indent=2, default=str))
    else:
        report(figures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
