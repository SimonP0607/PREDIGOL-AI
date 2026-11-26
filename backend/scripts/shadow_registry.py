"""RP-0.2 - the registry of the switches that run in shadow: ``docs/intelligence/sombras.json`` is the data, ``SOMBRAS.md`` is generated from it.

    python -m scripts.shadow_registry            # rewrites docs/intelligence/SOMBRAS.md
    python -m scripts.shadow_registry --check    # exits 1 when SOMBRAS.md is not what the data renders (CI runs it as a test)

One row per ``FBI_*`` switch that production holds in ``shadow``: what runs, where it writes, since when (the first row of its table, measured),
who reads it, which comparison would decide it, the numeric condition, who decides. A row that has no comparison or no condition SAYS so
(``definida`` false): the registry never invents a criterion; it shows which shadows still have none.

It reads two files and writes one; it never touches a database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[2]
DATA: Final = ROOT / "docs" / "intelligence" / "sombras.json"
DOC: Final = ROOT / "docs" / "intelligence" / "SOMBRAS.md"

FIELDS: Final = ("interruptor", "corre", "salida", "desde", "filas", "lee", "comparacion", "condicion", "decide", "definida")
"""Every row carries all of them; ``nota`` is optional."""


def load(path: Path = DATA) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def problems(doc: dict[str, Any]) -> list[str]:
    """What is wrong with the registry (empty: every row is complete)."""
    out: list[str] = []
    seen: set[str] = set()
    for row in doc.get("sombras", []):
        key = str(row.get("interruptor", "?"))
        if key in seen:
            out.append(f"{key}: repeated")
        seen.add(key)
        for f in FIELDS:
            v = row.get(f)
            if v is None or (isinstance(v, str) and not v.strip()):
                out.append(f"{key}: field {f!r} is empty")
        if not key.startswith("FBI_"):
            out.append(f"{key}: not an FBI_ switch")
    return out


def render(doc: dict[str, Any]) -> str:
    rows = doc["sombras"]
    open_rows = [r for r in rows if not r["definida"]]
    lines = [
        "# Registro de sombras de Intelligence (RP-0.2)",
        "",
        "<!-- Generado por `python -m scripts.shadow_registry` desde `docs/intelligence/sombras.json`. No lo edites a mano. -->",
        "",
        f"Medido el {doc['medido_utc']}. {doc['origen_produccion']}.",
        "",
        f"**{len(rows)} interruptores en sombra; {len(rows) - len(open_rows)} con comparación y condición numérica definidas, "
        f"{len(open_rows)} sin ellas.** Una fila marcada «no» dice la verdad: hoy ningún criterio del código decide esa sombra, "
        "y no se inventa uno aquí. Cada criterio nuevo pasa por la aprobación previa de la decisión D7 antes de medir.",
        "",
        "| Interruptor | Qué corre | Dónde escribe | Desde | Filas | Quién lo lee | Comparación que lo decide | Condición | Quién decide | ¿Definida? |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cells = [r["interruptor"], r["corre"], r["salida"], r["desde"], r["filas"], r["lee"], r["comparacion"], r["condicion"],
                 r["decide"], "sí" if r["definida"] else "no"]
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    notes = [r for r in rows if r.get("nota")]
    if notes:
        lines += ["", "## Notas", ""]
        lines += [f"- `{r['interruptor']}`: {r['nota']}." if not str(r["nota"]).endswith(".") else f"- `{r['interruptor']}`: {r['nota']}"
                  for r in notes]
    lines += ["", "## Sombras sin comparación o condición definida", ""]
    lines += [f"- `{r['interruptor']}`" for r in open_rows]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shadow_registry", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    doc = load()
    bad = problems(doc)
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    text = render(doc)
    if args.check:
        same = DOC.exists() and DOC.read_text(encoding="utf-8") == text
        print("SOMBRAS.md is current" if same else "SOMBRAS.md is out of date: run python -m scripts.shadow_registry")
        return 0 if same else 1
    DOC.write_text(text, encoding="utf-8")
    print(f"written {DOC} ({len(doc['sombras'])} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
