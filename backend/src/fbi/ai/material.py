"""The material change of a match (Plan Maestro IA, section 19): the only thing that pays for its brief again.

Until Phase 0 a brief was reused only when its input was BYTE-IDENTICAL - the hash of the whole packet - so a price that moved by a
cent, a model figure that was refreshed or a statistic that gained a decimal made a new, paid brief (on 24 Oct 2026, 232 of 299 matches
had two to four of them). A brief is a reading of a match's CONTEXT - who plays, who is out, what the news and the market say - and
the context changes less often than the packet does. The plan names what changes it:

* the line-up, an injury or a call-up, the coach;
* a price that moves more than 3 %;
* new evidence, or a contradiction between sources; a relevant piece of news (they are evidence, with a status);
* a change of kick-off time, or a suspension;
* a change of the competitive scenario;

and, besides, the selections the brief is asked about (its candidates), because it writes a note for each of them.

``material_of(packet, cards)`` reads that from the packet and gives two things:

* the DISCRETE parts - line-ups, absences, evidence, schedule, scenario, candidates, which prices exist, which blocks are missing - each
  hashed on its own, so that a rebuild can say WHICH part changed, and one hash of them all (``ai.match_briefs.material_hash``);
* the NUMBERS - the best price and the fair probability of every selection of the market, the price and the model's probability of
  every candidate - which are compared with the snapshot the brief was written under, with a tolerance. They are not hashed: hashing a
  rounded price would rebuild for a 0.1 % move that crosses a rounding edge and reuse a 5 % one that does not.

``compare(snapshot, current)`` says whether the stored brief is still the brief of this match: the same discrete parts and no number that
moved by more than ``PRICE_MOVE`` (3 %) of its value in the snapshot. A move of 2 % reuses the brief; a move of 4 % writes a new one. The
snapshot stays that of the brief that was written, so a price that drifts 1 % an hour is compared with what the model really read and the
brief is rebuilt when the sum of the drift passes 3 %.

Nothing here reads a clock, a key or a model; it changes no probability, threshold or pick. Rolled back with ``FBI_AI_BRIEF_MATERIAL=0``
the brief is reused by the identical hash only, as before.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fbi.ai.packet import Packet, canonical

MATERIAL_VERSION = "material-v1"
PRICE_MOVE = Decimal("0.03")
"""A price (or the model's probability for a candidate) that moves by MORE than this, relative to what the brief read, is a change."""
MAX_AGE = timedelta(hours=36)
"""A brief older than this is not reused for a material reason: the day it was written for is over."""
MISSING_THAT_MATTERS = frozenset({"absences", "lineups", "market", "phase", "standings"})
"""The blocks whose absence from the packet is itself information the brief reads (a block that arrives later is a change)."""
PARTS = ("lineups", "absences", "evidence", "schedule", "scenario", "cards", "priced", "missing")
SIDES = ("home", "away")


def _line(x: Any) -> str:
    """A line as one canonical text (0, 2.5, -1.25): the packet writes 0.00, a card 0 - the same as ``fbi.ai.brief.line_text``."""
    try:
        return format(Decimal(str(x)).normalize(), "f")
    except InvalidOperation:
        return str(x)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()[:16]


def _block(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ids(values: Any) -> list[str]:
    return sorted(str(v) for v in values) if isinstance(values, list) else []


def _number(value: Any) -> str | None:
    """A price or a probability as the text of its decimal, or None when it is not a finite number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    return str(d) if d.is_finite() else None


def _lineups(c: dict[str, Any]) -> dict[str, Any]:
    lineups = _block(c.get("lineups"))
    teams = _block(_block(c.get("dossier")).get("teams"))
    out: dict[str, Any] = {"confirmed": bool(lineups.get("confirmed"))}
    for side in SIDES:
        mine = _block(lineups.get(side))
        known_coach = _block(_block(teams.get(side)).get("coach")).get("name")
        out[side] = {"formation": mine.get("formation"), "starters": _ids(mine.get("starters")),
                     "coach": mine.get("coach") or known_coach}
    return out


def _absences(c: dict[str, Any]) -> dict[str, Any]:
    absences = _block(c.get("absences"))
    out: dict[str, Any] = {"checked": bool(absences.get("checked"))}
    for side in SIDES:
        players = _block(absences.get(side)).get("players")
        out[side] = sorted([str(p.get("player_id")), str(p.get("type") or ""), str(p.get("reason") or ""),
                            bool(p.get("key")), bool(p.get("first_choice_gk"))]
                           for p in (players if isinstance(players, list) else []) if isinstance(p, dict))
    return out


def _evidence(c: dict[str, Any]) -> list[list[Any]]:
    rows = c.get("evidence")
    return sorted([str(e.get("id")), str(e.get("status"))] for e in (rows if isinstance(rows, list) else [])
                  if isinstance(e, dict))


def _schedule(c: dict[str, Any]) -> dict[str, Any]:
    fx = _block(c.get("fixture"))
    return {"kickoff_at": fx.get("kickoff_at"), "status": fx.get("status"), "round": fx.get("round"),
            "venue": fx.get("venue"), "neutral": fx.get("neutral"), "changes": fx.get("kickoff_changes") or []}


def _scenario(c: dict[str, Any]) -> dict[str, Any]:
    return {"phase": c.get("phase"), "stakes": c.get("stakes"), "scenarios": c.get("scenarios")}


def _cards(cards: list[dict[str, Any]]) -> list[list[str]]:
    return sorted([str(k.get("market")), str(k.get("selection")), _line(k.get("line")), str(k.get("kind") or "")]
                  for k in cards)


def _numbers(c: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, str]:
    """Every price and probability whose relative move decides whether the brief is still the match's: the best price and the fair
    probability of each selection of the market, the price and the model's probability of each candidate."""
    out: dict[str, str] = {}
    selections = _block(c.get("market")).get("selections")
    for s in selections if isinstance(selections, list) else []:
        if not isinstance(s, dict):
            continue
        key = f"{s.get('market')}|{s.get('selection')}|{_line(s.get('line'))}"
        for name, field in (("odds", "best_odds"), ("fair", "p_fair")):
            n = _number(s.get(field))
            if n is not None:
                out[f"{name}|{key}"] = n
    for k in cards:
        key = f"{k.get('market')}|{k.get('selection')}|{_line(k.get('line'))}"
        for name, field in (("card_odds", "odds"), ("card_p", "p_model")):
            n = _number(k.get(field))
            if n is not None:
                out[f"{name}|{key}"] = n
    return out


@dataclass(frozen=True, slots=True)
class Material:
    """What decides whether a brief is still the match's: the hash of its discrete parts (and each part's own), and its numbers."""

    hash: str
    parts: dict[str, str]
    numbers: dict[str, str]

    def as_json(self) -> dict[str, Any]:
        return {"v": MATERIAL_VERSION, "hash": self.hash, "parts": self.parts, "numbers": self.numbers}


def material_of(packet: Packet, cards: list[dict[str, Any]]) -> Material:
    """The material of a match as its packet and the candidates' cards show it now."""
    c = packet.content
    numbers = _numbers(c, cards)
    discrete: dict[str, Any] = {
        "lineups": _lineups(c), "absences": _absences(c), "evidence": _evidence(c), "schedule": _schedule(c),
        "scenario": _scenario(c), "cards": _cards(cards), "priced": sorted(numbers),
        "missing": sorted(m for m in packet.missing if m in MISSING_THAT_MATTERS)}
    parts = {name: _digest(discrete[name]) for name in PARTS}
    return Material(_digest({"v": MATERIAL_VERSION, "parts": parts}), parts, numbers)


@dataclass(frozen=True, slots=True)
class Change:
    """Whether a stored brief is still the match's, and if not, what moved."""

    same: bool
    parts: tuple[str, ...] = ()
    """The discrete parts that differ (``PARTS``), or ``version`` / ``unreadable`` when the snapshot cannot be compared."""
    moved: tuple[tuple[str, str, str], ...] = ()
    """The numbers that moved by more than ``PRICE_MOVE``: (name, before, after)."""

    @property
    def why(self) -> str:
        return ",".join(self.parts + tuple(f"{k}:{a}>{b}" for k, a, b in self.moved)) or "none"


def moved(before: str, after: str) -> bool:
    """Whether a number is more than ``PRICE_MOVE`` away from what it was, relative to what it was (exactly 3 % is not a change)."""
    b, a = Decimal(before), Decimal(after)
    if b == 0:
        return a != 0
    return abs(a - b) / abs(b) > PRICE_MOVE


def compare(snapshot: Any, current: Material) -> Change:
    """The stored snapshot (``ai.match_briefs.material``) against the material of the match now."""
    if not isinstance(snapshot, dict) or snapshot.get("v") != MATERIAL_VERSION:
        return Change(False, ("version",))
    before_parts, before_numbers = snapshot.get("parts"), snapshot.get("numbers")
    if not isinstance(before_parts, dict) or not isinstance(before_numbers, dict):
        return Change(False, ("unreadable",))
    differ = tuple(p for p in PARTS if before_parts.get(p) != current.parts.get(p))
    shifted: list[tuple[str, str, str]] = []
    for name in sorted(current.numbers.keys() & before_numbers.keys()):
        try:
            if moved(str(before_numbers[name]), current.numbers[name]):
                shifted.append((name, str(before_numbers[name]), current.numbers[name]))
        except InvalidOperation:
            return Change(False, ("unreadable",))
    return Change(not differ and not shifted, differ, tuple(shifted))
