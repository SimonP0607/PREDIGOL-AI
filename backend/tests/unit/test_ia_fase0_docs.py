"""The Phase 0 guide (``docs/owner/IA_FASE0.md``) says what the code does.

The guide is for the owner: it says which variable rolls each optimisation back, what the three envelopes are, when a budget degrades, what a
cache write costs, what goes in a batch, what Gate A checks and with which thresholds, and which command answers with which exit status.
Nothing held it together with the code. This file reads the guide's tables and sentences and compares every figure, name and option with the
constants and parsers of the code: if a constant changes the test fails until the guide says the new value, and if the guide is edited to
something else it fails the same way. The dated figures of the guide (what the baseline measured on 24 Oct 2026, what the previous release's
suites counted) are data and not code, and are not compared; the baseline's own daily figure is held to ``IA_BASELINE_F0.md``.

The owner's list of manual actions (``docs/owner/IA_ACCIONES_MANUALES.md``) gets the same treatment where it states what the code reads: the
three budgets of action 7 are the ones Gate A expects.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import shlex
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from scripts import ia_equivalence, ia_gate, ia_probe, ia_reconcile

from fbi.ai import batch, budget_v3, config, gate_a, gates, lab, material, pricing, reconcile, usage
from fbi.ai.config import SWITCH_ENV, AiSettings
from fbi.ai.providers import anthropic
from fbi.ai.providers.base import JsonRequest

BACKEND = Path(__file__).resolve().parents[2]
DOCS = BACKEND / "docs"
D = Decimal


def read_doc(*parts: str) -> str:
    """A document of the repository, with the typographic minus (U+2212) written as a hyphen. Where the documents are not shipped (an image
    with the code only) there is nothing to compare."""
    path = DOCS.joinpath(*parts)
    if not path.is_file():
        pytest.skip(f"no {path.name} next to the code", allow_module_level=True)
    return path.read_text(encoding="utf-8").replace("\N{MINUS SIGN}", "-")


GUIDE = read_doc("owner", "IA_FASE0.md")
ACTIONS = read_doc("owner", "IA_ACCIONES_MANUALES.md")
BASELINE = read_doc("owner", "IA_BASELINE_F0.md")
SCHEDULER = (BACKEND / "apps" / "worker" / "scheduler.py").read_text(encoding="utf-8")


# ── reading the documents ─────────────────────────────────────────────────────────────────────────────────────────

def num(token: str) -> Decimal:
    """A number as the documents write it: decimal comma, thousands with a dot ('0,125', '1.600')."""
    token = token.strip()
    if "," in token:
        return D(token.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        return D(token.replace(".", ""))
    return D(token)


def section(number: int) -> str:
    m = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", GUIDE, flags=re.S | re.M)
    assert m, f"section {number} is missing from the guide"
    return m.group(0)


def table(text: str, header: str, *, nth: int = 0) -> list[list[str]]:
    """The cells of the rows of the ``nth`` table whose header line starts with ``header`` (the header and its rule left out, the bold marks
    taken off)."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(header)]
    assert len(starts) > nth, f"the guide no longer has the table {header!r}"
    out: list[list[str]] = []
    for line in lines[starts[nth] + 2:]:
        if not line.startswith("|"):
            break
        out.append([cell.strip().replace("**", "") for cell in line.strip().strip("|").split("|")])
    return out


def ticked(cell: str) -> str:
    m = re.search(r"`([^`]+)`", cell)
    assert m, f"no `code` in {cell!r}"
    return m.group(1)


def all_ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def find(pattern: str, text: str) -> tuple[Decimal, ...]:
    """The numbers captured by ``pattern`` in ``text``; the test fails (naming the pattern) if the guide stopped saying it."""
    m = re.search(pattern, text, flags=re.S)
    assert m, f"the guide no longer says {pattern!r}"
    return tuple(num(g) for g in m.groups())


def said(pattern: str, text: str, *expected: Decimal | int | float | str) -> None:
    """The guide says ``expected`` where ``pattern`` captures numbers (compared as numbers: 0,03 x 100 is 3)."""
    assert find(pattern, text) == tuple(D(str(e)) for e in expected), pattern


def commands(text: str, script: str) -> list[list[str]]:
    """The arguments of every ``python -m scripts.<script> ...`` line of the guide's code blocks (the comment after the ``#`` left out)."""
    out: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith(f"python -m scripts.{script} "):
            out.append(shlex.split(line.split(" #", 1)[0])[3:])
    return out


def options_of(parser: Any) -> set[str]:
    return {opt for action in parser._actions for opt in action.option_strings}


def migration() -> ModuleType:
    path = next((BACKEND / "migrations" / "versions").glob("0110_*.py"))
    spec = importlib.util.spec_from_file_location("ia_migration_0110", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guide_names(text: str) -> set[str]:
    return set(re.findall(r"FBI_AI_[A-Z0-9_]*[A-Z0-9]", text))


# ── 1. what the phase is ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_pieces_of_the_guide_are_files_and_jobs_that_exist() -> None:
    for row in table(section(1), "| Pieza"):
        for name in all_ticked(row[2]):
            if name.endswith(".py"):
                assert (BACKEND / "src" / "fbi" / "ai" / name).is_file(), name
            elif name.startswith("ia_"):
                assert (BACKEND / "scripts" / f"{name}.py").is_file(), name
            elif name == "ai_batch_poll":
                assert 'id="ai_batch_poll"' in SCHEDULER, "the worker job the guide names"
            else:
                raise AssertionError(f"the guide names {name!r} and the test does not know where it lives")


def test_the_documents_the_guide_names_exist_and_it_carries_no_key() -> None:
    for name in set(re.findall(r"\b([A-Z][A-Z_0-9]+\.md)\b", GUIDE)):
        assert (DOCS / "owner" / name).is_file(), name
    assert not re.search(r"sk-[A-Za-z0-9_-]{16,}", GUIDE + ACTIONS), "a key in a document"


# ── 2. the switches ───────────────────────────────────────────────────────────────────────────────────────────────

def test_the_switches_of_the_guide_are_the_ones_of_the_code() -> None:
    rows = table(section(2), "| Interruptor")
    assert {ticked(r[0]) for r in rows} == set(SWITCH_ENV), "the five optimisations, no more and no fewer"
    waiting: set[str] = set()
    for r in rows:
        name = ticked(r[0])
        assert ticked(r[1]) == SWITCH_ENV[name], name
        assert ticked(r[4]) == f"{SWITCH_ENV[name]}=0", "the way back is the variable at 0"
        on_by_default = gates.AUTO_WITHOUT_EVIDENCE[name]
        assert r[2].startswith("encendido") is on_by_default, f"{name}: what auto means"
        if not on_by_default:
            waiting.add(name)
            assert ticked(r[2]) == gates.GATE_OF[name], f"{name}: the gate its auto waits for"
    assert waiting == set(gates.GATE_OF), "the switches that wait for a gate are the ones the code says"


def test_the_values_a_switch_accepts_are_the_ones_the_guide_lists() -> None:
    m = re.search(r"Los valores (.+?) la apagan[^;]*; (.+?) la fuerzan; cualquier otro valor, o ninguno, es `auto`", section(2))
    assert m, "the guide no longer lists the values of a switch"
    off, on = all_ticked(m.group(1)), all_ticked(m.group(2))
    assert off == ["0", "off", "false", "no"] and on == ["1", "on", "true", "yes"]
    assert [config._switch(v) for v in off] == ["off"] * 4 and [config._switch(v) for v in on] == ["on"] * 4
    assert (config._switch(""), config._switch(None), config._switch("maybe")) == ("auto", "auto", "auto")


def test_every_variable_the_guide_names_is_read_by_the_code() -> None:
    known = inspect.getsource(config) + SCHEDULER
    for text, label in ((GUIDE, "the guide"), (ACTIONS, "the manual actions")):
        unknown = sorted(n for n in guide_names(text) if n not in known)
        assert not unknown, f"{label} names variables the code does not know: {unknown}"


def test_the_variables_of_the_guide_change_the_settings_they_say(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"FBI_AI_MONTHLY_BUDGET_USD": "111", "FBI_AI_LAB_MONTHLY_BUDGET_USD": "22", "FBI_AI_EXA_MONTHLY_BUDGET_USD": "33",
           "FBI_AI_JOINT_CEILING_USD": "44", "FBI_AI_RESERVE_USD": "5", "FBI_AI_BATCH_MIN_LEAD_MINUTES": "300",
           "FBI_AI_DAILY_MAX_FACTOR": "3", "FBI_AI_KEY_ANTHROPIC_LAB": "not-a-key", **dict.fromkeys(SWITCH_ENV.values(), "0")}
    monkeypatch.setattr("fbi.ai.config.environment", lambda: env)
    s = AiSettings.from_env()
    assert (s.monthly_budget, s.lab_monthly_budget, s.exa_monthly_budget, s.joint_ceiling, s.reserve) == (D(111), D(22), D(33), D(44), D(5))
    assert (s.batch_min_lead_minutes, s.daily_max_factor) == (300, D(3))
    assert "anthropic" in s.lab_keys and all(s.switch(name) == "off" for name in SWITCH_ENV)
    assert not {name for name in env if name not in GUIDE}, "every variable of the settings is described in the guide"
    said(r"`FBI_AI_BATCH_MIN_LEAD_MINUTES` \(por defecto (\d+)\)", section(2), AiSettings().batch_min_lead_minutes)


# ── 3. the gates ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_gates_of_the_guide_are_the_gates_of_the_code() -> None:
    rows = table(section(3), "| Gate")
    assert [ticked(r[0]) for r in rows] == list(gates.GATES)
    commands_of = {"ia_probe": ia_probe.COMMANDS, "ia_equivalence": ia_equivalence.COMMANDS, "ia_gate": ia_gate.COMMANDS}
    for r in rows:
        script, command = ticked(r[1]).split()[:2]
        assert command in commands_of[script], f"{script} has no command {command!r}"
    assert set(gate_a.OPTIMISATIONS) <= set(gates.GATES)


# ── 4. the budget ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_envelopes_and_ceilings_of_the_guide_are_the_codes() -> None:
    text = section(4)
    envelopes = {ticked(r[2]): num(r[3]) for r in table(text, "| Sobre")}
    assert envelopes == gate_a.EXPECTED_ENV, "the three budgets of owner action 7"
    s = AiSettings()
    said(r"\(producción más LAB\): (\d+) \(`FBI_AI_JOINT_CEILING_USD`\)", text, s.joint_ceiling)
    said(r"\*\*Reserva\*\*: (\d+) \(`FBI_AI_RESERVE_USD`\)", text, s.reserve)
    said(r"últimos (\d+) días del mes", text, budget_v3.RESERVE_RELEASE_DAYS)
    said(r"US\$ (0,015) cada una", text, budget_v3.EXA_SEARCH_USD)
    said(r"Su sobre es (\d+) en las fases 0 a 2", text, gate_a.EXPECTED_ENV["FBI_AI_LAB_MONTHLY_BUDGET_USD"])
    assert s.joint_ceiling == gate_a.JOINT_CEILING and s.exa_monthly_budget == envelopes["FBI_AI_EXA_MONTHLY_BUDGET_USD"]
    assert s.lab_monthly_budget == 0, "without the variable the LAB makes no call"


def test_the_projection_and_the_days_allocation_of_the_guide_are_the_budgets() -> None:
    text = section(4)
    said(r"en los últimos (\d+) días \(o en los últimos (\d+) si en menos de (\d+) de ellos", text,
         *budget_v3.UNIT_WINDOWS, budget_v3.MIN_UNIT_DAYS)
    said(r"próximos (\d+) días salen del calendario", text, budget_v3.CALENDAR_DAYS)
    said(r"en las últimas (\d+) semanas", text, budget_v3.WEEKDAY_WEEKS)
    said(r"entre (0,5) y `FBI_AI_DAILY_MAX_FACTOR` \((\d+)\) veces la media", text, usage.LOAD_MIN, AiSettings().daily_max_factor)
    said(r"Su tope duro es (1,5) veces la asignación", text, usage.HARD_FACTOR)


def test_the_states_of_the_guide_are_the_ones_the_budget_decides() -> None:
    rows = {ticked(r[0]): r for r in table(section(4), "| Estado")}
    assert list(rows) == ["EXHAUSTED", "CHEAP_ONLY", "REDUCED", "AJUSTE", "NORMAL"], "worst first: the order state_of applies"
    percents = {state: [num(p) for p in re.findall(r"(\d+) %", r[1])] for state, r in rows.items()}
    assert percents == {"EXHAUSTED": [], "CHEAP_ONLY": [usage.CHEAP_AT * 100],
                        "REDUCED": [budget_v3.PROJECTION_REDUCED_AT * 100, usage.REDUCED_AT * 100],
                        "AJUSTE": [budget_v3.AJUSTE_AT * 100, budget_v3.PROJECTION_REDUCED_AT * 100],
                        "NORMAL": [budget_v3.AJUSTE_AT * 100]}

    base: dict[str, Any] = {"monthly": D(100), "spent_month": D(10), "spent_today": D(0), "daily": D(10), "cap": D(15),
                            "projected": D(50), "limit_active": False}

    def state(**over: Any) -> str:
        return str(budget_v3.state_of(**(base | {k: D(v) if k != "limit_active" else v for k, v in over.items()}))[0])

    assert [state(projected="95"), state(projected="95.01"), state(projected="100"), state(projected="100.01")] == [
        "NORMAL", "AJUSTE", "AJUSTE", "REDUCED"], "the projection against the envelope: above 95 %, above 100 %"
    assert [state(spent_today="9.99"), state(spent_today="10"), state(spent_today="12.4"), state(spent_today="12.5")] == [
        "NORMAL", "REDUCED", "REDUCED", "CHEAP_ONLY"], "the day against its allocation: 100 %, 125 %"
    assert [state(spent_month="100"), state(spent_today="15"), state(limit_active=True)] == ["EXHAUSTED"] * 3, \
        "the month spent, the day's hard cap, the provider's limit"


def test_the_alerts_and_the_spent_limit_of_the_guide_are_the_budgets() -> None:
    text = section(4)
    m = re.search(r"el mes de cada sobre al ([\d, y]+) %, y la proyección de producción al ([\d, y]+) %", text)
    assert m, "the guide no longer lists the alerts"
    assert tuple(int(x) for x in re.findall(r"\d+", m.group(1))) == usage.ALERT_THRESHOLDS
    assert tuple(int(x) for x in re.findall(r"\d+", m.group(2))) == budget_v3.PROJECTION_ALERTS
    said(r"una espera de (\d+) minutos que se duplica con cada golpe de las últimas (\d+) horas", text,
         budget_v3.LIMIT_COOLDOWN.total_seconds() / 60, budget_v3.LIMIT_WINDOW.total_seconds() / 3600)
    waits = find(r"\((\d+) min, (\d+) h, (\d+) h, (\d+) h, (\d+) h como máximo\)", text)
    steps = [timedelta(minutes=int(waits[0])), *(timedelta(hours=int(h)) for h in waits[1:])]
    assert steps == [budget_v3.limit_cooldown(n) for n in range(1, 6)] and steps[-1] == budget_v3.LIMIT_COOLDOWN_MAX
    assert "HTTP 400" in text and "HTTP 429 `enforced_spend_limit_reached`" in text
    assert "enforced_spend_limit_reached" in inspect.getsource(anthropic), "the provider's error the client reads"


# ── 5. the cache ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_cache_prices_of_the_guide_are_the_price_table() -> None:
    text = section(5)
    models = {"Haiku 5.5": "claude-haiku-5-5", "Sonnet 5.5": "claude-sonnet-5-5", "Opus 5.5": "claude-opus-5-5"}
    write5, write1 = pricing.CACHE_WRITE_FACTOR["anthropic"]
    rows = table(text, "| Modelo")
    assert [r[0] for r in rows] == list(models)
    for r in rows:
        price, known = pricing.price_of("anthropic", models[r[0]])
        assert known, r[0]
        assert [num(c) for c in r[1:]] == [price.input, price.output, price.cached, price.input * write5, price.input * write1], r[0]
    said(r"escritura de 5 minutos vale (1,25) veces la entrada y la de 1 hora, (2) veces", text, write5, write1)
    haiku, sonnet, opus = (pricing.price_of("anthropic", model)[0] for model in models.values())
    said(r"la lectura vale (0,1) veces la entrada en Haiku y (0,05) en Sonnet y Opus", text,
         haiku.cached / haiku.input, sonnet.cached / sonnet.input)
    assert sonnet.cached / sonnet.input == opus.cached / opus.input
    said(r"bloques de unos (1\.600)", text, 1600)
    assert len(lab.PROBE_SYSTEM) >= 1600 * 4 and len(lab.PROBE_SHARED) >= 1600 * 4, "well over the 512 tokens a cache needs"


def test_the_blocks_the_guide_says_are_cached_are_the_ones_marked() -> None:
    body = anthropic.build_body("claude-sonnet-5-5", JsonRequest(system="s", user="u", schema={}, schema_name="x", shared="m"),
                                forced=True, effort=None, native=False, cache=True)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}, "the system block: one hour"
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}, "the match block: five minutes"
    assert "cache_control" not in body["messages"][0]["content"][1], "what varies is never cached"
    text = section(5)
    assert "bloque del sistema" in text and "durante **1 hora**" in text and "durante **5 minutos**" in text


# ── 6. Batch ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_what_goes_in_a_batch_is_what_the_guide_says() -> None:
    text = section(6)
    rows = table(text, "| Tarea")
    went = {ticked(r[0]): r[1].startswith("sí") for r in rows if "`" in r[0]}
    assert went == {"first": True, "pre": True, "final": False}
    assert {p for p, goes in went.items() if goes} == set(batch.BATCH_PASSES)
    assert rows[-1][1].startswith("nunca") and "candidate" in batch.BATCH_ROLES and "watch" not in batch.BATCH_ROLES
    said(r"dentro de (\d+) minutos", next(r for r in rows if "`pre`" in r[0])[1], AiSettings().batch_min_lead_minutes)
    said(r"tras (\d+) fallos de la misma tarea en (\d+) horas", text, batch.MAX_FAILED_ATTEMPTS,
         batch.ATTEMPT_WINDOW.total_seconds() / 3600)
    said(r"con menos de (\d+) minutos de margen antes del partido", text, batch.DEADLINE_MARGIN.total_seconds() / 60)
    assert str(pricing.BATCH_FACTOR) == "0.5" and "la mitad de precio" in text


def test_the_key_and_the_poll_of_a_batch_are_what_the_guide_says() -> None:
    text = section(6)
    task = batch.Task(purpose="pick_review", tier="analysis", request=JsonRequest(system="s", user="u", schema={}, schema_name="x"),
                      prompt_version="review-v3", input_hash="a" * 64)
    said(r"\(SHA-256, (\d+) caracteres\)", text, len(batch.custom_id_of(task, "claude-sonnet-5-5")))
    m = re.search(r'"FBI_AI_BATCH_POLL_MINUTES", "(\d+)"', SCHEDULER)
    assert m, "the worker's poll interval"
    said(r"cada (\d+) minutos, pregunta por los lotes", text, m.group(1))
    said(r"`FBI_AI_BATCH_POLL_MINUTES` \(por defecto (\d+)\)", text, m.group(1))


# ── 7. the material change ────────────────────────────────────────────────────────────────────────────────────────

def test_the_material_change_of_the_guide_is_the_codes() -> None:
    text = section(7).replace("**", "")
    said(r"se mueve más del (\d+) %", text, D(str(material.PRICE_MOVE)) * 100)
    low, high = find(r"Un movimiento del (\d+) % reutiliza el brief; uno del (\d+) % escribe uno nuevo", text)
    assert low / 100 < material.PRICE_MOVE < high / 100
    said(r"Un brief de más de (\d+) horas", text, material.MAX_AGE.total_seconds() / 3600)
    assert f"`{material.MATERIAL_VERSION}`" in text


# ── 8 and 14. the ledger and the migration ────────────────────────────────────────────────────────────────────────

def test_the_ledger_columns_of_the_guide_are_the_ones_the_migration_adds() -> None:
    m = migration()
    columns = [name for r in table(section(8), "| Columna") for name in all_ticked(r[0])]
    assert sorted(columns) == sorted(m.USAGE_COLUMNS)
    assert len(m.USAGE_COLUMNS) == 10 and "las diez columnas" in section(14)
    scope = inspect.getsource(m.upgrade)
    assert "WHEN tier = 'search' THEN 'exa'" in scope and "LIKE '%LAB'" in scope, "the rule of the scope the guide describes"


def test_the_migration_of_the_guide_is_the_migration() -> None:
    m = migration()
    upgrade = inspect.getsource(m.upgrade)
    text = section(14)
    named = set(re.findall(r"`(ai\.\w+)`", text))
    made = {f"ai.{n}" for n in re.findall(r"CREATE (?:OR REPLACE )?(?:TABLE|VIEW|FUNCTION) ai\.(\w+)", upgrade)}
    altered = {f"ai.{n}" for n in re.findall(r"ALTER TABLE ai\.(\w+)", upgrade)}
    assert named == made | altered, "what 0110 creates and alters, and nothing else"
    assert "ai.budget_alerts" not in altered, "the table the previous release shares is not touched"
    appended = re.search(r"(`ai\.\w+`), (`ai\.\w+`) y (`ai\.\w+`)\. Las tres últimas son de solo añadir", text)
    assert appended, "the guide no longer says which tables are append-only"
    assert {n.strip("`").removeprefix("ai.") for n in appended.groups()} == set(m.APPEND_ONLY)
    for name in ("usage_cache_write_check", "ai_usage_batch_once", "ai_usage_custom", "ai_match_briefs_material"):
        assert name in text and name in upgrade, name
    said(r"una espera de más de (\d+) s", text, 10)
    assert "SET LOCAL lock_timeout = '10s'" in upgrade
    assert "ON CONFLICT (month, threshold)" in usage.MONTH_ALERT_SQL, "the statement the previous release keeps using"


# ── 9. the LAB ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_lab_commands_and_rules_of_the_guide_are_the_codes() -> None:
    text = section(9)
    assert [ticked(r[0]) for r in table(text, "| Orden", nth=0)] == list(ia_probe.COMMANDS)
    assert [ticked(r[0]) for r in table(text, "| Orden", nth=1)] == list(ia_equivalence.COMMANDS)
    said(r"como mucho el (\d+) % y como mucho (\d+) punto por encima", text, D(str(lab.MAX_INVALID)) * 100,
         D(str(lab.INVALID_MARGIN)) * 100)
    said(r"al menos (\d+) entradas así", text, lab.MIN_INPUTS)
    assert f"`{lab.EQUIVALENCE_VERSION}`" in text
    letters = dict(re.findall(r"`([ADRS])` (aprobar|degradar|rechazar|abstenerse)", text))
    assert letters == {"A": "aprobar", "D": "degradar", "R": "rechazar", "S": "abstenerse"}
    assert set(letters) == set(lab.LETTER.values())
    asks = re.search(r"dos como hoy \(`(A1)`, `(A2)`\), una con salidas estructuradas \(`(B)`\) y una con el bloque común primero \(`(C)`\)", text)
    assert asks, "the guide no longer lists the four asks"
    assert asks.groups() == (*lab.BASELINES, lab.VARIANT_KEY["native_schema"], lab.VARIANT_KEY["shared_layout"])


def test_the_options_of_the_lab_commands_in_the_guide_are_the_parsers() -> None:
    text = section(9)
    defaults = ia_equivalence.build_parser().parse_args(["plan"])
    said(r"`--inputs` \(por defecto (\d+)\)", text, defaults.inputs)
    said(r"`--since-days` \((\d+)\)", text, defaults.since_days)
    assert f"`--tier` (por defecto `{defaults.tier}`" in text
    mentioned = set(re.findall(r"`(--[a-z-]+)", text))
    assert mentioned <= options_of(ia_equivalence.build_parser()) | options_of(ia_probe.build_parser()), mentioned
    assert "--no-record" in options_of(ia_probe.build_parser()), "batch-collect can show the verdict without writing it"
    said(r"unos US\$ (\d+) del sobre de (\d+) del LAB", text, 14, gate_a.EXPECTED_ENV["FBI_AI_LAB_MONTHLY_BUDGET_USD"])
    assert "US$14" in (ia_equivalence.__doc__ or "")


# ── 10. Gate A ────────────────────────────────────────────────────────────────────────────────────────────────────

AT = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
WINDOW = gate_a.Window(date(2026, 10, 27), date(2026, 11, 2), date(2026, 10, 26), "x", 8, date(2026, 11, 2))


def test_the_checks_and_thresholds_of_the_gate_a_in_the_guide_are_the_modules() -> None:
    text = section(10).replace("**", "")
    checks = {ticked(r[0]): r for r in table(text, "| Comprobación")}
    source = inspect.getsource(gate_a)
    assert len(checks) == 10 and all(f'"{check}"' in source for check in checks), "the ten checks, by name"
    assert "once líneas" in text, "the window and the ten checks"
    said(r"sobre (\d+) días completos", text, gate_a.WINDOW_DAYS)
    said(r"Son los (\d+) días de Bogotá que terminaron ayer", text, gate_a.WINDOW_DAYS)
    said(r"es de (\d+) USD", checks["cost_production"][1], gate_a.PRODUCTION_CEILING)
    said(r"al (\d+) % de un mes normal \(US\$ (\d+)\), (\d+) USD", checks["cost_joint"][1], 30, gate_a.SHADOW_NORMAL_MONTH_USD,
         gate_a.JOINT_CEILING)
    said(r"\(\+(\d+) %\), producción sola de (\d+) USD como máximo; el LAB cede lo que pase de (\d+)", checks["cost_heavy"][1],
         (gate_a.HEAVY_MONTH_FACTOR - 1) * 100, gate_a.PRODUCTION_CEILING, gate_a.JOINT_CEILING)
    said(r"como mucho (\d+) puntos por debajo", checks["coverage"][1], gate_a.COVERAGE_TOLERANCE * 100)
    said(r"en el (\d+) % de las pasadas", checks["final_t15"][1], gate_a.FINAL_BEFORE_T15_MIN * 100)
    said(r"con (\d+) paquetes o más", checks["verdict_equivalence"][1], gate_a.MIN_EQUIVALENCE_INPUTS)
    said(r"en (\d+) de los (\d+) días y, en tiempo real, el (\d+) % o más", checks["cache_visible"][1], gate_a.CACHE_DAYS_MIN,
         gate_a.WINDOW_DAYS, gate_a.CACHE_HIT_MIN * 100)
    said(r"como mucho el (\d+) % de peticiones caducadas", checks["batch_lost"][1], gate_a.BATCH_EXPIRED_MAX * 100)
    assert "3, 5 y 7" in inspect.getsource(gate_a.check_actions) and "acciones 3, 5 y 7" in checks["manual_actions"][1]
    mine = {check for check, r in checks.items() if "míos" in r[2]}
    assert mine == {"coverage", "cache_visible"}, "the readings of engineering that the guide marks as mine"


def test_the_baselines_of_the_gate_a_in_the_guide_are_the_ones_of_the_code_and_the_baseline_document() -> None:
    text = section(10)
    first, last = gate_a.BASELINE_COVERAGE_DAYS
    said(r"línea base sobre los (\d+) días del (\d+) al (\d+) oct 2026", text, (last - first).days + 1, first.day, last.day)
    first, last = gate_a.BASELINE_UNIT_DAYS
    daily = find(r"línea base de los (\d+) días del (\d+) al (\d+) oct 2026 \((\d+,\d+) USD al día", text)
    assert daily[:3] == (D((last - first).days + 1), D(first.day), D(last.day))
    assert f"Claude {str(daily[3]).replace('.', ',')} USD al día" in BASELINE, "the baseline document says the same figure"


def test_the_verdicts_of_the_guide_are_the_gates_and_only_two_are_recorded() -> None:
    rows = {ticked(r[0]): r for r in table(section(10), "| Veredicto")}
    assert list(rows) == [gate_a.PASS, gate_a.FAIL, gate_a.PENDING_TIME, gate_a.PENDING_ACTIONS]
    for verdict, r in rows.items():
        assert r[2].startswith("sí") is gate_a.GateReport(verdict, AT, WINDOW).recordable, verdict
    assert f"gate `{gate_a.GATE}`" in rows[gate_a.PASS][2] and "`decided_by` = `script`" in rows[gate_a.PASS][2]


def test_the_commands_of_the_guide_are_accepted_by_their_parsers() -> None:
    gate_commands = [ia_gate.build_parser().parse_args(args) for args in commands(section(10), "ia_gate")]
    assert {p.command for p in gate_commands} == set(ia_gate.COMMANDS)
    assert any(p.record for p in gate_commands) and any(p.as_json for p in gate_commands)
    assert any(p.through for p in gate_commands) and any(p.changed_on for p in gate_commands)
    assert any(p.command == "revert" and p.gate in gate_a.OPTIMISATIONS and p.reason for p in gate_commands)
    reconcile_commands = commands(section(11), "ia_reconcile")
    assert len(reconcile_commands) == 3 and [ia_reconcile.build_parser().parse_args(args) for args in reconcile_commands]
    mentioned = set(re.findall(r"`(--[a-z-]+)", section(11)))
    assert mentioned == {"--cost-column", "--date-column", "--workspace-column", "--cost-divisor", "--date-format"}
    assert mentioned <= options_of(ia_reconcile.build_parser())


# ── 11, 12 and 13. reconciliation, the way back, the exit codes ───────────────────────────────────────────────────

def test_the_reconciliation_of_the_guide_is_the_codes() -> None:
    said(r"Más de un (\d+) % de diferencia se investiga; una diferencia menor de US\$ (0,50) es redondeo", section(11),
         reconcile.TOLERANCE * 100, reconcile.ABSOLUTE_FLOOR)


def test_the_way_back_of_the_guide_uses_switches_and_commands_that_exist() -> None:
    rows = table(section(12), "| Qué quieres deshacer")
    variables = {name for r in rows for name in re.findall(r"`(FBI_AI_\w+)=0`", r[1])}
    assert variables == set(SWITCH_ENV.values()), "every switch has its way back, and only switches"
    reverts = {gate for r in rows for gate in re.findall(r"`ia_gate revert (\w+) --reason", r[1])}
    assert reverts == set(gate_a.OPTIMISATIONS)
    for gate in reverts:
        assert ia_gate.build_parser().parse_args(["revert", gate, "--reason", "x"]).gate == gate


def test_the_exit_codes_of_the_guide_are_the_scripts() -> None:
    text = section(13)
    assert re.search(r"^\| Comando \| Para qué \| 0 \| 1 \| 2 \| 3 \|$", text, flags=re.M), "the four statuses, in this order"
    assert (ia_probe.OK, ia_probe.NO, ia_probe.CANNOT, ia_probe.WAITING) == (0, 1, 2, 3)
    assert (ia_equivalence.OK, ia_equivalence.NO, ia_equivalence.CANNOT, ia_equivalence.WAITING) == (0, 1, 2, 3)
    assert (ia_gate.OK, ia_gate.NO, ia_gate.CANNOT, ia_gate.PENDING) == (0, 1, 2, 3)
    assert (ia_reconcile.OK, ia_reconcile.DIFFERS, ia_reconcile.CANNOT, ia_reconcile.EMPTY) == (0, 1, 2, 3)
    rows = {ticked(r[0]): r for r in table(text, "| Comando")}
    assert set(rows) == {"ia_probe", "ia_equivalence", "ia_gate", "ia_reconcile"}
    assert ticked(rows["ia_gate"][2]) == gate_a.PASS and ticked(rows["ia_gate"][3]) == gate_a.FAIL
    assert "pendiente" in rows["ia_gate"][5] and "difiere" in rows["ia_reconcile"][3] and "no hubo gasto" in rows["ia_reconcile"][5]
    assert "resultados en camino" in rows["ia_probe"][5] and "resultados en camino" in rows["ia_equivalence"][5]


# ── the manual actions ────────────────────────────────────────────────────────────────────────────────────────────

def test_action_7_of_the_manual_actions_sets_the_budgets_the_gate_expects() -> None:
    m = re.search(r"^## Acción 7 ·.*?(?=^## )", ACTIONS, flags=re.S | re.M)
    assert m, "action 7 is missing"
    values = {name: D(value) for name, value in re.findall(r"`(FBI_AI_\w+_USD)=(\d+)`", m.group(0))}
    assert values == gate_a.EXPECTED_ENV
    assert "`FBI_AI_KEY_ANTHROPIC_LAB`" in m.group(0), "the LAB key the gate looks for"
