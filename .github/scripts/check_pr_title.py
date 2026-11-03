#!/usr/bin/env python3
"""Valida título, rama y descripción de un PR según las convenciones de PrediGol.

Reglas: docs/proyecto/CONVENCIONES_GITHUB.md (código CI-005).

Entrada (variables de entorno, nunca interpoladas en la shell):
  PR_TITLE, PR_BRANCH, PR_BODY
Salida:
  - errores en pantalla (anotaciones ::error::) y código de salida 1 si hay alguno;
  - si GITHUB_OUTPUT existe, escribe `area=` y `tipo=` para etiquetar el PR.
"""

from __future__ import annotations

import os
import re
import sys

TYPES = ("feat", "fix", "docs", "test", "refactor", "perf", "ci", "build", "chore", "revert")
AREAS = ("CI", "SEG", "IA", "UX", "BE", "FE", "OPS", "DOC")

_T = "|".join(TYPES)
_A = "|".join(AREAS)

TITLE_RE = re.compile(rf"^(?P<tipo>{_T})\((?P<area>{_A})-(?P<num>\d{{3}})\): (?P<resumen>\S.*)$")
BRANCH_RE = re.compile(rf"^(?P<tipo>{_T})/(?P<area>{_A})-(?P<num>\d{{3}})-(?P<slug>[a-z0-9][a-z0-9-]{{1,48}}[a-z0-9])$")
DEPS_TITLE_RE = re.compile(r"^chore\(deps[a-z-]*\): \S")
REQUIRED_SECTIONS = ("Resumen", "Despliegue")

TITLE_MIN, TITLE_MAX = 15, 100


def _section(body: str, name: str) -> str | None:
    """Texto de la sección `## name` (sin comentarios HTML), o None si no existe."""
    clean = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    m = re.search(rf"^##[ \t]+{re.escape(name)}[ \t]*$", clean, flags=re.M | re.I)
    if not m:
        return None
    rest = clean[m.end():]
    nxt = re.search(r"^##[ \t]+\S", rest, flags=re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def is_dependabot(title: str, branch: str) -> bool:
    return branch.startswith("dependabot/") and bool(DEPS_TITLE_RE.match(title))


def validate(title: str, branch: str, body: str) -> tuple[list[str], str, str]:
    """Devuelve (errores, area, tipo). area/tipo vacíos si no se pudieron leer."""
    title = title.strip()
    if is_dependabot(title, branch):
        return [], "", "chore"

    errors: list[str] = []
    area = tipo = ""

    m = TITLE_RE.match(title)
    if not m:
        errors.append(
            "Título inválido. Formato: `tipo(ÁREA-NNN): resumen`, p. ej. "
            "`fix(IA-005): el sondeo de lotes no abandona lo que un ciclo aún va a enviar`. "
            f"Tipos: {', '.join(TYPES)}. Áreas: {', '.join(AREAS)}. NNN: tres dígitos."
        )
    else:
        area, tipo = m["area"], m["tipo"]
        if not TITLE_MIN <= len(title) <= TITLE_MAX:
            errors.append(f"El título mide {len(title)} caracteres; debe medir entre {TITLE_MIN} y {TITLE_MAX}.")
        if title.rstrip().endswith("."):
            errors.append("El título no termina en punto.")

    b = BRANCH_RE.match(branch)
    if not b:
        errors.append(
            f"Rama inválida: `{branch}`. Formato: `tipo/ÁREA-NNN-resumen-con-guiones` "
            "(resumen de 3 a 50 caracteres, minúsculas, dígitos y guiones), "
            "p. ej. `fix/IA-005-sondeo-lotes-sin-abandonar`."
        )
    elif m and f"{b['area']}-{b['num']}" != f"{m['area']}-{m['num']}":
        errors.append(
            f"El código de la rama ({b['area']}-{b['num']}) no coincide con el del título ({m['area']}-{m['num']})."
        )

    for name in REQUIRED_SECTIONS:
        text = _section(body or "", name)
        if text is None:
            errors.append(f"Falta la sección `## {name}` en la descripción (usa la plantilla del repositorio).")
        elif not text:
            errors.append(f"La sección `## {name}` está vacía; escribe el contenido o «No aplica».")

    return errors, area, tipo


def main() -> int:
    title = os.environ.get("PR_TITLE", "")
    branch = os.environ.get("PR_BRANCH", "")
    body = os.environ.get("PR_BODY", "")
    errors, area, tipo = validate(title, branch, body)

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"area={area}\ntipo={tipo}\n")

    if errors:
        print("El PR no cumple las convenciones (docs/proyecto/CONVENCIONES_GITHUB.md):\n")
        for e in errors:
            print(f"::error::{e}")
            print(f" - {e}")
        return 1
    print(f"OK: {title}  [{branch}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
