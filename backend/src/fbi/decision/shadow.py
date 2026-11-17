"""decision-v2 in a continuous, kept shadow (IA-093, plan piece AD-D01): it decides by itself and every decision is a row.

WHY. decision-v2 (``engine``) decided only when a person ran its replay (``replay``), and kept nothing: no decision of it could be
followed to kick-off, measured against the close or carried by the cycle of states. This pass makes it decide on its own, at fixed
moments, and keeps each decision with what it was made from - in tables of its own (revision 0150), never in ``intel.decisions``.

WHEN IT DECIDES (``TRIGGERS``), for the tracked matches (``core.competitions.is_tracked``):

    E1       once per match, between 24 and 12 hours before kick-off (the first evaluation of AD-D06);
    E4       once per match, at the last moment the engine still judges: between ``E4_FROM`` (20 min) and decision-v1's floor of
             ``decision.MIN_MINUTES`` (10 min) before kick-off. The plan's E4 is at T-5, but under 10 minutes the data stage - decision-v1's
             threshold, imported and never lowered - rejects every selection («menos de 10 min al saque»): a row at T-5 would say only that;
    mirror   at every moment decision-v1 decided (``intel.decisions`` of ``decision-v1``, the checkpoints T-36h ... T-15m and ``lineups``),
             as of that same moment and with that moment's rows as the replay reads them: the evidence that the kept shadow covers every
             candidate of decision-v1 (AD-D01's criterion: 99 %) and is the replay (0 differences).

HOW IT DECIDES: with ``replay.decide_at`` - the replay's own function, so a kept decision IS the replay's decision of its moment - under
``CONFIG``: the ruleset ``decision-v2.1`` (the odds book's price in force with its age by horizon, 195/75/45 min, AD-B06), the common
probability view ``forecast-v2`` (the single figure of every goals market, AD-B05) and the core's candidates. The book is read from the
RAW store as of the moment (``book_price``); the book's last price before kick-off (``engine.Close``) is NOT kept - it did not exist at
the moment of the decision.

WHAT IT KEEPS, per match and moment (``intel.decision_v2_moments``): the trigger, the configuration, the counts, the typed evidence of the
match it could cite (``ai.evidence`` as of the moment: kind, claim type, status, level and dates; research v2's claims only when
``typed_visible`` says they are part of what the system reads) and the fingerprint of the world it read. Per decision
(``intel.decisions_v2``): the state, reason and codes, the number judged (source, version, seal), the price with its source, age and
state, the inputs with their time - none later than the moment (``leaks``: such a decision is not written, and the database refuses it
too) -, the evidence the context stage read (ids, counts, the review), every stage, and the previous decision written of the same
selection under the same configuration (``previous_id``).

THE CYCLE. After writing, the decisions old enough that no earlier moment can still arrive (``LINK_LAG``) are handed to the cycle of
states through its own API (``fbi.lifecycle.store.extend``), under the writer ``decision-v2-shadow-v1``: this module never writes
``intel.selection_lifecycle`` itself.

SHADOW: nothing that decides, stakes, publishes or serves a reader imports this package (``tests/unit/test_decision_v2_isolation.py``);
``decision-v1`` and ``FBI_PICKS_SOURCE`` are untouched. Off by default: the worker schedules the pass only while ``FBI_DECISION_V2`` is
``shadow`` (``fbi.shadowjobs.decision_v2``). Two passes cannot write at once (an advisory lock); the same database gives the same rows.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.gates import typed_visible
from fbi.core.decision_versions import DECISION_CORE
from fbi.decision import book_price, engine, replay
from fbi.decision import view as common_view
from fbi.decision.families import CORE, Candidate, MarketFamily
from fbi.intel import decision
from fbi.lifecycle import derive
from fbi.lifecycle import store as lifecycle
from fbi.people.availability import press_basis
from fbi.storage.payload_store import PayloadStore

WRITER: Final = "decision-v2-shadow-v1"
"""The version of this writer (``intel.decision_v2_moments.writer_version``) and the writer of its chains in the cycle."""
LAYER: Final = "decision-v2"
SOURCE: Final = "intel.decisions_v2"
TRIGGERS: Final = ("E1", "E4", "mirror")
E1_FROM: Final = timedelta(hours=24)
E1_UNTIL: Final = timedelta(hours=12)
E4_FROM: Final = timedelta(minutes=20)
E4_UNTIL: Final = timedelta(minutes=decision.MIN_MINUTES)
"""E4 is kept before decision-v1's floor (``decision.MIN_MINUTES``): the engine imports that threshold and never lowers it."""
MIRROR_BACK: Final = timedelta(hours=6)
"""How far back a moment of decision-v1 is still mirrored (the pipeline writes its rows at the end of its run: 579 s at the median)."""
LINK_LAG: Final = timedelta(minutes=30)
"""A decision is handed to the cycle only once no earlier moment can still arrive (a moment of decision-v1 is written when its run
ends): otherwise a mirrored moment written late would land in the middle of a chain already stored, which the cycle refuses."""
LINK_BACK: Final = timedelta(days=2)
"""How long after kick-off a match's chain is still extended (to close it: in play or discarded)."""
MAX_MOMENTS: Final = 24
"""Moments of decision-v1 mirrored in one pass, oldest first (the rest in the next)."""
MAX_FIXTURES: Final = 60
"""Matches decided at E1 or E4 in one pass, nearest kick-off first."""
EVIDENCE_PER_FIXTURE: Final = 200
LOCK: Final = 0x1A093
TIMEOUT_MS: Final = 95_000


@dataclass(frozen=True, slots=True)
class Config:
    """What the shadow decides under. One configuration today; a new one is a new key, never a rewrite."""

    rules: str = engine.RULES_V21
    price: str = engine.BOOK
    probability: str = engine.COMMON
    view_version: str = common_view.VERSIONS[1]
    families: tuple[str, ...] = (CORE.name,)

    @property
    def key(self) -> str:
        return "|".join((self.rules, self.price, self.probability, self.view_version, "+".join(self.families)))

    def as_json(self) -> dict[str, Any]:
        return {"rules": self.rules, "price": self.price, "probability": self.probability, "view_version": self.view_version,
                "families": list(self.families), "council": None, "signals": False, "close": "not kept"}


CONFIG: Final = Config()
FAMILIES_BY_NAME: Final[Mapping[str, MarketFamily]] = {CORE.name: CORE}
"""The families the shadow can decide (the core today: decision-v1's candidates; the families of F10 stay with their own layer)."""


# -- what is due (pure) ---------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Due:
    fixture_id: int
    kickoff_at: datetime


def evaluation_due(kickoff_at: datetime, now: datetime) -> str | None:
    """The evaluation a match is in the window of at ``now`` (``E1``, ``E4``), or None. Pure."""
    if kickoff_at - E1_FROM <= now <= kickoff_at - E1_UNTIL:
        return "E1"
    if kickoff_at - E4_FROM <= now < kickoff_at - E4_UNTIL:
        return "E4"
    return None


@dataclass(frozen=True, slots=True)
class Planned:
    """A group decided together: one moment, its matches, and for a mirror the rows decision-v1 wrote then."""

    trigger: str
    at: datetime
    fixtures: tuple[int, ...]
    kickoffs: Mapping[int, datetime]
    rows: tuple[Mapping[str, Any], ...] | None = None

    @property
    def evaluation(self) -> str | None:
        return None if self.trigger == "mirror" else self.trigger


def plan_evaluations(due: Sequence[Due], done: Mapping[tuple[int, str], int], *, now: datetime, triggers: Iterable[str],
                     limit: int = MAX_FIXTURES) -> list[Planned]:
    """E1 and E4 of the matches whose window holds ``now`` and that were not decided in it yet (``done``: (fixture, trigger) -> moments
    already kept), nearest kick-off first, at most ``limit`` matches. Pure."""
    wanted = set(triggers)
    by_trigger: dict[str, list[Due]] = defaultdict(list)
    for d in sorted(due, key=lambda x: (x.kickoff_at, x.fixture_id)):
        ev = evaluation_due(d.kickoff_at, now)
        if ev is not None and ev in wanted and not done.get((d.fixture_id, ev)):
            by_trigger[ev].append(d)
    out: list[Planned] = []
    left = limit
    for ev in ("E4", "E1"):  # the nearest evaluation first when the pass is short
        chosen = by_trigger.get(ev, [])[:left]
        left -= len(chosen)
        if chosen:
            out.append(Planned(ev, now, tuple(d.fixture_id for d in chosen), {d.fixture_id: d.kickoff_at for d in chosen}))
    return out


def plan_mirrors(rows: Sequence[Mapping[str, Any]], mirrored: set[tuple[int, datetime]], *, limit: int = MAX_MOMENTS) -> list[Planned]:
    """One group per moment decision-v1 decided at (oldest first), with the matches of that moment not mirrored yet. Pure."""
    by_moment: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("checkpoint") == replay.SELECTION or r["known_at"] >= r["kickoff_at"]:
            continue
        if (int(r["fixture_id"]), r["known_at"]) in mirrored:
            continue
        by_moment[r["known_at"]].append(r)
    out: list[Planned] = []
    for at in sorted(by_moment)[:limit]:
        items = by_moment[at]
        fixtures = tuple(sorted({int(r["fixture_id"]) for r in items}))
        out.append(Planned("mirror", at, fixtures, {int(r["fixture_id"]): r["kickoff_at"] for r in items}, tuple(items)))
    return out


# -- what a decision keeps (pure) -----------------------------------------------------------------------------------------------------

def _iso(x: Any) -> Any:
    return x.isoformat() if isinstance(x, datetime) else x


def _plain(x: Any) -> Any:
    """JSON-ready, deterministic."""
    if isinstance(x, datetime):
        return x.isoformat()
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, Mapping):
        return {str(k): _plain(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, (list, tuple, set, frozenset)):
        items = [_plain(v) for v in x]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True)) if isinstance(x, (set, frozenset)) else items
    return x


def sha256(doc: Any) -> str:
    return hashlib.sha256(json.dumps(_plain(doc), sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def primary_row(world: decision.World, c: Candidate) -> Mapping[str, Any]:
    """The model row the stages judge (``engine.assess``: the market's primary model, else the first by name)."""
    names = sorted(c.models)
    return c.models[world.cal.primary_model(c.key[1], names) or names[0]]


def inputs_of(d: engine.Decision2, row: Mapping[str, Any], ctx: decision.Context, *, at: datetime) -> dict[str, Any]:
    """Every input of a decision with its time. Pure."""
    common = d.prediction.source == engine.COMMON
    cutoff = row.get("common_cutoff") if common else row.get("data_cutoff_ts")
    review = ctx.review
    return {"model": d.prediction.model, "model_version_id": d.prediction.model_version_id,
            "model_cutoff": _iso(cutoff), "probability": {"source": d.prediction.source, "version": d.prediction.version,
                                                           "seal": d.prediction.calibration, "basis": d.prediction.basis,
                                                           "missing": d.prediction.missing},
            "price": {"source": d.price.source, "at": _iso(d.price.price_at), "age_minutes": d.price.age_minutes,
                      "confirmed_by": d.price.confirmed_by, "provider_update_at": _iso(d.price.provider_update_at),
                      "state": d.price.state, "max_age_minutes": d.price.max_age_minutes, "band": d.price.band,
                      "rule": d.price.age_rule},
            "lineups_at": _iso(ctx.lineups_at), "review_at": None if review is None else _iso(review.get("reviewed_at")),
            "at": at.isoformat()}


def later_than(at: datetime, *times: Any) -> list[datetime]:
    """The inputs' times after ``at``: a decision must not have seen them. Pure."""
    return [t for t in times if isinstance(t, datetime) and t > at]


def evidence_of(ctx: decision.Context) -> dict[str, Any]:
    """What the context stage read of the evidence of a selection (decision-v1's own reading: ``decision.build_context``). Pure."""
    r = ctx.review
    return {"ids": list(ctx.evidence_ids), "counts": dict(sorted(ctx.evidence.items())), "status": ctx.status,
            "review": None if r is None else {"id": int(r["id"]), "decision": r.get("decision"), "engine_version": r.get("engine_version")},
            "signals": dict(sorted(ctx.rules_codes.items()))}


LEVEL_OF_PROVIDER: Final = "proveedor"
RUMOR: Final = "rumor"


def typed_item(r: Mapping[str, Any]) -> dict[str, Any]:
    """One item of evidence as the moment cites it: its type (kind, claim type, assertion), its subject, its status and level
    (``fbi.people.availability.press_basis``: oficial / dos_origenes / un_medio; ``proveedor``; ``rumor`` for what does not count) and
    its dates. Never its text. Pure."""
    level = LEVEL_OF_PROVIDER if r.get("origin") == "provider" else (press_basis(r.get("status"), r.get("source_tier")) or RUMOR)
    return {"id": int(r["id"]), "kind": r.get("kind"), "claim_type": r.get("claim_type"), "assertion": r.get("assertion"),
            "subject_type": r.get("subject_type"), "provider_player_id": r.get("provider_player_id"), "origin": r.get("origin"),
            "status": r.get("status"), "tier": r.get("source_tier"), "domain": r.get("source_domain"), "level": level,
            "published_at": _iso(r.get("published_at")), "retrieved_at": _iso(r.get("retrieved_at")),
            "typed": r.get("subject_type") is not None}


V1_WORDS: Final[Mapping[str, str]] = {"RECOMMENDED": "APROBADO", "CAUTION": "CAUTELA", "WATCH": "INVESTIGACION",
                                      "ABSTAIN": "INVESTIGACION", "REJECTED": "RECHAZADO"}
"""decision-v2's states in the words the cycle's map reads (``derive.map_decision``): state-v2 splits decision-v1's INVESTIGACION in two
(WATCH, ABSTAIN), so both go back to it; the reason codes are decision-v1's own and say the rest."""


# -- the reads ------------------------------------------------------------------------------------------------------------------------

DUE_SQL: Final = """
SELECT f.id, f.kickoff_at
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'scheduled'
   AND f.kickoff_at > %(at)s + %(floor)s AND f.kickoff_at <= %(at)s + %(ahead)s
 ORDER BY f.kickoff_at, f.id
"""
DONE_SQL: Final = """
SELECT fixture_id, trigger, count(*) AS n
  FROM intel.decision_v2_moments
 WHERE fixture_id = ANY(%(fixtures)s) AND config_key = %(config)s AND trigger IN ('E1', 'E4')
 GROUP BY 1, 2
"""
V1_MOMENTS_SQL: Final = """
SELECT d.id, d.decision_version, d.known_at, d.checkpoint, d.fixture_id, d.market_key, d.selection, d.line, d.model_name, d.state,
       d.reasons, d.context_status, d.kickoff_at
  FROM intel.decisions d
 WHERE d.decision_version = %(version)s AND d.known_at >= %(since)s AND d.known_at < %(until)s AND d.checkpoint <> 'selection'
 ORDER BY d.known_at, d.id
"""
"""decision-v1's rows of the last ``MIRROR_BACK``: the moments the mirror follows (only the core layer: its candidates are the shadow's)."""
MIRRORED_SQL: Final = """
SELECT fixture_id, known_at FROM intel.decision_v2_moments
 WHERE trigger = 'mirror' AND config_key = %(config)s AND known_at >= %(since)s
"""
EVIDENCE_SQL: Final = """
SELECT e.id, e.fixture_id, e.kind, e.claim_type, e.subject_type, e.provider_player_id, e.origin, e.status, e.source_tier,
       e.source_domain, e.published_at, e.retrieved_at, e.attributes->>'assertion' AS assertion
  FROM ai.evidence e
 WHERE e.fixture_id = ANY(%(fixtures)s) AND e.retrieved_at <= %(at)s AND (e.published_at IS NULL OR e.published_at <= %(at)s)
   AND e.status <> 'OUTDATED' AND (e.subject_type IS NULL OR %(typed)s)
 ORDER BY e.fixture_id, e.id
"""
"""The facts of the match as of the moment (nothing retrieved or published later); research v2's claims only when the system reads them."""
PREVIOUS_SQL: Final = """
SELECT DISTINCT ON (chain_key) chain_key, id FROM intel.decisions_v2
 WHERE fixture_id = ANY(%(fixtures)s) AND config_key = %(config)s
 ORDER BY chain_key, id DESC
"""
MOMENT_SQL: Final = """
INSERT INTO intel.decision_v2_moments (fixture_id, trigger, evaluation, evaluation_version, known_at, kickoff_at, mirrored_version,
    config_key, config, candidates, decided, evidence, world_hash, writer_version, code_version)
VALUES (%(fixture_id)s, %(trigger)s, %(evaluation)s, %(evaluation_version)s, %(known_at)s, %(kickoff_at)s, %(mirrored_version)s,
    %(config_key)s, %(config)s, %(candidates)s, %(decided)s, %(evidence)s, %(world_hash)s, %(writer_version)s, %(code_version)s)
ON CONFLICT ON CONSTRAINT decision_v2_moments_once DO NOTHING
RETURNING id
"""
DECISION_SQL: Final = """
INSERT INTO intel.decisions_v2 (moment_id, previous_id, chain_key, fixture_id, family, market_key, selection, line, model_hint, model,
    known_at, kickoff_at, trigger, evaluation, evaluation_version, checkpoint, state, reason, codes, label, version, rules, config_key,
    probability_source, probability_version, p_model, p_cal, calibration, price_source, odds, p_market, price_at, price_age_minutes,
    price_state, model_cutoff, context_status, inputs, evidence, decision, input_hash, mirror_of)
VALUES (%(moment_id)s, %(previous_id)s, %(chain_key)s, %(fixture_id)s, %(family)s, %(market_key)s, %(selection)s, %(line)s,
    %(model_hint)s, %(model)s, %(known_at)s, %(kickoff_at)s, %(trigger)s, %(evaluation)s, %(evaluation_version)s, %(checkpoint)s,
    %(state)s, %(reason)s, %(codes)s, %(label)s, %(version)s, %(rules)s, %(config_key)s, %(probability_source)s,
    %(probability_version)s, %(p_model)s, %(p_cal)s, %(calibration)s, %(price_source)s, %(odds)s, %(p_market)s, %(price_at)s,
    %(price_age_minutes)s, %(price_state)s, %(model_cutoff)s, %(context_status)s, %(inputs)s, %(evidence)s, %(decision)s,
    %(input_hash)s, %(mirror_of)s)
RETURNING id
"""
LINK_SQL: Final = """
SELECT d.id, d.fixture_id, d.market_key, d.selection, d.line, d.known_at, d.checkpoint, d.state, d.codes, d.context_status,
       d.kickoff_at, d.evaluation, d.evaluation_version
  FROM intel.decisions_v2 d
 WHERE d.config_key = %(config)s AND d.fixture_id = ANY(%(fixtures)s) AND d.known_at <= %(until)s
 ORDER BY d.known_at, d.id
"""
LINK_FIXTURES_SQL: Final = """
SELECT f.id, f.kickoff_at, f.status_short, f.status_group
  FROM core.fixtures f
 WHERE f.id IN (SELECT m.fixture_id FROM intel.decision_v2_moments m
                 WHERE m.config_key = %(config)s AND m.kickoff_at >= %(start)s AND m.kickoff_at < %(end)s)
"""


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _tables_exist(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute("SELECT to_regclass('intel.decisions_v2') IS NOT NULL AND to_regclass('intel.decision_v2_moments') IS NOT NULL"
                       ).fetchone()
    return bool(row and row[0])


# -- the pass -------------------------------------------------------------------------------------------------------------------------

@dataclass
class PassReport:
    planned: Counter[str] = field(default_factory=Counter)
    """Groups decided, by trigger."""
    moments: Counter[str] = field(default_factory=Counter)
    """Match-moments kept, by trigger."""
    already: int = 0
    """Match-moments another pass had kept (the unique key): nothing written for them."""
    candidates: int = 0
    decisions: int = 0
    by_state: Counter[str] = field(default_factory=Counter)
    mirror_rows: int = 0
    """decision-v1's rows of the mirrored moments."""
    mirror_matched: int = 0
    """Of those, the ones with a decision of decision-v2 of the same selection at the same moment."""
    leaks: int = 0
    """Decisions not written because an input was later than the moment."""
    lifecycle: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"planned": dict(sorted(self.planned.items())), "moments": dict(sorted(self.moments.items())), "already": self.already,
                "candidates": self.candidates, "decisions": self.decisions, "by_state": dict(sorted(self.by_state.items())),
                "mirror": {"rows": self.mirror_rows, "matched": self.mirror_matched,
                           "rate": None if not self.mirror_rows else round(self.mirror_matched / self.mirror_rows, 4)},
                "leaks": self.leaks, "lifecycle": self.lifecycle, "errors": self.errors[:20]}


def chain_key(config: Config, d: engine.Decision2) -> str:
    return "|".join((config.key, d.family, str(d.key[0]), d.key[1], d.key[2], str(d.key[3]), d.model_hint or ""))


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, store: PayloadStore | None, triggers: Iterable[str] = TRIGGERS,
             config: Config = CONFIG, code_version: str | None = None, dry_run: bool = False, link: bool = True,
             commit: bool = True) -> PassReport:
    """One pass: plan the moments due, decide each group with the replay's function, keep every decision, extend the chains. Each group
    is its own transaction (``commit``; without it, a savepoint inside the caller's transaction): a group that fails is rolled back,
    counted and the pass goes on. ``dry_run`` decides and writes nothing."""
    rep = PassReport()
    wanted = [t for t in triggers if t in TRIGGERS]
    have_tables = _tables_exist(conn)
    if not have_tables and not dry_run:
        raise RuntimeError("intel.decisions_v2 does not exist: apply revision 0150 first")
    if config.price == engine.BOOK and store is None:
        raise ValueError("the book's price is read from the RAW store: give the store")

    def end() -> None:
        if commit:
            conn.commit()

    if not dry_run:
        got = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
        if not got or not got[0]:
            rep.errors.append("another pass holds the lock")
            end()
            return rep
    try:
        if commit:
            conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        groups = _plan(conn, now=now, triggers=wanted, config=config, have_tables=have_tables)
        fixtures = sorted({f for g in groups for f in g.fixtures})
        book = book_price.read(conn, store, fixtures) if config.price == engine.BOOK and fixtures else None
        typed = typed_visible(conn)
        previous = {str(r["chain_key"]): int(r["id"]) for r in _fetch(conn, PREVIOUS_SQL, {"fixtures": fixtures, "config": config.key})
                    } if fixtures and have_tables else {}
        end()
        for g in groups:
            kept = dict(previous)
            try:
                with conn.transaction():
                    _decide_group(conn, g, book=book, typed=typed, previous=kept, config=config, code_version=code_version,
                                  dry_run=dry_run, rep=rep)
                previous.update(kept)
            except (psycopg.Error, ValueError, KeyError) as exc:
                rep.errors.append(f"{g.trigger}@{g.at.isoformat()}: {type(exc).__name__}: {exc}"[:300])
        if link and not dry_run:
            try:
                with conn.transaction():
                    rep.lifecycle = link_lifecycle(conn, now=now, config=config).as_json()
            except psycopg.Error as exc:
                rep.errors.append(f"lifecycle: {type(exc).__name__}: {exc}"[:300])
    finally:
        if not dry_run:
            if commit:
                conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
            end()
    return rep


def _plan(conn: psycopg.Connection[Any], *, now: datetime, triggers: Sequence[str], config: Config, have_tables: bool) -> list[Planned]:
    groups: list[Planned] = []
    if "mirror" in triggers and CORE.name in config.families:
        rows = _fetch(conn, V1_MOMENTS_SQL, {"version": DECISION_CORE, "since": now - MIRROR_BACK, "until": now})
        mirrored = ({(int(r["fixture_id"]), r["known_at"]) for r in _fetch(conn, MIRRORED_SQL, {"config": config.key,
                                                                                                  "since": now - MIRROR_BACK})}
                    if have_tables else set())
        groups += plan_mirrors(rows, mirrored)
    evaluations = [t for t in triggers if t != "mirror"]
    if evaluations:
        due = [Due(int(r["id"]), r["kickoff_at"]) for r in _fetch(conn, DUE_SQL, {"at": now, "floor": E4_UNTIL, "ahead": E1_FROM})]
        done: dict[tuple[int, str], int] = {}
        if due and have_tables:
            done = {(int(r["fixture_id"]), str(r["trigger"])): int(r["n"])
                    for r in _fetch(conn, DONE_SQL, {"fixtures": [d.fixture_id for d in due], "config": config.key})}
        groups += plan_evaluations(due, done, now=now, triggers=evaluations)
    return groups


def _decide_group(conn: psycopg.Connection[Any], g: Planned, *, book: book_price.BookReader | None, typed: bool, previous: dict[str, int],
                  config: Config, code_version: str | None, dry_run: bool, rep: PassReport) -> None:
    rep.planned[g.trigger] += 1
    fams = [FAMILIES_BY_NAME[n] for n in config.families]
    moment = replay.decide_at(conn, at=g.at, families=fams, fixtures=list(g.fixtures), rows=g.rows, price=config.price,
                              rules=config.rules, probability=config.probability, view_version=config.view_version, book=book,
                              closes=None)
    world = moment.world
    cands = {c.ident: c for c in moment.candidates}
    by_fixture: dict[int, list[engine.Decision2]] = defaultdict(list)
    for d in moment.decisions:
        by_fixture[d.key[0]].append(d)
    evidence: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in _fetch(conn, EVIDENCE_SQL, {"fixtures": list(g.fixtures), "at": g.at, "typed": typed}):
        if len(evidence[int(r["fixture_id"])]) < EVIDENCE_PER_FIXTURE:
            evidence[int(r["fixture_id"])].append(typed_item(r))
    v1_ids: dict[tuple[int, str, str, Decimal], int] = {}
    if g.rows is not None:
        for v1 in g.rows:
            v1_ids[replay.key_of(v1)] = int(v1["id"])
        rep.mirror_rows += len(g.rows)
        decided = {d.key for d in moment.decisions}
        rep.mirror_matched += sum(1 for v1 in g.rows if replay.key_of(v1) in decided)
    for fid in g.fixtures:
        mine = sorted(by_fixture.get(fid, []), key=lambda d: (d.family, d.key[1:], d.model_hint or ""))
        cited = evidence.get(fid, [])
        rows: list[dict[str, Any]] = []
        world_parts: list[Any] = [{"lineups_at": world.lineups.get(fid), "passes": world.passes.get(fid), "quality": world.quality.get(fid),
                                   "evidence": [e["id"] for e in cited]}]
        for d in mine:
            c = cands[d.ident]
            row = primary_row(world, c)
            ctx = decision.build_context(world, d.key, lineups_seen=d.key[0] in world.lineups)
            inputs = inputs_of(d, row, ctx, at=g.at)
            cutoff = row.get("common_cutoff") if d.prediction.source == engine.COMMON else row.get("data_cutoff_ts")
            late = later_than(g.at, cutoff, d.price.price_at, ctx.lineups_at, None if ctx.review is None else ctx.review.get("reviewed_at"))
            body = d.as_json()
            world_parts.append({"ident": [d.family, list(d.key), d.model_hint], "models": c.models})
            if late:
                rep.leaks += 1
                rep.errors.append(f"{d.key}: input after the moment {g.at.isoformat()}: {[t.isoformat() for t in late]}"[:300])
                continue
            rows.append({"family": d.family, "market_key": d.key[1], "selection": d.key[2], "line": d.key[3], "model_hint": d.model_hint,
                         "model": d.prediction.model, "checkpoint": d.checkpoint, "state": d.state, "reason": d.reason,
                         "codes": list(d.codes), "label": d.label, "version": d.version, "rules": d.rules,
                         "probability_source": d.prediction.source, "probability_version": d.prediction.version,
                         "p_model": round(d.prediction.p_model, 6), "p_cal": None if d.prediction.p_cal is None else round(d.prediction.p_cal, 6),
                         "calibration": d.prediction.calibration, "price_source": d.price.source,
                         "odds": None if d.price.odds is None else round(d.price.odds, 4),
                         "p_market": None if d.price.p_market is None else round(d.price.p_market, 6), "price_at": d.price.price_at,
                         "price_age_minutes": d.price.age_minutes, "price_state": d.price.state, "model_cutoff": cutoff,
                         "context_status": d.context_status, "inputs": inputs, "evidence": evidence_of(ctx), "decision": body,
                         "input_hash": sha256({"inputs": inputs, "decision": body}), "mirror_of": v1_ids.get(d.key),
                         "chain_key": chain_key(config, d)})
        rep.candidates += len(mine)
        if dry_run:
            rep.moments[g.trigger] += 1
            rep.decisions += len(rows)
            rep.by_state.update(r["state"] for r in rows)
            continue
        got = conn.execute(MOMENT_SQL, {
            "fixture_id": fid, "trigger": g.trigger, "evaluation": g.evaluation, "evaluation_version": None if g.evaluation is None else 1,
            "known_at": g.at, "kickoff_at": g.kickoffs[fid], "mirrored_version": DECISION_CORE if g.trigger == "mirror" else None,
            "config_key": config.key, "config": Jsonb(config.as_json()), "candidates": len(mine), "decided": len(rows),
            "evidence": Jsonb(cited), "world_hash": sha256({"at": g.at, "config": config.key, "fixture": fid, "world": world_parts}),
            "writer_version": WRITER, "code_version": code_version}).fetchone()
        if got is None:
            rep.already += 1
            continue
        rep.moments[g.trigger] += 1
        moment_id = int(got[0])
        for r in rows:
            out = conn.execute(DECISION_SQL, {
                **r, "moment_id": moment_id, "previous_id": previous.get(r["chain_key"]), "fixture_id": fid, "known_at": g.at,
                "kickoff_at": g.kickoffs[fid], "trigger": g.trigger, "evaluation": g.evaluation,
                "evaluation_version": None if g.evaluation is None else 1, "config_key": config.key, "inputs": Jsonb(_plain(r["inputs"])),
                "evidence": Jsonb(_plain(r["evidence"])), "decision": Jsonb(_plain(r["decision"]))}).fetchone()
            assert out is not None
            previous[r["chain_key"]] = int(out[0])
            rep.decisions += 1
            rep.by_state[r["state"]] += 1


# -- the cycle ------------------------------------------------------------------------------------------------------------------------

def histories_of(rows: Iterable[Mapping[str, Any]]) -> dict[derive.Key, derive.History]:
    """decision-v2's kept decisions as the cycle reads a layer (``derive.History``). Pure."""
    out: dict[derive.Key, derive.History] = {}
    for r in rows:
        k = derive.Key.of(r["fixture_id"], r["market_key"], r["selection"], r["line"])
        h = out.setdefault(k, derive.History(k))
        h.decisions.append(derive.Decision(int(r["id"]), LAYER, r["known_at"], str(r["checkpoint"]), V1_WORDS[str(r["state"])],
                                           tuple(str(c) for c in r["codes"] or ()), str(r["context_status"]), r["kickoff_at"],
                                           r.get("evaluation"), r.get("evaluation_version")))
    return out


def link_lifecycle(conn: psycopg.Connection[Any], *, now: datetime, config: Config = CONFIG, dry_run: bool = False) -> lifecycle.PassReport:
    """Hand the kept decisions of the matches of the last ``LINK_BACK`` and the next 48 h to the cycle of states (its API), those at least
    ``LINK_LAG`` old. The caller commits."""
    fixtures = {int(r["id"]): derive.Fixture(int(r["id"]), r["kickoff_at"], r["status_short"], r["status_group"])
                for r in _fetch(conn, LINK_FIXTURES_SQL, {"config": config.key, "start": now - LINK_BACK, "end": now + E1_FROM * 2})}
    if not fixtures:
        return lifecycle.PassReport()
    rows = _fetch(conn, LINK_SQL, {"config": config.key, "fixtures": sorted(fixtures), "until": now - LINK_LAG})
    return lifecycle.extend(conn, histories_of(rows), fixtures, now=now, writer=WRITER, source=SOURCE, dry_run=dry_run)


# -- the owner's checks (read-only) ---------------------------------------------------------------------------------------------------

STORED_SQL: Final = """
SELECT m.id AS moment_id, m.fixture_id, m.trigger, m.known_at, m.kickoff_at, d.family, d.market_key, d.selection, d.line, d.model_hint,
       d.state, d.reason, d.codes, d.label, d.checkpoint, d.mirror_of
  FROM intel.decision_v2_moments m LEFT JOIN intel.decisions_v2 d ON d.moment_id = m.id
 WHERE m.config_key = %(config)s AND m.known_at >= %(start)s AND m.known_at < %(end)s
 ORDER BY m.known_at, m.fixture_id, d.id
"""
V1_AT_SQL: Final = """
SELECT d.id, d.known_at, d.checkpoint, d.fixture_id, d.market_key, d.selection, d.line, d.model_name, d.context_status, d.kickoff_at
  FROM intel.decisions d
 WHERE d.decision_version = %(version)s AND d.fixture_id = %(fixture)s AND d.known_at = %(at)s AND d.checkpoint <> 'selection'
"""
COVERAGE_SQL: Final = """
SELECT d.id, d.known_at, d.fixture_id, d.market_key, d.selection, d.line
  FROM intel.decisions d
 WHERE d.decision_version = %(version)s AND d.known_at >= %(start)s AND d.known_at < %(end)s AND d.checkpoint <> 'selection'
"""


def verify(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, store: PayloadStore | None, config: Config = CONFIG,
           limit: int = 200) -> dict[str, Any]:
    """AD-D01's criterion over the kept moments of ``[start, end)``: the coverage of decision-v1's rows by a kept decision of the same
    selection at the same moment, and - for up to ``limit`` match-moments - every kept decision decided again by the replay's function from
    the same database: the differences (state, reason, codes, label, checkpoint) must be 0. Read-only."""
    stored = _fetch(conn, STORED_SQL, {"config": config.key, "start": start, "end": end})
    kept: dict[tuple[int, datetime, str], dict[tuple[str, int, str, str, Decimal, str | None], Mapping[str, Any]]] = defaultdict(dict)
    for r in stored:
        bucket = kept[(int(r["fixture_id"]), r["known_at"], str(r["trigger"]))]
        if r["family"] is not None:
            bucket[(str(r["family"]), int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]),
                    Decimal(str(r["line"])).quantize(decision.LINE_Q), r["model_hint"])] = r
    v1 = _fetch(conn, COVERAGE_SQL, {"version": DECISION_CORE, "start": start, "end": end})
    mirrored = {(f, at): b for (f, at, t), b in kept.items() if t == "mirror"}
    covered = sum(1 for r in v1 if any(k[1:5] == replay.key_of(r) for k in mirrored.get((int(r["fixture_id"]), r["known_at"]), {})))
    moments_v1 = {(int(r["fixture_id"]), r["known_at"]) for r in v1}
    checked = differences = 0
    examples: list[dict[str, Any]] = []
    fixtures = sorted({f for f, _, _ in kept})
    book = book_price.read(conn, store, fixtures) if config.price == engine.BOOK and fixtures and store is not None else None
    fams = [FAMILIES_BY_NAME[n] for n in config.families]
    for (fid, at, trigger), bucket in sorted(kept.items(), key=lambda kv: (kv[0][1], kv[0][0]))[:limit]:
        rows = None
        if trigger == "mirror":
            rows = _fetch(conn, V1_AT_SQL, {"fixture": fid, "at": at, "version": DECISION_CORE})
        if config.price == engine.BOOK and book is None:
            break
        again = replay.decide_at(conn, at=at, families=fams, fixtures=[fid], rows=rows, price=config.price, rules=config.rules,
                                 probability=config.probability, view_version=config.view_version, book=book)
        fresh = {(d.family, d.key[0], d.key[1], d.key[2], d.key[3], d.model_hint): d for d in again.decisions if d.key[0] == fid}
        checked += 1
        for k in set(bucket) | set(fresh):
            a, b = bucket.get(k), fresh.get(k)
            same = a is not None and b is not None and (a["state"], a["reason"], list(a["codes"] or []), a["label"], a["checkpoint"]) == (
                b.state, b.reason, list(b.codes), b.label, b.checkpoint)
            if not same:
                differences += 1
                if len(examples) < 20:
                    examples.append({"fixture_id": fid, "at": at.isoformat(), "trigger": trigger, "selection": [str(x) for x in k],
                                     "kept": None if a is None else [a["state"], a["reason"], list(a["codes"] or [])],
                                     "again": None if b is None else [b.state, b.reason, list(b.codes)]})
    triggers = Counter(t for _, _, t in kept)
    return {"config": config.key, "window": [start.isoformat(), end.isoformat()], "moments": dict(sorted(triggers.items())),
            "decisions": sum(len(b) for b in kept.values()),
            "coverage": {"v1_rows": len(v1), "covered": covered, "rate": None if not v1 else round(covered / len(v1), 4),
                         "v1_moments": len(moments_v1), "mirrored_moments": len(mirrored)},
            "equivalence": {"moments_checked": checked, "differences": differences, "examples": examples}}
