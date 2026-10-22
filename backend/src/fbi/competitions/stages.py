"""The one reading of a round label (plan F2: "one stage classifier, replacing three").

API-Football says where a match sits in its competition as free text: ``Regular Season - 12``,
``Apertura - Quarter-finals``, ``2nd Qualifying Round``, ``8th Finals``, ``1/128-finals``,
``MLS Cup - Conference Semi-finals``, ``3rd Round Qualifying Replays``. Until F2 four places read that text with a
regular expression of their own (the standings phases, the AI context, the dossier, the neutral-venue rule) and
they could disagree about the same match. This module is the only reader of the label's WORDS; whatever else is
needed about a stage (how many legs its ties have, who won them) is read from the fixtures, never from the text
(``fbi.competitions.ties``).

A label is ``<phase> - <part> - ... - <match day>``:

* the MATCH DAY is a trailing number (``Clausura - 12``): a stage with match days is a round-robin;
* the STAGE is the label without it (``Clausura``, ``Apertura - Quadrangular``, ``Round of 16``): the key of a
  stage inside a competition season, and what ``core.competition_stages`` stores;
* the PHASE is its first part (``Apertura`` for ``Apertura - Quarter-finals``): a knock-out stage belongs to the
  phase of the league stage that came before it.

What is read from a stage:

``kind``   league | knockout | qualifying | friendly | unresolved. The coarse reading the standings pages have
           used since ``phases-1`` (and still do, unchanged): whether a league table counts the stage.
``role``   the finer reading: league | group | knockout | playoff | final | third_place | placement | qualifying |
           friendly | unresolved.
``round_key`` which round of a bracket: ``final``, ``semi_final``, ``quarter_final``, ``round_of_16`` (teams in
           the round, however the provider spells it: ``8th Finals`` and ``1/8-finals`` are the round of 16),
           ``round_3``, ``playoff``..., ``None`` when the label does not say.
``replay`` the stage holds the replays of another stage (``1st Round Replays``): its matches belong to the ties
           of ``base`` (``1st Round``).

``unresolved`` is a state, not a failure. A label that no rule reads (the provider sometimes writes an internal id,
``R60310``) is kept as it is and said so; callers decide what an unread stage is worth. Nothing here guesses.

The rules are frozen by ``VERSION``: a change to any of them changes what a stored stage means, so it bumps the
version and ``fbi.competitions.builder`` rewrites the stages whose reading changed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

VERSION: Final = "stages-1"
"""The version of the rules below; stored with every stage so an old reading is recognisable."""

StageKind = Literal["league", "knockout", "qualifying", "friendly", "unresolved"]
Role = Literal["league", "group", "knockout", "playoff", "final", "third_place", "placement", "qualifying", "friendly",
               "unresolved"]

# ── the label ───────────────────────────────────────────────────────────────

MATCH_DAY: Final = re.compile(r"\s*-\s*\d+\s*$")
"""A trailing match-day number: "Clausura - 12"."""
SEPARATOR: Final = " - "


def stage_of(round_label: str | None) -> str:
    """The round label without its match-day number: "Apertura - 7" -> "Apertura", "Apertura -
    Quadrangular - 3" -> "Apertura - Quadrangular", "Round of 16" -> "Round of 16"."""
    return MATCH_DAY.sub("", round_label or "").strip()


def phase_of(label: str | None) -> str:
    """The first part of a round or stage label: "Apertura - Quarter-finals" -> "Apertura"."""
    return (label or "").split(SEPARATOR)[0].strip()


def bracket_key(stage: str) -> str:
    """The family of stages that make one bracket: their phase when the label has parts ("Apertura - Quarter-finals"
    and "Apertura - Final" are the Apertura's bracket, not the Clausura's), and the empty key for a bare knock-out name
    ("Quarter-finals", "Round of 16"), which every other bare name of the season belongs with."""
    return phase_of(stage) if SEPARATOR in stage else ""


def match_day_of(round_label: str | None) -> int | None:
    """The match-day number a round label ends with, if it does."""
    found = MATCH_DAY.search(round_label or "")
    return int(found.group(0).replace("-", "").strip()) if found else None


def fold(s: str) -> str:
    """Lower case without accents: "Primera División" and "Primera Division" are one name."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


# ── the words of the labels (the provider's, as found in 245,872 fixtures on 22 Oct 2026) ──────────────────

KNOCKOUT: Final = re.compile(
    r"final|play[- ]?(?:offs?|in|out)|knockout|round of|quarter|semi|8th|16th|1/\d|qualifying|qualification|preliminary|"
    r"promotion|relegation (?:play|deciding)|relegation$|third place|3rd place|\d+(?:st|nd|rd|th) place|super cup|"
    r"repechage|elimination|decider|reclasificaci", re.IGNORECASE)
"""Rounds no league table counts (the truth audit's rule, shared). ``phases-1`` did not read "7th place", "Play Offs",
"Play-In Round", "Relegation" or "Reclasificación" as knock-out; they are single matches or ties, not table stages."""
STRICT_KNOCKOUT: Final = re.compile(
    r"final|semi|quarter|round of|1/\d|8th|16th|32nd|play-?offs?(?!\s*group)|knockout|repechage|third place|3rd place",
    re.IGNORECASE)
"""Knock-out words that still mean knock-out when the rounds carry a match-day number."""
LEAGUE_FORMAT: Final = re.compile(
    r"\bgroups?\b|quadrangular|hexagonal|triangular|pentagonal|octagonal|league (?:stage|phase)|round robin|"
    r"championship round|relegation round|regular season", re.IGNORECASE)
NUMBERED_LEAGUE: Final = re.compile(r"final (?:round|stage|phase|tournament)", re.IGNORECASE)
"""With match-day numbers these are round-robins ("Final Round - 3": CONCACAF's World Cup qualifying groups)."""
LEAGUE_STAGE: Final = re.compile(r"\bleague (?:stage|phase)\b", re.IGNORECASE)
"""The single league table that replaced the group stage in the Champions League, Europa League and Conference League
(2024-25 on): for what comes before and after it, it is a group stage."""
GROUPISH: Final = re.compile(r"^group\b", re.IGNORECASE)
"""Phases that are one group of a group stage ("Group A - 2" in Euro 2024): together they are one phase."""
QUALIFYING: Final = re.compile(r"qualif|preliminary", re.IGNORECASE)
UNNUMBERED_KNOCKOUT: Final = re.compile(r"\b\d+(?:st|nd|rd|th) (?:round|phase)\b|\bround \d+\b", re.IGNORECASE)
FRIENDLY: Final = re.compile(r"friendl", re.IGNORECASE)
LEAGUE_WORD: Final = re.compile(
    r"apertura|clausura|opening|closing|turno|girone|torneo|temporada|season|league|liga|round$|^round\b", re.IGNORECASE)
"""Words of a stage that is a league stage by its own name when no match day says so ("Apertura", "Torneo de Verano")."""
REPLAYS: Final = re.compile(r"\s*\breplays?\s*$", re.IGNORECASE)

ORDINAL: Final = r"(\d+)(?:st|nd|rd|th)"

_ROUND_OF: Final = re.compile(r"\bround of (\d+)\b")
_NTH_FINALS: Final = re.compile(rf"\b{ORDINAL} finals?\b")
_FRACTION: Final = re.compile(r"\b1/(\d+)-?\s*finals?\b")
_PLACE: Final = re.compile(rf"\b{ORDINAL}(?:-{ORDINAL})? place\b")
_THIRD: Final = re.compile(r"\b(?:third|3rd) place\b")
_SEMI: Final = re.compile(r"\bsemi-?\s?finals?\b")
_QUARTER: Final = re.compile(r"\bquarter-?\s?finals?\b")
_FINAL: Final = re.compile(r"\bfinals?\b")
_FINAL_PLAIN: Final = re.compile(r"^(?:grand |plate )?finals?$")
_PLAYOFF: Final = re.compile(r"play-?\s?(?:offs?|in|out)|decider|liguilla|reclasificaci|repechage|promotion$|relegation$")
_SUB_FINAL: Final = re.compile(r"\b(conference|zonal|inter-?zonal) finals?\b")
_ELIMINATION: Final = re.compile(r"\belimination finals?\b")
_QUALIFICATION_FINAL: Final = re.compile(r"\bqualif\w* finals?\b")
_ORDINAL_ROUND: Final = re.compile(rf"\b{ORDINAL} (?:round|phase)\b")
_ROUND_N: Final = re.compile(r"\bround (\d+)\b")
_QUALIFYING_N: Final = re.compile(rf"\b{ORDINAL} (?:qualifying|preliminary) round\b|\b(?:qualification|preliminary) round (\d+)\b")
_EXTRA_PRELIM: Final = re.compile(r"\bextra preliminary\b")


@dataclass(frozen=True, slots=True)
class Reading:
    """What a stage label says. ``rule`` names the rule that decided ``kind`` (kept as evidence)."""

    stage: str
    phase: str
    kind: StageKind
    role: Role
    rule: str
    numbered: bool
    round_key: str | None = None
    teams: int | None = None
    """Teams that start the round when the label says it (round of 16: 16, quarter-final: 8, final: 2)."""
    round_no: int | None = None
    """The ordinal of an ordinal round ("3rd Round", "2nd Qualifying Round")."""
    replay: bool = False
    base: str = ""
    """The stage the matches belong to: the stage itself, or for a stage of replays the stage replayed."""

    @property
    def resolved(self) -> bool:
        return self.kind != "unresolved"

    @property
    def is_knockout_like(self) -> bool:
        """Played in ties (single matches, two legs, replays): a knock-out round or a qualifying round."""
        return self.kind in ("knockout", "qualifying")


def _kind(stage: str, numbered: bool) -> tuple[StageKind, str]:
    """``phases-1``'s decision order, word for word, plus the one new outcome: ``unresolved``."""
    if FRIENDLY.search(stage):
        return "friendly", "friendly"
    if LEAGUE_FORMAT.search(stage):
        return "league", "league_format"
    if numbered:
        if STRICT_KNOCKOUT.search(stage) and not NUMBERED_LEAGUE.search(stage):
            return "knockout", "numbered_knockout_word"
        return "league", "numbered"
    if QUALIFYING.search(stage):
        return "qualifying", "qualifying_word"
    if KNOCKOUT.search(stage) or UNNUMBERED_KNOCKOUT.search(stage):
        return "knockout", "knockout_word"
    if LEAGUE_WORD.search(stage):
        return "league", "league_word"
    return "unresolved", "no_rule"


def _teams_in(count: int) -> int:
    """"8th Finals" / "1/8-finals" are the matches of a round (8 matches): the round of 16."""
    return 2 * count


def _bracket(low: str) -> tuple[str | None, int | None, Role]:
    """Which round of a bracket a (folded) stage tail names: (round key, teams, role)."""
    if (m := _ROUND_OF.search(low)) is not None:
        n = int(m.group(1))
        return f"round_of_{n}", n, "knockout"
    if (m := _NTH_FINALS.search(low)) is not None and not _PLACE.search(low):
        n = _teams_in(int(m.group(1)))
        return f"round_of_{n}", n, "knockout"
    if (m := _FRACTION.search(low)) is not None:
        n = _teams_in(int(m.group(1)))
        return f"round_of_{n}", n, "knockout"
    if _THIRD.search(low):
        return "third_place", 2, "third_place"
    if (m := _PLACE.search(low)) is not None:
        return f"place_{m.group(1)}", 2, "placement"
    if (m := _SUB_FINAL.search(low)) is not None:
        return f"{m.group(1).replace('-', '')}_final", None, "knockout"
    if _SEMI.search(low):
        return "semi_final", 4, "knockout"
    if _QUARTER.search(low):
        return "quarter_final", 8, "knockout"
    if _ELIMINATION.search(low):
        return "elimination_final", None, "knockout"
    if _QUALIFICATION_FINAL.search(low):
        return "qualification_final", None, "knockout"
    if _FINAL.search(low) and _PLAYOFF.search(low):
        return "playoff", None, "playoff"
    if _FINAL_PLAIN.match(low) or (_FINAL.search(low) and not re.search(r"final (?:round|stage|phase|tournament|four)", low)):
        return "final", 2, "final"
    if _PLAYOFF.search(low):
        return "playoff", None, "playoff"
    return None, None, "knockout"


def classify(stage: str, *, numbered: bool = False) -> Reading:
    """Read a stage (the label without its match day). ``numbered`` says whether the competition season gives this
    stage match days: the same words mean a league stage with them and a bracket without them ("Final Round")."""
    name = stage.strip()
    kind, rule = _kind(name, numbered)
    low = fold(name)
    parts = [p.strip() for p in low.split(SEPARATOR)]
    tail = parts[-1]
    replay = REPLAYS.search(low) is not None
    base = REPLAYS.sub("", name).strip() if replay else name
    round_key: str | None = None
    teams: int | None = None
    round_no: int | None = None
    role: Role
    if kind == "friendly":
        role = "friendly"
    elif kind == "unresolved":
        role = "unresolved"
    elif kind == "league":
        role = "group" if "group" in low or LEAGUE_STAGE.search(low) else "league"
    else:
        round_key, teams, role = _bracket(tail)
        if round_key is None:
            # the tail says nothing ("Apertura - Quarter-finals" says it, "Apertura - 1st Round" does not): look at the whole
            round_key, teams, role = _bracket(low)
        if kind == "qualifying":
            role = "qualifying"
        if (m := _QUALIFYING_N.search(low)) is not None:
            round_no = int(m.group(1) or m.group(2))
        elif (m := _ORDINAL_ROUND.search(tail) or _ROUND_N.search(tail)) is not None:
            round_no = int(m.group(1))
        if round_key is None:
            if round_no is not None:
                round_key = f"round_{round_no}"
            elif _EXTRA_PRELIM.search(low):
                round_key = "extra_preliminary"
            elif QUALIFYING.search(low):
                round_key = "preliminary" if "prelim" in low else "qualifying"
    return Reading(stage=name, phase=phase_of(name), kind=kind, role=role, rule=rule, numbered=numbered,
                   round_key=round_key, teams=teams, round_no=round_no, replay=replay, base=base)


def stage_kind(stage: str, *, numbered: bool) -> StageKind:
    """The coarse reading alone: ``league`` (a table counts it), ``knockout``, ``qualifying``, ``friendly`` or
    ``unresolved``."""
    return classify(stage, numbered=numbered).kind
