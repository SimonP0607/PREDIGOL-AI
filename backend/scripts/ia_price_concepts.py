"""The concepts of price of the coming matches, as C-14 carries them (RP-10.1, ``price-glossary-v1``). Reading only: it writes nothing.

    python -m scripts.ia_price_concepts                 # the next 20 matches with prices: which concepts travel and whether they agree
    python -m scripts.ia_price_concepts --matches 30 --json

The plan's acceptance for the piece: the ten concepts present and coherent in 20 matches by the private route. Two of the ten cannot be: the validated
probability of PrediGol does not exist yet (no figure passed its gates) and the publication odds belong to a decision, not to the board of prices; the report
says so and counts the other eight. ``--dsn`` overrides the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg

from fbi.market import price_glossary as pg

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=120000"
UPCOMING_SQL = """
SELECT f.id FROM core.fixtures f WHERE f.kickoff_at > %(at)s AND f.status_group = 'scheduled'
   AND EXISTS (SELECT 1 FROM market.odds_asks a WHERE a.provider_fixture_id = f.provider_fixture_id)
 ORDER BY f.kickoff_at, f.id LIMIT %(n)s
"""
NOT_PRODUCED: frozenset[str] = frozenset(c.key for c in pg.CONCEPTS if c.contract_field is None)


def report(answers: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The coverage and the incoherences of the concepts over the private answers (as dicts), one per match."""
    carried: Counter[str] = Counter()
    problems: Counter[str] = Counter()
    selections = matches_with_all = 0
    possible = {c.key for c in pg.CONCEPTS} - NOT_PRODUCED
    for answer in answers:
        seen: set[str] = set()
        for market in (answer.get("markets") or {}).get("items", []):
            for sel in market["selections"]:
                selections += 1
                found = pg.present(sel, market)
                seen |= found
                carried.update(found)
                problems.update(pg.problems(sel))
        matches_with_all += int(possible <= seen)
    return {"version": pg.VERSION, "matches": len(answers), "selections": selections, "concepts_in_glossary": len(pg.CONCEPTS),
            "not_produced_by_the_board": sorted(NOT_PRODUCED), "carried": dict(sorted(carried.items())),
            "matches_with_all_producible": matches_with_all, "incoherences": dict(sorted(problems.items())),
            "coherent": not problems}


def lines(doc: dict[str, Any]) -> list[str]:
    out = [f"Conceptos de precio ({doc['version']}): {doc['matches']} partidos, {doc['selections']} selecciones; con los ocho conceptos que produce el "
           f"tablero en todos: {doc['matches_with_all_producible']} partidos",
           f"Sin campo en el tablero (no los produce): {', '.join(doc['not_produced_by_the_board'])}"]
    out += [f"  {k}: en {v} selecciones" for k, v in doc["carried"].items()]
    out.append("Incoherencias: " + ("ninguna" if doc["coherent"] else "; ".join(f"{k} ({v})" for k, v in doc["incoherences"].items())))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_price_concepts", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--matches", type=int, default=20)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.matches < 1:
        ap.error("--matches must be at least 1")
    from fbi.api.services import market_probs
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        ids = [int(r[0]) for r in conn.execute(UPCOMING_SQL, {"at": datetime.now(UTC), "n": args.matches}).fetchall()]
        answers = [market_probs.build(conn, i).model_dump(mode="json") for i in ids]
    doc = report(answers)
    sys.stdout.write((json.dumps(doc, indent=1, ensure_ascii=False) if args.as_json else "\n".join(lines(doc))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
