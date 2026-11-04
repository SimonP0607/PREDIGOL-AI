"""The arms of the shadow of phase 3, and the assignment of each match to one (plan IA, sections 22 and 23; ``ai.shadow_assignments``, ``arms-v1``).

Seven arms are compared on the same selections. Four of them cost nothing the orchestrator has to run (the model alone, the rules, the gap filter
and today's AI are what production already computes); THREE are shadow engines the orchestrator runs over a sample of the matches that have
candidates, in the LAB workspace, and write as reviews no decision reads:

    ``ma-v1``    MULTIAGENTE: the Match Agent, the contradiction detector and the Council (Sonnet, Opus by rule) - the sample
    ``ma-v1-h``  MULTIAGENTE + COUNCIL HAIKU: the same, with Haiku as the judge - the same sample, the same schedule, the same rules for Opus
    ``cs-v1``    COUNCIL SOLO: the Council (Sonnet) reading the compact view with no specialists - HALF of the sample (15 % of all the matches
                 when the sample is 30 %)

Who is in which arm is decided ONCE per match, by arithmetic and not by luck, and then remembered, because the comparison is only worth something
if no match changes group and no group changes its way of working half way:

* ``bucket(fixture_id, salt)`` puts every match in one of 10,000 buckets: the first eight bytes of ``sha256("<salt>:<fixture_id>")``, read big endian,
  modulo 10,000. It has no state and no clock, it is the same on every worker, every platform and every version of Python (never ``hash()``, which
  Python salts at every start), and it is uniform for any set of ids a league can produce.
* A match is SAMPLED when ``bucket < share * 10000``. The samples of two shares are NESTED: a match sampled at 30 % is sampled at 50 %, so raising the
  share only ADDS matches and never takes one out of the analysis.
* A sampled match runs ``ma-v1`` and ``ma-v1-h``; it ALSO runs ``cs-v1`` when a SECOND hash - ``sha256("<salt>:cs:<fixture_id>")``, the same
  reduction - falls in the first half of the buckets (``SOLO_SHARE``). Two hashes of two different texts are independent, so the COUNCIL SOLO half
  is not the low half of the sample but a half of it spread like the rest, and it is nested too.
* ``ai.shadow_assignments`` stores, per match and experiment, the bucket, the two decisions and the SHARE IN FORCE when it was assigned. The first
  row wins and is never changed ("ningun partido cambia de grupo"): a match first seen at 30 % and not sampled stays out when the owner raises the
  share to 50 %, and only the matches seen afterwards are assigned at the new share. The table itself refuses a row that contradicts the rule
  (``sampled`` is exactly ``bucket < share * 10000``; COUNCIL SOLO needs the sample), so the code and the database cannot drift apart.
* The experiment is its SALT (``SALT``): another salt is another experiment with its own groups, and so is a change to this file's way of hashing,
  which would be a new ``ARMS_VERSION`` and a new salt, never an edit.

``FBI_AI_ENGINES`` can narrow the arms (the plan's activation names ``ma-v1`` and ``ma-v1-h`` only, so COUNCIL SOLO does not run until the owner
adds ``cs-v1``): the assignment says what a match is in, ``runnable`` says what may run for it today, and the assignment is stored whatever the
owner has switched on, so that switching ``cs-v1`` on later does not re-draw the groups.

How a caller uses it (the orchestrator, once per pass, before it spends anything on a match)::

    assigned = arms.assign(conn, fixture_ids, at=now, share=settings.shadow_sample)
    conn.commit()                       # the assignment is the experiment's memory: it is written before the first shadow pass
    for fixture_id, arm in assigned.items():
        for engine in arms.runnable(arm, settings.shadow_engines): ...

Nothing here calls a model or reads anything but the table: a failure of the database propagates (the orchestrator catches it, and a failure of
the AI never stops the quantitative pipeline). ``assign`` does not commit: two workers that assign the same match at once agree on the row of the
first, and the second waits for the first to commit, so commit before the pass starts. It needs the isolation level psycopg gives by default (READ
COMMITTED) and a timezone-aware ``at``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

ARMS_VERSION: Final = "arms-v1"
"""The way a match is put in an arm. A change to the hash, the bucket count or the rules below is a new version and a new salt - never an edit."""
SALT: Final = "ma-shadow-v1"
"""The experiment's salt, and its name in ``ai.shadow_assignments.experiment``: another salt is another experiment."""
BUCKETS: Final = 10_000
"""How many buckets a match can fall in: a share of 0.3 samples the buckets below 3000 (``ai.shadow_assignments`` holds the same number)."""

MULTIAGENT: Final = "ma-v1"
MULTIAGENT_HAIKU: Final = "ma-v1-h"
COUNCIL_SOLO: Final = "cs-v1"
SAMPLE_ENGINES: Final[tuple[str, ...]] = (MULTIAGENT, MULTIAGENT_HAIKU)
"""What every sampled match runs. ``fbi.ai.config.SHADOW_ENGINES`` is these and ``COUNCIL_SOLO`` (a test holds them together)."""
SOLO_SHARE: Final = Decimal("0.5")
"""The share of the SAMPLE that also runs COUNCIL SOLO: half of it, 15 % of all the matches when the sample is 30 %."""

EXPERIMENT: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
"""The name of an experiment, the way an agent or a version is named (``fbi.ai.idempotency.NAME`` and the CHECK of the table say the same)."""


@dataclass(frozen=True, slots=True)
class Assignment:
    """The arms a match is in: whether it is in the sample, whether it is also in COUNCIL SOLO, and the shadow engines that follow (in the order of
    ``fbi.ai.config.KNOWN_ENGINES``). A match outside the sample is in no arm and has no engine."""

    sampled: bool
    council_solo: bool
    engines: tuple[str, ...]


OUTSIDE: Final = Assignment(sampled=False, council_solo=False, engines=())
"""The assignment of a match that is not in the sample."""


def _assignment(sampled: bool, council_solo: bool) -> Assignment:
    if not sampled:
        return OUTSIDE
    return Assignment(sampled=True, council_solo=council_solo, engines=(*SAMPLE_ENGINES, COUNCIL_SOLO) if council_solo else SAMPLE_ENGINES)


def _fixture(fixture_id: int) -> int:
    if isinstance(fixture_id, bool) or not isinstance(fixture_id, int) or fixture_id < 1:
        raise ValueError(f"a fixture id is a whole number from 1: {fixture_id!r}")
    return fixture_id


def _salt(salt: str) -> str:
    if not isinstance(salt, str) or not EXPERIMENT.fullmatch(salt):
        raise ValueError(f"an experiment is named like an agent version (ASCII letters, digits, '.', '_' and '-', up to 64): {salt!r}")
    return salt


def _bucket_of(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big") % BUCKETS


def bucket(fixture_id: int, salt: str = SALT) -> int:
    """The bucket of a match, 0 to 9999: the first hash. Pure and stable: ``sha256("<salt>:<fixture_id>")``, first eight bytes, big endian, modulo
    ``BUCKETS``."""
    return _bucket_of(f"{_salt(salt)}:{_fixture(fixture_id)}")


def solo_bucket(fixture_id: int, salt: str = SALT) -> int:
    """The second hash of a match, 0 to 9999, that picks COUNCIL SOLO among the sampled: ``sha256("<salt>:cs:<fixture_id>")``, reduced the same way.
    It reads the same salt and a different text, so it does not depend on ``bucket``."""
    return _bucket_of(f"{_salt(salt)}:cs:{_fixture(fixture_id)}")


def _share(share: Decimal) -> Fraction:
    if not isinstance(share, Decimal) or not share.is_finite() or not Decimal(0) <= share <= Decimal(1):
        raise ValueError(f"a share is a number from 0 to 1: {share!r}")
    return Fraction(share)


def _in_range(value: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < BUCKETS:
        raise ValueError(f"{what} is a whole number from 0 to {BUCKETS - 1}: {value!r}")
    return value


def arms_for(bucket: int, share: Decimal, second: int | None = None) -> Assignment:
    """The arms of a match from its bucket and the share of the sample: sampled when ``bucket < share * 10000`` - an exact comparison, no rounding
    - and, for a sampled match whose SECOND bucket (``solo_bucket``) is below ``SOLO_SHARE * 10000``, also in COUNCIL SOLO. Without a second bucket
    no match is in COUNCIL SOLO. A share of 0 samples nobody; a share of 1, everybody. Nested: a larger share never un-samples a bucket."""
    fraction = _share(share)
    sampled = Fraction(_in_range(bucket, "a bucket")) < fraction * BUCKETS
    solo = (second is not None and Fraction(_in_range(second, "a second bucket")) < Fraction(SOLO_SHARE) * BUCKETS)
    return _assignment(sampled, sampled and solo)


def arms_of(fixture_id: int, share: Decimal, salt: str = SALT) -> Assignment:
    """The arms a match WOULD be in at this share: both hashes and the rule. What it IS in is what ``assign`` stored the first time."""
    return arms_for(bucket(fixture_id, salt), share, solo_bucket(fixture_id, salt))


def runnable(assignment: Assignment, enabled: Iterable[str]) -> tuple[str, ...]:
    """The shadow engines that may run for a match today: the ones it is assigned to and the owner has switched on (``FBI_AI_ENGINES``), in the
    order of the assignment. Nothing the owner has not named runs, and nothing outside the sample does."""
    allowed = frozenset(enabled)
    return tuple(engine for engine in assignment.engines if engine in allowed)


INSERT_SQL: Final = """
INSERT INTO ai.shadow_assignments (experiment, fixture_id, bucket, sampled, council_solo, share, assigned_at)
SELECT %(experiment)s, a.fixture_id, a.bucket, a.sampled, a.council_solo, %(share)s, %(at)s
  FROM unnest(%(ids)s::bigint[], %(buckets)s::integer[], %(sampled)s::boolean[], %(solo)s::boolean[]) AS a(fixture_id, bucket, sampled, council_solo)
 ORDER BY a.fixture_id
ON CONFLICT (experiment, fixture_id) DO NOTHING
"""
"""One statement for all the matches: the ones with a row already are left as they are (``DO NOTHING`` is the whole of "never changes group").
The rows go in by fixture id whatever the order asked: two workers that assign overlapping sets take the keys in the same order, so they wait for
each other and never deadlock."""
STORED_SQL: Final = """
SELECT fixture_id, sampled, council_solo FROM ai.shadow_assignments WHERE experiment = %(experiment)s AND fixture_id = ANY(%(ids)s::bigint[])
"""


def stored(conn: psycopg.Connection[Any], fixture_ids: Iterable[int], *, experiment: str = SALT) -> dict[int, Assignment]:
    """What ``assign`` stored for these matches, by match. A match that has no row is not in the answer (it was never assigned, or the share was 0)."""
    ids = list(dict.fromkeys(_fixture(i) for i in fixture_ids))
    if not ids:
        return {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(STORED_SQL, {"experiment": _salt(experiment), "ids": ids})
        rows = cur.fetchall()
    return {int(fixture_id): _assignment(bool(sampled), bool(solo)) for fixture_id, sampled, solo in rows}


def assign(conn: psycopg.Connection[Any], fixture_ids: Iterable[int], *, at: datetime, share: Decimal, experiment: str = SALT) -> dict[int, Assignment]:
    """Put every match that has no assignment in its arms, at this share, and answer with the STORED assignment of each (the caller commits, BEFORE
    the first shadow pass of the match).

    A match that already has a row keeps it - whatever the share is now, whatever ``at`` says: the first row of a match in an experiment is its group
    for good. With a share of 0 nothing is written (no match is assigned while the shadow is off) and a match with no row answers ``OUTSIDE``; the
    answer has every match asked about, once, in the order asked. A share outside 0 to 1, a naive ``at``, a fixture id that is not a whole number
    from 1 or an experiment that is not named like one is a ``ValueError`` before the database is touched, so that a bad call never leaves the
    caller's transaction aborted."""
    fraction = _share(share)
    name = _salt(experiment)
    ids = list(dict.fromkeys(_fixture(i) for i in fixture_ids))
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("the moment of an assignment has a timezone")
    if not ids:
        return {}
    if fraction > 0:
        drawn = [(i, bucket(i, name), arms_of(i, share, name)) for i in ids]
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(INSERT_SQL, {"experiment": name, "share": share, "at": at, "ids": [i for i, _, _ in drawn],
                                     "buckets": [b for _, b, _ in drawn], "sampled": [a.sampled for _, _, a in drawn],
                                     "solo": [a.council_solo for _, _, a in drawn]})
    found = stored(conn, ids, experiment=name)
    return {i: found.get(i, OUTSIDE) for i in ids}
