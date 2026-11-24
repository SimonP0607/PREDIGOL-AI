"""What a bet is graded ON: the registry of settlement rules and the decision of which one applies to a bet (plan F9).

A rule is ONE measure of a finished match - the goals of the first half, the corners of the match, the cards counted as lines -
read from the columns of ``market.fixture_outcomes`` that it names, in one convention and one version. The rule does not grade (that is
the work of settlement, F11); it says what the number is that a line is compared with, and whether that number exists at all.

    Rule ........ a measure + a version + the columns it reads (``RULES``; written to ``market.settlement_rules`` by
                  ``fbi.market.catalogue.sync``, where a row is never edited)
    Decision .... for one bet (``explain``): the rule that grades it, or why none can (``reason``)

Why the cards have several rules. Houses do not count cards the same way: some count each card shown, some count points (10 for a
yellow, 25 for a red), some leave out the red that follows a second yellow. The provider's bet does not say which house's convention it
carries (``Cards Over/Under`` arrives from three houses at the median), so the conventions are separate, versioned rules and the bet is
linked to the one that is the best reading of its name; the matrix reports how many matches the conventions would grade differently
(``fbi.market.matrix``). A convention is never changed in place: a new reading is ``cards_lines_ft@v2`` and the old rule keeps its row.

Why a rule can be "not liquidable". The provider gives corners, shots, fouls, offsides and saves only as totals of the match. A bet on the
corners of ONE HALF has nothing to be graded on in anything we keep, so its rule exists with ``liquidable = False`` and the reason
``no_period_data``: the absence is written down (and tested), so a model of it is never built on a number that cannot exist.

That premise was wrong for corners (PM-05-03): the provider gives them by half (``/fixtures/statistics?half=true``) and PM-05-01 keeps them.
The first version of those two rules is NOT edited - it still says what it said, and it stays in force while ``FBI_CORNERS_BY_HALF`` is off. A
second version (``corners_1h@v2``, ``corners_2h@v2``) reads the columns ``market.fixture_outcomes`` got in migration 0176, known only when the
four figures came and the halves add up to the match total. ``RULES_BY_MEASURE`` answers with the version in force; ``RULES`` and
``RULES_BY_KEY`` hold every version, because a bet already linked to ``@v1`` keeps its key.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from fbi.odds.quote_taxonomy import BetSpec

OUTCOMES_VIEW: Final = "market.fixture_outcomes"

CORNERS_BY_HALF: Final = "FBI_CORNERS_BY_HALF"
"""PM-05-03: the corners of a half are graded with ``corners_1h@v2`` and ``corners_2h@v2`` (read from the provider's statistics by half) instead
of being «not available». OFF while the line is absent: the bets stay linked to ``@v1`` and nothing offers or grades them. The rules of the new
version are written to ``market.settlement_rules`` either way (a row is only ever added); the switch decides which version is IN FORCE."""

# Reasons a bet has no rule (``Decision.reason``); "ok" is the reason of a rule that grades.
OK: Final = "ok"
NO_PERIOD_DATA: Final = "no_period_data"  # the statistic exists only as a total of the match
NO_DATA: Final = "no_data"  # nothing we keep says how the match ended in this respect
NOT_UNDERSTOOD: Final = "not_understood"  # the bet's selections have not been read (kind unspecified)
KIND_NOT_GRADED: Final = "kind_not_graded"  # a kind of bet that does not apply to this measure
PLAYER_LEVEL: Final = "player_level"  # graded on one player's figures, not on the match's
OUT_OF_SCOPE: Final = "out_of_scope"  # timing, specials, other sports: outside the plan's families

# The kinds of selection a grader can read (``fbi.odds.quote_taxonomy`` ``kind``).
GRADABLE_KINDS: Final = frozenset({
    "over_under", "one_x_two", "double_chance", "draw_no_bet", "both_teams_score", "asian_handicap", "odd_even",
    "half_time_full_time", "highest_scoring_half",
})
_GOALS_ONLY_KINDS: Final = frozenset({"both_teams_score", "half_time_full_time", "highest_scoring_half"})


@dataclass(frozen=True, slots=True)
class Rule:
    measure: str
    version: int
    family: str
    period: str
    convention: str
    columns: tuple[str, ...]
    reason: str = OK
    note: str = ""
    switch: str | None = None
    """The environment switch a version needs to be in force (None: always). Not stored: ``market.settlement_rules`` holds what a rule IS,
    the code decides which version applies."""

    @property
    def key(self) -> str:
        return f"{self.measure}@v{self.version}"

    @property
    def liquidable(self) -> bool:
        return bool(self.columns)


def _pair(stem: str) -> tuple[str, str]:
    return f"{stem}_home", f"{stem}_away"


RULES: Final[tuple[Rule, ...]] = (
    # ── goals: the 90-minute score and its two halves (the half-time score is stored for ~98 % of finished matches)
    Rule("goals_ft", 1, "goals", "FT", "score after 90 minutes (extra time and penalties never count)", _pair("goals_ft")),
    Rule("goals_1h", 1, "goals_half", "1H", "half-time score", _pair("goals_1h")),
    Rule("goals_2h", 1, "goals_half", "2H", "goals after 90 minutes minus the half-time score", _pair("goals_2h")),
    Rule("goals_halves", 1, "goals_half", "FT", "both halves: the half-time score and the goals of the second half",
         (*_pair("goals_1h"), *_pair("goals_2h")), note="HT/FT, highest scoring half and the like read both halves."),
    # ── corners: totals of the match only (the provider gives no corners by half)
    Rule("corners_ft", 1, "corners", "FT", "corners of the match (NULL after extra time: the provider does not say whether its "
         "total includes the extra half hour)", _pair("corners_ft")),
    Rule("corners_1h", 1, "corners", "1H", "not available", (), NO_PERIOD_DATA,
         "The provider gives corners as a total of the match, never by half: a bet on the corners of the first half cannot be graded."),
    Rule("corners_2h", 1, "corners", "2H", "not available", (), NO_PERIOD_DATA,
         "The provider gives corners as a total of the match, never by half: a bet on the corners of the second half cannot be graded."),
    # ── corners by half, version 2 (PM-05-03): the provider DOES give them, in ``/fixtures/statistics?half=true`` (``statistics_1h`` and
    #    ``statistics_2h``, kept in core.fixture_team_stats_period by PM-05-01). Version 1 above stays as it was written: a rule is never edited.
    Rule("corners_1h", 2, "corners", "1H", "corners of the first half, as the provider gives them for that half; known only when the four "
         "figures of the match (both teams, both halves) came and the two halves add up to the match total", _pair("corners_1h"),
         note="NULL when a figure is missing or the halves do not add up to the total: a half is never graded on a figure that contradicts "
              "the match's own.", switch=CORNERS_BY_HALF),
    Rule("corners_2h", 2, "corners", "2H", "corners of the second half, as the provider gives them for that half; known only when the four "
         "figures came and the halves add up to the match total, and never after extra time (the provider does not say whether its second "
         "half includes the extra half hour)", _pair("corners_2h"),
         note="NULL after extra time, when a figure is missing or when the halves do not add up to the total.", switch=CORNERS_BY_HALF),
    # ── cards: each convention is its own rule (see the module docstring)
    Rule("cards_lines_ft", 1, "cards", "FT", "every card shown counts one: each yellow and each red, and the red that follows a "
         "second yellow counts as the red it is", _pair("cards_lines_ft"),
         note="The convention of the houses behind 'Cards Over/Under' is not stated by the provider."),
    Rule("cards_lines_1h", 1, "cards", "1H", "every card shown in the first half counts one", _pair("cards_lines_1h"),
         note="From the classified events only (the classified events of the match): the period of a card is not in the statistics."),
    Rule("cards_lines_2h", 1, "cards", "2H", "every card shown in the second half counts one", _pair("cards_lines_2h"),
         note="From the classified events only (the classified events of the match): the period of a card is not in the statistics."),
    Rule("yellow_ft", 1, "cards", "FT", "yellow cards only (the first yellow of a pair counts; the red that follows does not)",
         _pair("yellow_ft")),
    Rule("yellow_1h", 1, "cards", "1H", "yellow cards shown in the first half", _pair("yellow_1h"),
         note="From the classified events only."),
    Rule("yellow_2h", 1, "cards", "2H", "yellow cards shown in the second half", _pair("yellow_2h"),
         note="From the classified events only."),
    Rule("red_ft", 1, "cards", "FT", "dismissals: straight reds and the red that follows a second yellow", _pair("red_ft")),
    Rule("cards_points_ft", 1, "cards", "FT", "booking points: 10 a yellow, 25 a straight red, 15 more for the red that follows a "
         "second yellow", _pair("cards_points_ft"), note="From the classified events only. No bet of the provider says it uses points."),
    # ── shots, fouls, offsides, saves: totals of the match
    Rule("shots_ft", 1, "shots", "FT", "total shots of the match", _pair("shots_ft")),
    Rule("shots_on_target_ft", 1, "shots", "FT", "shots on target of the match", _pair("shots_on_target_ft")),
    Rule("fouls_ft", 1, "fouls", "FT", "fouls committed", _pair("fouls_ft")),
    Rule("offsides_ft", 1, "offsides", "FT", "offsides", _pair("offsides_ft")),
    Rule("saves_ft", 1, "saves", "FT", "goalkeeper saves of the team", _pair("saves_ft")),
)

RULES_BY_KEY: Final[dict[str, Rule]] = {r.key: r for r in RULES}
if len(RULES_BY_KEY) != len(RULES):  # pragma: no cover - import-time guard
    raise RuntimeError("two rules share a key: a changed convention is a new VERSION of the measure, written as a new key")


def switch_on(name: str | None, env: Mapping[str, str] | None = None) -> bool:
    """A rule's switch: None is always on; any other is on only when the line says 1, on, true or yes (off by default)."""
    if name is None:
        return True
    e = os.environ if env is None else env
    return e.get(name, "").strip().lower() in ("1", "on", "true", "yes")


class RulesInForce(Mapping[str, Rule]):
    """The rule each measure is graded with NOW: the highest version whose switch is on. Version 1 of every measure has no switch, so a
    measure always has a rule; a new version born behind a switch changes nothing until the switch is turned on. Read at each lookup (the
    environment, not an import-time copy), so a worker started with the switch on and an API started without it each say what they use."""

    def __init__(self, rules: tuple[Rule, ...]) -> None:
        by_measure: dict[str, list[Rule]] = {}
        for r in rules:
            by_measure.setdefault(r.measure, []).append(r)
        self._versions = {m: sorted(rs, key=lambda r: -r.version) for m, rs in by_measure.items()}
        for m, rs in self._versions.items():
            if len({r.version for r in rs}) != len(rs) or all(r.switch is not None for r in rs):  # pragma: no cover - import-time guard
                raise RuntimeError(f"measure {m}: two rules share a version, or no version is in force without a switch")

    def __getitem__(self, measure: str) -> Rule:
        for r in self._versions[measure]:
            if switch_on(r.switch):
                return r
        raise KeyError(measure)  # pragma: no cover - the guard above keeps a switchless version of every measure

    def __iter__(self) -> Iterator[str]:
        return iter(self._versions)

    def __len__(self) -> int:
        return len(self._versions)


RULES_BY_MEASURE: Final[Mapping[str, Rule]] = RulesInForce(RULES)


def rules_in_force() -> tuple[Rule, ...]:
    """The rules that grade today, one per measure, in the order of ``RULES``: what a reader of «which measures can be graded» lists. The
    measurements of coverage read every version in ``RULES`` instead - a figure measured is not a bet offered."""
    return tuple(RULES_BY_MEASURE[m] for m in dict.fromkeys(r.measure for r in RULES))


@dataclass(frozen=True, slots=True)
class Decision:
    """What settles a bet: ``rule`` is the rule that grades it, or None with the ``reason`` none does."""

    rule: Rule | None
    reason: str
    measure: str | None = None

    @property
    def liquidable(self) -> bool:
        return self.rule is not None and self.rule.liquidable


def _measure(spec: BetSpec) -> tuple[str | None, str]:
    """The measure a bet compares its line with, or (None, reason). Reads the family, the period and, for cards and shots, the name."""
    family, period = spec.family, spec.period
    low = spec.name.lower()
    if family in ("result", "goals"):
        return ("goals_ft", OK) if period == "FT" else (None, NO_DATA)
    if family == "goals_half":
        if period == "1H":
            return "goals_1h", OK
        if period == "2H":
            return "goals_2h", OK
        return ("goals_halves", OK) if period == "FT" else (None, NO_DATA)
    if family == "corners":
        stem = "corners"
    elif family == "cards":
        if period in ("INTERVAL", "OTHER"):
            return None, NO_PERIOD_DATA
        if "booking" in low:
            stem = "cards_points"
            if period != "FT":
                return None, NO_PERIOD_DATA
        elif "yellow" in low:
            stem = "yellow"
        elif "red" in low:
            if period != "FT":
                return None, NO_PERIOD_DATA
            stem = "red"
        else:
            stem = "cards_lines"
    elif family == "shots":
        if period != "FT":
            return None, NO_PERIOD_DATA
        return ("shots_on_target_ft" if ("ongoal" in low.replace(" ", "") or "on target" in low or "ontarget" in low
                                          or "on goal" in low) else "shots_ft"), OK
    elif family in ("fouls", "offsides", "saves"):
        if period != "FT":
            return None, NO_PERIOD_DATA
        return f"{family}_ft", OK
    elif family == "players":
        return None, PLAYER_LEVEL
    elif family == "tackles":
        return None, NO_DATA
    else:  # timing, special, advance, other_sport, unclassified
        return None, OUT_OF_SCOPE
    suffix = {"FT": "ft", "1H": "1h", "2H": "2h"}.get(period)
    if suffix is None:
        return None, NO_PERIOD_DATA
    return f"{stem}_{suffix}", OK


def explain(spec: BetSpec) -> Decision:
    """The rule that grades a bet, or the reason no rule can. The measure is resolved first (a bet on the corners of a half is
    NO_PERIOD_DATA whether or not its selections were read), then the kind of selection."""
    measure, reason = _measure(spec)
    if measure is None:
        return Decision(None, reason)
    rule = RULES_BY_MEASURE.get(measure)
    if rule is None:
        return Decision(None, NO_DATA, measure)
    if not rule.liquidable:
        return Decision(rule, rule.reason, measure)
    if spec.kind == "unspecified":
        return Decision(None, NOT_UNDERSTOOD, measure)
    if spec.kind not in GRADABLE_KINDS:
        return Decision(None, KIND_NOT_GRADED, measure)
    if spec.kind in _GOALS_ONLY_KINDS and rule.family not in ("goals", "goals_half"):
        return Decision(None, KIND_NOT_GRADED, measure)
    if spec.kind in ("half_time_full_time", "highest_scoring_half") and measure != "goals_halves":
        return Decision(None, KIND_NOT_GRADED, measure)
    if measure == "goals_halves" and spec.kind not in ("half_time_full_time", "highest_scoring_half"):
        return Decision(None, KIND_NOT_GRADED, measure)
    return Decision(rule, OK, measure)


def rule_for(spec: BetSpec) -> Rule | None:
    """The rule that can grade the bet (liquidable), or None."""
    decision = explain(spec)
    return decision.rule if decision.liquidable else None
