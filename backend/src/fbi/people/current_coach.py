"""Who coaches a team now (AD-H03, IA-075): the coach of its newest match sheet, with that match's date - and which open
careers of the provider that contradicts.

The provider's careers (``core.coach_careers``) are not a reliable answer: on 16-nov-2026, of 4,531 teams with an open career
(no end date) in the newest snapshot of each coach, only 1,404 had exactly one; 1,208 had two, 945 three and 974 four or more.
A career is closed only when the provider rewrites it, and many are never rewritten. The match sheet is a fact with a date:
``core.fixture_lineups.provider_coach_id`` is who sat on the bench that day.

THE RULE (``coach-current-v1``), pure and deterministic - this module reads nothing and writes nothing:

* The current coach of a team is the coach of its NEWEST match sheet that names one (a sheet without a coach is skipped and
  counted). The answer carries the match, its date and the source (``lineup``).
* An interim or caretaker is the current coach while he is on the bench: the rule does not know titles, only who sat there.
  ``career_known`` says whether the provider lists a career of his at the team.
* A team with no sheet naming a coach in the window falls back to the provider's career only when exactly ONE open career is
  left (source ``provider_career``); otherwise there is no answer, with its reason.
* An open career of the provider that STARTS after the newest sheet is reported (``announced``): a coach named after the last
  match. The current coach stays the one of the sheet until a sheet says otherwise.

CLOSING A CAREER (never deleting it). An open career of another coach X at the team contradicts the newest sheets when the
evidence is strong - the current coach sat on the bench in at least ``MIN_STREAK`` consecutive sheets, or the provider itself
lists an open career of his at the team - and X's career did not start after the current coach's run began. Then a
correction is proposed: the end date is X's last match on the bench of that team when the sheets show one (``last_lineup``),
else the day before the current coach's run began, as an upper bound (``before_successor``). A cessation is never inferred
without a sheet: a team without sheets gets no correction, and a single sheet of another coach (a suspended head coach, an
assistant on the bench for a day) is not enough unless the provider agrees.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal

from fbi.people.identity.names import alias_key, names_compatible

RULES_VERSION: Final = "coach-current-v1"
MIN_STREAK: Final = 2
"""Consecutive sheets of the current coach that make his run strong evidence against another open career."""
LOOKBACK_DAYS: Final = 400
"""How far back the sheets are read: a season and a bit, so a team between seasons still has its coach."""
FRESH_DAYS: Final = 90
"""A sheet older than this still names the coach, but the answer says it is not fresh (``fresh``)."""

Source = Literal["lineup", "provider_career"]
EndBasis = Literal["last_lineup", "before_successor"]
SamePerson = Callable[[int, int], bool]
"""Whether two provider coach ids may be one person (the provider gives some coaches two ids: ``Mariusz Jop`` and ``M. Jop``)."""


def same_person_by_names(names: Mapping[int, Sequence[str]], births: Mapping[int, date] | None = None) -> SamePerson:
    """Two ids are one person when their names do not contradict it (a shared surname, an initial and a surname, or the same
    words in another order: ``Tencati Claudio`` / ``Cláudio Tencati``) and their birth dates, when both are known, are equal.
    Used only to NOT close a career (a doubt keeps it open), never to merge two coaches."""
    born = births or {}

    def same(a: int, b: int) -> bool:
        if a == b:
            return True
        if a in born and b in born and born[a] != born[b]:
            return False
        na, nb = [n for n in names.get(a, ()) if n], [n for n in names.get(b, ()) if n]
        if not na or not nb:
            return False
        if {frozenset(alias_key(n).split()) for n in na} & {frozenset(alias_key(n).split()) for n in nb}:
            return True
        return names_compatible(na, nb)

    return same


def _day(at: datetime) -> date:
    """The UTC day of a moment (a match on Saturday 23:00 in Bogotá is a Sunday in UTC: one rule for every reader)."""
    return at.astimezone(UTC).date() if at.tzinfo else at.date()


def _distinct(a: int, b: int) -> bool:
    return a == b


@dataclass(frozen=True, slots=True)
class Sheet:
    """One match sheet of the team: who sat on the bench (None when the sheet names nobody)."""

    fixture_id: int
    kickoff_at: datetime
    provider_coach_id: int | None
    coach_id: int | None = None
    coach_name: str | None = None


@dataclass(frozen=True, slots=True)
class OpenCareer:
    """A row of the newest snapshot of a coach's careers at this team with no end date (provider or corrected)."""

    provider_coach_id: int
    observed_at: datetime
    ordinal: int
    start_date: date | None
    coach_id: int | None = None


@dataclass(frozen=True, slots=True)
class Closure:
    """A proposed correction: the career (its key) ends on ``end_date``, for ``basis``."""

    provider_coach_id: int
    observed_at: datetime
    ordinal: int
    end_date: date
    basis: EndBasis
    successor_provider_coach_id: int
    successor_since: date
    successor_streak: int
    successor_fixture_id: int
    last_fixture_id: int | None


@dataclass(slots=True)
class CurrentCoach:
    team_id: int
    provider_coach_id: int | None = None
    coach_id: int | None = None
    coach_name: str | None = None
    source: Source | None = None
    as_of: date | None = None
    """The date of the match the answer comes from (``lineup``), or the start of the one open career (``provider_career``)."""
    fixture_id: int | None = None
    fresh: bool = False
    streak: int = 0
    """Consecutive newest sheets naming this coach (sheets without a coach skipped)."""
    since: date | None = None
    """The first match of that run."""
    sheets_without_coach: int = 0
    """Sheets newer than the answer that name nobody."""
    career_known: bool | None = None
    """Whether the provider lists an open career of his at the team (None when it is not known)."""
    profile_team_agrees: bool | None = None
    """Whether the provider's own profile of the coach (``/coachs``) names this team as his: a contrast, never the answer."""
    announced: list[int] = field(default_factory=list)
    """Coaches with an open career at the team that starts after the answer's date: named after the last match."""
    contradicted: int = 0
    """Open careers of other coaches the sheets contradict (closed or not)."""
    open_after: int = 0
    """Coaches (persons, as far as ``SamePerson`` tells) with a career at the team still open once the closures are applied."""
    same_person_ids: list[int] = field(default_factory=list)
    """Other provider ids of what may be the same person (``SamePerson``): their sheets count in his run, their careers are
    never closed by him."""
    reason: str | None = None
    """Why there is no answer (``no_sheet``, ``several_open_careers``), when there is none."""
    rules_version: str = RULES_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "team_id": self.team_id, "provider_coach_id": self.provider_coach_id, "coach_id": self.coach_id,
            "coach_name": self.coach_name, "source": self.source,
            "as_of": self.as_of.isoformat() if self.as_of else None, "fixture_id": self.fixture_id, "fresh": self.fresh,
            "streak": self.streak, "since": self.since.isoformat() if self.since else None,
            "sheets_without_coach": self.sheets_without_coach, "career_known": self.career_known,
            "profile_team_agrees": self.profile_team_agrees, "announced": list(self.announced),
            "contradicted": self.contradicted, "open_after": self.open_after, "same_person_ids": list(self.same_person_ids), "reason": self.reason,
            "rules_version": self.rules_version,
        }


@dataclass(frozen=True, slots=True)
class Decision:
    current: CurrentCoach
    closures: tuple[Closure, ...]


def _newest_first(sheets: Iterable[Sheet]) -> list[Sheet]:
    return sorted(sheets, key=lambda s: (s.kickoff_at, s.fixture_id), reverse=True)


def decide(team_id: int, sheets: Iterable[Sheet], open_careers: Iterable[OpenCareer], *, now: datetime,
           profile_team_of: Mapping[int, bool] | None = None, same_person: SamePerson | None = None,
           min_streak: int = MIN_STREAK, fresh_days: int = FRESH_DAYS) -> Decision:
    """The current coach of ``team_id`` and the open careers his sheets close. ``sheets`` are the team's match sheets already
    played (any order); ``open_careers`` the open careers at the team (already net of earlier corrections);
    ``profile_team_of`` maps a provider coach id to whether his profile names this team; ``same_person`` says whether two
    ids may be one person (default: only an id is itself)."""
    same = same_person or _distinct
    ordered = [s for s in _newest_first(sheets) if s.kickoff_at <= now]
    opens = list(open_careers)
    profiles = profile_team_of or {}
    out = CurrentCoach(team_id=team_id)
    named = [s for s in ordered if s.provider_coach_id]
    if not named:
        out.sheets_without_coach = len(ordered)
        if len({c.provider_coach_id for c in opens}) == 1:
            only = min(opens, key=lambda c: (c.start_date or date.min, c.ordinal))
            out.provider_coach_id, out.coach_id = only.provider_coach_id, only.coach_id
            out.source, out.as_of, out.career_known = "provider_career", only.start_date, True
            out.profile_team_agrees = profiles.get(only.provider_coach_id)
        else:
            out.reason = "several_open_careers" if opens else "no_sheet"
        out.open_after = len({c.provider_coach_id for c in opens})
        return Decision(out, ())

    head = named[0]
    current = head.provider_coach_id
    assert current is not None
    out.provider_coach_id, out.coach_id, out.coach_name = current, head.coach_id, head.coach_name
    out.source, out.fixture_id, out.as_of = "lineup", head.fixture_id, _day(head.kickoff_at)
    out.fresh = (now - head.kickoff_at) <= timedelta(days=fresh_days)
    out.sheets_without_coach = next(i for i, s in enumerate(ordered) if s.fixture_id == head.fixture_id)
    run: list[Sheet] = []
    for s in named:
        if s.provider_coach_id is None or not same(current, s.provider_coach_id):
            break
        run.append(s)
    out.streak = len(run)
    since = _day(run[-1].kickoff_at)
    out.since = since
    ids = {s.provider_coach_id for s in named if s.provider_coach_id} | {c.provider_coach_id for c in opens}
    out.same_person_ids = sorted(k for k in ids if k != current and same(current, k))
    own_open = [c for c in opens if same(current, c.provider_coach_id)]
    out.career_known = bool(own_open)
    out.profile_team_agrees = profiles.get(current)
    out.announced = sorted({c.provider_coach_id for c in opens
                            if not same(current, c.provider_coach_id) and c.start_date is not None
                            and c.start_date > out.as_of})

    strong = out.streak >= min_streak or bool(own_open)
    last_seen: dict[int, Sheet] = {}
    for s in named:
        if s.provider_coach_id is not None and s.provider_coach_id not in last_seen:
            last_seen[s.provider_coach_id] = s
    closures: list[Closure] = []
    contradicted = 0
    for c in opens:
        if same(current, c.provider_coach_id):
            continue
        if c.start_date is not None and c.start_date >= since:
            continue  # started once the current coach's run had begun (or after it): not contradicted, maybe announced
        contradicted += 1
        if not strong:
            continue
        seen = last_seen.get(c.provider_coach_id)
        basis: EndBasis
        last_fixture: int | None
        if seen is not None:
            end, basis, last_fixture = _day(seen.kickoff_at), "last_lineup", seen.fixture_id
        else:
            end, basis, last_fixture = since - timedelta(days=1), "before_successor", None
        if c.start_date is not None and end < c.start_date:
            end = c.start_date  # a career never ends before it starts: the upper bound is clamped to its start
        closures.append(Closure(c.provider_coach_id, c.observed_at, c.ordinal, end, basis,
                                current, since, out.streak, run[-1].fixture_id, last_fixture))
    out.contradicted = contradicted
    closed = {(k.provider_coach_id, k.observed_at, k.ordinal) for k in closures}
    left = [c for c in opens if (c.provider_coach_id, c.observed_at, c.ordinal) not in closed]
    others = {c.provider_coach_id for c in left if not same(current, c.provider_coach_id)}
    out.open_after = len(others) + int(any(same(current, c.provider_coach_id) for c in left))
    return Decision(out, tuple(sorted(closures, key=lambda k: (k.provider_coach_id, k.observed_at, k.ordinal))))


def decide_all(sheets: Iterable[tuple[int, Sheet]], open_careers: Iterable[tuple[int, OpenCareer]], *, now: datetime,
               profile_teams: Mapping[int, int | None] | None = None,
               team_provider_ids: Mapping[int, int] | None = None,
               same_person: SamePerson | None = None) -> dict[int, Decision]:
    """``decide`` for every team that has a sheet or an open career. ``profile_teams`` maps a provider coach id to the provider
    team id his profile names, ``team_provider_ids`` our team id to its provider id (for the contrast)."""
    by_team: dict[int, list[Sheet]] = {}
    for team_id, s in sheets:
        by_team.setdefault(team_id, []).append(s)
    opens: dict[int, list[OpenCareer]] = {}
    for team_id, c in open_careers:
        opens.setdefault(team_id, []).append(c)
    profiles = profile_teams or {}
    providers = team_provider_ids or {}
    out: dict[int, Decision] = {}
    for team_id in sorted(set(by_team) | set(opens)):
        team_sheets = by_team.get(team_id, [])
        team_opens = opens.get(team_id, [])
        pid = providers.get(team_id)
        coaches = {s.provider_coach_id for s in team_sheets if s.provider_coach_id} | {c.provider_coach_id
                                                                                       for c in team_opens}
        agree = {k: profiles[k] == pid for k in coaches if k in profiles and pid is not None and profiles[k] is not None}
        out[team_id] = decide(team_id, team_sheets, team_opens, now=now, profile_team_of=agree, same_person=same_person)
    return out


def summary(decisions: Mapping[int, Decision], *, open_before: Mapping[int, int] | None = None) -> dict[str, int]:
    """The figures the audit prints: answers by source, fresh ones, closures by basis, and teams left with more than one open
    career once the proposed closures are applied (``open_before``: team -> distinct coach ids with an open career)."""
    s: dict[str, int] = {"teams": len(decisions), "lineup": 0, "lineup_fresh": 0, "provider_career": 0, "no_answer": 0,
                         "closures": 0, "closures_last_lineup": 0, "closures_before_successor": 0,
                         "teams_with_closures": 0, "announced": 0, "profile_disagrees": 0, "same_person_other_id": 0}
    for d in decisions.values():
        c = d.current
        if c.source == "lineup":
            s["lineup"] += 1
            s["lineup_fresh"] += int(c.fresh)
        elif c.source == "provider_career":
            s["provider_career"] += 1
        else:
            s["no_answer"] += 1
        s["closures"] += len(d.closures)
        s["closures_last_lineup"] += sum(1 for k in d.closures if k.basis == "last_lineup")
        s["closures_before_successor"] += sum(1 for k in d.closures if k.basis == "before_successor")
        s["teams_with_closures"] += int(bool(d.closures))
        s["announced"] += int(bool(c.announced))
        s["profile_disagrees"] += int(c.profile_team_agrees is False)
        s["same_person_other_id"] += int(bool(c.same_person_ids))
    s["teams_open_gt1_after"] = sum(1 for d in decisions.values() if d.current.open_after > 1)
    if open_before is not None:
        s["teams_open_gt1_before"] = sum(1 for n in open_before.values() if n > 1)
    return s


def closures_of(decisions: Mapping[int, Decision]) -> Sequence[tuple[int, Closure]]:
    return [(team_id, k) for team_id, d in sorted(decisions.items()) for k in d.closures]
