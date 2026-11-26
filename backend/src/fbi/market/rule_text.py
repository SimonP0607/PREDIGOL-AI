"""What each settlement rule SAYS, in the reader's words, and where the houses may count differently (RP-10.4, finding H22).

``fbi.market.rules`` holds the rules the code grades with; this module holds what a reader is told about them. Every rule has a text in
Spanish and in English, and a mark ``may_differ``: the provider does not say how each house counts, so for some measures the figure a bet is
graded on here may not be the figure the reader's own house uses. The mark is honest about it and says in what way.

The size of that difference is measured, not guessed (``conventions``): over the finished matches whose cards come from the classified events,
how many of them the alternative conventions of the cards would grade differently on the lines houses offer. The measurement reads
``market.fixture_outcomes`` in ONE grouped query and changes nothing.

No rule is edited here and none is added: a convention that changes is a new version in ``fbi.market.rules`` (its text is then added here, and a
test refuses a rule without text).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.market.rules import OUTCOMES_VIEW, RULES, Rule

VERSION: Final = "rule-text-v1"
CARD_LINES: Final = (1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5)
"""The total-cards lines that houses offer most; the discrepancy is measured on each."""


@dataclass(frozen=True, slots=True)
class RuleText:
    key: str  # ``measure@vN``
    es: str
    en: str
    may_differ: bool = False
    differ_es: str = ""
    differ_en: str = ""


def _t(key: str, es: str, en: str, *, differ: tuple[str, str] | None = None) -> RuleText:
    d_es, d_en = differ or ("", "")
    return RuleText(key, es, en, differ is not None, d_es, d_en)


_CARDS_DIFFER = (
    "El proveedor no dice cómo cuenta cada casa las tarjetas: algunas cuentan solo amarillas, otras dan más peso a la roja o puntúan. "
    "Si tu casa cuenta distinto, la apuesta puede liquidarse distinto.",
    "The provider does not say how each house counts cards: some count yellows only, some weigh a red more, some score points. "
    "If your house counts differently, the bet can settle differently.")
_NO_PERIOD = ("El proveedor no entrega este dato por mitad: no se puede liquidar.",
              "The provider does not give this figure by half: it cannot be settled.")

TEXTS: Final[tuple[RuleText, ...]] = (
    _t("goals_ft@v1", "Goles a los 90 minutos. La prórroga y los penaltis no cuentan.",
       "Goals after 90 minutes. Extra time and penalties never count."),
    _t("goals_1h@v1", "Goles de la primera parte (marcador al descanso).", "Goals of the first half (the half-time score)."),
    _t("goals_2h@v1", "Goles de la segunda parte: los de los 90 minutos menos los del descanso.",
       "Goals of the second half: those after 90 minutes minus the half-time score."),
    _t("goals_halves@v1", "Ambas partes: marcador al descanso y goles de la segunda parte (para descanso/final y parte con más goles).",
       "Both halves: the half-time score and the goals of the second half (for half-time/full-time and highest scoring half)."),
    _t("corners_ft@v1", "Córneres del partido. Si hubo prórroga no se liquida: el proveedor no dice si su total incluye la media hora extra.",
       "Corners of the match. After extra time it is not settled: the provider does not say whether its total includes the extra half hour.",
       differ=("Algunas casas liquidan sobre los córneres de los 90 minutos y otras sobre el total con prórroga.",
               "Some houses settle on the corners of the 90 minutes and others on the total with extra time.")),
    _t("corners_1h@v1", "Córneres de la primera parte: sin dato en esta versión.", "Corners of the first half: no data in this version."),
    _t("corners_2h@v1", "Córneres de la segunda parte: sin dato en esta versión.", "Corners of the second half: no data in this version."),
    _t("corners_1h@v2", "Córneres de la primera parte según el proveedor. Solo se conoce si llegan las cuatro cifras del partido y las dos "
       "partes suman el total.", "Corners of the first half as the provider gives them. Known only when the four figures of the match came and "
       "the two halves add up to the total."),
    _t("corners_2h@v2", "Córneres de la segunda parte según el proveedor. Solo se conoce si llegan las cuatro cifras, las partes suman el "
       "total y no hubo prórroga.", "Corners of the second half as the provider gives them. Known only when the four figures came, the halves "
       "add up to the total and there was no extra time."),
    _t("cards_lines_ft@v1", "Tarjetas del partido: cada tarjeta mostrada cuenta una (cada amarilla y cada roja; la roja tras una segunda "
       "amarilla cuenta como la roja que es).", "Cards of the match: every card shown counts one (each yellow and each red; the red that "
       "follows a second yellow counts as the red it is).", differ=_CARDS_DIFFER),
    _t("cards_lines_1h@v1", "Tarjetas de la primera parte: cada tarjeta mostrada cuenta una. Solo con eventos clasificados.",
       "Cards of the first half: every card shown counts one. From the classified events only.", differ=_CARDS_DIFFER),
    _t("cards_lines_2h@v1", "Tarjetas de la segunda parte: cada tarjeta mostrada cuenta una. Solo con eventos clasificados.",
       "Cards of the second half: every card shown counts one. From the classified events only.", differ=_CARDS_DIFFER),
    _t("yellow_ft@v1", "Solo amarillas: cuenta la primera amarilla de un par; la roja que la sigue no.",
       "Yellow cards only: the first yellow of a pair counts; the red that follows does not.",
       differ=("Algunas casas cuentan también la segunda amarilla como amarilla.",
               "Some houses also count the second yellow as a yellow.")),
    _t("yellow_1h@v1", "Amarillas de la primera parte. Solo con eventos clasificados.", "Yellow cards of the first half. From the classified "
       "events only."),
    _t("yellow_2h@v1", "Amarillas de la segunda parte. Solo con eventos clasificados.", "Yellow cards of the second half. From the classified "
       "events only."),
    _t("red_ft@v1", "Expulsiones: rojas directas y la roja que sigue a una segunda amarilla.",
       "Dismissals: straight reds and the red that follows a second yellow."),
    _t("cards_points_ft@v1", "Puntos de tarjeta: 10 la amarilla, 25 la roja directa, 15 más por la roja tras segunda amarilla.",
       "Booking points: 10 a yellow, 25 a straight red, 15 more for the red that follows a second yellow.", differ=_CARDS_DIFFER),
    _t("shots_ft@v1", "Tiros totales del partido.", "Total shots of the match."),
    _t("shots_on_target_ft@v1", "Tiros a puerta del partido.", "Shots on target of the match."),
    _t("fouls_ft@v1", "Faltas cometidas.", "Fouls committed."),
    _t("offsides_ft@v1", "Fueras de juego.", "Offsides."),
    _t("saves_ft@v1", "Paradas del portero del equipo.", "Goalkeeper saves of the team."),
)
TEXT_BY_KEY: Final[Mapping[str, RuleText]] = {t.key: t for t in TEXTS}

if len(TEXT_BY_KEY) != len(TEXTS):  # pragma: no cover - import-time guard
    raise RuntimeError("two texts share a rule key")


def text_of(rule: Rule) -> RuleText:
    """The text of a rule; a rule without one is a bug the tests refuse, not a blank the reader sees."""
    return TEXT_BY_KEY[rule.key]


def card(rule: Rule, lang: str = "es") -> dict[str, Any]:
    """What a reader is shown of a rule: its key, the words, the mark and, when marked, how houses may differ."""
    t = text_of(rule)
    en = lang == "en"
    out: dict[str, Any] = {"rule": rule.key, "measure": rule.measure, "period": rule.period, "liquidable": rule.liquidable,
                           "text": t.en if en else t.es, "may_differ": t.may_differ}
    if t.may_differ:
        out["differ_note"] = t.differ_en if en else t.differ_es
    if not rule.liquidable and rule.reason == "no_period_data":
        out["text"] = f"{out['text']} {_NO_PERIOD[1] if en else _NO_PERIOD[0]}"
    return out


def cards(lang: str = "es", *, in_force: bool = True) -> list[dict[str, Any]]:
    """The card of each rule, in the order of ``RULES``; by default only the version in force of each measure."""
    from fbi.market.rules import rules_in_force

    rules: Iterable[Rule] = rules_in_force() if in_force else RULES
    return [card(r, lang) for r in rules]


# ── How often the conventions would grade differently ────────────────────────────────────────────────────────────────────────────────────

CONVENTIONS: Final = {
    "solo_amarillas": "yellow cards only (the red, and the red after a second yellow, count nothing)",
    "roja_doble": "a red counts two cards",
}


def _alt(total: int, yellow: int, red: int, name: str) -> int:
    return yellow if name == "solo_amarillas" else total + red


def discrepancy(groups: Iterable[tuple[int, int, int, int]], lines: tuple[float, ...] = CARD_LINES) -> dict[str, Any]:
    """From the matches grouped by (cards counted by PrediGol, yellows, reds, matches): per alternative convention, in how many matches the total
    differs and, per line, in how many the Over/Under would be graded the other way. Pure: no database."""
    rows = [(int(t), int(y), int(r), int(n)) for t, y, r, n in groups]
    matches = sum(n for *_, n in rows)
    out: dict[str, Any] = {"version": VERSION, "matches": matches, "lines": list(lines), "conventions": {}}
    for name in CONVENTIONS:
        total_differs = sum(n for t, y, r, n in rows if _alt(t, y, r, name) != t)
        per_line: dict[str, dict[str, Any]] = {}
        for line in lines:
            differs = sum(n for t, y, r, n in rows if (t > line) != (_alt(t, y, r, name) > line))
            per_line[str(line)] = {"differs": differs, "pct": round(differs / matches, 4) if matches else None}
        out["conventions"][name] = {"description": CONVENTIONS[name], "total_differs": total_differs,
                                    "total_differs_pct": round(total_differs / matches, 4) if matches else None, "by_line": per_line}
    return out


def conventions(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> dict[str, Any]:
    """``discrepancy`` over the finished, tracked matches of the window whose cards come from the classified events: the only ones whose
    yellows and reds are known one by one. One grouped query; read-only."""
    sql = (f"SELECT cards_lines_ft_home + cards_lines_ft_away, yellow_ft_home + yellow_ft_away, red_ft_home + red_ft_away, count(*) "
           f"FROM {OUTCOMES_VIEW} WHERE is_tracked AND cards_source = 'events' AND kickoff_at >= %(since)s AND kickoff_at < %(until)s "
           "AND cards_lines_ft_home IS NOT NULL AND cards_lines_ft_away IS NOT NULL AND yellow_ft_home IS NOT NULL "
           "AND yellow_ft_away IS NOT NULL AND red_ft_home IS NOT NULL AND red_ft_away IS NOT NULL GROUP BY 1, 2, 3")
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(sql, {"since": since, "until": until})
        rows = cur.fetchall()
    return discrepancy(rows)
