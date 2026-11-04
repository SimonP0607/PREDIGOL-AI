"""The Phase 5 guide (``docs/owner/IA_FASE5.md``) says what the code does.

The guide is for the owner: it says what phase 5 is (the mechanical attribution of the shadow, the Post-Match Reviewer and the Learning Analyst, in the
LAB, reading nothing a decision reads), the two words that switch it on and how it goes back, the migration 0120, the rule of the attribution, what
each agent may write and how it is checked, the role that cannot promote, what the Console shows, what Gate B asks and how to measure it, and what the
code does LESS than the plan. This file reads the guide's tables and sentences and compares every figure, name and option with the constants,
settings, migration, registry and routes of the code - and where the guide says what the code DOES (a typo in the word is off, the daily step
attributes only when the word is on) it makes the code do it. If a constant changes the test fails until the guide says the new value, and if the
guide is edited to something else it fails the same way.

What is not compared is data and not code: the figures of the plan. The deviations the guide declares (section 10) are held both ways: the test makes
the code show each one, so a deviation that is fixed makes the test fail until the guide stops declaring it.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import get_args

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from fbi.ai import config, gates
from fbi.ai.agents import analyst, attribution, pmr, registry
from fbi.ai.battery import TARGETS
from fbi.ai.config import AiSettings
from fbi.ai.contracts import base, learning, postmatch
from fbi.ai.prompts import LA_VERSION, PMR_VERSION
from fbi.ai.usage import Purpose
from fbi.api.routers import ai_layer as ai_layer_routes
from fbi.api.services import ai_attribution
from fbi.intel import pm_questions

BACKEND = Path(__file__).resolve().parents[2]
MONOREPO = BACKEND.parent
DOCS = BACKEND / "docs"
SRC = BACKEND / "src" / "fbi"


def read_doc(*parts: str) -> str:
    """A document of the repository, with the typographic minus written as a hyphen. Where the documents are not shipped (an image with the code
    only) there is nothing to compare."""
    path = DOCS.joinpath(*parts)
    if not path.is_file():
        pytest.skip(f"no {path.name} next to the code", allow_module_level=True)
    return path.read_text(encoding="utf-8").replace("\N{MINUS SIGN}", "-")


GUIDE = read_doc("owner", "IA_FASE5.md")
PHASE_3 = read_doc("owner", "IA_FASE3.md")


# ── reading the document ──────────────────────────────────────────────────────────────────────────────────────────

def section(number: int) -> str:
    m = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", GUIDE, flags=re.S | re.M)
    assert m, f"section {number} is missing from the guide"
    return m.group(0)


def table(text: str, header: str, *, nth: int = 0) -> list[list[str]]:
    """The cells of the rows of the ``nth`` table whose header line starts with ``header`` (the header and its rule left out, the bold marks taken off)."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(header)]
    assert len(starts) > nth, f"the guide no longer has the table {header!r}"
    out: list[list[str]] = []
    for line in lines[starts[nth] + 2:]:
        if not line.startswith("|"):
            break
        out.append([cell.strip().replace("**", "") for cell in line.strip().strip("|").split("|")])
    return out


def ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def paths_in(text: str) -> set[str]:
    """The files a text names in backticks (a path with a slash and an extension)."""
    return set(re.findall(r"`([\w./-]+\.(?:py|sql|md|ts|tsx|sh))`", text))


def exists(path: str) -> bool:
    candidates = [BACKEND / path, SRC / path, BACKEND / "docs" / "owner" / path, MONOREPO / path, BACKEND / "deploy" / "vps" / path,
                  BACKEND / "deploy" / "vps" / "db" / path]
    return any(c.exists() for c in candidates)


def migration() -> ModuleType:
    path = next((BACKEND / "migrations" / "versions").glob("0120_*.py"))
    spec = importlib.util.spec_from_file_location("ia_migration_0120", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION_SRC = next((BACKEND / "migrations" / "versions").glob("0120_*.py")).read_text(encoding="utf-8")


# ── the guide as a whole ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_guide_has_its_eleven_sections_in_order() -> None:
    assert re.findall(r"^## (\d+)\. ", GUIDE, flags=re.M) == [str(n) for n in range(1, 12)]
    assert GUIDE.startswith("# Fase 5 del Plan Maestro IA")
    assert "`tests/unit/test_ia_fase5_docs.py`" in GUIDE


def test_every_file_the_guide_names_exists() -> None:
    missing = sorted(p for p in paths_in(GUIDE) if not exists(p))
    assert missing == [], missing


def test_the_guide_names_the_migration_it_ships_and_the_chain_ends_at_or_after_it() -> None:
    assert "migración 0120" in GUIDE and "La 0120 es **aditiva**" in section(3)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    revision = script.get_revision("0120")
    assert revision is not None and revision.down_revision == "0119"


# ── section 1: the pieces ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_pieces_are_where_the_guide_says() -> None:
    rows = table(section(1), "| Pieza")
    assert [r[0] for r in rows] == ["Atribución mecánica `attr-v1`", "Revisor posterior `pmr-v1`", "Analista de aprendizaje `la-v1`", "Camino al modelo",
                                    "Rol de la base", "Enganches", "Script", "Consola"]
    assert attribution.VERSION in rows[0][0] and PMR_VERSION in rows[1][0] and LA_VERSION in rows[2][0]
    for row in rows:
        for path in paths_in(row[2]):
            assert exists(path), path


def test_what_the_phase_writes_is_one_table_and_nobody_else_reads_it() -> None:
    sec = section(1)
    assert "`tests/unit/test_attribution_readers.py`" in sec
    assert (BACKEND / "tests" / "unit" / "test_attribution_readers.py").is_file()
    assert "intel.agent_attributions" in sec
    assert attribution.VERSION == "attr-v1" and registry.VERSION_LABEL.match(attribution.VERSION)


def test_the_agents_are_challengers_beside_the_ones_of_today() -> None:
    specs = {s.agent: s for s in registry.AGENTS}
    assert (specs["pmr"].replaces, specs["la"].replaces) == ("post_match_reviewer", "learning_analyst")
    assert "`pmr` nace junto a `post_match_reviewer` y `la` junto a `learning_analyst`" in section(1)
    ledger = {(r.agent, r.version) for r in registry.LEDGER}
    assert {("pmr", PMR_VERSION), ("la", LA_VERSION)} <= ledger


# ── section 2: the two switches ───────────────────────────────────────────────────────────────────────────────────

def test_the_two_switches_are_off_and_read_as_the_guide_says(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = table(section(2), "| Variable")
    assert [(r[0], r[1]) for r in rows] == [("`FBI_AI_PM_REVIEWER`", "apagada"), ("`FBI_AI_LEARNING_ANALYST`", "apagada")]
    assert rows[0][4] == "`0`" and rows[1][4] == "`0`"
    assert "07:35" in rows[0][3] and "`ai_learn`" in rows[0][3] and "lunes" in rows[1][3] and "`intel_weekly`" in rows[1][3]
    sec = section(2)
    assert "`1`, `on`, `true` y `yes` encienden" in sec
    for word, attr in (("FBI_AI_PM_REVIEWER", "pm_reviewer"), ("FBI_AI_LEARNING_ANALYST", "learning_analyst")):
        for raw, expected in (("1", True), ("on", True), (" TRUE ", True), ("Yes", True), ("0", False), ("", False), ("maybe", False), ("onn", False)):
            monkeypatch.setattr("fbi.ai.config.environment", lambda raw=raw, word=word: {word: raw})
            assert getattr(AiSettings.from_env(), attr) is expected, (word, raw)
        monkeypatch.setattr("fbi.ai.config.environment", dict)
        assert getattr(AiSettings.from_env(), attr) is False, "off when the owner said nothing"


def test_the_words_of_the_owner_reach_the_ledger_only_when_they_are_on(monkeypatch: pytest.MonkeyPatch) -> None:
    sec = section(2)
    assert "solo cuando están encendidas" in sec
    monkeypatch.setattr("fbi.ai.config.environment", dict)
    off = AiSettings.from_env()
    assert gates.phase5_words(off) == {}, "a default is not written to the ledger"
    monkeypatch.setattr("fbi.ai.config.environment", lambda: {"FBI_AI_PM_REVIEWER": "1", "FBI_AI_LEARNING_ANALYST": "1"})
    on = AiSettings.from_env()
    assert gates.phase5_words(on) == {"pm_reviewer": True, "learning_analyst": True}


def test_the_variables_are_in_the_examples_and_in_the_code() -> None:
    config_src = (SRC / "ai" / "config.py").read_text(encoding="utf-8")
    example = (BACKEND / ".env.example").read_text(encoding="utf-8")
    deploy = (BACKEND / "deploy" / "vps" / "app.env.example").read_text(encoding="utf-8")
    for word in ("FBI_AI_PM_REVIEWER", "FBI_AI_LEARNING_ANALYST"):
        assert word in config_src and word in example and f"# {word}=0" in deploy, word
    for word in re.findall(r"`(FBI_[A-Z0-9_]+)`", GUIDE):
        assert word in config_src, f"{word} is named by the guide and read by nothing"


def test_the_daily_step_attributes_only_when_the_word_is_on_and_the_weekly_one_asks_its_own() -> None:
    cycle = (SRC / "ai" / "cycle.py").read_text(encoding="utf-8")
    assert re.search(r"if settings\.pm_reviewer:\s*\n\s+.*_attributions\(", cycle), "the daily step attributes behind the word (D1)"
    weekly = (SRC / "intel" / "cycle.py").read_text(encoding="utf-8")
    assert "if not settings.learning_analyst:" in weekly and '("learning_analyst", _learning_analyst)' in weekly
    assert weekly.index('("learning_analyst", _learning_analyst)') < weekly.index('("matrix", _matrix)'), "before the matrix, as the guide says"
    assert "ayer y hoy" in section(2) and "antes de la matriz" in section(2)


# ── section 3: the migration ──────────────────────────────────────────────────────────────────────────────────────

def test_the_migration_is_what_section_three_says() -> None:
    sec = section(3)
    m = migration()
    assert (m.revision, m.down_revision) == ("0120", "0119")
    rows = table(sec, "| Qué")
    assert [r[0] for r in rows] == ["`intel.agent_attributions`", "`analytics.research_hypotheses`", "`analytics.experiments`"]
    for name in ("agent_attributions_append_only", "agent_attributions_once", "agent_attributions_one_refinement", "research_hypotheses_agent_pair",
                 "experiments_agent_pair"):
        assert name in sec, name
    assert "agent_attributions_append_only" in MIGRATION_SRC and "agent_attributions_once" in MIGRATION_SRC
    assert "agent_attributions_one_refinement" in MIGRATION_SRC
    assert "{short}_agent_pair" in MIGRATION_SRC
    assert "intel.refuse_change()" in sec and "EXECUTE FUNCTION intel.refuse_change()" in MIGRATION_SRC
    assert "Espera como máximo 10 segundos" in sec and "SET LOCAL lock_timeout = '10s'" in MIGRATION_SRC
    assert "REFERENCES" not in MIGRATION_SRC.upper().replace("REFERENCES NOTHING", ""), "no foreign key, as the guide says"
    assert "Sin claves foráneas" in sec


def test_the_vocabularies_of_the_table_are_the_ones_of_the_code() -> None:
    m = migration()
    assert m.CLASSES == pm_questions.CLASSES
    assert m.SHADOW_ENGINES == config.SHADOW_ENGINES
    assert get_args(postmatch.AttributionClass) == (*pm_questions.CLASSES, "NONE")
    assert get_args(learning.Subject) == m.SUBJECTS
    assert m.CLASSIFIERS == ("code", "pmr-v1")
    sec = section(4)
    for klass in pm_questions.CLASSES:
        assert f"`{klass}`" in sec, klass
    assert "`NONE`" in sec


# ── section 4: the rule ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_stances_are_the_ones_the_guide_lists() -> None:
    rows = table(section(4), "| Postura")
    assert [r[0] for r in rows] == ["a favor", "en contra", "sin partido"]
    assert set(ticked(rows[0][1])) == set(attribution.FOR_STANCES)
    assert set(ticked(rows[1][1])) == set(attribution.AGAINST_STANCES)
    assert set(ticked(rows[2][1])) == set(attribution.NO_SIDE)
    assert set(ticked(rows[0][2])) >= {"HIT", "MISS", "win", "half_win", "loss", "half_loss"}
    assert set(ticked(rows[0][2])) & {"win", "half_win", "loss", "half_loss"} == set(attribution.WON | attribution.LOST)
    assert set(ticked(rows[2][2])) == {"VOID", "push", "void"} and {"push", "void"} <= attribution.SETTLED
    assert set(attribution.WON | attribution.LOST | {"push", "void"}) == set(attribution.SETTLED)


def test_the_rule_does_what_the_guide_says_it_does() -> None:
    from decimal import Decimal

    assert attribution.polarity_of("APPROVE") == "FOR" and attribution.polarity_of("REJECT") == "AGAINST" and attribution.polarity_of("ABSTAIN") == "NONE"
    assert attribution.outcome_of("FOR", "win") == "HIT" and attribution.outcome_of("FOR", "loss") == "MISS"
    assert attribution.outcome_of("AGAINST", "loss") == "HIT" and attribution.outcome_of("AGAINST", "win") == "MISS"
    assert attribution.outcome_of("NONE", "win") == "VOID" and attribution.outcome_of("FOR", "push") == "VOID" and attribution.outcome_of("FOR", "void") == "VOID"
    assert attribution.class_of("AGAINST", "MISS", Decimal("-0.02"), None) == "NORMAL_VARIANCE"
    assert attribution.class_of("AGAINST", "MISS", Decimal("0.02"), None) == "UNKNOWN"
    assert attribution.class_of("FOR", "MISS", Decimal("0.02"), "MODEL_ERROR") == "MODEL_ERROR"
    assert attribution.class_of("FOR", "HIT", Decimal("0.02"), "MODEL_ERROR") == "NONE"
    assert set(get_args(postmatch.AttributionClass)) >= {"NONE", "UNKNOWN", "NORMAL_VARIANCE"}
    cal = attribution.calibration_of
    assert cal("win", Decimal("0.7"), Decimal("0.5"), Decimal("0.5")) == "MODEL_BETTER"
    assert cal("win", Decimal("0.3"), Decimal("0.5"), Decimal("0.5")) == "MARKET_BETTER"
    assert cal("win", Decimal("0.5"), Decimal("0.5"), Decimal("0.5")) == "EQUAL"
    assert cal("push", Decimal("0.5"), Decimal("0.5"), Decimal("0.5")) is None
    for word in ("MODEL_BETTER", "MARKET_BETTER", "EQUAL"):
        assert word in section(4), word
    assert attribution.SOURCES == ("live", "batch") and "`source = 'live'`" in section(4) and "`source = 'batch'`" in section(4)


# ── sections 5 and 6: the agents ──────────────────────────────────────────────────────────────────────────────────

def test_the_reviewer_is_what_section_five_says() -> None:
    sec = section(5)
    assert pmr.LOOKBACK.days == 7 and "los últimos 7 días" in sec
    assert pmr.MAX_CASES == 12 and "hasta 12 por vuelta" in sec
    assert pmr.MAX_STRONG_PER_DAY == 4 and "a lo sumo cuatro al día" in sec
    assert postmatch.NARRATIVE_MAX == 900 and "a lo sumo 900 caracteres" in sec
    assert pmr.NOTE_MAX == 240 and "de a lo sumo 240 caracteres" in sec
    assert pmr.PURPOSE == "postmortem" and "`ai.postmortem_narratives`" in sec and f"versión `{PMR_VERSION}`" in sec
    assert "**Haiku**" in sec and "**Sonnet**" in sec
    tasks = {t.task: str(t.model) for t in next(s for s in registry.AGENTS if s.agent == "pmr").tasks}
    assert set(tasks) == {"narrative", "loss_review"} and "haiku" in tasks["narrative"] and "sonnet" in tasks["loss_review"]
    assert "`fbi.ai.untrusted`" in sec


def test_the_analyst_is_what_section_six_says() -> None:
    sec = section(6)
    assert analyst.WINDOW.days == 7 and "los últimos 7 días" in sec
    assert analyst.MIN_STANCES == 30 and "menos de 30 posturas" in sec and "`too_few_stances`" in sec
    assert analyst.EXAMPLES == 3 and "hasta 3 filas" in sec
    assert analyst.GROUPS_MAX == 80 and "como mucho 80 grupos" in sec
    assert learning.HYPOTHESES_MAX == 5 and "a lo sumo cinco hipótesis por semana" in sec
    assert (learning.TITLE_MIN, learning.TITLE_MAX, learning.TEXT_MAX) == (5, 160, 600) and "de 5 a 160 caracteres" in sec and "a lo sumo 600" in sec
    assert analyst.PURPOSE == "learning" and analyst.ROLE == "predigol_learning" and "`predigol_learning`" in sec
    assert "`PROPOSED`" in sec and "`analytics.research_hypotheses`" in sec and "`intel.promotions`" in sec
    assert "too_few_stances" in (SRC / "ai" / "agents" / "analyst.py").read_text(encoding="utf-8")
    tasks = [str(t.model) for t in next(s for s in registry.AGENTS if s.agent == "la").tasks]
    assert len(tasks) == 1 and "sonnet" in tasks[0] and "(Sonnet)" in sec


def test_a_hypothesis_without_evidence_does_not_exist_and_one_with_foreign_evidence_is_dropped() -> None:
    sec = section(6)
    assert "una hipótesis que no cita nada no cumple el contrato" in sec
    with pytest.raises(ValueError):
        learning.Hypothesis.model_validate({"title": "Un título válido", "hypothesis": "h" * 10, "rationale": "r" * 10, "agent": "council", "agent_version": "council-v1",
                                            "attribution_ids": [], "experiment": {}})
    out = learning.LearningOut.model_validate({"contract": "la-v1", "hypotheses": []})
    verdict = analyst.check(out, versions={}, offered=[], cited={})
    assert verdict.standing == [] and base.LEARNING == "la-v1"
    for reason in ("unknown_version", "evidence_not_offered", "evidence_of_another_version"):
        assert reason in (SRC / "ai" / "agents" / "analyst.py").read_text(encoding="utf-8")


def test_the_role_is_in_the_database_files_and_cannot_promote() -> None:
    sec = section(6)
    roles = (BACKEND / "deploy" / "vps" / "db" / "roles.sql").read_text(encoding="utf-8")
    grants = (BACKEND / "deploy" / "vps" / "db" / "grants.sql").read_text(encoding="utf-8")
    assert "CREATE ROLE predigol_learning NOLOGIN" in roles and "`db/roles.sql`" in sec
    assert "GRANT SELECT, INSERT ON analytics.research_hypotheses TO predigol_learning" in grants
    assert not re.search(r"GRANT[^;]*intel\.promotions[^;]*predigol_learning", grants), "no grant on the promotions"
    assert (BACKEND / "tests" / "integration" / "test_learning_role.py").is_file()


# ── section 7: the Console ────────────────────────────────────────────────────────────────────────────────────────

def test_the_console_is_where_the_guide_says() -> None:
    sec = section(7)
    assert "`/admin/ai/attribution`" in sec and "de 1 a 60 días, 14 de serie" in sec
    paths = {getattr(r, "path", "") for r in ai_layer_routes.admin_router.routes}
    assert "/ai/attribution" in paths
    route = next(r for r in ai_layer_routes.admin_router.routes if getattr(r, "path", "") == "/ai/attribution")
    assert getattr(route, "methods", None) == {"GET"}
    import inspect

    param = inspect.signature(ai_layer_routes.get_attribution).parameters["days"]
    assert param.default == 14
    assert "ge=1" in str(param.annotation) and "le=60" in str(param.annotation)
    assert ai_attribution.BAR == 0.95 and "95 %" in sec
    web = MONOREPO / "web" / "src" / "live"
    if web.is_dir():
        assert '"attribution"' in (web / "adminAi.ts").read_text(encoding="utf-8")
        assert (web / "AttributionPanel.tsx").is_file()
    assert "cero partidos es un guion, no un 100 %" in sec and ai_attribution.share(0, 0) is None


# ── section 8: Gate B ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_script_is_what_section_eight_says() -> None:
    spec = importlib.util.spec_from_file_location("ia_attribution_script", BACKEND / "scripts" / "ia_attribution.py")
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    sec = section(8)
    assert script.GATE_B_SHARE == 0.95 and "≥ 95 %" in sec and "llega al 95 %" in sec
    assert (script.OK, script.NO, script.PENDING, script.CANNOT) == (0, 1, 3, 2)
    assert "Sale con 0 si llega al 95 %, 1 si no, 3 si todavía no hay ningún partido que juzgar y 2 si no puede correr" in sec
    assert tuple(script.COMMANDS) == ("coverage", "scoreboard", "recompute")
    for command in script.COMMANDS:
        assert f"python -m scripts.ia_attribution {command}" in sec, command
    assert "--dry-run" in sec and script.parse_day("2026-11-03").isoformat() == "2026-11-03"
    assert script.WINDOW.days == 14 and "los últimos 14 días" in sec
    assert "14 días de atribuciones" in sec and "dos informes semanales" in sec
    # the guide of phase 3 is a record of its day: it still says the attribution could not be measured then
    assert "**no construido**" in PHASE_3


def test_the_metrics_are_read_where_the_guide_says() -> None:
    rows = table(section(9), "| Métrica")
    assert len(rows) == 5
    assert "`ia_attribution coverage`" in rows[0][1] and "`ia_attribution scoreboard`" in rows[1][1]
    accepted = ai_attribution.COUNTS_SQL
    for status in ("ACCEPTED", "RUNNING", "SHADOW", "DONE", "PROMOTED"):
        assert f"'{status}'" in accepted and f"`{status}`" in rows[3][1], status
    assert "`postmortem`" in rows[4][1] and "`learning`" in rows[4][1] and {"postmortem", "learning"} <= set(get_args(Purpose))


# ── section 10: the deviations, held both ways ────────────────────────────────────────────────────────────────────

def deviations() -> dict[str, str]:
    return {r[0]: r[1] for r in table(section(10), "| Id")}


def test_the_deviations_are_the_ones_the_code_shows() -> None:
    d = deviations()
    assert list(d) == [f"D{n}" for n in range(1, 8)]
    # D1: the attribution of the daily step is behind the word
    assert "detrás de `FBI_AI_PM_REVIEWER`" in d["D1"]
    cycle = (SRC / "ai" / "cycle.py").read_text(encoding="utf-8")
    assert re.search(r"if settings\.pm_reviewer:", cycle)
    # D2: the agents have ids of their own and replace nobody by themselves
    assert "`pmr` y `la`" in d["D2"] and {s.agent for s in registry.AGENTS} >= {"pmr", "la"}
    assert all(s.agent in ("pmr", "la") or s.replaces != "post_match_reviewer" for s in registry.AGENTS)
    # D3: the role exists only when the operator creates it; without it the analyst writes as the worker
    assert "`roles.sql`" in d["D3"] and "no_role" in (SRC / "ai" / "agents" / "analyst.py").read_text(encoding="utf-8")
    # D4: the experiment is a draft inside the evidence of the hypothesis
    assert "borrador dentro de la evidencia" in d["D4"]
    assert "experiment" in (SRC / "ai" / "agents" / "analyst.py").read_text(encoding="utf-8")
    # D5: the cost is not measured - nothing in the code claims a measured cost for these two agents
    assert "no está medido" in d["D5"]
    # D6: the adversarial battery has no target for the two prompts
    assert tuple(TARGETS) == ("review", "extract", "claims") and "pmr" not in TARGETS and "la" not in TARGETS
    # D7: the production engines have no agent to attribute
    assert set(config.SHADOW_ENGINES) == {"ma-v1", "ma-v1-h", "cs-v1"}
    assert all(f"`{e}`" in d["D7"] for e in ("rules", "llm", "combined"))


# ── section 11: the tests ─────────────────────────────────────────────────────────────────────────────────────────

def test_every_test_the_guide_names_exists() -> None:
    sec = section(11)
    named = re.findall(r"`((?:tests/[\w/]+\.py)|(?:web/src/[\w/]+\.tsx?))`", sec)
    assert len(named) >= 15
    for path in named:
        assert (MONOREPO / path).is_file() if path.startswith("web/") else (BACKEND / path).is_file(), path
    assert "`tests/unit/test_ia_fase5_docs.py`" in sec


def test_what_is_missing_is_what_the_guide_says_it_is() -> None:
    rows = table(section(11), "| Falta")
    assert [r[0] for r in rows][:2] == ["Desplegar la fase apagada", "Ejecutar `roles.sql` y `grants.sql`"]
    assert "terminada en el código y sin desplegar" in section(11)
    assert (BACKEND / "deploy" / "vps" / "db" / "roles.sql").is_file()
