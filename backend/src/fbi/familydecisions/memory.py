"""WHAT THE FAMILIES REMEMBER (plan F11) - ``memory-fam-v1``: the post-mortems of their decisions added up, by family, by market, by competition and by
referee. The fourth and last step of the cycle of a family in shadow (decision, settlement, post-mortem, memory).

A post-mortem says what became of ONE decision; one result changes nothing. The memory is where the results become a record: how many decisions a
family has taken, how many it won against what it said it would win, what the price was worth against the close, what the stakes at flat units made,
and how the verdicts split between luck and decision (``intel.family_memory``, append-only, ``intel.family_memory_latest`` its newest snapshot).

WHAT IT SUMS. The post-mortems of ``pm-fam-v1`` (``intel.family_postmortems``) and nothing else: no decision, no forecast, no price is read again. For
each entity, over everything it has (``all``) and over the matches of the last 28 days (``recent``):

    n, decided, wins    decisions studied; of them, those won or lost outright (a push, a void, a half result has no hit to count)
    hit, claimed, gap   the share won against the share the family SAID it would win (the mean of its stated probabilities over the same decisions,
                        NOT calibrated: the families have no champion calibrator), and the difference. ``z`` is that difference in standard errors
                        of a coin that lands with the probabilities the family stated: -2 or less is a family that claimed far more than it got
    clv_n, clv_mean     the closing-line value (``clv-v1``) over the decisions that had a close; and how the prices split GOOD, NEUTRAL, BAD, UNKNOWN
    staked, profit, roi what one unit on each decision made (a push or a void stakes nothing), and what it made per unit staked
    verdicts, results   how many of each (MERECIDO, VARIANZA, SUERTE, ERROR, NULO, SIN_DATOS; win, loss, push, void, half_win, half_loss), every word
                        always there, a zero when there are none

``delta`` is the recent record minus the one over everything - hit, claimed, gap, clv_mean, roi - where both exist: the first sign that a family is
changing. A family also carries the same record by model (``models``): one family may run more than one.

THE ENTITIES, and how many post-mortems each needs to exist: a family (1), a market (1), a competition (3) and a referee (3). A competition or a
referee with one or two decisions is an anecdote and would only add noise to a console. A decision whose match has no competition or no referee the
identity layer placed counts for the family and the market and for no one else.

CONFIDENCE, 0 to 1: ``n_eff / (n_eff + 30)``, where ``n_eff`` is the sum over the decisions of ``0.5 ** (age / 60 days)``: a decision loses half its
weight every 60 days, so a family with a hundred decisions from a year ago is not as certain as one with thirty from last month. The 28 days, the 60
and the 30 are conventions of the memory, not parameters of any model, and they are written in the row; changing one is ``memory-fam-v2``.

WHEN IT WRITES. The nightly job. The snapshot of an entity is written only when the entity has post-mortems the newest earlier snapshot did not rest
on (their number or the newest one differs): a night with nothing new writes nothing, and the view keeps showing the last snapshot with the day it is
as of. At most one snapshot of an entity per Bogotá day (a second pass of the same day finds it written and waits for the next: the post-mortems
written after the pass of a day are in the snapshot of the following one, never in the one of the day). A rule that changes is a new version: the rows
of this one stay as they were written. Reads only the post-mortems and the names of competitions and referees. Zero requests to the provider, zero AI.

WHERE IT STOPS. What the families remember is the future of the matches it describes and it is derived: no forecast, decision, packet or pick reads it
(``tests/unit/test_postmortem_isolation.py``), and it is not the memory of the pipeline (``fbi.intel.memory``, ``intel.entity_memory``): that one is
read by the report of the day, the patterns and the lessons the AI is handed, and a research layer with forecasts that are not calibrated must not
move its sample sizes. It feeds a console and the owner's decisions.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.core.decision_versions import MEMORY_FAMILIES
from fbi.familydecisions import decide as fd
from fbi.familydecisions import postmortem as pm

log = structlog.get_logger(__name__)

VERSION: Final = MEMORY_FAMILIES
"""The version of the memory of the families: the ``version`` of its rows in ``intel.family_memory``."""
SOURCE: Final = pm.VERSION
"""The version of the post-mortems it adds up."""

RECENT_DAYS: Final = 28
"""The matches of the last this-many days are the recent record."""
HALF_LIFE_DAYS: Final = 60.0
"""A decision loses half its weight in the confidence every this-many days."""
PRIOR: Final = 30.0
"""The effective sample that makes a confidence of one half: ``n_eff / (n_eff + PRIOR)``."""
SAMPLE: Final = 5
"""How many of the newest post-mortems an entity names as the evidence it rests on."""
ERRORS_KEPT: Final = 5

ENTITY_TYPES: Final = ("family", "market", "competition", "referee")
NEEDS: Final[Mapping[str, int]] = {"family": 1, "market": 1, "competition": 3, "referee": 3}
"""The post-mortems an entity needs before it is remembered."""
RESULTS: Final = ("win", "loss", "push", "void", "half_win", "half_loss")
QUALITIES: Final = ("GOOD", "NEUTRAL", "BAD", "UNKNOWN")
VERDICTS: Final = ("MERECIDO", "VARIANZA", "SUERTE", "ERROR", "NULO", "SIN_DATOS")
NO_STAKE: Final = frozenset({"push", "void"})
"""The results that give the stake back: nothing was risked, so they are not in the denominator of the return."""
DECIDED: Final = frozenset({"win", "loss"})

ROWS_SQL: Final = """
SELECT p.id, p.decision_id, p.created_at, p.kickoff_at, p.family, p.model_name, p.market_key, p.competition_id, p.referee_id,
       p.result, p.quality, p.verdict, p.p_model, p.clv, p.profit_flat
  FROM intel.family_postmortems p
 WHERE p.version = %(source)s AND p.created_at <= %(at)s
 ORDER BY p.id
"""
"""The post-mortems the memory of a moment rests on: those written by then."""

COMPETITIONS_SQL: Final = "SELECT id, name FROM core.competitions WHERE id = ANY(%(ids)s)"
REFEREES_SQL: Final = "SELECT id, name FROM core.referees WHERE id = ANY(%(ids)s)"

PREVIOUS_SQL: Final = """
SELECT DISTINCT ON (entity_type, entity_key) entity_type, entity_key, as_of_day,
       (evidence_ref ->> 'postmortems')::int AS postmortems, (evidence_ref -> 'through' ->> 'id')::bigint AS through_id
  FROM intel.family_memory
 WHERE version = %(version)s
 ORDER BY entity_type, entity_key, as_of_day DESC, id DESC
"""
"""The newest snapshot of each entity under this version, and what it rests on."""

INSERT_SQL: Final = (
    "INSERT INTO intel.family_memory (version, as_of_day, built_at, entity_type, entity_key, entity_name, stats, delta, confidence, evidence_ref) "
    "VALUES (%(version)s, %(as_of)s, %(at)s, %(type)s, %(key)s, %(name)s, %(stats)s, %(delta)s, %(confidence)s, %(evidence)s) "
    "ON CONFLICT (version, as_of_day, entity_type, entity_key) DO NOTHING")


@dataclass(frozen=True, slots=True)
class Row:
    """A post-mortem, as the memory reads it."""

    id: int
    decision_id: int
    created_at: datetime
    kickoff_at: datetime
    family: str
    model: str
    key: str
    competition_id: int | None
    referee_id: int | None
    result: str
    quality: str
    verdict: str
    p_model: float
    clv: float | None
    profit: Decimal


@dataclass(frozen=True, slots=True)
class Entity:
    """The snapshot of one family, market, competition or referee."""

    type: str
    key: str
    name: str | None
    stats: dict[str, Any]
    delta: dict[str, float]
    confidence: float
    evidence: dict[str, Any]

    @property
    def n(self) -> int:
        return int(self.evidence["postmortems"])

    @property
    def through(self) -> int:
        return int(self.evidence["through"]["id"])


@dataclass(frozen=True, slots=True)
class Previous:
    """What the newest earlier snapshot of an entity rests on."""

    as_of: date
    postmortems: int
    through: int


def row_from(r: Mapping[str, Any]) -> Row:
    return Row(
        int(r["id"]), int(r["decision_id"]), r["created_at"], r["kickoff_at"], str(r["family"]), str(r["model_name"]), str(r["market_key"]),
        None if r["competition_id"] is None else int(r["competition_id"]), None if r["referee_id"] is None else int(r["referee_id"]),
        str(r["result"]), str(r["quality"]), str(r["verdict"]), float(r["p_model"]), None if r["clv"] is None else float(r["clv"]),
        Decimal(r["profit_flat"]))


# ── what it says (pure) ──────────────────────────────────────────────────────────────────────────────────────────────

def rounded(value: float | None, places: int) -> float | None:
    return None if value is None else round(value, places)


def record(rows: Sequence[Row]) -> dict[str, Any]:
    """The record of a set of post-mortems. Pure; every key is always there (a zero or ``None``), so a reader never has to ask whether it is."""
    results = Counter(r.result for r in rows)
    decided = [r for r in rows if r.result in DECIDED]
    wins = results["win"]
    claimed = sum(r.p_model for r in decided) / len(decided) if decided else None
    hit = wins / len(decided) if decided else None
    variance = sum(r.p_model * (1 - r.p_model) for r in decided)
    z = (wins - sum(r.p_model for r in decided)) / math.sqrt(variance) if variance > 0 else None
    closes = [r.clv for r in rows if r.clv is not None]
    staked = sum(1 for r in rows if r.result not in NO_STAKE)
    profit = sum((r.profit for r in rows), Decimal(0))
    qualities = Counter(r.quality for r in rows)
    verdicts = Counter(r.verdict for r in rows)
    return {
        "n": len(rows), "decided": len(decided), "wins": wins, "hit": rounded(hit, 4), "claimed": rounded(claimed, 4),
        "gap": rounded(None if hit is None or claimed is None else hit - claimed, 4), "z": rounded(z, 3),
        "clv_n": len(closes), "clv_mean": rounded(sum(closes) / len(closes) if closes else None, 6),
        "quality": {q: qualities[q] for q in QUALITIES},
        "staked": staked, "profit": round(float(profit), 4), "roi": rounded(float(profit) / staked if staked else None, 4),
        "verdicts": {v: verdicts[v] for v in VERDICTS}, "results": {x: results[x] for x in RESULTS},
    }


def age_in_days(row: Row, as_of: date) -> int:
    """How many Bogotá days before the day the snapshot is as of the match was played (never negative)."""
    return max((as_of - local_day(row.kickoff_at)).days, 0)


def effective_sample(rows: Sequence[Row], as_of: date) -> float:
    """The decisions counted once each and discounted by age: half the weight after ``HALF_LIFE_DAYS``."""
    return float(sum(math.pow(0.5, age_in_days(r, as_of) / HALF_LIFE_DAYS) for r in rows))


def confidence_of(n_eff: float) -> float:
    return n_eff / (n_eff + PRIOR)


CHANGED: Final = ("hit", "claimed", "gap", "clv_mean", "roi")


def delta_of(everything: Mapping[str, Any], recent: Mapping[str, Any]) -> dict[str, float]:
    """The recent record minus the one over everything, for what both have. Nothing while nothing is recent."""
    if not recent["n"]:
        return {}
    return {k: round(float(recent[k]) - float(everything[k]), 6 if k == "clv_mean" else 4)
            for k in CHANGED if recent[k] is not None and everything[k] is not None}


def evidence_of(rows: Sequence[Row], n_eff: float) -> dict[str, Any]:
    """What a snapshot rests on: how many post-mortems, the newest one (the id is how a later pass tells there is something new), the span of the
    matches and the newest few."""
    newest = max(rows, key=lambda r: r.id)
    return {
        "source_version": SOURCE, "postmortems": len(rows), "through": {"id": newest.id, "created_at": newest.created_at.isoformat()},
        "from_kickoff": min(r.kickoff_at for r in rows).isoformat(), "to_kickoff": max(r.kickoff_at for r in rows).isoformat(),
        "sample": [{"postmortem": r.id, "decision": r.decision_id} for r in sorted(rows, key=lambda r: -r.id)[:SAMPLE]],
        "n_eff": round(n_eff, 2), "half_life_days": HALF_LIFE_DAYS, "prior": PRIOR,
    }


def snapshot(kind: str, key: str, name: str | None, rows: Sequence[Row], as_of: date) -> Entity:
    """What is remembered of an entity as of a day, from every post-mortem it has."""
    everything = record(rows)
    recent_rows = [r for r in rows if age_in_days(r, as_of) < RECENT_DAYS]
    recent = record(recent_rows)
    stats: dict[str, Any] = {"all": everything, "recent": recent, "recent_days": RECENT_DAYS}
    if kind == "family":
        by_model: dict[str, list[Row]] = defaultdict(list)
        for r in rows:
            by_model[r.model].append(r)
        stats["models"] = {m: record(by_model[m]) for m in sorted(by_model)}
    n_eff = effective_sample(rows, as_of)
    return Entity(kind, key, name, stats, delta_of(everything, recent), round(confidence_of(n_eff), 4), evidence_of(rows, n_eff))


def entities_of(r: Row) -> list[tuple[str, str]]:
    """The entities a post-mortem belongs to: its family and its market, and its competition and its referee when the match has them."""
    found = [("family", r.family), ("market", r.key)]
    if r.competition_id is not None:
        found.append(("competition", str(r.competition_id)))
    if r.referee_id is not None:
        found.append(("referee", str(r.referee_id)))
    return found


def summarise(rows: Sequence[Row], *, as_of: date, names: Mapping[tuple[str, str], str] | None = None) -> list[Entity]:
    """Everything the post-mortems say, by entity: the families, the markets, and the competitions and the referees that have enough. Pure; the order
    of the rows does not matter, and the entities come out in a fixed order."""
    grouped: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in rows:
        for entity in entities_of(r):
            grouped[entity].append(r)
    called = dict(names or {})
    called.update({("family", f): pm.FAMILY_ES.get(f, f) for kind, f in grouped if kind == "family"})
    order = {kind: i for i, kind in enumerate(ENTITY_TYPES)}
    return [snapshot(kind, key, called.get((kind, key)), grouped[kind, key], as_of)
            for kind, key in sorted(grouped, key=lambda e: (order[e[0]], e[1])) if len(grouped[kind, key]) >= NEEDS[kind]]


def is_new(entity: Entity, previous: Previous | None) -> bool:
    """Does the entity rest on post-mortems its newest earlier snapshot did not? A night with nothing new writes nothing."""
    return previous is None or previous.postmortems != entity.n or previous.through != entity.through


# ── what is read and written ─────────────────────────────────────────────────────────────────────────────────────────

def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def load_rows(conn: psycopg.Connection[Any], *, at: datetime) -> list[Row]:
    """Every post-mortem of ``pm-fam-v1`` written by ``at``."""
    return [row_from(r) for r in _rows(conn, ROWS_SQL, {"source": SOURCE, "at": at})]


def load_names(conn: psycopg.Connection[Any], rows: Sequence[Row]) -> dict[tuple[str, str], str]:
    """The names of the competitions and the referees the post-mortems mention."""
    found: dict[tuple[str, str], str] = {}
    for kind, sql, ids in (("competition", COMPETITIONS_SQL, {r.competition_id for r in rows}), ("referee", REFEREES_SQL, {r.referee_id for r in rows})):
        wanted = sorted(i for i in ids if i is not None)
        if wanted:
            found.update({(kind, str(r["id"])): str(r["name"]) for r in _rows(conn, sql, {"ids": wanted}) if r["name"]})
    return found


def load_previous(conn: psycopg.Connection[Any]) -> dict[tuple[str, str], Previous]:
    return {(str(r["entity_type"]), str(r["entity_key"])): Previous(r["as_of_day"], int(r["postmortems"] or 0), int(r["through_id"] or 0))
            for r in _rows(conn, PREVIOUS_SQL, {"version": VERSION})}


def _insert(conn: psycopg.Connection[Any], e: Entity, *, as_of: date, at: datetime) -> bool:
    params = {"version": VERSION, "as_of": as_of, "at": at, "type": e.type, "key": e.key, "name": e.name, "stats": Jsonb(e.stats),
              "delta": Jsonb(e.delta), "confidence": Decimal(str(e.confidence)), "evidence": Jsonb(e.evidence)}
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, params)
        return cur.rowcount > 0


# ── a pass ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class MemoryReport:
    postmortems: int = 0
    """The post-mortems the memory rests on."""
    entities: int = 0
    """The entities that have enough of them to be remembered."""
    written: int = 0
    unchanged: int = 0
    """Entities with nothing new since their newest snapshot: nothing written."""
    waiting: int = 0
    """Entities with something new whose snapshot of the day is already written: it goes in the next day's."""
    failed: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"postmortems": self.postmortems, "entities": self.entities, "written": self.written, "unchanged": self.unchanged,
                "waiting": self.waiting, "failed": self.failed, "by_type": self.by_type, "errors": self.errors[:ERRORS_KEPT]}


def remember(conn: psycopg.Connection[Any], *, at: datetime, write: bool = True) -> MemoryReport:
    """Write the snapshot, as of the Bogotá day of ``at``, of every entity that has post-mortems its newest earlier snapshot did not rest on.
    Idempotent within a day; commits nothing itself. An entity the database refuses costs only itself. With ``write=False`` it reads and builds and
    writes nothing."""
    report = MemoryReport()
    rows = load_rows(conn, at=at)
    report.postmortems = len(rows)
    if not rows:
        return report
    as_of = local_day(at)
    entities = summarise(rows, as_of=as_of, names=load_names(conn, rows))
    report.entities = len(entities)
    previous = load_previous(conn)
    for e in entities:
        if not is_new(e, previous.get((e.type, e.key))):
            report.unchanged += 1
            continue
        if write:
            try:
                with conn.transaction():  # a savepoint: a row the database refuses costs that row, not the rest of the pass
                    wrote = _insert(conn, e, as_of=as_of, at=at)
            except Exception as exc:
                report.failed += 1
                report.errors.append(f"{e.type}/{e.key}: {type(exc).__name__}: {exc}"[:300])
                log.error("family_memory.entity_failed", entity=f"{e.type}/{e.key}", error=type(exc).__name__, detail=str(exc)[:300])
                continue
            if not wrote:
                report.waiting += 1
                continue
        report.written += 1
        report.by_type[e.type] = report.by_type.get(e.type, 0) + 1
    return report


def run_step(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Any]:
    """The step of the nightly job: nothing while the switch of the families' decisions is ``off``; in ``shadow`` the snapshots of what the post-mortems
    added up to. A step of its own in the job (``fbi.intel.cycle.run_nightly``): if it raises, the job writes it in its record and the others still
    run."""
    chosen = fd.mode()
    if chosen == "off":
        return {"mode": chosen}
    return {"mode": chosen, **remember(conn, at=at).as_dict()}
