"""What the model review would not have been asked if the rules' REJECT were respected (RP-12.2, ``review-prefilter-v1``). Reading only.

    python -m scripts.ia_review_replay                  # the last 30 days
    python -m scripts.ia_review_replay --days 14 --json

It counts the model reviews of the window whose selection the rules had already rejected (so the combined review was REJECT whatever the model
said), what they cost, the control the rule would keep reviewing and how many combined decisions skipping them would change (the criterion of the
plan: none). It switches nothing: ``FBI_AI_REVIEW_PREFILTER`` is the owner's, through the audited kit. ``--dsn`` overrides the database.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import psycopg

from fbi.ai import review_prefilter as rp

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_review_replay", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dsn", default=os.environ.get("FBI_DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://"))
    a = ap.parse_args(argv)
    if a.days < 1 or not a.dsn:
        print("usage: --days >= 1 and a database (--dsn or FBI_DATABASE_URL)", file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    with psycopg.connect(a.dsn, options=OPTIONS) as conn:
        out = rp.as_dict(rp.replay(rp.read(conn, since=now - timedelta(days=a.days), until=now), window_days=a.days))
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(f"Repetición de la revisión con modelo · {rp.VERSION} · {a.days} días · no cambia nada")
    print(f"  revisiones con modelo: {out['model_reviews']} (US$ {out['cost_usd']:.2f}); aprobadas por el modelo: {out['model_approvals']}")
    print(f"  que la regla habría omitido (reglas ya en REJECT, fuera del control): {out['would_skip']} (US$ {out['would_skip_cost_usd']:.2f}, "
          f"{out['share_of_cost']:.1%} del coste); control que sigue revisándose: {out['kept_as_control']}")
    print(f"  aprobaciones del modelo donde las reglas rechazaban: {out['model_approvals_where_rules_rejected']} · decisiones combinadas "
          f"que cambiarían: {out['combined_decisions_the_skip_would_change']}")
    return 0 if out["combined_decisions_the_skip_would_change"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
