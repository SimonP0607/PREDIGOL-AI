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
``fbi.market`` and ``fbi.ai.pm_narratives``.

Plan F11.6 adds the guide of the dependence between the families of one match, which is not only a text about the code but a reading of
the data: its numbers are the ones of the result stored next to it (``DEPENDENCIA_FAMILIAS_F11_resultado.json``), and the stored result
is held to the code's own arithmetic (every verdict re-derived from the lifts and their intervals). A guide whose table says one thing
and a stored result another, or a stored result that the code would no longer judge the same way, fails here."""

from __future__ import annotations

import argparse
import inspect
import json
import math
import re
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import learning, pm_narratives, usage
from fbi.ai.config import AiSettings
from fbi.families import bets, dependence, variants
from fbi.intel import calibration, decision, memory, postmortem, score, stake
from fbi.market import closing_reference, closing_value
from fbi.research import pattern_search as ps

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


def test_the_families_guide_says_what_the_code_does() -> None:
    """Plan F10: the guide of the models by family - the version, the models and their families, the parameters, the thresholds and the switches."""
    from fbi.families import fit, forecast, referee, versioning
    from fbi.predictions.forecast import HORIZON, MIN_LEAD

    doc = read_doc("owner", "FAMILIAS_F10.md")
    assert f"**`{forecast.VERSION}`**" in doc and f"**`{versioning.REGISTRY_FAMILY}`**" in doc and "migración 0093" in doc
    for spec in forecast.SPECS:
        assert f"`{spec.model}`" in doc and f"`{spec.family}`" in doc, f"the guide leaves out {spec.key}"
        xi, penalty = str(spec.xi).replace(".", ","), f"{spec.penalty:g}".replace(".", ",")
        assert f"(`{spec.model}`; decaimiento {xi}, encogimiento {penalty})" in doc, f"the guide does not state the parameters of {spec.key}"
    for spec in forecast.SPECS:
        if spec.referee_kappa:
            assert f"`{spec.model}`" in doc and f"un prior de {spec.referee_kappa:g} tarjetas" in doc, f"the guide does not state the referee prior of {spec.key}"
    assert f"al menos {referee.MIN_MATCHES} partidos conocidos" in doc
    assert f"**{fit.OUTCOME_KNOWN_AFTER.total_seconds() / 3600:g} horas después de su inicio**" in doc
    assert f"al menos {fit.MIN_TRAIN} partidos, un equipo se pronostica con al menos {fit.MIN_TEAM_MATCHES}" in doc
    assert f"más de {forecast.MAX_TEAMS} equipos" in doc
    assert f"se ajusta {forecast.DISPERSION_DAYS} días atrás" in doc and f"al menos {forecast.MIN_DISPERSION_MATCHES} partidos así" in doc
    assert f"dentro de los próximos {HORIZON.days} días (y no dentro de los próximos {int(MIN_LEAD.total_seconds() // 60)} minutos)" in doc
    assert "`FBI_FAMILY_FORECASTS`" in doc and "`FBI_FAMILY_FORECAST_MINUTES`" in doc and "cada 3 horas" in doc
    assert "| `FBI_FAMILY_FORECAST_MINUTES` | cada cuántos minutos corre | 180 |" in doc
    assert "`1.0.0/<especificación>@fc<huella>`" in doc and versioning.FAMILY_SEMVER == "1.0.0"
    assert "`mc9a7bec97ca`" in doc, "the fingerprint of the goal models, which F10 does not touch"


def test_the_guide_of_the_families_against_the_market_says_what_the_code_does() -> None:
    """Plan F11: the guide of the comparison with the books - the least number of books, the margin that is still a price, the moments the market is
    read at, the kinds of bet it is built for and the options of the command that repeats it."""
    from scripts import families as cli

    from fbi.families import versus

    doc = read_doc("owner", "FAMILIAS_VS_MERCADO_F11.md")
    assert f"**Con menos de {versus.MIN_BOOKS} casas no hay consenso y no se compara.**" in doc
    assert f"como mucho {str(versus.MAX_OVERROUND).replace('.', ',')}" in doc and "por encima de 1" in doc
    assert [name for name, _ in versus.REFERENCES] == ["close", "h24"], "the guide speaks of the last price and of a day before"
    assert "el **último precio** antes del inicio" in doc and f"**{int(versus.REFERENCES[1][1].total_seconds() // 3600)} horas antes**" in doc
    assert set(versus.OUTCOMES) == {"over_under", "both_teams_score", "odd_even", "draw_no_bet", "one_x_two"}
    assert "más/menos, ambos marcan, par/impar, empate no apuesta y 1X2" in doc
    assert "(sin línea, o con «medio»" in doc and versus.comparable(Decimal("9.5")) and not versus.comparable(Decimal("10"))
    args = cli.build_parser().parse_args(["score", "--days", "14", "--no-market", "--min-books", "4"])
    assert args.no_market is True and args.min_books == 4 and cli.build_parser().parse_args(["score"]).min_books == versus.MIN_BOOKS
    for option in ("--no-market", "--min-books", "python -m scripts.families score"):
        assert option in doc, f"the guide leaves out {option}"


def test_the_guide_of_the_criterion_for_a_family_says_what_the_code_does() -> None:
    """Plan F11.5: the guide of the criterion for a family to decide in shadow - the bets and the value the plan asks for, the moment of the bet, the
    books behind a price, the one definition of the closing-line value, the three verdicts it prints and the options of the command that repeats it."""
    from scripts import families as cli

    from fbi.families import versus

    doc = read_doc("owner", "CRITERIO_FAMILIAS_F11.md")
    assert f"**al menos {bets.MIN_BETS} apuestas simuladas**" in doc and "(el texto dice cuántas faltan)" in doc
    assert f"es de **al menos {bets.MIN_EV * 100:g} %**" in doc
    assert f"**{hours(bets.PICK_LEAD):g} horas o más antes del inicio**" in doc and bets.PICK_REF == "h24"
    assert f"con **{versus.MIN_BOOKS} casas o más** detrás" in doc
    assert f"como mucho {str(versus.MAX_OVERROUND).replace('.', ',')}" in doc and "por encima de 1" in doc
    assert closing_value.VERSION == "clv-v1" and "`clv-v1`" in doc and "`fbi.market.closing_value`" in doc
    for printed in bets.WORDS.values():
        assert f"`{printed}`" in doc, f"the guide leaves out the verdict {printed!r}"
    assert bets.verdict(bets.MIN_BETS, 0.0) == bets.MEETS and "(el cero pasa)" in doc
    assert bets.verdict(bets.MIN_BETS, -1e-9) == bets.CLV_NEGATIVE and bets.verdict(bets.MIN_BETS - 1, 1.0) == bets.TOO_FEW
    assert "within 2 standard errors of zero" in Path(bets.__file__).read_text(encoding="utf-8") and "*«but the closing-line value is within 2 standard errors of zero»*" in doc
    assert f"tandas de {versus.CHUNK} partidos" in doc
    parser = cli.build_parser()
    assert parser.parse_args(["score"]).min_ev == bets.MIN_EV and parser.parse_args(["score", "--min-ev", "0.05"]).min_ev == 0.05
    assert parser.parse_args(["score"]).wait_hours == 30.0 and "30 horas" in doc
    for option in ("python -m scripts.families score --days 60", "--min-ev 0.05", "--json"):
        assert option in doc, f"the guide leaves out {option}"
    assert (DOCS / "owner" / "FAMILIAS_VS_MERCADO_F11.md").is_file() and "`FAMILIAS_VS_MERCADO_F11.md`" in doc
    assert "`CRITERIO_FAMILIAS_F11.md`" in read_doc("owner", "FAMILIAS_VS_MERCADO_F11.md"), "the guide of the comparison points to this one"


def test_the_guide_of_the_cycle_of_the_families_says_what_the_code_does(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan F11: the guide of the cycle of the families in shadow - the switch and what it means, the four steps with their versions and the moment each
    runs, the rule that makes a selection a candidate, the cap and the stake, the wait before a decision is settled, the six rules that grade it, the bands of
    the quality of a price and the six verdicts, the conventions of the memory, the page of the Admin Console and the place the example of the settings points
    at."""
    from apps.worker import scheduler

    from fbi.api.routers import intelligence as router
    from fbi.api.services import families as page
    from fbi.core import decision_versions as versions
    from fbi.families import versus
    from fbi.familydecisions import decide as fd
    from fbi.familydecisions import memory as fm
    from fbi.familydecisions import outcomes as fo
    from fbi.familydecisions import postmortem as fp
    from fbi.intel import cycle
    from fbi.intel import outcomes as pipeline_outcomes
    from fbi.intel import postmortem as pipeline_pm
    from fbi.intel import stake as staking
    from fbi.market import rules

    guide = "CICLO_FAMILIAS_F11.md"
    doc = read_doc("owner", guide)
    flat = " ".join(doc.split())
    # the four versions, and the one of the forecasts they judge
    assert (versions.DECISION_FAMILIES, versions.OUTCOME_FAMILIES, versions.POSTMORTEM_FAMILIES, versions.MEMORY_FAMILIES) == (
        "decision-fam-v1", "outcome-fam-v1", "pm-fam-v1", "memory-fam-v1")
    for version in (versions.DECISION_FAMILIES, versions.OUTCOME_FAMILIES, versions.POSTMORTEM_FAMILIES, versions.MEMORY_FAMILIES, fd.FORECAST_VERSION):
        assert f"`{version}`" in doc, f"the guide leaves out {version}"
    assert fd.FORECAST_VERSION == "family-v1" and set(fd.SPECS) == {"GOALS_HALF", "CORNERS", "CARDS", "YELLOW"}
    assert "Las familias (goles por mitad, córners, tarjetas y amarillas)" in flat
    # the switch: off by default, whatever is not "shadow" means off, and the worker has to be restarted to read it
    assert fd.SWITCH == "FBI_FAMILY_DECISIONS" and fd.MODES == ("off", "shadow") and f"`{fd.SWITCH}=shadow`" in doc
    for value, want in ((None, "off"), ("", "off"), ("off", "off"), ("shadow", "shadow"), (" SHADOW ", "shadow"), ("on", "off"), ("1", "off")):
        monkeypatch.setattr(fd, "environment", lambda value=value: {} if value is None else {fd.SWITCH: value})
        assert fd.mode() == want, value
    modes = section_of(doc, "## 2. El interruptor")
    assert "| `off` (por omisión, y cualquier valor desconocido) | nada: el trabajo de decisión y el de la noche siguen como antes de las familias, " \
           "sin ningún paso suyo y sin ninguna clave suya en su registro |" in modes
    assert "| `shadow` | una pasada de decisión por hora y, de noche, la liquidación, el post-mortem y la memoria |" in modes
    assert "`/etc/predigol/app.env`" in flat and "`deploy/vps/app.env.example`" in flat and "hay que reiniciar el worker" in flat
    migration = DOCS.parent / "migrations" / "versions" / "0094_family_learning.py"
    if migration.is_file():
        text = migration.read_text(encoding="utf-8")
        assert "intel.family_postmortems" in text and "intel.family_memory" in text and "family_memory_latest" in text, "0094 makes the tables the guide names"
    assert "la migración `0094`" in flat
    # the steps: each one of its job, in the order of the nightly job, with its version and the table it writes
    monkeypatch.setattr(fd, "mode", lambda: "shadow")
    at = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    decide_steps = scheduler.family_decide_steps(None, at)  # type: ignore[arg-type]  # the steps are built, not run
    night_steps = scheduler.family_nightly_steps(None, at)  # type: ignore[arg-type]
    assert {after: [name for name, _ in steps] for after, steps in decide_steps.items()} == {"select": ["families"]}
    assert {after: [name for name, _ in steps] for after, steps in night_steps.items()} == {
        "outcomes": ["family_outcomes"], "postmortems": ["family_postmortems"], "memory": ["family_memory"]}
    nightly = [("outcomes", lambda: None), ("postmortems", lambda: None), ("memory", lambda: None), ("calibration", lambda: None)]
    assert [name for name, _ in cycle.with_extra(nightly, night_steps)] == [
        "outcomes", "family_outcomes", "postmortems", "family_postmortems", "memory", "family_memory", "calibration"]
    decide_job = [("decide", lambda: None), ("select", lambda: None)]
    assert [name for name, _ in cycle.with_extra(decide_job, decide_steps)] == ["decide", "select", "families"]
    assert list(page.STEPS) == ["families", "family_outcomes", "family_postmortems", "family_memory"]
    steps = [[cell.strip() for cell in row.strip("|").split("|")] for row in table_rows(section_of(doc, "## 3. Los cuatro pasos"), "| Paso |")]
    assert [row[0] for row in steps] == ["Decidir", "Liquidar", "Post-mortem", "Recordar"]
    assert [row[1] for row in steps] == [f"`{name}` (dentro de `{job}`)" for name, job in (
        ("families", "intel_decide"), ("family_outcomes", "intel_nightly"), ("family_postmortems", "intel_nightly"), ("family_memory", "intel_nightly"))]
    assert [row[3] for row in steps] == [f"`{v}`" for v in (versions.DECISION_FAMILIES, versions.OUTCOME_FAMILIES, versions.POSTMORTEM_FAMILIES,
                                                           versions.MEMORY_FAMILIES)]
    assert [row[4] for row in steps] == ["`intel.decisions`, sin pick", "`intel.decision_outcomes`", "`intel.family_postmortems`",
                                         "`intel.family_memory` (y la vista `intel.family_memory_latest`)"]
    assert scheduler.INTEL_DECIDE_MINUTES == 15 and "el trabajo que viene cada 15 minutos" in steps[0][2]
    assert timedelta(minutes=60) == fd.EVERY and "una vez por hora" in steps[0][2]
    assert fd.due(datetime(2026, 10, 25, 12, 0, tzinfo=UTC)) and fd.due(datetime(2026, 10, 25, 12, 14, tzinfo=UTC))
    assert not fd.due(datetime(2026, 10, 25, 12, 15, tzinfo=UTC)) and not fd.due(datetime(2026, 10, 25, 12, 45, tzinfo=UTC)), "the first pass of each hour"
    assert (scheduler.INTEL_NIGHTLY_HOUR, scheduler.INTEL_NIGHTLY_MINUTE) == (7, 50) and "a las 07:50 hora de Bogotá" in steps[1][2]
    assert "después** de elegir los picks del día" in steps[0][2]
    # what makes a selection a candidate
    assert f"**próximas {hours(fd.HORIZON):g} horas**" in flat
    assert f"**{versus.MIN_BOOKS} casas completas o más**" in flat
    assert f"con un margen de {str(versus.MAX_OVERROUND).replace('.', ',')} como mucho" in flat
    assert f"un **valor visto de al menos {fd.MIN_EV * 100:g} %**" in flat and fd.MIN_EV == bets.MIN_EV
    assert set(versus.OUTCOMES) == {"over_under", "both_teams_score", "odd_even", "draw_no_bet", "one_x_two"}
    assert "más/menos, ambos marcan, par/impar, empate no apuesta y 1X2" in flat
    assert versus.comparable(Decimal("9.5")) and not versus.comparable(Decimal("10")) and "(sin línea, o con «medio»)" in flat
    assert "`CRITERIO_FAMILIAS_F11.md`" in flat and "`PREDIGOL_INTELLIGENCE.md`, sección 5" in flat
    assert (DOCS / "intelligence" / "PREDIGOL_INTELLIGENCE.md").is_file() and (DOCS / "owner" / "CRITERIO_FAMILIAS_F11.md").is_file()
    # the cap, the stake and the reasons a row carries
    assert page.STATES == ("INVESTIGACION", "RECHAZADO") and "`INVESTIGACION`" in doc and "`RECHAZADO`" in doc
    assert staking.CAPS["INVESTIGACION"] == 0.0 and staking.CAPS["RECHAZADO"] == 0.0 and "**La apuesta es cero.**" in flat
    assert (fd.REASON_RESEARCH, fd.REASON_CAPPED) == ("family_research", "family_shadow_only")
    assert "`family_shadow_only`" in doc and "`family_research`" in doc
    assert (Path(__file__).parent / "test_decision_version_guard.py").is_file() and "`test_decision_version_guard.py`" in doc
    # the settlement: the wait, the look-back, the six rules, the profit of a unit and the close
    assert timedelta(hours=30) == fo.WAIT and f"liquida las decisiones de los partidos que terminaron **{hours(fo.WAIT):g} horas** atrás" in flat
    assert timedelta(days=30) == fo.LOOKBACK and f"que no pasaron de hace **{fo.LOOKBACK.days} días**" in flat
    assert fo.CLOSE_MIN_BOOKS == versus.MIN_BOOKS and "con las mismas 3 casas completas como mínimo" in flat
    assert closing_value.VERSION == "clv-v1" and "(`clv-v1`, la única definición del sistema)" in flat
    graded = [row[0] for row in (cells_of_rows(section_of(doc, "## 5. Cómo se liquida")))]
    keys = sorted(page.rules_of_families())
    assert keys == ["cards_lines_ft@v1", "corners_ft@v1", "goals_1h@v1", "goals_2h@v1", "goals_halves@v1", "yellow_ft@v1"]
    assert sorted(cell.strip("`") for cell in graded if cell.startswith("`")) == keys and all(rules.RULES_BY_KEY[key].liquidable for key in keys)
    assert [pipeline_outcomes.profit_per_unit(result, Decimal("2.5")) for result in ("win", "half_win", "push", "void", "half_loss", "loss")] == [
        Decimal("1.5"), Decimal("0.75"), Decimal(0), Decimal(0), Decimal("-0.5"), Decimal(-1)]
    assert "gana, cuota - 1; media ganada, (cuota - 1) / 2; devuelta o anulada, 0; media perdida, -½; pierde, -1" in flat
    # the post-mortem: the bands of the price, the six verdicts as the code gives them and the lesson of each
    assert closing_value.GOOD == 0.01 and "por encima de +1 % es `GOOD`, por debajo de -1 % es `BAD`, entre medias `NEUTRAL`, y sin cierre `UNKNOWN`" in flat
    assert [closing_value.quality(x) for x in (0.011, 0.0, -0.011, None)] == ["GOOD", "NEUTRAL", "BAD", "UNKNOWN"]
    verdicts = {row[2].strip("`"): row for row in ([cell.strip() for cell in line.strip("|").split("|")] for line in table_rows(section_of(doc, "## 6. Qué aprende de cada decisión (el post-mortem)"), "| Resultado |"))}
    assert set(verdicts) == set(fm.VERDICTS) == set(fp.LESSON) and [row[3] for row in verdicts.values()] == [fp.LESSON[v] for v in verdicts]
    asked = {"ganó": ("win", "half_win"), "perdió": ("loss", "half_loss"), "devuelta o anulada": ("push", "void"), "cualquiera": ("win", "loss")}
    quality = {"buena o neutra": ("GOOD", "NEUTRAL"), "mala": ("BAD",), "cualquiera": ("GOOD", "NEUTRAL", "BAD"), "sin cierre": ("UNKNOWN",)}
    for verdict, (result_text, quality_text, _, _) in verdicts.items():
        for result in asked[result_text]:
            for q in quality[quality_text]:
                if verdict == "SIN_DATOS" and result in ("push", "void"):
                    continue
                assert pipeline_pm.verdict_of(result, q) == verdict, (result, q, verdict)
    assert pipeline_pm.verdict_of("void", "UNKNOWN") == "NULO" and "una investigación) y no un rechazo" in flat
    # the memory: the entities and how many post-mortems each needs, the windows and the confidence
    assert fm.ENTITY_TYPES == ("family", "market", "competition", "referee") and fm.NEEDS == {"family": 1, "market": 1, "competition": 3, "referee": 3}
    assert "Una competición o un árbitro necesitan al menos 3 post-mortems para existir" in flat and "una familia o un mercado, uno" in flat
    assert fm.RECENT_DAYS == 28 and f"últimos **{fm.RECENT_DAYS} días**" in flat
    assert fm.HALF_LIFE_DAYS == 60.0 and f"cada **{fm.HALF_LIFE_DAYS:g} días**" in flat and f"`n_eff / (n_eff + {fm.PRIOR:g})`" in flat and fm.PRIOR == 30.0
    assert f"Los {fm.RECENT_DAYS}, los {fm.HALF_LIFE_DAYS:g} y los {fm.PRIOR:g} son convenciones de la memoria" in flat and "es `memory-fam-v2`" in flat
    # the page of the Admin Console
    assert any(getattr(route, "path", None) == "/intelligence/families" for route in router.router.routes) and "`GET /admin/intelligence/families`" in doc
    assert (page.DEFAULT_DAYS, page.MAX_DAYS, page.MEMORY_TOP) == (14, 120, 25) and "(por omisión 14 días, como mucho 120)" in flat
    assert "los 25 con más post-mortems de cada tipo" in flat and timedelta(days=7) == page.STEPS_LOOKBACK and "Mira los últimos **7 días**" in flat
    assert "`/admin/learning#tab=families`" in doc
    # the example of the settings of the server
    example = DOCS.parent / "deploy" / "vps" / "app.env.example"
    if example.is_file():
        variables = example.read_text(encoding="utf-8")
        assert f"# {fd.SWITCH}=off" in variables and f"docs/owner/{guide}" in variables, "the default is off and the example points at the guide"
        for mode_name in fd.MODES:
            assert f"#   {mode_name} " in variables
    for name in ("FAMILIAS_F10.md", "CRITERIO_FAMILIAS_F11.md", "DEPENDENCIA_FAMILIAS_F11.md", "PROMOCIONES_F12.md", "POSTMORTEM_MEMORIA_F8.md"):
        assert (DOCS / "owner" / name).is_file() and f"`{name}`" in doc, f"the guide points to {name}"


def test_the_guide_of_the_cycle_says_how_to_see_the_decisions_before_the_switch_is_on() -> None:
    """Plan F11.12: the command that runs the pass as a dry run - its name and options, that it cannot write, the window it reads, the steps of the
    funnel, that it needs no migration of the learning tables, and where the owner is told to use it."""
    from scripts import families as cli

    from fbi.familydecisions import decide as fd
    from fbi.familydecisions import preview

    doc = read_doc("owner", "CICLO_FAMILIAS_F11.md")
    flat = " ".join(doc.split())
    start = flat.index("**Verlo antes de encenderlo.**")
    seen = flat[start:flat.index("## 3. Los cuatro pasos")]
    # the command and its options exist, and the guide names every one of them
    parser = cli.build_parser()
    commands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    sub = commands.choices["decide"]
    options = {o for a in sub._actions for o in a.option_strings if o.startswith("--") and o != "--help"}
    assert options == {"--at", "--horizon-hours", "--fixture", "--top", "--json"}
    assert "`python -m scripts.families decide`" in seen
    for option in options - {"--horizon-hours"}:
        assert f"`{option}`" in seen, f"the guide says what {option} does"
    # it reads what the pass reads, over the window of the pass, and cannot write
    assert timedelta(hours=36) == fd.HORIZON and "las próximas 36 horas" in seen and sub.get_default("horizon_hours") == 36.0
    assert "una sesión de la base de datos que no puede escribir" in seen and "cero peticiones al proveedor, cero IA" in seen
    assert "los diez filtros" in seen
    # the funnel, step by step, in the order the text prints it
    assert "pronósticos → selecciones con precio → candidatas → decisiones juzgadas → filas que escribiría" in seen
    text = preview.render(preview.summarise(fd.FamilyReport(forecasts=1, fixtures=1), [], at=datetime(2035, 3, 1, tzinfo=UTC),
                                            horizon=fd.HORIZON, mode="off"))
    steps = ["forecasts", "priced selections", "candidates", "judged", "rows to write"]
    assert [text.index(step) for step in steps] == sorted(text.index(step) for step in steps), "the steps of the funnel come in the order the guide says"
    assert "por familia, estado y motivo" in seen and "en qué paso se agotó" in seen
    # it needs only what production already has: none of the tables the learning steps create (migration 0094) is read by the pass
    assert "no necesita la migración `0094`" in seen
    for table in ("family_postmortems", "family_memory"):
        assert table not in inspect.getsource(fd) and table not in inspect.getsource(preview)
    # and the owner is sent to it before the decision about the switch
    decisions = flat[flat.index("## 10. Lo que decides tú"):]
    assert "Antes de decidir, mira qué escribiría con `python -m scripts.families decide` (sección 2)." in decisions


def test_the_guide_of_the_cycle_says_what_a_decision_of_a_family_did_not_know() -> None:
    """Plan F11.10: the formal request for research a decision of a family carries - the version and the key of the record, the three things it can lack and
    who brings each, what each family asks for, the words of the context, what finding out costs in searches, that nothing serves it and why, the factors that
    could explain each family, and that it is informational, read as of the moment of the decision and refreshed only when a row is written."""
    from fbi.ai import research as ai_research
    from fbi.api.services import families as page
    from fbi.familydecisions import decide as fd
    from fbi.familydecisions import research
    from fbi.intel import factors

    doc = read_doc("owner", "CICLO_FAMILIAS_F11.md")
    flat = " ".join(doc.split())
    start = flat.index("**Lo que la decisión no sabía: pedir investigación.**")
    asked = flat[start:flat.index("## 5. Cómo se liquida")]
    assert research.KEY == "research" and research.VERSION == "research-fam-v1" and f"`{research.KEY}` (versión `{research.VERSION}`)" in asked
    # the three things, who brings each one, and the states
    assert set(research.NEEDS) == {"referee", "lineups", "context"}
    assert research.NEEDS["referee"].source == research.NEEDS["lineups"].source == research.PROVIDER and research.NEEDS["context"].source == research.SEARCH
    assert "*el árbitro designado* y *las alineaciones confirmadas*, que trae el proveedor sin ninguna búsqueda" in asked
    assert "*el contexto de fuera* (bajas y previa), lo único que solo una búsqueda mejora" in asked
    assert research.STATES == ("KNOWN", "PARTIAL", "MISSING")
    assert "(`KNOWN` sabida, `PARTIAL` en parte, `MISSING` falta)" in asked
    # what each family asks for, and why
    assert research.OF_FAMILY["GOALS_HALF"] == research.OF_FAMILY["CORNERS"] == ("lineups", "context")
    assert research.OF_FAMILY["CARDS"] == research.OF_FAMILY["YELLOW"] == ("referee", "context") and set(research.OF_FAMILY) == set(fd.SPECS)
    assert "los goles por mitad y los córners, alineaciones y contexto" in asked and "las tarjetas y las amarillas, árbitro y contexto" in asked
    assert "multiplica la media por el factor del árbitro cuando hay uno designado" in asked
    # the context is the word the ten filters already use
    assert research.CONTEXT_STATE == {"FULL": "KNOWN", "PARTIAL": "PARTIAL", "LIMITED": "MISSING", "PENDING": "MISSING", "AI_OFF": "MISSING"}
    assert "completo es sabido, parcial es en parte, y limitado, pendiente o IA apagada es que falta" in asked
    # the cost: one search a level, all three for the context, and one search serves every selection of the match
    assert research.NEEDS["context"].levels == (1, 2, 3) == tuple(range(1, ai_research.FULL + 1))
    assert research.NEEDS["referee"].levels == research.NEEDS["lineups"].levels == ()
    assert "una por nivel; el contexto abarca los tres niveles, así que son 3 búsquedas" in asked
    assert "la búsqueda de un nivel sirve a todas las selecciones del mismo partido" in asked and "Lo que solo trae el proveedor no cuesta ninguna." in asked
    # nothing serves it, and says why only when a search is what is missing
    assert research.UNSERVED == "family_shadow" and research.UNSERVED not in ai_research.UNSERVED
    assert "`served` es falso y, cuando lo que falta se pediría a una búsqueda, `unserved` dice `family_shadow`" in asked
    assert "las búsquedas y el presupuesto del día son tuyos (decisión 12 del estado del plan)" in asked
    # the factors that could explain each family
    for key in sum(research.HYPOTHESES.values(), ()):
        assert key in factors.BY_KEY
    assert "tactics_profile" in research.HYPOTHESES["GOALS_HALF"] and "tactics_profile" in research.HYPOTHESES["CORNERS"]
    assert all("scenarios" in research.HYPOTHESES[family] for family in ("GOALS_HALF", "CARDS", "YELLOW")) and "scenarios" not in research.HYPOTHESES["CORNERS"]
    assert "rest_congestion" in research.HYPOTHESES["GOALS_HALF"] and not any("rest_congestion" in research.HYPOTHESES[f] for f in ("CORNERS", "CARDS", "YELLOW"))
    assert not any("h2h_weighted" in names for names in research.HYPOTHESES.values())
    for label in (factors.BY_KEY[k].label for k in ("tactics_profile", "scenarios", "rest_congestion")):
        assert label.lower() in asked, f"the guide names the factor {label}"
    assert "la *táctica observable* para los goles por mitad y los córners" in asked
    assert "los *escenarios de tabla y de eliminatoria* para los goles por mitad, las tarjetas y las amarillas" in asked
    assert "el *descanso y congestión* para los goles por mitad" in asked
    assert research.DESCRIPTIVE == factors.DESCRIPTIVE and "un factor es descriptivo hasta que una persona valida un experimento suyo" in asked
    assert "ningún modelo de una familia lee ninguno" in asked
    # informational, as of the moment of the decision, and refreshed only with a row
    assert fd.finalise.__doc__ and "informational" in fd.finalise.__doc__
    assert "no cambia el estado, ni los motivos, ni la puntuación, ni la apuesta de la decisión" in asked
    assert "tal como estaban en el momento de la decisión" in asked and "solo cuando se escribe una fila nueva" in asked
    assert "Si esa lectura falla, la decisión se escribe igual, sin el registro" in asked
    # the page of the Admin Console reads it
    assert "research" in page.LAST_SQL and "«Qué le falta saber»" in flat and "«Sin registro»" in flat and "el filtro «Pedir investigación»" in asked
    assert "decisión 12" in flat and "**¿Servir algún día las peticiones de investigación de una familia?**" in flat


def test_the_guides_say_who_sees_what_the_families_forecast() -> None:
    """Plan F10.17b: what the families forecast is shown in the Admin Console's preview of a match, in a section of its own, and to no user. The guides say
    it as the contract and the page of the forecast do: the version, the field, and that it is null in every other answer."""
    from fbi.api.contracts.forecast import MatchForecast
    from fbi.api.services import forecast as page
    from fbi.families import forecast as families

    field = MatchForecast.model_fields["families"]
    assert field.default is None and page.FAMILY_VERSION == families.VERSION, "the field is null unless the preview fills it, and it reads the families' version"
    assert len({page.VERSION, page.FAMILY_VERSION}) == 2 and "forecast" in MatchForecast.model_fields, "the forecast of the match is another section, of another version"

    def flat(*parts: str) -> str:
        return " ".join(read_doc(*parts).split())

    f5, f10, cycle = flat("owner", "PRONOSTICO_F5.md"), flat("owner", "FAMILIAS_F10.md"), flat("owner", "CICLO_FAMILIAS_F11.md")
    assert "con `?preview=shadow` (solo SUPER_ADMIN; cualquier otro recibe 403)" in f5
    assert f"un cuarto bloque, `families`, con lo que pronostican las familias (goles por mitad, córners, tarjetas y amarillas, versión `{page.FAMILY_VERSION}`)" in f5
    assert "para cualquier otra respuesta es `null`" in f5 and f"que sigue leyendo solo `{page.VERSION}`" in f5
    assert "ningún usuario ve estas filas; la vista previa del administrador las muestra aparte, en la sección «Familias» de la ficha del partido" in f10
    assert "la sección es `null` para cualquiera que no sea esa vista previa y se pide a la base solo entonces" in f10
    assert "El administrador sí los ve, aparte, en la vista previa" in f10 and "`FBI_FORECAST_USERS` solo decide si los usuarios ven ese" in f10
    assert f"una sección «Familias» con lo que las cuatro familias pronostican de ese partido (versión `{page.FAMILY_VERSION}`)" in cycle
    assert "con la cuota justa (1 / probabilidad) y la regla que liquidaría una apuesta en ese mercado" in cycle and "Ningún usuario la recibe." in cycle
    assert page.USERS_SWITCH == "FBI_FORECAST_USERS"


def test_the_guide_of_the_model_code_promotions_says_what_the_code_does() -> None:
    """Plan F12: the guide of the promotions of the model's code - the code in force, the least a reason can say, the window of the plan, the
    statuses a fingerprint can have and the commands that measure and write them."""
    from fbi.research import promotions, trace

    doc = read_doc("owner", "PROMOCIONES_F12.md")
    assert f"`{promotions.in_force().fingerprint}`" in doc and promotions.LEDGER[0].baseline, "the guide names the code in force: the baseline"
    assert f"al menos {promotions.MIN_REASON} caracteres" in doc
    assert f"{trace.DEFAULT_DAYS} días" in doc and trace.DEFAULT_DAYS == 30, "the window of the plan's criterion"
    for status in ("BASELINE", "PROMOTED", "AFTER_USE", "PENDING_SYNC", "UNTRACED", "PRE_LEDGER"):
        assert f"`{status}`" in doc, f"the guide leaves out the status {status}"
    assert set(trace.TRACED) == {"BASELINE", "PROMOTED", "AFTER_USE"}, "traced = the three statuses that have a decision on record"
    for command in ("python -m scripts.promotion_trace show", "sync --confirm", "`fbi/research/promotions.py`"):
        assert command in doc, f"the guide leaves out {command}"
    assert "entity = 'model'" in trace.ROWS_SQL and "entidad `model`" in doc and "backtest_session_id IS NULL" in trace.USE_SQL


def test_the_guide_of_the_model_code_panel_says_what_the_page_does() -> None:
    """Plan F12, the console: the address and its limits, the time the request is given and the answer kept, and the words each status has on the
    page - read from the web's Spanish catalog, so a guide and a screen that say different things fail here."""
    import typing

    from fbi.api.contracts.evolution import CodeStatus
    from fbi.api.deps import READ_ONLY_OPTIONS
    from fbi.api.routers import evolution as router
    from fbi.api.services import evolution as service
    from fbi.research import trace

    doc = read_doc("owner", "PROMOCIONES_F12.md")
    flat = " ".join(doc.split())  # the prose, whatever the line breaks of the paragraph
    assert f"`GET /api/v1/admin/evolution/code-promotions?days={trace.DEFAULT_DAYS}`" in doc
    routes = [r for r in router.router.routes if getattr(r, "path", None) == "/evolution/code-promotions"]
    assert len(routes) == 1 and getattr(routes[0], "methods", None) == {"GET"}, "one address, read only"
    query = typing.get_args(typing.get_type_hints(router.get_code_promotions, include_extras=True)["days"])[1]
    assert {k: getattr(m, k) for m in query.metadata for k in ("ge", "le") if hasattr(m, k)} == {"ge": 1, "le": 365}
    assert "`days` entre 1 y 365" in flat
    assert service.CODE_TIMEOUT == "60s" and "se da **60 segundos**" in flat, "the request is given more than the API's own limit"
    assert "statement_timeout=10000" in READ_ONLY_OPTIONS and "se corta a los diez segundos" in flat
    assert service.CODE_CACHE_SECONDS == 300 and "se guarda **cinco minutos**" in flat
    assert trace.IN_FORCE_DAYS == 2 and "«Usado en los últimos 2 días»" in flat and "dos últimos días" in flat
    assert set(typing.get_args(CodeStatus)) == {"BASELINE", "PROMOTED", "AFTER_USE", "PENDING_SYNC", "UNTRACED", "PRE_LEDGER"}
    assert set(trace.TRACED) < set(typing.get_args(CodeStatus)), "the statuses the plan counts are among the ones the page shows"

    catalog = Path(__file__).resolve().parents[3] / "web" / "src" / "locales" / "es" / "ai.json"
    if not catalog.is_file():
        pytest.skip("no web catalog next to the code")
    words = json.loads(catalog.read_text(encoding="utf-8"))["evolution"]["code"]
    assert set(words["status"]) == set(words["statusHelp"]) == set(typing.get_args(CodeStatus)), "the page has words for each status"
    for status in typing.get_args(CodeStatus):
        row = f"| `{status}` | {words['status'][status]} | {words['statusHelp'][status]} |"
        assert row in doc, f"the guide's table says something else than the page for {status}: {row}"
    for tile in (words["tiles"]["coverage"], words["tiles"]["running"], words["tiles"]["fingerprints"], words["tiles"]["ledgerSince"],
                 words["ledger"]["title"], words["other"]["title"], words["title"]):
        assert f"«{tile}»" in flat, f"the guide does not name {tile!r} as the page does"
    assert f"«{words['noPromotion'].rstrip('.')}»" in flat


def test_the_guide_of_the_release_guard_says_what_the_tool_does() -> None:
    """Plan F12.7: the verdicts, the modes and the exit statuses the guide gives are the tool's own, its limits are said, and the decision it
    leaves to the owner is put as it stands: the guard is in ``inform``."""
    from scripts import model_code_guard as guard

    doc = read_doc("owner", "PROMOCIONES_F12.md")
    guide = section_of(doc, "## La guarda de lanzamiento (F12.7)")
    flat = " ".join(guide.split())
    for path in ("scripts/model_code_guard.py", "tests/unit/test_model_code_guard.py"):
        assert (DOCS.parent / path).is_file(), path
        assert f"`{path}`" in " ".join(doc.split()), f"the guide does not name {path}"
    verdicts = {row[0].strip("`"): row for row in cells_of_rows(guide) if len(row) == 3 and row[0].startswith("`")}
    assert tuple(verdicts) == guard.STATUSES, "one row for each verdict, in the order of the tool"
    assert "La huella cambia y la última entrada del registro del árbol nuevo es ese código" in verdicts[guard.COVERED][1]
    assert "no hay tal entrada" in verdicts[guard.UNCOVERED][1] and "el árbol no tiene registro" in verdicts[guard.UNCOVERED][1]
    assert "Pasa siempre" in verdicts[guard.UNCHANGED][2] and "Por omisión avisa" in verdicts[guard.UNCOVERED][2]
    assert guard.DEFAULT_MODE == "inform" and "`inform` (por omisión" in flat, "the default of the tool is the one the guide gives"
    assert all(f"`{mode}`" in flat for mode in guard.MODES)
    assert f"con el código de salida `{guard.EXIT_STOP}`" in flat
    assert f"`{guard.EXIT_GO}` si la entrega sigue" in flat and f"`{guard.EXIT_STOP}` si se detiene (solo `stop` con `UNCOVERED`)" in flat
    assert f"`{guard.EXIT_CANNOT_CHECK}` si no pudo comprobar nada" in flat and "no son nunca luz verde, tampoco en `inform`" in flat
    assert f"la {'.'.join(map(str, guard.MIN_PYTHON))} o una más nueva" in flat
    assert "solo usa la biblioteca estándar de Python" in flat and "no toca la base de datos ni la red y no escribe nada" in flat
    for limit in ("no mira la base de datos", "python -m scripts.promotion_trace show", "no cubre lo que mueve los números", "`DEPENDENCIAS_F14.md`",
                  "no sustituye la prueba del registro"):
        assert limit in flat, f"the guide leaves out what the guard does not do: {limit}"
    assert (DOCS / "owner" / "DEPENDENCIAS_F14.md").is_file()
    assert "`mc9a7bec97ca` en doce" in flat and "`mce0abbbb30d` solo en la de F5" in flat and "sale con 4" in flat and "`UNCHANGED`" in flat
    decision = section_of(doc, "## Decisiones tuyas")
    assert "puesto en modo `inform`" in " ".join(decision.split()) and "`--mode stop`" in decision, "the decision is put as it stands"
    assert "no toca `predigolctl` ni tu `deploy/release.sh`" in flat


# ── Plan F12.4: the hypotheses the repository proposes from a measurement ─────

def section_of(doc: str, heading: str) -> str:
    """One section of a guide, from its heading to the next ``## `` heading (the whole guide for an empty heading)."""
    if not heading:
        return doc
    start = doc.find("\n" + heading + "\n")
    assert start >= 0, f"the guide no longer has the section {heading!r}"
    rest = doc[start + len(heading) + 2:]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def cells_of_rows(section: str) -> list[list[str]]:
    """The cells of every row of the tables of a section (the bold marks taken off)."""
    return [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in section.replace("**", "").splitlines() if line.lstrip().startswith("|")]


def test_the_hypotheses_the_repository_proposes_quote_the_guide_they_rest_on() -> None:
    """Plan F12.4: every figure of a proposal is in the section of the guide it names - in the row of the table that holds it where the proposal says
    which row - so a proposal and a guide that say different things fail here; and the guide says how the proposals are registered and decided, in
    the words of the page."""
    from scripts import hypotheses as cli

    from fbi.research import hypotheses

    doc = read_doc("owner", hypotheses.GUIDE)
    flat = " ".join(doc.split())
    minus = "\N{MINUS SIGN}"
    assert hypotheses.SECTION in doc and hypotheses.SECTION_REPEAT in doc
    for p in hypotheses.REGISTER:
        for c in p.cited:
            section = section_of(doc, c.where)
            text = c.text.replace(minus, "-")  # the document is read with the typographic minus written as a hyphen
            where = c.where or "the guide"
            if c.row is None:
                assert text in " ".join(section.replace("**", "").split()), f"{p.key}: {where} no longer says {c.text!r}"
                continue
            labels = [label.replace(minus, "-") for label in c.row]
            assert any(text in cells and all(label in cells for label in labels) for cells in cells_of_rows(section)), \
                f"{p.key}: no row of {where} has {labels} and {c.text!r}"
    # the proposals are what the guide's own §8 proposes
    assert "por lo observado entre pronosticado de las 4 semanas anteriores" in flat
    assert "por lo observado entre pronosticado de las 4 semanas anteriores" in hypotheses.RECENT_LEVEL.hypothesis
    assert "corrección de nivel reciente" in flat and "mezcla anclada al mercado" in flat and "anclada al mercado" in hypotheses.MARKET_BLEND.title
    # the command that registers them and the words of the page where the owner decides
    assert "`fbi/research/hypotheses.py`" in doc and "una prueba falla si la guía y la propuesta dicen cosas distintas" in flat
    parser = cli.build_parser()
    assert parser.parse_args(["register", "--confirm"]).confirm is True and parser.parse_args(["register"]).confirm is False
    assert parser.parse_args(["show", "--full"]).full is True
    for command in ("python -m scripts.hypotheses register --confirm", "python -m scripts.hypotheses show --full"):
        assert command in doc, f"the guide leaves out {command}"
    catalog = Path(__file__).resolve().parents[3] / "web" / "src" / "locales" / "es" / "ai.json"
    if not catalog.is_file():
        pytest.skip("no web catalog next to the code")
    words = json.loads(catalog.read_text(encoding="utf-8"))["evolution"]
    for said in (words["proposals"]["title"], words["status"]["PROPOSED"], words["decide"]["reject"], words["decide"]["investigate"],
                 words["decide"]["approve_experiment"]):
        assert f"«{said}»" in flat, f"the guide does not call {said!r} what the page does"
    assert "no se vuelve a escribir aunque la hayas decidido" in flat


# ── Plan F11.6: the dependence between the families of one match ──────────────

STORED_DEPENDENCE = DOCS / "owner" / "DEPENDENCIA_FAMILIAS_F11_resultado.json"
TIMES = "\N{MULTIPLICATION SIGN}"
MONTHS_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
NOUNS_ES = {"goals": "goles", "corners": "córners", "cards": "tarjetas"}
EVENTS_BY_KEY = {e.key: e for e in dependence.EVENTS}
KIND_ROWS = ("total con total", "total con «quién tiene más»", "«quién tiene más» con «quién tiene más»", "«ambos marcan» con un total",
             "«ambos marcan» con «quién tiene más»")
"""The rows of the guide's table by kind of pair, in the order it gives them."""
MAIN_PAIRS = (("goals.over_2_5", "corners.over_9_5"), ("goals.over_2_5", "cards.over_4_5"), ("corners.over_9_5", "cards.over_4_5"),
              ("goals.btts", "corners.over_9_5"), ("goals.btts", "cards.over_4_5"), ("goals.home_more", "corners.home_more"),
              ("goals.away_more", "corners.away_more"), ("goals.home_more", "cards.home_more"), ("goals.away_more", "cards.away_more"),
              ("corners.home_more", "cards.home_more"), ("corners.away_more", "cards.away_more"), ("corners.home_more", "cards.away_more"),
              ("corners.away_more", "cards.home_more"))
"""The pairs of the guide's table of the most usual ones, in its order."""


def spanish(x: float, digits: int, *, sign: bool = False) -> str:
    """A number as the guides write it: decimal comma, a plus sign where ``sign`` (a minus is the hyphen that ``read_doc`` leaves)."""
    return (f"{x:+.{digits}f}" if sign else f"{x:.{digits}f}").replace(".", ",")


def thousands(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def percent(x: float) -> str:
    """A fraction as a percentage with one decimal and the decimal comma (0.0563 -> '5,6')."""
    return spanish(x * 100, 1)


def day_es(iso: str) -> str:
    """'2023-10-27T19:00:00+00:00' as the guide writes a day: '27-oct-2023'."""
    when = datetime.fromisoformat(iso)
    return f"{when.day}-{MONTHS_ES[when.month - 1]}-{when.year}"


def stored_dependence() -> dict[str, Any]:
    """The first real reading of the dependence (the ``--json`` of the command), kept next to the guide."""
    if not STORED_DEPENDENCE.is_file():
        pytest.skip(f"no {STORED_DEPENDENCE.name} next to the code")
    result: dict[str, Any] = json.loads(STORED_DEPENDENCE.read_text(encoding="utf-8"))
    return result


def event_words(event: dependence.Event) -> str:
    """A leg as the guide names it."""
    noun = NOUNS_ES[event.family]
    if event.kind == dependence.OVER:
        return f"más de {spanish(event.line or 0.0, 1)} {noun}"
    if event.kind == dependence.BTTS:
        return "ambos marcan"
    side = "local" if event.kind == dependence.HOME_MORE else "visitante"
    return f"gana el {side}" if event.family == "goals" else f"el {side} tiene más {noun}"


def variable_words(variable: str) -> str:
    """A count as the guide's table of correlations names it ('goals_total' -> 'goles totales', 'goals_diff' -> 'diferencia de goles')."""
    family, kind = variable.split("_")
    return f"{NOUNS_ES[family]} totales" if kind == "total" else f"diferencia de {NOUNS_ES[family]}"


def kind_of(pair: dict[str, Any]) -> str:
    """The row of the guide's table by kind that a pair belongs to."""
    a, b = EVENTS_BY_KEY[pair["first"]], EVENTS_BY_KEY[pair["second"]]
    kinds = {a.kind, b.kind}
    if kinds == {dependence.OVER}:
        return KIND_ROWS[0]
    if dependence.BTTS in kinds:
        other = b if a.kind == dependence.BTTS else a
        return KIND_ROWS[3] if other.kind == dependence.OVER else KIND_ROWS[4]
    return KIND_ROWS[1] if dependence.OVER in kinds else KIND_ROWS[2]


def deviation(pair: dict[str, Any]) -> float:
    """How far the independent product is at the farthest of the four combinations of a pair: |lift - 1|."""
    return max(abs(cell["lift"] - 1.0) for cell in pair["cells"].values())


def table_rows(text: str, header: str) -> list[str]:
    """The rows of the table that begins with the line ``header`` (the header and its rule line left out)."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(header)), None)
    assert start is not None, f"the guide no longer has the table {header!r}"
    rows: list[str] = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append(line)
    return rows


def test_the_guide_of_the_dependence_between_the_families_says_what_the_code_does() -> None:
    """Plan F11.6: the guide of the dependence between the families of one match - the questions asked, the groups the matches are compared in, the
    resamples of the intervals, the tolerance, the rule of the parlays that it leaves as it is and the options of the command that repeats it."""
    from scripts import families as cli

    from fbi.families import history
    from fbi.parlays import correlation, persist

    doc = read_doc("owner", "DEPENDENCIA_FAMILIAS_F11.md")
    assert dependence.VERSION == "dependence-v1"
    assert len(dependence.EVENTS) == 17 and f"Se miden **{len(dependence.EVENTS)} preguntas**" in doc
    assert dependence.FAMILIES == ("goals", "corners", "cards")
    lines = "; ".join(f"{NOUNS_ES[f]} " + " / ".join(spanish(x, 1) for x in dependence.LINES[f]) for f in dependence.FAMILIES)
    assert f"**Totales por encima de una línea:** {lines}." in doc
    assert {e.kind for e in dependence.EVENTS} == {dependence.OVER, dependence.BTTS, dependence.HOME_MORE, dependence.AWAY_MORE}
    assert "**Ambos marcan.**" in doc and "que el local o el visitante tenga más córners, más tarjetas o más goles (ganar)" in doc
    assert len(dependence.PAIRS) == 96 and all(dependence.EVENTS[i].family != dependence.EVENTS[j].family for i, j in dependence.PAIRS)
    assert f"({len(dependence.PAIRS)} parejas)" in doc and f"**Son {len(dependence.PAIRS)} parejas a la vez.**" in doc
    assert len(dependence.CELLS) == 4 and "hay cuatro casos: ocurren **ambas**, **solo la primera**, **solo la segunda** o **ninguna**" in doc
    # the groups the matches are compared in, and the intervals
    assert f"grupos de al menos {dependence.MIN_STRATUM} partidos" in doc and "**una competición en un semestre**" in doc
    assert dependence.REPLICATES == 400 and dependence.SEED == 11 and dependence.LEVEL == 0.95
    assert (f"**Los intervalos** ({dependence.LEVEL * 100:g} %) salen de **{dependence.REPLICATES} remuestreos** con semilla {dependence.SEED} "
            "en los que se sortean **días de una competición**") in doc
    # the tolerance is the margin a parlay must show
    assert dependence.TOLERANCE == dependence.BAR == decision.PARLAY_MIN_EV == 0.02
    assert f"**tolerancia de {dependence.TOLERANCE * 100:g} %**" in doc and "`PARLAY_MIN_EV`" in doc
    assert f"**+{dependence.BAR * 100:g} %** (el mínimo que se le exige)" in doc and f"del tamaño del **{dependence.BAR * 100:g} %** de margen" in doc
    assert f"supere el {dependence.BAR * 100:g} % **con el factor aplicado**" in doc
    for word in dependence.PAIR_WORDS.values():
        assert f"`{word}`" in doc, f"the guide leaves out the verdict {word!r}"
    # the verdicts it describes are the ones the code gives at the edges of the tolerance
    assert dependence.cell_status(1.0, 0.99, 1.01) == dependence.NEGLIGIBLE and dependence.cell_status(0.9, 0.85, 0.95) == dependence.TOO_HIGH
    assert dependence.cell_status(1.1, 1.05, 1.15) == dependence.TOO_LOW and dependence.cell_status(1.0, 0.9, 1.1) == dependence.BORDERLINE
    assert dependence.pair_verdict([dependence.NEGLIGIBLE, dependence.BORDERLINE]) == dependence.BORDERLINE
    assert dependence.pair_verdict([dependence.NEGLIGIBLE, dependence.TOO_LOW]) == dependence.MATERIAL
    # the rule of the parlays that the guide leaves as it is
    assert persist.RULE_VERSION == "parlay-v5" and "(`parlay-v5`)" in doc
    assert persist.MAX_PER_COMPETITION == 2 and "como mucho dos por competición" in doc
    assert "an estimate is allowed to make a parlay look worse, never better" in Path(correlation.__file__).read_text(encoding="utf-8")
    assert "*una estimación puede empeorar una combinada, nunca mejorarla*" in doc
    # the command that repeats it
    parser = cli.build_parser()
    args = parser.parse_args(["dependence"])
    assert (args.days, args.replicates, args.seed, args.top, args.json) == (dependence.HISTORY_DAYS, dependence.REPLICATES, dependence.SEED, 12, False)
    assert dependence.HISTORY_DAYS == 3 * 365 and "# 3 años, lee la base de datos (solo lectura)" in doc
    args = parser.parse_args(["dependence", "--days", "365", "--top", "20"])
    assert (args.days, args.top) == (365, 20)
    args = parser.parse_args(["dependence", "--csv-goals", "g.csv.gz", "--csv-corners", "c.csv.gz", "--csv-cards", "k.csv.gz"])
    assert (args.csv_goals, args.csv_corners, args.csv_cards) == ("g.csv.gz", "c.csv.gz", "k.csv.gz")
    for command in ("python -m scripts.families dependence ", "python -m scripts.families dependence --days 365 --top 20",
                    "python -m scripts.families dependence --json",
                    "python -m scripts.families dependence --csv-goals g.csv.gz --csv-corners c.csv.gz --csv-cards k.csv.gz"):
        assert command in doc, f"the guide leaves out {command}"
    goals, corners, cards = (dependence.MEASURES[f] for f in dependence.FAMILIES)
    assert f"`export --measure {goals}`, `{corners}` y `{cards}`" in doc
    for measure in dependence.MEASURES.values():
        assert history.columns_of(measure), f"{measure} is not a pair of counts a family can read"
    # what it points to
    assert (DOCS / "owner" / "DEPENDENCIA_FAMILIAS_F11_resultado.json").is_file() and "`DEPENDENCIA_FAMILIAS_F11_resultado.json`" in doc
    for guide in ("FAMILIAS_VS_MERCADO_F11.md", "CRITERIO_FAMILIAS_F11.md"):
        assert (DOCS / "owner" / guide).is_file() and f"`{guide}`" in doc
    assert "`DEPENDENCIA_FAMILIAS_F11.md`" in read_doc("owner", "CRITERIO_FAMILIAS_F11.md"), "the guide of the criterion points to this one"
    from . import test_families_dependence as calibration_tests

    assert hasattr(calibration_tests, "test_the_intervals_are_calibrated_on_matches_with_no_dependence"), "the test the guide speaks of"
    assert "Una prueba del código lo comprueba con partidos simulados sin ninguna dependencia" in doc


def test_the_stored_reading_of_the_dependence_is_the_codes_own_arithmetic() -> None:
    """Plan F11.6: the reading that the guide quotes is held to the code - the criterion it was made with, the events and pairs it has, the four
    combinations of a pair adding up to the matches, the lift being what was seen over what was expected, and every status and verdict being what
    the code would say of the lifts and intervals stored (so a change in how a combination is judged makes the stored reading, and the guide
    built on it, go stale loudly)."""
    stored = stored_dependence()
    assert stored["version"] == dependence.VERSION
    assert stored["criterion"] == {"tolerance": dependence.TOLERANCE, "bar": dependence.BAR, "level": dependence.LEVEL,
                                   "replicates": dependence.REPLICATES, "seed": dependence.SEED, "min_stratum": dependence.MIN_STRATUM,
                                   "min_matches": dependence.MIN_MATCHES, "strata": "a competition in a half-year, UTC", "unit": "competition-day"}
    data = stored["data"]
    assert data["matches"] >= dependence.MIN_MATCHES and data["coverage"]["joined"] - data["dropped"] == data["matches"]
    assert data["coverage"]["joined"] <= min(data["coverage"][f] for f in dependence.FAMILIES), "the matches with the three counts are in each history"
    assert data["first"] < data["last"]
    # the events: those of the code, with the rate at which each happened
    assert list(stored["events"]) == [e.key for e in dependence.EVENTS]
    for event in dependence.EVENTS:
        found = stored["events"][event.key]
        assert found["family"] == event.family and found["text"] == event.text and 0.0 < found["rate"] < 1.0
    # the pairs: those of the code, in its order
    assert [(p["first"], p["second"]) for p in stored["pairs"]] == [(dependence.EVENTS[i].key, dependence.EVENTS[j].key) for i, j in dependence.PAIRS]
    assert [(c["a"], c["b"]) for c in stored["correlations"]] == list(dependence.CORRELATIONS)
    for c in stored["correlations"]:
        assert c["low"] <= c["high"] and -1.0 <= c["r"] <= 1.0 and -1.0 <= c["pooled"] <= 1.0
    tally: Counter[str] = Counter()
    for pair in stored["pairs"]:
        cells = pair["cells"]
        assert list(cells) == list(dependence.CELLS)
        observed = [cells[name]["observed"] for name in dependence.CELLS]
        expected = [cells[name]["expected"] for name in dependence.CELLS]
        # the four combinations are the matches, and the two events happen as often as their own rates say, seen or expected
        assert sum(observed) == pytest.approx(data["matches"]) and sum(expected) == pytest.approx(data["matches"])
        assert observed[0] + observed[1] == pytest.approx(expected[0] + expected[1]) and observed[0] + observed[2] == pytest.approx(expected[0] + expected[2])
        assert stored["events"][pair["first"]]["rate"] == pytest.approx((observed[0] + observed[1]) / data["matches"])
        assert stored["events"][pair["second"]]["rate"] == pytest.approx((observed[0] + observed[2]) / data["matches"])
        for name in dependence.CELLS:
            cell = cells[name]
            assert cell["lift"] == pytest.approx(cell["observed"] / cell["expected"], rel=1e-9)
            assert cell["worth_at_the_bar"] == pytest.approx(dependence.worth_at_the_bar(cell["lift"]), abs=1e-12)
            assert 0.0 < cell["low"] <= cell["high"]
            assert cell["status"] == dependence.cell_status(cell["lift"], cell["low"], cell["high"]), f"{pair['first']} ~ {pair['second']} ({name})"
        assert pair["phi_low"] <= pair["phi_high"] and -1.0 <= pair["phi"] <= 1.0
        assert pair["verdict"] == dependence.pair_verdict(cells[name]["status"] for name in dependence.CELLS), f"{pair['first']} ~ {pair['second']}"
        tally[pair["verdict"]] += 1
    summary = stored["summary"]
    assert summary == {"pairs": len(dependence.PAIRS), dependence.NEGLIGIBLE: tally[dependence.NEGLIGIBLE], dependence.BORDERLINE: tally[dependence.BORDERLINE],
                       dependence.MATERIAL: tally[dependence.MATERIAL]}
    # the text of the command prints what is stored, and says the same tally
    printed = dependence.render(stored, top=3)
    assert f"{summary['pairs']} pairs of events of two families" in printed and f"{summary[dependence.MATERIAL]} material" in printed


def test_the_guide_of_the_dependence_between_the_families_says_what_was_measured() -> None:
    """Plan F11.6: every figure of the guide - the window and the matches it was read on, the correlations of the counts, the tally of the pairs and
    their worst deviations, the example of the factor and the table of the usual pairs - is the one of the stored reading, written the way the
    guide writes it (decimal comma, thousands with a dot), and what it says in words about the direction of the dependence is true of those numbers."""
    doc = read_doc("owner", "DEPENDENCIA_FAMILIAS_F11.md")
    stored = stored_dependence()
    data, summary, cover = stored["data"], stored["summary"], stored["data"]["coverage"]
    corr = {(c["a"], c["b"]): c for c in stored["correlations"]}
    pairs = {(p["first"], p["second"]): p for p in stored["pairs"]}
    assert list(pairs) == [(dependence.EVENTS[i].key, dependence.EVENTS[j].key) for i, j in dependence.PAIRS]
    # the window and the matches
    assert f"Ventana de {dependence.HISTORY_DAYS // 365} años ({day_es(data['first'])} a {day_es(data['last'])})" in doc
    assert (f"Tenían goles {thousands(cover['goals'])} partidos, córners {thousands(cover['corners'])} y tarjetas {thousands(cover['cards'])}; "
            f"los tres a la vez, {thousands(cover['joined'])}, y {thousands(data['matches'])} tras dejar fuera {thousands(data['dropped'])} "
            f"en grupos de menos de {dependence.MIN_STRATUM} ({thousands(data['strata'])} grupos, {thousands(data['clusters'])} días de competición)") in doc
    assert f"({thousands(data['matches'])} con goles, córners y tarjetas conocidos)" in doc and "Medido con 3 años de partidos terminados" in doc
    assert f"Un {round((1 - cover['joined'] / cover['goals']) * 100)} % de los partidos con marcador no tiene las tres cosas" in doc
    # the correlations of the counts: in the summary and in the table
    totals = [corr[("goals_total", "corners_total")]["r"], corr[("goals_total", "cards_total")]["r"], corr[("corners_total", "cards_total")]["r"]]
    assert all(r < 0 for r in totals) and f"correlación de {spanish(max(totals), 3)} a {spanish(min(totals), 3)}" in doc
    assert f"(correlación {spanish(corr[('corners_diff', 'cards_diff')]['r'], 3)} entre la diferencia de córners y la de tarjetas)" in doc
    assert f"({spanish(corr[('goals_diff', 'cards_diff')]['r'], 3)} con los goles)" in doc
    expected_rows = [f"| {variable_words(c['a'])} con {variable_words(c['b'])} | {spanish(c['r'], 3, sign=True)} "
                     f"[{spanish(c['low'], 3, sign=True)}, {spanish(c['high'], 3, sign=True)}] | {spanish(c['pooled'], 3, sign=True)} |"
                     for c in stored["correlations"]]
    assert table_rows(doc, "| Conteos |") == expected_rows
    assert max(abs(c["r"] - c["pooled"]) for c in stored["correlations"]) < 0.05, "the guide says the groups hardly change the correlations"
    # how much the product of the totals is wrong, and for which kind of pair it is wrong most
    total_pairs = [p for p in stored["pairs"] if kind_of(p) == KIND_ROWS[0]]
    off = [abs(cell["lift"] - 1.0) for p in total_pairs for cell in p["cells"].values()]
    found = Counter(p["verdict"] for p in total_pairs)
    assert f"(**{percent(statistics.median(off))} % de mediana, {percent(max(off))} % como mucho**)" in doc
    assert found[dependence.NEGLIGIBLE] == 0, "the guide says that no pair of totals is shown negligible"
    assert (f"de las {len(total_pairs)} parejas de totales, ninguna queda demostrada despreciable "
            f"({found[dependence.BORDERLINE]} dudosas y {found[dependence.MATERIAL]} materiales)") in doc
    worst_more = max(deviation(p) for p in stored["pairs"] if kind_of(p) == KIND_ROWS[2])
    assert f"Ahí el producto se equivoca hasta un **{percent(worst_more)} %**" in doc
    both = pairs[("goals.btts", "cards.over_4_5")]["cells"]["both"]["lift"]
    assert both > 1.0 and (f"«Ambos marcan» con «{event_words(EVENTS_BY_KEY['cards.over_4_5'])}» ocurren juntos un {percent(both - 1.0)} % más "
                           "de lo que dice el producto") in doc
    # the example of the factor
    cells = pairs[("goals.over_2_5", "corners.over_9_5")]["cells"]
    assert (f"«{event_words(EVENTS_BY_KEY['goals.over_2_5'])}» y «{event_words(EVENTS_BY_KEY['corners.over_9_5'])}» ocurren juntos con un factor "
            f"de **{TIMES}{spanish(cells['both']['lift'], 3)}**") in doc
    assert f"El producto sobrestima esa combinación un {round((1.0 - cells['both']['lift']) * 100)} %" in doc
    assert f"valdría en realidad **{spanish(cells['both']['worth_at_the_bar'] * 100, 1)} %**" in doc
    assert (f"el factor es **{TIMES}{spanish(cells['first_only']['lift'], 3)}** y la misma combinada valdría "
            f"**{spanish(cells['first_only']['worth_at_the_bar'] * 100, 1, sign=True)} %**") in doc
    # the tally of the pairs, and by kind
    assert (f"**Las {summary['pairs']} parejas:** {summary[dependence.NEGLIGIBLE]} son `{dependence.PAIR_WORDS[dependence.NEGLIGIBLE]}`, "
            f"{summary[dependence.BORDERLINE]} `{dependence.PAIR_WORDS[dependence.BORDERLINE]}` y {summary[dependence.MATERIAL]} "
            f"`{dependence.PAIR_WORDS[dependence.MATERIAL]}`.") in doc
    by_kind = []
    for label in KIND_ROWS:
        members = [p for p in stored["pairs"] if kind_of(p) == label]
        verdicts = Counter(p["verdict"] for p in members)
        by_kind.append(f"| {label} | {len(members)} | {verdicts[dependence.NEGLIGIBLE]} | {verdicts[dependence.BORDERLINE]} | {verdicts[dependence.MATERIAL]} "
                       f"| {percent(max(deviation(p) for p in members))} % |")
    assert table_rows(doc, "| Tipo de pareja |") == by_kind
    assert sum(int(row.split("|")[2]) for row in by_kind) == summary["pairs"]
    # the usual pairs
    usual = []
    for key in MAIN_PAIRS:
        pair = pairs[key]
        first, second = (event_words(EVENTS_BY_KEY[k]) for k in key)
        lifts = " | ".join(f"{TIMES}{spanish(pair['cells'][name]['lift'], 3)}" for name in dependence.CELLS)
        usual.append(f"| {first} | {second} | {spanish(pair['phi'], 3, sign=True)} | {lifts} | `{pair['verdict']}` |")
    assert table_rows(doc, "| Primera selección |") == usual
    # what it says in words
    phi = {key: pairs[key]["phi"] for key in MAIN_PAIRS}
    assert abs(phi[("goals.home_more", "corners.home_more")]) < 0.01 and abs(phi[("goals.away_more", "corners.away_more")]) < 0.01, "winning and more corners"
    assert phi[("corners.home_more", "cards.home_more")] < 0 and phi[("corners.away_more", "cards.away_more")] < 0, "the side with more corners has fewer cards"
    assert phi[("corners.home_more", "cards.away_more")] > 0 and phi[("corners.away_more", "cards.home_more")] > 0
    assert phi[("goals.home_more", "cards.home_more")] < 0 and phi[("goals.away_more", "cards.away_more")] < 0, "the side that wins has fewer cards"
    assert phi[("goals.btts", "cards.over_4_5")] > 0, "matches with goals from both sides have more cards"


# ── Plan F12.5: a variant of a family against the market ──────────────────────

STORED_VARIANTS = DOCS / "owner" / "VARIANTES_VS_MERCADO_F12_resultado.json"
VARIANTS_GUIDE = "VARIANTES_VS_MERCADO_F12.md"
FAMILIES_READ = ("corners_ft", "cards_lines_ft", "yellow_ft")
"""The families of the first reading, in the order the guide gives them."""
SUBJECT_ROWS = {variants.TOTAL: "total del partido", variants.HOME: "equipo local", variants.AWAY: "equipo visitante",
                variants.RESULT: "quién tiene más (1X2)"}
"""What the guide's tables call what a comparison is about."""
SCOPE_OF = {variants.TOTAL: variants.MAIN, variants.HOME: variants.MAIN, variants.AWAY: variants.MAIN, variants.RESULT: variants.ALL}
"""The guide's tables read one line per match where the market gives one (its main line); who has more has no main line: every selection is a row."""
MOMENT_ROWS = {"close": "último precio", "h24": "24 h antes"}


def stored_variants() -> dict[str, Any]:
    """The first real readings of the variants (the ``--out`` of the command, one per family), kept next to the guide."""
    if not STORED_VARIANTS.is_file():
        pytest.skip(f"no {STORED_VARIANTS.name} next to the code")
    result: dict[str, Any] = json.loads(STORED_VARIANTS.read_text(encoding="utf-8"))
    return result


def variant_words(name: str) -> str:
    """A variant as the guide's tables name it: 'as-is' -> 'tal cual', 'recent-level:28' -> 'corrección de 28 días'."""
    return "tal cual" if name == variants.AS_IS else f"corrección de {variants.parse(name).level_days} días"


def with_error(x: float, se: float, digits: int) -> str:
    """A figure and its standard error as the guide writes them: '-0,0038 ± 0,0032'."""
    return f"{spanish(x, digits, sign=True)} ± {spanish(se, digits)}"


def points(x: float) -> str:
    """A fraction as signed percentage points with one decimal and the percent sign: 0.1603 -> '+16,0 %'."""
    return f"{spanish(x * 100, 1, sign=True)} %"


def points_with_error(x: float, se: float) -> str:
    """'-1,0 % ± 0,3 %': a value and its standard error, both in percentage points."""
    return f"{points(x)} ± {spanish(se * 100, 1)} %"


def blocks_of(report: dict[str, Any], subject: str, ref: str) -> list[dict[str, Any]] | None:
    """What each variant (the family as it is first) says of ``subject`` at a moment, or None when the books gave nothing for it. The variants are
    read on the same rows: the guide's tables give one number of matches for all."""
    blocks = [v["versus"].get(ref, {}).get(subject, {}).get(SCOPE_OF[subject]) for v in report["variants"].values()]
    if blocks[0] is None:
        return None
    for block in blocks:
        assert block is not None and (block["n"], block["fixtures"]) == (blocks[0]["n"], blocks[0]["fixtures"]), f"{subject} {ref}: not read on the same rows"
    return [b for b in blocks if b is not None]


def head_of(first: str, names: list[str]) -> str:
    return f"| {first} | Momento | Partidos | " + " | ".join(variant_words(n).capitalize() for n in names) + " |"


def gap_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """Market minus model of each variant, on the main line of each match: the header and the rows of the guide's table."""
    rows = []
    for subject, label in SUBJECT_ROWS.items():
        for ref in report["criterion"]["references"]:
            blocks = blocks_of(report, subject, ref)
            if blocks is not None:
                rows.append(f"| {label} | {MOMENT_ROWS[ref]} | {thousands(blocks[0]['fixtures'])} | "
                            + " | ".join(with_error(b["market_minus_model"], b["se"], 4) for b in blocks) + " |")
    return head_of("Mercado", list(report["variants"])), rows


def signal_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """The extra signal of each variant: how much weight the model deserves on top of the market."""
    rows = []
    for subject, label in SUBJECT_ROWS.items():
        for ref in report["criterion"]["references"]:
            blocks = blocks_of(report, subject, ref)
            if blocks is not None:
                cells = [with_error(b["signal"]["coef"], b["signal"]["se"], 2) if b["signal"] else "n/d" for b in blocks]
                rows.append(f"| {label} | {MOMENT_ROWS[ref]} | {thousands(blocks[0]['fixtures'])} | " + " | ".join(cells) + " |")
    return head_of("Señal extra de", list(report["variants"])), rows


def saves_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """What each variant saves against the family as it is, on the very same rows."""
    names = list(report["paired"])
    rows = []
    for subject, label in SUBJECT_ROWS.items():
        for ref in report["criterion"]["references"]:
            found = [report["paired"][n].get(ref, {}).get(subject, {}).get(SCOPE_OF[subject]) for n in names]
            if found and found[0] is not None and found[0]["n"]:
                rows.append(f"| {label} | {MOMENT_ROWS[ref]} | {thousands(found[0]['fixtures'])} | "
                            + " | ".join(with_error(p["gain"], p["se"], 4) for p in found if p is not None) + " |")
    return head_of("Ahorra en", names), rows


def levels_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """The multiplier of each block, home and away, for every variant that corrects the level."""
    corrected = {name: v["levels"] for name, v in report["variants"].items() if v["level_days"]}
    head = "| Bloque desde | " + " | ".join(f"Local ({variants.parse(n).level_days} días) | Visitante ({variants.parse(n).level_days} días)" for n in corrected) + " |"
    blocks = sorted({lv["at"] for levels in corrected.values() for lv in levels})
    rows = []
    for at in blocks:
        cells = []
        for levels in corrected.values():
            lv = next((x for x in levels if x["at"] == at), None)
            cells += [f"{TIMES}{spanish(lv['home'], 3)}", f"{TIMES}{spanish(lv['away'], 3)}"] if lv else ["", ""]
        rows.append(f"| {day_es(at)} | " + " | ".join(cells) + " |")
    return head, rows


BETS_HEAD = ("| Variante | Apuestas | Partidos | Faltan | Creía el modelo | Las casas ese día | Valor de cierre | Rendimiento | Veredicto |")


def bets_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """The plan's criterion for each variant: its simulated bets and the verdict (no row for one that took none)."""
    rows = []
    for name, m in report["bets"]["models"].items():
        if m["n"]:
            rows.append(f"| {variant_words(name)} | {thousands(m['n'])} | {thousands(m['fixtures'])} | {thousands(m['needed'])} | {points(m['believed'])} | "
                        f"{points(m['at_pick'])} | {points_with_error(m['clv'], m['clv_se'])} | {points_with_error(m['return'], m['return_se'])} | "
                        f"`{bets.WORDS[m['verdict']]}` |")
    return BETS_HEAD, rows


TABLES = {"gap": gap_table, "signal": signal_table, "saves": saves_table, "levels": levels_table, "bets": bets_table}


HEADINGS = {"corners_ft": "## 5. Primera lectura: córners", "cards_lines_ft": "## 6. Primera lectura: tarjetas", "yellow_ft": "## 7. Primera lectura: amarillas"}
"""The sections of the guide where each family's reading is, in the order of ``FAMILIES_READ``."""
AS_IS, LEVEL_28, LEVEL_56 = variants.AS_IS, "recent-level:28", "recent-level:56"


def group(report: dict[str, Any], variant: str, ref: str, subject: str) -> dict[str, Any]:
    """What a variant says of ``subject`` at a moment: the main line, or every selection of who has more."""
    found: dict[str, Any] = report["variants"][variant]["versus"][ref][subject][SCOPE_OF[subject]]
    return found


def saving(report: dict[str, Any], variant: str, ref: str, subject: str) -> dict[str, Any]:
    """What a variant saves against the family as it is on the very same rows."""
    found: dict[str, Any] = report["paired"][variant][ref][subject][SCOPE_OF[subject]]
    return found


def gap_words(report: dict[str, Any], variant: str, ref: str, subject: str) -> str:
    b = group(report, variant, ref, subject)
    return with_error(b["market_minus_model"], b["se"], 4)


def saving_words(report: dict[str, Any], variant: str, ref: str, subject: str) -> str:
    q = saving(report, variant, ref, subject)
    return with_error(q["gain"], q["se"], 4)


def sigmas(report: dict[str, Any], variant: str, ref: str, subject: str) -> float:
    """How many standard errors from zero the gap to the market is."""
    b = group(report, variant, ref, subject)
    return abs(b["market_minus_model"]) / b["se"]


def multipliers(report: dict[str, Any], variant: str, side: str) -> list[float]:
    """What the correction of a variant multiplied the means of ``side`` by, block by block."""
    return [lv[side] for lv in report["variants"][variant]["levels"]]


def bet_of(report: dict[str, Any], variant: str) -> dict[str, Any]:
    found: dict[str, Any] = report["bets"]["models"][variant]
    return found


def test_the_guide_of_the_variants_says_what_the_code_does() -> None:
    """Plan F12.5: the guide of the variants of a family against the market - the block, the memory of the correction and the least it needs, the
    dispersion, the main line and its band, the books and the criterion it reuses, the test it points to and the options of the command that
    repeats it (every command it shows is one the parser accepts)."""
    import shlex

    from scripts import families as cli

    from fbi.families import forecast, versus
    from fbi.families.fit import OUTCOME_KNOWN_AFTER

    from . import test_families_variants as variant_tests

    doc = read_doc("owner", VARIANTS_GUIDE)
    flat = " ".join(doc.split())
    assert variants.VERSION == "variants-v1" and variants.STEP_DAYS == 7 and "Cada 7 días (un «bloque»)" in flat
    assert hours(OUTCOME_KNOWN_AFTER) == 6 and f"(6 horas después de su inicio) y solo si hay al menos {variants.MIN_PAST} partidos" in flat and variants.MIN_PAST == 200
    assert (variants.MIN_LEVEL_DAYS, variants.MAX_LEVEL_DAYS, variants.LEVEL_DAYS) == (7, 365, 28)
    assert (f"N va de {variants.MIN_LEVEL_DAYS} a {variants.MAX_LEVEL_DAYS} días y, si no se pide otra, se lee `{variants.RECENT_LEVEL}:{variants.LEVEL_DAYS}`") in flat
    assert variants.DISPERSION_DAYS == forecast.DISPERSION_DAYS == 120 and f"se mide en los {variants.DISPERSION_DAYS} días anteriores a cada bloque" in flat
    assert forecast.MIN_DISPERSION_MATCHES == 300 and f"si no hay {forecast.MIN_DISPERSION_MATCHES} partidos con los que medirla, no se declara nada" in flat
    low, high = variants.MAIN_BAND
    assert f"entre el {low * 100:g} % y el {high * 100:g} % (en un empate, la línea más baja)" in flat
    assert versus.MIN_BOOKS == 3 and f"con {versus.MIN_BOOKS} casas o más, al último precio antes del inicio y {hours(versus.REFERENCES[1][1]):g} horas antes" in flat
    assert [name for name, _ in versus.REFERENCES] == ["close", "h24"]
    assert bets.MIN_BETS == 300 and bets.MIN_EV == 0.03 and bets.PICK_REF == "h24"
    assert f"declarados {hours(bets.PICK_LEAD):g} horas o más antes del inicio y cuando el modelo ve un valor de al menos {bets.MIN_EV * 100:g} %" in flat
    assert f"Con menos de {variants.MIN_SIGNAL} filas no se calcula" in flat and variants.MIN_SIGNAL == 30
    for printed in bets.WORDS.values():
        assert f"`{printed}`" in doc, f"the guide leaves out the verdict {printed!r}"
    assert "(`variants-v1`)" in doc, "the guide names the version of the reading the stored files were made with"
    # the families that can be read, and what the reading never does
    assert tuple(sorted(variants.specs())) == tuple(sorted(FAMILIES_READ))
    for family in FAMILIES_READ:
        assert f"`{family}`" in doc
    assert "Los goles por mitad se ajustan con dos y no se leen aquí" in flat and "goals_halves" not in variants.specs()
    assert "Solo lee (conexión de solo lectura, 0 peticiones al proveedor, 0 IA)" in flat
    # the test it points to exists
    assert hasattr(variant_tests, "test_no_number_of_a_week_changes_when_what_happens_from_that_week_on_does")
    assert "(`test_no_number_of_a_week_changes_when_what_happens_from_that_week_on_does`)" in doc
    assert hasattr(variant_tests, "test_the_two_runs_of_the_same_data_are_the_same_reading") and "Otra prueba comprueba que dos lecturas de los mismos datos dan lo mismo" in flat
    # the options: what the command does when they are not given
    parser = cli.build_parser()
    args = parser.parse_args(["variant", "--family", "corners_ft"])
    assert (args.days, args.wait_hours, args.step_days, args.dispersion_days, args.min_books, args.min_ev) == (
        28, 30.0, variants.STEP_DAYS, variants.DISPERSION_DAYS, versus.MIN_BOOKS, bets.MIN_EV)
    assert args.variant is None and args.since is None and args.until is None and args.out is None and args.json is False
    for said in ("`--days` (por omisión 28)", "(por omisión 30:", "`--step-days` (por omisión 7)", "`--dispersion-days` (por omisión 120)",
                 "`--min-books` (por omisión 3)", "`--min-ev` (por omisión 0,03)"):
        assert said in flat, f"the guide leaves out {said!r}"
    with pytest.raises(SystemExit):
        parser.parse_args(["variant"])  # --family is required
    with pytest.raises(SystemExit):
        parser.parse_args(["variant", "--family", "goals_halves"])
    for option in ("--family", "--variant", "--days", "--since", "--until", "--wait-hours", "--step-days", "--dispersion-days", "--min-books",
                   "--min-ev", "--out", "--json"):
        assert f"`{option}`" in doc, f"the guide leaves out {option}"
    # every command the guide shows is one the parser accepts, with the meaning the guide gives it
    block = doc.split("```")[1]
    commands = [line.split("#")[0].strip() for line in block.splitlines() if line.startswith("python -m scripts.families variant")]
    assert len(commands) == 4
    parsed = [parser.parse_args(shlex.split(command)[3:]) for command in commands]
    assert parsed[0].family == "corners_ft" and parsed[0].variant is None
    assert parsed[1].variant == [f"{variants.RECENT_LEVEL}:28", f"{variants.RECENT_LEVEL}:56"]
    assert parsed[2].family == "cards_lines_ft" and parsed[2].since == datetime(2026, 9, 25, tzinfo=UTC) and parsed[2].until == datetime(2026, 10, 23, 12, tzinfo=UTC)
    assert parsed[2].out == "lectura.json" and parsed[3].json is True
    # what it points to, and what points to it
    for guide in ("FAMILIAS_VS_MERCADO_F11.md", "CRITERIO_FAMILIAS_F11.md", "PROMOCIONES_F12.md", "VARIANTES_VS_MERCADO_F12_resultado.json"):
        assert (DOCS / "owner" / guide).is_file() and f"`{guide}`" in doc, guide
    assert f"`{VARIANTS_GUIDE}`" in read_doc("owner", "FAMILIAS_VS_MERCADO_F11.md"), "the guide of the comparison points to this one"
    assert "python -m scripts.hypotheses register --confirm" in doc and "`fbi/research/hypotheses.py`" in doc


def test_the_stored_readings_of_the_variants_are_the_codes_own_arithmetic() -> None:
    """Plan F12.5: the readings that the guide quotes are held to the code - the criterion they were made with, the window the code would plan, the
    variants asked for, the gap to the market being the difference of the two log losses, the market and what happened being the same for every
    variant, a variant's saving being the difference of the two models' log losses on the same rows, and every verdict being what the code says of
    the bets stored (so a change in the criterion, the window or the arithmetic makes the stored readings, and the guide built on them, go stale
    loudly)."""
    import math

    from fbi.families import forecast, versus

    stored = stored_variants()
    assert list(stored) == list(FAMILIES_READ)
    for family, report in stored.items():
        spec = variants.spec_of(family)
        assert report["version"] == variants.VERSION and report["family"] == family and report["measure"] == spec.measures[0], family
        assert report["params"] == {"xi": spec.xi, "penalty": spec.penalty, "referee_kappa": spec.referee_kappa}
        c = report["criterion"]
        assert c == {"min_books": versus.MIN_BOOKS, "min_ev": bets.MIN_EV, "min_bets": bets.MIN_BETS, "dispersion_days": variants.DISPERSION_DAYS,
                     "min_dispersion": forecast.MIN_DISPERSION_MATCHES, "min_past": variants.MIN_PAST, "main_band": list(variants.MAIN_BAND),
                     "pick_lead_hours": hours(bets.PICK_LEAD), "references": [name for name, _ in versus.REFERENCES]}, family
        # the variants asked for, and the window the code plans for them
        names = list(report["variants"])
        assert names == [AS_IS, LEVEL_28, LEVEL_56] and report["reference"] == AS_IS and list(report["paired"]) == names[1:]
        start, end = (datetime.fromisoformat(report["window"][k]) for k in ("start", "end"))
        planned = variants.plan(start, end, step_days=variants.STEP_DAYS, burn_in_days=variants.DISPERSION_DAYS + 56)
        assert report["window"] == {"start": start.isoformat(), "end": end.isoformat(), "first_block": planned.first.isoformat(),
                                    "step_days": variants.STEP_DAYS}, family
        assert report["window"] == stored[FAMILIES_READ[0]]["window"], "the three families are read on the same window"
        reference = report["variants"][AS_IS]
        for name, v in report["variants"].items():
            days = variants.parse(name).level_days
            assert v["level_days"] == days and v["matches"] == reference["matches"] > 0 and v["without_dispersion"] == 0
            assert v["corrected_matches"] == (v["matches"] if days else 0) and bool(v["levels"]) == bool(days)
            for lv in v["levels"]:
                at = datetime.fromisoformat(lv["at"])
                assert start <= at < end and (at - planned.first) % timedelta(days=variants.STEP_DAYS) == timedelta(0), "a level is stated at the start of a block"
                assert lv["home"] > 0 and lv["away"] > 0 and lv["matches"] >= variants.MIN_PAST
            for spread in v["dispersion"]:
                assert spread["matches"] >= c["min_dispersion"] and min(spread["home"], spread["away"], spread["total"]) >= 0
            if days:
                assert [lv["at"] for lv in v["levels"]] == [lv["at"] for lv in report["variants"][LEVEL_28]["levels"]], "every correction is stated in the same blocks"
            for ref, by_subject in v["versus"].items():
                assert ref in c["references"]
                for subject, by_scope in by_subject.items():
                    assert subject in variants.SUBJECTS
                    for scope, b in by_scope.items():
                        assert scope in variants.SCOPES
                        assert b["market_minus_model"] == pytest.approx(b["log_loss_market"] - b["log_loss_model"], abs=1e-12), f"{family} {name} {ref} {subject}"
                        assert 1 <= b["fixtures"] <= b["n"] and b["se"] > 0 and b["mean_books"] >= c["min_books"]
                        assert 0 < b["mean_p_model"] < 1 and 0 < b["mean_p_market"] < 1 and 0 <= b["observed"] <= 1
                        assert scope != variants.MAIN or b["n"] == b["fixtures"], "one row per match on the main line"
                        sig = b["signal"]
                        assert sig is None or (math.isfinite(sig["coef"]) and sig["se"] > 0 and math.isfinite(sig["market_slope"]))
                        # the market and what happened do not depend on the variant: only the model's probability does
                        base = reference["versus"][ref][subject][scope]
                        for same in ("n", "fixtures", "mean_p_market", "observed", "log_loss_market", "mean_books"):
                            assert b[same] == pytest.approx(base[same], abs=1e-12), f"{family} {name} {ref} {subject} {scope}: {same}"
        # a variant against the family as it is, on the very same rows
        for name, tree in report["paired"].items():
            for ref, by_subject in tree.items():
                for subject, by_scope in by_subject.items():
                    for scope, p in by_scope.items():
                        base = reference["versus"][ref][subject][scope]
                        mine = report["variants"][name]["versus"][ref][subject][scope]
                        assert p["n"] == base["n"] == mine["n"] and p["fixtures"] == base["fixtures"] and p["se"] > 0
                        assert p["gain"] == pytest.approx(base["log_loss_model"] - mine["log_loss_model"], abs=1e-12), f"{family} {name} {ref} {subject} {scope}"
        # the simulated bets and the verdicts
        simulated = report["bets"]
        assert simulated["criterion"] == {"min_bets": bets.MIN_BETS, "min_ev": bets.MIN_EV, "min_books": versus.MIN_BOOKS, "pick": bets.PICK_REF,
                                          "close": bets.CLOSE_REF}
        assert list(simulated["models"]) == names
        for m in simulated["models"].values():
            assert m["verdict"] == bets.verdict(m["n"], m["clv"]) and m["needed"] == max(0, bets.MIN_BETS - m["n"])
            assert m["taken"] == m["n"] + m["no_closing_line"]
            if m["n"]:
                assert sum(x["n"] for x in m["by_key"]) == m["n"] and m["fixtures"] <= m["n"] and m["believed"] >= bets.MIN_EV
                assert m["mean_odds"] > 1 and 0 < m["hit_rate"] < 1 and m["clv_se"] > 0 and m["return_se"] > 0
        assert report["left_out"] == {"pushed": 0, "ungradable": 0}
        # the referee is part of the means of the families that state with it, and only of those
        history = report["history"]
        assert (history["window_with_referee"] > 0) == bool(spec.referee_kappa) and history["window_with_referee"] <= reference["matches"]
        assert history["competitions"] > 0 and history["walk_forward_rows"] >= reference["matches"]
        # the text of the command prints what is stored
        printed = variants.render(report)
        assert printed.startswith(f"{family} ({variants.VERSION}): the family and its variants set against the books")
        for name in names:
            assert f"  {name}: {reference['matches']} matches" in printed


def test_the_guide_of_the_variants_says_what_was_measured() -> None:
    """Plan F12.5: every figure of the guide - the window and the matches, the tables of each family and what is said of them in words - is the one
    of the stored readings, written the way the guide writes it (decimal comma, thousands with a dot), and what it says about the direction of the
    results (the total of corners level with the market, the sides not, the criterion not met, the cards corrected the other way, the yellows with
    nothing to compare) is true of those numbers."""
    doc = read_doc("owner", VARIANTS_GUIDE)
    flat = " ".join(doc.split())
    f11 = " ".join(read_doc("owner", "FAMILIAS_VS_MERCADO_F11.md").split())
    stored = stored_variants()
    corners, cards, yellow = (stored[family] for family in FAMILIES_READ)
    # the window: the same for the three, and the one the prices begin at
    w = corners["window"]
    window = f"del {day_es(w['start'])} al {day_es(w['end'])} a las {w['end'][11:16]} UTC"
    assert flat.count(window) == 2 and datetime.fromisoformat(w["start"]) == datetime(2026, 9, 25, tzinfo=UTC)
    assert "guarda desde el 25 de septiembre" in flat and datetime.fromisoformat(w["end"]) - datetime.fromisoformat(w["start"]) > timedelta(days=28)
    assert f"**Cuatro semanas de precios** ({window})" in flat and "4 semanas" in flat
    # the tables of each family are the stored numbers, and the guide has no other table
    for family, report in stored.items():
        section = section_of(doc, HEADINGS[family])
        shown = 0
        for name, build in TABLES.items():
            head, rows = build(report)
            if rows:
                assert table_rows(section, head) == rows, f"{family}: the table {name!r} of the guide is not the stored reading"
                shown += 1
            else:
                assert head not in section, f"{family}: the guide has a table {name!r} the reading does not"
        assert sum(1 for line in section.splitlines() if line.startswith("|---")) == shown, f"{family}: a table of the guide that nothing checks"
    # the headline of each reading, that the numbers checked below it bear out
    for lead in ("**El total queda a la par del mercado.**", "**La corrección sí mejora a la familia tal cual, pero solo la lleva hasta el mercado.**",
                 "**Por equipo no se cierra.**", "**Dar 28 o 56 días da lo mismo.**", "**Las apuestas pasan de 300 pero no el valor de cierre.**",
                 "**Una cosa que mirar, no un hallazgo:**", "**La corrección va en sentido contrario al de córners:**", "**Acerca el total al mercado:**",
                 "**Faltan apuestas:**", "**No hay con qué compararlas.**", "**Ninguna variante cumple el criterio del plan.**",
                 "**Ninguna variante tiene valor demostrado.**", "**La corrección de nivel es un arreglo, no una ventaja.**"):
        assert lead in doc, f"the guide no longer says {lead}"
    # § 1 and § 5: corners
    gap = {v: gap_words(corners, v, "close", "total") for v in (AS_IS, LEVEL_28, LEVEL_56)}
    gap24 = {v: gap_words(corners, v, "h24", "total") for v in (AS_IS, LEVEL_28, LEVEL_56)}
    assert f"(mercado - modelo pasa de {gap[AS_IS]} a {gap[LEVEL_28]} al cierre) y mejora a la familia tal cual (ahorra {saving_words(corners, LEVEL_28, 'close', 'total')} por fila)" in flat
    assert f"el local sigue {spanish(sigmas(corners, LEVEL_28, 'close', 'home'), 1)} errores estándar por debajo del mercado" in flat
    first = group(corners, AS_IS, "close", "total")
    assert (f"{thousands(corners['variants'][AS_IS]['matches'])} partidos con pronóstico, {thousands(first['fixtures'])} de ellos con una línea principal "
            f"del total al cierre y {thousands(group(corners, AS_IS, 'h24', 'total')['fixtures'])} a 24 horas") in flat
    assert (f"Tal cual, mercado - modelo es {gap[AS_IS]} al cierre ({spanish(sigmas(corners, AS_IS, 'close', 'total'), 1)} errores estándar: el mercado "
            "va por delante, sin que se distinga de cero);") in flat
    assert 0 < sigmas(corners, AS_IS, "close", "total") < 2 and group(corners, AS_IS, "close", "total")["market_minus_model"] < 0
    assert (f"con la corrección de 28 días queda en {gap[LEVEL_28]} y con la de 56 en {gap[LEVEL_56]}, y a 24 horas en {gap24[LEVEL_28]} y {gap24[LEVEL_56]}") in flat
    for variant in (LEVEL_28, LEVEL_56):
        for ref in ("close", "h24"):
            b = group(corners, variant, ref, "total")
            assert abs(b["market_minus_model"]) < b["se"], f"the total of corners is level with the market ({variant}, {ref})"
    # ... and it is what the hand-made measurement of F11 gave, within the rounding of two windows that do not coincide
    hand_before, hand_after = "-0,0040 ± 0,0032", "-0,0006 ± 0,0030"
    assert f"(de {hand_before} a {hand_after} con 1.268 partidos)" in flat and hand_before in f11 and hand_after in f11 and "1.268" in f11
    assert abs(first["market_minus_model"] + 0.0040) < 0.0005 and abs(group(corners, LEVEL_28, "close", "total")["market_minus_model"] + 0.0006) < 0.0005
    assert f"(aquí {thousands(first['fixtures'])})" in flat and first["fixtures"] != 1268
    gains = {(v, s): saving(corners, v, "close", s) for v in (LEVEL_28, LEVEL_56) for s in ("total", "away", "home")}
    assert (f"En el total ahorra {saving_words(corners, LEVEL_28, 'close', 'total')} por fila al cierre con 28 días ({saving_words(corners, LEVEL_56, 'close', 'total')} con 56) "
            f"y en el visitante {saving_words(corners, LEVEL_28, 'close', 'away')} ({saving_words(corners, LEVEL_56, 'close', 'away')}); "
            f"en el local no ahorra nada ({saving_words(corners, LEVEL_28, 'close', 'home')})") in flat
    assert all(gains[(v, s)]["gain"] > 0 for v in (LEVEL_28, LEVEL_56) for s in ("total", "away")), "the correction saves on the total and on the visitor"
    assert abs(gains[(LEVEL_28, "home")]["gain"]) < gains[(LEVEL_28, "home")]["se"], "and nothing on the home side"
    assert (f"El local sigue en {gap_words(corners, LEVEL_28, 'close', 'home')} al cierre con 28 días "
            f"({spanish(sigmas(corners, LEVEL_28, 'close', 'home'), 1)} errores estándar por debajo del mercado) y «quién tiene más córners» en "
            f"{gap_words(corners, LEVEL_28, 'close', 'result')} ({spanish(sigmas(corners, LEVEL_28, 'close', 'result'), 1)})") in flat
    assert sigmas(corners, LEVEL_28, "close", "home") > 3 and sigmas(corners, LEVEL_28, "close", "result") > 2, "by side the market is still ahead"
    assert all(group(corners, v, "close", s)["market_minus_model"] < 0 for v in (AS_IS, LEVEL_28, LEVEL_56) for s in ("home", "away", "result"))
    home, away = multipliers(corners, LEVEL_28, "home"), multipliers(corners, LEVEL_28, "away")
    assert (f"multiplicó las medias del local por entre {spanish(min(home), 3)} y {spanish(max(home), 3)} y las del visitante por entre "
            f"{spanish(min(away), 3)} y {spanish(max(away), 3)}, hasta {spanish(max(away), 3)} en el último bloque") in flat
    assert min(home + away) > 1.0 and away[-1] == max(away) and away[-3] < away[-2] < away[-1], "the visitor, more and more short from the block of the 9th"
    assert [lv["at"][:10] for lv in corners["variants"][LEVEL_28]["levels"]][-3] == "2026-10-09"
    assert "4,5 % corto entre el 18 de septiembre y el 16 de octubre" in flat and "4,5 % corto" in f11 and "1,045" in f11
    assert (f"(total al cierre {gap[LEVEL_28]} frente a {gap[LEVEL_56]})") in flat
    assert abs(group(corners, LEVEL_28, "close", "total")["market_minus_model"] - group(corners, LEVEL_56, "close", "total")["market_minus_model"]) < group(corners, LEVEL_28, "close", "total")["se"]
    made = {v: bet_of(corners, v) for v in (AS_IS, LEVEL_28, LEVEL_56)}
    assert (f"Son {thousands(made[AS_IS]['n'])}, {thousands(made[LEVEL_28]['n'])} y {thousands(made[LEVEL_56]['n'])} apuestas y el valor de cierre es "
            f"{points_with_error(made[AS_IS]['clv'], made[AS_IS]['clv_se'])} tal cual, {points_with_error(made[LEVEL_28]['clv'], made[LEVEL_28]['clv_se'])} con 28 días "
            f"y {points_with_error(made[LEVEL_56]['clv'], made[LEVEL_56]['clv_se'])} con 56") in flat
    assert all(m["n"] >= bets.MIN_BETS and m["verdict"] == bets.CLV_NEGATIVE and m["clv"] < 0 for m in made.values())
    assert all(abs(made[v]["clv"] / made[AS_IS]["clv"] - 0.5) < 0.1 for v in (LEVEL_28, LEVEL_56)), "the correction halves what the value at the close lacked"
    returns = [made[v] for v in (AS_IS, LEVEL_28, LEVEL_56)]
    assert (f"Los rendimientos ({points(returns[0]['return'])}, {points(returns[1]['return'])} y {points(returns[2]['return'])}, con errores de "
            f"±{spanish(min(m['return_se'] for m in returns) * 100, 1)} a ±{spanish(max(m['return_se'] for m in returns) * 100, 1)} puntos) no se distinguen de cero") in flat
    assert all(abs(m["return"]) < 2 * m["return_se"] for m in returns)
    kinds = [next(x for x in m["by_key"] if x["key"] == "CORNERS_1X2") for m in returns]
    assert (f"({points(kinds[0]['clv'])}, {points(kinds[1]['clv'])} y {points(kinds[2]['clv'])}, con errores de ±{spanish(min(k['clv_se'] for k in kinds) * 100, 1)} "
            f"a ±{spanish(max(k['clv_se'] for k in kinds) * 100, 1)} puntos, con {min(k['n'] for k in kinds)} a {max(k['n'] for k in kinds)} apuestas)") in flat
    assert all(k["clv"] > 0 for k in kinds) and all(x["clv"] < 0 for m in returns for x in m["by_key"] if x["key"] != "CORNERS_1X2"), "the only kind with a positive value at the close"
    assert abs(kinds[1]["clv"] - kinds[0]["clv"]) < 2 * kinds[0]["clv_se"], "the same with the correction as without it"
    assert "(`CRITERIO_FAMILIAS_F11.md`, límites)" in flat and "El mejor precio de todas las casas" in " ".join(read_doc("owner", "CRITERIO_FAMILIAS_F11.md").split())
    # § 6: cards
    k28, k56 = (gap_words(cards, v, "close", "total") for v in (LEVEL_28, LEVEL_56))
    kfirst = group(cards, AS_IS, "close", "total")
    assert (f"aplicado a {thousands(cards['history']['window_with_referee'])} de los {thousands(cards['variants'][AS_IS]['matches'])} partidos de la ventana") in flat
    assert f"un prior de {cards['params']['referee_kappa']:g} tarjetas" in flat and "un prior de 150 tarjetas" in " ".join(read_doc("owner", "FAMILIAS_VS_MERCADO_F11.md").split())
    assert (f"{thousands(kfirst['fixtures'])} partidos al cierre y {thousands(group(cards, AS_IS, 'h24', 'total')['fixtures'])} a 24 horas") in flat
    assert {subject for by_subject in cards["variants"][AS_IS]["versus"].values() for subject in by_subject} == {variants.TOTAL}, "only the total has a consensus"
    assert f"pero con {thousands(kfirst['fixtures'])} partidos el error es más del doble que el de córners" in flat
    assert kfirst["se"] > 2 * first["se"] and group(cards, AS_IS, "h24", "total")["se"] > kfirst["se"]
    cards_28 = multipliers(cards, LEVEL_28, "home") + multipliers(cards, LEVEL_28, "away")
    assert max(cards_28) < 1.0 and f"entre un {round((1 - max(cards_28)) * 100)} % y un {round((1 - min(cards_28)) * 100)} %" in flat
    assert doc.count(f"entre un {round((1 - max(cards_28)) * 100)} % y un {round((1 - min(cards_28)) * 100)} %") == 2
    assert (f"de {gap_words(cards, AS_IS, 'close', 'total')} a {k28} al cierre con 28 días ({k56} con 56), y ahorra {saving_words(cards, LEVEL_28, 'close', 'total')} por fila "
            f"(28 días) y {saving_words(cards, LEVEL_56, 'close', 'total')} (56)") in flat
    assert group(cards, LEVEL_28, "close", "total")["market_minus_model"] > kfirst["market_minus_model"] and saving(cards, LEVEL_28, "close", "total")["gain"] > 0
    assert all(abs(group(cards, v, "h24", "total")["market_minus_model"]) < 2 * group(cards, v, "h24", "total")["se"] for v in (AS_IS, LEVEL_28, LEVEL_56))
    short = {v: bet_of(cards, v) for v in (AS_IS, LEVEL_28, LEVEL_56)}
    assert (f"son {thousands(short[AS_IS]['n'])}, {thousands(short[LEVEL_28]['n'])} y {thousands(short[LEVEL_56]['n'])}; con la corrección de 28 días faltan "
            f"{thousands(short[LEVEL_28]['needed'])} para las 300 (`{bets.WORDS[bets.TOO_FEW]}`). El valor de cierre "
            f"({points_with_error(short[LEVEL_28]['clv'], short[LEVEL_28]['clv_se'])}) no es prueba de nada todavía") in flat
    assert all(m["verdict"] == bets.TOO_FEW and m["n"] < bets.MIN_BETS for m in short.values()) and bets.MIN_BETS == 300
    # § 7: yellows
    nothing = [bet_of(yellow, v) for v in (AS_IS, LEVEL_28, LEVEL_56)]
    assert all(m["n"] == 0 and m["verdict"] == bets.TOO_FEW for m in nothing) and all(not v["versus"] for v in yellow["variants"].values()) and not any(yellow["paired"].values())
    printed = variants.render(yellow)
    assert f"{yellow['bets']['models'][AS_IS]['n']} bets" not in printed and "market minus model" not in printed
    assert f"{AS_IS}: no bet -> {bets.WORDS[bets.TOO_FEW]}" in printed and f"(`no bet -> {bets.WORDS[bets.TOO_FEW]}`)" in doc
    assert "el reloj de precios guarda una sola casa para ellas, y con menos de 3 no hay consenso" in f11 and "guarda para las amarillas una sola casa" in flat
    levels_28 = multipliers(yellow, LEVEL_28, "home") + multipliers(yellow, LEVEL_28, "away")
    assert f"por entre {spanish(min(levels_28), 3)} y {spanish(max(levels_28), 3)}" in flat and max(levels_28) < 1.0
    # § 1 and § 8: nothing meets the criterion
    assert "Córners tiene más de 300 apuestas simuladas pero un valor de cierre negativo; tarjetas no llega a 300; amarillas no tiene ninguna." in flat
    assert "el margen de las casas (≈ -3 %) sigue ahí" in flat and "el margen de las casas (≈ -3 %) sigue ahí" in f11
    assert "Registrarlas no cambia ningún modelo" in f11 and "sección 8" in flat and "## 8. Qué significa y qué se propone" in read_doc("owner", "FAMILIAS_VS_MERCADO_F11.md")
    assert variants.STEP_DAYS == 7 and "hasta casi 7 días antes del partido" in flat
    assert "se reajustan cada 3 horas" in f11 and "que se reajustan cada 3 horas" in flat


# ── Plan F12.6: the search for patterns in the settled decisions ──────────────

PATTERNS_GUIDE = "PATRONES_F12.md"
STORED_PATTERNS = DOCS / "owner" / "PATRONES_F12_resultado.json"
LEAD_ES = {"under 1 h": "menos de 1 h", "1-3 h": "de 1 a 3 h", "3-6 h": "de 3 a 6 h", "6-12 h": "de 6 a 12 h", "12-24 h": "de 12 a 24 h",
           "24 h and over": "24 h o más", "-": "sin dato"}
"""The lead-time bands as the guide's table names them: one for each band of the code, so that a new band fails here until the guide has it."""
WHY_ES = {"a larger finding in the same dimension says it already": "Fuera: otro mayor de la misma dimensión ya lo dice",
          "shares most of its rows with a larger finding": "Fuera: comparte la mitad o más de sus filas con otro mayor"}
"""What the guide's table says of a finding that repeats and is left out, for each reason the search gives (``ps.triage``)."""
PROPOSED_WORDS = "**Se propone**"
DOES_NOT_REPEAT = "Fuera: no se repite en las dos mitades"
CANNOT_TELL = "Fuera: no se pudo comprobar la repetición"
FINDINGS_HEAD = "| Medida | Grupo | Partidos (grupo / resto) | En el grupo | En el resto | Diferencia | z | z de cada mitad | Qué se hace con él |"
LEAD_HEAD = "| Antelación de la decisión | Decisiones | Partidos | Valor de cierre medio |"
COVERAGE_HEAD = ("| Dimensión | Calibración y frente al cierre (grupos · probados · con las mismas filas que otro) "
                 "| Valor de cierre (grupos · probados · con las mismas filas que otro) |")
DESCRIPTIVE_HEAD = "| Dimensión | Hallazgos | El mayor |"
ROWS_HEAD = "| Medida | Filas | Partidos | Media |"
PROPOSALS_HEAD = "| Hipótesis que deja | Qué cambiaría | z | ¿Sobrevive a la corrección? |"
TARGET_ES = {"models": "Modelos", "pick_engine": "Motor de picks"}
"""What Evolución calls the part of the system a hypothesis would change (``evolution.target`` of the Spanish catalogue of the page)."""


def stored_patterns() -> dict[str, Any]:
    """The first real reading of the search (the ``--out`` of the command), kept next to the guide."""
    if not STORED_PATTERNS.is_file():
        pytest.skip(f"no {STORED_PATTERNS.name} next to the code")
    result: dict[str, Any] = json.loads(STORED_PATTERNS.read_text(encoding="utf-8"))
    return result


def odds_band_es(name: str) -> str:
    """An odds band as the guide writes it: 'under 1.40' -> 'menos de 1,40', '1.40-1.69' -> '1,40 a 1,69', '6.00 and over' -> '6,00 o más'."""
    if name.startswith("under "):
        return "menos de " + name[len("under "):].replace(".", ",")
    if name.endswith(" and over"):
        return name[:-len(" and over")].replace(".", ",") + " o más"
    low, high = name.split("-")
    return f"{low} a {high}".replace(".", ",")


def group_name(f: dict[str, Any]) -> str:
    """A group as the guide's tables name it: the dimension and the group (an odds band in words)."""
    label = odds_band_es(f["label"]) if f["dimension"] == "odds_band" else f["label"]
    return f"{ps.DIMENSION_ES[f['dimension']]}: {label}"


def level(metric: str, x: float) -> str:
    """A mean as the guide writes it: the value of the price as a percentage, the other measures as they come."""
    return points(x) if metric == "clv" else spanish(x, 3, sign=True)


def gap_of(metric: str, x: float) -> str:
    """A difference of means as the guide writes it: the value of the price in points of percentage."""
    return f"{spanish(x * 100, 1, sign=True)} puntos" if metric == "clv" else spanish(x, 3, sign=True)


def what_is_done(report: dict[str, Any], f: dict[str, Any]) -> str:
    """What the search does with a finding that is not just the price: proposes it, or leaves it out and says why."""
    chosen, left = ps.triage(report)
    if any(f is c for c in chosen):
        return PROPOSED_WORDS
    for other, why in left:
        if other is f:
            return WHY_ES[why]
    return DOES_NOT_REPEAT if f["stable"] is False else CANNOT_TELL


def findings_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """The findings that are not just how the price is built, as the guide's table gives them (the largest ``z`` first, the way the report does)."""
    rows = []
    for f in report["found"]:
        if f["descriptive"]:
            continue
        m = f["metric"]
        halves = " / ".join("n/d" if h is None else spanish(h["z"], 1, sign=True) for h in f["halves"])
        rows.append(f"| {ps.MEASURE_ES[m]} | {group_name(f)} | {thousands(f['matches'])} / {thousands(f['matches_rest'])} | {level(m, f['mean'])} | "
                    f"{level(m, f['mean_rest'])} | {gap_of(m, f['delta'])} | {spanish(f['z'], 1, sign=True)} | {halves} | {what_is_done(report, f)} |")
    return FINDINGS_HEAD, rows


def lead_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """The value of the price by the time that went by between the decision and the kick-off."""
    return LEAD_HEAD, [f"| {LEAD_ES[b['band']]} | {thousands(b['decisions'])} | {thousands(b['matches'])} | {points(b['mean'])} |" for b in report["lead"]]


def coverage_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """How many groups each dimension had, how many had enough matches to be tested and how many were set aside for having the rows of another."""
    def cell(c: dict[str, int]) -> str:
        return f"{thousands(c['groups'])} · {thousands(c['tested'])} · {thousands(c['same'])}"

    cov = report["coverage"]
    return COVERAGE_HEAD, [f"| {ps.DIMENSION_ES[d]} | {cell(cov['calibration'][d])} | {cell(cov['clv'][d])} |" for d in ps.DIMENSIONS]


def rows_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """What was read: the rows of each measure, the matches they come from and their mean."""
    return ROWS_HEAD, [f"| {ps.MEASURE_ES[m]} | {thousands(r['rows'])} | {thousands(r['matches'])} | {level(m, r['mean'])} |"
                       for m, r in report["rows"]["by_measure"].items()]


def proposals_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """The hypotheses the search leaves for the owner, the way Evolución will show them: the title, what they would change and how sure they are."""
    chosen = ps.triage(report)[0]
    return PROPOSALS_HEAD, [f"| {p.title} | {TARGET_ES[p.target]} | {spanish(f['z'], 1, sign=True)} | {'sí' if f['survives_correction'] else 'no'} |"
                            for p, f in zip(ps.proposals(report), chosen, strict=True)]


def descriptive_table(report: dict[str, Any]) -> tuple[str, list[str]]:
    """The findings that only describe how the price is built: how many each structural dimension has and its largest."""
    rows = []
    for d in ps.STRUCTURAL:
        mine = [f for f in report["found"] if f["descriptive"] and f["dimension"] == d]
        top = max(mine, key=lambda f: abs(f["z"]))
        label = odds_band_es(top["label"]) if d == "odds_band" else top["label"]
        rows.append(f"| {ps.DIMENSION_ES[d]} | {len(mine)} | {label}: {level('clv', top['mean'])} frente a {level('clv', top['mean_rest'])} en el resto "
                    f"(z {spanish(top['z'], 1, sign=True)}) |")
    return DESCRIPTIVE_HEAD, rows


def pattern_doc() -> tuple[str, str]:
    """The guide of the search for patterns, and the same on one line (the prose, whatever the line breaks of the paragraph)."""
    doc = read_doc("owner", PATTERNS_GUIDE)
    return doc, " ".join(doc.split())


def listed(items: list[str]) -> str:
    """'a, b y c': a list the way the guide writes it in a sentence."""
    return ", ".join(items[:-1]) + " y " + items[-1]


def test_the_guide_of_the_search_for_patterns_says_what_the_code_does(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan F12.6: the guide of the search for patterns - the three measures and how each is computed, the rows it reads, the twelve dimensions and
    their groups, the bars (matches, z, the two halves, the correction for the comparisons), what only describes the price and what is read inside
    the kind of bet, what is proposed and under which key, the weekly switch and the hour the job runs, and the commands and options (every
    command it shows is one the parser accepts, with the meaning the guide gives it)."""
    import inspect
    import shlex

    from apps.worker import scheduler
    from scripts import patterns as cli

    from fbi.families.versus import loss as log_loss
    from fbi.intel import cycle

    from . import test_pattern_search as search_tests

    doc, flat = pattern_doc()
    stored = stored_patterns()
    # the version, the window and the bars, with the words the guide gives them
    assert ps.VERSION == "search-v1" and "(`search-v1`)" in doc
    assert (ps.WINDOW_DAYS, ps.MIN_Z, ps.MIN_MATCHES, ps.HALF_MIN_MATCHES, ps.HALF_MIN_Z, ps.ALPHA, ps.MAX_PROPOSALS, ps.NEAREST, ps.OVERLAP, ps.TOP) == (
        90, 3.0, 30, 10, 1.0, 0.05, 5, 10, 0.5, 5)
    for said in ("Ventana de 90 días", "corre la búsqueda de 90 días",
                 "Un grupo es un **hallazgo** cuando su diferencia llega a **3 errores estándar** (|z| ≥ 3, `--min-z`)",
                 "**Un grupo se prueba solo con 30 partidos** en el grupo y 30 en el resto (`--min-matches`)",
                 "llegar a |z| ≥ 1 (`--half-min-z`) en las dos, con 10 partidos del grupo como mínimo en cada una (`--half-min-matches`)",
                 "A lo sumo 5 por búsqueda (`--limit`)", "lista los diez grupos que se quedaron más cerca de la barra",
                 "que comparten la mitad o más de sus filas (las de ambos sobre las de cualquiera de los dos)",
                 "por debajo de 0,05 dividido por las comparaciones", "y los cinco mayores", "hasta cinco hipótesis"):
        assert said in flat, f"the guide leaves out {said!r}"
    # the correction for the comparisons: the tails it reads, how much more often chance reaches a z of 3 with 30 matches, and the bar for many more
    near_normal, near_student = ps.two_sided_p(3.0), ps.student_two_sided_p(3.0, ps.MIN_MATCHES - 1)
    assert 1.9 < near_student / near_normal < 2.1
    assert f"un z de 3 lo alcanza el azar el doble de veces (p {spanish(near_student, 4)}) que lo que dice la curva normal ({spanish(near_normal, 4)})" in flat
    assert f"con 2.000 haría falta un z de {spanish(ps.corrected_z(2000), 1)}" in flat and f"con 162, por debajo de {ps.ALPHA / 162:.4f}".replace(".", ",") in flat
    assert "la t de Student con los partidos del lado más pequeño menos uno" in flat and "corrección de Bonferroni" in flat
    # the three measures: what each is, per row, and what a positive number says
    assert ps.METRICS == ("calibration", "vs_close", "clv") and [ps.MEASURE_ES[m] for m in ps.METRICS] == ["calibración", "frente al cierre", "valor de cierre (CLV)"]
    measures = section_of(doc, "## 2. Qué mira")
    for m in ps.METRICS:
        assert f"| {ps.MEASURE_ES[m]} |" in measures
    won, lost = search_tests.row(1, p=0.6, won=1, p_close=0.55, clv=0.04), search_tests.row(2, p=0.6, won=0, p_close=0.55)
    assert ps.measure("calibration", won) == pytest.approx(1 - 0.6) and ps.measure("calibration", lost) == pytest.approx(0 - 0.6)
    vs_won, vs_lost = ps.measure("vs_close", won), ps.measure("vs_close", lost)
    assert vs_won is not None and vs_lost is not None and vs_won > 0 > vs_lost, "positive: the system read it better than the close"
    assert ps.measure("vs_close", won) == pytest.approx(log_loss(0.55, 1) - log_loss(0.6, 1)) and ps.measure("clv", won) == 0.04
    assert closing_value.VERSION == "clv-v1" and closing_value.clv(2.0, 0.55) == pytest.approx(2.0 * 0.55 - 1)
    assert "`cuota \N{MULTIPLICATION SIGN} probabilidad justa de cierre - 1` (`clv-v1`)" in flat and "scores about -6 % even if nothing moved" in " ".join((closing_value.__doc__ or "").split())
    assert "Un precio de una casa con un margen del 6 % da cerca de -6 % aunque nada se mueva" in flat
    # the rows: the last decision of each selection, settled and not void, and the ones a probability can be read against
    sql = " ".join(ps.DECISIONS_SQL.split())
    assert "DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line)" in sql and "d.known_at DESC" in sql and "o.result_status <> 'void'" in sql
    assert "COALESCE(l.p_cal, l.p_model)" in sql and "la calibrada si hubo calibrador; si no, la del modelo" in flat
    assert "la última decisión de cada selección antes del inicio del partido (así lee la memoria), con el partido jugado y sin las anuladas" in flat
    assert ps.SELECTED_ONLY == "l.state NOT IN ('RECHAZADO', 'INVESTIGACION')" and "(`--selected-only` deja solo las que quedaron como pick o en vigilancia)" in flat
    assert ps.readable("win", 0.0, Decimal("2.5")) and ps.readable("loss", 0.0, Decimal("-0.5")) and not ps.readable("half_win", 0.0, Decimal("2.25"))
    assert not ps.readable("win", 0.1, Decimal("2.5")) and not ps.readable("loss", 0.0, Decimal("-0.75"))
    assert "sin apuesta devuelta, sin medias ganadas ni perdidas y sin líneas de cuarto" in flat
    # the twelve dimensions, in the order of the code, and the groups the guide gives them
    assert len(ps.DIMENSIONS) == 12 and "**Doce dimensiones.**" in doc
    positions = [measures.index(f"\n| {ps.DIMENSION_ES[d]} | ") for d in ps.DIMENSIONS]
    assert positions == sorted(positions), "the dimensions are listed in the order of the code"
    bands = [odds_band_es(name) for _, name in ps.ODDS_BANDS] + [odds_band_es(ps.LAST_BAND)]
    assert f"| Rango de cuota | {'; '.join(bands)} |" in measures
    assert ps.NAMED[("calibration_role", "none")] == "ninguno (sin calibrar)" and "`CHAMPION`, `CHALLENGER` o «ninguno (sin calibrar)»" in measures
    assert ps.side_tags("1X2", "Draw") == ps.side_tags("OU", "Over") == ps.side_tags("BTTS", "Yes") == ("home", "away") and ps.side_tags("DC", "1X") == ("home",)
    assert "el equipo al que respalda la selección; si no respalda a ninguno (el empate) o habla del partido entero (goles, ambos marcan), los dos" in measures
    # ... the context statuses, with the meaning the code gives them
    read: dict[str, Any] = {"ai_mode": "shadow", "first_pass": True, "reviewed": False, "searched": False, "web_good": 0, "provider_items": 0, "lineups": False}
    assert decision.context_status(**{**read, "ai_mode": "off"}) == "AI_OFF" and decision.context_status(**{**read, "first_pass": False}) == "PENDING"
    assert decision.context_status(**{**read, "web_good": 1}) == "FULL" and decision.context_status(**{**read, "searched": True, "lineups": True}) == "FULL"
    assert decision.context_status(**{**read, "provider_items": 1}) == "PARTIAL" and decision.context_status(**{**read, "lineups": True}) == "PARTIAL"
    assert decision.context_status(**read) == "LIMITED"
    for status, words in (("FULL", "leído, con evidencia de la web o las alineaciones confirmadas"), ("PARTIAL", "leído, solo con lo que informa el proveedor"),
                          ("LIMITED", "leído, sin nada fuera de los números"), ("PENDING", "aún no lo había leído"), ("AI_OFF", "capa de IA apagada")):
        assert f"`{status}` ({words})" in measures
    # what only describes the price, and what is read inside the kind of bet (lead time, line and odds band)
    assert ps.STRUCTURAL == ("market", "market_line", "selection", "odds_band") and ps.ADJUSTED == ("clv",) and ps.STRATA == ("market_line", "odds_band", "lead")
    situational = [ps.DIMENSION_ES[d].lower() for d in ps.DIMENSIONS if d not in ps.STRUCTURAL]
    assert f"**{listed([ps.DIMENSION_ES[d] for d in ps.STRUCTURAL])}** son la estructura del precio" in flat
    assert f"**Las demás dimensiones** ({listed(situational)}) se comparan en el valor de cierre **dentro de cada clase de apuesta**" in flat
    assert all(ps.descriptive("clv", d) and not ps.adjusted("clv", d) for d in ps.STRUCTURAL)
    assert all(ps.adjusted("clv", d) and not ps.descriptive("clv", d) for d in ps.DIMENSIONS if d not in ps.STRUCTURAL)
    assert not any(ps.adjusted(m, d) or ps.descriptive(m, d) for m in ("calibration", "vs_close") for d in ps.DIMENSIONS), "the other two measures need no such care"
    lead_names = [LEAD_ES[name] for _, name in ps.LEAD_BANDS] + [LEAD_ES[ps.LAST_LEAD]]
    assert f"la misma línea de mercado, el mismo rango de cuota y la misma antelación de la decisión ({', '.join(lead_names)}; cada banda incluye su límite inferior)" in flat
    assert ps.lead_band(0.99) == "under 1 h" and ps.lead_band(1.0) == "1-3 h" and ps.lead_band(24.0) == ps.LAST_LEAD and ps.lead_band(None) == "-"
    assert set(LEAD_ES) == {name for _, name in ps.LEAD_BANDS} | {ps.LAST_LEAD, "-"}
    assert "los pesos del estimador de Mantel-Haenszel" in flat and "una clase donde solo hay una de las dos partes no cuenta" in flat
    # what is proposed: the key, the targets and the cost, and what the owner sees
    keys = [p.key for p in ps.proposals(stored)]
    assert keys[0] == "pattern2:calibration:calibration_role:none:down" and "`pattern2:{medida}:{dimensión}:{grupo}:{up|down}`" in doc
    assert "(por ejemplo, `pattern2:calibration:calibration_role:none:down`)" in flat and all(re.fullmatch(r"pattern2:\w+:\w+:[^:]+:(up|down)", k) for k in keys)
    assert ps.TARGET == {"calibration": "models", "vs_close": "models", "clv": "pick_engine"} and set(TARGET_ES) == set(ps.TARGET.values())
    assert "Las de calibración y las de frente al cierre apuntan a «Modelos»; las del valor de cierre, al «Motor de picks»" in flat
    assert f"«{ps.INVESTIGATION}»" in flat and ps.proposals(stored)[0].evidence["investigation_cost"] == ps.INVESTIGATION
    assert all(p.evidence["pattern_version"] == ps.VERSION for p in ps.proposals(stored))
    # ... Evolución's own words
    catalog = Path(__file__).resolve().parents[3] / "web" / "src" / "locales" / "es" / "ai.json"
    if catalog.is_file():
        words = json.loads(catalog.read_text(encoding="utf-8"))["evolution"]
        assert words["proposals"]["title"] == "Mejoras propuestas" and words["status"]["PROPOSED"] == "Propuesta"
        assert [words["decide"][k] for k in ("reject", "investigate", "approve_experiment")] == ["Rechazar", "Investigar", "Aprobar experimento"]
        assert (words["target"]["models"], words["target"]["pick_engine"]) == (TARGET_ES["models"], TARGET_ES["pick_engine"])
        assert (words["propose"]["fieldTarget"], words["proposals"]["cost"]) == ("Qué cambiaría", "Costo de investigarlo")
    for said in ("**«Mejoras propuestas»**", "**«Propuesta»**", "**«Rechazar»**, **«Investigar»** o **«Aprobar experimento»**", "costo de investigarlo",
                 "y lo que cambiarían"):
        assert said in flat, f"the guide leaves out {said!r}"
    # the weekly job: the switch and its three states, the hour, the place it keeps its summary and where it sits among the steps
    assert ps.SWITCH == "FBI_PATTERN_SEARCH" and f"`{ps.SWITCH}`" in doc and ps.MODES == ("off", "report", "propose")
    for value, want in ((None, "off"), ("bogus", "off"), ("", "off"), ("report", "report"), (" PROPOSE ", "propose")):
        monkeypatch.setattr(ps, "environment", lambda value=value: {} if value is None else {ps.SWITCH: value})
        assert ps.mode() == want
    modes = section_of(doc, "## 9. Cada lunes, si lo enciendes")
    for mode_text in ("| `off` (por omisión, y cualquier valor desconocido) | nada: la búsqueda no corre |", "| `report` | corre la búsqueda de 90 días y guarda un resumen",
                      "| `propose` | lo mismo, y además propone en Evolución, una sola vez cada una, hasta cinco hipótesis"):
        assert mode_text in modes
    assert (scheduler.INTEL_WEEKLY_WEEKDAY, scheduler.INTEL_WEEKLY_HOUR, scheduler.INTEL_WEEKLY_MINUTE) == ("mon", 4, 40)
    assert re.search(r'minute=INTEL_WEEKLY_MINUTE, timezone="America/Bogota", id="intel_weekly"', inspect.getsource(scheduler))
    assert "(`intel_weekly`, los lunes a las 04:40 hora de Bogotá)" in flat
    assert '("matrix", _matrix), ("patterns", _patterns)])' in inspect.getsource(cycle.run_weekly) and "tiene este paso al final" in flat
    assert "report.counts[name] = result" in inspect.getsource(cycle._run) and "`counts.patterns`" in flat and "`intel.runs`" in flat
    assert set(ps.summary(stored)) == {"version", "decisions", "matches", "tests", "expected_by_chance", "found", "descriptive", "repeating", "survive_correction",
                                       "top"} and len(ps.summary(stored)["top"]) <= ps.TOP
    assert 'report.status = "partial"' in inspect.getsource(cycle._run) and "deja la corrida como «parcial» sin parar los demás pasos de la semana" in flat
    assert "`/etc/predigol/app.env`" in flat and "`deploy/vps/app.env.example`" in flat
    # ... and the two other places that tell the owner about it: the file of variables of the server and the document of the intelligence
    example = DOCS.parent / "deploy" / "vps" / "app.env.example"
    if example.is_file():
        variables = example.read_text(encoding="utf-8")
        assert "# FBI_PATTERN_SEARCH=off" in variables and f"docs/owner/{PATTERNS_GUIDE}" in variables, "the default is off and the example points at the guide"
        assert all(f"#   {mode_name} " in variables for mode_name in ps.MODES) and "Every Monday at 04:40 Bogotá, as the last step of intel_weekly" in variables
    weekly_row = next(line for line in PI.splitlines() if line.startswith("| lunes 04:40 |"))
    assert f"(`{ps.SWITCH}`)" in weekly_row and f"`docs/owner/{PATTERNS_GUIDE}`" in weekly_row and "`intel_weekly`" in weekly_row and "apagada por omisión" in weekly_row
    # the commands: the parser accepts each, with the meaning the guide gives it, and the options have the defaults the guide says
    parser = cli.build_parser()
    blocks = doc.split("```")
    sample = blocks[1].strip("\n")
    assert sample in ps.render(stored).splitlines(), "the line the guide shows is the one the command prints"
    commands = [line.split("#")[0].strip() for line in blocks[3].splitlines() if line.startswith("python -m scripts.patterns")]
    assert len(commands) == 5
    parsed = [parser.parse_args(shlex.split(command)[3:]) for command in commands]
    assert [a.command for a in parsed] == ["search", "search", "search", "propose", "propose"]
    assert parsed[0].days == 90 and parsed[1].days == 60 and parsed[1].selected_only is True and parsed[1].metric == ["clv"]
    assert parsed[1].dimension == ["competition", "market"] and parsed[2].json is True and parsed[2].out == "patrones.json"
    assert parsed[3].confirm is False and parsed[4].confirm is True
    search_args, propose_args = parser.parse_args(["search"]), parser.parse_args(["propose"])
    assert (search_args.days, search_args.until, search_args.selected_only, search_args.metric, search_args.dimension) == (90, None, False, None, None)
    assert (search_args.min_matches, search_args.min_z, search_args.half_min_matches, search_args.half_min_z, search_args.alpha) == (30, 3.0, 10, 1.0, 0.05)
    assert (search_args.json, search_args.out, propose_args.limit, propose_args.confirm) == (False, None, 5, False)
    options = {cells[0]: cells for cells in ([c.strip() for c in line.strip("|").split("|")] for line in table_rows(section_of(doc, "## 10. Cómo se repite"), "| Opción |"))}
    defaults = {"`--days`": "90", "`--until`": "ahora", "`--selected-only`": "no", "`--metric`": "las tres", "`--dimension`": "las doce", "`--min-matches`": "30",
                "`--min-z`": "3", "`--half-min-matches`": "10", "`--half-min-z`": "1", "`--alpha`": "0,05"}
    assert {name: cells[1] for name, cells in options.items() if name in defaults} == defaults
    assert len(ps.METRICS) == 3 and len(ps.DIMENSIONS) == 12 and set(ps.METRICS) == {"calibration", "vs_close", "clv"}
    for option in ("--days", "--until", "--selected-only", "--metric", "--dimension", "--min-matches", "--min-z", "--half-min-matches", "--half-min-z", "--alpha",
                   "--json", "--out", "--limit", "--confirm"):
        assert f"`{option}`" in doc, f"the guide leaves out {option}"
    with pytest.raises(SystemExit):
        parser.parse_args(["search", "--metric", "roi"])
    with pytest.raises(SystemExit):
        parser.parse_args(["search", "--dimension", "weather"])
    assert "Solo lee: abre la conexión de solo lectura y la deshace; con `propose --confirm` es la única orden que escribe" in flat
    assert cli.READ_ONLY == "-c default_transaction_read_only=on"
    # what it points to, and what points to it
    for guide in ("FAMILIAS_VS_MERCADO_F11.md", "PROMOCIONES_F12.md", "VARIANTES_VS_MERCADO_F12.md", "PATRONES_F12_resultado.json"):
        assert (DOCS / "owner" / guide).is_file() and f"`{guide}`" in doc, guide
    assert "## 8. Qué significa y qué se propone" in read_doc("owner", "FAMILIAS_VS_MERCADO_F11.md") and "(`FAMILIAS_VS_MERCADO_F11.md`, sección 8)" in flat
    for test_name in ("test_inside_the_strata_the_difference_is_the_average_of_the_differences_weighted_by_the_rows_of_both",
                      "test_a_planted_difference_is_found_with_its_numbers_and_nothing_else_is"):
        assert hasattr(search_tests, test_name) and f"`{test_name}`" in doc, test_name
    assert (Path(__file__).resolve().parents[1] / "integration" / "test_pattern_search.py").is_file() and "`tests/integration/test_pattern_search.py`" in doc
    assert "`fbi/research/pattern_search.py`" in doc and "`scripts/patterns.py`" in doc


def test_the_stored_reading_of_the_search_is_the_codes_own_arithmetic() -> None:
    """Plan F12.6: the reading that the guide quotes is held to the code - the criterion it was made with, the window the code reads, the comparisons
    being the groups it tested, the chance and the corrected bar being what the code computes from them, each finding's z being its difference over its
    error and its p the tail of Student's t for the matches of its smaller side, whether it survives the correction being that p against alpha over the
    comparisons, its flags being what the code says of its dimension and measure, whether it repeats being what its two halves say, the lead table adding
    up to the price read and the proposals being what the code leaves of the findings (so a change in the criterion, the arithmetic or the triage makes
    the stored reading, and the guide built on it, go stale loudly)."""
    stored = stored_patterns()
    assert stored["version"] == ps.VERSION and list(stored) == ["version", "criterion", "rows", "lead", "coverage", "tests", "expected_by_chance",
                                                                "corrected_z", "found", "nearest", "window"]
    c = stored["criterion"]
    assert {k: c[k] for k in ("min_z", "min_matches", "half_min_matches", "half_min_z", "alpha")} == {
        "min_z": ps.MIN_Z, "min_matches": ps.MIN_MATCHES, "half_min_matches": ps.HALF_MIN_MATCHES, "half_min_z": ps.HALF_MIN_Z, "alpha": ps.ALPHA}
    assert c["within"] == {"measures": list(ps.ADJUSTED), "strata": list(ps.STRATA), "descriptive": list(ps.STRUCTURAL)}
    # the window: the days the code reads, ending at midnight, over every decision; the decisions begin on 13 October, so the halves are about five days
    w = stored["window"]
    start, end, split = (datetime.fromisoformat(x) for x in (w["start"], w["end"], c["split"]))
    assert w["days"] == ps.WINDOW_DAYS and end - start == timedelta(days=ps.WINDOW_DAYS) and w["selected_only"] is False and end == datetime(2026, 10, 24, tzinfo=UTC)
    assert datetime(2026, 10, 17, tzinfo=UTC) < split < datetime(2026, 10, 19, tzinfo=UTC)
    assert timedelta(days=10) <= 2 * (split - datetime(2026, 10, 13, tzinfo=UTC)) <= timedelta(days=11), "the decisions of the system begin on 13 October"
    assert "The decisions of the system begin on 13 October 2026" in " ".join((Path(ps.__file__).read_text(encoding="utf-8")).split())
    # what was read
    by = stored["rows"]["by_measure"]
    assert list(by) == list(ps.METRICS) and by["calibration"]["rows"] == by["vs_close"]["rows"] < by["clv"]["rows"] == stored["rows"]["decisions"]
    assert max(m["matches"] for m in by.values()) == stored["rows"]["matches"] <= stored["rows"]["decisions"]
    # the questions asked: every group tested is a comparison, and the two measures that read the same rows were asked the same questions
    cov = stored["coverage"]
    assert list(cov) == list(ps.METRICS) and all(list(cov[m]) == list(ps.DIMENSIONS) for m in ps.METRICS) and cov["calibration"] == cov["vs_close"]
    assert all(v["tested"] + v["same"] <= v["groups"] for m in ps.METRICS for v in cov[m].values())
    tests = stored["tests"]
    assert tests == sum(cov[m][d]["tested"] for m in ps.METRICS for d in ps.DIMENSIONS)
    assert stored["corrected_z"] == pytest.approx(ps.corrected_z(tests, c["alpha"]))
    assert tests * ps.two_sided_p(c["min_z"]) <= stored["expected_by_chance"] <= tests * ps.student_two_sided_p(c["min_z"], c["min_matches"] - 1)
    # every finding is the arithmetic of its own numbers
    found, nearest = stored["found"], stored["nearest"]
    assert all(abs(f["z"]) >= c["min_z"] for f in found) and all(abs(f["z"]) < c["min_z"] for f in nearest) and len(nearest) == ps.NEAREST
    for group in (found, nearest):
        assert [abs(f["z"]) for f in group] == sorted((abs(f["z"]) for f in group), reverse=True)
    assert abs(found[-1]["z"]) >= c["min_z"] > abs(nearest[0]["z"])
    for i, f in enumerate(found + nearest):
        who = f"{f['metric']} {f['dimension']} {f['label']}"
        assert f["metric"] in ps.METRICS and f["dimension"] in ps.DIMENSIONS, who
        assert f["z"] == pytest.approx(f["delta"] / f["se"]) and f["delta"] == pytest.approx(f["mean"] - f["mean_rest"], abs=1e-12), who
        assert f["matches"] >= c["min_matches"] and f["matches_rest"] >= c["min_matches"] and f["n"] >= f["matches"] and f["n_rest"] >= f["matches_rest"], who
        assert f["p"] == pytest.approx(ps.student_two_sided_p(f["z"], min(f["matches"], f["matches_rest"]) - 1), rel=1e-9, abs=1e-15), who
        assert f["survives_correction"] == (f["p"] <= c["alpha"] / tests), who
        assert f["descriptive"] == ps.descriptive(f["metric"], f["dimension"]) and f["within_strata"] == ps.adjusted(f["metric"], f["dimension"]), who
        assert all(ps.STANDS_FOR.index(f["dimension"]) < ps.STANDS_FOR.index(d) for d, _ in f["same_rows_as"]), "the dimension that stands for the others is named"
        assert all(j < i for j in f["overlaps"]), "a finding overlaps only with a larger one"
        if f in nearest:
            assert f["halves"] == [None, None] and f["stable"] is None, "the halves are worked out only for what reached the bar"
            continue
        # whether it repeats: the same sign and the bar of a half in each half, each with matches enough to be read
        assert len(f["halves"]) == 2
        if None in f["halves"]:
            assert f["stable"] is None, who
            continue
        assert all(h["matches"] >= c["half_min_matches"] for h in f["halves"]), who
        assert f["stable"] == all(math.copysign(1.0, h["delta"]) == math.copysign(1.0, f["delta"]) and abs(h["z"]) >= c["half_min_z"] for h in f["halves"]), who
    # what is proposed, and why each of the others that repeat is not
    chosen, left = ps.triage(stored)
    assert len(chosen) == ps.MAX_PROPOSALS == len(ps.proposals(stored)) and all(f["stable"] is True and not f["descriptive"] for f in chosen)
    assert len({(f["metric"], f["dimension"]) for f in chosen}) == len(chosen) and [abs(f["z"]) for f in chosen] == sorted((abs(f["z"]) for f in chosen), reverse=True)
    assert {why for _, why in left} == {"descriptive: how the price is built", "a larger finding in the same dimension says it already",
                                        "shares most of its rows with a larger finding"}
    assert sorted(id(f) for f in chosen + [f for f, _ in left]) == sorted(id(f) for f in found if f["stable"] is True), "every finding that repeats is proposed or left out"
    assert sum(1 for f, _ in left if f["descriptive"]) == sum(1 for f in found if f["descriptive"]) == 39
    summary = ps.summary(stored)
    assert (summary["found"], summary["descriptive"], summary["survive_correction"]) == (len(found), 39, sum(1 for f in found if f["survives_correction"]))
    assert summary["repeating"] == sum(1 for f in found if f["stable"] is True and not f["descriptive"])
    # the price by lead time adds up to the price read
    lead = stored["lead"]
    assert [b["band"] for b in lead] == [name for _, name in ps.LEAD_BANDS] + [ps.LAST_LEAD]
    assert sum(b["decisions"] for b in lead) == by["clv"]["rows"] and all(b["matches"] <= by["clv"]["matches"] for b in lead)
    assert sum(b["decisions"] * b["mean"] for b in lead) / by["clv"]["rows"] == pytest.approx(by["clv"]["mean"], abs=1e-12)
    # the text of the command prints what is stored
    printed = ps.render(stored)
    assert printed.startswith(f"pattern search {ps.VERSION}") and f"FOUND, |z| >= {ps.MIN_Z:g}: {len(found)}" in printed
    assert f"comparisons made: {tests:,}. By chance alone {stored['expected_by_chance']:.1f}" in printed and f"|z| of about {stored['corrected_z']:.1f}" in printed


def find_finding(report: dict[str, Any], metric: str, dimension: str, label: str) -> dict[str, Any]:
    """One finding of the stored reading, by its measure, its dimension and the name of its group."""
    return next(f for f in report["found"] if (f["metric"], f["dimension"], f["label"]) == (metric, dimension, label))


def test_the_guide_of_the_search_for_patterns_says_what_was_measured() -> None:
    """Plan F12.6: every figure of the guide - the questions asked and what chance would have said, what was read, the tables and what is said of them
    in words - is the one of the stored reading, written the way the guide writes it (decimal comma, thousands with a dot), and what it says of
    the direction of the results (the price explains most of what reaches the bar, the decisions with no calibrator the clearest, the context
    twice and not twice as proof, the Champions League and the line of 1.5 goals the frailest) is true of those numbers."""
    doc, flat = pattern_doc()
    stored = stored_patterns()
    found, nearest, tests, c = stored["found"], stored["nearest"], stored["tests"], stored["criterion"]
    by = stored["rows"]["by_measure"]
    # the tables of the guide are the stored numbers, and the guide has no other table than the ones that something checks
    tables = {"## 2. Qué mira": [], "## 3. Qué cuenta como un hallazgo, y qué se propone": [], "## 4. El precio se compara con lo de su clase": [lead_table],
              "## 6. Primera lectura": [rows_table, coverage_table, descriptive_table, findings_table, proposals_table],
              "## 9. Cada lunes, si lo enciendes": [], "## 10. Cómo se repite": []}
    for heading, builders in tables.items():
        part = section_of(doc, heading)
        for build in builders:
            head, rows = build(stored)
            assert rows and table_rows(part, head) == rows, f"{heading}: the table {head!r} of the guide is not the stored reading"
        rules = sum(1 for line in part.splitlines() if line.startswith("|---"))
        others = {"## 2. Qué mira": 2, "## 9. Cada lunes, si lo enciendes": 1, "## 10. Cómo se repite": 1}.get(heading, 0)
        assert rules == len(builders) + others, f"{heading}: a table of the guide that nothing checks"
    # § 1: the questions, what chance says of them, what reaches the bar and what is proposed
    expected = stored["expected_by_chance"]
    descriptive = [f for f in found if f["descriptive"]]
    survivors = [f for f in found if f["survives_correction"]]
    chosen = ps.triage(stored)[0]
    assert (f"Fueron {tests} comparaciones: por azar solo {spanish(expected, 1)} de ellas llegarían a {c['min_z']:g} errores estándar, y para seguir siendo "
            f"significativa después de hacerlas todas, una diferencia entre grupos grandes necesita llegar a {spanish(stored['corrected_z'], 1)}") in flat
    assert (f"**Primera lectura: {len(found)} grupos llegan a {c['min_z']:g} errores estándar, y {len(descriptive)} de ellos solo describen cómo se construye el precio**") in flat
    assert (f"De los otros {len(found) - len(descriptive)}, **{len(chosen)} se proponen** (los que se repiten en las dos mitades de la ventana y no dicen lo que ya "
            f"dice otro mayor) y {sum(1 for f in chosen if f['survives_correction'])} de las {len(chosen)} siguen siendo significativas corrigiendo por todas las comparaciones") in flat
    assert (len(found), len(descriptive), len(chosen), sum(1 for f in chosen if f["survives_correction"])) == (49, 39, 5, 3)
    none = find_finding(stored, "calibration", "calibration_role", "ninguno (sin calibrar)")
    assert (f"En {none['n']} decisiones de {none['matches']} partidos, lo que ocurre queda en promedio {spanish(-none['mean'], 3)} por debajo de lo que el sistema decía; "
            f"en el resto queda {spanish(none['mean_rest'], 3)} por encima. Sale en las dos mitades.") in flat
    assert none["mean"] < 0 < none["mean_rest"] and none["stable"] is True and none["survives_correction"] and (none["n"], none["matches"]) == (295, 231)
    assert "son unos 10 días de partidos, y «se repite en las dos mitades» quiere decir en dos mitades de unos 5" in flat
    assert "pero el sistema decide desde el 13 de octubre" in flat and "de modo que de esos 90 días solo hay decisiones en unos 10" in flat
    # § 2: what was read
    assert f"líneas de cuarto: {thousands(by['calibration']['rows'])} de las {thousands(stored['rows']['decisions'])}. El valor de cierre se lee en todas" in flat
    assert by["calibration"]["rows"] == by["vs_close"]["rows"] < by["clv"]["rows"] == stored["rows"]["decisions"], "the first two are read in some of the decisions, the third in all"
    assert f"la media de todas las decisiones es {spanish(by['clv']['mean'] * 100, 1)} %" in flat
    # § 3: the half of the window
    split = datetime.fromisoformat(c["split"])
    assert f"el {split.day} de octubre a las {split:%H:%M} UTC" in flat and (split.month, split.day) == (10, 18)
    # § 4: the lead time weighs more than almost any finding
    lead = stored["lead"]
    best, worst = max(lead, key=lambda b: b["mean"]), min(lead, key=lambda b: b["mean"])
    situational = [abs(f["delta"]) for f in found if f["metric"] == "clv" and not f["descriptive"]]
    assert (f"De la mejor banda ({LEAD_ES[best['band']]}, {points(best['mean'])}) a la peor ({LEAD_ES[worst['band']]}, {points(worst['mean'])}) hay "
            f"{spanish((best['mean'] - worst['mean']) * 100, 1)} puntos, más que cualquiera de las diferencias entre grupos de dimensiones situacionales de la sección 6 "
            f"(la mayor es de {spanish(max(situational) * 100, 1)})") in flat
    assert best["mean"] - worst["mean"] > max(situational) and (best["band"], worst["band"]) == ("under 1 h", "12-24 h")
    # § 5: the line the guide shows, token by token
    line = " ".join(ps.render(stored).splitlines()[next(i for i, x in enumerate(ps.render(stored).splitlines()) if x.lstrip().startswith("calibration") and "ninguno" in x)].split())
    for token in (f"matches {none['matches']} rows {none['n']}", f"group {none['mean']:+.3f} rest {none['mean_rest']:+.3f}", f"diff {none['delta']:+.3f}", f"z {none['z']:+.1f}",
                  f"halves {none['halves'][0]['z']:+.1f}/{none['halves'][1]['z']:+.1f} repeats", "SURVIVES the correction"):
        assert token in line, token
    assert f"**`matches {none['matches']} rows {none['n']}`**" in doc and f"**`group {none['mean']:+.3f} rest {none['mean_rest']:+.3f}`**" in doc
    assert f"**`z {none['z']:+.1f}`**" in doc and f"**`halves {none['halves'][0]['z']:+.1f}/{none['halves'][1]['z']:+.1f}`**" in doc
    assert "**`diff`** es grupo - resto" in flat and "**`SURVIVES the correction`**" in doc and "**`repeats`**" in doc
    # § 6: the window, what the coverage says of the teams, the referees and the coaches, and what only describes the price
    start, end = (datetime.fromisoformat(stored["window"][k]) for k in ("start", "end"))
    assert f"entre el {day_es(stored['window']['start'])} y el {day_es(stored['window']['end'])} a las {end:%H:%M} UTC" in flat and (end - start).days == 90
    cov = stored["coverage"]["clv"]
    assert (cov["team"]["tested"], cov["referee"]["tested"], cov["coach"]["tested"]) == (0, 0, 1)
    assert "**ningún equipo, ningún árbitro y un solo entrenador** pudieron probarse (0, 0 y 1)" in flat and "(`--days 365`, cuando haya un año de decisiones)" in flat
    assert f"({len(descriptive)} de los {len(found)}; por dimensión y el mayor de cada una)" in flat
    assert f"Se repiten los {len(descriptive)} y {sum(1 for f in descriptive if f['survives_correction'])} sobreviven a la corrección" in flat
    assert all(f["stable"] is True for f in descriptive) and sum(1 for f in descriptive if f["survives_correction"]) == 36 == len(survivors) - sum(
        1 for f in found if f["survives_correction"] and not f["descriptive"]) and sum(1 for f in found if f["survives_correction"] and not f["descriptive"]) == 5
    bands = {f["label"]: f for f in descriptive if f["dimension"] == "odds_band"}
    long_odds, short_odds = bands["3.50-5.99"], [bands[k] for k in ("1.40-1.69", "1.70-1.99", "2.00-2.49")]
    rare = find_finding(stored, "clv", "market_line", "OU 1.25")
    assert (f"las cuotas largas (3,50 a 5,99) valen {spanish(-long_odds['delta'] * 100, 1)} puntos menos al cierre que el resto y las cortas (de 1,40 a 2,49) entre "
            f"{spanish(min(f['delta'] for f in short_odds) * 100, 1)} y {spanish(max(f['delta'] for f in short_odds) * 100, 1)} puntos más; las líneas raras, como `OU 1.25`, "
            f"hasta {spanish(-rare['delta'] * 100, 1)} menos") in flat
    assert long_odds["delta"] < 0 < min(f["delta"] for f in short_odds) and rare["delta"] == min(f["delta"] for f in descriptive if f["dimension"] == "market_line")
    assert f"**Los otros {len(found) - len(descriptive)} hallazgos**" in flat
    # § 6, in words: the decisions with no calibrator, and the hypothesis that is the same fact seen from the other side
    challenger = find_finding(stored, "calibration", "calibration_role", "CHALLENGER")
    market_dc = find_finding(stored, "calibration", "market", "DC")
    assert (f"Lo que ocurre queda {spanish(-none['mean'], 3)} por debajo de lo que el sistema decía (frente a {spanish(none['mean_rest'], 3, sign=True)} en el resto: "
            f"{spanish(none['delta'], 3, sign=True)}, z {spanish(none['z'], 1, sign=True)}), con el mismo signo en las dos mitades "
            f"({spanish(none['halves'][0]['z'], 1, sign=True)} y {spanish(none['halves'][1]['z'], 1, sign=True)}) y sin perderse en la corrección") in flat
    assert (f"el de `CHALLENGER` ({spanish(challenger['delta'], 3, sign=True)}) es el mismo hecho visto desde el otro lado: su resto "
            f"({spanish(challenger['mean_rest'], 3, sign=True)}) lleva dentro a los sin calibrar") in flat
    assert challenger["mean_rest"] < challenger["mean"] and challenger["mean_rest"] > none["mean"] and ps.triage(stored)[1] and any(
        f is challenger and "same dimension" in why for f, why in ps.triage(stored)[1])
    assert any(f is market_dc and "shares most of its rows" in why for f, why in ps.triage(stored)[1]) and market_dc["same_rows_as"] == [["market_line", "DC 0"]]
    # ... the context, twice
    pending_clv, pending_cal = (find_finding(stored, m, "context", "PENDING") for m in ("clv", "calibration"))
    assert (f"El precio tomado pierde {spanish(-pending_clv['delta'] * 100, 1)} puntos más contra el cierre que el resto, en las mismas clases de apuesta "
            f"({points(pending_clv['mean'])} frente a {points(pending_clv['mean_rest'])}, z {spanish(pending_clv['z'], 1, sign=True)}), y lo que ocurre queda "
            f"{spanish(pending_cal['delta'], 3)} por encima de lo que el sistema decía ({spanish(pending_cal['mean'], 3, sign=True)} frente a "
            f"{spanish(pending_cal['mean_rest'], 3, sign=True)}, z {spanish(pending_cal['z'], 1, sign=True)})") in flat
    assert (f"la del precio es mucho más débil en la segunda mitad ({spanish(pending_clv['halves'][0]['z'], 1, sign=True)} y "
            f"{spanish(pending_clv['halves'][1]['z'], 1, sign=True)})") in flat
    assert pending_clv["delta"] < 0 < pending_cal["delta"] and abs(pending_clv["halves"][1]["z"]) < abs(pending_clv["halves"][0]["z"]) / 2
    assert pending_clv["survives_correction"] and pending_cal["survives_correction"] and pending_clv["stable"] is True is pending_cal["stable"]
    assert 0.8 < pending_cal["matches"] / pending_clv["matches"] < 1.2, "in good part the same decisions"
    # ... the Champions League and the line of 1.5 goals, the frailest of the five
    champions = find_finding(stored, "clv", "competition", "UEFA Champions League")
    goals = find_finding(stored, "vs_close", "market_line", "OU 1.5")
    assert (f"Son {champions['matches']} partidos ({champions['n']} decisiones) con el precio tomado {spanish(champions['delta'] * 100, 1)} puntos mejor contra el cierre que el resto "
            f"({points(champions['mean'])} frente a {points(champions['mean_rest'])}, z {spanish(champions['z'], 1, sign=True)}, mitades "
            f"{spanish(champions['halves'][0]['z'], 1, sign=True)} y {spanish(champions['halves'][1]['z'], 1, sign=True)}). Se repite, pero no sobrevive a la corrección: "
            f"su p ({spanish(champions['p'], 4)}) queda por encima de {spanish(c['alpha'] / tests, 4)}") in flat
    assert champions["stable"] is True and not champions["survives_correction"] and champions["p"] > c["alpha"] / tests and champions["matches"] < 100
    assert (f"En {goals['matches']} partidos el sistema queda ligeramente por encima de las casas ({spanish(goals['mean'], 3, sign=True)} por fila) mientras que en el "
            f"resto las casas van por delante ({spanish(goals['mean_rest'], 3, sign=True)}): diferencia de {spanish(goals['delta'], 3, sign=True)}, "
            f"z {spanish(goals['z'], 1, sign=True)}. Tampoco sobrevive (p {spanish(goals['p'], 4)})") in flat
    assert goals["mean"] > 0 > goals["mean_rest"] and goals["n"] == goals["matches"] and not goals["survives_correction"] and goals["stable"] is True
    # ... what was left out, and what came near
    full_clv, full_cal = find_finding(stored, "clv", "context", "FULL"), find_finding(stored, "calibration", "context", "FULL")
    limited = find_finding(stored, "clv", "context", "LIMITED")
    assert (f"«Contexto: LIMITED» en valor de cierre ({spanish(limited['delta'] * 100, 1, sign=True)} puntos, z {spanish(limited['z'], 1, sign=True)}) tiene "
            f"{spanish(limited['halves'][0]['z'], 1, sign=True)} en la primera mitad y {spanish(limited['halves'][1]['z'], 1, sign=True)} en la segunda") in flat
    assert limited["stable"] is False and limited["halves"][1]["z"] < c["half_min_z"] and "Cinco hallazgos se quedaron fuera" in flat
    left = ps.triage(stored)[1]
    assert sum(1 for f, _ in left if not f["descriptive"]) + sum(1 for f in found if f["stable"] is False) == 5
    assert all(any(f is x and "same dimension" in why for x, why in left) for f in (challenger, full_clv, full_cal)) and "Tres porque otro mayor de su misma dimensión ya lo dice" in flat
    assert f"(de z {spanish(abs(nearest[0]['z']), 1)} a {spanish(abs(nearest[-1]['z']), 1)})" in flat
    # § 7: what can and cannot be said
    assert (f"Tres sobreviven a la corrección por las {tests} comparaciones, y dos no" in flat and "Salen de unos 10 días de partidos" in flat
            and f"{len(descriptive)} de los {len(found)} hallazgos solo dicen cómo se construye el precio" in flat)
    assert f"Las {tests} comparaciones no son {tests} pruebas independientes" in flat
    assert f"El {spanish(by['clv']['mean'] * 100, 1)} % de la media es sobre todo el margen de las casas" in flat
    assert "ningún equipo ni árbitro y un solo entrenador llegaron a los 30 partidos" in flat
    for lead_in in ("**Hoy hay cinco hipótesis, ninguna prueba.**", "**El precio no es el sistema.**", "**Las dimensiones miran las mismas decisiones.**",
                    "**El valor de cierre medio no es una pérdida.**", "**Equipos, árbitros y entrenadores no se leen todavía**",
                    "**Lo que dice esta lectura no es la prueba.**", "**La más clara es la de las decisiones sin calibrar.**",
                    "**«Contexto: PENDING» sale en dos medidas.**", "**La Champions League es la más frágil de las cinco.**", "**«OU 1.5» frente al cierre.**"):
        assert lead_in in doc, f"the guide no longer says {lead_in}"
    # § 8: nothing has been written to the owner's page by this reading
    assert "La lectura de esta guía no registró ninguna" in flat and "la lectura de esta guía no escribió nada" in flat
