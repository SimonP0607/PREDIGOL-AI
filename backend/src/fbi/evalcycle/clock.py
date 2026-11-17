"""When each evaluation is due (IA-105, AD-D06; IA-142, AD-D06/D07): the football clock of ``eval-cycle-v1``. Pure: no database, no clock
(``now`` is given). ``VERSION`` names the clock (``eval-clock-v2`` since IA-142; the E4 runs say which one they ran under).

    E1  once per match, from ``E1_FROM`` (24 h) to ``E1_UNTIL`` (12 h) before kick-off
    E2  between E1 and the opening of E4, for the facts of the match retrieved after E1 and not looked at yet (``plan_facts``)
    E3  when a side's official line-up is read (``plan_line_up``): both sides, or one side alone once ``PARTIAL_GRACE`` has passed
        without the other; a new content (a corrected starter, the second side) is a new E3 version
    E4  once per match, at T-5: from ``E4_FROM`` (5 min) to kick-off (``E4_UNTIL``, 0)

THE OWNER'S DECISION OF 17-NOV-2026 (IA-142, ``backend/docs/owner/IA_140_DECISIONES_DUENO_20261117.md``): E4 moves to T-5. ``decision-v1``
is PROTECTED and its floor is never lowered (``fbi.intel.decision.MIN_MINUTES``, 10 min: under it its data stage rejects every selection
«menos de 10 min al saque», and decision-v2 inherits the rule). So E4 at T-5 does NOT decide: it judges every selection with
decision-v2's LAST kept decision (in the shadow) and the price READ AGAIN at T-5.

    last decision   from ``DECIDE_FROM`` (20 min) to ``DECISION_FLOOR`` (decision-v1's 10 min, imported): decision-v2 decides for the
                    last time before its floor, as its own kept shadow does (IA-093, trigger ``E4``) - the moment E4 adopts at T-5

The mirror of decision-v1 (IA-093) has nothing to follow at T-5: decision-v1 does not decide there (its last checkpoint is ``T-15m``, and a
run under its floor only rejects). E4 never adopts a moment written under the floor, so a mirrored rejection there never becomes E4's
decision; the comparison with decision-v1 ends at its last moment.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from fbi.intel import decision

VERSION: Final = "eval-clock-v2"
"""``eval-clock-v1``: E4 from T-20 to T-10 (IA-105). ``eval-clock-v2``: E4 at T-5 with the last decision (IA-142, owner, 17-nov-2026)."""
E1_FROM: Final = timedelta(hours=24)
E1_UNTIL: Final = timedelta(hours=12)
E4_FROM: Final = timedelta(minutes=5)
"""E4 opens at T-5 (the owner's decision of 17-nov-2026, IA-142)."""
E4_UNTIL: Final = timedelta(0)
"""E4 is due until kick-off: a pass every ``fbi.shadowjobs.eval_cycle.every_minutes`` (at most 5) always falls inside it."""
DECIDE_FROM: Final = timedelta(minutes=20)
DECISION_FLOOR: Final = timedelta(minutes=decision.MIN_MINUTES)
"""decision-v1's floor, imported and never lowered: the cycle never decides closer to kick-off than decision-v1 would."""
E3_DEADLINE: Final = timedelta(minutes=2)
"""AD-D06's criterion: an E3 ends less than two minutes after its line-up was first seen (``eval_runs.latency_ms``)."""
PARTIAL_GRACE: Final = timedelta(minutes=3)
"""How long one side's line-up waits for the other before E3 runs on it alone (both usually arrive in the same answer)."""
STARTERS: Final = 11
MODEL_KINDS: Final = frozenset({"injury", "suspension", "doubtful", "lineup"})
"""The kinds of fact decision-v1's context stage reads (``fbi.ai.evidence.CONTEXT_SQL``): a fact of one of them touches a variable of the
model; any other kind is noted, not recalculated - unless it names a player a selection depends on."""

SIDES: Final = ("home", "away")


def window(kickoff_at: datetime, now: datetime) -> str | None:
    """``E1`` or ``E4`` when ``now`` is in its window before ``kickoff_at``, else None."""
    if kickoff_at - E1_FROM <= now <= kickoff_at - E1_UNTIL:
        return "E1"
    if kickoff_at - E4_FROM <= now < kickoff_at - E4_UNTIL:
        return "E4"
    return None


def last_decision(kickoff_at: datetime, now: datetime) -> bool:
    """Whether ``now`` is in the window of decision-v2's last decision before its floor (T-20 to T-10), the one E4 judges with at T-5."""
    return kickoff_at - DECIDE_FROM <= now < kickoff_at - DECISION_FLOOR


def in_facts_window(kickoff_at: datetime, now: datetime, e1_at: datetime | None) -> bool:
    """E2 runs only after E1 and before E4 opens (a fact later than that is E4's)."""
    return e1_at is not None and e1_at < now < kickoff_at - E4_FROM


def decides(kickoff_at: datetime, now: datetime) -> bool:
    """Whether decision-v2 may still decide at ``now``: at least decision-v1's floor before kick-off."""
    return now < kickoff_at - DECISION_FLOOR


# -- E3 --------------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Arrival:
    """The newest observation of one side's line-up by the moment (``core.fixture_lineup_arrivals``: change-only, so ``observed_at`` is
    when this content was first seen)."""

    side: str
    observed_at: datetime
    starters_hash: str
    starters: int
    arrival_id: int | None = None
    payload_hash: str | None = None


@dataclass(frozen=True, slots=True)
class LineUpDue:
    key: str
    cause: str
    sides: tuple[str, ...]
    trigger_at: datetime
    """When the newest content of the line-up E3 reads was first seen: E3's latency is measured from here."""
    arrivals: tuple[Arrival, ...]


def line_up_key(arrivals: Sequence[Arrival]) -> str:
    """The identity of a line-up as E3 reads it: the starters of each side seen (``-`` for a side not seen)."""
    by = {a.side: a.starters_hash[:16] for a in arrivals}
    return "xi:" + "|".join(f"{s}:{by.get(s, '-')}" for s in SIDES)


def plan_line_up(newest: Mapping[str, Arrival], done: Iterable[str], *, now: datetime, kickoff_at: datetime) -> LineUpDue | None:
    """The E3 due for one match, or None: the sides whose newest line-up (by ``now``) has eleven starters, both of them or one alone
    after ``PARTIAL_GRACE``; nothing once kick-off has come, nothing twice for the same content (``done``: the keys of the E3 already
    kept)."""
    if now >= kickoff_at:
        return None
    complete = sorted((a for a in newest.values() if a.side in SIDES and a.starters >= STARTERS and a.observed_at <= now),
                      key=lambda a: a.side)
    if not complete:
        return None
    if len(complete) == 1 and now - complete[0].observed_at < PARTIAL_GRACE:
        return None
    key = line_up_key(complete)
    seen = set(done)
    if key in seen:
        return None
    cause = "correccion_alineacion" if any(k.startswith("xi:") for k in seen) else "alineacion_oficial"
    return LineUpDue(key, cause, tuple(a.side for a in complete), max(a.observed_at for a in complete), tuple(complete))


# -- E2 --------------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Fact:
    evidence_id: int
    kind: str | None
    provider_player_id: int | None
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class FactCall:
    fact: Fact
    action: str
    """``recalcula`` or ``anota``."""
    reason: str


RECALCULATE: Final = "recalcula"
NOTE: Final = "anota"


def judge_fact(f: Fact, dependents: frozenset[int]) -> FactCall:
    """Whether a new fact makes E2 recalculate: it names a player a selection depends on, or it is of a kind the model's context reads."""
    if f.provider_player_id is not None and f.provider_player_id in dependents:
        return FactCall(f, RECALCULATE, "dependencia_declarada")
    if f.kind in MODEL_KINDS:
        return FactCall(f, RECALCULATE, "variable_del_modelo")
    return FactCall(f, NOTE, "no_toca_el_modelo")


def plan_facts(facts: Sequence[Fact], seen: Iterable[int], dependents: frozenset[int], *, e1_at: datetime | None, now: datetime,
               kickoff_at: datetime) -> list[FactCall]:
    """The facts E2 looks at now: retrieved after E1 and by ``now``, never looked at before (``seen``), in the order they were known. Empty
    outside E2's window."""
    if not in_facts_window(kickoff_at, now, e1_at):
        return []
    assert e1_at is not None
    old = set(seen)
    fresh = sorted((f for f in facts if f.evidence_id not in old and e1_at < f.retrieved_at <= now),
                   key=lambda f: (f.retrieved_at, f.evidence_id))
    return [judge_fact(f, dependents) for f in fresh]


def facts_key(calls: Sequence[FactCall]) -> str:
    ids = ",".join(str(c.fact.evidence_id) for c in sorted(calls, key=lambda c: c.fact.evidence_id))
    return "hechos:" + hashlib.sha256(ids.encode()).hexdigest()[:24]
