"""The events of a match, read once (plan F7, ``events-v1``): what each line of the provider's list IS and in which period it happened.

The provider lists, in the order things happened, goals, cards, substitutions and VAR decisions as ``(type, detail, comments)`` text. Four
things in that text are not what they look like, and every one was measured on production (23 Oct 2026, 3,218,434 events):

* **A goal is not always a goal of the match.** The kicks of a penalty shoot-out are ``Goal / Penalty`` (converted) and ``Goal / Missed
  Penalty`` with the comment ``Penalty Shootout`` (10,908 of them, all at minute 120; in the older ones ``extra_minute`` is the number of
  the kick, not a minute). An own goal is filed under the team that GETS the goal (the 1,154 matches whose only goal was an own goal),
  although the man who scored it is the other team's. A converted penalty of the match and one of a shoot-out are the same words.
* **A second yellow is two lines.** The provider lists a dismissal for a second yellow card as a ``Yellow Card`` and a ``Red Card`` of the
  same man at the same minute (18,676 reds out of 41,179 with a player; in 50 more the yellow comes AFTER the red in the list, and in 40 of
  those the man had been booked before, so they are the same thing in the other order); only 100 events say ``Second Yellow Card``
  outright. Its own statistics agree: the match's ``yellow_cards`` count includes the yellow of the pair and its ``red_cards`` the red
  (1,571 of 1,707 sides and 1,684 of 1,707). So the red of a pair is classed ``second_yellow`` (a dismissal for two yellows) and keeps
  its place in the red count; a red of a man who had a yellow at ANOTHER minute is a ``red`` flagged ``after_yellow`` (a straight red
  after a booking, or a second yellow the provider listed with one line only: the list does not say, so it is not guessed).
* **A VAR decision that takes a goal away leaves no goal to point at.** For 2,251 of the 2,253 sides with a ``Goal cancelled`` /
  ``Goal Disallowed`` decision the provider's goals ARE the score: it removes the goal and keeps the decision. The decision is a fact of
  the match on its own (a goal disallowed at minute m, for this side); there is no line to link it to.
* **Some lines name nobody.** 3,303 ``Normal Goal`` (of 90,175 in the last 400 days), 63 own goals and 331 penalties, converted or missed
  (the kicks of the recent shoot-outs among them), have neither a player id nor a name. They are goals all the same (they are in the
  score), but they cannot be given to a man: the line says ``no_player`` and the layer of the players says how many it could not attribute.
* **The period is not the minute.** ``minute`` is the minute of the clock: stoppage time is ``minute = 45`` (or 90, 105, 120) with an
  ``extra_minute``, and 73 matches that ended in regular time still carry minutes above 90 (164 events). A minute above 90 is extra time
  only in a match that WENT to extra time (the caller knows: ``AET``, ``PEN``); in any other it is the second half's stoppage time.

Pure functions: nothing here reads the database or the clock. ``normalize`` is deterministic (the same list, the same answer) and
idempotent: normalizing the events again changes nothing, which is what lets the Match Knowledge be rebuilt at will.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

VERSION: Final = "events-v1"

# ── kinds ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

GOAL: Final = "goal"
OWN_GOAL: Final = "own_goal"
PENALTY_GOAL: Final = "penalty_goal"
PENALTY_MISSED: Final = "penalty_missed"
SHOOTOUT_GOAL: Final = "shootout_goal"
SHOOTOUT_MISS: Final = "shootout_miss"
YELLOW: Final = "yellow"
SECOND_YELLOW: Final = "second_yellow"
RED: Final = "red"
CARD_UNKNOWN: Final = "card_unknown"
SUBSTITUTION: Final = "sub"
VAR_GOAL_CANCELLED: Final = "var_goal_cancelled"
VAR_GOAL_CONFIRMED: Final = "var_goal_confirmed"
VAR_PENALTY_AWARDED: Final = "var_penalty_awarded"
VAR_PENALTY_CANCELLED: Final = "var_penalty_cancelled"
VAR_CARD_UPGRADED: Final = "var_card_upgraded"
VAR_CARD_CANCELLED: Final = "var_card_cancelled"
VAR_CARD_REVIEWED: Final = "var_card_reviewed"
VAR_OTHER: Final = "var_other"
OTHER: Final = "other"

KINDS: Final = (
    GOAL, OWN_GOAL, PENALTY_GOAL, PENALTY_MISSED, SHOOTOUT_GOAL, SHOOTOUT_MISS, YELLOW, SECOND_YELLOW, RED, CARD_UNKNOWN, SUBSTITUTION,
    VAR_GOAL_CANCELLED, VAR_GOAL_CONFIRMED, VAR_PENALTY_AWARDED, VAR_PENALTY_CANCELLED, VAR_CARD_UPGRADED, VAR_CARD_CANCELLED,
    VAR_CARD_REVIEWED, VAR_OTHER, OTHER,
)

SCORING: Final = frozenset({GOAL, OWN_GOAL, PENALTY_GOAL})
"""The kinds that change the score of the match (regulation or extra time). A missed penalty and the kicks of a shoot-out do not."""
SHOOTOUT: Final = frozenset({SHOOTOUT_GOAL, SHOOTOUT_MISS})
DISMISSALS: Final = frozenset({RED, SECOND_YELLOW})
"""A man sent off, however it came about."""

# ── periods ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

FIRST_HALF: Final = "1H"
SECOND_HALF: Final = "2H"
EXTRA_TIME: Final = "ET"
PENALTIES: Final = "PEN"
PERIODS: Final = (FIRST_HALF, SECOND_HALF, EXTRA_TIME, PENALTIES)

HALF_TIME_MINUTE: Final = 45
FULL_TIME_MINUTE: Final = 90
SHOOTOUT_COMMENT: Final = "penalty shootout"

# ── flags ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

FLAG_AFTER_YELLOW: Final = "after_yellow"
"""A red of a man who was booked at another minute: a straight red or a second yellow listed with one line (the list does not say)."""
FLAG_SECOND_OF_PAIR: Final = "second_of_pair"
"""The yellow that, with the red of the same minute, is a dismissal for two yellows."""
FLAG_LATE_MINUTE: Final = "late_minute"
"""A minute above 90 in a match that did not go to extra time: stoppage time of the second half."""
FLAG_MINUTE_OUT_OF_RANGE: Final = "minute_out_of_range"
"""A minute above 120 (the provider's junk): kept, counted in the period of the match's last stretch."""
FLAG_UNKNOWN_DETAIL: Final = "unknown_detail"
FLAG_NO_SIDE: Final = "no_side"
"""The provider's team is neither the home nor the away side of the match (0.07 % of the events)."""
FLAG_NO_PLAYER: Final = "no_player"
"""A goal, a missed penalty, a kick of a shoot-out or a card with neither a player id nor a name: it counts, but it is nobody's."""

NAMES_A_MAN: Final = frozenset({GOAL, OWN_GOAL, PENALTY_GOAL, PENALTY_MISSED, SHOOTOUT_GOAL, SHOOTOUT_MISS, YELLOW, SECOND_YELLOW, RED})
"""The kinds whose line is about one man, so that a line with no man is worth a flag."""

_VAR_KINDS: Final[dict[str, str]] = {
    "goal cancelled": VAR_GOAL_CANCELLED,
    "goal disallowed": VAR_GOAL_CANCELLED,
    "goal disallowed - offside": VAR_GOAL_CANCELLED,
    "goal disallowed - foul": VAR_GOAL_CANCELLED,
    "goal disallowed - handball": VAR_GOAL_CANCELLED,
    "goal disallowed - video review": VAR_GOAL_CANCELLED,
    "goal confirmed": VAR_GOAL_CONFIRMED,
    "penalty awarded": VAR_PENALTY_AWARDED,
    "penalty confirmed": VAR_PENALTY_AWARDED,
    "penalty cancelled": VAR_PENALTY_CANCELLED,
    "card upgrade": VAR_CARD_UPGRADED,
    "card upgrade confirmed": VAR_CARD_UPGRADED,
    "card upgrade cancelled": VAR_CARD_CANCELLED,
    "red card cancelled": VAR_CARD_CANCELLED,
    "card reviewed": VAR_CARD_REVIEWED,
    "red card confirmed": VAR_CARD_REVIEWED,
}
"""What each ``Var / <detail>`` the provider uses means (lower case). A detail not here is ``var_other``."""


# ── the line, as the provider gave it, and as it is read ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RawEvent:
    """One line of ``core.fixture_events``."""

    seq: int
    minute: int
    extra_minute: int | None
    side: str | None
    event_type: str
    detail: str | None = None
    comments: str | None = None
    player_id: int | None = None
    player_name: str | None = None
    assist_id: int | None = None
    assist_name: str | None = None


@dataclass(frozen=True, slots=True)
class Event:
    """A line of the provider's list, read: what it is, when in the match, whose it is."""

    seq: int
    kind: str
    period: str
    minute: int
    extra_minute: int | None
    side: str | None
    """The side the provider filed the line under. For a goal that is the side whose score it counts for - also for an own goal."""
    player_side: str | None
    """The side of the man the line is about: ``side``, except in an own goal (the other one)."""
    player_id: int | None
    player_name: str | None
    assist_id: int | None
    assist_name: str | None
    """In a substitution: the player who goes OFF is ``player_*`` and the one who comes ON is ``assist_*`` (the provider's way: 97.5 % of
    the sampled ``player`` were starters and 99.9 % of the ``assist`` were on the bench)."""
    detail: str | None
    comments: str | None
    pair_seq: int | None = None
    """The other line of a dismissal for two yellows (the yellow, from the red, and the red, from the yellow)."""
    flags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """A compact form for the stored layer: keys with no value are left out."""
        full: dict[str, Any] = {
            "seq": self.seq, "kind": self.kind, "period": self.period, "minute": self.minute, "extra": self.extra_minute,
            "side": self.side, "player_side": self.player_side if self.player_side != self.side else None,
            "player": self.player_id, "name": self.player_name, "assist": self.assist_id, "assist_name": self.assist_name,
            "pair": self.pair_seq, "flags": list(self.flags) or None,
        }
        return {k: v for k, v in full.items() if v is not None}


# ── one line ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def kind_of(event_type: str | None, detail: str | None, comments: str | None) -> tuple[str, bool]:
    """What a line is - ``(kind, known)``; ``known`` is False when the provider used words this table has not met (the line is then
    ``other`` or ``card_unknown`` / ``var_other``, never a guess). A card is ``yellow``, ``red`` or ``second_yellow`` here; the red of a
    pair is turned into ``second_yellow`` by ``normalize``, which sees the whole list."""
    kind = (event_type or "").strip().lower()
    what = (detail or "").strip().lower()
    shootout = (comments or "").strip().lower() == SHOOTOUT_COMMENT
    if kind == "goal":
        if what == "normal goal":
            return GOAL, True
        if what == "penalty":
            return (SHOOTOUT_GOAL if shootout else PENALTY_GOAL), True
        if what == "missed penalty":
            return (SHOOTOUT_MISS if shootout else PENALTY_MISSED), True
        if what == "own goal":
            return OWN_GOAL, True
        return OTHER, False
    if kind == "card":
        if what == "yellow card":
            return YELLOW, True
        if what == "red card":
            return RED, True
        if what in ("second yellow card", "second yellow"):
            return SECOND_YELLOW, True
        return CARD_UNKNOWN, False
    if kind == "subst":
        return SUBSTITUTION, True
    if kind == "var":
        known = _VAR_KINDS.get(what)
        return (known, True) if known else (VAR_OTHER, False)
    return OTHER, False


def period_of(minute: int, *, shootout: bool, extra_time: bool) -> tuple[str, tuple[str, ...]]:
    """The period of a line and the flags its minute earns. ``extra_time``: the match went to extra time (``AET`` / ``PEN``)."""
    if shootout:
        return PENALTIES, ()
    if minute <= HALF_TIME_MINUTE:
        return FIRST_HALF, ()
    if minute <= FULL_TIME_MINUTE:
        return SECOND_HALF, ()
    if extra_time:
        return EXTRA_TIME, (FLAG_MINUTE_OUT_OF_RANGE,) if minute > 120 else ()
    return SECOND_HALF, (FLAG_LATE_MINUTE,)


def _is_shootout(raw: RawEvent) -> bool:
    return (raw.comments or "").strip().lower() == SHOOTOUT_COMMENT


# ── the list ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def normalize(raws: Iterable[RawEvent], *, extra_time: bool) -> list[Event]:
    """The events of a match, read - in the provider's order (``seq``). Nothing is dropped and nothing is invented: every line of the list
    comes out as one ``Event``; the pairs of a second yellow are linked; a line with words this table has not met keeps them and says so."""
    lines = sorted(raws, key=lambda r: r.seq)
    kinds: dict[int, str] = {}
    flags: dict[int, list[str]] = {}
    pair: dict[int, int] = {}
    for raw in lines:
        kind, known = kind_of(raw.event_type, raw.detail, raw.comments)
        kinds[raw.seq] = kind
        flags[raw.seq] = [] if known else [FLAG_UNKNOWN_DETAIL]
        if raw.side not in ("home", "away"):
            flags[raw.seq].append(FLAG_NO_SIDE)
    # a dismissal for two yellows: a red and a yellow of the same man, side and minute, in the order the provider listed them (the yellow
    # first: 18,676) or the other (50)
    yellows: dict[tuple[int, int], list[RawEvent]] = {}
    booked: dict[int, set[int]] = {}
    for raw in lines:
        if raw.player_id is not None and kinds[raw.seq] == YELLOW:
            yellows.setdefault((raw.player_id, raw.minute), []).append(raw)
            booked.setdefault(raw.player_id, set()).add(raw.minute)
    for raw in lines:
        if raw.player_id is None or kinds[raw.seq] != RED:
            continue
        mates = [y for y in yellows.get((raw.player_id, raw.minute), []) if y.seq not in pair and y.side == raw.side]
        earlier = [y for y in mates if y.seq < raw.seq]
        yellow = earlier[-1] if earlier else (mates[0] if mates else None)
        if yellow is not None:
            kinds[raw.seq] = SECOND_YELLOW
            pair[raw.seq], pair[yellow.seq] = yellow.seq, raw.seq
            flags[yellow.seq].append(FLAG_SECOND_OF_PAIR)
        elif any(m < raw.minute for m in booked.get(raw.player_id, ())):
            flags[raw.seq].append(FLAG_AFTER_YELLOW)
    for raw in lines:
        if kinds[raw.seq] in NAMES_A_MAN and raw.player_id is None and not (raw.player_name or "").strip():
            flags[raw.seq].append(FLAG_NO_PLAYER)
    out: list[Event] = []
    for raw in lines:
        kind = kinds[raw.seq]
        period, minute_flags = period_of(raw.minute, shootout=_is_shootout(raw), extra_time=extra_time)
        player_side = raw.side
        if kind == OWN_GOAL and raw.side in ("home", "away"):
            player_side = "away" if raw.side == "home" else "home"
        out.append(Event(
            seq=raw.seq, kind=kind, period=period, minute=raw.minute, extra_minute=raw.extra_minute, side=raw.side,
            player_side=player_side, player_id=raw.player_id, player_name=raw.player_name, assist_id=raw.assist_id,
            assist_name=raw.assist_name, detail=raw.detail, comments=raw.comments, pair_seq=pair.get(raw.seq),
            flags=tuple(flags[raw.seq]) + minute_flags))
    return out


# ── what a list says ─────────────────────────────────────────────────────────────────────────────────────────────────────


def goals_by_period(events: Sequence[Event]) -> dict[str, dict[str, int]]:
    """The goals of the scoreboard in each period (``1H``, ``2H``, ``ET``) and the converted kicks of the shoot-out (``PEN``), by the side
    they count for: ``{"1H": {"home": 1, "away": 0}, ...}``. A goal filed under no side is left out (``data_quality`` counts it)."""
    out: dict[str, dict[str, int]] = {p: {"home": 0, "away": 0} for p in PERIODS}
    for e in events:
        if e.side not in ("home", "away"):
            continue
        if e.kind in SCORING or e.kind == SHOOTOUT_GOAL:
            out[e.period][e.side] += 1
    return out


def regulation_goals(events: Sequence[Event]) -> tuple[int, int]:
    """Goals of the 90 minutes (both halves, stoppage time included), home and away."""
    by = goals_by_period(events)
    return by[FIRST_HALF]["home"] + by[SECOND_HALF]["home"], by[FIRST_HALF]["away"] + by[SECOND_HALF]["away"]


def counts(events: Sequence[Event]) -> dict[str, int]:
    """How many lines of each kind (only the kinds that appear), in the order of ``KINDS``."""
    seen = Counter(e.kind for e in events)
    return {k: seen[k] for k in KINDS if seen[k]}
