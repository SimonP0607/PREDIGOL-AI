"""``contra-v1``: the detector of the contradictions C01-C08 (Plan Maestro IA, sections 11 and 17; architecture, section 12).

CODE decides that a contradiction exists; a model never does. The detector reads the PACKAGE of a match (``fbi.ai.package.Package.document``,
or the ``match`` slice of it: every block it reads is in both; the ``stats`` slice carries no figures to tell the usual starters by, so there
C03 is ``input_missing``, and a slice may have trimmed the evidence C07 reads, so the package is the reference), the candidates the agents
know by name (``fbi.ai.agents.common.Naming``) and the assessments the specialists wrote, and returns what the Council must read BEFORE it
decides: one ``Contradiction`` per fact, with the candidates it touches, the references it rests on and the numbers it was computed from.

What it never does. It calls no model, reads no database, no clock and no setting (``at`` is part of the signature so that a rule that needs
the moment gets it as a parameter; none of this version's eight does - every figure they read is already relative to the kick-off inside the
package, and a test holds the output equal for two moments). It never raises on a package it cannot read and never fills a gap with a default:
what a rule needs and the package does not have makes the rule ``input_missing`` in ``coverage``, and the rule does not fire. And it copies no
text that came from outside: an evidence's summary, a name, a reason, a domain are never read. Besides the closed codes (the kind, the state
and the side of an evidence, the ``pressure`` of the stakes) the only texts it looks at are the provider's absence type (by its prefix:
``Missing`` or ``Questionable``) and the names of two competitions (to see whether they are the same); neither is ever written into the
output. ``subject`` and ``detail`` hold codes and numbers computed here, a player id is digits only, and the labels of the assessments are
used only when they are codes themselves. An evidence is read only when the Council could cite it (its id is an integer of the index).

The eight rules (thresholds are starting values, kept in ``PARAMS`` and calibrated in the shadow; the router owns two of them and they are
read from it, so that there is one number and not two):

    code  fires when                                                       reads (paths of the package)           touches
    C01   a KEY player of a side is out (not its first-choice keeper)      shared.absences.<side>, evidence       Over (OU), BTTS Yes, the side's win
    C02   the first-choice goalkeeper of a side is out                      shared.absences.<side>, evidence       Under (OU), BTTS No
    C03   another competition within 3 days AND, with the OFFICIAL XI,     shared.schedule.<side>, shared.lineups,  the side's win
          >= 4 usual starters are not in it                                 shared.players.<side>, shared.absences
    C04   the side's stakes are settled (``pressure == "settled"``)        shared.stakes.<side>                   the side's win
    C05   the referee's multiplier is below 0.85 (strictly)                shared.referee.multiplier (*)          Over of cards (family CARDS)
    C06   abs(p_model - p_market) is above 0.20 (strictly), any family      the candidate's p_model and p_market   that candidate
    C07   two or more evidences CONTRADICTORY on the same subject          evidence                               every candidate
    C08   SUPPORT in one assessment, CONCERN/REJECT_SIGNAL in ANOTHER      the assessments                        the two candidates
          (different label) on candidates that are aligned

(*) No builder writes ``shared.referee.multiplier`` yet (the multiplier lives inside the forecasts of ``family-v1``): until the package carries it,
``coverage`` says C05 is ``input_missing`` and the rule does not fire; a number that is not positive is not a multiplier.

"The side's win" is one closed set: the 1X2 selection of that side, the double chance that covers it (``1X`` for the home side, ``X2`` for the
away side, ``12`` for both) and the Asian handicap on that side, at any line. "Over" and "Under" are the selections of the ``OU`` family at any
line. The draw, the opposite side and every market of another family are never touched by the rules that name a side.

KEY PLAYER (C01, C02, and the regulars C03 counts among the reported absences). The definition already in the code base is
``fbi.ai.context.importance``: a regular starter (among the eleven most-used players, with at least 60 % of the most-used player's minutes)
or a player with at least 20 % of the team's goals and assists; the first-choice goalkeeper is the keeper with the most minutes. The packet
stamps it on every absent player (``key``, ``first_choice_gk``, ``minutes_share``, ``ga_share``), and this module reads the stamp: it does not
define the thresholds a second time (a test builds the entries through ``importance`` and holds both sides of each boundary). A first-choice
goalkeeper is C02's and not C01's: an offensive rule for the man who keeps the goal would point at the wrong selections.

OUT. A player is out when the provider's report lists him as ``Missing...``, or when an evidence of kind injury or suspension on him is CONFIRMED
or PROBABLE; ``Questionable`` alone is a doubt and a RUMOR is nothing. ``confirmed`` is true only when a CONFIRMED evidence says so (the
provider's report alone stays PROBABLE, as everywhere in the code base) - that is the fact router-v1's E2 reads. A player who is in the official
eleven is not out, whatever a stale report says. A side whose absences cannot be read (the list was never asked for, the squad has no figures,
an entry has no stamp) is not evaluated; an evidence alone does not make a player key, so without the list it fires nothing. The keeper is
one fact of the side (``team:<side>``), a key player one fact each (``player:<id>``).

ROTATION (C03) reads the calendar of the side in BOTH directions - the last three matches and the next ones - for a match of ANOTHER competition
(a different name from the fixture's) within 3 days; a calendar that is not whole and lists nothing does not prove there is none, so then the
rule is not evaluated. The line-up is official only when the package says it is confirmed and lists eleven different starters. "Usual starters
not in it" are the players of the dossier's list (the six most-used of the last ten matches) who started at least 60 % of the matches they
played, plus the key players reported out; the dossier lists six, so a seventh usual starter left out is not seen (documented limit: the rule
is built for precision), and a list with no readable figures says nothing, so then the rule is not evaluated. The competition of the calendar
and the fixture's are compared by name: both come from ``core.competitions`` for a competition PrediGol follows, so the same one has the same
name; the package rounds the days to one decimal.

C08 and the alignment of candidates. The plan does not define "correlated", and the code base has only coarse notions (filter 8 treats every
selection of a match as correlated; ``fbi.parlays.correlation`` measures matchday effects across matches). Here two candidates are ALIGNED when
they are the same selection or lean on the same outcome - the same bet in different clothes: a side's win (1X2, ``1X``/``X2``, Asian handicap
of that side), more goals (Over at any line, BTTS Yes), fewer goals (Under, BTTS No), the draw, and more or fewer corners or cards of the same
family. Opposite selections are NOT aligned (supporting one and doubting the other is coherent), and neither are different outcomes that are
only statistically related: the architecture (section 10) records that the totals of goals, corners and cards barely depend on each other
(-0.021 to -0.028 over 59,252 matches), and a relation between counts is DESCRIPTIVE until a person validates it. The relation is symmetric and
ignores the line (it flags for the Council to resolve in writing; it does not prove an inconsistency). A finer table is a new version.

Output. Sorted by ``(code, subject, candidates, refs, detail)``; ``candidates`` by their number, ``refs`` and ``detail`` sorted and without
repeats; a contradiction that touches no candidate is dropped (C07 touches all, and with no candidates there is nothing to return); every
reference exists in the document (``E:<id>`` of the evidence that fires a rule, ``P:<path>`` of the block it read). C08 cites the evidence and
the blocks the opposing stances themselves rested on, and names the two labels in ``detail`` (the ``A:<label>`` the Council cites is not a block
of the package).

Subjects. C01 ``player:<id>``; C02, C03 and C04 ``team:<side>``; C05 ``referee``; C06 ``pair:cN+cN`` (the one candidate: its model against its
market - the vocabulary of ``Contradiction.subject`` has no form for a single candidate); C07 ``player:<id>``, ``team:<side>`` or ``match``,
after the side its evidences name; C08 ``pair:<supported>+<objected>``, in that order (the pair is directed: who is supported, who is doubted).
Subjects sort as strings (``player:10`` comes before ``player:9``); the candidates of one contradiction sort by their number.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal, get_args

from fbi.ai import router
from fbi.ai.agents.common import Assessed, ContraCode, Contradiction, Named, Naming, known_refs
from fbi.ai.contracts.base import CANDIDATE, check_refs
from fbi.ai.contracts.mcp import EvidenceKind

VERSION: Final = "contra-v1"

PARAMS: Final[dict[str, Any]] = {
    "rotation_days": 3,
    "usual_starters_out": router.PARAMS["e3_usual_starters_out"],
    "lineup_size": 11,
    "regular_starts_share": "0.60",
    "referee_multiplier_below": "0.85",
    "model_market_gap": router.PARAMS["e6_gap"],
    "conflicting_evidences": 2,
}
"""The thresholds of this version. ``usual_starters_out`` and ``model_market_gap`` ARE the router's (``e3_usual_starters_out``, ``e6_gap``): the
escalation and the contradiction that feeds it cannot disagree. ``rotation_days`` is the largest number of days (inclusive) between this match
and one of another competition; ``lineup_size`` the starters an official line-up lists; ``regular_starts_share`` the share of the matches he
played that a player of the dossier's list must have started to count as a usual starter (C03); ``referee_multiplier_below`` is exclusive."""

EVALUATED: Final = "evaluated"
INPUT_MISSING: Final = "input_missing"
"""What ``coverage`` says of a rule: the package has what it reads, or it does not (and the rule did not fire - it was not asked)."""

Side = Literal["home", "away"]
SIDES: Final[tuple[Side, ...]] = ("home", "away")

OUT_KINDS: Final = frozenset({"injury", "suspension"})
"""The kinds of evidence that say a player is out (``doubtful`` is a doubt, ``lineup`` is not about absence)."""
STANDING: Final = frozenset({"CONFIRMED", "PROBABLE"})
"""The states of evidence that may say it; a RUMOR is nothing and a CONTRADICTORY pair is C07's."""
PRESSURES: Final = frozenset({"title", "europe", "relegation", "promotion", "mid_table", "settled"})
"""The ``pressure`` codes of ``fbi.ai.context.stakes`` that say something (``unknown`` does not)."""
_KINDS: Final = frozenset(get_args(EvidenceKind))
_EVIDENCE_SIDES: Final = frozenset({"home", "away", "match"})
_DIGITS: Final = re.compile(r"[0-9]{1,12}")
_ID_LIMIT: Final = 10**12
_MAGNITUDE: Final = 30
"""The largest figure read (``adjusted()`` is the power of ten of its first digit): ids have at most twelve digits, the rest is smaller."""
_LABEL: Final = re.compile(r"[a-z][a-z0-9_]{0,39}")
"""An assessment's label is used in the output only when it is a code (``match_evaluation``) and not a text."""

# selection -> the sides whose win it leans on (the closed set "the side's win" of the docstring)
_BACKS: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("1X2", "HOME"): frozenset({"home"}), ("1X2", "AWAY"): frozenset({"away"}),
    ("DC", "1X"): frozenset({"home"}), ("DC", "X2"): frozenset({"away"}), ("DC", "12"): frozenset({"home", "away"}),
    ("AH", "HOME"): frozenset({"home"}), ("AH", "AWAY"): frozenset({"away"})}
# selection -> the outcome it leans on, for the alignment of C08 (a selection with none is aligned only with itself)
_LEANS: Final[dict[tuple[str, str], str]] = {
    ("1X2", "HOME"): "win:home", ("1X2", "AWAY"): "win:away", ("1X2", "DRAW"): "draw",
    ("DC", "1X"): "win:home", ("DC", "X2"): "win:away",
    ("AH", "HOME"): "win:home", ("AH", "AWAY"): "win:away",
    ("OU", "OVER"): "goals:up", ("BTTS", "YES"): "goals:up", ("OU", "UNDER"): "goals:down", ("BTTS", "NO"): "goals:down",
    ("CORNERS", "OVER"): "corners:up", ("CORNERS", "UNDER"): "corners:down",
    ("CARDS", "OVER"): "cards:up", ("CARDS", "UNDER"): "cards:down"}


def params_hash() -> str:
    """The digest that goes with every run of this version, like ``router.params_hash``: the parameters, in canonical form."""
    return hashlib.sha256(json.dumps(PARAMS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def _dec(name: str) -> Decimal:
    return Decimal(str(PARAMS[name]))


# -- reading a package that may be anything ------------------------------------------------------------------------------------------

def _number(value: Any) -> Decimal | None:
    """A finite number of a sane size from a JSON value (a bool is not a number, and neither is a text that is not one); None otherwise. A
    figure too large to be a count, a share or a number of days is garbage, and arithmetic on it could overflow: it is not read."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):  # ValueError: an int with thousands of digits has no text form
        return None
    return number if number.is_finite() and number.adjusted() <= _MAGNITUDE else None


def _probability(value: Any) -> Decimal | None:
    number = _number(value)
    return number if number is not None and 0 <= number <= 1 else None


def _int(value: Any) -> int | None:
    """A non-negative integer of at most twelve digits (an id, a count): an int, or a text made of digits only, so that nothing but digits
    can reach a subject."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value < _ID_LIMIT else None
    return int(value) if isinstance(value, str) and _DIGITS.fullmatch(value) else None


def _node(root: Any, *path: str) -> Any:
    """The value at a path of keys, or None as soon as a step is not there. No step raises."""
    node = root
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def _items(value: Any) -> Sequence[Any]:
    return value if isinstance(value, (list, tuple)) else ()


def _name(value: Any) -> str | None:
    """A text compared for equality only (the name of a competition): casefolded; None when there is nothing to compare."""
    if not isinstance(value, str):
        return None
    return value.strip().casefold() or None


def _plain(number: Decimal) -> str:
    return format(number, "f")


@dataclass(frozen=True, slots=True)
class _Evidence:
    """The five fields of an evidence the rules read. Never its summary, its domain, its class of source or its date."""

    id: int
    kind: str
    side: str
    player_id: int | None
    status: str


def _evidence(doc: Mapping[str, Any]) -> tuple[_Evidence, ...] | None:
    """The index of the evidence, readable items only, in a canonical order; None when the document has no index."""
    raw = doc.get("evidence")
    if not isinstance(raw, (list, tuple)):
        return None
    items: list[_Evidence] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        ident, kind, status = item.get("id"), item.get("kind"), item.get("status")
        side = item.get("side", "match")
        side = "match" if side is None else side
        # an evidence is read only if the Council can cite it: its id is a real integer of the index (``known_refs`` lists the same ones)
        if isinstance(ident, bool) or not isinstance(ident, int) or not 1 <= ident < _ID_LIMIT or not isinstance(kind, str) \
                or kind not in _KINDS or not isinstance(status, str) or not isinstance(side, str) or side not in _EVIDENCE_SIDES:
            continue
        items.append(_Evidence(ident, kind, side, _int(item.get("player_id")), status))
    items.sort(key=lambda e: (e.id, e.kind, e.side, -1 if e.player_id is None else e.player_id, e.status))
    first: dict[int, _Evidence] = {}
    for e in items:
        first.setdefault(e.id, e)  # an id is indexed once; if a document repeats one, the same copy is kept whatever the order
    return tuple(first.values())


@dataclass(frozen=True, slots=True)
class _Absentee:
    player_id: int
    out: bool
    """The provider's report lists him as missing (``Missing...``); ``Questionable`` and anything else is not."""
    key: bool
    keeper: bool
    minutes_share: Decimal | None
    ga_share: Decimal | None


def _absentee(item: Any) -> _Absentee | None:
    if not isinstance(item, Mapping):
        return None
    player, key, keeper = _int(item.get("player_id")), item.get("key"), item.get("first_choice_gk")
    if player is None or not isinstance(key, bool) or not isinstance(keeper, bool):
        return None
    kind = item.get("type")
    out = isinstance(kind, str) and kind.strip().lower().startswith("missing")
    return _Absentee(player, out, key, keeper, _probability(item.get("minutes_share")), _probability(item.get("ga_share")))


def _absentees(doc: Mapping[str, Any], side: Side) -> tuple[_Absentee, ...] | None:
    """Who the provider lists on a side, or None when the package cannot say (the list was never asked for, the squad has no figures to
    weigh anyone by, or an entry lacks the stamp of the packet)."""
    block = _node(doc, "shared", "absences")
    mine = _node(block, side)
    listed = _node(mine, "players")
    if not isinstance(listed, (list, tuple)):
        return None
    if not listed:
        return () if _node(block, "checked") is True else None
    squad = _int(_node(mine, "squad_known"))
    if squad is None or squad < 1:
        return None
    entries = [_absentee(item) for item in listed]
    if any(e is None for e in entries):
        return None
    ordered = sorted((e for e in entries if e is not None),
                     key=lambda a: (a.player_id, not a.out, not a.key, not a.keeper, str(a.minutes_share), str(a.ga_share)))
    first: dict[int, _Absentee] = {}
    for a in ordered:
        first.setdefault(a.player_id, a)
    return tuple(first.values())


def _official_xi(doc: Mapping[str, Any], side: Side) -> frozenset[int] | None:
    """The eleven starters of an OFFICIAL line-up, or None (not confirmed, not listed for the side, or not eleven different ids)."""
    block = _node(doc, "shared", "lineups")
    starters = _node(block, side, "starters")
    if _node(block, "confirmed") is not True or not isinstance(starters, (list, tuple)):
        return None
    ids = [_int(x) for x in starters]
    if None in ids or len(set(ids)) != len(ids) or len(ids) != int(PARAMS["lineup_size"]):
        return None
    return frozenset(i for i in ids if i is not None)


@dataclass(frozen=True, slots=True)
class _Congestion:
    days: Decimal
    after: bool


_Calendar = Literal["listed", "clear", "unknown"]


def _congestion(doc: Mapping[str, Any], side: Side) -> tuple[_Calendar, _Congestion | None]:
    """A match of another competition within ``rotation_days`` of this one, before or after: ``listed`` (with the nearest), ``clear`` (the
    side's calendar is whole and lists none) or ``unknown`` (it lists none, or cannot be compared, and is not whole)."""
    mine = _node(doc, "shared", "schedule", side)
    if not isinstance(mine, Mapping):
        return "unknown", None
    here = _name(_node(doc, "header", "competition", "name"))
    window = Decimal(int(PARAMS["rotation_days"]))
    entries: list[tuple[bool, Any]] = [(False, e) for e in _items(mine.get("recent"))]
    entries += [(True, e) for e in (mine.get("next_match"), *_items(mine.get("upcoming")))]
    nearest: _Congestion | None = None
    undecided = False
    for after, entry in entries:
        days = _number(_node(entry, "days_after" if after else "days_before"))
        if days is None or not 0 <= days <= window:
            continue
        other = _name(_node(entry, "competition"))
        if here is None or other is None:
            undecided = True
        elif other != here and (nearest is None or (days, not after) < (nearest.days, not nearest.after)):
            nearest = _Congestion(days, after)
    if nearest is not None:
        return "listed", nearest
    whole = _node(doc, "shared", "schedule", "calendar", side, "complete") is True
    return ("clear", None) if whole and not undecided else ("unknown", None)


@dataclass(frozen=True, slots=True)
class _Rotation:
    nearest: _Congestion | None
    out: frozenset[int]
    used_absences: bool


def _rotation_of(doc: Mapping[str, Any], side: Side) -> _Rotation | None:
    """What C03 needs of a side, or None when the package cannot answer (the line-up is not official, the calendar is not whole and silent,
    or the dossier has no list of players)."""
    xi = _official_xi(doc, side)
    state, nearest = _congestion(doc, side)
    players = _node(doc, "shared", "players", side)
    if xi is None or state == "unknown" or not isinstance(players, (list, tuple)):
        return None
    share = _dec("regular_starts_share")
    out: set[int] = set()
    readable = 0
    for p in players:
        ident, apps, starts = _int(_node(p, "id")), _number(_node(p, "apps")), _number(_node(p, "starts"))
        if ident is None or apps is None or starts is None:
            continue
        readable += 1
        if apps > 0 and starts >= share * apps and ident not in xi:
            out.add(ident)
    if not readable:  # a list with no figures to tell the usual starters by (the statistics slice carries none) says nothing
        return None
    reported = {a.player_id for a in _absentees(doc, side) or () if a.out and (a.key or a.keeper) and a.player_id not in xi}
    return _Rotation(nearest, frozenset(out | reported), bool(reported - out))


def _pressure(doc: Mapping[str, Any], side: Side) -> str | None:
    pressure = _node(doc, "shared", "stakes", side, "pressure")
    return pressure if isinstance(pressure, str) and pressure in PRESSURES else None


def _multiplier(doc: Mapping[str, Any]) -> Decimal | None:
    number = _number(_node(doc, "shared", "referee", "multiplier"))
    return number if number is not None and number > 0 else None


# -- the candidates a fact touches ---------------------------------------------------------------------------------------------------

def _selection(n: Named) -> str:
    return str(n.candidate.selection).strip().upper()


def _backs(n: Named, side: str) -> bool:
    """The selection leans on the win of ``side`` (the closed set of the docstring)."""
    return side in _BACKS.get((n.family, _selection(n)), frozenset())


def _goals_up(n: Named) -> bool:
    return (n.family, _selection(n)) in {("OU", "OVER"), ("BTTS", "YES")}


def _goals_down(n: Named) -> bool:
    return (n.family, _selection(n)) in {("OU", "UNDER"), ("BTTS", "NO")}


def _cards_over(n: Named) -> bool:
    return (n.family, _selection(n)) == ("CARDS", "OVER")


def _every(n: Named) -> bool:
    return True


def _win_of(side: str) -> Callable[[Named], bool]:
    """The candidates that lean on the win of ``side``."""
    def touches(n: Named) -> bool:
        return _backs(n, side)
    return touches


def _goals_up_or_win_of(side: str) -> Callable[[Named], bool]:
    """The candidates that lean on more goals or on the win of ``side`` (what the absence of its key player puts in doubt)."""
    def touches(n: Named) -> bool:
        return _goals_up(n) or _backs(n, side)
    return touches


def _aligned(a: Named, b: Named) -> bool:
    """The same selection, or two selections that lean on the same outcome (symmetric; the line does not matter)."""
    if a.key == b.key:
        return True
    lean = _LEANS.get((a.family, _selection(a)))
    return lean is not None and lean == _LEANS.get((b.family, _selection(b)))


def _number_of(name: str) -> int:
    return int(name[1:])


@dataclass(frozen=True, slots=True)
class _Ctx:
    """One run: the document, the candidates by name (valid names only, by number), the index of the evidence and what a reference may name."""

    doc: Mapping[str, Any]
    named: tuple[Named, ...]
    evidence: tuple[_Evidence, ...]
    ids: frozenset[int]
    paths: frozenset[str]

    def pick(self, predicate: Callable[[Named], bool]) -> list[str]:
        return [n.key for n in self.named if predicate(n)]

    def make(self, code: ContraCode, subject: str, touched: Iterable[str], refs: Iterable[str], **fields: Any) -> Contradiction | None:
        """A contradiction with its candidates by number and only the references that exist; None when it touches no candidate."""
        names = sorted(set(touched), key=_number_of)
        if not names:
            return None
        asked = sorted(set(refs))
        bad = set(check_refs(asked, evidence_ids=self.ids, paths=self.paths))
        return Contradiction(code, subject, tuple(names), tuple(r for r in asked if r not in bad), **fields)

    def evidence_of(self, side: Side, player: int) -> tuple[_Evidence, ...]:
        """The evidence that says a player is out: injury or suspension, CONFIRMED or PROBABLE, about him (the side, or no side at all)."""
        return tuple(e for e in self.evidence if e.player_id == player and e.kind in OUT_KINDS and e.status in STANDING
                     and e.side in (side, "match"))


def _context(document: Any, naming: Naming) -> _Ctx:
    doc: Mapping[str, Any] = document if isinstance(document, Mapping) else {}
    try:
        ids, paths = known_refs(doc)
    except (RecursionError, ValueError, TypeError):  # a document nested beyond reason, or keyed by garbage, names nothing a reference could point at
        ids, paths = frozenset(), frozenset()
    ids = frozenset(i for i in ids if 0 < i < _ID_LIMIT)  # an id of thousands of digits is not one, and ``check_refs`` would have to print it
    seen: dict[str, Named] = {}
    for n in sorted(naming.named, key=lambda x: (x.key, x.candidate.market_key, x.candidate.selection, x.candidate.line)):
        if CANDIDATE.fullmatch(n.key):
            seen.setdefault(n.key, n)
    return _Ctx(doc, tuple(sorted(seen.values(), key=lambda n: _number_of(n.key))), _evidence(doc) or (), ids, paths)


def _detail(**values: str | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((k, v) for k, v in values.items() if v is not None))


# -- C01, C02: the absences ----------------------------------------------------------------------------------------------------------

def _absences(ctx: _Ctx) -> list[Contradiction]:
    """C01 and C02: for each side, each listed player who is out and is a key player (C01) or the first-choice goalkeeper (C02). The keeper is
    one fact of the side (``team:<side>``): were the list to flag two of them, what they rest on is joined and not repeated."""
    found: list[Contradiction | None] = []
    for side in SIDES:
        xi = _official_xi(ctx.doc, side) or frozenset()
        keeper_refs: list[str] = []
        keeper_out = keeper_confirmed = False
        for a in _absentees(ctx.doc, side) or ():
            evidence = ctx.evidence_of(side, a.player_id)
            if a.player_id in xi or not (a.out or evidence) or not (a.keeper or a.key):
                continue
            confirmed = any(e.status == "CONFIRMED" for e in evidence)
            refs = [f"P:shared.absences.{side}", *(f"E:{e.id}" for e in evidence)]
            if a.keeper:
                keeper_out, keeper_confirmed = True, keeper_confirmed or confirmed
                keeper_refs += refs
            else:
                found.append(ctx.make("C01", f"player:{a.player_id}", ctx.pick(_goals_up_or_win_of(side)), refs, confirmed=confirmed,
                                      detail=_detail(side=side, minutes_share=None if a.minutes_share is None else _plain(a.minutes_share),
                                                     ga_share=None if a.ga_share is None else _plain(a.ga_share))))
        if keeper_out:
            found.append(ctx.make("C02", f"team:{side}", ctx.pick(_goals_down), keeper_refs, confirmed=keeper_confirmed,
                                  detail=_detail(side=side)))
    return [c for c in found if c is not None]


# -- C03: rotation -------------------------------------------------------------------------------------------------------------------

def _rotation(ctx: _Ctx) -> list[Contradiction]:
    found: list[Contradiction | None] = []
    for side in SIDES:
        rotation = _rotation_of(ctx.doc, side)
        if rotation is None or rotation.nearest is None or len(rotation.out) < int(PARAMS["usual_starters_out"]):
            continue
        refs = [f"P:shared.lineups.{side}", f"P:shared.schedule.{side}", f"P:shared.players.{side}"]
        if rotation.used_absences:
            refs.append(f"P:shared.absences.{side}")
        found.append(ctx.make("C03", f"team:{side}", ctx.pick(_win_of(side)), refs, official_lineup=True,
                              starters_out=len(rotation.out),
                              detail=_detail(side=side, days=_plain(rotation.nearest.days),
                                             other_match="after" if rotation.nearest.after else "before")))
    return [c for c in found if c is not None]


# -- C04: nothing at stake -----------------------------------------------------------------------------------------------------------

def _nothing_at_stake(ctx: _Ctx) -> list[Contradiction]:
    found = [ctx.make("C04", f"team:{side}", ctx.pick(_win_of(side)), [f"P:shared.stakes.{side}"],
                      detail=_detail(side=side, remaining=_remaining(ctx.doc, side)))
             for side in SIDES if _pressure(ctx.doc, side) == "settled"]
    return [c for c in found if c is not None]


def _remaining(doc: Mapping[str, Any], side: Side) -> str | None:
    left = _int(_node(doc, "shared", "stakes", side, "remaining"))
    return None if left is None else str(left)


# -- C05: a lenient referee ----------------------------------------------------------------------------------------------------------

def _lenient_referee(ctx: _Ctx) -> list[Contradiction]:
    multiplier = _multiplier(ctx.doc)
    if multiplier is None or multiplier >= _dec("referee_multiplier_below"):
        return []
    made = ctx.make("C05", "referee", ctx.pick(_cards_over), ["P:shared.referee.multiplier"], detail=_detail(multiplier=_plain(multiplier)))
    return [] if made is None else [made]


# -- C06: the model against the market -----------------------------------------------------------------------------------------------

def _gap_of(n: Named) -> tuple[Decimal, Decimal, Decimal] | None:
    """(gap, p_model, p_market) of a candidate: the same quantity as ``Candidate.edge`` (the model's probability less the market's
    de-vigged one), in absolute value; None when the candidate does not have both."""
    p_model, p_market = _probability(n.candidate.p_model), _probability(n.candidate.p_market)
    if p_model is None or p_market is None:
        return None
    return abs(p_model - p_market), p_model, p_market


def _gap(ctx: _Ctx) -> list[Contradiction]:
    threshold = _dec("model_market_gap")
    found: list[Contradiction | None] = []
    for n in ctx.named:
        measured = _gap_of(n)
        if measured is not None and measured[0] > threshold:
            found.append(ctx.make("C06", f"pair:{n.key}+{n.key}", [n.key], ["P:market", "P:models"], gap=measured[0],
                                  detail=_detail(p_model=_plain(measured[1]), p_market=_plain(measured[2]))))
    return [c for c in found if c is not None]


# -- C07: evidence in conflict -------------------------------------------------------------------------------------------------------

def _conflict(ctx: _Ctx) -> list[Contradiction]:
    """Two or more evidences CONTRADICTORY about one subject: (side, player) when they name a player, else (side, kind)."""
    groups: dict[tuple[str, int | str, bool], list[_Evidence]] = {}
    for e in ctx.evidence:
        if e.status == "CONTRADICTORY":
            groups.setdefault((e.side, e.kind if e.player_id is None else e.player_id, e.player_id is not None), []).append(e)
    found: list[Contradiction | None] = []
    for (side, who, is_player), members in groups.items():
        if len(members) < int(PARAMS["conflicting_evidences"]):
            continue
        subject = f"player:{who}" if is_player else "match" if side == "match" else f"team:{side}"
        found.append(ctx.make("C07", subject, ctx.pick(_every), [f"E:{e.id}" for e in members],
                              detail=_detail(side=side, evidences=str(len(members)), kind=None if is_player else str(who))))
    return [c for c in found if c is not None]


# -- C08: specialists in disagreement ------------------------------------------------------------------------------------------------

@dataclass(slots=True)
class _Dispute:
    supporters: set[str] = field(default_factory=set)
    objectors: set[str] = field(default_factory=set)
    strongest: str = "CONCERN"
    refs: set[str] = field(default_factory=set)


def _stances(assessed: Assessed, known: set[str]) -> tuple[str, dict[str, tuple[str, tuple[str, ...]]]] | None:
    """(label, name -> (stance, refs)) of an assessment whose label is a code, for the candidates it took a side on that this match has."""
    label = assessed.label
    if not isinstance(label, str) or _LABEL.fullmatch(label) is None:
        return None
    taken: dict[str, tuple[str, tuple[str, ...]]] = {}
    for c in _items(getattr(getattr(assessed, "out", None), "candidates", ())):
        name, stance = getattr(c, "candidate", None), getattr(c, "stance", None)
        if isinstance(name, str) and name in known and stance in ("SUPPORT", "CONCERN", "REJECT_SIGNAL"):
            taken[name] = (stance, tuple(r for r in _items(getattr(c, "refs", ())) if isinstance(r, str)))
    return label, taken


def _disagreement(ctx: _Ctx, assessments: Sequence[Assessed]) -> list[Contradiction]:
    by_name = {n.key: n for n in ctx.named}
    read = [r for a in assessments if (r := _stances(a, set(by_name))) is not None]
    disputes: dict[tuple[str, str], _Dispute] = {}
    for for_label, for_taken in read:
        for against_label, against_taken in read:
            if for_label == against_label:
                continue
            for supported, (stance, support_refs) in for_taken.items():
                for objected, (objection, objection_refs) in against_taken.items():
                    if stance != "SUPPORT" or objection == "SUPPORT" or not _aligned(by_name[supported], by_name[objected]):
                        continue
                    dispute = disputes.setdefault((supported, objected), _Dispute())
                    dispute.supporters.add(for_label)
                    dispute.objectors.add(against_label)
                    dispute.refs |= {*support_refs, *objection_refs}
                    if objection == "REJECT_SIGNAL":
                        dispute.strongest = "REJECT_SIGNAL"
    found = [ctx.make("C08", f"pair:{supported}+{objected}", [supported, objected], d.refs,
                      detail=_detail(support_by="+".join(sorted(d.supporters)), against_by="+".join(sorted(d.objectors)),
                                     against_stance=d.strongest))
             for (supported, objected), d in disputes.items()]
    return [c for c in found if c is not None]


# -- the public face -----------------------------------------------------------------------------------------------------------------

def _order(c: Contradiction) -> tuple[str, str, tuple[int, ...], tuple[str, ...], tuple[tuple[str, str], ...]]:
    return c.code, c.subject, tuple(_number_of(k) for k in c.candidates), c.refs, c.detail


def detect(document: Mapping[str, Any], *, naming: Naming, assessments: Sequence[Assessed] = (), at: datetime
           ) -> tuple[Contradiction, ...]:
    """The contradictions of ``contra-v1`` in a match: pure, total and deterministic (the same package, candidates and assessments give the
    same tuple whatever order they came in). ``blocking`` is the orchestrator's business - whether a model is called - and the detector does
    not read it. ``at`` is part of the signature and no rule of this version depends on it."""
    ctx = _context(document, naming)
    found = [*_absences(ctx), *_rotation(ctx), *_nothing_at_stake(ctx), *_lenient_referee(ctx), *_gap(ctx), *_conflict(ctx),
             *_disagreement(ctx, assessments)]
    return tuple(sorted(dict.fromkeys(found), key=_order))


def coverage(document: Mapping[str, Any], *, naming: Naming) -> dict[str, str]:
    """For each code, whether the package has what the rule reads (``evaluated``) or not (``input_missing``): a rule that did not fire
    because its input was missing is not a rule that found nothing. A rule that concerns both sides is evaluated only when it can be on
    both. C08's input is the assessments, not the package: it is always evaluated (with fewer than two labels there is nothing to set against
    each other)."""
    doc: Mapping[str, Any] = document if isinstance(document, Mapping) else {}
    named = _context(doc, naming).named
    absences = all(_absentees(doc, side) is not None for side in SIDES)
    ready = {
        "C01": absences, "C02": absences,
        "C03": all(_rotation_of(doc, side) is not None for side in SIDES),
        "C04": all(_pressure(doc, side) is not None for side in SIDES),
        "C05": _multiplier(doc) is not None,
        "C06": bool(named) and all(_gap_of(n) is not None for n in named),
        "C07": _evidence(doc) is not None,
        "C08": True}
    return {code: EVALUATED if ready[code] else INPUT_MISSING for code in sorted(ready)}


def facts_for(items: Sequence[Contradiction], candidate: str, *, hours_to_kickoff: Decimal | None, researched: bool = False
              ) -> dict[str, Any]:
    """The fields of ``router.Facts`` that ONLY the contradictions decide, for one candidate (by its name): a CONFIRMED absence that fires C01
    or C02 on it, an official line-up that fires C03 on it (and how many usual starters it leaves out), a C07 that a research did not
    resolve, the gap of C06 - and the hours to the kick-off, passed through. Never what only the Council knows (its confidence, whether it
    approves with a low one, whether C08 was left unresolved) nor what the orchestrator knows (pick of the day, parlay leg, the edge)."""
    mine = [c for c in items if candidate in c.candidates]
    rotation = [c for c in mine if c.code == "C03" and c.official_lineup]
    gaps = [c.gap for c in mine if c.code == "C06" and c.gap is not None]
    return {
        "confirmed_news_on_candidate": any(c.code in ("C01", "C02") and c.confirmed for c in mine),
        "official_lineup_surprise": bool(rotation),
        "usual_starters_out": max((c.starters_out for c in rotation), default=0),
        "c07_unresolved_after_research": researched and any(c.code == "C07" for c in mine),
        "model_market_gap": max(gaps, default=None),
        "hours_to_kickoff": hours_to_kickoff}
