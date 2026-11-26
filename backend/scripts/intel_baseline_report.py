"""RP-0.1 - turns the output of ``intel_baseline.sh`` into the frozen baseline file.

    python -m scripts.intel_baseline_report run.txt --out ../docs/intelligence/baseline/baseline-v1.json \
        --code-version d5e61206 [--latency-manifest data/baselines/<folder>/manifest.json]

The input is text made of ``### section`` lines each followed by a CSV table (what ``intel_baseline.sh`` writes). The output is a
JSON document with one entry per section: its rows as parsed, and the sha256 of its CSV block. Two runs with the same cut give the
same hash for every section that is not marked live (the heartbeat of the worker cannot be bounded by a cut); the file records which
sections are live so the repeatability check leaves them out.

It reads text and writes one file; it never touches a database.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Final

DEFINITION_VERSION: Final = "intel-baseline-v1"

INDICATORS: Final[tuple[tuple[int, str, str], ...]] = (
    (1, "Predicción", "i01_i02_forecast_vs_market"),
    (2, "Predicción", "i01_i02_forecast_vs_market"),
    (3, "Calibración", "i03_calibration_by_family"),
    (4, "Por mercado", "i04_loss_vs_market_by_family"),
    (5, "Por competición", "i05_by_competition_level"),
    (6, "Coherencia", "i06_coherence"),
    (7, "Cierre", "i07_close_minutes"),
    (8, "Investigación", "i08_research_coverage_played"),
    (9, "Investigación", "i09_researched_before_match_day"),
    (10, "Hechos", "i10_facts_per_researched_match"),
    (11, "Hechos", "i11_unknown_tier_share"),
    (12, "Noticias", "i12_stories_with_own_text"),
    (13, "Texto", "i13_complete_texts"),
    (14, "Texto", "i14_unsupported_claims"),
    (15, "Coste", "i15_cost_per_analyzed_match"),
    (16, "Coste", "i16_cost_per_confirmed_fact"),
    (17, "Coste", "i17_review_share_of_spend"),
    (18, "Aprendizaje", "i18_hypotheses"),
    (19, "Aprendizaje", "i19_experiments_since_4_oct"),
    (20, "Operación", "i20_runs_by_status_7d"),
    (21, "Parlays", "i21_parlays_30d"),
    (22, "Operación", "i22_latency"),
)
"""The 22 indicators of section 23 of the plan: number, area, the section of the SQL that holds its figure."""

LIVE_SECTIONS: Final = frozenset({"run", "i20b_jobs_outside_ledger_live"})
"""Read state that a cut cannot bound; reported, left out of the repeatability check."""

NOISE: Final = frozenset({"BEGIN", "SET", "ROLLBACK", "COMMIT"})


def split_sections(text: str) -> dict[str, str]:
    """``### name`` blocks, in order. Lines psql prints about itself (BEGIN, SET, ``Null display ...``) are dropped."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            out[current] = []
            continue
        if current is None or line.strip() in NOISE or line.startswith("Null display"):
            continue
        out[current].append(line)
    return {name: "\n".join(lines).strip("\n") for name, lines in out.items()}


def parse_csv(block: str) -> list[dict[str, str]]:
    return [dict(r) for r in csv.DictReader(io.StringIO(block))] if block else []


def section_hash(block: str) -> str:
    return hashlib.sha256(block.encode("utf-8")).hexdigest()


def build(text: str, *, code_version: str, latency: dict[str, Any] | None = None) -> dict[str, Any]:
    """The baseline document. Raises ValueError when a section of one of the 22 indicators is missing or psql reported an error."""
    if "ERROR:" in text:
        raise ValueError("the run contains a psql ERROR; the baseline is not frozen")
    sections = split_sections(text)
    missing = sorted({s for _, _, s in INDICATORS if s not in sections and s != "i22_latency"} - set(sections))
    if missing:
        raise ValueError(f"sections missing from the run: {missing}")
    doc_sections: dict[str, Any] = {}
    for name, block in sections.items():
        doc_sections[name] = {"live": name in LIVE_SECTIONS, "sha256": section_hash(block), "rows": parse_csv(block)}
    if latency is not None:
        block = json.dumps(latency, sort_keys=True)
        doc_sections["i22_latency"] = {"live": True, "sha256": section_hash(block), "rows": [latency]}
    run = parse_csv(sections.get("run", ""))
    meta = parse_csv(sections.get("meta", ""))
    return {
        "definition_version": DEFINITION_VERSION,
        "code_version": code_version,
        "run": run[0] if run else {},
        "meta": meta[0] if meta else {},
        "indicators": [{"n": n, "area": area, "section": s} for n, area, s in INDICATORS],
        "sections": doc_sections,
    }


def repeatable(first: dict[str, Any], second: dict[str, Any]) -> list[str]:
    """Sections whose hash differs between two runs with the same cut, live sections excluded. Empty = same baseline."""
    diffs: list[str] = []
    for name, sec in first["sections"].items():
        other = second["sections"].get(name)
        if sec["live"] or (other and other["live"]):
            continue
        if other is None or other["sha256"] != sec["sha256"]:
            diffs.append(name)
    return diffs


def summarize_latency(manifest: dict[str, Any]) -> dict[str, Any]:
    """I22 from the manifest of ``baseline_snapshot``: median and p90 of the Intelligence routes, in milliseconds."""
    timings = {k: v for k, v in (manifest.get("timings_ms") or {}).items() if "intel" in k or "admin__ops" in k}
    values = sorted(timings.values())
    if not values:
        return {"routes": 0}
    return {
        "routes": len(values),
        "median_ms": values[len(values) // 2],
        "p90_ms": values[min(len(values) - 1, int(len(values) * 0.9))],
        "max_ms": values[-1],
        "slowest": sorted(timings, key=lambda k: -timings[k])[:5],
    }


PROSE: Final = """# Línea base de Intelligence (RP-0.1)

<!-- Generado por `python -m scripts.intel_baseline_report --doc` desde `docs/intelligence/baseline/baseline-v1.json`. No lo edites a mano. -->

Los 22 indicadores de la sección 23 del Plan Maestro, medidos en producción en solo lectura al aprobarse el plan, antes de
cambiar nada. Es el punto contra el que se mide toda mejora o empeoramiento posterior: ninguna pieza se da por buena con una comparación que no
use estas definiciones.

**Cómo se midió.** `backend/scripts/intel_baseline.sql` corre dentro de una transacción de solo lectura con límite de tiempo
(`intel_baseline.sh`); cada cifra está acotada por el corte (`cut_utc`), así que repetir la medición con el mismo corte da la misma huella
sha256 en cada sección (comprobado con dos ejecuciones; las secciones «vivas» —latido del trabajador— se dejan fuera de esa comprobación).
Las competiciones de la base fija son las seguidas y creadas antes del 24-nov-2026 (`base_before_utc`), para que las que se añadan después no
muevan la línea base.

**Qué no está medido, y por qué.** I6 (coherencia matemática) lo crea la pieza RP-2.2; I14 (afirmaciones sin apoyo) lo crea RP-7.4 con su muestra
de 50 textos; I22 (latencia) solo se mide con `baseline_snapshot` una vez desplegado este cambio. El indicador I9 cuenta todos los partidos de la base,
porque la lista de competiciones prioritarias (D2) se aplica después, en RP-5.4.

**Diferencias de definición con la auditoría.** No se reproducen al dígito las cifras de 1X2 de la auditoría (3.098 partidos, +0,0326 bruta,
+0,0075 mostrada) porque la consulta de entonces no se guardó; esta definición queda fijada y es la que se usará en adelante: 3.165 partidos,
+0,0378 bruta y +0,0113 mostrada.
"""

SHOW_ROWS: Final = 12
"""A section with more rows than this is summarised in the document (the JSON keeps all of them)."""


def render_markdown(doc: dict[str, Any]) -> str:
    """The readable baseline: the prose above and, per indicator, the rows of its section."""
    out = [PROSE, f"Versión de la definición: `{doc['definition_version']}`. Código: `{doc['code_version']}`. Migración: "
           f"`{doc['meta'].get('migration', '?')}`. Corte: `{doc['run'].get('cut_utc', '?')}`.", ""]
    for ind in doc["indicators"]:
        sec = doc["sections"].get(ind["section"])
        out += [f"## I{ind['n']} · {ind['area']} (`{ind['section']}`)", ""]
        rows = sec["rows"] if sec else []
        if not rows:
            out += ["Sin filas.", ""]
            continue
        cols = list(rows[0].keys())
        if len(rows) > SHOW_ROWS:
            out += [f"{len(rows)} filas (todas en el JSON); las primeras {SHOW_ROWS}:", ""]
        out += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        out += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows[:SHOW_ROWS]]
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="intel_baseline_report", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path, nargs="?")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--code-version")
    ap.add_argument("--doc", type=Path, help="renders this baseline JSON as the readable document and exits (no run text needed)")
    ap.add_argument("--latency-manifest", type=Path)
    ap.add_argument("--compare", type=Path, help="a second run text with the same cut: lists sections whose hash differs")
    args = ap.parse_args(argv)
    if args.doc:
        args.doc.with_suffix(".md").write_text(render_markdown(json.loads(args.doc.read_text())), encoding="utf-8")
        print(f"written {args.doc.with_suffix('.md')}")
        return 0
    if not (args.run and args.out and args.code_version):
        ap.error("run, --out and --code-version are required (or --doc)")
    latency = summarize_latency(json.loads(args.latency_manifest.read_text())) if args.latency_manifest else None
    doc = build(args.run.read_text(), code_version=args.code_version, latency=latency)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"written {args.out} ({len(doc['sections'])} sections)")
    if args.compare:
        other = build(args.compare.read_text(), code_version=args.code_version, latency=latency)
        diffs = repeatable(doc, other)
        print("repeatable: yes" if not diffs else f"repeatable: NO, differ: {diffs}")
        return 0 if not diffs else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
