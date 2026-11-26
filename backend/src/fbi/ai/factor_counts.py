"""How complete the facts of a window are under the one schema of a context fact (plan RP-4.1, ``context-fact-v1``): by kind, by category and by
attribute. Pure over the grouped rows ``value_sheet_readers.fact_rows`` reads; it decides and changes nothing.

Two groups are counted apart and never added together: the facts WRITTEN UNDER THE SCHEMA (``fact_schema`` set: the database refuses an incomplete one,
so they are complete by construction and the count says how many there are) and the facts written before (``fact_schema`` NULL: left as they are, and
counted by which of the seven attributes they happen to have, so that nobody reads a share of them as a failure of the schema). The acceptance of the
piece is about the first group: 100 % of the new facts complete, which ``complete_share`` states over the facts that DECLARE the schema and the
attributes they actually have.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Final

from fbi.ai import factor_schema

VERSION: Final = "context-fact-counts-v1"


def _has_all(row: Mapping[str, Any]) -> bool:
    """A grouped row has the attributes the database checks (source, date, entity, validity, side): the state always exists."""
    return bool(row["has_source"] and row["has_date"] and row["has_entity"] and row["has_validity"] and row["side"] is not None)


def report(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The counts of a window: new facts (by kind and category), the facts of before, and the share of the new ones that are complete."""
    new_kind: Counter[str] = Counter()
    new_category: Counter[str] = Counter()
    old_kind: Counter[str] = Counter()
    old_category: Counter[str] = Counter()
    new_total = new_complete = old_total = old_with_all = 0
    for r in rows:
        n = int(r["n"])
        category = factor_schema.category_of(r["status"], str(r["origin"]), r["source_tier"], r.get("certainty")) or "sin_categoria"
        if r["fact_schema"] is not None:
            new_total += n
            new_complete += n if _has_all(r) else 0
            new_kind[str(r["kind"])] += n
            new_category[category] += n
        else:
            old_total += n
            old_with_all += n if _has_all(r) else 0
            old_kind[str(r["kind"])] += n
            old_category[category] += n
    return {
        "version": VERSION, "schema": factor_schema.VERSION,
        "new": {"facts": new_total, "complete": new_complete, "complete_share": None if not new_total else new_complete / new_total,
                "by_kind": dict(sorted(new_kind.items())), "by_category": dict(sorted(new_category.items()))},
        "before": {"facts": old_total, "with_all_attributes": old_with_all,
                   "by_kind": dict(sorted(old_kind.items())), "by_category": dict(sorted(old_category.items()))},
        "new_kinds_seen": sorted(set(new_kind) & set(factor_schema.NEW_KINDS)),
        "new_kinds_missing": sorted(set(factor_schema.NEW_KINDS) - set(new_kind)),
    }


def lines(doc: Mapping[str, Any]) -> list[str]:
    """The report in Spanish."""
    new, old = doc["new"], doc["before"]
    share = "sin hechos nuevos" if new["complete_share"] is None else f"{new['complete_share']:.0%} completos"
    cats = ", ".join(f"{k} {v}" for k, v in new["by_category"].items()) or "ninguna"
    kinds = ", ".join(f"{k} {v}" for k, v in new["by_kind"].items()) or "ninguno"
    old_cats = ", ".join(f"{k} {v}" for k, v in old["by_category"].items()) or "ninguna"
    return [
        f"Hechos de contexto ({doc['schema']})",
        f"Escritos con el esquema único: {new['facts']} ({share}); por tipo: {kinds}; por categoría: {cats}",
        f"Escritos antes: {old['facts']} (con los atributos que revisa la base: {old['with_all_attributes']}); por categoría: {old_cats}",
        "Tipos nuevos sin ningún hecho: " + (", ".join(doc["new_kinds_missing"]) or "ninguno"),
    ]


__all__ = ["VERSION", "lines", "report"]
