"""«Por qué hay valor», los factores y los puntos clave de la lectura de un partido (plan de cierre UX, 2.1): three sections added
to the structured reading (``fbi.api.services.reading``), written like it from what is already stored - no AI is called, nothing
is estimated, and a datum that is missing is left out, never filled.

    value       Why a pick PrediGol published for this match has value: the probability PrediGol gives the selection against
                the one the market gives it, and the price against the fair price of each. Only for a pick a reader may see
                (a RECOMMENDED one, the same the match's Picks tab shows: UX-002, «solo verde»; an evaluation pick never
                gets here, not even in the owner's preview). With no such pick the section does not exist: this is not
                «there is value» written for a match that has none.
    factors     The facts of the reading's own sections that stand out by the rules the reading already applies (what a side is
                playing for, the first leg, key absences, a long run, a market that moved), copied as they are.
    key_points  Three to five of them, in the order a reader needs them - what limits the reading, what PrediGol expects, why
                there is value, the factors, the main risk. Never padded: a match with little data has fewer, and one with
                no data says so (the reading's risks never are empty).

The numbers of ``value`` are the pick's own, the ones its card and its explanation already show (``PickCard``: PrediGol's
calibrated probability, the market's de-vigged one, the best price now - or, once the match started, the price it was taken at).
The fair prices are 1 / probability, as the glossary defines them. Nothing here changes a pick, a probability or a threshold.

These sections are derived from the six of ``reading`` and are NOT part of what the narrative of PrediGol's AI reads or is hashed
from (``reading.reading_hash``): the AI tells context and risks and is forbidden to say «valor» or «pick» (plan 2.4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Final

from fbi.api.contracts.product import PickCard, StartedPick
from fbi.api.contracts.reading import MatchReading, ReadingFact, ReadingSection
from fbi.api.envelope import Envelope
from fbi.api.repositories import Conn
from fbi.api.services import product

EXTRA_KEYS: Final = ("key_points", "value", "factors")
PICKS_HOURS: Final = 168
"""How far ahead the picks of the match are looked for: the longest window the picks board accepts (a match has no pick before
the day it is played, in practice)."""
MAX_VALUE: Final = 3
MAX_FACTORS: Final = 6
MAX_POINTS: Final = 5
KEY_VALUE: Final = 2
KEY_FACTORS: Final = 2
FACTOR_CODES: Final = ("stakes_pressure", "first_leg", "tie_outlook", "key_absences", "streak_unbeaten", "streak_winless",
                       "market_moved")
"""The facts of the reading that stand out, in this order. Each one is already chosen by the reading's own rule (a streak of
four or more, a move of two points or more, a key player out...); a «settled» pressure - nothing to play for - does not."""


def _share(p: Decimal | None) -> float | None:
    return None if p is None else round(float(p), 3)


def _fair(p: Decimal | None) -> float | None:
    """The fair price of a probability: 1 / p (the glossary's «cuota justa» for the market's, «cuota según PrediGol» for the
    model's)."""
    return None if p is None or p <= 0 else round(1 / float(p), 2)


def _facts(*, pick_id: int, market: str, selection: str, line: Decimal, home: str, away: str, p_model: Decimal,
           p_market: Decimal | None, odds: Decimal | None, taken: bool) -> list[ReadingFact]:
    ref = f"pick:{pick_id}"
    who: dict[str, str | float] = {"market": market, "selection": selection, "line": float(line), "home": home,
                                   "away": away}
    out: list[ReadingFact] = []
    if p_market is not None:
        out.append(ReadingFact(code="value_pick", ref=ref,
                               params={**who, "p_model": _share(p_model), "p_market": _share(p_market)}))
    if odds is not None:
        out.append(ReadingFact(code="value_price", ref=ref,
                               params={**who, "odds": round(float(odds), 2), "fair_market": _fair(p_market),
                                       "fair_model": _fair(p_model), "taken": taken}))
    return out


def _card(c: PickCard) -> list[ReadingFact]:
    return _facts(pick_id=c.pick_id, market=c.market_key, selection=c.selection, line=c.line, home=c.home.name,
                  away=c.away.name, p_model=c.p_model, p_market=c.p_market, odds=c.best_odds, taken=False)


def _started(s: StartedPick) -> list[ReadingFact]:
    return _facts(pick_id=s.pick_id, market=s.market_key, selection=s.selection, line=s.line, home=s.home.name,
                  away=s.away.name, p_model=s.p_model, p_market=s.p_market, odds=s.odds_taken, taken=True)


def value_facts(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> list[ReadingFact]:
    """The value facts of the picks a reader is shown for this match - the board's own cut, so this is never more than the
    match's Picks tab says - before kick-off at the best price now, afterwards as the pick was taken."""
    env = product.picks_board(conn, include_shadow=False, competition_id=None, market=None, min_odds=None, max_odds=None,
                              hours=PICKS_HOURS, at=at, fixture_id=fixture_id)
    board = env.data
    if board is None:
        return []
    out: list[ReadingFact] = []
    for c in board.picks[:MAX_VALUE]:
        out += _card(c)
    for s in board.started[:max(0, MAX_VALUE - len(board.picks))]:
        out += _started(s)
    return out


def factors(sections: Mapping[str, Sequence[ReadingFact]]) -> list[ReadingFact]:
    """The reading's facts that stand out (``FACTOR_CODES``), copied as they are, in that order."""
    found = [f for code in FACTOR_CODES for key in ("context", "data", "market") for f in sections.get(key, ())
             if f.code == code and not (code == "stakes_pressure" and f.params.get("pressure") == "settled")]
    return found[:MAX_FACTORS]


def key_points(sections: Mapping[str, Sequence[ReadingFact]], value: Sequence[ReadingFact],
               standing: Sequence[ReadingFact]) -> list[ReadingFact]:
    """Three to five points, never padded, in the order a reader needs them (see the module's docstring)."""
    wanted: list[ReadingFact] = []
    wanted += [f for f in sections.get("conclusion", ()) if f.code == "description_only"][:1]
    wanted += [f for f in sections.get("summary", ()) if f.code in ("expected_result", "forecast_missing")][:1]
    wanted += [f for f in value if f.code == "value_pick"][:KEY_VALUE]
    wanted += list(standing[:KEY_FACTORS])
    wanted += list(sections.get("risks", ()))[:1]
    out: list[ReadingFact] = []
    for f in wanted:
        if f not in out:
            out.append(f)
    return out[:MAX_POINTS]


def extras(conn: Conn, sections: Sequence[ReadingSection], *, fixture_id: int,
           at: datetime | None = None) -> list[ReadingSection]:
    """The sections derived from a reading's six: ``key_points``, ``value`` and ``factors`` - each only when it has facts."""
    by_key: dict[str, Sequence[ReadingFact]] = {s.key: s.facts for s in sections}
    value = value_facts(conn, fixture_id, at=at)
    standing = factors(by_key)
    points = key_points(by_key, value, standing)
    out: list[ReadingSection] = []
    if points:
        out.append(ReadingSection(key="key_points", facts=points))
    if value:
        out.append(ReadingSection(key="value", facts=value))
    if standing:
        out.append(ReadingSection(key="factors", facts=standing))
    return out


def attach(conn: Conn, found: Envelope[MatchReading | None], *, at: datetime | None = None) -> Envelope[MatchReading | None]:
    """The reading as the route answers it: its six sections, then the derived ones. Nothing to add to a reading that is not
    shown (``not_available``) - the owner's switch hides these sections with it."""
    reading = found.data
    if reading is None:
        return found
    derived = extras(conn, reading.sections, fixture_id=reading.fixture_id, at=at)
    if not derived:
        return found
    return found.model_copy(update={"data": reading.model_copy(update={"sections": [*reading.sections, *derived]})})
