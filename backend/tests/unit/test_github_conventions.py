"""GitHub conventions (CI-005, docs/proyecto/CONVENCIONES_GITHUB.md): the PR validator, the labels file, the templates and the registry.
These tests pin the format so nobody weakens it without the CI noticing."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
GH = REPO / ".github"
SCRIPT = GH / "scripts" / "check_pr_title.py"
DOCS = REPO / "docs" / "proyecto"

BODY = "## Resumen\n\nCambia algo.\n\n## Despliegue\n\nNo aplica.\n"
TITLE = "fix(IA-005): el sondeo de lotes no abandona lo que un ciclo aún va a enviar"
BRANCH = "fix/IA-005-sondeo-lotes-sin-abandonar"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_pr_title", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load()


def test_a_correct_pr_passes_and_yields_area_and_type() -> None:
    errors, area, tipo = V.validate(TITLE, BRANCH, BODY)
    assert errors == [] and (area, tipo) == ("IA", "fix")


@pytest.mark.parametrize(
    "title",
    [
        "Update stuff",
        "C4: arreglo del despliegue desde GitHub",
        "fix: cosas que se arreglan en el servidor",  # sin código
        "fix(IA-5): el sondeo de lotes no abandona nada",  # código mal formado
        "Feat(CI-001): integración continua en GitHub Actions",  # tipo en mayúscula
        "feat(XX-001): un área que no existe en el registro",
        "feat(CI-001) integración continua sin los dos puntos",
        "feat(CI-001): integración continua en GitHub Actions.",  # punto final
        "fix(CI-001): x",  # menos de 15
        "feat(CI-001): " + "x" * 100,  # más de 100
        "feat(CI-001):    ",
    ],
)
def test_bad_titles_are_rejected(title: str) -> None:
    errors, _, _ = V.validate(title, "feat/CI-001-integracion-continua", BODY)
    assert errors, title


@pytest.mark.parametrize(
    "branch",
    ["main", "ia-p05", "fix/ia-005-minusculas", "fix/IA-005-", "fix/IA-005-ab", "fix/IA-005-Mayusculas-Dentro", "fix/IA-005-" + "a" * 51, "IA-005-sin-tipo", "fix/IA-005_guion_bajo"],
)
def test_bad_branches_are_rejected(branch: str) -> None:
    errors, _, _ = V.validate(TITLE, branch, BODY)
    assert any("Rama inválida" in e for e in errors), branch


def test_the_code_in_the_branch_must_equal_the_one_in_the_title() -> None:
    errors, _, _ = V.validate(TITLE, "fix/IA-006-otro-codigo-distinto", BODY)
    assert any("no coincide" in e for e in errors)


@pytest.mark.parametrize(
    "body",
    ["", "sin secciones", "## Resumen\n\nalgo\n", "## Despliegue\n\nNo aplica.\n", "## Resumen\n\n<!-- solo comentario -->\n\n## Despliegue\n\nNo aplica.\n", "## Resumen\n\nalgo\n\n## Despliegue\n\n"],
)
def test_the_body_needs_both_sections_with_content(body: str) -> None:
    errors, _, _ = V.validate(TITLE, BRANCH, body)
    assert errors


def test_the_real_template_filled_in_passes_and_the_empty_one_does_not() -> None:
    template = (GH / "pull_request_template.md").read_text(encoding="utf-8")
    assert V.validate(TITLE, BRANCH, template)[0], "la plantilla sin rellenar no puede pasar"
    filled = template.replace("<!-- Una o dos frases: qué cambia para quien lo lea, no cómo. -->", "Algo cambia.")
    assert not any("Resumen" in e for e in V.validate(TITLE, BRANCH, filled)[0])


def test_dependabot_is_exempt_but_only_with_both_marks() -> None:
    assert V.validate("chore(deps): bump ruff from 0.8 to 0.9 in /backend", "dependabot/pip/backend/ruff-0.9", "")[0] == []
    assert V.validate("chore(deps-dev): bump vite", "dependabot/bun/web/vite-6", "")[0] == []
    assert V.validate("chore(deps): bump ruff", "chore/CI-001-mi-rama-normal", "")[0], "una rama normal no se libra con el título"
    assert V.validate("Bump ruff", "dependabot/pip/backend/ruff-0.9", "")[0], "una rama de dependabot necesita el prefijo"


def test_every_type_and_area_has_a_label_and_the_file_is_sane() -> None:
    data = json.loads((GH / "labels.json").read_text(encoding="utf-8"))
    names = [x["name"] for x in data["labels"]]
    assert len(names) == len(set(names))
    for a in V.AREAS:
        assert f"area:{a}" in names
    for t in V.TYPES:
        assert f"tipo:{t}" in names
    for n in ("requiere-despliegue", "requiere-decision-del-dueno", "estado:desplegado", "prioridad:alta"):
        assert n in names
    for x in data["labels"]:
        assert re.fullmatch(r"[0-9a-f]{6}", x["color"]) and len(x["description"]) <= 100, x
    assert len(data["milestones"]) == 6


def test_the_workflow_passes_values_through_env_and_never_through_the_shell() -> None:
    wf = yaml.safe_load((GH / "workflows" / "pr-title.yml").read_text(encoding="utf-8"))
    assert wf[True]["pull_request"]["types"] == ["opened", "edited", "synchronize", "reopened"]  # YAML parses `on` as True
    assert "paths" not in wf[True]["pull_request"], "tiene que correr en todos los PR para poder ser obligatorio"
    steps = wf["jobs"]["convenciones"]["steps"]
    assert wf["jobs"]["convenciones"]["name"] == "Convenciones del PR"  # el nombre exacto de la comprobación obligatoria en `main`
    for step in steps:
        assert "${{" not in step.get("run", ""), step
    assert wf["permissions"] == {"contents": "read", "pull-requests": "write"}


def test_dependabot_uses_the_conventional_prefix_and_known_labels() -> None:
    cfg = yaml.safe_load((GH / "dependabot.yml").read_text(encoding="utf-8"))
    known = {x["name"] for x in json.loads((GH / "labels.json").read_text(encoding="utf-8"))["labels"]} | set(json.loads((GH / "labels.json").read_text(encoding="utf-8"))["keep"])
    for u in cfg["updates"]:
        assert u["commit-message"]["prefix"] == "chore(deps)", u
        assert set(u["labels"]) <= known, u


@pytest.mark.parametrize("name", ["cambio.yml", "error.yml", "decision.yml", "config.yml"])
def test_issue_forms_parse_and_use_the_areas(name: str) -> None:
    form = yaml.safe_load((GH / "ISSUE_TEMPLATE" / name).read_text(encoding="utf-8"))
    if name == "config.yml":
        assert form["blank_issues_enabled"] is False
        return
    assert form["name"] and form["description"] and form["title"]
    area = next(b for b in form["body"] if b.get("id") == "area")
    assert area["attributes"]["options"] == list(V.AREAS)


def test_the_pr_template_has_the_sections_the_doc_promises() -> None:
    t = (GH / "pull_request_template.md").read_text(encoding="utf-8")
    for s in ("Resumen", "Qué cambia", "Por qué", "Cómo se probó", "Riesgo y vuelta atrás", "Despliegue", "Códigos"):
        assert re.search(rf"^## {re.escape(s)}$", t, flags=re.M), s


def test_the_registry_is_consistent() -> None:
    reg = (DOCS / "REGISTRO_CODIGOS.md").read_text(encoding="utf-8")
    codes = re.findall(rf"^\| ((?:{'|'.join(V.AREAS)})-\d{{3}})(?: a [A-Z]+-\d{{3}})? \|", reg, flags=re.M)
    assert len(codes) == len(set(codes)), "código repetido"
    assert "CI-005" in codes
    # the "next free" line must be above every code used in each area
    tail = reg.split("## Siguiente número libre")[1]
    for area, num in re.findall(r"([A-Z]+)-(\d{3})", tail):
        used = [int(c.split("-")[1]) for c in codes if c.startswith(area + "-")]
        assert int(num) > max(used, default=0), (area, num)
    for area in V.AREAS:
        assert f"{area}-" in tail, area


def test_the_docs_name_the_files_that_exist() -> None:
    doc = (DOCS / "CONVENCIONES_GITHUB.md").read_text(encoding="utf-8")
    for rel in re.findall(r"`((?:\.github|docs|backend)/[A-Za-z0-9_./-]+\.(?:md|json|yml|py))`", doc):
        assert (REPO / rel).exists(), rel
    assert (REPO / "CONTRIBUTING.md").exists() and (GH / "CODEOWNERS").exists()
