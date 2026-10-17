"""The API-Football endpoint matrix: what PrediGol takes, keeps and uses from each endpoint, and what each is worth.

    python -m scripts.endpoint_matrix > docs/owner/API_FOOTBALL_ENDPOINT_MATRIX.md

Generated from ``fbi.providers.api_football.integration`` (what we do) and ``.value`` (what it is worth); a unit
test keeps both complete against the documented endpoints. 0 provider requests.
"""

from __future__ import annotations

from collections import Counter

from fbi.providers.api_football.integration import USES
from fbi.providers.api_football.value import VALUES

INGESTED = {"FULL": "Sí", "PARTIAL": "Parcial", "COVERED": "Sí, vía /fixtures?ids", "MISSING": "No", "WRONG": "Mal"}


def matrix() -> str:
    lines = ["# API-Football v3 - matriz de endpoints", "",
             "Generada por `python -m scripts.endpoint_matrix` desde `fbi.providers.api_football.integration` (qué "
             "hacemos) y `.value` (cuánto vale). \"Guardamos todo\" = la respuesta completa queda en RAW "
             "(gzip + índice), así que un campo no normalizado hoy se recupera después sin pedir de nuevo.", "",
             "| Endpoint | Ya ingerimos | Guardamos todo | Usamos | Valor potencial | Clase | Prioridad | Acción |",
             "|---|---|---|---|---|---|---|---|"]
    for endpoint, use in USES.items():
        value = VALUES[endpoint]
        stored = "Sí (RAW)" if use.status in ("FULL", "PARTIAL", "COVERED") else "No"
        if use.status == "COVERED":
            stored = "Sí (RAW de /fixtures?ids)"
        read = "; ".join(use.read_by) if use.read_by else "-"
        lines.append(f"| `{endpoint}` | {INGESTED[use.status]} | {stored} | {read} | {value.potential} | "
                     f"{value.klass} | {value.priority} | {value.action or '-'} |")
    counts = Counter(v.klass for v in VALUES.values())
    status = Counter(u.status for u in USES.values())
    lines += ["", f"Endpoints revisados: {len(USES)}. Integración: " + ", ".join(f"{k} {n}" for k, n in
              sorted(status.items())) + ". Clases: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())) + "."]
    return "\n".join(lines) + "\n"


def main() -> int:
    print(matrix(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
