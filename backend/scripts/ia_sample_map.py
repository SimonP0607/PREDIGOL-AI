"""The map of sample by family and competition and the level each parameter must live at (RP-3.1), recomputable and dated.

    python -m scripts.ia_sample_map                      # a summary
    python -m scripts.ia_sample_map --json               # the whole matrix
    python -m scripts.ia_sample_map --out reports/       # also writes reports/sample_map_<date>.json

Read-only (the connection refuses writes); one grouped query; nothing here is read by a decision, a forecast or a page. Exit 0, 2 when it
cannot run."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from fbi.stats import sample_map

OK = 0
CANNOT = 2


def render(doc: dict[str, object]) -> str:
    summary = doc["summary"]
    assert isinstance(summary, dict)
    lines = [f"Mapa de muestra {doc['version']} · ventana {doc['window_days']} días · mínimo {doc['min_matches']} partidos con el dato",
             f"competiciones seguidas: {summary['competitions']}"]
    levels = summary["levels"]
    assert isinstance(levels, dict)
    for fam, per in levels.items():
        lines.append(f"  {fam:<11} liga/competición {per['competition']:>4}   hereda del tipo {per['type']:>4}   solo global {per['global']:>4}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--window-days", type=int, default=sample_map.WINDOW_DAYS)
    ap.add_argument("--min-matches", type=int, default=sample_map.MIN_MATCHES)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--out", type=Path, default=None, help="folder where the dated matrix is written")
    ap.add_argument("--dsn", default=None)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.window_days <= 0 or args.min_matches <= 0:
        ap.error("--window-days and --min-matches must be positive")
    from fbi.core.config import settings as platform

    now = datetime.now(UTC)
    try:
        with psycopg.connect(args.dsn or platform.database.psycopg_url,
                             options="-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000") as conn:
            doc = sample_map.read(conn, at=now, window_days=args.window_days, minimum=args.min_matches)
    except psycopg.Error as exc:
        sys.stderr.write(f"cannot read: {exc}\n")
        return CANNOT
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"sample_map_{now:%Y%m%d}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.write((json.dumps(doc, indent=1, ensure_ascii=False) if args.as_json else render(doc)) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
