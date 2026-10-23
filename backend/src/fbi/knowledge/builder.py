"""Match Knowledge, built (plan F7): which finished matches are due, the build of each, and where it is written.

``fbi.knowledge.layers`` is pure (inputs in, nine layers out) and ``fbi.knowledge.reader`` reads the inputs. This module is what runs them
over the database:

* ``refresh_pending`` is the worker's pass: the finished matches that have been SETTLED (``SETTLE`` after kick-off: the provider's last
  re-read of a match) in the last ``days`` days, newest first, each built if what it is made of is not what its newest build read;
* ``build_many`` is the same for a list of matches (the console, a backfill);
* ``coverage`` says, from the outside, how many of the finished matches have a build and how complete.

A match is built again only when the fingerprint of its inputs (``reader.signatures``) is not the one the newest build stored: reading a
match whose facts have not changed costs a few aggregate queries and writes nothing. When it is built the new row names the build it
replaced (``supersedes``) and the database lets a build be replaced once, so two builders that meet - the worker and a person at the
console - cannot both add the next row: the one that finds the place taken leaves it (``raced``). The lines of the match's events are
rewritten in ``core.fixture_event_kinds`` in the same transaction, and only by the builder that owns the new row.

A match that fails (a defect in a rule, a value the layers refuse) is rolled back to its own savepoint, logged and reported; the others go
on. The caller commits, unless ``commit`` is set (a chunk of matches at a time).
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
import structlog
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.knowledge import events as ev
from fbi.knowledge import layers, reader

log = structlog.get_logger(__name__)

JOB: Final = "match_knowledge"
SETTLE: Final = timedelta(hours=26)
"""A match is built when it is over and settled: the provider re-reads a finished match for a day, and its last read is what is kept."""
DEFAULT_DAYS: Final = 10
"""The window of the worker's pass: the matches that kicked off in the last ten days (a correction later than that is for the wide pass)."""
MAX_FAILED_CHUNKS: Final = 3
"""A pass whose last chunks all failed to be read stops: the database is not well, and asking again and again does not help it."""

CANDIDATES_SQL: Final = """
SELECT f.id FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND (NOT %(tracked)s OR c.is_tracked)
 ORDER BY f.kickoff_at DESC, f.id DESC
"""

NEWEST_SQL: Final = """
SELECT k.fixture_id, m.id, m.inputs_hash, m.content_hash
  FROM unnest(%(ids)s::bigint[]) AS k(fixture_id)
 CROSS JOIN LATERAL (SELECT x.id, x.inputs_hash, x.content_hash FROM intel.match_knowledge x
                      WHERE x.fixture_id = k.fixture_id AND x.version = %(version)s ORDER BY x.id DESC LIMIT 1) m
"""

INSERT_SQL: Final = """
INSERT INTO intel.match_knowledge (fixture_id, version, supersedes, known_at, inputs_hash, content_hash, completeness, layers, quality)
VALUES (%(fixture)s, %(version)s, %(supersedes)s, %(known_at)s, %(inputs)s, %(content)s, %(completeness)s, %(layers)s, %(quality)s)
ON CONFLICT DO NOTHING
RETURNING id
"""

KINDS_SOURCE: Final = reader.SOURCE
KINDS_DELETE_SQL: Final = "DELETE FROM core.fixture_event_kinds WHERE fixture_id = %s AND source = %s AND NOT (seq = ANY(%s::smallint[]))"
KINDS_UPSERT_SQL: Final = """
INSERT INTO core.fixture_event_kinds AS k (fixture_id, source, seq, rules_version, kind, period, side, player_side, pair_seq, flags, event_fetched_at)
SELECT %(fixture)s, %(source)s, u.seq, %(rules)s, u.kind, u.period, u.side, u.player_side, u.pair_seq,
       COALESCE(string_to_array(NULLIF(u.flags, ''), ','), '{}'::text[]), u.fetched_at
  FROM unnest(%(seq)s::smallint[], %(kind)s::text[], %(period)s::text[], %(side)s::text[], %(player_side)s::text[], %(pair)s::smallint[],
              %(flags)s::text[], %(fetched_at)s::timestamptz[])
       AS u(seq, kind, period, side, player_side, pair_seq, flags, fetched_at)
ON CONFLICT (fixture_id, source, seq) DO UPDATE
   SET rules_version = EXCLUDED.rules_version, kind = EXCLUDED.kind, period = EXCLUDED.period, side = EXCLUDED.side,
       player_side = EXCLUDED.player_side, pair_seq = EXCLUDED.pair_seq, flags = EXCLUDED.flags,
       event_fetched_at = EXCLUDED.event_fetched_at, built_at = now()
 WHERE (k.rules_version, k.kind, k.period, k.side, k.player_side, k.pair_seq, k.flags, k.event_fetched_at)
       IS DISTINCT FROM (EXCLUDED.rules_version, EXCLUDED.kind, EXCLUDED.period, EXCLUDED.side, EXCLUDED.player_side, EXCLUDED.pair_seq,
                         EXCLUDED.flags, EXCLUDED.event_fetched_at)
"""


@dataclass(frozen=True, slots=True)
class Build:
    """The newest stored build of a match."""

    id: int
    inputs_hash: str
    content_hash: str


@dataclass(slots=True)
class BuildReport:
    """What a pass did."""

    seen: int = 0
    """Matches looked at."""
    due: int = 0
    """... of which had no build, or whose inputs are not the ones their newest build read."""
    built: int = 0
    """Rows added (in a dry run, rows that would be)."""
    same_content: int = 0
    """... of which say what the newest build said (an input changed that no layer shows)."""
    raced: int = 0
    """Matches another builder replaced first: left to it."""
    failed: int = 0
    kinds: int = 0
    """Lines of ``core.fixture_event_kinds`` written or changed."""
    bytes: int = 0
    """What the layers of the rows built weigh as JSON text (a bound of what they take in the database, which compresses them)."""
    biggest: int = 0
    by_completeness: Counter[str] = field(default_factory=Counter)
    by_layer: Counter[str] = field(default_factory=Counter)
    """``"c3_events:ok"``: how many of the rows built had that layer in that state."""
    layer_bytes: Counter[str] = field(default_factory=Counter)
    stopped: str | None = None
    """``time``, ``limit`` or ``errors`` when the pass ended before the end of its queue."""
    left: int = 0
    """Matches of the queue not looked at when it stopped."""
    errors: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        mean = round(self.bytes / self.built) if self.built else 0
        return {"seen": self.seen, "due": self.due, "built": self.built, "same_content": self.same_content, "raced": self.raced,
                "failed": self.failed, "kinds": self.kinds, "bytes": self.bytes, "bytes_mean": mean, "bytes_max": self.biggest,
                "by_completeness": dict(self.by_completeness), "by_layer": dict(sorted(self.by_layer.items())),
                "layer_bytes": dict(sorted(self.layer_bytes.items())), "stopped": self.stopped, "left": self.left,
                "seconds": round(self.seconds, 2), "errors": self.errors[:5]}


# ── which matches ────────────────────────────────────────────────────────────────────────────────────────────────────────


def candidates(conn: psycopg.Connection[Any], *, now: datetime, days: int = DEFAULT_DAYS, until: datetime | None = None,
               tracked: bool = True) -> list[int]:
    """The finished matches that kicked off in the last ``days`` days and have been settled (``SETTLE``), newest first. Of the competitions
    PrediGol follows (``is_tracked``: the ones whose matches are followed, priced and judged) unless ``tracked`` is off."""
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL, {"since": now - timedelta(days=days), "until": until if until is not None else now - SETTLE,
                                     "tracked": tracked})
        return [int(r[0]) for r in cur.fetchall()]


def newest_builds(conn: psycopg.Connection[Any], fixture_ids: Sequence[int], *, version: str = layers.VERSION) -> dict[int, Build]:
    """The newest stored build of each match that has one."""
    ids = [int(i) for i in fixture_ids]
    if not ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(NEWEST_SQL, {"ids": ids, "version": version})
        return {int(r["fixture_id"]): Build(int(r["id"]), str(r["inputs_hash"]), str(r["content_hash"])) for r in cur.fetchall()}


def due_among(signatures: Mapping[int, str], newest: Mapping[int, Build]) -> list[int]:
    """The matches, in order, whose inputs are not those their newest build read (or that have no build)."""
    return [i for i, signature in signatures.items() if (build := newest.get(i)) is None or build.inputs_hash != signature]


# ── writing ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def rewrite_kinds(conn: psycopg.Connection[Any], fixture_id: int, events: Sequence[ev.Event], stamps: Mapping[int, datetime]) -> int:
    """Bring the lines of ``core.fixture_event_kinds`` of a match to what its events are: the lines that are gone are deleted, the others
    written when they differ. Returns how many lines were written or deleted. The caller holds the transaction."""
    changed = 0
    with conn.cursor() as cur:
        cur.execute(KINDS_DELETE_SQL, (fixture_id, KINDS_SOURCE, [e.seq for e in events]))
        changed += max(cur.rowcount, 0)
        if events:
            cur.execute(KINDS_UPSERT_SQL, {
                "fixture": fixture_id, "source": KINDS_SOURCE, "rules": ev.VERSION, "seq": [e.seq for e in events], "kind": [e.kind for e in events],
                "period": [e.period for e in events], "side": [e.side for e in events], "player_side": [e.player_side for e in events],
                "pair": [e.pair_seq for e in events], "flags": [",".join(e.flags) for e in events],
                "fetched_at": [stamps[e.seq] for e in events]})
            changed += max(cur.rowcount, 0)
    return changed


def write(conn: psycopg.Connection[Any], read: reader.Read, built: layers.Knowledge, *, inputs_hash: str,
          supersedes: int | None) -> tuple[int, int] | None:
    """Add the build as the successor of ``supersedes`` and rewrite the lines of the match's events, in one transaction. Returns the id of
    the new row and the lines written, or ``None`` when another builder replaced that build first (nothing is written then)."""
    fixture_id = read.inputs.fixture.id
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, {
                "fixture": fixture_id, "version": built.version, "supersedes": supersedes, "known_at": built.known_at, "inputs": inputs_hash,
                "content": built.content_hash, "completeness": built.completeness, "layers": Jsonb(built.layers), "quality": Jsonb(built.quality)})
            row = cur.fetchone()
        if row is None:
            return None
        return int(row[0]), rewrite_kinds(conn, fixture_id, built.events, read.event_stamps)


def _weigh(report: BuildReport, built: layers.Knowledge) -> None:
    sizes = {name: len(json.dumps(layer, separators=(",", ":"), ensure_ascii=False)) for name, layer in built.layers.items()}
    total = sum(sizes.values()) + len(json.dumps(built.quality, separators=(",", ":"), ensure_ascii=False))
    report.bytes += total
    report.biggest = max(report.biggest, total)
    report.by_completeness[built.completeness] += 1
    report.layer_bytes.update(sizes)
    for name, layer in built.layers.items():
        report.by_layer[f"{name}:{layer['status']}"] += 1


# ── a pass ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _recover(conn: psycopg.Connection[Any]) -> None:
    """A match that failed inside its own transaction block was rolled back to its savepoint. Only a connection left in an aborted
    transaction by something outside that block needs more."""
    if conn.info.transaction_status == TransactionStatus.INERROR:
        conn.rollback()


def _fail(conn: psycopg.Connection[Any], report: BuildReport, what: str, exc: Exception) -> None:
    if isinstance(exc, psycopg.Error) and conn.closed:
        raise exc
    _recover(conn)
    message = f"{what}: {type(exc).__name__}: {str(exc)[:300]}"
    report.failed += 1
    if len(report.errors) < 20:
        report.errors.append(message)
    log.warning("match_knowledge.failed", what=what, error=message[:300])


def _read_due(conn: psycopg.Connection[Any], due: Sequence[int], report: BuildReport) -> dict[int, reader.Read]:
    """The inputs of the matches that are due. A value of one match that the reader refuses is that match's failure, not its chunk's: the
    chunk is read again match by match and the matches that read are built. Trouble with the database is the chunk's (it is raised)."""
    if not due:
        return {}
    try:
        with conn.transaction():
            return reader.read(conn, due)
    except psycopg.Error:
        raise
    except Exception as exc:  # a defect of the reader or a value it does not know: find the match
        if len(due) == 1:
            _fail(conn, report, f"match {due[0]}", exc)
            return {}
    reads: dict[int, reader.Read] = {}
    for fixture_id in due:
        reads.update(_read_due(conn, [fixture_id], report))
    return reads


def build_many(conn: psycopg.Connection[Any], fixture_ids: Sequence[int], *, apply: bool = True, max_seconds: float | None = None,
               limit: int | None = None, commit: bool = True, chunk: int = reader.CHUNK,
               progress: Callable[[BuildReport], None] | None = None) -> BuildReport:
    """Look at the matches ``chunk`` at a time and build those that are due. Without ``apply`` nothing is written and the report says what
    would be. ``max_seconds`` stops between matches, ``limit`` after that many rows built; the report says why a pass stopped and how many
    matches were left. A match that fails does not stop the pass (see the module docstring)."""
    report = BuildReport()
    started = time.monotonic()
    queue = [int(i) for i in fixture_ids]
    step = max(chunk, 1)
    failed_chunks = 0

    def out_of_time() -> bool:
        return max_seconds is not None and time.monotonic() - started > max_seconds

    def reason() -> str | None:
        if out_of_time():
            return "time"
        return "limit" if limit is not None and report.built >= limit else None

    for start in range(0, len(queue), step):
        ids = queue[start:start + step]
        after = len(queue) - start - len(ids)
        stop = reason()
        if stop is not None:
            report.stopped, report.left = stop, len(queue) - start
            break
        try:
            signatures = reader.signatures(conn, ids)
            newest = newest_builds(conn, ids)
            due = due_among(signatures, newest)
            reads = _read_due(conn, due, report)
        except Exception as exc:  # the database, or a defect: this chunk is not looked at, the next one may be
            _fail(conn, report, f"matches {ids[0]}..{ids[-1]}", exc)
            failed_chunks += 1
            report.seen += len(ids)
            if failed_chunks >= MAX_FAILED_CHUNKS:
                report.stopped, report.left = "errors", after
                break
            continue
        failed_chunks = 0
        report.seen += len(ids)
        report.due += len(due)
        for position, fixture_id in enumerate(due):
            stop = reason()
            if stop is not None:
                report.stopped, report.left = stop, after + len(due) - position
                break
            read = reads.get(fixture_id)
            if read is None:  # not a match any more (deleted between the two reads), or one the reader refused (counted)
                continue
            try:
                built = layers.build(read.inputs)
                previous = newest.get(fixture_id)
                if apply:
                    added = write(conn, read, built, inputs_hash=signatures[fixture_id], supersedes=None if previous is None else previous.id)
                    if added is None:
                        report.raced += 1
                        continue
                    report.kinds += added[1]
                report.built += 1
                if previous is not None and previous.content_hash == built.content_hash:
                    report.same_content += 1
                _weigh(report, built)
            except Exception as exc:  # a defect in a rule, a value the database refuses: this match only
                _fail(conn, report, f"match {fixture_id}", exc)
        if commit:
            conn.commit()
        if progress is not None:
            progress(report)
        if report.stopped is not None:
            break
    report.seconds = time.monotonic() - started
    return report


def refresh_pending(conn: psycopg.Connection[Any], *, now: datetime, days: int = DEFAULT_DAYS, max_seconds: float | None = None,
                    limit: int | None = None, apply: bool = True, commit: bool = True, tracked: bool = True,
                    progress: Callable[[BuildReport], None] | None = None) -> BuildReport:
    """One pass of the worker's job: the finished matches settled in the last ``days`` days, newest first, those that are due built."""
    queue = candidates(conn, now=now, days=days, tracked=tracked)
    if commit:
        conn.commit()
    return build_many(conn, queue, apply=apply, max_seconds=max_seconds, limit=limit, commit=commit, progress=progress)


# ── what is stored, checked from the outside ─────────────────────────────────────────────────────────────────────────────

COVERAGE_SQL: Final = """
SELECT count(*) AS finished, count(m.id) AS built,
       count(*) FILTER (WHERE m.completeness = 'complete') AS complete,
       count(*) FILTER (WHERE m.completeness = 'partial') AS partial,
       count(*) FILTER (WHERE m.completeness = 'minimal') AS minimal
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN LATERAL (SELECT x.id, x.completeness FROM intel.match_knowledge x
                      WHERE x.fixture_id = f.id AND x.version = %(version)s ORDER BY x.id DESC LIMIT 1) m ON true
 WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND (NOT %(tracked)s OR c.is_tracked)
"""
KINDS_COVERAGE_SQL: Final = """
WITH lines AS (
    SELECT e.fixture_id, count(*) AS n FROM core.fixture_events e JOIN core.fixtures f ON f.id = e.fixture_id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
     WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND (NOT %(tracked)s OR c.is_tracked)
     GROUP BY e.fixture_id
), kinds AS (
    SELECT k.fixture_id, count(*) AS n, count(*) FILTER (WHERE k.rules_version <> %(rules)s) AS old_rules
      FROM core.fixture_event_kinds k WHERE k.fixture_id IN (SELECT fixture_id FROM lines) GROUP BY k.fixture_id
)
SELECT count(*) AS with_events, count(*) FILTER (WHERE k.fixture_id IS NOT NULL AND k.n = l.n AND k.old_rules = 0) AS read,
       count(*) FILTER (WHERE k.fixture_id IS NULL) AS unread,
       count(*) FILTER (WHERE k.fixture_id IS NOT NULL AND (k.n <> l.n OR k.old_rules > 0)) AS stale
  FROM lines l LEFT JOIN kinds k ON k.fixture_id = l.fixture_id
"""


def coverage(conn: psycopg.Connection[Any], *, now: datetime, days: int = 400, version: str = layers.VERSION,
             tracked: bool = True) -> dict[str, Any]:
    """How many of the finished matches that kicked off in the last ``days`` days (and are settled) have a build, how complete the builds
    are, and how many matches with events have the lines of those events read (``stale``: the number of lines is not the match's, or
    they were read by older rules). Of the competitions PrediGol follows unless ``tracked`` is off."""
    window = {"since": now - timedelta(days=days), "until": now - SETTLE, "tracked": tracked}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COVERAGE_SQL, {**window, "version": version})
        got = {k: int(v) for k, v in (cur.fetchone() or {}).items()}
        cur.execute(KINDS_COVERAGE_SQL, {**window, "rules": ev.VERSION})
        kinds = {k: int(v) for k, v in (cur.fetchone() or {}).items()}
    share = round(100 * got["built"] / got["finished"], 2) if got["finished"] else 0.0
    return {"days": days, "version": version, "tracked": tracked, **got, "share": share, "events": kinds}
