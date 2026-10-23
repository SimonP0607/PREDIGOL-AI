"""Plan F0, defect 12: the documentation says what the code does.

PrediGol Intelligence's document (``docs/intelligence/PREDIGOL_INTELLIGENCE.md``) listed a forecast age of 48 h (the code
allows 72), a price not fresh at the end as a RECHAZADO (it is a CAUTELA), a PICK PREMIUM that needed only a score and the
CLV of its type (it needs the market's walk-forward CLV too), a parlay probability "with the measured dependence" (it is
the product of two probabilities from different competitions) and a monthly budget of US$180 (the server's setting; the
code's default is US$20). Nothing held the two together.

This file reads the documents and compares every figure of the ten filters, the PICK PREMIUM, the parlay, the score, the
stake, the calibration gates and the budget with the constants of the code - and the "Falla ->" column with the state
each filter really imposes (``test_decision_rules.effects_of_failing``). If a constant changes, the test fails until the
document says the new value; if the document is edited to something else, it fails the same way. The audit of section 0
is a dated snapshot of production data and is not compared.

Plan F8 adds the one post-mortem and the memory: the conventions table of the longitudinal memory (the half-life and the ``k`` of each
kind of memory), the figures of the post-mortem (when it is studied, how far back, how many investigations, the band of a price's
quality, the named close) and the limits of the narratives, against ``fbi.intel.memory``, ``fbi.intel.postmortem``,
``fbi.market`` and ``fbi.ai.pm_narratives``."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fbi.ai import learning, pm_narratives, usage
from fbi.ai.config import AiSettings
from fbi.intel import calibration, decision, memory, postmortem, score, stake
from fbi.market import closing_reference, closing_value

from .test_decision_rules import effects_of_failing

DOCS = Path(__file__).resolve().parents[2] / "docs"


def read_doc(*parts: str) -> str:
    """A document of the repository, with the typographic minus (U+2212) written as a hyphen (``T-90m``, ``-0,005``).
    Where the documents are not shipped (an image with the code only) there is nothing to compare."""
    path = DOCS.joinpath(*parts)
    if not path.is_file():
        pytest.skip(f"no {path.name} next to the code", allow_module_level=True)
    return path.read_text(encoding="utf-8").replace("\N{MINUS SIGN}", "-")


PI = read_doc("intelligence", "PREDIGOL_INTELLIGENCE.md")
LAYER = read_doc("ai", "AI_DECISION_LAYER.md")


# ── reading the documents ─────────────────────────────────────────────────────

def num(token: str) -> float:
    """A number as the documents write it: decimal comma, thousands with a dot ('1.500', '0,005')."""
    if "," in token:
        return float(token.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        return float(token.replace(".", ""))
    return float(token)


def find(pattern: str, text: str) -> tuple[float, ...]:
    """The numbers captured by ``pattern`` in ``text``; the test fails (naming the pattern) if the document stopped
    saying it."""
    m = re.search(pattern, text, flags=re.S)
    assert m, f"the document no longer says {pattern!r}"
    return tuple(num(g) for g in m.groups())


def said(pattern: str, text: str, *expected: float) -> None:
    """The document says ``expected`` where ``pattern`` captures numbers (compared as numbers: 0,02 x 100 is 2)."""
    assert find(pattern, text) == pytest.approx(expected), pattern


def hours(d: timedelta) -> float:
    return d.total_seconds() / 3600


def minutes(d: timedelta) -> float:
    return d.total_seconds() / 60


def section(text: str, number: int) -> str:
    m = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", text, flags=re.S | re.M)
    assert m, f"section {number} is missing"
    return m.group(0)


def paragraph(text: str, start: str) -> str:
    """The paragraph (up to the blank line) that begins with ``start``, on one line."""
    i = text.find(start)
    assert i >= 0, f"the paragraph {start!r} is missing"
    j = text.find("\n\n", i)
    return " ".join((text[i:] if j < 0 else text[i:j]).split())


def filter_cells() -> dict[int, tuple[str, str]]:
    """Section 5's table: filter number -> (what it checks, the state it fails to)."""
    rows: dict[int, tuple[str, str]] = {}
    for m in re.finditer(r"^\| (\d+) \| (.+) \| (.+) \|$", section(PI, 5), flags=re.M):
        rows[int(m[1])] = (m[2], m[3])
    return rows


STATES = {"RECHAZADO": "RECHAZADO", "INVESTIGACIÓN": "INVESTIGACION", "CAUTELA": "CAUTELA"}


def states_in(cell: str) -> set[str]:
    return {code for name, code in STATES.items() if name in cell}


# ── the ten filters ───────────────────────────────────────────────────────────

def test_the_table_has_the_ten_filters() -> None:
    assert sorted(filter_cells()) == list(range(1, 11))


def test_filter_1_data() -> None:
    what, _ = filter_cells()[1]
    said(r"pronóstico de hace ≤ (\d+) h", what, hours(decision.FORECAST_MAX_AGE))  # it said 48 h
    said(r"≥ (\d+) min al saque", what, decision.MIN_MINUTES)
    missing = [code for code in sorted(decision.BAD_STATUS) if code not in what]
    assert not missing, f"match statuses that make a match unplayable and the document does not list: {missing}"


def test_filter_3_market() -> None:
    what, _ = filter_cells()[3]
    said(r"≥ (\d+) casas", what, decision.MIN_BOOKS)
    said(r"de ≤ (\d+) h", what, hours(decision.MAX_PRICE_AGE))
    said(r"≤ (\d+) % sobre el consenso", what, decision.MAX_PRICE_EDGE * 100)


def test_filter_5_ev() -> None:
    what, _ = filter_cells()[5]
    said(r"EV calibrado ≥ (\d+) %", what, decision.EV_MIN * 100)
    said(r"edge calibrado ≥ (\d+) pto", what, decision.EDGE_MIN * 100)


def test_filter_7_risk() -> None:
    what, _ = filter_cells()[7]
    said(r"cuota > (\d+,\d+)", what, decision.RISK_MAX_ODDS)
    said(r"p_calibrada < (\d+,\d+)", what, decision.RISK_MIN_P)
    said(r"intervalo > (\d+,\d+)", what, decision.RISK_MAX_WIDTH)


def test_filter_9_price_at_the_end() -> None:
    what, _ = filter_cells()[9]
    said(r"ese precio debe tener ≤ (\d+) min", what, minutes(decision.FINAL_FRESH))
    labels = {"lineups": "alineaciones"}
    missing = [labels.get(c, c) for c in sorted(decision.FINAL_CHECKPOINTS) if labels.get(c, c) not in what]
    assert not missing, f"final checkpoints the document does not name: {missing}"


def test_filter_10_classification() -> None:
    what, _ = filter_cells()[10]
    said(r"score ≥ (\d+)", what, decision.PREMIUM_SCORE)
    said(r"cuota (\d+,\d+)\N{EN DASH}(\d+,\d+), p ≥ (\d+,\d+)", what, *decision.PARLAY_ODDS, decision.PARLAY_MIN_P)
    said(r"hasta (\d+) por score", what, decision.MAX_PICKS)
    said(r"máx\. (\d+) por competición", what, decision.MAX_PER_COMPETITION)
    said(r"últimos (\d+) días", what, decision.TYPE_CLV_WINDOW.days)
    premium = re.search(r"PICK PREMIUM \((.*?)\); CANDIDATO", what)
    assert premium, "the PICK PREMIUM condition is missing"
    for part in ("score ≥", "CLV walk-forward de la regla del mercado > 0", "CLV del tipo de pick"):
        assert part in premium[1], f"PICK PREMIUM needs {part!r}: the code requires it (decision.evaluate)"


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8, 9])
def test_the_failing_state_of_each_filter_is_the_one_the_code_imposes(n: int) -> None:
    """The "Falla ->" column against what each filter really does when it fails (scenarios in test_decision_rules)."""
    _, effect_cell = filter_cells()[n]
    assert states_in(effect_cell) == effects_of_failing(n), (n, effect_cell)


def test_the_decision_checkpoints_and_the_rewrite_rule() -> None:
    cell = next(line for line in PI.splitlines() if "| `intel_decide` |" in line and "00:10" in line)
    reachable = {decision.checkpoint_of(m, important=i, lineups=lineups)
                 for m in range(0, 2200, 5) for i in (False, True) for lineups in (False, True)}
    names = {"lineups": "alineaciones"}
    missing = [names.get(c, c) for c in sorted(reachable) if names.get(c, c) not in cell]
    assert not missing, f"checkpoints the code uses and the document does not name: {missing}"
    said(r"el precio más de un (\d+) %", cell, decision.PRICE_MOVE * 100)
    said(r"próximas (\d+) h", cell, hours(decision.HORIZON))


# ── score and stake ───────────────────────────────────────────────────────────

def test_the_pick_score_weights() -> None:
    text = paragraph(PI, "**PrediGol Pick Score")
    weights = [int(w) for w in re.findall(r"\((\d+)\)", text)]
    assert weights == list(score.WEIGHTS.values()), "the components, in the order of score.WEIGHTS"
    assert sum(weights) == 100


def test_the_stake_rules() -> None:
    text = paragraph(PI, "**Stake (`stake-v1`):**")
    assert "¼" in text and stake.KELLY_FRACTION == 0.25
    said(r"redondeo hacia abajo a (\d+,\d+) u", text, stake.STEP)
    caps = {"CAUTELA": "CAUTELA", "APROBADO": "APROBADO", "PICK DEL DÍA": "PICK_DEL_DIA", "PREMIUM": "PICK_PREMIUM"}
    for name, state in caps.items():
        said(rf"{name} (\d+,\d+) u", text, stake.CAPS[state])
    said(r"parlay (\d+,\d+) u", text, stake.PARLAY_CAP)
    assert stake.CAPS["INVESTIGACION"] == stake.CAPS["RECHAZADO"] == 0 and "INVESTIGACIÓN y RECHAZADO 0" in text


# ── the day's picks and the parlays ──────────────────────────────────────────

def test_the_parlay_paragraph_says_what_the_code_does() -> None:
    text = paragraph(PI, "**Parlays:**")
    said(r"hasta (\d+) al día", text, decision.MAX_PARLAYS)
    said(r"EV ≥ (\d+) %", text, decision.PARLAY_MIN_EV * 100)
    said(r"decisión de ≤ (\d+) min", text, minutes(decision.DAY_FRESH))
    said(r"tope (\d+,\d+) u", text, stake.PARLAY_CAP)
    assert "de 2 patas" in text and "competiciones distintos" in text
    assert "el producto de las dos probabilidades calibradas" in text, "the joint probability is the product"
    assert "no el producto ingenuo" not in text, "the old claim: this code does not use the measured dependence"


def test_the_days_picks_row_of_the_cycle_table() -> None:
    row = next(line for line in PI.splitlines() if "**PICKS DEL DÍA PI**" in line)
    said(r"hasta (\d+) APROBADOS", row, decision.MAX_PICKS)
    said(r"máx\. (\d+) por competición", row, decision.MAX_PER_COMPETITION)


# ── calibration and the gates ────────────────────────────────────────────────

def test_the_calibration_figures() -> None:
    text = section(PI, 4)
    said(r"últimos (\d+) días con resultado", text, calibration.WINDOW.days)
    said(r"Mínimo ([\d.]+) selecciones", text, calibration.MIN_TRAIN)
    said(r"fuera de muestra ≥ ([\d.]+) selecciones en ≥ (\d+) días", text, calibration.MIN_OOS_N,
         calibration.MIN_OOS_DAYS)
    said(r"log loss\(calibrada\) ≤ log loss\(modelo crudo\) - (0,\d+)", text, calibration.MIN_GAIN_VS_RAW)
    said(r"ECE\(calibrada\) ≤ (0,\d+)", text, calibration.MAX_ECE)
    said(r"log loss\(mercado\) \+ (0,\d+)", text, calibration.MAX_LOSS_VS_MARKET)
    said(r"«EV calibrado ≥ (\d+) %».*?≥ (\d+) selecciones y \*\*CLV medio ≥ (\d+)\*\*", text,
         calibration.EV_RULE * 100, calibration.MIN_RULE_N, calibration.MIN_RULE_CLV)
    said(r"mejora el log loss del champion en ≥ (0,\d+)", text, calibration.REPLACE_GAIN)


# ── the AI budget ─────────────────────────────────────────────────────────────

def test_the_budget_the_document_gives_is_the_servers_and_the_default_is_the_codes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    flat = " ".join(section(PI, 9).split())
    monkeypatch.setattr("fbi.ai.config.environment", lambda: {})
    default = AiSettings.from_env()
    assert default.monthly_budget == AiSettings().monthly_budget, "the dataclass default and the environment's agree"
    said(r"Sin esa variable el código usa \*\*US\$(\d+)\*\*", flat, float(default.monthly_budget))
    assert "FBI_AI_MONTHLY_BUDGET_USD=180" in flat and "US$180 en el servidor" in flat
    assert "mes/30" in flat and default.daily_budget == (default.monthly_budget / 30).quantize(Decimal("0.01"))
    alerts = re.search(r"Alertas ((?:\d+/)+\d+) %", flat)
    assert alerts, "the budget alerts are no longer listed"
    assert tuple(int(x) for x in alerts[1].split("/")) == usage.ALERT_THRESHOLDS
    said(r"techo (\d+,\d+)\N{MULTIPLICATION SIGN}", flat, float(usage.HARD_FACTOR))
    said(r"se detiene al (\d+) % del presupuesto del día", flat, float(usage.MARGINAL_SHARE) * 100)
    said(r"con el mes ≥ (\d+) %", flat, usage.MARGINAL_MONTH * 100)


def test_the_variables_of_the_ai_layers_document_have_the_codes_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fbi.ai.config.environment", lambda: {})
    s = AiSettings.from_env()
    text = " ".join(section(LAYER, 7).split())
    defaults: dict[str, Decimal | int] = {"FBI_AI_MONTHLY_BUDGET_USD": s.monthly_budget, "FBI_AI_DAILY_MAX_FACTOR": s.daily_max_factor,
                "FBI_AI_MAX_LLM_REVIEWS_PER_DAY": s.max_llm_reviews_per_day, "FBI_AI_MAX_DEEP_PER_DAY": s.max_deep_per_day,
                "FBI_AI_MAX_WEB_FIRST": s.max_web_first, "FBI_AI_MAX_WEB_PRE": s.max_web_pre,
                "FBI_AI_MAX_WATCH_PER_DAY": s.max_watch_per_day, "FBI_AI_HORIZON_HOURS": s.horizon_hours}
    for name, value in defaults.items():
        said(rf"`{name}` \((\d+)", text, float(value))


# ── the one post-mortem and the memory (plan F8) ─────────────────────────────

def memory_table() -> dict[str, tuple[float, ...]]:
    """The conventions table of the longitudinal memory (section 7): what it is the memory of -> (half-life in days, k...)."""
    rows: dict[str, tuple[float, ...]] = {}
    for m in re.finditer(r"^\s*\| ([^|]+) \| (\d+) \| ([\d /]+) \|$", section(PI, 7), flags=re.M):
        rows[m[1].strip()] = (float(m[2]), *(float(k) for k in m[3].split("/")))
    return rows


def test_the_memory_conventions_table_is_the_codes() -> None:
    """The half-lives and the ``k`` are conventions of the memory (changing one is a new version and a rebuild): the document lists
    them, and a table that says something else than ``fbi.intel.memory`` fails here."""
    table = memory_table()
    one_each = {
        "Decisiones de un equipo": memory.DECISIONS_TEAM,
        "Decisiones de una competición": memory.DECISIONS_COMPETITION,
        "Decisiones de un mercado": memory.DECISIONS_MARKET,
        "Árbitro (persona)": memory.REFEREE,
        "Entrenador (por id)": memory.COACH,
        "Jugador (disponibilidad)": memory.PLAYER,
        "Córners, tarjetas y goles esperados de una liga": memory.LEAGUE_FIGURES,
    }
    for label, spec in one_each.items():
        assert table.get(label) == (spec.half_life, spec.k), label
    teams = [memory.TEAM_FIGURES[aspect] for aspect in ("corners", "cards", "xg")]
    assert table.get("Córners, tarjetas y goles esperados de un equipo") == (teams[0].half_life, *(s.k for s in teams))
    assert {s.half_life for s in teams} == {teams[0].half_life}, "the three figures of a team share one half-life"
    assert len(table) == len(one_each) + 1, f"a kind of memory the test does not know: {sorted(table)}"


def test_the_memory_paragraph_says_what_the_code_does() -> None:
    flat = " ".join(section(PI, 7).split())
    said(r"las (\d+) más recientes\)", flat, memory.MAX_SOURCES)
    said(r"`memory-v4` no continúa ninguna versión anterior; empieza el (\d+) de octubre de (\d+)", flat,
         memory.LINEAGE_START.day, memory.LINEAGE_START.year)
    assert memory.LINEAGE_START.month == 10
    assert f"`{memory.VERSION}`" in flat
    assert "`confidence` = `n_eff / (n_eff + k)`" in flat, "the confidence formula is no longer written"


def test_the_post_mortem_paragraph_says_what_the_code_does() -> None:
    flat = " ".join(section(PI, 7).split())
    assert f"`{postmortem.VERSION}`" in flat
    said(r"Se estudia (\d+) horas después del inicio y mira los últimos (\d+) días", flat,
         hours(postmortem.SETTLE_DELAY), postmortem.LOOKBACK.days)
    said(r"las (\d+) mejores INVESTIGACIONES", flat, postmortem.TOP_INVESTIGATION)
    said(r"BUENO / NEUTRO / MALO, ±(\d+) %", flat, closing_value.GOOD * 100)
    assert postmortem.GOOD_CLV == closing_value.GOOD
    assert f"`{closing_reference.REFERENCE}`" in flat, "the named close is no longer written"
    said(r"marca `far` si fueron más de (\d+)", flat, closing_reference.FAR_FROM_KICKOFF)


def test_the_ai_layers_post_mortem_text_says_what_the_code_does() -> None:
    """Section 5 of the AI layer's document (the rest of it is not compared; section 7 is, above)."""
    flat = " ".join(section(LAYER, 5).split())
    for version in (postmortem.VERSION, pm_narratives.VERSION, learning.VERSION):
        assert f"`{version}`" in flat, version
    said(r"Se estudia (\d+) horas después del inicio, mira los últimos (\d+) días", flat,
         hours(postmortem.SETTLE_DELAY), postmortem.LOOKBACK.days)
    said(r"Haiku, máx\. (\d+) por corrida, y Sonnet para las pérdidas de picks del día, (\d+); ventana de (\d+) días", flat,
         pm_narratives.MAX_NARRATIVES, pm_narratives.MAX_STRONG_NARRATIVES, pm_narratives.LOOKBACK.days)
    said(r"precio bueno / neutro / malo con banda ±(\d+) %", flat, closing_value.GOOD * 100)


def test_the_catalogue_guide_says_what_the_code_does() -> None:
    """Plan F9: the guide of the catalogue of markets - the rules, the windows, the minimum of houses and the thresholds of the matrix."""
    from fbi.market import matrix as mx
    from fbi.market import rules as mr

    doc = read_doc("owner", "CATALOGO_MERCADOS_F9.md")
    for rule in mr.RULES:
        assert f"`{rule.key}`" in doc, f"the guide leaves out the rule {rule.key}"
    liquidable = sum(1 for r in mr.RULES if r.liquidable)
    assert f"{len(mr.RULES)} reglas, de las que {liquidable} pueden liquidar" in doc
    assert f"`{mx.MATRIX_VERSION}`" in doc and f"{len(mx.ROWS)} filas por familia" in doc
    assert f"Precios de los últimos {mx.PRICE_DAYS} días" in doc and f"resultados de los últimos {mx.OUTCOME_DAYS} días" in doc
    assert f"al menos {mx.MIN_HOUSES} casas" in doc
    assert f"cobertura de precio de {round(mx.HIGH_PRICE_COVERAGE * 100)} % o más" in doc
    assert abs(mx.MEDIUM_PRICE_COVERAGE - 1 / 3) < 1e-9 and "Media**: un tercio o más" in doc
    assert f"al menos {mx.HIGH_RESULTS:,}".replace(",", ".") + " partidos" in doc
    assert f"al menos {mx.MEDIUM_RESULTS:,}".replace(",", ".") + " partidos" in doc
    assert "los córners de una parte no se pueden\nliquidar" in doc and not mr.RULES_BY_KEY["corners_1h@v1"].liquidable
    # the booking points of the guide are the view's: 10 a yellow, 25 a straight red, 15 more for the red after a second yellow
    migration = (DOCS.parent / "migrations" / "versions" / "0092_market_catalogue.py").read_text(encoding="utf-8")
    assert "10 * " in migration.replace("10*", "10 * ") and "25 * " in migration and "15 * " in migration
    assert "10 por amarilla, 25 por roja directa, 15 más" in doc
