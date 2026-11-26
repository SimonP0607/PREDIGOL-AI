"""The eight tests of mathematical coherence of what PrediGol forecasts (plan RP-2.2, finding H04/H23, ``coherence-battery-v1``). Pure.

One match's figures go in (``Figure``: what a selection wins, what comes back, and the interval the model measured) and the violations of the
eight relations of section 11 of the plan come out. Each relation is a function with the tolerance the plan gives it:

    1  complementary events add up to one            over/under, both teams score, the two sides of a handicap, a double chance and its rest    1e-6
    2  exhaustive results add up to one              home, draw, away                                                                           1e-6
    3  lines are monotone                             over 1.5 cannot be below over 2.5; a larger handicap never wins less                       strict
    4  result, double chance and handicap coincide    1X is home plus draw, home -0.5 is home, home 0 is draw no bet                              1e-6
    5  totals and goals of each team coincide         the total is at least what either team scores, and at most both together                  0.001
    6  halves and the full match coincide             the match is at least what either half scores, and at most both together                   0.001
    7  Asian lines as five states                     win, half win, push, half loss, loss are a distribution and give the stored figure         1e-6
    8  the interval contains the figure               min <= figure <= max                                                                       strict

Tests 5 and 6 hold the NECESSARY conditions that the stored markets give (the joint distribution of two teams or two halves is not stored): the
total is at least each part, and if it passes a line L = k - 1/2 then one part passed m - 1/2 with m = ceil(k / 2), so it is at most the two parts
together at that line. A figure that breaks one cannot come from any single distribution of goals. A test with none of the figures it needs does not
run and says so (``Report.ran``): it never passes by absence. ``strict`` means exactly: equal is not a violation, nothing else is allowed.

A violation does not change a figure. ``check`` says which test, which selections and by how much; the nightly audit (``scripts/ia_coherence_audit.py``)
keeps the report and links each violation to the seal of the figure it came from; ``publishable`` is what keeps a set with a violation from being shown.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import pairwise
from math import ceil
from typing import Final

VERSION: Final = "coherence-battery-v1"

TOL_EXACT: Final = 0.000001
TOL_LOOSE: Final = 0.001
TOLERANCES: Final[dict[int, float | None]] = {1: TOL_EXACT, 2: TOL_EXACT, 3: None, 4: TOL_EXACT, 5: TOL_LOOSE, 6: TOL_LOOSE, 7: TOL_EXACT, 8: None}
"""The plan's tolerances; ``None`` is strict."""
NAMES: Final[dict[int, str]] = {
    1: "complementarias suman uno", 2: "resultados exhaustivos suman uno", 3: "monotonía de líneas",
    4: "resultado, doble oportunidad y hándicap coinciden", 5: "totales y goles por equipo coinciden",
    6: "mitades y partido completo coinciden", 7: "líneas asiáticas como estados", 8: "el intervalo contiene la cifra"}

Key = tuple[str, str, Decimal]
"""(market, selection, the selection's own line)."""
ZERO: Final = Decimal(0)
TOTAL: Final = "OU"
TEAMS: Final = ("OU_HOME", "OU_AWAY")
HALVES: Final = ("OU_1H", "OU_2H")
SIDES: Final = (("OU", "Over", "Under"), ("OU_HOME", "Over", "Under"), ("OU_AWAY", "Over", "Under"), ("OU_1H", "Over", "Under"),
                ("OU_2H", "Over", "Under"), ("BTTS", "Yes", "No"), ("BTTS_1H", "Yes", "No"), ("BTTS_2H", "Yes", "No"), ("DNB", "Home", "Away"))
RESULT_MARKETS: Final = ("1X2", "1X2_1H", "1X2_2H")
DOUBLE_CHANCE_REST: Final = (("1X", "Away"), ("X2", "Home"), ("12", "Draw"))
"""A double chance and the result that is left out of it."""


@dataclass(frozen=True, slots=True)
class Figure:
    """One selection's figure: what it wins, the share of the stake that comes back, and the interval the model measured."""

    market: str
    selection: str
    line: Decimal
    win: float
    push: float = 0.0
    lo: float | None = None
    hi: float | None = None

    @property
    def key(self) -> Key:
        return self.market, self.selection, self.line

    @property
    def lose(self) -> float:
        return 1.0 - self.win - self.push


@dataclass(frozen=True, slots=True)
class Violation:
    test: int
    rule: str
    detail: str
    gap: float
    """How far past the tolerance (always above zero)."""
    selections: tuple[Key, ...] = ()

    def as_json(self) -> dict[str, object]:
        return {"test": self.test, "name": NAMES[self.test], "rule": self.rule, "detail": self.detail, "gap": self.gap,
                "selections": [[m, s, str(line)] for m, s, line in self.selections]}


@dataclass(frozen=True, slots=True)
class Report:
    violations: tuple[Violation, ...]
    ran: dict[int, int] = field(default_factory=dict)
    """How many comparisons each test made: a test with 0 had nothing to compare and proves nothing for this set."""

    @property
    def publishable(self) -> bool:
        return not self.violations

    def by_test(self) -> dict[int, int]:
        out = dict.fromkeys(NAMES, 0)
        for v in self.violations:
            out[v.test] += 1
        return out

    def as_json(self) -> dict[str, object]:
        return {"version": VERSION, "publishable": self.publishable, "by_test": self.by_test(), "ran": dict(self.ran),
                "violations": [v.as_json() for v in self.violations]}


class _Run:
    """The comparisons of one test: counts them and keeps the violations."""

    def __init__(self, test: int) -> None:
        self.test = test
        self.n = 0
        self.found: list[Violation] = []
        self.tol = TOLERANCES[test] or 0.0

    def _flag(self, rule: str, text: str, gap: float, keys: tuple[Figure, ...]) -> None:
        self.found.append(Violation(self.test, rule, text, gap, tuple(k.key for k in keys)))

    def equal(self, rule: str, detail: str, value: float, expected: float, *keys: Figure) -> None:
        self.n += 1
        gap = abs(value - expected) - self.tol
        if gap > 0:
            self._flag(rule, f"{detail}: {value:.9f} vs {expected:.9f}", gap, keys)

    def at_most(self, rule: str, detail: str, small: float, big: float, *keys: Figure) -> None:
        """``small <= big`` within the tolerance (exactly when strict)."""
        self.n += 1
        gap = small - big - self.tol
        if gap > 0:
            self._flag(rule, f"{detail}: {small:.9f} > {big:.9f}", gap, keys)


def _index(figures: Iterable[Figure]) -> dict[Key, Figure]:
    return {f.key: f for f in figures}


def t1_complementary(figures: Sequence[Figure]) -> _Run:
    """Two sides of one event, pushes included, add up to one; and the stake that comes back is the same on both."""
    r, idx = _Run(1), _index(figures)
    for market, a, b in SIDES:
        for (m, s, line), fa in sorted(idx.items()):
            fb = idx.get((market, b, line)) if (m, s) == (market, a) else None
            if fb is not None:
                r.equal("sides_add_up", f"{market} {a}+{b} at {line}", fa.win + fb.win + fa.push, 1.0, fa, fb)
                r.equal("push_is_the_same", f"{market} {line} push", fa.push, fb.push, fa, fb)
    for (m, s, line), fa in sorted(idx.items()):  # a handicap's two sides sit at opposite lines
        fb = idx.get(("AH", "Away", -line + ZERO)) if (m, s) == ("AH", "Home") else None
        if fb is not None:
            r.equal("sides_add_up", f"AH Home {line:+} + Away {-line:+}", fa.win + fb.win + fa.push, 1.0, fa, fb)
            r.equal("push_is_the_same", f"AH {line:+} push", fa.push, fb.push, fa, fb)
    for sel, rest in DOUBLE_CHANCE_REST:
        dc, other = idx.get(("DC", sel, ZERO)), idx.get(("1X2", rest, ZERO))
        if dc is not None and other is not None:
            r.equal("double_chance_and_the_rest", f"DC {sel} + {rest}", dc.win + other.win, 1.0, dc, other)
    return r


def t2_exhaustive(figures: Sequence[Figure]) -> _Run:
    r, idx = _Run(2), _index(figures)
    for market in RESULT_MARKETS:
        parts = [idx.get((market, s, ZERO)) for s in ("Home", "Draw", "Away")]
        present = [p for p in parts if p is not None]
        if len(present) == 3:
            r.equal("results_add_up", f"{market} Home+Draw+Away", sum(p.win for p in present), 1.0, *present)
    return r


def t3_monotone(figures: Sequence[Figure]) -> _Run:
    """Along a market's lines the figure only goes one way. Strict: it may equal its neighbour, never lie on the wrong side of it. Over and a
    handicap win more as the line is easier (a lower total, a higher handicap for the selection), Under the opposite."""
    r = _Run(3)
    groups: dict[tuple[str, str], list[Figure]] = defaultdict(list)
    for f in figures:
        if f.market in (TOTAL, *TEAMS, *HALVES, "AH"):
            groups[(f.market, f.selection)].append(f)
    for (market, selection), fs in sorted(groups.items()):
        ordered = sorted(fs, key=lambda f: f.line)
        rising = market == "AH" or selection == "Under"  # the figure goes up with the line
        for lo, hi in pairwise(ordered):
            small, big = (lo, hi) if rising else (hi, lo)
            r.at_most("monotone_lines", f"{market} {selection}: {small.line:+} cannot win more than {big.line:+}", small.win, big.win, lo, hi)
    return r


def t4_result_double_chance_handicap(figures: Sequence[Figure]) -> _Run:
    r, idx = _Run(4), _index(figures)
    h, d, a = (idx.get(("1X2", s, ZERO)) for s in ("Home", "Draw", "Away"))
    if h is not None and d is not None and a is not None:
        for sel, parts in (("1X", (h, d)), ("X2", (d, a)), ("12", (h, a))):
            dc = idx.get(("DC", sel, ZERO))
            if dc is not None:
                r.equal("dc_is_the_sum", f"DC {sel}", dc.win, sum(p.win for p in parts), dc, *parts)
        for side, own in (("Home", h), ("Away", a)):
            dnb = idx.get(("DNB", side, ZERO))
            if dnb is not None:
                r.equal("dnb_wins_as_the_result", f"DNB {side} win", dnb.win, own.win, dnb, own)
                r.equal("dnb_returns_on_a_draw", f"DNB {side} push", dnb.push, d.win, dnb, d)
            for line, expected in ((Decimal("-0.5"), own.win), (Decimal("0.5"), own.win + d.win)):
                ah = idx.get(("AH", side, line))
                if ah is not None:
                    r.equal("half_goal_is_the_result", f"AH {side} {line:+}", ah.win, expected, ah, own, d)
    for side in ("Home", "Away"):
        dnb, ah0 = idx.get(("DNB", side, ZERO)), idx.get(("AH", side, ZERO))
        if dnb is not None and ah0 is not None:
            r.equal("ah0_is_dnb", f"AH {side} 0 win", ah0.win, dnb.win, ah0, dnb)
            r.equal("ah0_is_dnb", f"AH {side} 0 push", ah0.push, dnb.push, ah0, dnb)
    return r


def _is_half_line(line: Decimal) -> bool:
    return abs(line * 2) % 2 == 1


def _bounds(r: _Run, parts: tuple[str, ...], what: str, idx: dict[Key, Figure]) -> None:
    """The total (``OU`` Over/Under at a half line) against its parts: the two necessary conditions, with the parts' lines they imply."""
    for (m, s, line), total in sorted(idx.items()):
        if m != TOTAL or s not in ("Over", "Under") or not _is_half_line(line):
            continue
        found = [idx.get((p, s, line)) for p in parts]
        for part in (x for x in found if x is not None):
            if s == "Over":
                r.at_most(f"total_covers_each_{what}", f"Over {line}: {part.market} <= {TOTAL}", part.win, total.win, part, total)
            else:
                r.at_most(f"total_within_each_{what}", f"Under {line}: {TOTAL} <= {part.market}", total.win, part.win, total, part)
        if s != "Over":
            continue
        m_goals = ceil((line + Decimal("0.5")) / 2)  # passing the total means one part scored m or more
        pair = [idx.get((p, "Over", Decimal(m_goals) - Decimal("0.5"))) for p in parts]
        if all(x is not None for x in pair):
            both = [x for x in pair if x is not None]
            r.at_most(f"total_within_both_{what}s", f"Over {line}: {TOTAL} <= the two {what}s at {m_goals - 0.5}", total.win, sum(x.win for x in both),
                      total, *both)


def t5_totals_and_teams(figures: Sequence[Figure]) -> _Run:
    r = _Run(5)
    _bounds(r, TEAMS, "team", _index(figures))
    return r


def t6_halves_and_match(figures: Sequence[Figure]) -> _Run:
    r = _Run(6)
    _bounds(r, HALVES, "half", _index(figures))
    return r


ASIAN_STATES: Final = ("win", "half_win", "push", "half_loss", "loss")
STEP: Final = Decimal("0.25")


def is_quarter(line: Decimal) -> bool:
    return abs(line * 4) % 2 == 1


def quarter_states(easier: Figure, harder: Figure) -> dict[str, float]:
    """The five states of a quarter line from the two neighbouring lines it is the half stake on (the selection's own lines: the easier one is the
    higher). The neighbours are nested events half a goal apart, so what each state weighs follows from their marginals: it wins when the harder
    one wins, half wins where the easier one wins and the harder one does not, half loses where the harder one loses and the easier one does not,
    and loses when the easier one loses. There is no whole push on a quarter line."""
    return {"win": harder.win, "half_win": easier.win - harder.win, "push": 0.0, "half_loss": harder.lose - easier.lose, "loss": easier.lose}


def t7_asian_states(figures: Sequence[Figure]) -> _Run:
    """Every Asian line is a distribution over its five states. A whole or half line has win, push and loss; a quarter line has the five that its
    two neighbours give, and the figure stored for it must be what those five pay (win plus half the half wins, push of half the half states)."""
    r, idx = _Run(7), _index(figures)
    for (m, s, line), f in sorted(idx.items()):
        if m != "AH":
            continue
        if is_quarter(line):
            easier, harder = idx.get((m, s, line + STEP)), idx.get((m, s, line - STEP))
            if easier is None or harder is None:
                continue
            states = quarter_states(easier, harder)
            keys: tuple[Figure, ...] = (f, easier, harder)
        else:
            states = {"win": f.win, "half_win": 0.0, "push": f.push, "half_loss": 0.0, "loss": f.lose}
            keys = (f,)
        r.n += 1
        worst = min(states.values())
        off = abs(sum(states.values()) - 1.0)
        if worst < -r.tol or off > r.tol:
            r._flag("states_are_a_distribution", f"AH {s} {line:+}: " + ", ".join(f"{k} {v:.6f}" for k, v in states.items()),
                    max(-worst, off) - r.tol, keys)
            continue
        if is_quarter(line):
            r.equal("stored_is_what_the_states_pay", f"AH {s} {line:+} win", f.win, states["win"] + states["half_win"] / 2, *keys)
            r.equal("stored_is_what_the_states_pay", f"AH {s} {line:+} push", f.push, (states["half_win"] + states["half_loss"]) / 2, *keys)
    return r


def t8_interval(figures: Sequence[Figure]) -> _Run:
    r = _Run(8)
    for f in figures:
        if f.lo is None and f.hi is None:
            continue
        name = f"{f.market} {f.selection} {f.line}"
        if f.lo is None or f.hi is None:
            r.n += 1
            r._flag("interval_is_a_pair", f"{name}: only one end of the interval", 1.0, (f,))
            continue
        r.at_most("figure_above_the_minimum", f"{name}: minimum <= figure", f.lo, f.win, f)
        r.at_most("figure_below_the_maximum", f"{name}: figure <= maximum", f.win, f.hi, f)
    return r


TESTS: Final = (t1_complementary, t2_exhaustive, t3_monotone, t4_result_double_chance_handicap, t5_totals_and_teams, t6_halves_and_match,
                t7_asian_states, t8_interval)


def check(figures: Iterable[Figure]) -> Report:
    """Run the eight tests over one match's figures."""
    items = list(figures)
    found: list[Violation] = []
    ran: dict[int, int] = {}
    for test in TESTS:
        run = test(items)
        found.extend(run.found)
        ran[run.test] = run.n
    return Report(tuple(sorted(found, key=lambda v: (v.test, v.rule, v.detail))), ran)


def publishable(figures: Iterable[Figure]) -> bool:
    """Whether a set of figures may be shown: not one violation. The violation does not change a figure; it keeps the set from being published."""
    return check(figures).publishable


__all__ = ["NAMES", "TESTS", "TOLERANCES", "VERSION", "Figure", "Report", "Violation", "check", "publishable", "quarter_states"]
