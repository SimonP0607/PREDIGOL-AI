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

import json
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import learning, pm_narratives, usage
from fbi.ai.config import AiSettings
from fbi.families import dependence
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

    from fbi.families import bets, versus

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
