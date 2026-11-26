"""RP-0.3 - who reads and who writes each table and version that the plan marks to keep, consolidate or retire.

    python -m scripts.consumers_map            # rewrites docs/intelligence/CONSUMIDORES.md and consumidores.json
    python -m scripts.consumers_map --check    # exits 1 when either is out of date, or a retire/consolidate candidate has a NEW consumer

It walks the code (``backend/src``, ``backend/apps``, ``backend/scripts``, ``backend/tests``, ``web/src``) and looks for each candidate by the name of its table or the
name of its version. A hit is classified by WHERE it is (a worker job, an API route, the web, a script, a test, another module) and, for a
table, by HOW (it writes when the file has ``INSERT INTO`` / ``UPDATE`` / ``DELETE FROM`` of the table; otherwise it reads or mentions it).
It reads files and writes two files; it never touches a database and removes nothing.

It finds NAMES, not call graphs: a module that reaches a table through a helper that does not spell its name is not seen. The report says so
and the guard (a new consumer of something marked to retire fails the test) is therefore a floor, not a proof of absence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[2]
BACKEND: Final = ROOT / "backend"
OUT_MD: Final = ROOT / "docs" / "intelligence" / "CONSUMIDORES.md"
OUT_JSON: Final = ROOT / "docs" / "intelligence" / "consumidores.json"
SCAN: Final = (BACKEND / "src", BACKEND / "apps", BACKEND / "scripts", BACKEND / "tests", ROOT / "web" / "src")
SUFFIXES: Final = (".py", ".ts", ".tsx", ".sql")
SKIP_PARTS: Final = frozenset({"__pycache__", "node_modules", "migrations"})
SELF: Final = frozenset({"consumers_map.py", "test_consumers_map.py"})
VERSION: Final = "consumers-map-v1"

KEEP, CONSOLIDATE, RETIRE = "conservar", "consolidar", "retirar"


@dataclass(frozen=True, slots=True)
class Candidate:
    key: str
    label: str
    destiny: str
    patterns: tuple[str, ...]
    """Regular expressions of the names that identify it (a table, a version, a switch)."""
    tables: tuple[str, ...] = ()
    """Tables among the names: a file that writes one of them is reported as a writer."""


CANDIDATES: Final[tuple[Candidate, ...]] = (
    Candidate("decision_v1", "decision-v1 (referencia estable)", KEEP, (r"decision-v1",)),
    Candidate("decision_v2", "decision-v2 en sombra", CONSOLIDATE, (r"decision-v2", r"intel\.decisions_v2", r"decision_v2_moments"),
              ("intel.decisions_v2", "intel.decision_v2_moments")),
    Candidate("decision_families", "decisiones de familias (decision-fam-v1)", CONSOLIDATE,
              (r"decision-fam-v1", r"family_postmortems", r"family_memory"), ("intel.family_postmortems", "intel.family_memory")),
    Candidate("eval_cycle", "ciclo de evaluación E1 a E4", CONSOLIDATE, (r"intel\.eval_runs", r"intel\.eval_verdicts", r"eval-cycle"),
              ("intel.eval_runs", "intel.eval_verdicts")),
    Candidate("lifecycle", "ciclo de estados de la selección", CONSOLIDATE, (r"intel\.selection_lifecycle",), ("intel.selection_lifecycle",)),
    Candidate("forecast_v1", "forecast-v1 (cifra por modelo)", CONSOLIDATE, (r"forecast-v1", r"models\.match_forecasts"),
              ("models.match_forecasts",)),
    Candidate("forecast_v2", "forecast-v2 (cifra única)", KEEP, (r"forecast-v2", r"single_figure"), ()),
    Candidate("news_items", "circuito de noticias: news.items", CONSOLIDATE, (r"news\.items", r"news\.stories"), ("news.items", "news.stories")),
    Candidate("evidence", "almacén de evidencia: ai.evidence", KEEP, (r"ai\.evidence",), ("ai.evidence",)),
    Candidate("user_narrative", "texto de los lectores (user-narrative-v3)", CONSOLIDATE, (r"user-narrative-v3",)),
    Candidate("brief_v8", "resumen del partido (brief-v8)", CONSOLIDATE, (r"brief-v8",)),
    Candidate("chronicle_v4", "crónica única (chronicle-v4)", KEEP, (r"chronicle-v4", r"ai\.chronicles"), ("ai.chronicles",)),
    Candidate("extract_v1", "extractor de investigación v1", CONSOLIDATE, (r"extract-v1",)),
    Candidate("extract_v3", "investigación v2 (extract-v3)", CONSOLIDATE, (r"extract-v3", r"entity_research")),
    Candidate("extract_v2", "extractor nuevo en cuarentena (extract-v2)", CONSOLIDATE, (r"extract-v2", r"extract_v2")),
    Candidate("unified_research", "investigación unificada", CONSOLIDATE, (r"unified_research", r"FBI_AI_RESEARCH_UNIFIED")),
    Candidate("haiku_arm", "brazo de comparación multiagente ma-v1-h", RETIRE, (r"ma-v1-h",)),
    Candidate("shadow_reports", "informe diario ai.shadow_reports (filas not_configured)", RETIRE, (r"ai\.shadow_reports",),
              ("ai.shadow_reports",)),
    Candidate("pick_reviews", "revisiones del modelo de lenguaje sobre candidatos", RETIRE, (r"ai\.pick_reviews",), ("ai.pick_reviews",)),
    Candidate("hgb", "modelos experimentales hgb y hgb_market", RETIRE, (r"\bhgb_market\b", r"\bhgb\b")),
)

WRITE_VERBS = r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)"


def files() -> Iterable[Path]:
    for base in SCAN:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in SUFFIXES and not (set(p.parts) & SKIP_PARTS) and p.name not in SELF:
                yield p


def classify(path: Path) -> str:
    """Where the file lives: worker job, API route, web, script, test or another module."""
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith("web/"):
        return "web"
    if rel.startswith("backend/apps/worker/"):
        return "trabajo"
    if rel.startswith("backend/tests/"):
        return "prueba"
    if rel.startswith("backend/scripts/"):
        return "script"
    if "/shadowjobs/" in rel or rel.endswith("_job.py"):
        return "trabajo"
    if "/api/" in rel:
        return "ruta"
    return "módulo"


def package(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    parts = rel.split("/")
    if rel.startswith("backend/src/fbi/") and len(parts) > 4:
        return parts[3]
    return parts[1] if parts[0] == "backend" and len(parts) > 2 else parts[0]


def kind(text: str, tables: tuple[str, ...]) -> str:
    """``escribe`` when the text spells an INSERT/UPDATE/DELETE of one of the candidate's tables; otherwise ``lee o cita``."""
    for t in tables:
        if re.search(WRITE_VERBS + r"\s+" + re.escape(t) + r"\b", text, re.IGNORECASE):
            return "escribe"
    return "lee o cita"


def scan(candidates: Iterable[Candidate] = CANDIDATES, paths: Iterable[Path] | None = None) -> dict[str, list[dict[str, str]]]:
    """``{candidate: [{path, package, class, kind}]}``, sorted by path. Only files that name the candidate."""
    cands = list(candidates)
    compiled = {c.key: [re.compile(p) for p in c.patterns] for c in cands}
    out: dict[str, list[dict[str, str]]] = {c.key: [] for c in cands}
    for p in paths if paths is not None else files():
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for c in cands:
            if any(rx.search(text) for rx in compiled[c.key]):
                out[c.key].append({"path": p.relative_to(ROOT).as_posix(), "package": package(p), "class": classify(p),
                                   "kind": kind(text, c.tables)})
    return out


def summarize(found: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    cands = {c.key: c for c in CANDIDATES}
    res: dict[str, Any] = {}
    for key, rows in found.items():
        non_test = [r for r in rows if r["class"] != "prueba"]
        res[key] = {
            "etiqueta": cands[key].label,
            "destino": cands[key].destiny,
            "archivos": len(rows),
            "sin_pruebas": len(non_test),
            "por_clase": {k: sum(1 for r in rows if r["class"] == k) for k in sorted({r["class"] for r in rows})},
            "escriben": sorted(r["path"] for r in rows if r["kind"] == "escribe" and r["class"] != "prueba"),
            "paquetes": {k: sum(1 for r in non_test if r["package"] == k) for k in sorted({r["package"] for r in non_test})},
            "consumidores": sorted(r["path"] for r in non_test),
        }
    return res


def document(found: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    return {"version": VERSION, "candidatos": summarize(found)}


def render(doc: dict[str, Any]) -> str:
    lines = [
        "# Mapa de consumidores (RP-0.3)",
        "",
        "<!-- Generado por `python -m scripts.consumers_map` desde el código de main. No lo edites a mano. -->",
        "",
        "Quién lee o escribe cada tabla y cada versión que el plan conserva, consolida o retira. Encuentra **nombres** en el código (de tabla, "
        "de versión, de interruptor); no sigue llamadas, así que un módulo que llega a una tabla por una función que no escribe su nombre "
        "no aparece. Por eso la guarda de la prueba (un consumidor nuevo de algo marcado para retirar o consolidar la rompe) es un suelo, "
        "no una prueba de ausencia. Los archivos de prueba se cuentan aparte y no cuentan como consumidores.",
        "",
        "| Candidato | Destino | Archivos | Sin pruebas | Escriben | Rutas | Trabajos | Web | Scripts |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, c in doc["candidatos"].items():
        k = c["por_clase"]
        lines.append(f"| {c['etiqueta']} (`{key}`) | {c['destino']} | {c['archivos']} | {c['sin_pruebas']} | {len(c['escriben'])} | "
                     f"{k.get('ruta', 0)} | {k.get('trabajo', 0)} | {k.get('web', 0)} | {k.get('script', 0)} |")
    for key, c in doc["candidatos"].items():
        lines += ["", f"## {c['etiqueta']} (`{key}`) — {c['destino']}", ""]
        if not c["sin_pruebas"]:
            lines += ["Ningún consumidor fuera de las pruebas.", ""]
            continue
        lines.append("Paquetes: " + ", ".join(f"`{p}` ({n})" for p, n in c["paquetes"].items()) + ".")
        lines.append("")
        if c["escriben"]:
            lines.append("Escriben: " + ", ".join(f"`{p}`" for p in c["escriben"]) + ".")
        else:
            lines.append("Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).")
    lines.append("")
    return "\n".join(lines)


def new_consumers(current: dict[str, Any], frozen: dict[str, Any]) -> dict[str, list[str]]:
    """Files that now name a candidate marked to consolidate or retire and did not when the map was frozen."""
    out: dict[str, list[str]] = {}
    for key, c in current["candidatos"].items():
        if c["destino"] == KEEP:
            continue
        before = set(frozen.get("candidatos", {}).get(key, {}).get("consumidores", []))
        added = sorted(set(c["consumidores"]) - before)
        if added:
            out[key] = added
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="consumers_map", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    doc = document(scan())
    md = render(doc)
    js = json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if args.check:
        added = new_consumers(doc, json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else {})
        same = OUT_MD.exists() and OUT_MD.read_text(encoding="utf-8") == md and OUT_JSON.exists() and OUT_JSON.read_text() == js
        if added:
            print(f"new consumers of candidates to consolidate or retire: {added}", file=sys.stderr)
        print("map is current" if same else "map is out of date: run python -m scripts.consumers_map")
        return 0 if same and not added else 1
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_JSON.write_text(js, encoding="utf-8")
    print(f"written {OUT_MD.name} and {OUT_JSON.name} ({len(doc['candidatos'])} candidates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
