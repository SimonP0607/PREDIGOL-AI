"""The table between Cuotas and the match's «Mercados» (plan Cuotas, phase 6: UX-073).

``web/src/product/match/marketLinks.json`` says, for a market of the explorer at a period, which market of the match's
catalogue it is (the address of «Abrir partido» carries it). It is made from the taxonomy: this test rebuilds it and a
difference fails, so a new type in ``tax-v3`` or in the catalogue cannot leave the web with a stale table.
"""

from __future__ import annotations

import json
from pathlib import Path

from fbi.odds.book_markets import market_key as explorer_key
from fbi.odds.book_taxonomy import SPECS
from fbi.odds.quote_current import CATALOG_FAMILIES, MARKET_CODES, market_key

TABLE = Path(__file__).resolve().parents[3] / "web/src/product/match/marketLinks.json"


def expected() -> list[dict[str, str]]:
    links: dict[tuple[str, str], dict[str, str]] = {}
    for s in SPECS:
        if not s.visible or s.family not in CATALOG_FAMILIES or s.bet_id not in MARKET_CODES:
            continue
        value = {"category": s.family, "catalog": market_key(s.bet_id, s.period, s.subject)}
        key = (explorer_key(s), s.period)
        assert links.setdefault(key, value) == value, f"{key} names two catalogue markets"
    rows = [{"key": k, "period": p, **v} for (k, p), v in links.items()]
    rows.sort(key=lambda r: (CATALOG_FAMILIES.index(r["category"]), r["key"], r["period"]))
    return rows


def test_the_web_table_is_the_one_the_taxonomy_gives() -> None:
    assert json.loads(TABLE.read_text(encoding="utf-8"))["links"] == expected()


def test_a_catalogue_market_has_one_explorer_market() -> None:
    rows = expected()
    assert len({r["catalog"] for r in rows}) == len(rows)
