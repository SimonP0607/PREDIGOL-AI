"""The Knowledge Store (``ks-v1``, Plan Maestro IA, P1): ONE read surface over the memories PrediGol keeps today, in shadow.

Four memories hold what PrediGol Intelligence knows, each in its own shape, and a reader that wants "everything about this referee" has to know all four:

* ``ai.memory_events``      the AI's log (``fbi.ai.memory``): append-only events with their evidence, a confidence and the writer's version;
* ``intel.entity_memory``   memory-v4 (``fbi.intel.memory``): entity x aspect x Bogota day, the cumulative state as of the day and its delta;
* ``intel.family_memory``   memory-fam-v1 (``fbi.familydecisions.memory``): the families' post-mortems added up by family, market, competition, referee;
* ``intel.match_knowledge`` Match Knowledge mk-v1 (``fbi.knowledge``): the nine layers of a finished match;

and the relations of ``fbi.people`` (a player's clubs and national team, a coach's clubs, the referee of a match) plus the hypotheses the patterns and
the research propose (``analytics.research_hypotheses``). This module reads them and gives back ONE record type (``Record``): what is known about an
entity (team, player, coach, referee, competition, market - or a fixture, for an episode), of which kind (entity_state, event, episode, relation, lesson,
hypothesis), on which aspect, its value made compact, WHEN it was known, from which row of which table under which version, and the confidence or status
when the source has one. It never invents a value: a source that cannot answer is listed as ``Absent`` with the reason, not filled.

STRICT AS-OF. Every record carries ``known_at``: the moment the store could first have read it, which is the LATER of the moment its content refers to
and the moment its row was written. Nothing with ``known_at`` after ``at`` is returned - the SQL cuts on it and ``_cut`` cuts again - so a rebuilt row
(memory-v4 rebuilt from 13 October, a Match Knowledge row that supersedes another) is not seen before it existed:

    intel.entity_memory / intel.family_memory   max(end of the Bogota day ``as_of_day``, built_at)
    ai.memory_events                            created_at
    intel.match_knowledge                       max(known_at, built_at) of the newest build that satisfies both
    intel.decisions (+ outcomes)                max(known_at, created_at); the outcome only once settled_at and computed_at have passed
    intel.postmortems / match_ / family_        created_at
    core.player_spells / player_national_caps   built_at (rewritten in place: a past ``at`` sees a spell only if it was built by then),
                                                and an end after ``at`` is not told (the edge is open as of ``at``)
    core.coach_careers                          observed_at of the newest snapshot of the career observed by ``at``
    core.fixture_officials                      observed_at of the newest observation of the match by ``at``
    analytics.research_hypotheses               created_at; the status is replayed from ``stage_history`` up to ``at``

IN SHADOW. It writes nothing, deletes nothing and is imported by no decision path (``tests/unit/test_knowledge_store.py`` holds that
``fbi.intel.decision``, ``fbi.picks``, ``fbi.familydecisions.decide`` and ``fbi.api`` never import it). Its readers are the owner's command
(``python -m scripts.ia_knowledge``) and, later, the layers that will stop reading four stores. Like the rest of ``fbi.knowledge`` it imports nothing of
ours outside the package.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from itertools import combinations
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from fbi.knowledge import reader

VERSION: Final = "ks-v1"
BOGOTA: Final = ZoneInfo("America/Bogota")
"""The day of memory-v4 and memory-fam-v1 is a Bogota day: its state is known once that day is over there."""

Kind = Literal["entity_state", "event", "episode", "relation", "lesson", "hypothesis"]
KINDS: Final[tuple[Kind, ...]] = ("entity_state", "event", "episode", "relation", "lesson", "hypothesis")
ENTITY_TYPES: Final = ("team", "player", "coach", "referee", "competition", "market")
CANONICAL_ID: Final[Mapping[str, str]] = {
    "team": "core.teams.id", "player": "provider_player_id (core.players)", "coach": "core.coaches.id", "referee": "core.referees.id",
    "competition": "core.competitions.id", "market": "market key (market.markets.key)",
}
"""What the id of an entity is. A player is his provider id because that is what memory-v4, the AI's events and the spells all key him by."""

DECISION_LAYERS: Final[Mapping[str, str]] = {"core": reader.DECISION_LAYER, "families": "decision-fam-v1"}
"""Both layers of ``intel.decisions``, each labelled. A copy of ``fbi.core.decision_versions.LAYERS`` (this package imports nothing of ours), held equal
by ``tests/unit/test_knowledge_store.py``."""

PATTERN_KINDS: Final = frozenset({"league_pattern", "team_pattern", "player_pattern"})
"""The AI's events that state a pattern rather than a happening: lessons."""

MAX_LIST: Final = 10
MAX_TEXT: Final = 400
MAX_DEPTH: Final = 4
LIMIT: Final = 50
"""At most this many records of one source and kind per entity, newest first; the rest are counted in ``truncated``."""

MEMORY_EVENTS: Final = "ai.memory_events"
ENTITY_MEMORY: Final = "intel.entity_memory"
FAMILY_MEMORY: Final = "intel.family_memory"
MATCH_KNOWLEDGE: Final = "intel.match_knowledge"
DECISIONS: Final = "intel.decisions"
POSTMORTEMS: Final = "intel.postmortems"
MATCH_POSTMORTEMS: Final = "intel.match_postmortems"
FAMILY_POSTMORTEMS: Final = "intel.family_postmortems"
SPELLS: Final = "core.player_spells"
CAPS: Final = "core.player_national_caps"
CAREERS: Final = "core.coach_careers"
OFFICIALS: Final = "core.fixture_officials"
HYPOTHESES: Final = "analytics.research_hypotheses"

HOLDS: Final[Mapping[str, frozenset[str]]] = {
    ENTITY_MEMORY: frozenset(ENTITY_TYPES),
    FAMILY_MEMORY: frozenset({"market", "competition", "referee"}),
    MEMORY_EVENTS: frozenset({"team", "player", "competition", "market"}),
    MATCH_KNOWLEDGE: frozenset({"team", "competition", "referee"}),
    SPELLS: frozenset({"team", "player"}),
    CAPS: frozenset({"team", "player"}),
    CAREERS: frozenset({"team", "coach"}),
    OFFICIALS: frozenset({"referee"}),
    HYPOTHESES: frozenset(ENTITY_TYPES),
}
"""Which source can answer for which type of entity. The others are listed as absent (``not_held``), with the reason in ``WHY_NOT``."""

WHY_NOT: Final[Mapping[str, str]] = {
    FAMILY_MEMORY: "memory-fam-v1 keeps families, markets, competitions and referees only",
    MEMORY_EVENTS: "the AI's events are written about fixtures, picks, teams, players, competitions, markets, models, sources and reviewers",
    MATCH_KNOWLEDGE: "Match Knowledge is keyed by fixture; only a team's, a competition's and a referee's matches can be found from it",
    SPELLS: "the spells are a player's clubs",
    CAPS: "the caps are a player's national team",
    CAREERS: "the careers are a coach's clubs",
    OFFICIALS: "the officials are the referee of each match",
}

EVIDENCE_KEYS: Final[Mapping[str, tuple[str, ...]]] = {
    "team": ("team_id",), "player": ("provider_player_id", "player_id"), "coach": ("coach_id",), "referee": ("referee_id",),
    "competition": ("competition_id",), "market": ("market_key", "market"),
}
"""The keys of a hypothesis's evidence that name an entity directly. A hypothesis is also about an entity when it cites (``memory_refs``) an event of it."""


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Source:
    """Where a record comes from: the table, the row (its key as text) and the version that wrote it, when the row says."""

    table: str
    id: str
    version: str | None = None


@dataclass(frozen=True, slots=True)
class Record:
    """One thing known about an entity as of a moment."""

    kind: Kind
    entity_type: str
    entity_id: str
    aspect: str
    value: Any
    known_at: datetime
    source: Source
    valid_from: datetime | date | None = None
    valid_to: datetime | date | None = None
    confidence: float | None = None
    status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "entity": {"type": self.entity_type, "id": self.entity_id}, "aspect": self.aspect, "value": self.value,
            "known_at": _iso(self.known_at), "valid_from": _iso(self.valid_from), "valid_to": _iso(self.valid_to),
            "source": {"table": self.source.table, "id": self.source.id, "version": self.source.version},
            "confidence": self.confidence, "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class Absent:
    """A source that has nothing to say: it does not hold this type of entity (``not_held``), nothing of this entity was known by ``at``
    (``none_as_of``), or the entity is not in the catalogue (``not_in_catalogue``)."""

    source: str
    reason: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"source": self.source, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Entity:
    """An entity as the stores key it: the canonical id, its name, the keys each store writes it under."""

    type: str
    id: str
    name: str | None = None
    keys: tuple[str, ...] = ()
    """The ids it is stored under: the canonical one first, then memory-v4's ``p<provider id>`` of a coach or the referees merged into this one."""
    provider_id: int | None = None
    known: bool = True


@dataclass(frozen=True, slots=True)
class Answer:
    """What ``about``, ``episode`` or ``relations`` found."""

    entity: Entity
    at: datetime
    records: tuple[Record, ...]
    absent: tuple[Absent, ...] = ()
    truncated: Mapping[str, int] = field(default_factory=dict)
    """Per source and kind, how many more records there were than ``LIMIT`` (the oldest are left out)."""

    def by_kind(self, kind: Kind) -> list[Record]:
        return [r for r in self.records if r.kind == kind]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION, "at": _iso(self.at),
            "entity": {"type": self.entity.type, "id": self.entity.id, "name": self.entity.name, "keys": list(self.entity.keys),
                       "canonical": CANONICAL_ID.get(self.entity.type, "core.fixtures.id"), "in_catalogue": self.entity.known},
            "counts": {k: n for k in KINDS if (n := len(self.by_kind(k)))},
            "records": [r.as_dict() for r in self.records], "absent": [a.as_dict() for a in self.absent], "truncated": dict(self.truncated),
        }


# ── small pure things ────────────────────────────────────────────────────────────────────────────────────────────────


def _iso(moment: datetime | date | None) -> str | None:
    if moment is None:
        return None
    if isinstance(moment, datetime):
        return moment.astimezone(UTC).isoformat()
    return moment.isoformat()


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def compact(value: Any, depth: int = 0) -> Any:
    """A value made small and plain: lists cut to ``MAX_LIST`` (with how many there were), long texts cut, numbers as floats, moments as ISO text,
    and nothing deeper than ``MAX_DEPTH``. It drops nothing silently: a cut says so."""
    if isinstance(value, Mapping):
        if depth >= MAX_DEPTH:
            return {"_cut": f"{len(value)} keys"}
        return {str(k): compact(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        items = [compact(v, depth + 1) for v in list(value)[:MAX_LIST]]
        if len(value) > MAX_LIST:
            items.append({"_cut": f"{len(value) - MAX_LIST} more of {len(value)}"})
        return items
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return _iso(value)
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT] + "…"
    return value


def day_end(day: date) -> datetime:
    """The moment a Bogota day is over: the state a memory writes "as of" it is known then, not before."""
    return datetime.combine(day + timedelta(days=1), time(0), tzinfo=BOGOTA).astimezone(UTC)


def local_day(at: datetime) -> date:
    return at.astimezone(BOGOTA).date()


def later(*moments: datetime | None) -> datetime:
    found = [m for m in moments if m is not None]
    if not found:
        raise ValueError("a record needs a moment it was known")
    return max(found)


def _moment(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _cut(records: Iterable[Record], at: datetime) -> list[Record]:
    """The second guard of the as-of rule: whatever a query let through, nothing known after ``at`` leaves this module."""
    return [r for r in records if r.known_at <= at]


def market_of(entity_id: str) -> str:
    """The market of an AI event about a selection: ``<market>:<selection>:<line>`` (``fbi.intel.postmortem``) or the market key alone."""
    parts = entity_id.rsplit(":", 2)
    return parts[0] if len(parts) == 3 else entity_id


def status_as_of(row: Mapping[str, Any], at: datetime) -> str:
    """The status a hypothesis had at ``at``: PROPOSED when it was made, then each step of ``stage_history`` taken by then."""
    status = "PROPOSED"
    steps = [(m, s) for s in (row.get("stage_history") or []) if isinstance(s, Mapping) and (m := _moment(s.get("at"))) is not None]
    for moment, step in sorted(steps, key=lambda p: p[0]):
        if moment <= at and step.get("to"):
            status = str(step["to"])
    if not steps and row.get("decided_at") is not None and row["decided_at"] <= at:
        status = str(row["status"])
    return status


# ── each source's shape, normalised (pure) ───────────────────────────────────────────────────────────────────────────


def from_entity_memory(row: Mapping[str, Any], entity: Entity) -> Record:
    """A row of memory-v4: the cumulative state of one aspect as of a Bogota day."""
    day: date = row["as_of_day"]
    return Record(
        "entity_state", entity.type, entity.id, str(row["aspect"]),
        {"stats": compact(row["stats"]), "delta": compact(row.get("delta") or {}), "evidence": compact(row.get("evidence_ref"))},
        later(day_end(day), row["built_at"]), Source(ENTITY_MEMORY, str(row["id"]), str(row["version"])),
        valid_from=day, confidence=_float(row.get("confidence")))


def from_family_memory(row: Mapping[str, Any], entity: Entity) -> Record:
    """A snapshot of memory-fam-v1: what the families' post-mortems add up to for a market, a competition or a referee."""
    day: date = row["as_of_day"]
    return Record(
        "entity_state", entity.type, entity.id, "families",
        {"stats": compact(row["stats"]), "delta": compact(row.get("delta") or {}), "evidence": compact(row.get("evidence_ref"))},
        later(day_end(day), row["built_at"]), Source(FAMILY_MEMORY, str(row["id"]), str(row["version"])),
        valid_from=day, confidence=_float(row.get("confidence")))


def from_memory_event(row: Mapping[str, Any], entity_type: str, entity_id: str) -> Record:
    """An event of the AI's log; a pattern it states is a lesson."""
    kind: Kind = "lesson" if row["kind"] in PATTERN_KINDS else "event"
    value = {"hypothesis": row.get("hypothesis"), "result": row.get("result"), "evidence": compact(row.get("evidence") or {}),
             "fixture_id": row.get("fixture_id"), "stored_as": f"{row['entity_type']}:{row['entity_id']}"}
    return Record(kind, entity_type, entity_id, str(row["kind"]), value, row["created_at"],
                  Source(MEMORY_EVENTS, str(row["id"]), str(row["version"])), valid_from=row["created_at"],
                  confidence=_float(row.get("confidence")))


def from_match_knowledge(row: Mapping[str, Any]) -> list[Record]:
    """A build of Match Knowledge: one ``episode`` record per layer, each with its own status and the moment the layer itself was known."""
    known = later(row["known_at"], row["built_at"])
    fid = str(row["fixture_id"])
    out: list[Record] = []
    for name, layer in sorted((row.get("layers") or {}).items()):
        layer = layer if isinstance(layer, Mapping) else {}
        value = {"data": compact(layer.get("data") or {}), "sources": list(layer.get("sources") or []), "notes": list(layer.get("notes") or [])}
        out.append(Record("episode", "fixture", fid, str(name), value, known, Source(MATCH_KNOWLEDGE, str(row["id"]), str(row["version"])),
                          valid_from=_moment(layer.get("known_at")), status=str(layer.get("status") or "missing")))
    out.append(Record("episode", "fixture", fid, "completeness", {"quality": compact(row.get("quality") or {}), "supersedes": row.get("supersedes")},
                      known, Source(MATCH_KNOWLEDGE, str(row["id"]), str(row["version"])), status=str(row["completeness"])))
    return out


def from_match_summary(row: Mapping[str, Any], entity: Entity) -> Record:
    """A finished match of a team, a competition or a referee, as Match Knowledge put it together: its result layer and how complete it is."""
    stored = row.get("result")
    result: Mapping[str, Any] = stored if isinstance(stored, Mapping) else {}
    value = {"fixture_id": int(row["fixture_id"]), "kickoff_at": _iso(row["kickoff_at"]), "result": compact(result.get("data") or {})}
    return Record("episode", entity.type, entity.id, "match", value, later(row["known_at"], row["built_at"]),
                  Source(MATCH_KNOWLEDGE, str(row["id"]), str(row["version"])), valid_from=row["kickoff_at"], status=str(row["completeness"]))


def from_decision(row: Mapping[str, Any], at: datetime) -> Record:
    """A decision about a selection of the match (either layer, labelled), with its settlement only when that was known by ``at``."""
    layer = next((name for name, v in DECISION_LAYERS.items() if v == row["decision_version"]), "unknown")
    settled = row.get("settled_at")
    outcome = None
    if settled is not None and later(settled, row.get("computed_at")) <= at:
        outcome = {"result": row["result_status"], "profit_flat": _float(row["profit_flat"]), "clv": _float(row.get("clv")), "settled_at": _iso(settled),
                   "version": row.get("outcome_version")}
    value = {"layer": layer, "checkpoint": row["checkpoint"], "model": row["model_name"], "odds": _float(row.get("odds")),
             "p_model": _float(row.get("p_model")), "p_cal": _float(row.get("p_cal")), "p_market": _float(row.get("p_market")),
             "score": _float(row.get("score")), "stake_units": _float(row.get("stake_units")), "reasons": list(row.get("reasons") or []),
             "outcome": outcome}
    return Record("event", "fixture", str(row["fixture_id"]), f"decision:{row['market_key']}:{row['selection']}:{_float(row['line'])}", value,
                  later(row["known_at"], row.get("created_at")), Source(DECISIONS, str(row["id"]), str(row["decision_version"])),
                  valid_from=row["known_at"], status=str(row["state"]))


def from_postmortem(row: Mapping[str, Any], table: str) -> Record:
    """A post-mortem of the match: of a selection (``intel.postmortems``), of a family's decision (``intel.family_postmortems``) or of the match as a
    whole (``intel.match_postmortems``)."""
    if table == MATCH_POSTMORTEMS:
        aspect, status = "postmortem:match", None
        value: dict[str, Any] = {"outcome": compact(row.get("outcome") or {}), "findings": compact(row.get("findings") or {})}
    elif table == FAMILY_POSTMORTEMS:
        aspect, status = f"postmortem:{row['family']}:{row['market_key']}:{row['selection']}:{_float(row['line'])}", str(row["verdict"])
        value = {"decision_id": row["decision_id"], "result": row["result"], "quality": row["quality"], "clv": _float(row.get("clv")),
                 "profit_flat": _float(row.get("profit_flat")), "causes": compact(row.get("causes") or [])}
    else:
        selection = "" if row.get("market_key") is None else f":{row['market_key']}:{row['selection']}:{_float(row['line'])}"
        aspect, status = f"postmortem{selection or ':decision'}", str(row["verdict"])
        value = {"decision_id": row.get("decision_id"), "outcome": row["outcome"], "quality": row["decision_quality"],
                 "loss_class": row.get("loss_class"), "clv": _float(row.get("clv")), "causes": compact(row.get("causes") or [])}
    return Record("event", "fixture", str(row["fixture_id"]), aspect, value, row["created_at"], Source(table, str(row["id"]), str(row["version"])),
                  valid_from=row["created_at"], status=status)


def from_hypothesis(row: Mapping[str, Any], entity: Entity, at: datetime) -> Record:
    """A hypothesis proposed by the patterns or the research, with the status it had at ``at`` (not the one it has now)."""
    value = {"title": row["title"], "hypothesis": compact(row["hypothesis"]), "target": row["target"], "proposed_by": row["proposed_by"],
             "evidence": compact(row.get("evidence") or {})}
    return Record("hypothesis", entity.type, entity.id, f"hypothesis:{row['target']}", value, row["created_at"],
                  Source(HYPOTHESES, str(row["id"]), row.get("agent_version")), valid_from=row["created_at"], status=status_as_of(row, at))


def _open_end(end: date | None, at: datetime) -> date | None:
    """An end after ``at`` was not known at ``at``: the edge is open then."""
    return None if end is None or end > local_day(at) else end


def from_spell(row: Mapping[str, Any], at: datetime, *, entity: Entity) -> Record:
    """A streak of a player at a club (``spells-v1``), seen from the player or from the club."""
    value = {"player": int(row["provider_player_id"]), "provider_team_id": int(row["provider_team_id"]), "team_id": row.get("team_id"),
             "team": row.get("team_name"), "basis": row["source"], "matches": int(row["matches"]), "via": row.get("via"),
             "start_known": row.get("valid_from") is not None}
    return Record("relation", entity.type, entity.id, "player-club", value, row["built_at"],
                  Source(SPELLS, f"{row['provider_player_id']}:{row['ordinal']}", str(row["version"])),
                  valid_from=row.get("valid_from"), valid_to=_open_end(row.get("valid_to"), at))


def from_caps(row: Mapping[str, Any], *, entity: Entity) -> Record:
    """A player's caps for one national team, as of ``at``: how many, how many he played, the first and the last."""
    value = {"player": int(row["provider_player_id"]), "team_id": int(row["team_id"]), "team": row.get("team_name"), "caps": int(row["caps"]),
             "appeared": int(row["appeared"]), "starts": int(row["starts"])}
    return Record("relation", entity.type, entity.id, "player-national_team", value, row["built_at"],
                  Source(CAPS, f"{row['provider_player_id']}:{row['team_id']}", str(row["version"])),
                  valid_from=row["first_kickoff"], valid_to=row["last_kickoff"])


def from_career(row: Mapping[str, Any], at: datetime, *, entity: Entity) -> Record:
    """A club in a coach's career, from the newest snapshot of it observed by ``at``."""
    value = {"provider_coach_id": int(row["provider_coach_id"]), "coach_id": row.get("coach_id"), "provider_team_id": row.get("provider_team_id"),
             "team_id": row.get("team_id"), "team": row.get("team_name")}
    return Record("relation", entity.type, entity.id, "coach-club", value, row["observed_at"],
                  Source(CAREERS, f"{row['provider_coach_id']}:{_iso(row['observed_at'])}:{row['ordinal']}", str(row["normalizer_version"])),
                  valid_from=row.get("start_date"), valid_to=_open_end(row.get("end_date"), at))


def from_official(row: Mapping[str, Any], *, entity_type: str, entity_id: str) -> Record:
    """The referee of a match, by the newest observation of it by ``at``."""
    value = {"referee_id": int(row["referee_id"]), "fixture_id": int(row["fixture_id"]), "alias_id": int(row["alias_id"]),
             "home_team_id": row.get("home_team_id"), "away_team_id": row.get("away_team_id")}
    return Record("relation", entity_type, entity_id, "referee-match", value, row["observed_at"],
                  Source(OFFICIALS, f"{row['fixture_id']}:{_iso(row['observed_at'])}", None), valid_from=row["kickoff_at"], valid_to=row["kickoff_at"])


# ── the queries ──────────────────────────────────────────────────────────────────────────────────────────────────────

VERSION_RANK: Final = "NULLIF(regexp_replace(version, '[^0-9]', '', 'g'), '')::int DESC NULLS LAST"
"""The newer version of a memory wins a day, as in the views ``*_latest``."""

ENTITY_MEMORY_SQL: Final = f"""
SELECT DISTINCT ON (aspect) id, entity_type, entity_id, entity_name, aspect, as_of_day, built_at, version, stats, delta, confidence, evidence_ref
  FROM intel.entity_memory
 WHERE entity_type = %(type)s AND entity_id = ANY(%(keys)s) AND as_of_day < %(today)s AND built_at <= %(at)s
   AND (%(aspects)s::text[] IS NULL OR aspect = ANY(%(aspects)s))
 ORDER BY aspect, as_of_day DESC, {VERSION_RANK}, id DESC
"""
"""The state of each aspect as of ``at``: the newest Bogota day that was over by then, of a row written by then."""

FAMILY_MEMORY_SQL: Final = f"""
SELECT id, version, as_of_day, built_at, entity_type, entity_key, entity_name, stats, delta, confidence, evidence_ref
  FROM intel.family_memory
 WHERE entity_type = %(type)s AND entity_key = ANY(%(keys)s) AND as_of_day < %(today)s AND built_at <= %(at)s
 ORDER BY as_of_day DESC, {VERSION_RANK}, id DESC
 LIMIT 1
"""

MEMORY_EVENTS_SQL: Final = """
SELECT id, created_at, kind, entity_type, entity_id, fixture_id, hypothesis, evidence, result, confidence::float8 AS confidence, version,
       count(*) OVER () AS total
  FROM ai.memory_events
 WHERE created_at <= %(at)s AND entity_type = %(type)s
   AND (entity_id = ANY(%(keys)s) OR (%(type)s = 'market' AND split_part(entity_id, ':', 1) = ANY(%(keys)s)))
 ORDER BY created_at DESC, id DESC
 LIMIT %(limit)s
"""

FIXTURE_EVENTS_SQL: Final = """
SELECT id, created_at, kind, entity_type, entity_id, fixture_id, hypothesis, evidence, result, confidence::float8 AS confidence, version
  FROM ai.memory_events
 WHERE created_at <= %(at)s AND (fixture_id = %(f)s OR (entity_type = 'fixture' AND entity_id = %(fid)s))
 ORDER BY created_at, id
"""

TEAM_FIXTURES_SQL: Final = "SELECT id FROM core.fixtures WHERE (home_team_id = %(id)s OR away_team_id = %(id)s) AND kickoff_at <= %(at)s"
COMPETITION_FIXTURES_SQL: Final = """
SELECT f.id FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE cs.competition_id = %(id)s AND f.kickoff_at <= %(at)s
"""

SUMMARIES_SQL: Final = """
SELECT * FROM (
    SELECT DISTINCT ON (k.fixture_id) k.id, k.fixture_id, k.version, k.built_at, k.known_at, k.completeness, k.layers -> 'c1_result' AS result,
           f.kickoff_at
      FROM intel.match_knowledge k
      JOIN core.fixtures f ON f.id = k.fixture_id
     WHERE k.fixture_id = ANY(%(fixtures)s) AND k.built_at <= %(at)s AND k.known_at <= %(at)s
     ORDER BY k.fixture_id, k.id DESC
) s ORDER BY kickoff_at DESC, fixture_id DESC
"""
"""The newest build of each of the entity's matches made, and knowing only what was known, by ``at``."""

BUILD_SQL: Final = """
SELECT id, fixture_id, version, supersedes, built_at, known_at, completeness, layers, quality
  FROM intel.match_knowledge
 WHERE fixture_id = %(f)s AND built_at <= %(at)s AND known_at <= %(at)s
 ORDER BY id DESC LIMIT 1
"""

DECISIONS_SQL: Final = """
SELECT d.id, d.decision_version, d.known_at, d.created_at, d.checkpoint, d.fixture_id, d.market_key, d.selection, d.line, d.model_name, d.odds,
       d.p_model, d.p_cal, d.p_market, d.score, d.stake_units, d.state, d.reasons,
       o.settled_at, o.computed_at, o.result_status, o.profit_flat, o.clv, o.version AS outcome_version
  FROM intel.decisions d
  LEFT JOIN intel.decision_outcomes o ON o.decision_id = d.id
 WHERE d.fixture_id = %(f)s AND d.decision_version = ANY(%(layers)s) AND d.known_at <= %(at)s AND d.created_at <= %(at)s
 ORDER BY d.known_at, d.id
"""
"""Every decision of the match by ``at``, of both layers (each says which: ``decision_version``); its outcome is told only once it was known."""

POSTMORTEMS_SQL: Final[Mapping[str, str]] = {
    POSTMORTEMS: "SELECT * FROM intel.postmortems WHERE fixture_id = %(f)s AND created_at <= %(at)s ORDER BY created_at, id",
    FAMILY_POSTMORTEMS: "SELECT * FROM intel.family_postmortems WHERE fixture_id = %(f)s AND created_at <= %(at)s ORDER BY created_at, id",
    MATCH_POSTMORTEMS: "SELECT * FROM intel.match_postmortems WHERE fixture_id = %(f)s AND created_at <= %(at)s ORDER BY created_at, id",
}

SPELLS_SQL: Final = """
SELECT s.*, t.id AS team_id, count(*) OVER () AS total
  FROM core.player_spells s
  LEFT JOIN core.teams t ON t.provider_team_id = s.provider_team_id
 WHERE s.{side} = %(id)s AND s.built_at <= %(at)s AND (s.valid_from IS NULL OR s.valid_from <= %(today)s)
 ORDER BY s.valid_from DESC NULLS LAST, s.provider_player_id, s.ordinal
 LIMIT %(limit)s
"""

CAPS_SQL: Final = """
SELECT c.provider_player_id, c.team_id, t.name AS team_name, count(*) AS caps, count(*) FILTER (WHERE c.appeared) AS appeared,
       count(*) FILTER (WHERE c.is_starter) AS starts, min(f.kickoff_at) AS first_kickoff, max(f.kickoff_at) AS last_kickoff,
       max(c.built_at) AS built_at, max(c.version) AS version, count(*) OVER () AS total
  FROM core.player_national_caps c
  JOIN core.fixtures f ON f.id = c.fixture_id
  JOIN core.teams t ON t.id = c.team_id
 WHERE c.{side} = %(id)s AND c.built_at <= %(at)s AND f.kickoff_at <= %(at)s
 GROUP BY c.provider_player_id, c.team_id, t.name
 ORDER BY max(f.kickoff_at) DESC
 LIMIT %(limit)s
"""

CAREERS_SQL: Final = """
SELECT k.*, count(*) OVER () AS total
  FROM core.coach_careers k
 WHERE k.{side} = %(id)s AND (k.start_date IS NULL OR k.start_date <= %(today)s)
   AND k.observed_at = (SELECT max(x.observed_at) FROM core.coach_careers x
                         WHERE x.provider_coach_id = k.provider_coach_id AND x.observed_at <= %(at)s)
 ORDER BY k.start_date DESC NULLS LAST, k.provider_coach_id, k.ordinal
 LIMIT %(limit)s
"""
"""Each career as its newest snapshot observed by ``at`` says it was (``core.coach_spells`` is the newest snapshot of today)."""

OFFICIALS_SQL: Final = """
SELECT * FROM (
    SELECT DISTINCT ON (o.fixture_id) o.fixture_id, o.observed_at, o.alias_id, a.referee_id, f.kickoff_at, f.home_team_id, f.away_team_id
      FROM core.fixture_officials o
      JOIN core.referee_aliases a ON a.id = o.alias_id
      JOIN core.fixtures f ON f.id = o.fixture_id
     WHERE o.role = 'referee' AND o.observed_at <= %(at)s AND f.kickoff_at <= %(at)s
       AND o.fixture_id = ANY(COALESCE(%(fixtures)s::bigint[], ARRAY(
             SELECT x.fixture_id FROM core.fixture_officials x JOIN core.referee_aliases y ON y.id = x.alias_id
              WHERE y.referee_id = ANY(%(keys)s::bigint[]) AND x.observed_at <= %(at)s)))
     ORDER BY o.fixture_id, o.observed_at DESC
) n WHERE %(keys)s::bigint[] IS NULL OR n.referee_id = ANY(%(keys)s::bigint[])
 ORDER BY n.kickoff_at DESC, n.fixture_id DESC
"""
"""The referee of each match by its newest observation by ``at`` - of the matches of a referee (``keys``) or of the given ones (``fixtures``)."""

HYPOTHESES_SQL: Final = """
SELECT h.id, h.title, h.hypothesis, h.target, h.proposed_by, h.evidence, h.status, h.created_at, h.decided_at, h.stage_history, h.agent_version
  FROM analytics.research_hypotheses h
 WHERE h.created_at <= %(at)s
   AND (EXISTS (SELECT 1 FROM unnest(%(evidence_keys)s::text[]) k WHERE h.evidence ->> k = ANY(%(keys)s))
        OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(CASE WHEN jsonb_typeof(h.evidence -> 'memory_refs') = 'array'
                                                                THEN h.evidence -> 'memory_refs' ELSE '[]'::jsonb END) r
                    WHERE r.value ~ '^[0-9]+$' AND r.value::bigint = ANY(%(events)s::bigint[])))
 ORDER BY h.created_at DESC, h.id DESC
"""
"""The hypotheses of an entity made by ``at``: those whose evidence names it, and those that cite one of its events."""

EVENT_IDS_SQL: Final = """
SELECT id FROM ai.memory_events
 WHERE created_at <= %(at)s AND entity_type = %(type)s
   AND (entity_id = ANY(%(keys)s) OR (%(type)s = 'market' AND split_part(entity_id, ':', 1) = ANY(%(keys)s)))
"""

FIXTURE_SQL: Final = """
SELECT f.id, f.kickoff_at, f.status_group, f.home_team_id, f.away_team_id, cs.competition_id
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.id = %(f)s
"""

ENTITY_SQL: Final[Mapping[str, str]] = {
    "team": "SELECT id::text AS id, name, provider_team_id AS provider_id FROM core.teams WHERE id = %(n)s",
    "player": "SELECT provider_player_id::text AS id, name, provider_player_id AS provider_id FROM core.players WHERE provider_player_id = %(n)s",
    "coach": "SELECT id::text AS id, name, provider_coach_id AS provider_id FROM core.coaches WHERE id = %(n)s OR provider_coach_id = %(p)s "
             "ORDER BY (id = %(n)s) DESC LIMIT 1",
    "referee": "SELECT id::text AS id, name, NULL::int AS provider_id FROM core.referees WHERE id = %(n)s",
    "competition": "SELECT id::text AS id, name, provider_league_id AS provider_id FROM core.competitions WHERE id = %(n)s",
}
MERGED_SQL: Final = "SELECT id::text AS id FROM core.referees WHERE merged_into = %(n)s ORDER BY id"
MARKET_SQL: Final = "SELECT key AS id, name FROM market.markets WHERE key = %(key)s"


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _check(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("at must be timezone-aware")
    return at.astimezone(UTC)


def _number(entity_id: str) -> int | None:
    text = entity_id.strip()
    return int(text) if text.isdigit() else None


def resolve(conn: psycopg.Connection[Any], entity_type: str, entity_id: str | int) -> Entity:
    """The entity as the stores key it. One the catalogue does not hold is still looked for under the id given (``known`` False)."""
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity type {entity_type!r}: one of {', '.join(ENTITY_TYPES)}")
    raw = str(entity_id).strip()
    if entity_type == "market":
        found = _rows(conn, MARKET_SQL, {"key": raw})
        return Entity("market", raw, found[0]["name"] if found else None, (raw,), known=bool(found))
    provider = _number(raw[1:]) if entity_type == "coach" and raw.startswith("p") else None
    number = _number(raw)
    if number is None and provider is None:
        raise ValueError(f"a {entity_type} is named by a number (got {raw!r})")
    found = _rows(conn, ENTITY_SQL[entity_type], {"n": number if number is not None else -1, "p": provider if provider is not None else -1})
    if not found:
        return Entity(entity_type, raw, None, (raw,), known=False)
    row = found[0]
    keys = [str(row["id"])]
    if entity_type == "coach" and row["provider_id"] is not None:
        keys.append(f"p{row['provider_id']}")
    if entity_type == "referee":
        keys += [r["id"] for r in _rows(conn, MERGED_SQL, {"n": int(row["id"])})]
    return Entity(entity_type, str(row["id"]), row["name"], tuple(keys), row["provider_id"], True)


class _Collect:
    """What a read gathers: the records, the sources that had nothing, and what was cut by ``LIMIT``."""

    def __init__(self, entity: Entity, at: datetime) -> None:
        self.entity, self.at = entity, at
        self.records: list[Record] = []
        self.absent: list[Absent] = []
        self.truncated: dict[str, int] = {}

    def add(self, source: str, records: Sequence[Record], *, total: int | None = None, empty: str | None = None) -> None:
        kept = _cut(records, self.at)
        self.records += kept
        if total is not None and total > len(records):
            self.truncated[source] = total - len(records)
        if not kept and not any(a.source == source for a in self.absent) and not any(r.source.table == source for r in self.records):
            self.absent.append(Absent(source, "none_as_of", empty or f"nothing of this {self.entity.type} known by {_iso(self.at)}"))

    def not_held(self, source: str) -> None:
        self.absent.append(Absent(source, "not_held", WHY_NOT.get(source, "")))

    def answer(self) -> Answer:
        order = {k: n for n, k in enumerate(KINDS)}
        records = sorted(self.records, key=lambda r: (order[r.kind], r.source.table, -r.known_at.timestamp(), r.aspect))
        absent = [a for a in self.absent if not any(r.source.table == a.source for r in records) or a.reason != "none_as_of"]
        return Answer(self.entity, self.at, tuple(records), tuple(absent), dict(self.truncated))


def _held(c: _Collect, source: str) -> bool:
    if c.entity.type in HOLDS[source]:
        return True
    c.not_held(source)
    return False


def _total(rows: Sequence[Mapping[str, Any]]) -> int:
    return int(rows[0]["total"]) if rows else 0


# ── the reads ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _relations(conn: psycopg.Connection[Any], c: _Collect, *, limit: int) -> list[int]:
    """The time-bounded edges of the entity, and (for a referee) the matches they lead to."""
    e, at = c.entity, c.at
    today = local_day(at)
    fixtures: list[int] = []
    if _held(c, SPELLS):
        if e.type == "player" or e.provider_id is not None:
            side = "provider_player_id" if e.type == "player" else "provider_team_id"
            ident = int(e.id) if e.type == "player" else e.provider_id
            rows = _rows(conn, SPELLS_SQL.format(side=side), {"id": ident, "at": at, "today": today, "limit": limit})
            c.add(SPELLS, [from_spell(r, at, entity=e) for r in rows], total=_total(rows))
        else:
            c.absent.append(Absent(SPELLS, "not_in_catalogue", "the club's provider id is needed to find its players' spells"))
    if _held(c, CAPS):
        side = "provider_player_id" if e.type == "player" else "team_id"
        rows = _rows(conn, CAPS_SQL.format(side=side), {"id": int(e.id), "at": at, "limit": limit})
        c.add(CAPS, [from_caps(r, entity=e) for r in rows], total=_total(rows))
    if _held(c, CAREERS):
        side, ident = ("team_id", int(e.id)) if e.type == "team" else ("provider_coach_id", e.provider_id)
        if ident is None:
            c.absent.append(Absent(CAREERS, "not_in_catalogue", "the coach's provider id is needed to find his career"))
        else:
            rows = _rows(conn, CAREERS_SQL.format(side=side), {"id": ident, "at": at, "today": today, "limit": limit})
            c.add(CAREERS, [from_career(r, at, entity=e) for r in rows], total=_total(rows))
    if _held(c, OFFICIALS):
        keys = [int(k) for k in e.keys if k.isdigit()]
        rows = _rows(conn, OFFICIALS_SQL, {"keys": keys, "fixtures": None, "at": at})
        fixtures = [int(r["fixture_id"]) for r in rows]
        c.add(OFFICIALS, [from_official(r, entity_type=e.type, entity_id=e.id) for r in rows[:limit]], total=len(rows))
    return fixtures


def about(conn: psycopg.Connection[Any], entity_type: str, entity_id: str | int, *, at: datetime, aspects: Sequence[str] | None = None,
          limit: int = LIMIT) -> Answer:
    """Everything known about an entity as of ``at``, from the four memories, the relations and the hypotheses. ``aspects`` narrows memory-v4's
    states (``market:1X2``, ``discipline``, ``corners``...); the rest is not filtered by it."""
    at = _check(at)
    entity = resolve(conn, entity_type, entity_id)
    c = _Collect(entity, at)
    if not entity.known:
        c.absent.append(Absent("catalogue", "not_in_catalogue", f"no {entity_type} {entity_id} in the catalogue; the memories are read under that id"))
    keys = list(entity.keys)
    today = local_day(at)
    rows = _rows(conn, ENTITY_MEMORY_SQL, {"type": entity.type, "keys": keys, "today": today, "at": at,
                                           "aspects": None if aspects is None else list(aspects)})
    c.add(ENTITY_MEMORY, [from_entity_memory(r, entity) for r in rows])
    if _held(c, FAMILY_MEMORY):
        rows = _rows(conn, FAMILY_MEMORY_SQL, {"type": entity.type, "keys": keys, "today": today, "at": at})
        c.add(FAMILY_MEMORY, [from_family_memory(r, entity) for r in rows])
    if _held(c, MEMORY_EVENTS):
        rows = _rows(conn, MEMORY_EVENTS_SQL, {"type": entity.type, "keys": keys, "at": at, "limit": limit})
        c.add(MEMORY_EVENTS, [from_memory_event(r, entity.type, entity.id) for r in rows], total=_total(rows))
    referee_fixtures = _relations(conn, c, limit=limit)
    if _held(c, MATCH_KNOWLEDGE):
        if entity.type == "referee":
            fixtures = referee_fixtures
        else:
            sql = TEAM_FIXTURES_SQL if entity.type == "team" else COMPETITION_FIXTURES_SQL
            fixtures = [int(r["id"]) for r in _rows(conn, sql, {"id": _number(entity.id) or -1, "at": at})]
        rows = _rows(conn, SUMMARIES_SQL, {"fixtures": fixtures, "at": at}) if fixtures else []
        c.add(MATCH_KNOWLEDGE, [from_match_summary(r, entity) for r in rows[:limit]], total=len(rows))
    events = [int(r["id"]) for r in _rows(conn, EVENT_IDS_SQL, {"type": entity.type, "keys": keys, "at": at})] if entity.type in HOLDS[MEMORY_EVENTS] else []
    rows = _rows(conn, HYPOTHESES_SQL, {"at": at, "evidence_keys": list(EVIDENCE_KEYS[entity.type]), "keys": keys, "events": events})
    c.add(HYPOTHESES, [from_hypothesis(r, entity, at) for r in rows[:limit]], total=len(rows))
    return c.answer()


def relations(conn: psycopg.Connection[Any], entity_type: str, entity_id: str | int, *, at: datetime, limit: int = LIMIT) -> Answer:
    """The time-bounded edges of an entity as of ``at``: player-club, player-national team, coach-club, referee-match."""
    at = _check(at)
    c = _Collect(resolve(conn, entity_type, entity_id), at)
    _relations(conn, c, limit=limit)
    return c.answer()


def episode(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> Answer:
    """A match as it was known at ``at``: the layers of the newest Match Knowledge build made by then, the decisions of both layers (with the outcomes
    known by then), the post-mortems written by then, the AI's events about it and its referee."""
    at = _check(at)
    found = _rows(conn, FIXTURE_SQL, {"f": fixture_id})
    entity = Entity("fixture", str(fixture_id), None, (str(fixture_id),), known=bool(found))
    c = _Collect(entity, at)
    if not found:
        c.absent.append(Absent("core.fixtures", "not_in_catalogue", f"no fixture {fixture_id}"))
        return c.answer()
    build = _rows(conn, BUILD_SQL, {"f": fixture_id, "at": at})
    c.add(MATCH_KNOWLEDGE, from_match_knowledge(build[0]) if build else [],
          empty="no build of the match made by then (a match is put together once it is over and settled)")
    c.add(DECISIONS, [from_decision(r, at) for r in _rows(conn, DECISIONS_SQL, {"f": fixture_id, "at": at, "layers": list(DECISION_LAYERS.values())})])
    for table, sql in POSTMORTEMS_SQL.items():
        c.add(table, [from_postmortem(r, table) for r in _rows(conn, sql, {"f": fixture_id, "at": at})])
    rows = _rows(conn, FIXTURE_EVENTS_SQL, {"f": fixture_id, "fid": str(fixture_id), "at": at})
    c.add(MEMORY_EVENTS, [from_memory_event(r, "fixture", str(fixture_id)) for r in rows])
    rows = _rows(conn, OFFICIALS_SQL, {"keys": None, "fixtures": [fixture_id], "at": at})
    c.add(OFFICIALS, [from_official(r, entity_type="fixture", entity_id=str(fixture_id)) for r in rows])
    return c.answer()


# ── coverage: the evidence for the unification ───────────────────────────────────────────────────────────────────────

COVERAGE_SQL: Final[Mapping[str, Mapping[str, str]]] = {
    "team": {
        ENTITY_MEMORY: "SELECT DISTINCT entity_id AS id FROM intel.entity_memory WHERE entity_type = 'team'",
        MEMORY_EVENTS: "SELECT DISTINCT entity_id AS id FROM ai.memory_events WHERE entity_type = 'team'",
        MATCH_KNOWLEDGE: "SELECT DISTINCT t.id::text AS id FROM intel.match_knowledge k JOIN core.fixtures f ON f.id = k.fixture_id "
                         "CROSS JOIN LATERAL (VALUES (f.home_team_id), (f.away_team_id)) t(id)",
        SPELLS: "SELECT DISTINCT COALESCE(t.id::text, 'provider:' || s.provider_team_id) AS id FROM core.player_spells s "
                "LEFT JOIN core.teams t ON t.provider_team_id = s.provider_team_id",
        CAPS: "SELECT DISTINCT team_id::text AS id FROM core.player_national_caps",
        CAREERS: "SELECT DISTINCT team_id::text AS id FROM core.coach_careers WHERE team_id IS NOT NULL",
    },
    "player": {
        ENTITY_MEMORY: "SELECT DISTINCT entity_id AS id FROM intel.entity_memory WHERE entity_type = 'player'",
        MEMORY_EVENTS: "SELECT DISTINCT entity_id AS id FROM ai.memory_events WHERE entity_type = 'player'",
        SPELLS: "SELECT DISTINCT provider_player_id::text AS id FROM core.player_spells",
        CAPS: "SELECT DISTINCT provider_player_id::text AS id FROM core.player_national_caps",
    },
    "coach": {
        ENTITY_MEMORY: "SELECT DISTINCT COALESCE(c.id::text, m.entity_id) AS id FROM intel.entity_memory m "
                       "LEFT JOIN core.coaches c ON m.entity_id ~ '^p[0-9]+$' AND c.provider_coach_id = substr(m.entity_id, 2)::int "
                       "WHERE m.entity_type = 'coach'",
        CAREERS: "SELECT DISTINCT COALESCE(coach_id::text, 'p' || provider_coach_id) AS id FROM core.coach_careers",
    },
    "referee": {
        ENTITY_MEMORY: "SELECT DISTINCT entity_id AS id FROM intel.entity_memory WHERE entity_type = 'referee' AND entity_id ~ '^[0-9]+$'",
        FAMILY_MEMORY: "SELECT DISTINCT entity_key AS id FROM intel.family_memory WHERE entity_type = 'referee'",
        OFFICIALS: "SELECT DISTINCT a.referee_id::text AS id FROM core.fixture_officials o JOIN core.referee_aliases a ON a.id = o.alias_id",
        MATCH_KNOWLEDGE: "SELECT DISTINCT a.referee_id::text AS id FROM intel.match_knowledge k JOIN core.fixture_officials o ON o.fixture_id = k.fixture_id "
                         "JOIN core.referee_aliases a ON a.id = o.alias_id",
    },
    "competition": {
        ENTITY_MEMORY: "SELECT DISTINCT entity_id AS id FROM intel.entity_memory WHERE entity_type = 'competition'",
        MEMORY_EVENTS: "SELECT DISTINCT entity_id AS id FROM ai.memory_events WHERE entity_type = 'competition'",
        FAMILY_MEMORY: "SELECT DISTINCT entity_key AS id FROM intel.family_memory WHERE entity_type = 'competition'",
        MATCH_KNOWLEDGE: "SELECT DISTINCT cs.competition_id::text AS id FROM intel.match_knowledge k JOIN core.fixtures f ON f.id = k.fixture_id "
                         "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id",
        HYPOTHESES: "SELECT DISTINCT evidence ->> 'competition_id' AS id FROM analytics.research_hypotheses WHERE evidence ? 'competition_id'",
    },
    "market": {
        ENTITY_MEMORY: "SELECT DISTINCT entity_id AS id FROM intel.entity_memory WHERE entity_type = 'market'",
        MEMORY_EVENTS: "SELECT DISTINCT split_part(entity_id, ':', 1) AS id FROM ai.memory_events WHERE entity_type = 'market'",
        FAMILY_MEMORY: "SELECT DISTINCT entity_key AS id FROM intel.family_memory WHERE entity_type = 'market'",
    },
}
"""For each type of entity, the ids each source holds, under the canonical id (a coach of memory-v4's ``p<provider id>`` resolved when the catalogue
can; a club of the spells the catalogue does not hold stays ``provider:<id>``; memory-v2's referees keyed by a string are not people and not counted)."""

LEGACY_SQL: Final = "SELECT count(DISTINCT entity_id) AS n FROM intel.entity_memory WHERE entity_type = 'referee' AND entity_id !~ '^[0-9]+$'"


def overlap(sets: Mapping[str, set[str]]) -> dict[str, Any]:
    """How the sources cover one type of entity: how many each holds, the union, every pair's intersection, what only one holds and what each misses."""
    union: set[str] = set().union(*sets.values()) if sets else set()
    every = set.intersection(*sets.values()) if sets else set()
    return {
        "sources": {s: len(ids) for s, ids in sets.items()},
        "union": len(union),
        "in_every_source": len(every),
        "pairs": {f"{a} & {b}": len(sets[a] & sets[b]) for a, b in combinations(sorted(sets), 2)},
        "only_in": {s: len(ids - set().union(*(o for n, o in sets.items() if n != s))) for s, ids in sets.items()},
        "missing_from": {s: len(union - ids) for s, ids in sets.items()},
    }


def coverage(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """Per type of entity: how many entities each memory and relation covers, the overlaps and the gaps - today, over every row."""
    out: dict[str, Any] = {"version": VERSION, "types": {}}
    for kind, sources in COVERAGE_SQL.items():
        sets = {s: {str(r["id"]) for r in _rows(conn, sql, {}) if r["id"] is not None} for s, sql in sources.items()}
        block = overlap(sets)
        block["not_held_by"] = sorted(s for s in HOLDS if kind not in HOLDS[s] and s != HYPOTHESES)
        out["types"][kind] = block
    out["types"]["referee"]["legacy_string_keys"] = int(_rows(conn, LEGACY_SQL, {})[0]["n"])
    return out


def dumps(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)
