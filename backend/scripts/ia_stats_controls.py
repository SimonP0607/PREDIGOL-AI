"""PrediGol Intelligence - RP-6.4: the report of the controls of the statistical facts over the real documents.

    python -m scripts.ia_stats_controls [--min-sample 8] [--replay-days 30] [--json] [--out DIR]

What the three controls (cut-off, stale document, small sample) say about the teams that play in the next days, and the replay of the past
days that must show ZERO facts with data after the cut-off. Read only: the connection refuses writes; nothing here is read by a decision, a
forecast or a page. Exit 0, 2 when the database cannot be read, 1 when the replay found a leak.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from fbi.stats import controls_report

OK = 0
LEAK = 1
CANNOT = 2


def render(doc: dict[str, object]) -> str:
    up, rp = doc["upcoming"], doc["replay"]
    assert isinstance(up, dict) and isinstance(rp, dict)
    return "\n".join([
        f"Controles de los hechos estadísticos {doc['version']} · mínimo de muestra {doc['min_sample']} · corte {doc['as_of']}",
        f"próximos {up['days']} días: {up['teams']} equipos · documentos {up['status']} · controles {up['controls']} · documentos con fuga {up['documents_with_a_leak']}",
        f"repetición de {rp['days']} días: {rp['moments']} momentos · {rp['status']} · rechazados por posteriores al corte "
        f"{rp['refused_after_cutoff']} · HECHOS CON FUGA {rp['facts_with_a_leak']}",
        str(rp["nota"])])


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--min-sample", type=int, default=8)
    ap.add_argument("--replay-days", type=int, default=30)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--out", type=Path, default=None, help="folder where the dated report is written")
    ap.add_argument("--dsn", default=None)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.min_sample <= 0 or args.replay_days <= 0:
        ap.error("--min-sample and --replay-days must be positive")
    from fbi.core.config import settings as platform

    now = datetime.now(UTC)
    try:
        with psycopg.connect(args.dsn or platform.database.psycopg_url,
                             options="-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000") as conn:
            doc = controls_report.report(conn, at=now, min_sample=args.min_sample, replay_days=args.replay_days)
    except psycopg.Error as exc:
        sys.stderr.write(f"cannot read: {exc}\n")
        return CANNOT
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"stats_controls_{now:%Y%m%d}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.write((json.dumps(doc, indent=1, ensure_ascii=False) if args.as_json else render(doc)) + "\n")
    return LEAK if doc["replay"]["facts_with_a_leak"] else OK


if __name__ == "__main__":
    raise SystemExit(main())
