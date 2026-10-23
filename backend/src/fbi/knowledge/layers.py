"""Match Knowledge, layer by layer (plan F7, ``mk-v1``): a finished match as ONE object, built by rules from facts already stored.

When a match ends, what PrediGol knows about it is spread over a dozen tables written by different jobs at different moments. This module
puts it side by side, in nine layers, each saying what it is made of (``sources``), how fresh it is (``known_at``) and how far it can be
trusted (``status``). Nothing is invented and nothing is guessed: a layer that cannot be built says ``missing``, one that is built from less
than it needs says ``partial`` and why (``notes``), and the layer of the external context is ``off`` until the owner decides otherwise.

    c1_result        the score at the break, at 90 minutes, after extra time and from the spot; how the match was decided; the corrections the
                     provider made afterwards; the tie it was a leg of (and who went through, only if this leg closed it)
    c2_team_stats    the statistics of each team: shots, corners, fouls, cards, possession, passes, expected goals
    c3_events        the goals, cards, VAR decisions and shoot-out kicks by period (``fbi.knowledge.events``), and whether those lists give the
                     score the match ended with (the lists are the provider's, and in 0.3 % of the matches they do not)
    c4_players       who played, who started, who came on, the best rated, the captain - a few men, not the squad
    c5_tactics       the formation and the coach of each side, the substitutions with the score at that moment, and the story of the score
                     (who scored first, who led, how many minutes each side was ahead, the first dismissal and the score then)
    c6_market        the consensus probability of each market a week before kick-off and at the last snapshot before it, with the books and the
                     minutes to the kick-off of that snapshot: what the market expected and what it came to expect; and, when the provider
                     still had them after the match, its last pre-match prices (``final``: the middle of the bookmakers', nearer to the
                     kick-off than the snapshot is) - the only word on the market for a match the worker was down for
    c7_context       the external context of the match (the news, the AI's reading afterwards): OFF, decided by the owner
    c8_picks         what PrediGol's decision layer made of each line at its last checkpoint and how it ended, and its shadow picks by market
    c9_postmortem    the post-mortems of those decisions: the result against the decision, the verdict and the causes

The object is for a match that is OVER. No reader of a pre-match moment may use it (``tests/unit/test_knowledge_isolation.py``).

Pure functions: nothing here reads the database or the clock. ``build`` is deterministic (the same ``Inputs``, the same ``Knowledge``) and
its ``content_hash`` leaves out the moments (``known_at``), so that reading the same facts again, later, says the same thing. What each input
is and how it is read from the database is in ``fbi.knowledge.reader``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

from fbi.knowledge import events as ev
from fbi.people import sides

VERSION: Final = "mk-v1"
RULES: Final[dict[str, str]] = {"layers": VERSION, "events": ev.VERSION, "sides": sides.VERSION}
"""The versions of the rules a build applied: part of what a build read (``inputs_hash``), so that changing a rule rebuilds what it touches."""

# ── statuses ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

OK: Final = "ok"
PARTIAL: Final = "partial"
MISSING: Final = "missing"
OFF: Final = "off"
STATUSES: Final = (OK, PARTIAL, MISSING, OFF)

COMPLETE: Final = "complete"
MINIMAL: Final = "minimal"
COMPLETENESS: Final = (COMPLETE, PARTIAL, MINIMAL)
"""How much of the match the object holds: ``complete`` (the result, the statistics, the events and the players, all trustworthy),
``minimal`` (the result alone, or not even that), ``partial`` (anything between)."""

C1_RESULT: Final = "c1_result"
C2_TEAM_STATS: Final = "c2_team_stats"
C3_EVENTS: Final = "c3_events"
C4_PLAYERS: Final = "c4_players"
C5_TACTICS: Final = "c5_tactics"
C6_MARKET: Final = "c6_market"
C7_CONTEXT: Final = "c7_context"
C8_PICKS: Final = "c8_picks"
C9_POSTMORTEM: Final = "c9_postmortem"
LAYERS: Final = (C1_RESULT, C2_TEAM_STATS, C3_EVENTS, C4_PLAYERS, C5_TACTICS, C6_MARKET, C7_CONTEXT, C8_PICKS, C9_POSTMORTEM)
FACT_LAYERS: Final = (C2_TEAM_STATS, C3_EVENTS, C4_PLAYERS)
"""The layers a match needs to be ``complete`` besides its result: what the provider says happened in it."""

EXTRA_TIME_STATUSES: Final = frozenset({"AET", "PEN"})
REGULATION: Final = 90
OPENING_LOOKBACK_DAYS: Final = 7
"""The opening of a market is its first consensus in the week before kick-off: a fixed reference, the packet's (``fbi.ai.packet``)."""
TOP_DECISIONS: Final = 5
TOP_PLAYERS: Final = 3
MARKETS: Final = ("1X2", "OU", "BTTS", "AH")
OVER_UNDER_MAIN: Final = Decimal("2.5")

TEAM_STAT_KEYS: Final[dict[str, str]] = {
    "shots": "shots", "shots_on_target": "on_target", "shots_off_target": "off_target", "shots_blocked": "blocked",
    "shots_inside_box": "in_box", "shots_outside_box": "out_box", "corners": "corners", "fouls": "fouls", "offsides": "offsides",
    "yellow_cards": "yellow", "red_cards": "red", "saves": "saves", "possession_pct": "possession", "passes": "passes",
    "passes_accurate": "passes_ok", "expected_goals": "xg", "goals_prevented": "prevented",
}
"""The columns of ``core.fixture_team_stats`` that the layer keeps, with the short name it keeps them under."""

STATE_RANK: Final[dict[str, int]] = {
    "PICK_PREMIUM": 0, "PICK_DEL_DIA": 1, "APROBADO": 2, "CANDIDATO_PARLAY": 3, "CAUTELA": 4, "INVESTIGACION": 5, "RECHAZADO": 6,
}
"""The decision layer's states, from the one that matters most to the one that matters least."""
LEAN_STATES: Final = frozenset({"PICK_PREMIUM", "PICK_DEL_DIA", "APROBADO", "CANDIDATO_PARLAY", "CAUTELA"})
"""The states that name a line PrediGol would back (at any stake): the rest were rejected or sent to be investigated."""

_PERIOD_RANK: Final = {ev.FIRST_HALF: 0, ev.SECOND_HALF: 1, ev.EXTRA_TIME: 2, ev.PENALTIES: 3}


# ── inputs ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Fixture:
    id: int
    kickoff_at: datetime
    status: str
    """``status_short``: FT, AET, PEN, AWD, WO..."""
    home_team_id: int
    away_team_id: int
    neutral: bool = False
    leg: int | None = None
    tie_id: int | None = None


@dataclass(frozen=True, slots=True)
class Result:
    """A row of ``core.fixture_results``: ``goals_*`` is the final score with extra time (a shoot-out is not in it), ``reg_*`` the score of
    the 90 minutes the markets settle on."""

    goals_home: int
    goals_away: int
    reg_home: int
    reg_away: int
    settled_at: datetime
    ht_home: int | None = None
    ht_away: int | None = None
    et_home: int | None = None
    et_away: int | None = None
    pen_home: int | None = None
    pen_away: int | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Revision:
    """A correction the provider made to a finished result (``core.fixture_result_revisions``)."""

    observed_at: datetime
    kind: str
    changed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Tie:
    id: int
    format: str
    status: str
    legs: int
    team_a_id: int
    team_b_id: int
    aggregate_a: int | None = None
    aggregate_b: int | None = None
    winner_team_id: int | None = None
    decided_by: str | None = None
    shootout_a: int | None = None
    shootout_b: int | None = None
    winner_check: str | None = None


@dataclass(frozen=True, slots=True)
class TeamStats:
    """A side's row of ``core.fixture_team_stats``: ``values`` by the column's name."""

    side: str
    values: Mapping[str, float | int | None]
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class PlayerStat:
    """A man's row of ``core.fixture_player_stats``. The statistics put every man on his side, also when the squad sheet was crossed."""

    player_id: int
    side: str
    name: str | None
    minutes: int | None
    rating: float | None
    captain: bool
    substitute: bool
    goals: int | None = None
    assists: int | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Lineup:
    """A side's squad sheet: its formation and coach (``core.fixture_lineups``)."""

    side: str
    formation: str | None
    coach_id: int | None
    coach_name: str | None
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class Quote:
    """A consensus probability (Shin) of a selection at a snapshot (``market.market_consensus``)."""

    market: str
    selection: str
    line: Decimal
    p_fair: float
    books: int
    as_of: datetime


@dataclass(frozen=True, slots=True)
class FinalQuote:
    """The provider's last pre-match price of a selection (``market.final_prematch_odds``): the price in the middle of the bookmakers' - the
    lower median, so a price somebody quoted - and how many of them quoted it. ``as_of`` is the provider's own stamp (before kick-off) and
    ``fetched_at`` the moment it was read (after the match: that is when it became known)."""

    market: str
    selection: str
    line: Decimal
    odds: float
    books: int
    as_of: datetime
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class Decision:
    """A decision of the decision layer at a checkpoint (``intel.decisions``), and what became of it if it did."""

    id: int
    checkpoint: str
    market: str
    selection: str
    line: Decimal
    state: str
    known_at: datetime
    score: float | None = None
    odds: float | None = None
    p_cal: float | None = None
    edge_cal: float | None = None
    stake: float = 0.0
    result: str | None = None
    profit: float | None = None
    """The profit of one flat unit on the decision (``intel.decision_outcomes.profit_flat``), whatever stake it carried."""
    clv: float | None = None
    outcome_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PickTally:
    """The shadow picks of one market that ended one way (``pending`` while not settled): how many and their profit in units."""

    market: str
    result: str
    n: int
    profit: float
    settled_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Postmortem:
    """A post-mortem of a decision (``intel.postmortems``)."""

    id: int
    decision_id: int
    version: str
    outcome: str
    quality: str
    verdict: str
    created_at: datetime
    causes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Inputs:
    """Everything the layers are built from, as stored. Absent things are empty, never invented."""

    fixture: Fixture
    result: Result | None = None
    revisions: Sequence[Revision] = ()
    tie: Tie | None = None
    team_stats: Sequence[TeamStats] = ()
    events: Sequence[ev.RawEvent] = ()
    events_fetched_at: datetime | None = None
    players: Sequence[PlayerStat] = ()
    lineups: Sequence[Lineup] = ()
    sheets_crossed: bool = False
    """The statistics put the squad sheets on the other side (``fbi.people.sides``): the formation of a crossed sheet is not used."""
    open_quotes: Sequence[Quote] = ()
    close_quotes: Sequence[Quote] = ()
    final_quotes: Sequence[FinalQuote] = ()
    decisions: Sequence[Decision] = ()
    picks: Sequence[PickTally] = ()
    postmortems: Sequence[Postmortem] = ()


@dataclass(frozen=True, slots=True)
class Knowledge:
    """What is known of a finished match: the layers, what could not be said, how complete it is, and the hash of all that."""

    version: str
    layers: dict[str, dict[str, Any]]
    quality: dict[str, Any]
    completeness: str
    known_at: datetime
    content_hash: str
    events: tuple[ev.Event, ...] = ()
    """The lines of the provider's list, read (``core.fixture_event_kinds`` keeps them)."""


# ── small things ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def iso(moment: datetime | None) -> str | None:
    """A moment as the text the layers keep: UTC, to the second."""
    return None if moment is None else moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def newest(*moments: datetime | None) -> datetime | None:
    seen = [m for m in moments if m is not None]
    return max(seen) if seen else None


def canonical(value: Any) -> str:
    """The one text a value is hashed as: keys sorted, no spaces, no NaN."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def signature_hash(signature: Mapping[str, Any]) -> str:
    """The ``inputs_hash``: the fingerprint of what a build read (``fbi.knowledge.reader.signatures``), canonical and hashed."""
    return digest(canonical(signature))


def content_hash(layers: Mapping[str, Mapping[str, Any]], quality: Mapping[str, Any], completeness: str) -> str:
    """What the object SAYS, not when it was known: the moments are left out, so reading the same facts again later changes nothing."""
    kept = {name: {k: v for k, v in layer.items() if k != "known_at"} for name, layer in layers.items()}
    return digest(canonical({"layers": kept, "quality": quality, "completeness": completeness}))


def _layer(status: str, *, known_at: datetime | None = None, sources: Sequence[str] = (), data: Mapping[str, Any] | None = None,
           notes: Sequence[str] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status}
    if known_at is not None:
        out["known_at"] = iso(known_at)
    if sources:
        out["sources"] = list(sources)
    if data:
        out["data"] = dict(data)
    if notes:
        out["notes"] = list(notes)
    return out


def _round(value: float | int | Decimal | None, places: int) -> float | None:
    return None if value is None else round(float(value), places)


def _stat(value: float | int | None) -> float | int | None:
    """A statistic as kept: whole numbers stay whole, the rest to two decimals."""
    if value is None:
        return None
    return value if isinstance(value, int) else round(float(value), 2)


def _pair(a: int | None, b: int | None) -> list[int] | None:
    return None if a is None or b is None else [a, b]


def went_to_extra_time(fixture: Fixture) -> bool:
    """The provider's status says the match went to extra time (``AET``) or to the spot after it (``PEN``)."""
    return fixture.status in EXTRA_TIME_STATUSES


def chronological(events: Sequence[ev.Event]) -> list[ev.Event]:
    """The lines in the order things happened: by period, then by the clock (stoppage time after the minute), then by the provider's order.
    The provider's own order is not chronological inside the stoppage time."""
    return sorted(events, key=lambda e: (_PERIOD_RANK[e.period], e.minute, e.extra_minute or 0, e.seq))


# ── c1: the result ───────────────────────────────────────────────────────────────────────────────────────────────────────


def tie_block(fixture: Fixture, tie: Tie) -> dict[str, Any]:
    """The tie this match was a leg of. What the tie came to is told only by the leg that closed it: a first leg says it was the first of
    two and nothing of what happened later (so a leg's knowledge does not change when another leg is played)."""
    out: dict[str, Any] = {"format": tie.format, "legs": tie.legs}
    if fixture.leg is not None:
        out["leg"] = fixture.leg
    closes_it = fixture.leg == tie.legs if fixture.leg is not None else tie.legs == 1
    if not closes_it or tie.status != "decided":
        return out
    home_is_a = fixture.home_team_id == tie.team_a_id

    def toward(a: int | None, b: int | None) -> list[int] | None:
        return None if a is None or b is None else ([a, b] if home_is_a else [b, a])

    if (aggregate := toward(tie.aggregate_a, tie.aggregate_b)) is not None:
        out["aggregate"] = aggregate
    if tie.winner_team_id is not None and tie.winner_team_id in (fixture.home_team_id, fixture.away_team_id):
        out["winner"] = "home" if tie.winner_team_id == fixture.home_team_id else "away"
    if tie.decided_by:
        out["decided_by"] = tie.decided_by
    if (shootout := toward(tie.shootout_a, tie.shootout_b)) is not None:
        out["shootout"] = shootout
    if tie.winner_check == "contradicted":
        out["contradicted"] = True
    return out


def outcome_of(home: int, away: int) -> str:
    return "Home" if home > away else "Draw" if home == away else "Away"


def c1_result(inp: Inputs) -> dict[str, Any]:
    fx, r = inp.fixture, inp.result
    head: dict[str, Any] = {"status": fx.status, "kickoff": iso(fx.kickoff_at)}
    if r is None:
        return _layer(MISSING, sources=["core.fixtures"], data=head, notes=["no_result_row"])
    extra = went_to_extra_time(fx)
    data: dict[str, Any] = {
        **head, "reg": [r.reg_home, r.reg_away], "outcome": outcome_of(r.reg_home, r.reg_away), "total": r.reg_home + r.reg_away,
        "btts": r.reg_home > 0 and r.reg_away > 0,
        "decided_by": "penalties" if r.pen_home is not None or fx.status == "PEN" else "extra_time" if extra else "regulation",
    }
    notes: list[str] = []
    if (ht := _pair(r.ht_home, r.ht_away)) is not None:
        data["ht"] = ht
    else:
        notes.append("no_half_time")
    if extra:
        data["final"] = [r.goals_home, r.goals_away]
    if (pens := _pair(r.pen_home, r.pen_away)) is not None:
        data["pen"] = pens
    if fx.neutral:
        data["neutral"] = True
    sources = ["core.fixtures", "core.fixture_results"]
    if inp.revisions:
        sources.append("core.fixture_result_revisions")
        data["revisions"] = {
            "n": len(inp.revisions), "last": iso(max(v.observed_at for v in inp.revisions)),
            "kinds": sorted({v.kind for v in inp.revisions}), "fields": sorted({c for v in inp.revisions for c in v.changed}),
        }
    if inp.tie is not None:
        sources.append("core.ties")
        data["tie"] = tie_block(fx, inp.tie)
    known = newest(r.settled_at, r.fetched_at, *(v.observed_at for v in inp.revisions))
    return _layer(OK, known_at=known, sources=sources, data=data, notes=notes)


# ── c2: the statistics of the teams ──────────────────────────────────────────────────────────────────────────────────────


def c2_team_stats(inp: Inputs) -> dict[str, Any]:
    rows = {t.side: t for t in inp.team_stats if t.side in sides.SIDES}
    sources = ["core.fixture_team_stats"]
    if not rows:
        return _layer(MISSING, sources=sources)
    data: dict[str, Any] = {}
    for side in sides.SIDES:
        row = rows.get(side)
        if row is None:
            continue
        kept = {short: _stat(row.values.get(column)) for column, short in TEAM_STAT_KEYS.items() if row.values.get(column) is not None}
        if kept:
            data[side] = kept
    known = newest(*(t.fetched_at for t in rows.values()))
    if len(data) == len(sides.SIDES):
        return _layer(OK, known_at=known, sources=sources, data=data)
    if not data:
        return _layer(MISSING, known_at=known, sources=sources, notes=["no_figures"])
    absent = [s for s in sides.SIDES if s not in data]
    return _layer(PARTIAL, known_at=known, sources=sources, data=data, notes=[f"no_{s}" for s in absent])


# ── c3: the events ───────────────────────────────────────────────────────────────────────────────────────────────────────

_LISTED_AS_GOALS: Final = ev.SCORING
_CARD_KINDS: Final = frozenset({ev.YELLOW, ev.SECOND_YELLOW, ev.RED, ev.CARD_UNKNOWN})
_VAR_KINDS: Final = frozenset({
    ev.VAR_GOAL_CANCELLED, ev.VAR_GOAL_CONFIRMED, ev.VAR_PENALTY_AWARDED, ev.VAR_PENALTY_CANCELLED, ev.VAR_CARD_UPGRADED,
    ev.VAR_CARD_CANCELLED, ev.VAR_CARD_REVIEWED, ev.VAR_OTHER,
})


def event_checks(inp: Inputs, events: Sequence[ev.Event]) -> dict[str, Any]:
    """Do the lists of the provider say what the result says? ``True`` they do, ``False`` they do not, ``None`` it cannot be told (the
    result, the break, the extra time or the kicks of the shoot-out are not there to compare with). ``listed`` is what the list says of
    the 90 minutes, only when it differs."""
    r = inp.result
    by = ev.goals_by_period(events)
    check: dict[str, Any] = {"reg": None, "ht": None, "et": None, "pen": None, "cards": None}
    if r is None:
        return check
    listed = ev.regulation_goals(events)
    check["reg"] = listed == (r.reg_home, r.reg_away)
    if check["reg"] is False:
        check["listed"] = list(listed)
    if r.ht_home is not None and r.ht_away is not None:
        check["ht"] = (by[ev.FIRST_HALF]["home"], by[ev.FIRST_HALF]["away"]) == (r.ht_home, r.ht_away)
    if went_to_extra_time(inp.fixture):
        check["et"] = (by[ev.EXTRA_TIME]["home"], by[ev.EXTRA_TIME]["away"]) == (r.goals_home - r.reg_home, r.goals_away - r.reg_away)
    if r.pen_home is not None and r.pen_away is not None and any(e.kind in ev.SHOOTOUT for e in events):
        check["pen"] = (by[ev.PENALTIES]["home"], by[ev.PENALTIES]["away"]) == (r.pen_home, r.pen_away)
    stats = {t.side: t for t in inp.team_stats}
    if all(side in stats for side in sides.SIDES):
        compared: list[bool] = []
        for side in sides.SIDES:
            yellow = sum(1 for e in events if e.kind == ev.YELLOW and e.side == side)
            red = sum(1 for e in events if e.kind in ev.DISMISSALS and e.side == side)
            for stated, listed_n in ((stats[side].values.get("yellow_cards"), yellow), (stats[side].values.get("red_cards"), red)):
                if stated is not None:
                    compared.append(stated == listed_n)
        check["cards"] = all(compared) if compared else None
    return check


def c3_events(inp: Inputs, events: Sequence[ev.Event], check: Mapping[str, Any]) -> dict[str, Any]:
    sources = ["core.fixture_events"]
    if not events:
        return _layer(MISSING, sources=sources, notes=["no_events"])
    extra = went_to_extra_time(inp.fixture)
    by = ev.goals_by_period(events)
    ordered = chronological(events)
    periods: dict[str, list[int]] = {
        ev.FIRST_HALF: [by[ev.FIRST_HALF]["home"], by[ev.FIRST_HALF]["away"]],
        ev.SECOND_HALF: [by[ev.SECOND_HALF]["home"], by[ev.SECOND_HALF]["away"]],
    }
    if extra:
        periods[ev.EXTRA_TIME] = [by[ev.EXTRA_TIME]["home"], by[ev.EXTRA_TIME]["away"]]
    if any(e.kind in ev.SHOOTOUT for e in events):
        periods[ev.PENALTIES] = [by[ev.PENALTIES]["home"], by[ev.PENALTIES]["away"]]
    data: dict[str, Any] = {
        "rules": ev.VERSION, "n": len(events), "counts": ev.counts(events), "by_period": periods,
        "check": {k: v for k, v in check.items() if v is not None},
    }
    for key, kinds in (("goals", _LISTED_AS_GOALS), ("missed", frozenset({ev.PENALTY_MISSED})), ("shootout", ev.SHOOTOUT),
                       ("cards", _CARD_KINDS), ("var", _VAR_KINDS)):
        picked = [e.as_dict() for e in ordered if e.kind in kinds]
        if picked:
            data[key] = picked
    notes: list[str] = []
    wrong = [name for name in ("reg", "ht", "et", "pen") if check.get(name) is False]
    if check.get("reg") is None:
        notes.append("score_unknown")
    if check.get("reg") is False:
        notes.append("events_do_not_give_the_score")
    notes += [f"{name}_differs" for name in wrong if name != "reg"]
    if check.get("cards") is False:
        notes.append("cards_differ_from_the_statistics")
    unknown = sum(1 for e in events if ev.FLAG_UNKNOWN_DETAIL in e.flags)
    if unknown:
        notes.append("words_not_met")
    status = OK if check.get("reg") is True and not wrong else PARTIAL
    return _layer(status, known_at=inp.events_fetched_at, sources=sources, data=data, notes=notes)


# ── c4: the players ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _man(p: PlayerStat) -> dict[str, Any]:
    out: dict[str, Any] = {"p": p.player_id, "name": p.name, "rating": _round(p.rating, 1), "min": p.minutes,
                           "g": p.goals or None, "a": p.assists or None}
    return {k: v for k, v in out.items() if v is not None}


def c4_players(inp: Inputs, events: Sequence[ev.Event]) -> dict[str, Any]:
    sources = ["core.fixture_player_stats"]
    rows = [p for p in inp.players if p.side in sides.SIDES]
    if not rows:
        return _layer(MISSING, sources=sources)
    data: dict[str, Any] = {}
    notes: list[str] = []
    for side in sides.SIDES:
        mine = [p for p in rows if p.side == side]
        if not mine:
            notes.append(f"no_{side}")
            continue
        played = [p for p in mine if (p.minutes or 0) > 0]
        block: dict[str, Any] = {
            "listed": len(mine), "played": len(played), "started": sum(1 for p in played if not p.substitute),
            "came_on": sum(1 for p in played if p.substitute),
        }
        rated = sorted((p for p in played if p.rating is not None), key=lambda p: (-(p.rating or 0.0), -(p.minutes or 0), p.player_id))
        if rated:
            block["top"] = [_man(p) for p in rated[:TOP_PLAYERS]]
        captain = next((p for p in sorted(mine, key=lambda q: q.player_id) if p.captain), None)
        if captain is not None:
            block["captain"] = captain.player_id
        data[side] = block
    if not any(p.minutes for p in rows):
        notes.append("no_minutes")
    if not any(p.rating is not None for p in rows):
        notes.append("no_ratings")
    nobody = sum(1 for e in events if ev.FLAG_NO_PLAYER in e.flags and e.kind in ev.SCORING)
    if nobody:
        data["goals_with_no_player"] = nobody
    known = newest(*(p.fetched_at for p in rows))
    both = all(side in data for side in sides.SIDES)
    return _layer(OK if both and "no_minutes" not in notes else PARTIAL, known_at=known, sources=sources, data=data, notes=notes)


# ── c5: the tactics and the story of the score ───────────────────────────────────────────────────────────────────────────


def coach_key(coach_id: int | None, name: str | None) -> str | None:
    """A key for the coach of a sheet: his id when the sheet has one, else his name as written (``fbi.intel.tactics.coach_key`` says the
    same; a test holds them equal)."""
    if coach_id is not None:
        return f"id:{int(coach_id)}"
    text = " ".join(str(name or "").split()).lower()
    return f"name:{text}" if text else None


def story(events: Sequence[ev.Event]) -> tuple[dict[str, Any], dict[str, list[tuple[int, int]]]]:
    """How the score went in the 90 minutes, and each side's substitutions with the lead at that moment (from that side). The events must be
    known to give the score. Stoppage time counts as the 90th minute."""
    lead = 0
    prev = 0
    spent = {"home_ahead": 0, "level": 0, "away_ahead": 0}
    ahead = {"home": False, "away": False}
    first: dict[str, Any] | None = None
    sent_off: dict[str, Any] | None = None
    changes = 0
    last_sign = 0
    last_goal = None
    subs: dict[str, list[tuple[int, int]]] = {"home": [], "away": []}
    for e in chronological(events):
        if e.period not in (ev.FIRST_HALF, ev.SECOND_HALF):
            continue
        if e.kind in ev.SCORING and e.side in sides.SIDES:
            at = min(max(e.minute, 0), REGULATION)
            spent["home_ahead" if lead > 0 else "away_ahead" if lead < 0 else "level"] += max(at - prev, 0)
            prev = max(prev, at)
            lead += 1 if e.side == "home" else -1
            sign = (lead > 0) - (lead < 0)
            if sign:
                ahead["home" if sign > 0 else "away"] = True
                if last_sign and sign != last_sign:
                    changes += 1
                last_sign = sign
            if first is None:
                first = {"minute": e.minute, "side": e.side}
            last_goal = e.minute
        elif e.kind == ev.SUBSTITUTION and e.side in sides.SIDES:
            subs[e.side].append((e.minute, lead if e.side == "home" else -lead))
        elif e.kind in ev.DISMISSALS and sent_off is None and e.player_side in sides.SIDES:
            sent_off = {"minute": e.minute, "side": e.player_side, "lead": lead if e.player_side == "home" else -lead}
    spent["home_ahead" if lead > 0 else "away_ahead" if lead < 0 else "level"] += max(REGULATION - prev, 0)
    out: dict[str, Any] = {"ahead": ahead, "lead_changes": changes, "minutes": spent}
    if first is not None:
        out["first_goal"] = first
        out["last_goal"] = last_goal
    if sent_off is not None:
        out["first_dismissal"] = sent_off
    return out, subs


def c5_tactics(inp: Inputs, events: Sequence[ev.Event], check: Mapping[str, Any]) -> dict[str, Any]:
    sources = ["core.fixture_lineups", "core.fixture_events"]
    sheets = {s.side: s for s in inp.lineups if s.side in sides.SIDES}
    gives_the_score = check.get("reg") is True
    if not sheets and not events:
        return _layer(MISSING, sources=sources)
    data: dict[str, Any] = {}
    notes: list[str] = []
    story_data: dict[str, Any] = {}
    subs: dict[str, list[list[int | None]]] = {"home": [], "away": []}
    if events:
        if gives_the_score:
            story_data, told = story(events)
            subs = {side: [[minute, lead] for minute, lead in told[side]] for side in sides.SIDES}
        else:
            notes.append("story_not_told")
            for e in chronological(events):
                if e.kind == ev.SUBSTITUTION and e.side in sides.SIDES and e.period in (ev.FIRST_HALF, ev.SECOND_HALF):
                    subs[e.side].append([e.minute, None])
    for side in sides.SIDES:
        block: dict[str, Any] = {}
        sheet = sheets.get(side)
        if sheet is not None:
            formation = " ".join((sheet.formation or "").split())
            if formation and not inp.sheets_crossed:
                block["formation"] = formation
            if (coach := coach_key(sheet.coach_id, sheet.coach_name)) is not None:
                block["coach"] = coach
        if subs[side]:
            block["subs"] = subs[side]
        if block:
            data[side] = block
    if story_data:
        data["story"] = story_data
    if inp.sheets_crossed:
        notes.append("sheets_crossed")
    if not all("formation" in data.get(side, {}) for side in sides.SIDES):
        notes.append("formation_missing")
    if not data:
        return _layer(MISSING, sources=sources, notes=notes)
    known = newest(inp.events_fetched_at, *(s.fetched_at for s in sheets.values()))
    complete = bool(sheets) and bool(events) and gives_the_score and "formation_missing" not in notes
    return _layer(OK if complete else PARTIAL, known_at=known, sources=sources, data=data, notes=notes)


# ── c6: the market ───────────────────────────────────────────────────────────────────────────────────────────────────────


def main_line(market: str, quotes: Sequence[Quote]) -> Decimal | None:
    """The line a market is read at: Over/Under 2.5 when it is quoted; otherwise the line the most books quote, and among those the one
    whose prices are closest to even (the rule of the odds board, ``fbi.api.services.product.main_line``). Markets with one line have it."""
    by_line: dict[Decimal, list[Quote]] = {}
    for q in quotes:
        by_line.setdefault(q.line, []).append(q)
    if not by_line:
        return None
    if market == "OU" and OVER_UNDER_MAIN in by_line:
        return OVER_UNDER_MAIN

    def rank(item: tuple[Decimal, list[Quote]]) -> tuple[int, float, Decimal]:
        line, rows = item
        return -max(q.books for q in rows), max(abs(q.p_fair - 0.5) for q in rows), abs(line)

    return min(by_line.items(), key=rank)[0]


def _minutes_before(kickoff: datetime, moment: datetime) -> int:
    return int((kickoff - moment).total_seconds() // 60)


def _close_block(market: str, line: Decimal, opening: Sequence[Quote], closing: Sequence[Quote], kickoff: datetime) -> dict[str, Any]:
    """What the consensus said of the market at ``line``: from its first reading of the week to its last before kick-off."""
    close = {q.selection: q for q in closing if q.market == market and q.line == line}
    start = {q.selection: q for q in opening if q.market == market and q.line == line}
    at = max(q.as_of for q in close.values())
    block: dict[str, Any] = {
        "p": {s: [_round(start[s].p_fair, 3) if s in start else None, _round(close[s].p_fair, 3)] for s in sorted(close)},
        "books": max(q.books for q in close.values()),
        "close_at": iso(at),
        "min_to_ko": _minutes_before(kickoff, at),
    }
    if start:
        block["open_at"] = iso(min(q.as_of for q in start.values()))
    return block


def _final_block(market: str, line: Decimal, last: Sequence[FinalQuote], kickoff: datetime) -> dict[str, Any] | None:
    """What the provider's last pre-match prices say of the market at ``line``: the price in the middle of the bookmakers' (not de-vigged: a
    price is a price), how many quoted it and how long before kick-off the provider last moved them. ``None`` when nobody quoted that line."""
    prices = {q.selection: q for q in last if q.market == market and q.line == line}
    if not prices:
        return None
    at = max(q.as_of for q in prices.values())
    return {"odds": {s: _round(prices[s].odds, 3) for s in sorted(prices)}, "books": max(q.books for q in prices.values()),
            "at": iso(at), "min_to_ko": _minutes_before(kickoff, at)}


def _final_line(market: str, last: Sequence[FinalQuote]) -> Decimal | None:
    """The line to read the last prices at when the consensus has none to say which: ``main_line``'s rule with the price in the place of the
    probability (how far from even a selection is, asked of 1 / price)."""
    return main_line(market, [Quote(q.market, q.selection, q.line, 1.0 / q.odds, q.books, q.as_of) for q in last])


def c6_market(inp: Inputs) -> dict[str, Any]:
    """The market, from the consensus (opening to closing) and from the provider's last pre-match prices (``final``): the second is read after
    the match, a median of the bookmakers' own prices, and the nearest to kick-off that is stored. A market has the line the consensus reads
    it at; when the consensus has nothing on it (the worker was down) the last prices alone say it."""
    sources = ["market.market_consensus", "market.final_prematch_odds"]
    kickoff = inp.fixture.kickoff_at
    data: dict[str, Any] = {}
    for market in MARKETS:
        closing = [q for q in inp.close_quotes if q.market == market]
        last = [q for q in inp.final_quotes if q.market == market]
        line = main_line(market, closing) if closing else _final_line(market, last)
        if line is None:
            continue
        block = _close_block(market, line, inp.open_quotes, inp.close_quotes, kickoff) if closing else {}
        if (final := _final_block(market, line, last, kickoff)) is not None:
            block["final"] = final
        if market in ("OU", "AH"):
            block["line"] = float(line)
        data[market] = block
    if not data:
        return _layer(MISSING, sources=sources)
    known = newest(*(q.as_of for q in inp.close_quotes), *(q.fetched_at for q in inp.final_quotes))
    wanted = ("1X2", "OU", "BTTS")
    absent = [m for m in wanted if m not in data]
    return _layer(OK if not absent else PARTIAL, known_at=known, sources=sources, data=data, notes=[f"no_{m}" for m in absent])


# ── c7: the external context ─────────────────────────────────────────────────────────────────────────────────────────────


def c7_context() -> dict[str, Any]:
    """OFF. The reading of a match after it (the news, the AI's account) is the owner's to switch on; until he does the layer says so."""
    return _layer(OFF, notes=["decided_by_the_owner"])


# ── c8: the picks ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _decision_line(d: Decision) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": d.id, "cp": d.checkpoint, "market": d.market, "sel": d.selection, "line": float(d.line), "state": d.state,
        "score": _round(d.score, 1), "odds": _round(d.odds, 2), "p": _round(d.p_cal, 3), "edge": _round(d.edge_cal, 3),
        "stake": _round(d.stake, 2) if d.stake else None, "result": d.result, "profit": _round(d.profit, 3), "clv": _round(d.clv, 3),
    }
    return {k: v for k, v in out.items() if v is not None}


def c8_picks(inp: Inputs) -> dict[str, Any]:
    sources = ["intel.decisions", "intel.decision_outcomes", "picks.picks", "picks.pick_results"]
    if not inp.decisions and not inp.picks:
        return _layer(MISSING, sources=sources)
    data: dict[str, Any] = {}
    notes: list[str] = []
    unsettled = False
    if inp.decisions:
        last: dict[tuple[str, str, Decimal], Decision] = {}
        for d in inp.decisions:
            key = (d.market, d.selection, d.line)
            held = last.get(key)
            if held is None or (d.known_at, d.id) > (held.known_at, held.id):
                last[key] = d
        states: dict[str, dict[str, int]] = {}
        for d in last.values():
            tally = states.setdefault(d.state, {"n": 0})
            tally["n"] += 1
            if d.result is not None:
                tally[d.result] = tally.get(d.result, 0) + 1
        lean = sorted((d for d in last.values() if d.state in LEAN_STATES),
                      key=lambda d: (STATE_RANK[d.state], -(d.score or 0.0), d.id))
        unsettled = any(d.result is None and d.odds is not None for d in lean)
        data["decisions"] = {"n": len(inp.decisions), "lines": len(last), "states": states}
        if lean:
            data["decisions"]["top"] = [_decision_line(d) for d in lean[:TOP_DECISIONS]]
    if inp.picks:
        by_market: dict[str, dict[str, Any]] = {}
        for t in inp.picks:
            block = by_market.setdefault(t.market, {"n": 0, "profit": 0.0})
            block["n"] += t.n
            block[t.result] = block.get(t.result, 0) + t.n
            block["profit"] = round(block["profit"] + t.profit, 3)
        data["picks"] = {"n": sum(t.n for t in inp.picks), "by_market": by_market}
        if any(t.result == "pending" for t in inp.picks):
            unsettled = True
    if unsettled:
        notes.append("not_settled_yet")
    known = newest(*(d.outcome_at for d in inp.decisions), *(t.settled_at for t in inp.picks),
                   *(d.known_at for d in inp.decisions))
    return _layer(PARTIAL if unsettled else OK, known_at=known, sources=sources, data=data, notes=notes)


# ── c9: the post-mortems ─────────────────────────────────────────────────────────────────────────────────────────────────


def c9_postmortem(inp: Inputs) -> dict[str, Any]:
    sources = ["intel.postmortems"]
    if not inp.postmortems:
        return _layer(MISSING, sources=sources)
    newest_of: dict[int, Postmortem] = {}
    for p in inp.postmortems:
        held = newest_of.get(p.decision_id)
        if held is None or (p.created_at, p.id) > (held.created_at, held.id):
            newest_of[p.decision_id] = p
    decisions = {d.id: d for d in inp.decisions}
    verdicts: dict[str, int] = {}
    qualities: dict[str, int] = {}
    for p in newest_of.values():
        verdicts[p.verdict] = verdicts.get(p.verdict, 0) + 1
        qualities[p.quality] = qualities.get(p.quality, 0) + 1

    def rank(p: Postmortem) -> tuple[int, float, int]:
        d = decisions.get(p.decision_id)
        return (STATE_RANK.get(d.state, len(STATE_RANK)) if d else len(STATE_RANK), -((d.score or 0.0) if d else 0.0), p.decision_id)

    items: list[dict[str, Any]] = []
    for p in sorted(newest_of.values(), key=rank)[:TOP_DECISIONS]:
        d = decisions.get(p.decision_id)
        item: dict[str, Any] = {"decision": p.decision_id, "outcome": p.outcome, "quality": p.quality, "verdict": p.verdict}
        if d is not None:
            item |= {"market": d.market, "sel": d.selection, "line": float(d.line), "state": d.state}
        if p.causes:
            item["causes"] = list(p.causes)
        items.append(item)
    data = {"n": len(newest_of), "version": max(p.version for p in newest_of.values()), "verdicts": verdicts, "qualities": qualities,
            "items": items}
    return _layer(OK, known_at=newest(*(p.created_at for p in newest_of.values())), sources=sources, data=data)


# ── the whole ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def completeness_of(layers: Mapping[str, Mapping[str, Any]]) -> str:
    if layers[C1_RESULT]["status"] != OK:
        return MINIMAL
    statuses = [layers[name]["status"] for name in FACT_LAYERS]
    if all(s == OK for s in statuses):
        return COMPLETE
    if all(s == MISSING for s in statuses):
        return MINIMAL
    return PARTIAL


def build(inp: Inputs) -> Knowledge:
    """The nine layers of a finished match, what could not be said, and the hash of what it says."""
    events = tuple(ev.normalize(inp.events, extra_time=went_to_extra_time(inp.fixture))) if inp.events else ()
    check = event_checks(inp, events) if events else {}
    layers: dict[str, dict[str, Any]] = {
        C1_RESULT: c1_result(inp), C2_TEAM_STATS: c2_team_stats(inp), C3_EVENTS: c3_events(inp, events, check),
        C4_PLAYERS: c4_players(inp, events), C5_TACTICS: c5_tactics(inp, events, check), C6_MARKET: c6_market(inp),
        C7_CONTEXT: c7_context(), C8_PICKS: c8_picks(inp), C9_POSTMORTEM: c9_postmortem(inp),
    }
    completeness = completeness_of(layers)
    doubts: list[str] = []
    if layers[C1_RESULT]["status"] != OK:
        doubts.append("no_result")
    if check.get("reg") is False:
        doubts.append("events_do_not_give_the_score")
    doubts += [f"events_{name}_differ" for name in ("ht", "et", "pen") if check.get(name) is False]
    if check.get("cards") is False:
        doubts.append("cards_differ_from_the_statistics")
    if inp.sheets_crossed:
        doubts.append("sheets_crossed")
    if any(ev.FLAG_UNKNOWN_DETAIL in e.flags for e in events):
        doubts.append("event_words_not_met")
    if any(ev.FLAG_NO_PLAYER in e.flags for e in events):
        doubts.append("lines_with_no_player")
    if any(ev.FLAG_LATE_MINUTE in e.flags or ev.FLAG_MINUTE_OUT_OF_RANGE in e.flags for e in events):
        doubts.append("odd_minutes")
    quality: dict[str, Any] = {
        "layers": {name: layers[name]["status"] for name in LAYERS},
        "events_give_the_score": check.get("reg"),
        "doubts": doubts,
    }
    known = newest(*(layer_known(layers[name]) for name in LAYERS)) or inp.fixture.kickoff_at
    return Knowledge(version=VERSION, layers=layers, quality=quality, completeness=completeness, known_at=known,
                     content_hash=content_hash(layers, quality, completeness), events=events)


def layer_known(layer: Mapping[str, Any]) -> datetime | None:
    stamp = layer.get("known_at")
    return None if stamp is None else datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
