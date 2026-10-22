"""The referees in the database: placing the spellings the provider wrote, and what a person can change afterwards (plan F3).

``fbi.people.referee_identity`` decides who is who from the spellings and the matches they are the final word on; this module
reads those from ``core.fixture_facts``, asks it, and writes the answer: a ``core.referees`` row per person, a
``core.referee_aliases`` row per spelling in a scope, the history of who officiated each match (``core.fixture_officials``) and
the queue of doubts (``core.referee_candidates``).

A PASS (``build``) is idempotent and incremental by construction. It reads every observation of the facts (210 thousand rows,
a few seconds), gives the rules every spelling - the ones already stored as FROZEN (they keep their referee, whatever the rules
would say now) and the new ones - and writes only the difference: new referees for new groups, new aliases, the officials rows
that do not exist yet, the names that changed, and the candidates that appeared or went away. A second pass writes nothing.

WHAT A PERSON CAN DO (``merge``, ``undo``, ``split``, ``reject``, ``reopen``, ``rename``)
-------------------------------------------------------------------------------------
Every one runs in one transaction under the same advisory lock as the pass, so they never write at once. A merge moves the
aliases of one referee to another and marks the first ``merged``; nothing else changes, because the officials point at aliases.
The event keeps which aliases moved and what each one was, so ``undo`` puts them back. A split moves some aliases of a referee
to a new one. Both leave the pair as a REJECTED candidate when they separate (an undone merge, a split), so the machine does not
suggest again what a person just undone. The pass never moves a stored alias: it only attaches new spellings and renames.
"""

from __future__ import annotations

import itertools
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.people import referee_identity as ri
from fbi.people.countries import UNKNOWN_SCOPE, plain, scope_of
from fbi.people.referee_names import parse_referee

JOB: Final = "referee_identity"
LOCK_KEY: Final = "fbi.referee_identity"
VERSION: Final = ri.VERSION
MANUAL_LOCK_WAIT: Final = "20s"
"""How long a person's action waits for a pass that is writing: a pass takes seconds, the first one half a minute."""

OBSERVATIONS_SQL: Final = """
SELECT f.fixture_id, f.observed_at, f.referee, f.referee_country, x.kickoff_at, c.country, c.competition_type
  FROM core.fixture_facts f
  JOIN core.fixtures x ON x.id = f.fixture_id
  JOIN core.competition_seasons s ON s.id = x.competition_season_id
  JOIN core.competitions c ON c.id = s.competition_id
 ORDER BY f.fixture_id, f.observed_at
"""
"""Every observation of every match, in order: the history of what the provider said about the referee."""


class ActionError(Exception):
    """A person's action that cannot be done; ``code`` is for the API (404 missing, 409 not allowed, 422 invalid)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Change:
    """The provider changed (or first gave) the referee of a match: the spelling it wrote, None when it took him off."""

    fixture_id: int
    observed_at: datetime
    spelling: ri.FormId | None


@dataclass(slots=True)
class Reading:
    observations: int = 0
    fixtures: int = 0
    """Matches whose newest observation names a referee."""
    without_kickoff: int = 0
    changes: list[Change] = field(default_factory=list)
    forms: dict[ri.FormId, ri.Form] = field(default_factory=dict)
    displays: dict[ri.FormId, Counter[str]] = field(default_factory=dict)


def spelling_of(referee: str | None, referee_country: str | None, competition_country: str | None,
                competition_type: str | None) -> tuple[ri.FormId, str] | None:
    """The spelling and the way the provider wrote it (``Michael Oliver``) of one observation, or None for no referee."""
    parsed = parse_referee(referee, referee_country)
    if parsed is None:
        return None
    return (parsed.key, scope_of(parsed.country, competition_country, competition_type)), parsed.display


def read_spellings(conn: psycopg.Connection[Any]) -> Reading:
    """The history of the referee of every match, as the changes of its spelling, and the spellings with the matches they are
    the final word on."""
    reading = Reading()
    cache: dict[tuple[Any, ...], tuple[ri.FormId, str] | None] = {}
    seen: Counter[ri.FormId] = Counter()
    with conn.transaction(), conn.cursor(name="referee_observations") as cur:
        cur.itersize = 20_000
        cur.execute(OBSERVATIONS_SQL)
        for fixture_id, rows in itertools.groupby(cur, key=lambda r: r[0]):
            previous: ri.FormId | None = None
            kickoff: datetime | None = None
            for _, observed_at, referee, referee_country, kickoff_at, comp_country, comp_type in rows:
                reading.observations += 1
                kickoff = kickoff_at
                token = (referee, referee_country, comp_country, comp_type)
                if token not in cache:
                    cache[token] = spelling_of(referee, referee_country, comp_country, comp_type)
                parsed = cache[token]
                current = parsed[0] if parsed else None
                if current == previous:
                    continue
                reading.changes.append(Change(int(fixture_id), observed_at, current))
                if parsed is not None:
                    seen[parsed[0]] += 1
                    reading.displays.setdefault(parsed[0], Counter())[parsed[1]] += 1
                previous = current
            if previous is not None:
                reading.fixtures += 1
                form = reading.forms.setdefault(previous, ri.Form(previous[0], previous[1]))
                if kickoff is None:
                    reading.without_kickoff += 1
                else:
                    form.games.append((int(kickoff.timestamp() // 60), int(fixture_id)))
    for spelling, count in seen.items():
        reading.forms.setdefault(spelling, ri.Form(spelling[0], spelling[1])).seen = count
    return reading


@dataclass(frozen=True, slots=True)
class StoredAlias:
    id: int
    referee_id: int
    spelling: ri.FormId
    display: str


@dataclass(frozen=True, slots=True)
class StoredReferee:
    id: int
    name: str
    name_key: str
    country_key: str | None
    name_locked: bool


def read_aliases(conn: psycopg.Connection[Any]) -> dict[ri.FormId, StoredAlias]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, referee_id, name_key, scope, display FROM core.referee_aliases")
        return {(k, s): StoredAlias(int(i), int(r), (k, s), d) for i, r, k, s, d in cur.fetchall()}


def read_referees(conn: psycopg.Connection[Any]) -> dict[int, StoredReferee]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, name_key, country_key, name_locked FROM core.referees WHERE status = 'active'")
        return {int(i): StoredReferee(int(i), n, k, c, bool(lock)) for i, n, k, c, lock in cur.fetchall()}


def read_officials(conn: psycopg.Connection[Any]) -> set[tuple[int, datetime]]:
    with conn.cursor() as cur:
        cur.execute("SELECT fixture_id, observed_at FROM core.fixture_officials WHERE role = 'referee'")
        return {(int(f), t) for f, t in cur.fetchall()}


def read_candidates(conn: psycopg.Connection[Any]) -> dict[tuple[int, int], tuple[int, str, str, float, int, dict[str, Any], str]]:
    """(referee_a, referee_b) -> (id, status, reason, score, impact, evidence, version)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, referee_a, referee_b, status, reason, score, impact, evidence, version FROM core.referee_candidates")
        return {(int(a), int(b)): (int(i), st, rs, float(sc), int(im), ev, ver) for i, a, b, st, rs, sc, im, ev, ver in cur.fetchall()}


# ── the pass ─────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class BuildReport:
    version: str = VERSION
    applied: bool = False
    skipped_locked: bool = False
    seconds: float = 0.0
    observations: int = 0
    fixtures: int = 0
    without_kickoff: int = 0
    forms: int = 0
    groups: int = 0
    games: int = 0
    games_settled: int = 0
    new_referees: int = 0
    new_aliases: int = 0
    renamed: int = 0
    officials_to_write: int = 0
    candidates: int = 0
    candidates_added: int = 0
    candidates_changed: int = 0
    candidates_removed: int = 0
    vetoes: int = 0
    basis: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.new_referees or self.new_aliases or self.renamed or self.officials_to_write
                    or self.candidates_added or self.candidates_changed or self.candidates_removed)

    @property
    def settled_share(self) -> float:
        return self.games_settled / self.games if self.games else 1.0

    def as_dict(self) -> dict[str, Any]:
        return {"version": self.version, "applied": self.applied, "skipped_locked": self.skipped_locked,
                "seconds": round(self.seconds, 1), "observations": self.observations, "fixtures": self.fixtures,
                "without_kickoff": self.without_kickoff, "forms": self.forms, "groups": self.groups,
                "games": self.games, "games_settled": self.games_settled, "settled_share": round(self.settled_share, 4),
                "new_referees": self.new_referees, "new_aliases": self.new_aliases, "renamed": self.renamed,
                "officials_to_write": self.officials_to_write, "candidates": self.candidates,
                "candidates_added": self.candidates_added, "candidates_changed": self.candidates_changed,
                "candidates_removed": self.candidates_removed, "vetoes": self.vetoes, "basis": self.basis}


@dataclass(frozen=True, slots=True)
class GroupName:
    name: str
    name_key: str
    country_key: str | None


@dataclass(slots=True)
class Plan:
    resolution: ri.Resolution
    names: dict[int, GroupName]
    """Group number -> the name and country the referee of the group should have."""
    new_aliases: list[tuple[ri.FormId, int, str, str]]
    """(spelling, group, display, basis) of the spellings not stored yet."""
    renames: list[tuple[int, GroupName]]
    """(referee, name) of the stored referees whose name or country is not the one the group gives."""
    officials: list[Change]
    """The changes of referee that are not in ``core.fixture_officials`` yet."""


def make_plan(reading: Reading, stored: dict[ri.FormId, StoredAlias], referees: dict[int, StoredReferee],
              existing: set[tuple[int, datetime]], params: ri.Params = ri.DEFAULT_PARAMS) -> Plan:
    forms: dict[ri.FormId, ri.Form] = {}
    for spelling, form in reading.forms.items():
        alias = stored.get(spelling)
        form.entity = alias.referee_id if alias else None
        forms[spelling] = form
    for spelling, alias in stored.items():  # a stored spelling no match uses any more still belongs to its referee
        forms.setdefault(spelling, ri.Form(spelling[0], spelling[1], entity=alias.referee_id))
    resolution = ri.resolve(forms.values(), params)

    def display(spelling: ri.FormId) -> str:
        if spelling in stored:
            return stored[spelling].display
        counts = reading.displays.get(spelling)
        return min(counts, key=lambda d: (-counts[d], d)) if counts else spelling[0]

    names: dict[int, GroupName] = {}
    for group in resolution.groups:
        by_scope: Counter[str] = Counter()
        for spelling in group.forms:
            by_scope[spelling[1]] += len(forms[spelling].games)
        home = ri.home_scope(by_scope)
        names[group.number] = GroupName(display(group.canonical), group.canonical[0], home)

    new_aliases = [(f.id, resolution.group_of[f.id], display(f.id), resolution.basis[f.id])
                   for f in sorted(forms.values(), key=lambda f: f.id) if f.entity is None]
    renames: list[tuple[int, GroupName]] = []
    for group in resolution.groups:
        if group.entity is None:
            continue
        current = referees.get(group.entity)
        wanted = names[group.number]
        if current is not None and not current.name_locked and (current.name, current.country_key) != (wanted.name, wanted.country_key):
            renames.append((group.entity, wanted))
    officials = [c for c in reading.changes if (c.fixture_id, c.observed_at) not in existing]
    return Plan(resolution, names, new_aliases, renames, officials)


def _lock(conn: psycopg.Connection[Any], *, wait: bool) -> bool:
    with conn.cursor() as cur:
        if wait:
            cur.execute(f"SET LOCAL lock_timeout = '{MANUAL_LOCK_WAIT}'")
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
            return True
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        row = cur.fetchone()
        return bool(row and row[0])


def _write_candidates(conn: psycopg.Connection[Any], plan: Plan, referee_of_group: dict[int, int], report: BuildReport) -> None:
    existing = read_candidates(conn)
    wanted: dict[tuple[int, int], ri.Candidate] = {}
    games = {g.number: g.games for g in plan.resolution.groups}
    for c in plan.resolution.candidates:
        a, b = referee_of_group[c.a], referee_of_group[c.b]
        if a != b:
            wanted[(min(a, b), max(a, b))] = c
    with conn.cursor() as cur:
        for pair, c in sorted(wanted.items()):
            impact = min(games[c.a], games[c.b])
            have = existing.get(pair)
            if have is None:
                cur.execute(
                    "INSERT INTO core.referee_candidates (referee_a, referee_b, reason, score, impact, evidence, version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)", (pair[0], pair[1], c.reason, c.score, impact, Jsonb(c.evidence), VERSION))
                report.candidates_added += 1
            elif have[1] == "open" and (have[2], round(have[3], 3), have[4], have[5], have[6]) != (
                    c.reason, round(c.score, 3), impact, c.evidence, VERSION):
                cur.execute(
                    "UPDATE core.referee_candidates SET reason = %s, score = %s, impact = %s, evidence = %s, version = %s, "
                    "updated_at = now() WHERE id = %s", (c.reason, c.score, impact, Jsonb(c.evidence), VERSION, have[0]))
                report.candidates_changed += 1
        stale = [have[0] for pair, have in existing.items() if have[1] == "open" and pair not in wanted]
        if stale:
            cur.execute("DELETE FROM core.referee_candidates WHERE id = ANY(%s) AND status = 'open'", (stale,))
            report.candidates_removed += len(stale)


def _apply(conn: psycopg.Connection[Any], plan: Plan, stored: dict[ri.FormId, StoredAlias], report: BuildReport) -> None:
    referee_of_group: dict[int, int] = {g.number: g.entity for g in plan.resolution.groups if g.entity is not None}
    with conn.cursor() as cur:
        for group in plan.resolution.groups:
            if group.entity is not None:
                continue
            n = plan.names[group.number]
            cur.execute("INSERT INTO core.referees (name, name_key, country_key, origin, version) VALUES (%s, %s, %s, 'rules', %s) "
                        "RETURNING id", (n.name, n.name_key, n.country_key, VERSION))
            row = cur.fetchone()
            assert row is not None
            referee_of_group[group.number] = int(row[0])
        alias_of: dict[ri.FormId, int] = {spelling: a.id for spelling, a in stored.items()}
        for spelling, group_number, shown, basis in plan.new_aliases:
            cur.execute("INSERT INTO core.referee_aliases (referee_id, name_key, scope, display, basis, placed_by, version) "
                        "VALUES (%s, %s, %s, %s, %s, 'rules', %s) RETURNING id",
                        (referee_of_group[group_number], spelling[0], spelling[1], shown, basis, VERSION))
            row = cur.fetchone()
            assert row is not None
            alias_of[spelling] = int(row[0])
        for referee_id, n in plan.renames:
            cur.execute("UPDATE core.referees SET name = %s, name_key = %s, country_key = %s, updated_at = now() WHERE id = %s",
                        (n.name, n.name_key, n.country_key, referee_id))
        if plan.officials:
            with cur.copy("COPY core.fixture_officials (fixture_id, role, observed_at, alias_id) FROM STDIN") as copy:
                for c in plan.officials:
                    copy.write_row((c.fixture_id, "referee", c.observed_at, alias_of[c.spelling] if c.spelling else None))
    _write_candidates(conn, plan, referee_of_group, report)


def build(conn: psycopg.Connection[Any], *, apply: bool = False, wait: bool = False,
          params: ri.Params = ri.DEFAULT_PARAMS) -> BuildReport:
    """One pass. Without ``apply`` nothing is written and the report says what would be. ``wait`` takes the lock and waits for it
    (a person at the console); the worker does not wait: when another pass is writing it returns ``skipped_locked``."""
    started = time.monotonic()
    report = BuildReport(applied=apply)
    with conn.transaction():
        if not _lock(conn, wait=wait):
            report.skipped_locked = True
            report.applied = False
            return report
        reading = read_spellings(conn)
        stored = read_aliases(conn)
        plan = make_plan(reading, stored, read_referees(conn), read_officials(conn), params)
        summary = plan.resolution.summary()
        report.observations, report.fixtures, report.without_kickoff = reading.observations, reading.fixtures, reading.without_kickoff
        report.forms, report.groups = summary["forms"], summary["groups"]
        report.games, report.games_settled, report.vetoes = summary["games"], summary["games_settled"], summary["vetoes"]
        report.new_referees = sum(1 for g in plan.resolution.groups if g.entity is None)
        report.new_aliases, report.renamed = len(plan.new_aliases), len(plan.renames)
        report.officials_to_write, report.candidates = len(plan.officials), len(plan.resolution.candidates)
        report.basis = dict(Counter(plan.resolution.basis.values()))
        if apply:
            _apply(conn, plan, stored, report)
    report.seconds = time.monotonic() - started
    return report


# ── what a person can do ─────────────────────────────────────────────────────────────────────────────────────────────


def _event(cur: psycopg.Cursor[Any], *, actor: str, action: str, referee_id: int | None, other_id: int | None = None,
           alias_ids: Sequence[int] = (), detail: dict[str, Any] | None = None) -> int:
    cur.execute("INSERT INTO core.referee_events (actor, action, referee_id, other_id, alias_ids, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (actor, action, referee_id, other_id, list(alias_ids), Jsonb(detail or {})))
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _active(cur: psycopg.Cursor[Any], ids: Iterable[int]) -> dict[int, tuple[str, bool]]:
    """(name, name locked) of the referees, locked FOR UPDATE. Raises when one does not exist or is merged into another."""
    wanted = sorted(set(ids))
    cur.execute("SELECT id, name, name_locked FROM core.referees WHERE id = ANY(%s) AND status = 'active' ORDER BY id FOR UPDATE", (wanted,))
    rows = {int(i): (n, bool(lk)) for i, n, lk in cur.fetchall()}
    for i in wanted:
        if i not in rows:
            raise ActionError("not_found", f"referee {i} does not exist or is merged into another one")
    return rows


def games_of(conn: psycopg.Connection[Any], referee_id: int) -> list[ri.Game]:
    """The kick-offs (minutes since the epoch, fixture) of the matches the referee has now, sorted."""
    with conn.cursor() as cur:
        cur.execute("SELECT x.kickoff_at, fr.fixture_id FROM core.fixture_referees fr JOIN core.fixtures x ON x.id = fr.fixture_id "
                    "WHERE fr.referee_id = %s AND x.kickoff_at IS NOT NULL", (referee_id,))
        return sorted((int(k.timestamp() // 60), int(f)) for k, f in cur.fetchall())


def refresh_identity(conn: psycopg.Connection[Any], referee_id: int) -> None:
    """Name and country of an unlocked referee from his aliases and their matches (what the pass does for every group)."""
    with conn.cursor() as cur:
        cur.execute("SELECT name_locked FROM core.referees WHERE id = %s", (referee_id,))
        row = cur.fetchone()
        if row is None or row[0]:
            return
        cur.execute("SELECT a.name_key, a.scope, a.display, count(fr.fixture_id) FROM core.referee_aliases a "
                    "LEFT JOIN core.fixture_referees fr ON fr.alias_id = a.id WHERE a.referee_id = %s GROUP BY a.id", (referee_id,))
        aliases = [(k, s, d, int(n)) for k, s, d, n in cur.fetchall()]
        if not aliases:
            return
        best = min(aliases, key=lambda a: ri.canonical_rank(a[0], a[1], a[3]))
        by_scope: Counter[str] = Counter()
        for _, scope, _, n in aliases:
            by_scope[scope] += n
        cur.execute("UPDATE core.referees SET name = %s, name_key = %s, country_key = %s, updated_at = now() "
                    "WHERE id = %s AND (name, country_key) IS DISTINCT FROM (%s, %s)",
                    (best[2], best[0], ri.home_scope(by_scope), referee_id, best[2], ri.home_scope(by_scope)))


def _set_decision(cur: psycopg.Cursor[Any], a: int, b: int, status: str, actor: str) -> None:
    """Record the decision on a pair: the candidate row is made rejected or merged (created when the pair was never suggested)."""
    low, high = min(a, b), max(a, b)
    cur.execute("INSERT INTO core.referee_candidates (referee_a, referee_b, reason, score, impact, version, status, decided_by, decided_at) "
                "VALUES (%s, %s, 'manual', 0, 0, %s, %s, %s, now()) "
                "ON CONFLICT (referee_a, referee_b) DO UPDATE SET status = EXCLUDED.status, decided_by = EXCLUDED.decided_by, "
                "decided_at = now(), updated_at = now()", (low, high, VERSION, status, actor))


def merge(conn: psycopg.Connection[Any], keep_id: int, merge_id: int, *, actor: str, note: str | None = None,
          force: bool = False) -> int:
    """Merge referee ``merge_id`` into ``keep_id``: his aliases move, he is marked merged. Refused when the two have matches at
    the same time (they are two people) unless ``force``. Returns the id of the event (what ``undo`` takes)."""
    if keep_id == merge_id:
        raise ActionError("invalid", "a referee cannot be merged into himself")
    with conn.transaction():
        _lock(conn, wait=True)
        with conn.cursor() as cur:
            _active(cur, (keep_id, merge_id))
        clashes = ri.collisions(games_of(conn, keep_id), games_of(conn, merge_id), ri.DEFAULT_PARAMS.collision_minutes)
        if clashes and not force:
            raise ActionError("collision", f"the two referees have {clashes} matches at the same time: they are two people")
        with conn.cursor() as cur:
            cur.execute("SELECT id, basis, placed_by FROM core.referee_aliases WHERE referee_id = %s ORDER BY id", (merge_id,))
            moved = cur.fetchall()
            ids = [int(r[0]) for r in moved]
            cur.execute("UPDATE core.referee_aliases SET referee_id = %s, basis = 'manual', placed_by = 'manual' WHERE referee_id = %s",
                        (keep_id, merge_id))
            cur.execute("UPDATE core.referees SET status = 'merged', merged_into = %s, updated_at = now() WHERE id = %s", (keep_id, merge_id))
            cur.execute("DELETE FROM core.referee_candidates WHERE status = 'open' AND (referee_a = %s OR referee_b = %s)", (merge_id, merge_id))
            _set_decision(cur, keep_id, merge_id, "merged", actor)
            event = _event(cur, actor=actor, action="merge", referee_id=keep_id, other_id=merge_id, alias_ids=ids,
                           detail={"note": note, "forced": bool(force and clashes), "collisions": clashes,
                                   "previous": {str(r[0]): [r[1], r[2]] for r in moved}})
        refresh_identity(conn, keep_id)
    return event


def undo(conn: psycopg.Connection[Any], event_id: int, *, actor: str) -> int:
    """Reverse a merge: the aliases it moved go back to the referee it merged (those a later action moved elsewhere stay where
    they are and are listed), who is active again; the pair is rejected so it is not suggested again."""
    with conn.transaction():
        _lock(conn, wait=True)
        with conn.cursor() as cur:
            cur.execute("SELECT referee_id, other_id, alias_ids, undone_by, action, detail FROM core.referee_events WHERE id = %s FOR UPDATE", (event_id,))
            row = cur.fetchone()
            if row is None or row[4] != "merge":
                raise ActionError("not_found", f"there is no merge event {event_id}")
            keep_id, merged_id, alias_ids, undone_by, _, detail = row
            if undone_by is not None:
                raise ActionError("conflict", f"merge {event_id} was already undone (event {undone_by})")
            cur.execute("SELECT status, merged_into FROM core.referees WHERE id = %s FOR UPDATE", (merged_id,))
            state = cur.fetchone()
            if state is None or state[0] != "merged" or state[1] != keep_id:
                raise ActionError("conflict", "that referee has been merged again since: undo the later merge first")
            previous = (detail or {}).get("previous", {})
            skipped: list[int] = []
            restored: list[int] = []
            for alias_id in alias_ids:
                basis, placed_by = previous.get(str(alias_id), ["identity", "rules"])
                cur.execute("UPDATE core.referee_aliases SET referee_id = %s, basis = %s, placed_by = %s "
                            "WHERE id = %s AND referee_id = %s", (merged_id, basis, placed_by, alias_id, keep_id))
                (restored if cur.rowcount else skipped).append(int(alias_id))
            cur.execute("UPDATE core.referees SET status = 'active', merged_into = NULL, updated_at = now() WHERE id = %s", (merged_id,))
            _set_decision(cur, keep_id, merged_id, "rejected", actor)
            undo_id = _event(cur, actor=actor, action="undo", referee_id=keep_id, other_id=merged_id, alias_ids=restored,
                             detail={"of": event_id, "skipped": skipped})
            cur.execute("UPDATE core.referee_events SET undone_by = %s WHERE id = %s", (undo_id, event_id))
        refresh_identity(conn, keep_id)
        refresh_identity(conn, int(merged_id))
    return undo_id


def split(conn: psycopg.Connection[Any], referee_id: int, alias_ids: Sequence[int], *, actor: str, name: str | None = None,
          note: str | None = None) -> int:
    """Move some aliases of a referee to a NEW referee (two people were taken for one). At least one alias stays. The pair is
    rejected so the machine does not suggest joining them again. Returns the id of the new referee."""
    wanted = sorted(set(alias_ids))
    if not wanted:
        raise ActionError("invalid", "name the aliases to split off")
    with conn.transaction():
        _lock(conn, wait=True)
        with conn.cursor() as cur:
            _active(cur, (referee_id,))
            cur.execute("SELECT id, name_key, scope, display, basis, placed_by FROM core.referee_aliases WHERE referee_id = %s ORDER BY id FOR UPDATE", (referee_id,))
            mine = {int(r[0]): r for r in cur.fetchall()}
            if any(a not in mine for a in wanted):
                raise ActionError("invalid", "an alias does not belong to that referee")
            if len(wanted) >= len(mine):
                raise ActionError("invalid", "at least one alias has to stay with the referee")
            first = min((mine[a] for a in wanted), key=lambda r: ri.canonical_rank(r[1], r[2], 0))
            shown = (name or "").strip() or first[3]
            cur.execute("INSERT INTO core.referees (name, name_key, country_key, name_locked, origin, version) "
                        "VALUES (%s, %s, %s, %s, 'manual', %s) RETURNING id",
                        (shown, plain(shown) if name else first[1], None if first[2] == UNKNOWN_SCOPE else first[2], bool(name), VERSION))
            created = cur.fetchone()
            assert created is not None
            new_id = int(created[0])
            cur.execute("UPDATE core.referee_aliases SET referee_id = %s, basis = 'manual', placed_by = 'manual' WHERE id = ANY(%s)", (new_id, wanted))
            _set_decision(cur, referee_id, new_id, "rejected", actor)
            _event(cur, actor=actor, action="split", referee_id=referee_id, other_id=new_id, alias_ids=wanted,
                   detail={"note": note, "previous": {str(a): [mine[a][4], mine[a][5]] for a in wanted}})
        refresh_identity(conn, referee_id)
        refresh_identity(conn, new_id)
    return new_id


def reject(conn: psycopg.Connection[Any], referee_a: int, referee_b: int, *, actor: str, note: str | None = None) -> int:
    """Say that two referees are different people: the pair is never suggested again (a pair never suggested is recorded).
    Returns the id of the event."""
    if referee_a == referee_b:
        raise ActionError("invalid", "a referee is the same person as himself")
    with conn.transaction():
        _lock(conn, wait=True)
        with conn.cursor() as cur:
            _active(cur, (referee_a, referee_b))
            _set_decision(cur, referee_a, referee_b, "rejected", actor)
            return _event(cur, actor=actor, action="reject", referee_id=min(referee_a, referee_b), other_id=max(referee_a, referee_b),
                          detail={"note": note})


def reopen(conn: psycopg.Connection[Any], referee_a: int, referee_b: int, *, actor: str) -> int:
    """Take back a rejection: the pair is a question again (the next pass refreshes it, or removes it if nothing suggests it).
    Returns the id of the event."""
    low, high = min(referee_a, referee_b), max(referee_a, referee_b)
    with conn.transaction():
        _lock(conn, wait=True)
        with conn.cursor() as cur:
            cur.execute("UPDATE core.referee_candidates SET status = 'open', decided_by = NULL, decided_at = NULL, updated_at = now() "
                        "WHERE referee_a = %s AND referee_b = %s AND status = 'rejected'", (low, high))
            if not cur.rowcount:
                raise ActionError("not_found", "that pair is not rejected")
            return _event(cur, actor=actor, action="reopen", referee_id=low, other_id=high)


def rename(conn: psycopg.Connection[Any], referee_id: int, name: str | None, *, actor: str) -> int:
    """Set the name a referee is shown with (the pass keeps it from then on); ``None`` gives the naming back to the pass.
    Returns the id of the event."""
    shown = (name or "").strip()
    if name is not None and not plain(shown):
        raise ActionError("invalid", "a name is needed")
    with conn.transaction():
        _lock(conn, wait=True)
        with conn.cursor() as cur:
            before = _active(cur, (referee_id,))[referee_id]
            if name is None:
                cur.execute("UPDATE core.referees SET name_locked = false, updated_at = now() WHERE id = %s", (referee_id,))
            else:
                cur.execute("UPDATE core.referees SET name = %s, name_key = %s, name_locked = true, updated_at = now() WHERE id = %s",
                            (shown, plain(shown), referee_id))
            event = _event(cur, actor=actor, action="rename", referee_id=referee_id, detail={"from": before[0], "to": shown or None})
        if name is None:
            refresh_identity(conn, referee_id)
    return event


# ── audit ────────────────────────────────────────────────────────────────────────────────────────────────────────────

COUNTS: Final = (
    ("referees_active", "SELECT count(*) FROM core.referees WHERE status = 'active'"),
    ("referees_merged", "SELECT count(*) FROM core.referees WHERE status = 'merged'"),
    ("aliases", "SELECT count(*) FROM core.referee_aliases"),
    ("aliases_on_merged_referee", "SELECT count(*) FROM core.referee_aliases a JOIN core.referees r ON r.id = a.referee_id WHERE r.status <> 'active'"),
    ("active_without_alias", "SELECT count(*) FROM core.referees r WHERE r.status = 'active' AND NOT EXISTS (SELECT 1 FROM core.referee_aliases a WHERE a.referee_id = r.id)"),
    ("officials_rows", "SELECT count(*) FROM core.fixture_officials"),
    ("fixtures_with_referee", "SELECT count(*) FROM core.fixture_referees"),
    ("candidates_open", "SELECT count(*) FROM core.referee_candidates WHERE status = 'open'"),
    ("candidates_rejected", "SELECT count(*) FROM core.referee_candidates WHERE status = 'rejected'"),
    ("candidates_merged", "SELECT count(*) FROM core.referee_candidates WHERE status = 'merged'"),
    ("candidates_on_merged_referee", "SELECT count(*) FROM core.referee_candidates c JOIN core.referees r ON r.id IN (c.referee_a, c.referee_b) WHERE c.status = 'open' AND r.status <> 'active'"),
)
# The matches whose referee has a doubt waiting: the smaller side of every open pair, each referee once.
UNSETTLED_SQL: Final = """
WITH sides AS (
    SELECT CASE WHEN ga <= gb THEN c.referee_a ELSE c.referee_b END AS referee_id
      FROM (SELECT c.*, (SELECT count(*) FROM core.fixture_referees x JOIN core.referee_aliases a ON a.id = x.alias_id WHERE a.referee_id = c.referee_a) AS ga,
                        (SELECT count(*) FROM core.fixture_referees x JOIN core.referee_aliases a ON a.id = x.alias_id WHERE a.referee_id = c.referee_b) AS gb
              FROM core.referee_candidates c WHERE c.status = 'open') c
)
SELECT count(*) FROM core.fixture_referees fr JOIN core.referee_aliases a ON a.id = fr.alias_id
 WHERE a.referee_id IN (SELECT referee_id FROM sides)
"""


INVARIANTS: Final = ("aliases_on_merged_referee", "active_without_alias", "candidates_on_merged_referee")
"""Counts that must be zero: an alias on a merged referee, an active referee with no spelling, an open doubt about a merged one."""


def counts(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """The figures of the tables and the share of matches whose referee has no doubt waiting - cheap: no pass is simulated (the
    console reads this; ``audit`` adds what a pass would write)."""
    out: dict[str, Any] = {}
    with conn.cursor() as cur:
        for name, sql in COUNTS:
            cur.execute(sql)
            row = cur.fetchone()
            out[name] = int(row[0]) if row else 0
        cur.execute(UNSETTLED_SQL)
        row = cur.fetchone()
        out["matches_with_a_doubt"] = int(row[0]) if row else 0
    placed = out["fixtures_with_referee"]
    out["settled_share"] = round(1 - out["matches_with_a_doubt"] / placed, 4) if placed else 1.0
    return out


def broken_invariants(figures: dict[str, Any]) -> list[str]:
    """The invariants of the tables that do not hold in ``figures`` (an audit or ``counts``); empty when all is well."""
    return [name for name in INVARIANTS if figures[name]]


def audit(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """The state of the referees, read from the database, and what a pass would still write (it must be nothing)."""
    out = counts(conn)
    pending = build(conn, apply=False, wait=True)
    out["with_a_referee_in_the_facts"] = pending.fixtures
    out["pass_would_write"] = {"referees": pending.new_referees, "aliases": pending.new_aliases, "officials": pending.officials_to_write,
                               "renames": pending.renamed, "candidates": pending.candidates_added + pending.candidates_changed}
    placed = out["fixtures_with_referee"]
    out["placed_share"] = round(placed / pending.fixtures, 4) if pending.fixtures else 1.0
    return out


def counts_by_basis(conn: psycopg.Connection[Any]) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT basis, count(*) FROM core.referee_aliases GROUP BY basis")
        return {str(b): int(n) for b, n in cur.fetchall()}


def aliases_of(conn: psycopg.Connection[Any], referee_id: int) -> list[dict[str, Any]]:
    """The spellings of a referee and the matches each one is the newest word on (for the console and the API)."""
    with conn.cursor() as cur:
        cur.execute("SELECT a.id, a.name_key, a.scope, a.display, a.basis, a.placed_by, count(fr.fixture_id), min(x.kickoff_at), max(x.kickoff_at) "
                    "FROM core.referee_aliases a LEFT JOIN core.fixture_referees fr ON fr.alias_id = a.id "
                    "LEFT JOIN core.fixtures x ON x.id = fr.fixture_id WHERE a.referee_id = %s GROUP BY a.id ORDER BY count(fr.fixture_id) DESC, a.id",
                    (referee_id,))
        return [{"id": int(i), "name_key": k, "scope": s, "display": d, "basis": b, "placed_by": p, "matches": int(n),
                 "first": f, "last": la} for i, k, s, d, b, p, n, f, la in cur.fetchall()]


# ── what the console and the API read ───────────────────────────────────────────────────────────────────────────────────

MATCHES_OF_SQL: Final = (
    "(SELECT count(*) FROM core.fixture_referees x JOIN core.referee_aliases a ON a.id = x.alias_id WHERE a.referee_id = {col})")
"""The matches a referee has now (``{col}`` is the column holding his id)."""

QUEUE_SQL: Final = f"""
WITH page AS (
    SELECT c.id, c.referee_a, c.referee_b, c.reason, c.score, c.impact, c.evidence, c.status, c.decided_by, c.decided_at
      FROM core.referee_candidates c
     WHERE c.status = %(status)s AND (%(reason)s::text IS NULL OR c.reason = %(reason)s::text)
     ORDER BY c.impact DESC, c.score DESC, c.id
     LIMIT %(limit)s OFFSET %(offset)s
)
SELECT p.id, p.referee_a, p.referee_b, p.reason, p.score, p.impact, p.evidence, p.status, p.decided_by, p.decided_at,
       ra.name AS name_a, ra.country_key AS country_a, rb.name AS name_b, rb.country_key AS country_b,
       {MATCHES_OF_SQL.format(col="p.referee_a")} AS matches_a, {MATCHES_OF_SQL.format(col="p.referee_b")} AS matches_b
  FROM page p JOIN core.referees ra ON ra.id = p.referee_a JOIN core.referees rb ON rb.id = p.referee_b
 ORDER BY p.impact DESC, p.score DESC, p.id
"""


def queue(conn: psycopg.Connection[Any], *, status: str = "open", reason: str | None = None, limit: int = 50,
          offset: int = 0) -> list[dict[str, Any]]:
    """The pairs waiting for a person (``status='open'``) or already decided, the ones that touch most matches first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(QUEUE_SQL, {"status": status, "reason": reason, "limit": limit, "offset": offset})
        return list(cur.fetchall())


def queue_size(conn: psycopg.Connection[Any], *, status: str = "open", reason: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.referee_candidates WHERE status = %s AND (%s::text IS NULL OR reason = %s::text)",
                    (status, reason, reason))
        row = cur.fetchone()
        return int(row[0]) if row else 0


REFEREE_SQL: Final = f"""
SELECT r.id, r.name, r.name_key, r.country_key, r.name_locked, r.status, r.merged_into, r.origin, r.version, r.created_at,
       r.updated_at, {MATCHES_OF_SQL.format(col="r.id")} AS matches,
       (SELECT min(x.kickoff_at) FROM core.fixture_referees fr JOIN core.referee_aliases a ON a.id = fr.alias_id
          JOIN core.fixtures x ON x.id = fr.fixture_id WHERE a.referee_id = r.id) AS first_match,
       (SELECT max(x.kickoff_at) FROM core.fixture_referees fr JOIN core.referee_aliases a ON a.id = fr.alias_id
          JOIN core.fixtures x ON x.id = fr.fixture_id WHERE a.referee_id = r.id) AS last_match
  FROM core.referees r
"""


def referee_row(conn: psycopg.Connection[Any], referee_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(REFEREE_SQL + " WHERE r.id = %s", (referee_id,))
        return cur.fetchone()


TOP_SQL: Final = """
SELECT r.id, r.name, r.name_key, r.country_key, r.name_locked, r.status, r.merged_into, r.origin, r.version, r.created_at,
       r.updated_at, COALESCE(s.matches, 0) AS matches, s.first_match, s.last_match
  FROM core.referees r
  LEFT JOIN (SELECT a.referee_id, count(*) AS matches, min(x.kickoff_at) AS first_match, max(x.kickoff_at) AS last_match
               FROM core.fixture_referees fr JOIN core.referee_aliases a ON a.id = fr.alias_id
               JOIN core.fixtures x ON x.id = fr.fixture_id GROUP BY a.referee_id) s ON s.referee_id = r.id
 WHERE r.status = 'active'
 ORDER BY matches DESC, r.id
 LIMIT %(limit)s OFFSET %(offset)s
"""


def top(conn: psycopg.Connection[Any], *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """The active referees with most matches first (one pass over the placed matches, whatever the page)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TOP_SQL, {"limit": limit, "offset": offset})
        return list(cur.fetchall())


def find(conn: psycopg.Connection[Any], text: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Active referees whose name, or any spelling of it, contains the words of ``text`` (accents and case do not matter)."""
    words = plain(text).split()
    if not words:
        return []
    pattern = "%" + "%".join(words) + "%"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM (" + REFEREE_SQL + " WHERE r.status = 'active' AND (r.name_key LIKE %(p)s OR EXISTS ("
                    "SELECT 1 FROM core.referee_aliases a WHERE a.referee_id = r.id AND a.name_key LIKE %(p)s))) q "
                    "ORDER BY q.matches DESC, q.id LIMIT %(limit)s", {"p": pattern, "limit": limit})
        return list(cur.fetchall())


def candidates_of(conn: psycopg.Connection[Any], referee_id: int, *, status: str = "open") -> list[dict[str, Any]]:
    """The pairs a referee is in, with the other one."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT c.id, c.reason, c.score, c.impact, c.evidence, c.status, c.decided_by, c.decided_at, o.id AS other_id, "
            f"o.name AS other_name, o.country_key AS other_country, {MATCHES_OF_SQL.format(col='o.id')} AS other_matches "
            "FROM core.referee_candidates c JOIN core.referees o ON o.id = CASE WHEN c.referee_a = %(id)s THEN c.referee_b ELSE c.referee_a END "
            "WHERE %(id)s IN (c.referee_a, c.referee_b) AND c.status = %(status)s ORDER BY c.impact DESC, c.score DESC, c.id",
            {"id": referee_id, "status": status})
        return list(cur.fetchall())


def events_of(conn: psycopg.Connection[Any], referee_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
    """What was changed about a referee (as the one kept, the one merged or the one split off), newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT e.id, e.at, e.actor, e.action, e.referee_id, e.other_id, e.alias_ids, e.undone_by, e.detail "
                    "FROM core.referee_events e WHERE %(id)s IN (e.referee_id, e.other_id) ORDER BY e.at DESC, e.id DESC LIMIT %(limit)s",
                    {"id": referee_id, "limit": limit})
        return list(cur.fetchall())


def recent_matches(conn: psycopg.Connection[Any], referee_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    """The newest matches a referee has, with the spelling the provider used for each."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT x.id AS fixture_id, x.kickoff_at, th.name AS home, ta.name AS away, c.name AS competition, s.season, "
                    "a.display AS spelling "
                    "FROM core.fixture_referees fr JOIN core.referee_aliases a ON a.id = fr.alias_id AND a.referee_id = %(id)s "
                    "JOIN core.fixtures x ON x.id = fr.fixture_id JOIN core.teams th ON th.id = x.home_team_id "
                    "JOIN core.teams ta ON ta.id = x.away_team_id JOIN core.competition_seasons s ON s.id = x.competition_season_id "
                    "JOIN core.competitions c ON c.id = s.competition_id ORDER BY x.kickoff_at DESC NULLS LAST, x.id DESC LIMIT %(limit)s",
                    {"id": referee_id, "limit": limit})
        return list(cur.fetchall())
