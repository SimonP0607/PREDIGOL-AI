"""The Phase 4 guide (``docs/owner/IA_FASE4.md``) says what the code does.

The guide is for the owner: it says what the Statistics Agent in the shadow is (corners and cards of the whole match, in the LAB, reading nothing a
decision reads), the one word that switches it on and the way back, that there is no migration, what the agent asks and what the server makes of
the answer, how candidates are named, the DESCRIPTIVE factors, what the Council of the arms reads, which engines the phase did NOT add, C05 and C08
by family, what the shadow can measure for Gate B (and that it never says pass), and what the code does LESS than the plan. This file reads the
guide's tables and sentences and compares every figure, name and option with the constants, settings and sources of the code - and where the guide
says what the code DOES (``stats`` alone switches nothing on, a half is never named, the report is never a pass) it makes the code do it. If a
constant changes the test fails until the guide says the new value, and if the guide is edited to something else it fails the same way.

The deviations the guide declares (section 11) are held both ways where the code can show them. Not compared: the plan's figures (the 14 days are the
plan's and ARE compared with the constant that holds them) and the measures nobody has made yet.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal
from functools import cache as memo
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import config, contra, orchestrator, prompts, router, shadow, stats_factors
from fbi.ai import package as mcp_package
from fbi.ai.agents import registry as agent_registry
from fbi.ai.agents import stats
from fbi.ai.agents.common import HALF_TOKENS, NAMING_COUNTS_VERSION, NAMING_VERSION
from fbi.ai.config import AiSettings
from fbi.ai.contracts.assessment import CANDIDATES_MAX

BACKEND = Path(__file__).resolve().parents[2]
MONOREPO = BACKEND.parent
DOCS = BACKEND / "docs"
SRC = BACKEND / "src" / "fbi"
D = Decimal


def read_doc(*parts: str) -> str:
    path = DOCS.joinpath(*parts)
    if not path.is_file():
        pytest.skip(f"no {path.name} next to the code", allow_module_level=True)
    return path.read_text(encoding="utf-8").replace("\N{MINUS SIGN}", "-")


GUIDE = read_doc("owner", "IA_FASE4.md")
PHASE_3 = read_doc("owner", "IA_FASE3.md")
ORCH_SRC = (SRC / "ai" / "orchestrator.py").read_text(encoding="utf-8")
CONTRA_SRC = (SRC / "ai" / "contra.py").read_text(encoding="utf-8")


def section(number: int) -> str:
    m = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", GUIDE, flags=re.S | re.M)
    assert m, f"section {number} is missing from the guide"
    return m.group(0)


def table(text: str, header: str) -> list[list[str]]:
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(header)]
    assert starts, f"the guide no longer has the table {header!r}"
    out: list[list[str]] = []
    for line in lines[starts[0] + 2:]:
        if not line.startswith("|"):
            break
        out.append([cell.strip().replace("**", "") for cell in line.strip().strip("|").split("|")])
    return out


def ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def settings_of(monkeypatch: pytest.MonkeyPatch, **env: str) -> AiSettings:
    monkeypatch.setattr("fbi.ai.config.environment", lambda: env)
    return AiSettings.from_env()


# ── the header and the whole guide ────────────────────────────────────────────────────────────────────────────────

SECTION_TITLES = [
    "Qué es la Fase 4 y qué no toca",
    "El interruptor y la vuelta atrás",
    "Sin migración",
    "El Agente de Estadísticas: qué pregunta y qué hace el servidor con la respuesta",
    "Los nombres de los candidatos y lo que nunca se nombra",
    "Los factores DESCRIPTIVOS",
    "En la sombra: qué lee el Council, el Batch y las fugas",
    "Motores y lectores: qué se decidió",
    "Contradicciones por familia: C05 y C08",
    "Lo que se puede medir para el gate B",
    "Desviaciones y límites declarados",
    "Las pruebas y lo que falta",
]


def test_the_sections_are_1_to_12_in_order_and_the_header_says_where_the_phase_stands() -> None:
    titles = dict(re.findall(r"^## (\d+)\. (.*)$", GUIDE, flags=re.M))
    assert [int(n) for n in titles] == list(range(1, 13))
    assert list(titles.values()) == SECTION_TITLES
    assert GUIDE.startswith("# Fase 4 del Plan Maestro IA · El Agente de Estadísticas en sombra: córners y tarjetas\n")
    head = GUIDE.split("## 1.", 1)[0]
    assert "todavía sin desplegar" in head and "no lleva migración" in head
    assert "tests/unit/test_ia_fase4_docs.py" in head and Path(__file__).name == "test_ia_fase4_docs.py"
    assert "`IA_FASE3.md`" in head and "tests/unit/test_ia_fase3_docs.py" in PHASE_3


def test_the_documents_it_leans_on_exist_and_it_carries_no_key_and_no_gap() -> None:
    for name in set(re.findall(r"`?(IA_[A-Z0-9_]+\.md)`?", GUIDE)):
        assert (DOCS / "owner" / name).is_file(), name
    assert not re.search(r"sk-[A-Za-z0-9_-]{8,}", GUIDE), "a key (or something shaped like one) in the guide"
    assert "@@" not in GUIDE and "[[" not in GUIDE, "a placeholder left in the guide"


ROOTS = ((BACKEND / "src", (".py", ".sql", ".json")), (BACKEND / "scripts", (".py", ".sh", ".sql")), (BACKEND / "migrations", (".py",)),
         (BACKEND / "docs", (".md",)), (BACKEND / "tests", (".py",)), (BACKEND / "apps", (".py",)))
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@memo
def vocabulary() -> frozenset[str]:
    """Every identifier-like word of the code, scripts, migrations, other documents and tests (this guide and this file left out: they would vouch
    for themselves), and the stem of every file's name."""
    skip = {(DOCS / "owner" / "IA_FASE4.md").resolve(), Path(__file__).resolve()}
    words: set[str] = set()
    for root, extensions in ROOTS:
        for folder, folders, files in os.walk(root, followlinks=True):
            folders[:] = [f for f in folders if f not in {".venv", "node_modules", "__pycache__"}]
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


def test_the_pieces_are_files_that_exist_and_the_tests_it_names_exist() -> None:
    for row in table(section(1), "| Pieza"):
        for name in ticked(row[2]):
            assert (BACKEND / name).is_file() if name.startswith("scripts/") else (SRC / name).is_file(), f"{name} (piece {row[0]!r})"
    names = set(re.findall(r"`(tests/[a-z_/0-9]+\.py)`", GUIDE))
    assert len(names) >= 7
    for name in names:
        assert (BACKEND / name).is_file(), name
    assert set(re.findall(r"FBI_[A-Z0-9_]*[A-Z0-9]", GUIDE)) == {"FBI_AI_AGENTS"}, "the phase adds no variable"
    assert "FBI_AI_AGENTS" in (SRC / "ai" / "config.py").read_text(encoding="utf-8")


# ── 1 and 2. what it does not touch, the word and the way back ────────────────────────────────────────────────────

ON = {"FBI_AI_MODE": "shadow", "FBI_AI_ENGINES": "rules,llm,ma-v1,ma-v1-h", "FBI_AI_SHADOW_SAMPLE": "0.3", "FBI_AI_AGENTS": "match,council,stats"}


def test_the_word_the_defaults_the_activation_and_the_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    sec = section(2)
    [row] = table(sec, "| Variable")
    assert row[0].strip("`") == "FBI_AI_AGENTS" and row[1] == "vacío" and AiSettings().agents == ()
    assert row[3].strip("`") == "match,council,stats" and row[4].strip("`") == "match,council"
    assert config.AGENTS == ("match", "council", "stats") and set(re.findall(r"`(match|council|stats)`", row[2])) == set(config.AGENTS)
    assert "FBI_AI_AGENTS=match,council,stats" in sec and "FBI_AI_AGENTS=match,council`" in sec
    on = settings_of(monkeypatch, **ON)
    assert on.orchestrate is True and on.agents == ("match", "council", "stats") and on.shadow_engines == ("ma-v1", "ma-v1-h")
    rollback = settings_of(monkeypatch, **{**ON, "FBI_AI_AGENTS": row[4].strip("`")})
    assert rollback.orchestrate is True and rollback.agents == ("match", "council"), "the shadow of phase 3 stays"
    # ``stats`` alone, or without one of the two, switches nothing on; a name that is none is dropped
    for agents in ("stats", "stats,match", "stats,council", ""):
        assert settings_of(monkeypatch, **{**ON, "FBI_AI_AGENTS": agents}).orchestrate is False, agents
    assert settings_of(monkeypatch, **{**ON, "FBI_AI_AGENTS": "match,council,stats,player"}).agents == ("match", "council", "stats")
    assert "`stats` por sí solo no enciende nada" in sec


def test_what_the_phase_does_not_touch_is_what_the_default_leaves_alone() -> None:
    sec = section(1)
    off = AiSettings()
    assert off.engines == ("rules", "llm") and off.agents == () and off.orchestrate is False
    assert config.SHADOW_ENGINES == ("ma-v1", "ma-v1-h", "cs-v1"), "the phase adds no engine"
    assert set(re.findall(r"`(ma-v1-h|ma-v1|cs-v1)`", sec)) == set(config.SHADOW_ENGINES)
    for forbidden in ("INSERT INTO ai.evidence", "INSERT INTO ai.fixture_passes"):
        assert forbidden not in ORCH_SRC
    assert "ni los motores de `ai.pick_reviews`" in sec and "ni `ai.evidence` ni `ai.fixture_passes`" in sec


# ── 3. no migration ───────────────────────────────────────────────────────────────────────────────────────────────

def test_there_is_no_migration_of_phase_4() -> None:
    versions = sorted(p.name for p in (BACKEND / "migrations" / "versions").glob("[0-9]*_*.py"))
    # phase 4 adds none: the last one it knew is 0119 (phase 5 adds the 0120 after it, and that one has nothing to do with the Statistics Agent)
    assert any(name.startswith("0119_") for name in versions) and not any("stats" in name for name in versions)
    sec = section(3)
    assert "la última sigue siendo la 0119" in sec and "Una migración `0120` no hizo falta" in sec
    assert "ON CONFLICT (factor, version) WHERE previous_id IS NULL DO NOTHING" in (SRC / "ai" / "stats_factors.py").read_text(encoding="utf-8")


# ── 4. the agent ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_agent_table_says_what_the_router_and_the_registry_say() -> None:
    [row] = table(section(4), "| Quién")
    assert row[0] == "Agente de Estadísticas" and row[1] == "evaluación"
    assert stats.TASK == "evaluation" and stats.MODE == "EVALUATION" and stats.AGENT == "stats" and stats.VERSION == "stats-v2"
    assert row[2] == f"Haiku (`{stats.model_of()}`)" and stats.model_of() == "claude-haiku-5-5"
    assert row[3].strip("`") == stats.effort_of() == "medium"
    assert row[4].strip("`") == prompts.STATS_ASSESS_VERSION == "stats-assess-v2" and row[5].strip("`") == "aa-v1"
    assert stats.model_of() == router.MODELS[router.SPECS["evaluation"].level]
    spec = next(s for s in agent_registry.AGENTS if s.agent == "stats")
    assert spec.contract == "aa-v1" and spec.reads == "stats"
    assert prompts.STATS_ASSESS_SYSTEM and "DATA" in prompts.STATS_ASSESS_SYSTEM
    [born, entry] = [e for e in agent_registry.LEDGER if e.agent == "stats"]
    assert born.version == "stats-v1" and born.phase == "IA-4" and born.decided_by == "owner"
    assert entry.version == "stats-v2" and entry.phase == "IA-009" and entry.decided_by == "owner" and entry.born_as == "CHALLENGER"
    sec = section(4)
    assert f"{mcp_package.CAPS['stats']:,}".replace(",", ".") in sec and "tope de 18.000 tokens" in sec
    assert "`stats_slice_over_its_cap`" in sec and "stats_slice_over_its_cap" in ORCH_SRC
    assert stats.LOWERED == "rests_only_on_descriptive_factor" and f"`{stats.LOWERED}`" in sec
    assert "una sola tarea, sin modo CONTEXT" in sec.replace("**una sola tarea**", "una sola tarea")


# ── 5. the names ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_names_the_halves_and_the_limit() -> None:
    sec = section(5)
    assert NAMING_VERSION == "cand-names-v1" and NAMING_COUNTS_VERSION == "cand-names-v2"
    assert "`cand-names-v2`" in sec and "`cand-names-v1`" in sec and "`name_with_counts`" in sec
    assert CANDIDATES_MAX == 12 and "El contrato admite 12 nombres" in sec
    assert {"1H", "2H", "HT", "FH", "SH", "H1", "H2", "HALF"} == HALF_TOKENS
    for token in HALF_TOKENS:
        assert f"`{token.lower()}`" in sec.lower() or token in sec, token
    for code in ("period_not_settleable", "beyond_the_limit", "family_not_read"):
        assert f"`{code}`" in sec
    assert "def escalation_naming" in ORCH_SRC and "GOALS_RESULT" in ORCH_SRC
    assert "Las reglas E1 a E7" in sec and "solo sobre las selecciones de goles y resultado" in sec


# ── 6. the DESCRIPTIVE factors ────────────────────────────────────────────────────────────────────────────────────

def test_the_descriptive_factors_are_the_ones_of_the_code() -> None:
    sec = section(6)
    keys = [r.key for r in stats_factors.RELATIONS]
    assert keys == ["pressure_shots_corners", "intensity_fouls_cards"]
    for key in keys:
        assert f"`{key}`" in sec
    for code in stats_factors.BLOCKED_DRIVERS.values():
        assert f"`{code}`" in sec
    assert "`RATE`" in sec and "`NEUTRAL`" in sec and "`LOW`" in sec
    assert "fbi.intel.factors.CATALOGUE" in sec.replace("`", "")
    from fbi.intel import factors
    assert not {r.key for r in stats_factors.RELATIONS} & {f.key for f in factors.CATALOGUE}, "on purpose: the catalogue builds the block of every packet"
    assert stats_factors.VERSION == "stats-relations-v1"
    paths, drivers = stats_factors.descriptive_blocks({})
    assert "shared.tactics" in paths and drivers == set(stats_factors.BLOCKED_DRIVERS.values()), "a package that says nothing is DESCRIPTIVE"
    assert "`shared.tactics`" in sec


# ── 7 and 8. the shadow and the engines ───────────────────────────────────────────────────────────────────────────

def test_the_engines_that_read_the_agent_and_their_versions() -> None:
    sec = section(7)
    assert set(orchestrator.WITH_MATCH) == {"ma-v1", "ma-v1-h"} and "cs-v1" not in orchestrator.WITH_MATCH
    assert orchestrator.STATS_PART == "+stats-v2"
    assert orchestrator.engine_version("ma-v1", with_stats=True) == "ma-v1+match-v2+stats-v2+council-v1+contra-v1+router-v1"
    assert "`ma-v1+match-v2+stats-v2+council-v1+contra-v1+router-v1`" in sec
    assert orchestrator.engine_version("ma-v1", with_stats=False) == orchestrator.ENGINE_VERSION["ma-v1"]
    assert orchestrator.engine_version("cs-v1", with_stats=True) == orchestrator.ENGINE_VERSION["cs-v1"]
    assert "`A:stats_evaluation`" in sec and "route.stats" in sec.replace("`", "") and '"stats": p.stats_on' in ORCH_SRC
    assert "`no_count_to_assess`" in sec and "no_count_to_assess" in ORCH_SRC
    assert "(sección 10, D6)" in sec


def test_no_engine_is_added_and_the_gate_of_goals_does_not_read_counts() -> None:
    sec = section(8)
    assert "No hay motor nuevo" in sec and "`pick_reviews_engine_check` no cambia" in sec
    assert config.KNOWN_ENGINES == ("rules", "llm", "ma-v1", "ma-v1-h", "cs-v1")
    assert "`market_outcome`" in sec and "market_outcome" in (SRC / "ai" / "shadow.py").read_text(encoding="utf-8")
    assert "ai-gate-v2" in sec and "ai-gate-v2" in (SRC / "ai" / "shadow.py").read_text(encoding="utf-8")


# ── 9. C05 and C08 by family ──────────────────────────────────────────────────────────────────────────────────────

def test_c05_and_c08_by_family_say_what_the_code_says() -> None:
    sec = section(9)
    assert contra.NOT_APPLICABLE == "not_applicable" and contra.EVALUATED == "evaluated" and contra.INPUT_MISSING == "input_missing"
    assert contra.RULE_FAMILIES == {"C05": ("CARDS",)}
    rows = {r[0]: r for r in table(sec, "| Regla")}
    assert set(rows) == {"C05 (el árbitro tolerante baja las tarjetas Over)", "C08 (una evaluación apoya y otra objeta selecciones alineadas)", "C06"}
    c05 = rows["C05 (el árbitro tolerante baja las tarjetas Over)"][1]
    assert "`input_missing` para tarjetas" in c05 and "`not_applicable` para córners" in c05 and "`shared.referee.multiplier`" in c05
    assert "No builder writes ``shared.referee.multiplier`` yet" in CONTRA_SRC, "the day a builder writes it, this guide is wrong"
    assert "coverage_by_family" in sec and "tally_by_family" in sec and "model_status.stats.contra" in sec.replace("`", "")
    assert "model_status[\"stats\"]" in ORCH_SRC or '"stats"' in ORCH_SRC


# ── 10. what Gate B can read ──────────────────────────────────────────────────────────────────────────────────────

def test_the_report_of_the_counts_is_what_the_guide_says_and_never_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    sec = section(10)
    assert shadow.COUNTS_MIN_DAYS == 14 and "14 días" in sec and "los 14 que el plan pide" in sec
    keys = [r[0].strip("`") for r in table(sec, "| Cifra")]
    assert shadow.COUNTS_VERSION == "ai-counts-v1"
    monkeypatch.setattr(shadow, "load_counted", lambda *a, **k: ([], {"half": 0, "ungradable": 0, "unreadable": 0}))
    from datetime import UTC, datetime

    from fbi.families import score
    report: dict[str, Any] = shadow.counts_report(None, score, at=datetime(2026, 11, 3, tzinfo=UTC))  # type: ignore[arg-type]
    assert report["verdict"] == "not_judged" and "pass" in report["reason"] and report["evidence"] == {"days": 0, "need_days": 14, "enough_days": False}
    assert tuple(report["engines"]) == config.SHADOW_ENGINES
    engine = report["engines"]["ma-v1"]
    for key in ("by_stance", "abstentions", "versus_market", "by_decision", "by_family", "left_out"):
        assert key in engine and f"`{key}`" in sec, key
    assert set(engine["abstentions"]) == {"abstained", "no_answer", "rate"} and "`no_answer`" in sec and "`ABSTAIN`" in sec
    assert "`evidence`" in sec and "evidence" in report
    assert keys[0] == "CLV por evaluación" and "**El veredicto es siempre `not_judged`**" in sec and "nunca forzar PASS" in sec
    assert "python -m scripts.ia_counts_report" in sec
    script = (BACKEND / "scripts" / "ia_counts_report.py").read_text(encoding="utf-8")
    assert "conn.read_only = True" in script and "counts_report(conn, score" in script and "INSERT" not in script
    assert "from fbi.families" not in (SRC / "ai" / "shadow.py").read_text(encoding="utf-8"), "the scoreboard is given to the report: fbi.ai must not import fbi.families"
    assert set(re.findall(r"`(SUPPORT|NEUTRAL|CONCERN|REJECT_SIGNAL)`", sec)) == {"SUPPORT", "NEUTRAL", "CONCERN", "REJECT_SIGNAL"}


# ── 11. the deviations, held both ways ────────────────────────────────────────────────────────────────────────────

def test_the_deviations_are_what_the_code_shows() -> None:
    rows = {r[0]: r for r in table(section(11), "| Id")}
    assert list(rows) == [f"D{i}" for i in range(1, 9)]
    # D1: no view of the counts in the Console
    web = MONOREPO / "web" / "src"
    if web.is_dir():
        assert "counts_report" not in "".join(p.read_text(encoding="utf-8", errors="ignore") for p in web.rglob("*.ts*"))
    # D2: C05 cannot fire (see section 9) and C08 compares the assessments of one family: the Match Agent is asked about goals and result only
    assert "GOALS_RESULT" in ORCH_SRC
    # D3: the prompt of the Council is the one of phase 3 and says nothing of corners or cards
    assert prompts.COUNCIL_VERSION == "council-v1" and "corners" not in prompts.COUNCIL_SYSTEM.lower() and "cards" not in prompts.COUNCIL_SYSTEM.lower()
    assert "`council-v1`" in rows["D3"][1]
    # D4: Opus is never asked about a count
    assert "def escalation_naming" in ORCH_SRC
    # D6: the state keeps all the slices of the package
    assert "for name in SLICE_NAMES if name in p.slices" in ORCH_SRC
    # D7: the guide says the battery had no target for the new prompt - true of battery-v2; IA-010 (battery-v3) closes it
    from fbi.ai.battery import TARGETS, corpus
    assert "`stats-assess-v2`" in rows["D7"][1] and "stats" in TARGETS and corpus.target("stats").prompts == ("stats-assess-v2",)
    # D8: the Batch keeps the flag it was queued with
    assert "p.stats_on" in ORCH_SRC and "stats_wanted" in ORCH_SRC


def test_what_is_still_missing_is_in_the_guide_and_owes_nothing_to_the_code() -> None:
    sec = section(12)
    assert "terminada en el código y sin desplegar" in sec and "no lleva migración" in sec
    assert "`evidence.enough_days`" in sec and "enough_days" in (SRC / "ai" / "shadow.py").read_text(encoding="utf-8")
