"""The Phase 3 guide (``docs/owner/IA_FASE3.md``) says what the code does.

The guide is for the owner: it says what the shadow of phase 3 is (the Orchestrator, the Match Agent and the Council, in the LAB, reading nothing
a decision reads), the three words that switch it on and the order of the activation, the migration 0119 and how it is deployed, the seven arms
and the rule that puts a match in one of them for good, what a turn of the Orchestrator does, the models and contracts of the agents, the
contradictions C01-C08, the guards, the budget, the two rules of the nightly leak audit, what the Console shows, what Gate B asks, and what the
code does LESS than the plan. Nothing held it together with the code. This file reads the guide's tables and sentences and compares every
figure, name and option with the constants, settings, migration and routes of the code - and where the guide says what the code DOES (the three
words are needed together, a match never changes group, a model cannot ask for Opus) it makes the code do it. If a constant changes the test
fails until the guide says the new value, and if the guide is edited to something else it fails the same way.

What is not compared is data and not code: the figures of the plan (≈ 1.7 USD a day of LAB) and the sizes measured on a date (the 115,220 rows
of ``ai.pick_reviews`` of 25 Oct 2026, which ``IA_BASELINE_F0.md`` holds). The deviations the guide declares (section 13) are held both ways: the
test makes the code show each one, so a deviation that is fixed makes the test fail until the guide stops declaring it.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import os
import re
from decimal import Decimal
from functools import cache as memo
from pathlib import Path
from types import ModuleType
from typing import Any, get_args

import pytest
from apps.worker import scheduler

from fbi.ai import arms, config, contra, orchestrator, orchestrator_store, router, runtime
from fbi.ai import prompts as prompt_labels
from fbi.ai.agents import council, match
from fbi.ai.agents import registry as agent_registry
from fbi.ai.agents.common import CONTRA_CODES
from fbi.ai.battery import TARGETS
from fbi.ai.config import AiSettings
from fbi.ai.contracts import assessment as aa
from fbi.ai.contracts import base
from fbi.ai.contracts import council as cd
from fbi.api.routers import ai_layer as ai_layer_routes
from fbi.intel import leakage

BACKEND = Path(__file__).resolve().parents[2]
MONOREPO = BACKEND.parent
DOCS = BACKEND / "docs"
D = Decimal


def read_doc(*parts: str) -> str:
    """A document of the repository, with the typographic minus written as a hyphen. Where the documents are not shipped (an image with the code
    only) there is nothing to compare."""
    path = DOCS.joinpath(*parts)
    if not path.is_file():
        pytest.skip(f"no {path.name} next to the code", allow_module_level=True)
    return path.read_text(encoding="utf-8").replace("\N{MINUS SIGN}", "-")


GUIDE = read_doc("owner", "IA_FASE3.md")
PHASE_2 = read_doc("owner", "IA_FASE2.md")
ACTIONS = read_doc("owner", "IA_ACCIONES_MANUALES.md")
SRC = BACKEND / "src" / "fbi"
ORCH_SRC = (SRC / "ai" / "orchestrator.py").read_text(encoding="utf-8")
STORE_SRC = (SRC / "ai" / "orchestrator_store.py").read_text(encoding="utf-8")
CONFIG_SRC = (SRC / "ai" / "config.py").read_text(encoding="utf-8")
SCHEDULER_SRC = Path(scheduler.__file__).read_text(encoding="utf-8")


# ── reading the documents ─────────────────────────────────────────────────────────────────────────────────────────

def section(number: int) -> str:
    m = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", GUIDE, flags=re.S | re.M)
    assert m, f"section {number} is missing from the guide"
    return m.group(0)


def table(text: str, header: str, *, nth: int = 0) -> list[list[str]]:
    """The cells of the rows of the ``nth`` table whose header line starts with ``header`` (the header and its rule left out, the bold marks taken
    off)."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(header)]
    assert len(starts) > nth, f"the guide no longer has the table {header!r}"
    out: list[list[str]] = []
    for line in lines[starts[nth] + 2:]:
        if not line.startswith("|"):
            break
        out.append([cell.strip().replace("**", "") for cell in line.strip().strip("|").split("|")])
    return out


def all_ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def number(token: str) -> Decimal:
    """A number as the guide writes it: decimal comma, thousands with a dot."""
    token = token.strip()
    if "," in token:
        return D(token.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        return D(token.replace(".", ""))
    return D(token)


def said(pattern: str, text: str, *expected: Decimal | int | str) -> None:
    """The guide says ``expected`` where ``pattern`` captures numbers."""
    m = re.search(pattern, text, flags=re.S)
    assert m, f"the guide no longer says {pattern!r}"
    assert tuple(number(g) for g in m.groups()) == tuple(D(str(e)) for e in expected), pattern


def migration_module() -> ModuleType:
    path = next((BACKEND / "migrations" / "versions").glob("0119_*.py"))
    spec = importlib.util.spec_from_file_location("ia_migration_0119", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings_of(monkeypatch: pytest.MonkeyPatch, **env: str) -> AiSettings:
    monkeypatch.setattr("fbi.ai.config.environment", lambda: env)
    return AiSettings.from_env()


# ── the header and the whole guide ────────────────────────────────────────────────────────────────────────────────

SECTION_TITLES = [
    "Qué es la Fase 3 y qué no toca",
    "Los tres interruptores y la vuelta atrás",
    "La migración 0119 y cómo se despliega",
    "Los siete brazos y la regla de asignación",
    "El Orchestrator: qué hace cada vuelta",
    "El Match Agent y el Council: contratos y modelos",
    "Las contradicciones C01 a C08",
    "Las guardas de ejecución",
    "El presupuesto",
    "Las reglas de fuga `agent_known` y `shadow_review_known`",
    "Lo que muestra la Consola",
    "Lo que pide el gate B y tu acción 15",
    "Desviaciones y límites declarados",
    "Las pruebas y lo que falta",
]


def test_the_sections_of_the_guide_are_1_to_14_in_order_and_the_header_says_where_the_phase_stands() -> None:
    titles = dict(re.findall(r"^## (\d+)\. (.*)$", GUIDE, flags=re.M))
    assert [int(n) for n in titles] == list(range(1, 15))
    assert list(titles.values()) == SECTION_TITLES
    assert GUIDE.startswith("# Fase 3 del Plan Maestro IA · El multiagente en sombra: Orchestrator, Match Agent y Council\n")
    head = GUIDE.split("## 1.", 1)[0]
    assert "todavía sin desplegar" in head and "se despliega apagada" in head and "la migración 0119" in head
    assert "tests/unit/test_ia_fase3_docs.py" in head and Path(__file__).name == "test_ia_fase3_docs.py"
    assert "`IA_FASE2.md`" in head and "tests/unit/test_ia_fase2_docs.py" in PHASE_2


def test_the_documents_the_guide_leans_on_exist_and_it_carries_no_key_and_no_gap() -> None:
    for name in set(re.findall(r"`?(IA_[A-Z0-9_]+\.md)`?", GUIDE)):
        assert (DOCS / "owner" / name).is_file(), name
    assert not re.search(r"sk-[A-Za-z0-9_-]{8,}", GUIDE), "a key (or something shaped like one) in the guide"
    assert "@@" not in GUIDE and "[[" not in GUIDE, "a placeholder left in the guide"
    for name in ("IA_FASE1.md", "IA_FASE2.md", "IA_BASELINE_F0.md", "IA_ACCIONES_MANUALES.md"):
        assert f"`{name}`" in GUIDE


def test_every_variable_the_guide_names_is_read_by_the_code() -> None:
    names = set(re.findall(r"FBI_[A-Z0-9_]*[A-Z0-9]", GUIDE))
    assert names == {
        "FBI_AI_ENGINES", "FBI_AI_SHADOW_SAMPLE", "FBI_AI_AGENTS", "FBI_AI_ORCHESTRATE_MINUTES", "FBI_AI_MODE",
        "FBI_AI_KEY_ANTHROPIC_LAB", "FBI_AI_MODEL_BULK", "FBI_AI_MODEL_ANALYSIS", "FBI_AI_MODEL_FINAL", "FBI_AI_LAB_MONTHLY_BUDGET_USD",
        "FBI_AI_BATCH", "FBI_AI_BATCH_MIN_LEAD_MINUTES",  # the Batch calendar has no switch of its own: the batch gate's
    }
    for name in names:
        if name == "FBI_AI_KEY_ANTHROPIC_LAB":  # built from the provider name: FBI_AI_KEY_<PROVIDER>_LAB
            assert 'f"FBI_AI_KEY_{p.upper()}_LAB"' in CONFIG_SRC and "anthropic" in config.PROVIDERS
            continue
        assert name in CONFIG_SRC or name in SCHEDULER_SRC, f"{name} is named by the guide and read by nobody"


ROOTS = ((BACKEND / "src", (".py", ".sql", ".json")), (BACKEND / "scripts", (".py", ".sh", ".sql")), (BACKEND / "migrations", (".py",)),
         (BACKEND / "deploy", (".sh", ".yml", ".sql", ".md", ".env", ".txt")), (BACKEND / "docs", (".md",)), (BACKEND / "tests", (".py",)),
         (BACKEND / "apps", (".py",)), (MONOREPO / "web" / "src", (".ts", ".tsx", ".json")))
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@memo
def vocabulary() -> frozenset[str]:
    """Every identifier-like word of the code, the scripts, the migrations, the other documents, the tests and the web (this guide and this file
    left out: they would vouch for themselves), and the stem of every file's name."""
    skip = {(DOCS / "owner" / "IA_FASE3.md").resolve(), Path(__file__).resolve()}
    words: set[str] = set()
    for root, extensions in ROOTS:
        for folder, folders, files in os.walk(root, followlinks=True):
            folders[:] = [f for f in folders if f not in {".venv", "node_modules", "__pycache__", "screenshots"}]
            for name in files:
                path = Path(folder, name)
                if path.suffix in extensions:
                    words.add(path.stem)
                    if path.resolve() not in skip:
                        words.update(WORD.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return frozenset(words)


def test_every_name_the_guide_writes_between_backticks_exists_in_the_repository() -> None:
    spans = re.findall(r"`([^`\n]+)`", GUIDE)
    unknown = sorted({w for span in spans for w in WORD.findall(span) if len(w) >= 2} - vocabulary())
    assert not unknown, f"names between backticks that nothing in the repository has (a name that changed, or a typo): {unknown}"


def test_the_pieces_of_the_guide_are_files_that_exist() -> None:
    rows = table(section(1), "| Pieza")
    assert [r[0] for r in rows] == ["Interruptores", "Brazos y asignación", "Orchestrator", "Match Agent", "Contradicciones", "Council",
                                    "Router", "Guardas", "Trabajo del worker", "Auditoría de fugas", "Consola"]
    for row in rows:
        for name in all_ticked(row[2]):
            if re.fullmatch(r"\d{4}", name):
                assert any((BACKEND / "migrations" / "versions").glob(f"{name}_*.py")), name
            elif name.startswith("web/"):
                assert not (MONOREPO / "web").is_dir() or (MONOREPO / name).is_file(), name
            elif name.startswith("apps/"):
                assert (BACKEND / name).is_file(), name
            else:
                assert (SRC / name).is_file(), f"{name} (piece {row[0]!r})"


def test_the_tests_the_guide_names_exist() -> None:
    names = set(re.findall(r"`(tests/[a-z_/0-9]+\.py)`", GUIDE))
    assert len(names) >= 18
    for name in names:
        assert (BACKEND / name).is_file(), name


# ── 1. what the phase does not touch ──────────────────────────────────────────────────────────────────────────────

def test_what_the_phase_does_not_touch_is_what_the_default_leaves_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    sec = section(1)
    off = AiSettings()
    assert off.engines == ("rules", "llm") and off.shadow_sample == 0 and off.agents == () and off.orchestrate is False
    assert "Con los valores de serie" in sec and "no abre ni una conexión" in sec
    # the decision layer reads only combined and rules; the readers of production name its engines
    assert "r.engine IN ('combined', 'rules')" in (SRC / "intel" / "decision.py").read_text(encoding="utf-8")
    assert config.PRODUCTION_ENGINES == ("rules", "llm", "combined")
    for name in ("ai/gate_a.py", "ai/costs.py", "ai/gate_research.py", "ai/postmortem.py", "ai/shadow.py", "intel/match_review.py"):
        assert f"`{name}`" in sec
        text = (SRC / name).read_text(encoding="utf-8")
        assert "PRODUCTION_ENGINES" in text or "'rules', 'llm', 'combined'" in text, name
    assert "tests/unit/test_engine_filter_guard.py" in sec
    # the shadow never writes evidence nor passes
    for forbidden in ("INSERT INTO ai.evidence", "INSERT INTO ai.fixture_passes"):
        assert forbidden not in STORE_SRC and forbidden not in ORCH_SRC
    assert "nunca llegan al filtro 6" in sec


# ── 2. the three words and the way back ───────────────────────────────────────────────────────────────────────────

ON = {"FBI_AI_MODE": "shadow", "FBI_AI_ENGINES": "rules,llm,ma-v1,ma-v1-h", "FBI_AI_SHADOW_SAMPLE": "0.3", "FBI_AI_AGENTS": "match,council"}


def test_the_switch_table_says_the_defaults_the_settings_have() -> None:
    rows = {r[0].strip("`"): r for r in table(section(2), "| Variable")}
    assert set(rows) == {"FBI_AI_ENGINES", "FBI_AI_SHADOW_SAMPLE", "FBI_AI_AGENTS"}
    defaults = AiSettings()
    assert rows["FBI_AI_ENGINES"][1].strip("`") == ",".join(defaults.engines)
    assert rows["FBI_AI_SHADOW_SAMPLE"][1].strip("`") == str(defaults.shadow_sample)
    assert rows["FBI_AI_AGENTS"][1] == "vacío" and defaults.agents == ()
    # the engines that the list can add are the shadow engines of the code
    assert set(re.findall(r"`(ma-v1-h|ma-v1|cs-v1)`", rows["FBI_AI_ENGINES"][2])) == set(config.SHADOW_ENGINES)
    assert "`rules` y `llm` están siempre" in rows["FBI_AI_ENGINES"][2]
    assert config.KNOWN_ENGINES == ("rules", "llm", "ma-v1", "ma-v1-h", "cs-v1") and config.AGENTS == ("match", "council", "stats")
    said(r"\(`0\.3` es el (\d+) %\)", rows["FBI_AI_SHADOW_SAMPLE"][2], 30)


def test_the_activation_of_the_guide_makes_the_shadow_run_and_the_rollback_stops_it(monkeypatch: pytest.MonkeyPatch) -> None:
    sec = section(2)
    rows = {r[0].strip("`"): r for r in table(sec, "| Variable")}
    activation = {k: rows[k][3].strip("`") for k in rows}
    rollback = {k: rows[k][4].strip("`") for k in rows}
    assert activation == {"FBI_AI_ENGINES": "rules,llm,ma-v1,ma-v1-h", "FBI_AI_SHADOW_SAMPLE": "0.3", "FBI_AI_AGENTS": "match,council"}
    for line in ("`FBI_AI_ENGINES=rules,llm,ma-v1,ma-v1-h`", "`FBI_AI_SHADOW_SAMPLE=0.3`", "`FBI_AI_AGENTS=match,council`"):
        assert line in sec
    on = settings_of(monkeypatch, **ON)
    assert on.orchestrate is True and on.shadow_engines == ("ma-v1", "ma-v1-h") and on.shadow_sample == D("0.3") and on.agents == ("match", "council")
    # the activation does not name cs-v1: COUNCIL SOLO does not run
    assert "cs-v1" not in on.engines
    # the rollback values
    assert rollback["FBI_AI_ENGINES"] == "rules,llm" and rollback["FBI_AI_SHADOW_SAMPLE"] == "0"
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_ENGINES": "rules,llm"}).orchestrate is False
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_SHADOW_SAMPLE": "0"}).orchestrate is False
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_AGENTS": ""}).orchestrate is False
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_AGENTS": "match"}).orchestrate is False, "the Orchestrator needs both agents"
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_MODE": "off"}).orchestrate is False
    assert "La sombra necesita **las tres palabras a la vez**" in sec


def test_the_words_are_clamped_and_a_typo_switches_nothing_on(monkeypatch: pytest.MonkeyPatch) -> None:
    sec = section(2)
    assert "un error de tecleo apaga" in sec and "nunca lanza un error" in sec
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_SHADOW_SAMPLE": "7"}).shadow_sample == 1
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_SHADOW_SAMPLE": "-1"}).shadow_sample == 0
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_SHADOW_SAMPLE": "thirty"}).shadow_sample == 0
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_ENGINES": "ma-v2"}).orchestrate is False, "a name that is none of the engines is dropped"
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_ENGINES": " MA-V1 , llm"}).engines == ("rules", "llm", "ma-v1"), "case and spaces do not count"
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_ENGINES": "ma-v1"}).engines[:2] == ("rules", "llm"), "the list only adds"
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_AGENTS": "match,council,stats"}).agents == ("match", "council", "stats"), "phase 4 knows stats"
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_AGENTS": "match,council,player"}).agents == ("match", "council"), "a name that is none is dropped"
    assert "más de 1 cuenta como 1, menos de 0 como 0 y lo que no es un número, como 0" in sec


def test_the_job_is_on_the_clock_every_five_minutes_and_inert_until_the_three_words_say_so() -> None:
    sec = section(2)
    said(r"`FBI_AI_ORCHESTRATE_MINUTES` \(de serie (\d+), nunca menos de (\d+)\)", sec, scheduler.AI_ORCHESTRATE_MINUTES, 1)
    tree = ast.parse(SCHEDULER_SRC)
    jobs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_job"
            and any(k.arg == "id" and isinstance(k.value, ast.Constant) and k.value.value == "ai_orchestrate" for k in n.keywords)]
    assert len(jobs) == 1
    kw = {k.arg: k.value for k in jobs[0].keywords if k.arg}
    assert isinstance(kw["max_instances"], ast.Constant) and kw["max_instances"].value == 1
    assert "_deadline" not in ast.unparse(jobs[0])
    body = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_ai_orchestrate_now")
    assert "settings.orchestrate" in ast.unparse(body) and "open_cycle(conn, 'orchestrate'" in ast.unparse(body)
    assert not {n.attr.lower() for n in ast.walk(body) if isinstance(n, ast.Attribute) and "lock" in n.attr.lower()}
    assert "ai_orchestrate" in (scheduler.__doc__ or "")
    assert "un solo ejemplar a la vez, sin tomar el cerrojo del ciclo de análisis" in section(5)


def test_the_activation_sequence_names_what_it_needs_and_the_models_must_be_the_routers() -> None:
    sec = section(2)
    assert "`PASA`" in sec and "acción 15" in sec and "FBI_AI_KEY_ANTHROPIC_LAB" in sec
    assert router.MODELS["simple"] == "claude-haiku-5-5" and router.MODELS["complex"] == "claude-sonnet-5-5" and router.MODELS["critical"] == "claude-opus-5-5"
    assert "Haiku, Sonnet y Opus 5.5" in sec
    # a LAB tier whose model is not the router's is not asked: the code says model_not_configured
    assert "model_not_configured" in ORCH_SRC and "`model_not_configured`" in sec
    assert "configured.model != model" in ORCH_SRC
    said(r"sobre de la fase 0 \((\d+) US\$\)", sec, 15)
    assert "copia fechada de `app.env`" in sec and "reiniciar el worker" in sec
    # the three words enter the owner's ledger only when moved from their default
    from fbi.ai import gates
    assert gates.shadow_words(AiSettings()) == {}
    assert set(gates.shadow_words(AiSettings(engines=("rules", "llm", "ma-v1"), shadow_sample=D("0.3"), agents=("match", "council")))) == {
        "engines", "shadow_sample", "agents"}
    assert "gate `switches`" in sec


def test_the_rollback_table_says_what_each_way_back_keeps() -> None:
    rows = table(section(2), "| Qué quieres deshacer")
    assert [r[0] for r in rows] == ["Que la sombra corra", "Un brazo concreto", "Que la sombra gaste", "Toda la fase"]
    assert "FBI_AI_SHADOW_SAMPLE=0" in rows[0][1] and "FBI_AI_ENGINES=rules,llm" in rows[0][1]
    # closing the LAB envelope stops the run with no_envelope
    assert "FBI_AI_LAB_MONTHLY_BUDGET_USD=0" in rows[2][1] and "no_envelope" in rows[2][1]
    assert "no_envelope" in orchestrator.BUDGET_STOPS
    # taking an engine out and putting it back does not redraw the groups: the assignment is stored whatever the engines are
    assert arms.runnable(arms.arms_for(0, D("1"), 0), ("ma-v1",)) == ("ma-v1",)
    assert arms.runnable(arms.arms_for(0, D("1"), 0), ()) == ()


# ── 3. the migration ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_phase_adds_the_one_migration_the_guide_says_and_no_other() -> None:
    versions = BACKEND / "migrations" / "versions"
    assert sorted(p.name[:4] for p in versions.glob("*_ia_phase3_*.py")) == ["0119"]
    assert "la fase lleva una sola migración, la 0119" in GUIDE
    m = migration_module()
    assert m.revision == "0119" and m.down_revision == "0118"


def test_migration_0119_adds_what_the_guide_says_and_nothing_is_rewritten() -> None:
    sec = section(3)
    m = migration_module()
    assert tuple(m.SHADOW_ENGINES) == config.SHADOW_ENGINES == ("ma-v1", "ma-v1-h", "cs-v1")
    assert tuple(m.ENGINES) == ("rules", "llm", "combined")
    assert "orchestrate" in inspect.getsource(m.upgrade)
    rows = {r[0].strip("`"): r[1] for r in table(sec, "| Qué")}
    assert set(rows) == {"ai.pick_reviews", "ai.cycles", "ai.shadow_assignments"}
    for name in ("pick_reviews_engine_check", "cycles_kind_check", "shadow_assignments_append_only", "shadow_assignments_sample_rule",
                 "shadow_assignments_solo_is_sampled"):
        assert name in sec and name in inspect.getsource(m)
    assert "`ma-v1`, `ma-v1-h` y `cs-v1`" in rows["ai.pick_reviews"] and "`orchestrate`" in rows["ai.cycles"]
    assert "orchestrate" in inspect.getsource(m.upgrade) and "DROP TABLE ai.shadow_assignments" in inspect.getsource(m.downgrade)
    # additive: a lock waits at most 10 seconds and the busy tables go first
    upgrade = inspect.getsource(m.upgrade)
    assert "SET LOCAL lock_timeout = '10s'" in upgrade and "10 segundos" in sec
    assert upgrade.index("ai.pick_reviews") < upgrade.index("CREATE TABLE ai.shadow_assignments")
    # the downgrade leaves the old lists unvalidated
    assert inspect.getsource(m.downgrade).count("NOT VALID") == 2 and "**sin validar**" in sec
    assert "UPDATE ai.cycles SET status = 'failed'" in inspect.getsource(m.downgrade)
    said(r"son ([\d.]+) filas medidas el 25 oct 2026", sec, 115220)
    assert "115,220" in inspect.getsource(m) and "115.220" in read_doc("owner", "IA_BASELINE_F0.md") + sec
    # the table holds the rule the code applies
    assert f"bucket < share * {arms.BUCKETS}" in inspect.getsource(m) and m.BUCKETS == arms.BUCKETS


def test_the_deployment_goes_by_the_release_chain_with_a_backup_and_the_proof_of_the_restore() -> None:
    sec = section(3)
    chain = (BACKEND / "deploy" / "release" / "README.md").read_text(encoding="utf-8")
    assert "backup + restore test" in chain and "precheck" in chain and "follow-ups at 10/30/60 minutes" in chain
    assert "**copia de seguridad y prueba de restauración de esa misma copia**" in sec and "10, 30 y 60 minutos" in sec
    assert (BACKEND / "deploy" / "release" / "templates" / "server" / "step_backup.sh").is_file()
    assert "predigolctl restore-test" in (BACKEND / "deploy" / "release" / "templates" / "server" / "step_backup.sh").read_text(encoding="utf-8")
    assert "no deshace nada por sí sola" in sec and "se detiene en el primer fallo" in sec
    # the precheck lets the three words through app.env
    precheck = (BACKEND / "deploy" / "release" / "templates" / "server" / "step_precheck.sh").read_text(encoding="utf-8")
    assert "ENGINES|SHADOW_SAMPLE|AGENTS|ORCHESTRATE_MINUTES" in precheck


def test_going_back_by_the_code_of_before_would_count_shadow_rows_in_four_figures_and_the_guide_says_so() -> None:
    sec = section(3)
    assert "la vuelta atrás normal son las palabras de la sección 2" in sec and "cuatro cifras" in sec
    # the four readers the commit that made them engine-aware changed
    for reader in ("gate_a.py", "costs.py", "postmortem.py"):
        assert "PRODUCTION_ENGINES" in (SRC / "ai" / reader).read_text(encoding="utf-8") or "'rules', 'llm', 'combined'" in (SRC / "ai" / reader).read_text(encoding="utf-8")
    assert "'rules', 'llm', 'combined'" in (SRC / "intel" / "match_review.py").read_text(encoding="utf-8")


# ── 4. the arms ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_salt_the_buckets_and_the_hash_are_the_ones_the_guide_gives() -> None:
    sec = section(4)
    assert "**`ma-shadow-v1`**" in sec and arms.SALT == "ma-shadow-v1" and arms.ARMS_VERSION == "arms-v1"
    said(r"de 0 a ([\d.]+) que sale", sec, arms.BUCKETS - 1)
    said(r"módulo ([\d.]+)\.", sec, arms.BUCKETS)
    for fixture_id in (1, 7, 12345, 987654321):
        first = int.from_bytes(hashlib.sha256(f"{arms.SALT}:{fixture_id}".encode()).digest()[:8], "big") % 10_000
        second = int.from_bytes(hashlib.sha256(f"{arms.SALT}:cs:{fixture_id}".encode()).digest()[:8], "big") % 10_000
        assert arms.bucket(fixture_id) == first and arms.solo_bucket(fixture_id) == second
    assert 'sha256("<sal>:<fixture_id>")' in sec and 'sha256("<sal>:cs:<fixture_id>")' in sec
    assert "No usa `hash()`" in sec and not re.search(r"(?<![a-z_.])hash\(", re.sub(r'"""(.|\n)*?"""', "", inspect.getsource(arms)))
    assert D("0.5") == arms.SOLO_SHARE and "la primera mitad de los cubos" in sec
    # the table of the seven arms has the engines of the code
    rows = table(sec, "| Brazo")
    assert len(rows) == 6
    engines = [all_ticked(r[1]) for r in rows]
    assert [e[0] for e in engines if e and e[0] in config.KNOWN_ENGINES] == ["rules", "llm", "ma-v1", "ma-v1-h", "cs-v1"]
    assert arms.MULTIAGENT == "ma-v1" and arms.MULTIAGENT_HAIKU == "ma-v1-h" and arms.COUNCIL_SOLO == "cs-v1"
    assert arms.SAMPLE_ENGINES == ("ma-v1", "ma-v1-h") and set(config.SHADOW_ENGINES) == {*arms.SAMPLE_ENGINES, arms.COUNCIL_SOLO}
    assert "el 15 % de todos los partidos con la muestra al 30 %" in sec


def test_a_sample_is_nested_a_match_is_in_the_sample_exactly_when_the_bucket_is_below_the_share() -> None:
    assert "`cubo < parte \N{MULTIPLICATION SIGN} 10.000`" in section(4) and "**anidadas**" in section(4)
    for fixture_id in range(1, 400):
        b = arms.bucket(fixture_id)
        for share in (D("0.1"), D("0.3"), D("0.5"), D("1")):
            assert arms.arms_of(fixture_id, share).sampled is (b < share * arms.BUCKETS)
        if arms.arms_of(fixture_id, D("0.3")).sampled:
            assert arms.arms_of(fixture_id, D("0.5")).sampled
    assert not arms.arms_of(5, D("0")).sampled
    # a sampled match runs ma-v1 and ma-v1-h, and cs-v1 only when the second hash says so
    solo = [i for i in range(1, 2000) if arms.arms_of(i, D("1")).council_solo]
    plain = [i for i in range(1, 2000) if not arms.arms_of(i, D("1")).council_solo]
    assert solo and plain
    assert arms.arms_of(solo[0], D("1")).engines == ("ma-v1", "ma-v1-h", "cs-v1")
    assert arms.arms_of(plain[0], D("1")).engines == ("ma-v1", "ma-v1-h")
    assert arms.arms_of(solo[0], D("0")).engines == ()
    # COUNCIL SOLO is about half of the sample, spread as the rest
    assert 0.4 < len(solo) / 1999 < 0.6


def test_the_assignment_is_written_once_before_anything_is_spent_and_never_changes() -> None:
    sec = section(4)
    assert "ON CONFLICT (experiment, fixture_id) DO NOTHING" in arms.INSERT_SQL
    assert "«ningún partido cambia de grupo»" in sec
    # the orchestrator commits the assignment before the first pass
    go = ORCH_SRC[ORCH_SRC.index("def go(self)"):ORCH_SRC.index("def item(")]
    assert go.index("arms.assign(") < go.index("self.conn.commit()") < go.index("self.item(")
    assert "Un partido visto con la muestra al 30 % y fuera de ella sigue fuera aunque subas la parte al 50 %" in sec
    # with no share nothing is written, and a match with no row is outside
    class Boom:
        def cursor(self, *a: Any, **k: Any) -> Any:
            raise AssertionError("a share of 0 writes nothing and reads nothing before the check")
    from datetime import UTC, datetime
    assert arms.assign(Boom(), [], at=datetime.now(UTC), share=D("0.3")) == {}  # type: ignore[arg-type]
    assert "`runnable` dice qué corre hoy" in sec and arms.runnable(arms.arms_for(0, D("1"), 0), ("ma-v1-h",)) == ("ma-v1-h",)
    assert "COUNCIL SOLO no corre hasta que lo añadas" in sec


# ── 5. the Orchestrator ───────────────────────────────────────────────────────────────────────────────────────────

def test_a_turn_looks_at_twenty_passes_for_240_seconds_in_the_last_two_days() -> None:
    sec = section(5)
    params = inspect.signature(orchestrator.run).parameters
    said(r"con (\d+) pasadas como máximo y (\d+) segundos", sec, params["limit"].default, int(params["max_seconds"].default))
    said(r"terminaron bien \(`ok` o `partial`\) en los últimos (\d+) días", sec, orchestrator_store.WINDOW.days)
    assert "p.status IN ('ok', 'partial')" in orchestrator_store.PENDING_SQL and "r.engine = 'rules'" in orchestrator_store.PENDING_SQL
    assert "f.kickoff_at > %(at)s" in orchestrator_store.PENDING_SQL
    assert orchestrator_store.LATE_MARGIN == runtime.FINAL_MARGIN
    assert "Primero las que aún pueden terminar antes de T-15" in sec
    assert "ai.agent_tasks" in sec and "ai.agent_runs" in sec and "`run_kind = 'shadow'`" in sec and "`mode = 'shadow'`" in sec
    assert orchestrator_store.SHADOW_RUN == "shadow" and "'shadow'" in STORE_SRC
    assert "never raises" in inspect.getdoc(orchestrator.run).lower() and "NEVER raises" in inspect.getdoc(orchestrator.run)  # type: ignore[operator,union-attr]


def test_the_candidates_are_the_selections_production_reviewed_named_by_a_pure_function() -> None:
    from fbi.ai.agents import common
    sec = section(5)
    assert "(`1X2`, `DC`, `AH`, `OU`, `BTTS`)" in sec and base.GOALS_RESULT == ("1X2", "DC", "AH", "OU", "BTTS")
    said(r"`c1`\.\.\.`c(\d+)`", sec, aa.CANDIDATES_MAX)
    assert "family_not_read" in sec and "family_not_read" in inspect.getsource(common.name_candidates)
    assert "beyond_the_limit" in inspect.getsource(common.name_candidates) and "mayor valor esperado" in sec
    assert "REVIEWED_SQL" in STORE_SRC and "r.engine = 'rules'" in orchestrator_store.REVIEWED_SQL
    assert "fair_and_minimum" in ORCH_SRC


def test_the_order_of_the_calls_and_the_models_asked_are_the_guides() -> None:
    sec = section(5)
    run_body = ORCH_SRC[ORCH_SRC.index("    def shadow(self"):ORCH_SRC.index("    # -- planning")]
    assert run_body.index("contra.detect") < run_body.index("self.match_round") < run_body.index("self.councils") < run_body.index("self.escalate")
    assert "lab=True" in ORCH_SRC and "usage.call_json(" in ORCH_SRC
    assert "`usage.call_json` con `lab=True`" in sec
    assert frozenset({"ma-v1", "ma-v1-h"}) == orchestrator.WITH_MATCH
    assert "`ma-v1` y `ma-v1-h` leen la misma vista con las posturas del Match Agent; `cs-v1` la lee sin ellas" in sec
    assert orchestrator.ENGINE_LEVEL == {"ma-v1": "complex", "ma-v1-h": "simple", "cs-v1": "complex"}


def test_when_no_model_can_be_asked_the_state_is_written_with_the_reason_and_a_fallback_review() -> None:
    sec = section(5)
    for reason in ("blocked:", "no_candidate_to_name", "slice_over_its_cap", "every_arm_paused"):
        assert reason in ORCH_SRC
    assert "ABSTAIN" in ORCH_SRC and orchestrator.STATUS_FALLBACK == "fallback"
    assert "(`ABSTAIN`, estado `fallback`, confianza 0)" in sec
    assert orchestrator.confidence_value(None) == 0 and orchestrator.confidence_value("anything") == 0


def test_the_report_has_the_fields_the_guide_lists() -> None:
    sec = section(5)
    listed = re.search(r"\*\*El informe\*\*.*?: (`skipped`.*?)\. El ciclo", sec, flags=re.S)
    assert listed
    fields = re.findall(r"`([a-z_]+)`", re.sub(r"\(.*?\)", "", listed.group(1)))
    assert fields == list(orchestrator.Report().to_json())
    assert orchestrator.Report(skipped="off").to_json()["skipped"] == "off" and "`off` si la sombra está apagada" in sec
    # the status of the cycle follows the report
    doc = inspect.getsource(scheduler._orchestrate_cycle_report)
    assert '"partial" if' in doc and '"failed"' in doc
    assert "`ok` si nada falló, `partial` si alguna pasada falló y otras corrieron, y `failed` si ninguna corrió" in sec


def test_the_confidence_is_a_fixed_map_and_the_engine_version_names_what_it_is_made_of() -> None:
    sec = section(5)
    said(r"`LOW` ([\d,]+), `MEDIUM` ([\d,]+), `HIGH` ([\d,]+)", sec, *(orchestrator.CONFIDENCE[k] for k in ("LOW", "MEDIUM", "HIGH")))
    assert {"LOW": D("0.35"), "MEDIUM": D("0.60"), "HIGH": D("0.85")} == orchestrator.CONFIDENCE
    assert orchestrator.ENGINE_VERSION["ma-v1"] == "ma-v1+match-v1+council-v1+contra-v1+router-v1" and "`ma-v1+match-v1+council-v1+contra-v1+router-v1`" in sec
    assert orchestrator.ENGINE_VERSION["cs-v1"] == "cs-v1+council-v1+router-v1" and "`cs-v1+council-v1+router-v1`" in sec
    for status in (orchestrator.STATUS_OK, orchestrator.STATUS_FALLBACK, orchestrator.STATUS_INVALID, orchestrator.STATUS_FAILED, orchestrator.STATUS_OVER_BUDGET):
        assert f"`{status}`" in sec
    assert orchestrator.VERSION == "orch-v1" and orchestrator_store.STATE_VERSION == "orch-v1"


def test_a_second_turn_over_the_same_passes_finds_nothing_and_a_paid_question_is_not_paid_again() -> None:
    sec = section(5)
    assert "NOT EXISTS (SELECT 1 FROM ai.match_runs m" in orchestrator_store.PENDING_SQL and "ai.agent_tasks t" in orchestrator_store.PENDING_SQL
    assert "idem-v1" in sec and "idem-v1" in (SRC / "ai" / "idempotency.py").read_text(encoding="utf-8")
    assert "def existing(" in STORE_SRC and "old = existing(self.conn, key)" in ORCH_SRC and "asked.reused = True" in ORCH_SRC
    assert "shared.shared = True" in ORCH_SRC and "_AlreadyShadowedError" in ORCH_SRC
    assert "Una vuelta es **idempotente**" in sec


# ── 6. the agents ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_models_efforts_prompts_and_contracts_are_the_routers_and_the_agents() -> None:
    rows = table(section(6), "| Quién")
    assert len(rows) == 5
    by = {(r[0], r[1]): r for r in rows}
    spec = router.SPECS
    assert match.model_of("CONTEXT") == router.MODELS[spec["context"].level] and spec["context"].effort == "low"
    assert match.model_of("EVALUATION") == router.MODELS[spec["evaluation"].level] and spec["evaluation"].effort == "medium"
    assert match.effort_of("CONTEXT") == "low" and match.effort_of("EVALUATION") == "medium"
    assert spec["council"].level == "complex" and spec["council"].effort == "medium"
    assert spec["escalation"].level == "critical" and spec["escalation"].effort == "medium"
    expected = [
        ("Match Agent", "contexto", router.MODELS["simple"], "low", prompt_labels.MATCH_CONTEXT_VERSION, base.ASSESSMENT),
        ("Match Agent", "evaluación", router.MODELS["simple"], "medium", prompt_labels.MATCH_ASSESS_VERSION, base.ASSESSMENT),
        ("Council", "veredicto", router.MODELS["complex"], "medium", prompt_labels.COUNCIL_VERSION, base.COUNCIL),
        ("Council", "escalada", router.MODELS["critical"], "medium", prompt_labels.COUNCIL_OPUS_VERSION, base.COUNCIL),
    ]
    for agent, task, model, effort, prompt, contract in expected:
        row = by[(agent, task)]
        assert all_ticked(row[2]) == [model] and all_ticked(row[3]) == [effort] and all_ticked(row[4]) == [prompt] and all_ticked(row[5]) == [contract]
    haiku = by[("Council (brazo `ma-v1-h`)", "veredicto")]
    assert all_ticked(haiku[4]) == [prompt_labels.COUNCIL_VERSION] and "Haiku" in haiku[2]
    assert council.model_of("simple") == router.MODELS["simple"] and council.TASK_OF["simple"] == council.TASK_OF["complex"] == "council"
    assert (prompt_labels.MATCH_CONTEXT_VERSION, prompt_labels.MATCH_ASSESS_VERSION, prompt_labels.COUNCIL_VERSION,
            prompt_labels.COUNCIL_OPUS_VERSION) == ("match-context-v1", "match-assess-v1", "council-v1", "council-opus-v1")


def test_the_agents_are_born_challengers_in_the_registry() -> None:
    sec = section(6)
    assert "nacen **RETADORES**" in sec and "`match-v1`, `council-v1`" in sec
    source = inspect.getsource(agent_registry)
    assert 'Registration(agent="match", version="match-v1"' in source and 'Registration(agent="council", version="council-v1"' in source
    assert match.VERSION == "match-v1" and council.VERSION == "council-v1" and contra.VERSION == "contra-v1"
    assert "It is born CHALLENGER" in source and "it is born CHALLENGER" in source


def test_the_limits_of_the_contracts_are_the_guides() -> None:
    sec = section(6)
    said(r"hasta (\d+) señales y (\d+) candidatos, y como mucho (\d+) referencias, (\d+) conductores y (\d+) riesgos", sec,
         aa.SIGNALS_MAX, aa.CANDIDATES_MAX, aa.REFS_MAX, aa.DRIVERS_MAX, aa.RISKS_MAX)
    said(r"hasta (\d+) conductores y (\d+) riesgos, y hasta (\d+) referencias", sec, cd.DRIVERS_MAX, cd.RISKS_MAX, aa.REFS_MAX)
    assert cd.VERDICTS_MAX == 12 and "como mucho una petición de investigación" in sec
    for word in get_args(base.Stance) + get_args(base.Verdict) + get_args(base.Level) + get_args(base.ResearchTopic):
        assert f"`{word}`" in sec, word
    assert "ni para pedir Opus" in sec
    # no field of a contract is a probability, a price, a stake, a URL, a query or SQL
    for model in (aa.AssessmentOut, cd.CouncilOut):
        assert base.forbidden_names(base.wire_schema(model)) == []
    assert "escalation" not in cd.CouncilOut.model_fields and "escalate" not in " ".join(cd.CouncilOut.model_fields)
    assert base.ASSESSMENT == "aa-v1" and base.COUNCIL == "cd-v1"


def test_what_the_server_does_with_an_answer_is_what_the_guide_says() -> None:
    sec = section(6)
    # an APPROVE with no driver or no reference that stands becomes ABSTAIN; a REJECT with no reference too
    out = cd.CouncilOut(contract="cd-v1", research=[], verdicts=[
        cd.SelectionVerdict(candidate="c1", verdict="APPROVE", confidence="HIGH", drivers=[], risks=[], refs=[]),
        cd.SelectionVerdict(candidate="c2", verdict="REJECT", confidence="HIGH", drivers=["NEWS"], risks=[], refs=[])])
    got = cd.check(out, asked={"c1", "c2"}, evidence_ids=set(), paths=set(), assessments=set())
    assert [v.verdict for v in got.council.verdicts] == ["ABSTAIN", "ABSTAIN"] and got.valid
    # a candidate that was not asked, one that is missing, a reference that is nowhere: invalid as a whole
    bad = cd.check(out, asked={"c1", "c3"}, evidence_ids=set(), paths=set(), assessments=set())
    assert not bad.valid and any(p.startswith("candidate_not_asked") for p in bad.problems) and any(p.startswith("candidate_missing") for p in bad.problems)
    assert "se descarta entera" in sec and "pasan a `ABSTAIN`" in sec and "**Un veredicto del Council nunca sube un estado**" in sec
    assert match.ORDER_LIKE == "instruction_like" and "`instruction_like`" in sec


def test_text_from_outside_is_data_in_every_prompt_of_the_phase() -> None:
    sec = section(6)
    for system in (prompt_labels.MATCH_CONTEXT_SYSTEM, prompt_labels.MATCH_ASSESS_SYSTEM, prompt_labels.COUNCIL_SYSTEM, prompt_labels.COUNCIL_OPUS_SYSTEM):
        assert "untrusted" in system.lower()
    assert "bloques `untrusted`" in sec and "nunca lleva una dirección web" in sec
    assert council._URL.search("see https://example.com/page") is not None, "the view strips what this pattern finds"


def test_the_view_of_the_council_is_under_ten_thousand_real_tokens_and_is_cut_in_the_guides_order() -> None:
    sec = section(6)
    said(r"de menos de \*\*([\d.]+)\*\* tokens reales", sec, council.VIEW_CAP)
    assert council.VIEW_VERSION == "council-view-v1" and "`council-view-v1`" in sec
    steps = [name for name, _ in council._STEPS]
    assert steps[:3] == ["h2h_detail", "form_detail", "standings_detail"] and "summaries_120" in steps and "summaries_60" in steps
    assert "`view_too_large`" in sec and "view_too_large" in ORCH_SRC
    assert frozenset({"PROBABLE", "RUMOR"}) == council.DROPPABLE_STATUS and "PROBABLE o RUMOR" in sec


def test_opus_goes_only_where_a_rule_fires_three_times_a_day_shared_by_the_arms_of_the_multiagent() -> None:
    sec = section(6)
    said(r"tope es de \*\*(\d+) llamadas por día de Bogotá\*\*", sec, router.PARAMS["opus_calls"]["shadow"])
    assert router.ESCALATIONS == ("E1", "E2", "E3", "E4", "E5", "E6", "E7") and "**E1 a E7**" in sec
    assert "escalation_skipped" in sec and "escalation_skipped" in ORCH_SRC
    assert "COUNCIL SOLO no se escala nunca" in sec and "if arm.engine not in WITH_MATCH or arm.reading is None:" in ORCH_SRC
    # a model cannot ask for Opus: the facts are built from code
    assert "researched=False" in ORCH_SRC and "escalation_facts(" in ORCH_SRC
    assert "day_bounds(local_day(at))" in inspect.getsource(orchestrator_store.opus_today)
    assert "shared.shared = True" in ORCH_SRC and "compartido por los dos brazos del multiagente" in sec


# ── 7. the contradictions ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_eight_contradictions_and_their_thresholds_are_the_guides() -> None:
    sec = section(7)
    rows = table(sec, "| Código")
    assert [r[0] for r in rows] == list(CONTRA_CODES) == ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"]
    p = contra.PARAMS
    said(r"a (\d+) días o menos .*? al menos (\d+) titulares", rows[2][1], p["rotation_days"], p["usual_starters_out"])
    assert p["usual_starters_out"] == router.PARAMS["e3_usual_starters_out"] and p["model_market_gap"] == router.PARAMS["e6_gap"]
    said(r"menor que ([\d,]+)", rows[4][1], D(p["referee_multiplier_below"]))
    said(r"supera ([\d,]+)", rows[5][1], D(p["model_market_gap"]))
    assert p["conflicting_evidences"] == 2 and "dos o más evidencias" in rows[6][1]
    assert "`settled`" in rows[3][1] and "settled" in contra.PRESSURES
    assert "contradiction" in " ".join(rows[7]).lower() or "objeta" in rows[7][1]
    assert contra.INPUT_MISSING == "input_missing" and "`input_missing`" in sec
    assert contra.VERSION == "contra-v1" and "`contra-v1`" in sec
    assert "No copia nunca un texto que vino de fuera" in sec


def test_c05_cannot_fire_yet_because_no_builder_writes_the_referee_multiplier() -> None:
    sec = section(7)
    assert "**C05 todavía no puede dispararse**" in sec
    assert "No builder writes ``shared.referee.multiplier`` yet" in inspect.getsource(contra)
    assert "con la porción de estadísticas" in sec and "slice carries no figures to tell the usual starters by" in inspect.getsource(contra)


# ── 8. the guards ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_guards_are_the_numbers_of_the_runtime() -> None:
    rows = {r[0]: r[1] for r in table(section(8), "| Guarda")}
    assert list(rows) == ["Concurrencia", "Circuito (uno por modelo)", "Reintentos", "Plazo de T-15", "Pausa de un brazo"]
    c = runtime.CONCURRENCY
    said(r"como mucho (\d+) llamadas de Haiku, (\d+) de Sonnet y (\d+) de Opus", rows["Concurrencia"], c["simple"], c["complex"], c["critical"])
    assert c == {"simple": 4, "complex": 3, "critical": 1}
    said(r"hasta (\d+) s un hueco", rows["Concurrencia"], int(orchestrator.SLOT_WAIT_S))
    said(r"con (\d+) fallos seguidos, o con más del (\d+) % de fallos en (\d+) minutos si hay al menos (\d+) llamadas", rows["Circuito (uno por modelo)"],
         runtime.FAILURES_IN_A_ROW, runtime.ERROR_RATE_PERCENT, int(runtime.RATE_WINDOW.total_seconds() // 60), runtime.MIN_CALLS)
    said(r"rechaza toda llamada (\d+) minutos", rows["Circuito (uno por modelo)"], int(runtime.OPEN_FOR.total_seconds() // 60))
    said(r"como mucho (\d+) reintentos .*? esperas de (\d+), (\d+) y (\d+) segundos \(tope de (\d+)\)", rows["Reintentos"], runtime.MAX_RETRIES,
         *(int(runtime.backoff_s(n)) for n in (1, 2, 3)), int(runtime.BACKOFF_CAP_S))
    for code in ("timeout", "unavailable", "rate_limited"):
        assert code in runtime.RETRYABLE_CODES and f"`{code}`" in rows["Reintentos"]
    assert runtime.retryable("invalid_output") is False and runtime.retryable("limit_reached") is False and runtime.retryable("over_budget") is False
    said(r"estrictamente antes de las (\d+) minutos previos .*? dure (\d+) minutos", rows["Plazo de T-15"],
         int(runtime.FINAL_MARGIN.total_seconds() // 60), int(orchestrator.EXPECTED.total_seconds() // 60))
    said(r"menos (\d+) segundos, y no se hace con menos de (\d+) segundos", rows["Plazo de T-15"], 5, int(orchestrator.MIN_CALL_S))
    said(r"pasa del (\d+) % de salidas inválidas en el día con al menos (\d+) pasadas", rows["Pausa de un brazo"], runtime.INVALID_LIMIT_PERCENT, runtime.MIN_CALLS_FOR_RATE)
    assert "left - 5.0" in ORCH_SRC


def test_the_deadline_the_circuit_and_the_pause_behave_as_the_guide_says() -> None:
    from datetime import UTC, datetime, timedelta
    kick = datetime(2026, 11, 4, 20, 0, tzinfo=UTC)
    expected = orchestrator.EXPECTED
    deadline = kick - timedelta(minutes=15)
    assert runtime.verdict("final", kick, deadline - expected - timedelta(seconds=1), expected) == "go"
    assert runtime.verdict("final", kick, deadline - expected, expected) == "too_late", "ending at T-15 exactly is already late"
    # the pause: 34 calls is the fewest for which one bad answer is already over 3 %; fewer say nothing
    assert runtime.arm_pause(invalid=1, calls=33, circuit_state="closed", envelope_left_usd=D(1)) == []
    assert runtime.arm_pause(invalid=2, calls=34, circuit_state="closed", envelope_left_usd=D(1)) == [runtime.PAUSE_INVALID]
    assert runtime.arm_pause(invalid=0, calls=0, circuit_state="open", envelope_left_usd=D(1)) == [runtime.PAUSE_CIRCUIT]
    assert runtime.arm_pause(invalid=0, calls=0, circuit_state="half_open", envelope_left_usd=D(0)) == [runtime.PAUSE_ENVELOPE]
    # one circuit and one set of slots per process
    assert orchestrator.process_circuit() is orchestrator.process_circuit() and orchestrator.process_slots() is orchestrator.process_slots()
    assert "**un** circuito por proceso" in section(8)
    # a paused arm skips and does not change model: the router has no input for a failed call
    assert "nunca otro modelo ni otra petición" in section(8) and "**no** cambia de modelo ni de petición" in section(8)


# ── 9. the budget ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_budget_figures_are_the_owners_action_15_and_the_stops_are_the_orchestrators() -> None:
    sec = section(9)
    said(r"tope de la Console de PREDIGOL-LAB es de \*\*(\d+)\*\* US\$ y el sobre interno del servidor \(`FBI_AI_LAB_MONTHLY_BUDGET_USD`\) de \*\*(\d+)\*\*", sec, 60, 55)
    action = ACTIONS[ACTIONS.index("## Acción 15"):ACTIONS.index("## Acción 16")]
    assert "«Monthly limit»: `60`; avisos en `30`, `42`, `51` y `57`" in action and "`FBI_AI_LAB_MONTHLY_BUDGET_USD=55`" in action
    assert "fases 3 a 8" in sec and "fase 9 vuelven a 20 y 15" in sec
    final = ACTIONS[ACTIONS.index("## Acción 16"):]
    assert "`20`" in final and "`FBI_AI_LAB_MONTHLY_BUDGET_USD=15`" in final
    for reason in ("no_envelope", "api_limit", "yields_to_production", "allocation_spent", "insufficient", "exhausted"):
        assert reason in orchestrator.BUDGET_STOPS and f"`{reason}`" in sec
    assert orchestrator.budget_stop_reason(True, D(1), "ok", D(2)) == "insufficient" and orchestrator.budget_stop_reason(True, D(2), "ok", D(2)) is None
    assert orchestrator.budget_stop_reason(False, D(0), "no_envelope", D(0)) == "no_envelope"
    assert D("1.10") == orchestrator.ESTIMATE_MARGIN and "un 10 % de margen" in sec
    assert orchestrator.SYNC_FACTOR == 2 and "ai.limit_hits" not in sec
    assert "enforced_spend_limit_reached" in sec and "enforced_spend_limit_reached" in (SRC / "ai" / "providers" / "anthropic.py").read_text(encoding="utf-8")
    from fbi.ai import budget_v3 as usage
    said(r"\((\d+) minutos, que se duplica hasta (\d+) horas\)", sec, int(usage.LIMIT_COOLDOWN.total_seconds() // 60), int(usage.LIMIT_COOLDOWN_MAX.total_seconds() // 3600))
    assert "tier_<nivel>_not_allowed" in sec and 'f"tier_{tier}_not_allowed"' in ORCH_SRC
    assert "self.exhausted = True" in ORCH_SRC and 'self.tally.budget_stop = "exhausted"' in ORCH_SRC


def test_the_lab_does_not_run_with_no_envelope_and_the_default_is_no_envelope() -> None:
    assert AiSettings().lab_monthly_budget == 0
    assert "El LAB corre un día entero o no corre" in section(9)
    from fbi.ai import budget_v3
    assert "no_envelope" in inspect.getsource(budget_v3.lab_day)


# ── 10. the leak rules ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_two_rules_are_in_the_nightly_audit_and_only_the_second_needs_rows() -> None:
    sec = section(10)
    rows = {r[0].strip("`"): r[1] for r in table(sec, "| Regla")}
    assert set(rows) == {"agent_known", "shadow_review_known"}
    assert leakage.RULE_NAMES[-3:] == ("slice_known", "agent_known", "shadow_review_known")
    assert set(leakage.PYTHON_RULES) >= set(rows)
    assert frozenset({"shadow_review_known"}) == leakage.NEEDS_DATA and "**la única regla cuyo silencio significa algo**" in sec
    assert leakage.passes_gate("shadow_review_known", 0, 0) is False and leakage.passes_gate("shadow_review_known", 3, 0) is True
    assert leakage.passes_gate("shadow_review_known", 3, 1) is False and leakage.passes_gate("agent_known", 0, 0) is True
    assert "intel.audit_checks.n_checked" in sec and "07:50 de Bogotá" in sec and leakage.VERSION == "leak-audit-v8"
    assert (leakage.INTEL_NIGHTLY_HOUR if hasattr(leakage, "INTEL_NIGHTLY_HOUR") else 7) == scheduler.INTEL_NIGHTLY_HOUR == 7 and scheduler.INTEL_NIGHTLY_MINUTE == 50
    for shadow in config.SHADOW_ENGINES:
        assert shadow in leakage.SHADOW_REVIEWS
    assert "ai.agent_runs" in leakage.AGENT_RUNS and "ai.pick_reviews" in leakage.SHADOW_REVIEWS
    # what the rules find: the codes of what is wrong with one run or one review
    for code in ("known_after_start", "no_known_at", "known_after_kickoff", "package_unknown", "package_late", "parent_missing", "parent_other_match", "parent_after"):
        assert code in inspect.getsource(leakage.run_problems)
    for code in ("packet_unknown", "packet_late", "moment_late", "after_kickoff"):
        assert code in inspect.getsource(leakage.review_problems)


# ── 11. the Console ───────────────────────────────────────────────────────────────────────────────────────────────

def test_the_console_lists_the_six_engines_and_names_the_shadow_ones() -> None:
    sec = section(11)
    assert get_args(ai_layer_routes.Engine) == ("rules", "llm", "combined", "ma-v1", "ma-v1-h", "cs-v1")
    assert "`combined` (de serie), `rules`, `llm`, `ma-v1`, `ma-v1-h` y `cs-v1`" in sec
    es = (MONOREPO / "web" / "src" / "locales" / "es" / "ai.json")
    if es.is_file():
        text = es.read_text(encoding="utf-8")
        for label in ("Multiagente (sombra)", "Multiagente + Council Haiku (sombra)", "Council solo (sombra)"):
            assert label in text and f"«{label}»" in sec
        assert "Motor en sombra: sus revisiones se guardan para evaluarlo y nunca llegan a la capa de decisión ni a los usuarios." in text
        admin = (MONOREPO / "web" / "src" / "locales" / "es" / "admin.json").read_text(encoding="utf-8")
        for tab in ("Trabajo de la IA", "Revisiones", "Agentes", "La IA frente al modelo"):
            assert f'"{tab}"' in admin, tab
    from fbi.api.services import ai_agents
    assert ai_agents.AUDIT_RULES == ("slice_known", "agent_known", "review_known", "shadow_review_known")
    assert "(`slice_known`, `agent_known`, `review_known` y `shadow_review_known`)" in sec
    assert "Contradicciones" in sec and "Sombra con brazos y muestras" in sec


def test_the_shadow_report_by_engine_is_written_only_when_something_settled() -> None:
    from fbi.ai import shadow
    assert shadow.ENGINES == ("rules", "llm", "combined", "ma-v1", "ma-v1-h", "cs-v1") and shadow.REPORTED_EMPTY == ("rules", "combined")
    assert "no deja filas vacías" in section(11)


# ── 12. gate B and action 15 ──────────────────────────────────────────────────────────────────────────────────────

def test_gate_b_asks_what_the_plan_asks_and_says_what_is_not_built() -> None:
    sec = section(12)
    rows = table(sec, "| Exigencia")
    assert len(rows) == 8
    plan = Path("/home/claude/project_docs/PLAN_MAESTRO_IA_INTELLIGENCE.md")
    if plan.is_file():
        line = next(x for x in plan.read_text(encoding="utf-8").splitlines() if x.startswith("| B · Sombra funcional"))
        for fragment in ("0 pasadas `final` fuera de plazo", "≤ 3 % de salidas inválidas por agente", "0 pagos duplicados", "atribución en ≥ 95 %",
                         "batería adversaria en verde", "Research v2 con ≥ 95 % de las evidencias de v1"):
            assert fragment in line
    assert "no tiene hoy un comando que lo evalúe" in sec
    assert not list((BACKEND / "scripts").glob("*gate_b*")) and not list((BACKEND / "scripts").glob("ia_gate_b*"))
    # unique index of paid runs: no duplicated payment
    assert "ai_agent_runs_paid_once" in sec and "ai_agent_runs_paid_once" in (next((BACKEND / "migrations" / "versions").glob("0111_*.py"))).read_text(encoding="utf-8")
    # the attribution of settled matches is not built
    assert "no construido" in rows[7][2]
    assert not [p for p in (SRC / "ai").glob("*.py") if re.search(r"attribution", p.read_text(encoding="utf-8"), flags=re.I)]
    assert "ia_battery" in rows[1][1] and "ia_research_gate" in rows[2][1]
    assert (BACKEND / "scripts" / "ia_battery.py").is_file() and (BACKEND / "scripts" / "ia_research_gate.py").is_file()


def test_the_owner_has_one_new_action_and_it_is_the_one_the_list_has() -> None:
    sec = section(12)
    assert "**Tu acción 15**" in sec and "No hay más acciones tuyas nuevas en esta fase" in sec
    assert "## Acción 15 · Al empezar la fase 3" in ACTIONS and "**el arranque de la sombra**" in ACTIONS
    assert "`60` con avisos en 30, 42, 51 y 57" in sec and "`FBI_AI_LAB_MONTHLY_BUDGET_USD=55`" in sec


# ── 13. what the code does less than the plan ─────────────────────────────────────────────────────────────────────

def test_the_deviations_are_eight_and_each_one_is_shown_by_the_code() -> None:
    sec = section(13)
    rows = table(sec, "| Id")
    assert [r[0] for r in rows] == [f"D{i}" for i in range(1, 9)]
    # D1: COUNCIL SOLO is an engine of the shadow beyond the two the plan's text names, and it is the owner's to accept or to remove
    assert "cs-v1" in config.SHADOW_ENGINES and "Aceptarlo o quitarlo es decisión tuya." in rows[0][2]
    assert "cs-v1" not in ON["FBI_AI_ENGINES"] and "tercer motor de la sombra" in rows[0][1]
    plan_activation = "rules,llm,ma-v1,ma-v1-h"
    assert "cs-v1" not in plan_activation
    # D2: the Batch calendar is built: the queue is the orchestrator's, the poll keeps the raw answer, and a Batch pass never goes back to real time
    imports = re.findall(r"^(?:from|import) fbi\.ai\.batch.*$", ORCH_SRC, flags=re.M)
    assert imports == ["from fbi.ai.batch import BatchClient, BatchQueue, Task, estimate_cost"]
    assert "def ask_batch(" in ORCH_SRC and "def ask(" in ORCH_SRC and "calendario de Batch está construido" in rows[1][1]
    assert 'elif kind == "shadow":' in (SRC / "ai" / "lab.py").read_text(encoding="utf-8") and "`other`" in rows[1][1]
    assert "batch_too_late" in rows[1][1] and "no está medido" in rows[1][1]
    # D3: the research that a model asks for is ignored, and the council has one round
    assert "research_ask_ignored" in ORCH_SRC and '"round": 1' in ORCH_SRC and "ignored_asks" in ORCH_SRC
    # D4: neither the pick of the day nor the legs of the parlay nor a research is known to the shadow
    assert "pick_of_the_day=()" in ORCH_SRC and "main_parlay_legs=()" in ORCH_SRC and "researched=False" in ORCH_SRC
    facts = router.Facts(council_confidence="LOW")
    assert router.fired_rules(facts) == ()
    # D5: the caps by share are read against the allocation of the month the LAB has, not the day's
    assert "allocation_usd=room.allocation" in ORCH_SRC and "room.allocation" in ORCH_SRC
    assert "the month's allocation" in (SRC / "ai" / "budget_v3.py").read_text(encoding="utf-8") or "What the LAB may spend this month" in (SRC / "ai" / "budget_v3.py").read_text(encoding="utf-8")
    assert "Haiku 30 %, Council 65 %, Opus 30 % en la sombra" in rows[4][1]
    assert router.PARAMS["share"]["simple"] == "0.30" and router.PARAMS["share"]["council"] == "0.65" and router.PARAMS["share"]["opus"]["shadow"] == "0.30"
    # D6: the battery has three targets and none is the Match Agent or the Council
    assert TARGETS == ("review", "extract", "claims") and "(`review`, `extract`, `claims`)" in rows[5][1]
    # D7: a single instance, no queue to share; the second writer of a pass keeps nothing
    assert "max_instances=1" in SCHEDULER_SRC and "SKIP LOCKED" not in ORCH_SRC + STORE_SRC
    # D8: attribution (phase 5) is not built
    assert "fase 5" in rows[7][1] + rows[7][2]


def test_the_deviation_about_the_caps_by_share_is_true_whatever_the_lab_allocation() -> None:
    day = router.Day(allocation_usd=D("55"), scope="shadow", spent_opus_usd=D("5"))
    assert router.cap_reached("opus", day) is None, "5 USD of Opus in a day is far below 30 % of the month's 55"
    assert router.cap_reached("opus", router.Day(allocation_usd=D("55"), scope="shadow", opus_calls=3)) == "cap:opus_calls"
    assert router.cap_reached("opus", router.Day(allocation_usd=D("1.7"), scope="shadow", spent_opus_usd=D("5"))) == "cap:opus_share", (
        "against a day's 1.7 the same 5 USD would have closed the cap")


# ── 14. tests and what is missing ─────────────────────────────────────────────────────────────────────────────────

def test_what_is_missing_names_the_things_the_code_does_not_have_yet() -> None:
    sec = section(14)
    rows = table(sec, "| Falta")
    assert len(rows) == 8
    assert {r[1] for r in rows} == {"el tiempo", "yo, con tu palabra", "tú", "yo"}
    assert "ia_gate evaluate --record" in rows[0][2] and (BACKEND / "scripts" / "ia_gate.py").is_file()
    joined = " ".join(r[0] for r in rows)
    assert "calendario de Batch" not in joined, "the Batch calendar is built: it is not missing"
    for pending in ("Contradicciones", "Agentes", "Match y Council", "Sombra con brazos y muestras", "batería", "estadística de la sombra"):
        assert pending in joined, pending
    web = MONOREPO / "web" / "src"
    if web.is_dir():
        text = " ".join(p.read_text(encoding="utf-8", errors="ignore") for p in web.glob("live/*Live.tsx"))
        assert "Contradicciones" not in text, "the Console view of contradictions is built: take it off the list"
    assert "**terminada en el código y sin desplegar**" in sec


def test_the_deploy_leaves_the_three_words_undefined_in_the_worker() -> None:
    for example in (BACKEND / ".env.example", BACKEND / "deploy" / "vps" / "app.env.example"):
        text = example.read_text(encoding="utf-8")
        for name, value in (("FBI_AI_ENGINES", "rules,llm"), ("FBI_AI_SHADOW_SAMPLE", "0"), ("FBI_AI_AGENTS", "")):
            assert re.search(rf"^# {name}={re.escape(value)}$", text, flags=re.M), f"{example.name}: {name} must be commented out at its default"
    assert not re.search(r"^FBI_AI_(ENGINES|SHADOW_SAMPLE|AGENTS)=", (BACKEND / ".env.example").read_text(encoding="utf-8"), flags=re.M)
