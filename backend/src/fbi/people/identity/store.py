"""Where external identity and names are written (AD-H01, AD-H02, AD-H09): loads as versions, differences, decisions.

A LOAD is a version: a pinned Reep release (``load_reep``) or a sync of our own names and of the old alias tables
(``sync_core``). A load writes only what changed against what is in force for its source: new rows are added under the load,
rows it no longer has are RETIRED (``core.entity_identity_retirements``); nothing is updated or deleted. Retiring a load
(``retire_load``) hides what it added and brings back what it retired. Loading the same release again writes nothing.

What a person decides (``decide``, ``decide_link``, ``undo``) is a row of ``core.entity_identity_decisions``; the views
``core.entity_ids_live`` / ``core.entity_aliases_live`` / ``core.entity_identity_queue_open`` combine the three.

``backfill_player_keys`` fills ``player_id`` on the old rows of ``core.squad_members`` and ``ai.evidence`` (AD-H09) in small
committed batches with a short ``lock_timeout``; the trigger of migration 0141 keeps the new ones.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.people.identity import names as nm
from fbi.people.identity import rules
from fbi.people.identity.reep import LICENSE, ReepData
from fbi.people.identity.rules import AliasRow, IdRow, Ours, QueueItem

TABLES: Final[Mapping[str, tuple[str, str]]] = {
    "player": ("core.players", "provider_player_id"),
    "team": ("core.teams", "provider_team_id"),
    "coach": ("core.coaches", "provider_coach_id"),
    "competition": ("core.competitions", "provider_league_id"),
    "venue": ("core.venues", "provider_venue_id"),
    "referee": ("core.referees", ""),
}
"""Our table of each entity type and the column holding its API-Football id (referees have none: the provider gives no id)."""

LINKABLE: Final = ("player", "team", "coach", "competition", "venue")

_ENTITY_SQL: Final[Mapping[str, str]] = {
    "player": "SELECT id, provider_player_id, name, firstname, lastname, birth_date FROM core.players ORDER BY id",
    "coach": "SELECT id, provider_coach_id, name, firstname, lastname, birth_date FROM core.coaches ORDER BY id",
    "team": "SELECT id, provider_team_id, name, short_name, NULL, NULL FROM core.teams ORDER BY id",
    "competition": "SELECT id, provider_league_id, name, NULL, NULL, NULL FROM core.competitions ORDER BY id",
    "venue": "SELECT id, provider_venue_id, name, NULL, NULL, NULL FROM core.venues ORDER BY id",
    "referee": "SELECT id, NULL, name, NULL, NULL, NULL FROM core.referees WHERE status = 'active' ORDER BY id",
}


def our_entities(conn: psycopg.Connection[Any], entity_type: str) -> Iterator[Ours]:
    """Our entities of one type as the rules read them, streamed."""
    with conn.cursor(name=f"identity_{entity_type}", row_factory=tuple_row) as cur:
        cur.itersize = 5000
        cur.execute(_ENTITY_SQL[entity_type])
        for eid, provider_id, name, first, last, birth in cur:
            names: list[str] = [str(name)] if name else []
            if entity_type in rules.PERSONS and first and last:
                names.append(f"{first} {last}")
            elif entity_type == "team" and first:
                names.append(str(first))  # short_name
            yield Ours(entity_type, int(eid), int(provider_id) if provider_id is not None else None, tuple(names),
                       birth, str(first) if entity_type in rules.PERSONS and first else None)


def provider_ids(conn: psycopg.Connection[Any]) -> dict[str, set[int]]:
    """The API-Football ids we hold, per type: what the release reader keeps."""
    out: dict[str, set[int]] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        for etype in LINKABLE:
            table, column = TABLES[etype]
            cur.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")
            out[etype] = {int(r[0]) for r in cur.fetchall()}
    return out


# ── loads and differences ────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class LoadReport:
    load_id: int | None
    source: str
    release: str
    already_loaded: bool = False
    counts: dict[str, int] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)


_VISIBLE_SQL: Final = """
SELECT t.id, t.row_key FROM core.{table} t
  JOIN core.entity_id_loads l ON l.id = t.load_id AND l.status = 'active' AND l.source = %(source)s
 WHERE NOT EXISTS (SELECT 1 FROM core.entity_identity_retirements r
                     JOIN core.entity_id_loads rl ON rl.id = r.load_id AND rl.status = 'active'
                    WHERE r.kind = %(kind)s AND r.row_id = t.id)
"""


COPY_CHUNK: Final = 20_000


def _copy(cur: psycopg.Cursor[Any], sql: str, rows: Iterable[tuple[Any, ...]]) -> None:
    """COPY in chunks: the rows may come from a server-side cursor of the same connection, which cannot fetch while a COPY
    is open."""
    chunk: list[tuple[Any, ...]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= COPY_CHUNK:
            with cur.copy(sql) as cp:
                for r in chunk:
                    cp.write_row(r)
            chunk = []
    if chunk:
        with cur.copy(sql) as cp:
            for r in chunk:
                cp.write_row(r)


def _stage_ids(cur: psycopg.Cursor[Any], rows: Iterable[IdRow]) -> None:
    cur.execute("DROP TABLE IF EXISTS pg_temp.want_ids")
    cur.execute("CREATE TEMP TABLE want_ids (row_key TEXT, entity_type TEXT, entity_id BIGINT, system TEXT, "
                "namespace TEXT, external_id TEXT, method TEXT, confidence NUMERIC(4,3), review TEXT, evidence JSONB) "
                "ON COMMIT DROP")
    _copy(cur, "COPY want_ids FROM STDIN", (
        (r.row_key, r.entity_type, r.entity_id, r.system, r.namespace, r.external_id, r.method, r.confidence, r.review,
         json.dumps(dict(r.evidence), sort_keys=True, default=str)) for r in rows))
    cur.execute("CREATE INDEX ON want_ids (row_key)")


def _stage_aliases(cur: psycopg.Cursor[Any], rows: Iterable[AliasRow]) -> None:
    cur.execute("DROP TABLE IF EXISTS pg_temp.want_aliases")
    cur.execute("CREATE TEMP TABLE want_aliases (row_key TEXT, entity_type TEXT, entity_id BIGINT, alias TEXT, "
                "alias_key TEXT, alias_type TEXT, languages TEXT[], script TEXT, source TEXT, source_detail TEXT, "
                "via_external TEXT, confidence NUMERIC(4,3)) ON COMMIT DROP")
    _copy(cur, "COPY want_aliases FROM STDIN", (
        (a.row_key, a.entity_type, a.entity_id, a.alias, a.alias_key, a.alias_type, list(a.languages), a.script,
         a.source, a.source_detail, a.via_external, None if a.confidence is None else round(a.confidence, 3))
        for a in rows))
    cur.execute("CREATE INDEX ON want_aliases (row_key)")


def _stage_queue(cur: psycopg.Cursor[Any], items: Iterable[QueueItem]) -> None:
    cur.execute("DROP TABLE IF EXISTS pg_temp.want_queue")
    cur.execute("CREATE TEMP TABLE want_queue (item_key TEXT, kind TEXT, entity_type TEXT, entity_a BIGINT, "
                "entity_b BIGINT, system TEXT, namespace TEXT, external_id TEXT, score REAL, evidence JSONB) "
                "ON COMMIT DROP")
    _copy(cur, "COPY want_queue FROM STDIN", (
        (q.item_key, q.kind, q.entity_type, q.entity_a, q.entity_b, q.system, q.namespace, q.external_id, q.score,
         json.dumps(dict(q.evidence), sort_keys=True, default=str)) for q in items))


def _differences(cur: psycopg.Cursor[Any], source: str) -> dict[str, int]:
    """How many rows the staged sets would add and retire against what is in force for ``source``; and whether the queue
    differs from what the newest load of the source raised."""
    out: dict[str, int] = {}
    for kind, label, table, want in (("id", "ids", "entity_ids", "want_ids"),
                                     ("alias", "aliases", "entity_aliases", "want_aliases")):
        visible = _VISIBLE_SQL.format(table=table)
        cur.execute(f"SELECT count(DISTINCT w.row_key) FROM {want} w WHERE NOT EXISTS "
                    f"(SELECT 1 FROM ({visible}) v WHERE v.row_key = w.row_key)", {"source": source, "kind": kind})
        out[f"{label}_added"] = int(_one(cur))
        cur.execute(f"SELECT count(*) FROM ({visible}) v WHERE NOT EXISTS "
                    f"(SELECT 1 FROM {want} w WHERE w.row_key = v.row_key)", {"source": source, "kind": kind})
        out[f"{label}_retired"] = int(_one(cur))
    cur.execute("""
        WITH last AS (SELECT max(id) AS id FROM core.entity_id_loads WHERE source = %(s)s AND status = 'active'),
             seen AS (SELECT q.item_key FROM core.entity_identity_queue_seen s JOIN core.entity_identity_queue q
                        ON q.id = s.queue_id WHERE s.load_id = (SELECT id FROM last))
        SELECT (SELECT count(*) FROM (SELECT item_key FROM want_queue EXCEPT SELECT item_key FROM seen) a)
             + (SELECT count(*) FROM (SELECT item_key FROM seen EXCEPT SELECT item_key FROM want_queue) b)""",
                {"s": source})
    out["queue_changes"] = int(_one(cur))
    cur.execute("SELECT count(DISTINCT item_key) FROM want_queue")
    out["queue_items"] = int(_one(cur))
    return out


def _apply(cur: psycopg.Cursor[Any], source: str, load_id: int) -> None:
    for kind, table, want, cols in (
        ("id", "entity_ids", "want_ids",
         "row_key, entity_type, entity_id, system, namespace, external_id, method, confidence, review, evidence"),
        ("alias", "entity_aliases", "want_aliases",
         "row_key, entity_type, entity_id, alias, alias_key, alias_type, languages, script, source, source_detail, "
         "via_external, confidence"),
    ):
        visible = _VISIBLE_SQL.format(table=table)
        params = {"source": source, "kind": kind, "load": load_id}
        cur.execute(f"INSERT INTO core.entity_identity_retirements (load_id, kind, row_id) "
                    f"SELECT %(load)s, %(kind)s, v.id FROM ({visible}) v WHERE NOT EXISTS "
                    f"(SELECT 1 FROM {want} w WHERE w.row_key = v.row_key)", params)
        cur.execute(f"INSERT INTO core.{table} (load_id, {cols}) "
                    f"SELECT DISTINCT ON (w.row_key) %(load)s, {', '.join('w.' + c.strip() for c in cols.split(','))} "
                    f"FROM {want} w WHERE NOT EXISTS (SELECT 1 FROM ({visible}) v WHERE v.row_key = w.row_key) "
                    f"ORDER BY w.row_key", params)
    cur.execute("""
        INSERT INTO core.entity_identity_queue (item_key, source, kind, entity_type, entity_a, entity_b, system, namespace,
                                                external_id, score, evidence, rules_version, first_load_id)
        SELECT DISTINCT ON (item_key) item_key, %(s)s, kind, entity_type, entity_a, entity_b, system, namespace,
               external_id, score, evidence, %(v)s, %(load)s
          FROM want_queue ORDER BY item_key
        ON CONFLICT (item_key) DO NOTHING""", {"s": source, "v": rules.VERSION, "load": load_id})
    cur.execute("INSERT INTO core.entity_identity_queue_seen (queue_id, load_id) "
                "SELECT DISTINCT q.id, %(load)s FROM want_queue w JOIN core.entity_identity_queue q "
                "ON q.item_key = w.item_key", {"load": load_id})


def _one(cur: psycopg.Cursor[Any]) -> Any:
    row = cur.fetchone()
    return row[0] if row else None


def _new_load(cur: psycopg.Cursor[Any], *, source: str, release: str, release_sha256: str | None,
              files: Mapping[str, str], license_: str | None, actor: str) -> int:
    cur.execute("INSERT INTO core.entity_id_loads (source, release, release_sha256, files, license, rules_version, "
                "loaded_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (source, release, release_sha256, json.dumps(dict(files), sort_keys=True), license_, rules.VERSION,
                 actor))
    return int(_one(cur))


def load_reep(conn: psycopg.Connection[Any], data: ReepData, *, release: str, release_sha256: str,
              files: Mapping[str, str], as_of: date, actor: str,
              entities: Iterable[Ours] | None = None) -> LoadReport:
    """Load a verified release: the rules over all our linkable entities, the difference against what is in force.

    The same release under the same rules is loaded once: a second call writes nothing and says so."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id FROM core.entity_id_loads WHERE source = 'reep' AND release = %s AND rules_version = %s",
                    (release, rules.VERSION))
        existing = cur.fetchone()
        if existing is not None:
            return LoadReport(int(existing[0]), "reep", release, already_loaded=True)
        if entities is None:
            entities = [e for etype in LINKABLE for e in our_entities(conn, etype)]
        plan = rules.plan_links(entities, data, as_of=as_of)
        _stage_ids(cur, plan.ids)
        _stage_aliases(cur, plan.aliases)
        _stage_queue(cur, plan.queue)
        counts = _differences(cur, "reep")
        load_id = _new_load(cur, source="reep", release=release, release_sha256=release_sha256, files=files,
                            license_=LICENSE, actor=actor)
        _apply(cur, "reep", load_id)
        counts["rows_read"] = sum(data.rows_read.values())
        cur.execute("UPDATE core.entity_id_loads SET counts = %s WHERE id = %s",
                    (json.dumps({**counts, **dict(plan.stats)}, sort_keys=True), load_id))
    return LoadReport(load_id, "reep", release, counts=counts, stats=dict(plan.stats))


def own_aliases(conn: psycopg.Connection[Any]) -> Iterator[AliasRow]:
    """Our own names, and the two old alias tables, as alias rows (AD-H02): absorbed, not a third way."""

    def row(etype: str, eid: int, text: str, kind: str, source: str, detail: str = "") -> AliasRow | None:
        key = nm.alias_key(text)
        if not key:
            return None
        return AliasRow(etype, eid, text, key, kind, (), nm.script_of(text), source, detail, None, None)

    for etype in ("player", "coach", "team", "competition", "venue", "referee"):
        for e in our_entities(conn, etype):
            if not e.names:
                continue
            source = "core.referees" if etype == "referee" else "api_football"
            first = row(etype, e.entity_id, e.names[0], "official", source)
            if first is not None:
                yield first
            for other in e.names[1:]:
                if nm.alias_key(other) == nm.alias_key(e.names[0]):
                    continue
                kind = "full" if etype in rules.PERSONS else (
                    "code" if len(other) <= 4 and other.isupper() else "short")
                r = row(etype, e.entity_id, other, kind, source)
                if r is not None:
                    yield r
    with conn.cursor(name="identity_team_aliases", row_factory=tuple_row) as cur:
        cur.execute("SELECT team_id, alias, source FROM core.team_aliases ORDER BY source, alias")
        for team_id, alias, src in cur:
            r = row("team", int(team_id), str(alias), "alternative", "core.team_aliases", str(src))
            if r is not None:
                yield r
    with conn.cursor(name="identity_referee_aliases", row_factory=tuple_row) as cur:
        cur.execute("SELECT referee_id, display, scope FROM core.referee_aliases ORDER BY id")
        for referee_id, display, scope in cur:
            r = row("referee", int(referee_id), str(display), "alternative", "core.referee_aliases", str(scope))
            if r is not None:
                yield r


def sync_core(conn: psycopg.Connection[Any], *, actor: str, at: datetime | None = None) -> LoadReport:
    """Our names, the old alias tables and the homonym queue, as a load of source ``core``: written only when something
    changed, so a second run writes nothing."""
    at = at or datetime.now(UTC)
    release = "sync-" + at.strftime("%Y%m%dT%H%M%S.%fZ")
    with conn.cursor(row_factory=tuple_row) as cur:
        _stage_ids(cur, ())
        _stage_aliases(cur, own_aliases(conn))
        homonyms, stats = rules.plan_homonyms(our_entities(conn, "player"))
        _stage_queue(cur, homonyms)
        counts = _differences(cur, "core")
        if not (counts["aliases_added"] or counts["aliases_retired"] or counts["queue_changes"]):
            return LoadReport(None, "core", release, already_loaded=True, counts=counts, stats=stats)
        load_id = _new_load(cur, source="core", release=release, release_sha256=None, files={}, license_=None,
                            actor=actor)
        _apply(cur, "core", load_id)
        cur.execute("UPDATE core.entity_id_loads SET counts = %s WHERE id = %s",
                    (json.dumps({**counts, **stats}, sort_keys=True), load_id))
    return LoadReport(load_id, "core", release, counts=counts, stats=stats)


def retire_load(conn: psycopg.Connection[Any], load_id: int, *, actor: str, note: str) -> bool:
    """Take a load back: what it added is hidden, what it retired comes back. False if it was not active."""
    with conn.cursor() as cur:
        cur.execute("UPDATE core.entity_id_loads SET status = 'retired', retired_by = %s, retired_at = now(), "
                    "retire_note = %s WHERE id = %s AND status = 'active'", (actor, note, load_id))
        return cur.rowcount == 1


# ── decisions ────────────────────────────────────────────────────────────────────────────────────────────────────────

QUEUE_ACTIONS: Final[Mapping[str, frozenset[str]]] = {
    "bridge_conflict": frozenset({"dismiss"}),
    "name_mismatch": frozenset({"accept", "reject"}),
    "shared_external": frozenset({"same", "different", "keep_a", "keep_b"}),
    "possible_duplicate": frozenset({"same", "different"}),
    "near_birth_date": frozenset({"same", "different"}),
}
"""What a person may answer to each kind of question. ``same`` on a shared external id: the two ids are one person, both
get it; ``different``: neither; ``keep_a`` / ``keep_b``: only that one."""


class DecisionError(ValueError):
    pass


def _links_of(cur: psycopg.Cursor[Any], entity_type: str, entity_id: int, *, only: tuple[str, str, str] | None = None,
              via: str | None = None) -> list[tuple[str, str, str]]:
    """The links in force of one entity (all, the one ``only`` names, or those that ride on Reep id ``via``)."""
    cur.execute("SELECT system, namespace, external_id, evidence FROM core.entity_ids_live "
                "WHERE entity_type = %s AND entity_id = %s ORDER BY system, namespace, external_id",
                (entity_type, entity_id))
    out = []
    for system, namespace, external, evidence in cur.fetchall():
        key = (str(system), str(namespace), str(external))
        if only is not None and key != only:
            continue
        if via is not None and not (key == ("reep", "", via) or (evidence or {}).get("via") == via):
            continue
        out.append(key)
    return out


def _write(cur: psycopg.Cursor[Any], action: str, actor: str, note: str | None, *, queue_id: int | None = None,
           link: tuple[str, int, str, str, str] | None = None, undoes: int | None = None) -> int:
    etype, eid, system, namespace, external = link if link is not None else (None, None, None, None, None)
    cur.execute("INSERT INTO core.entity_identity_decisions (queue_id, action, entity_type, entity_id, system, namespace, "
                "external_id, undoes, actor, note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (queue_id, action, etype, eid, system, namespace, external, undoes, actor, note))
    return int(_one(cur))


def decide(conn: psycopg.Connection[Any], queue_id: int, action: str, *, actor: str, note: str | None = None) -> list[int]:
    """Answer an open question of the queue; the decision rows written."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT kind, entity_type, entity_a, entity_b, system, namespace, external_id "
                    "FROM core.entity_identity_queue_open WHERE id = %s", (queue_id,))
        item = cur.fetchone()
        if item is None:
            raise DecisionError(f"queue item {queue_id} is not open")
        kind, etype, a, b, system, namespace, external = item
        if action not in QUEUE_ACTIONS[str(kind)]:
            raise DecisionError(f"{kind} takes {sorted(QUEUE_ACTIONS[str(kind)])}, not {action!r}")
        written: list[int] = []
        if kind == "name_mismatch":
            for key in _links_of(cur, etype, int(a), via=str(external)):
                written.append(_write(cur, action, actor, note, queue_id=queue_id, link=(etype, int(a), *key)))
        elif kind == "shared_external":
            shared = (str(system), str(namespace), str(external))
            keep = {"same": (True, True), "different": (False, False), "keep_a": (True, False),
                    "keep_b": (False, True)}[action]
            reep_id = str(external) if system == "reep" else None
            for entity, kept in ((int(a), keep[0]), (int(b), keep[1])):
                keys = (_links_of(cur, etype, entity, via=reep_id) if reep_id
                        else _links_of(cur, etype, entity, only=shared))
                for key in keys:
                    written.append(_write(cur, "accept" if kept else "reject", actor, note, queue_id=queue_id,
                                          link=(etype, entity, *key)))
        if not written:
            written.append(_write(cur, action if action in ("same", "different", "dismiss") else "dismiss", actor,
                                  note, queue_id=queue_id))
    return written


def decide_link(conn: psycopg.Connection[Any], link: tuple[str, int, str, str, str], action: str, *, actor: str,
                note: str | None = None) -> int:
    """Accept or reject one link directly (a wrong link nobody queued)."""
    if action not in ("accept", "reject"):
        raise DecisionError("a link is accepted or rejected")
    with conn.cursor(row_factory=tuple_row) as cur:
        etype, eid, system, namespace, external = link
        if (system, namespace, external) not in _links_of(cur, etype, eid):
            raise DecisionError(f"{link} is not a link in force")
        return _write(cur, action, actor, note, link=link)


def undo(conn: psycopg.Connection[Any], *, actor: str, decision_id: int | None = None, queue_id: int | None = None,
         note: str | None = None) -> list[int]:
    """Take back one decision, or every decision in force on a queue item."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("""
            SELECT d.id FROM core.entity_identity_decisions d
             WHERE d.action <> 'undo' AND (d.id = %s OR d.queue_id = %s)
               AND NOT EXISTS (SELECT 1 FROM core.entity_identity_decisions u WHERE u.undoes = d.id)
             ORDER BY d.id""", (decision_id, queue_id))
        targets = [int(r[0]) for r in cur.fetchall()]
        if not targets:
            raise DecisionError("nothing to undo")
        return [_write(cur, "undo", actor, note, undoes=t) for t in targets]


# ── AD-H09: one player key ───────────────────────────────────────────────────────────────────────────────────────────

CREATE_MISSING_PLAYERS_SQL: Final = """
INSERT INTO core.players (provider_player_id, name, position, source_payload_hash, source_fetched_at)
SELECT DISTINCT ON (s.provider_player_id) s.provider_player_id, btrim(s.player_name), s.position,
       (SELECT p.hash FROM raw.ingestion_payloads p WHERE p.hash = s.payload_hash), s.last_seen_at
  FROM core.squad_members s
 WHERE s.player_id IS NULL AND s.provider_player_id > 0 AND length(btrim(coalesce(s.player_name, ''))) > 0
   AND NOT EXISTS (SELECT 1 FROM core.players p WHERE p.provider_player_id = s.provider_player_id)
 ORDER BY s.provider_player_id, s.last_seen_at DESC
ON CONFLICT (provider_player_id) DO NOTHING
"""
"""An identity-only row (id, name, position: what a squad carries) for a squad player the provider never named in a match.
The same kind of row ``fbi.ingestion.identity`` writes from a line-up; the profile sweep fills the rest later."""

_FILL_SQL: Final[Mapping[str, str]] = {
    "core.squad_members": """
        UPDATE core.squad_members s SET player_id = p.id FROM core.players p
         WHERE p.provider_player_id = s.provider_player_id
           AND (s.team_id, s.provider_player_id) IN (
                SELECT x.team_id, x.provider_player_id FROM core.squad_members x
                 WHERE x.player_id IS NULL AND x.provider_player_id > 0
                   AND EXISTS (SELECT 1 FROM core.players q WHERE q.provider_player_id = x.provider_player_id)
                 LIMIT %(batch)s)""",
}
"""Squad rows: one statement."""

_EVIDENCE_FILL_SQL: Final[tuple[str, ...]] = (
    """
        UPDATE ai.evidence e SET player_id = p.id FROM core.players p
         WHERE p.provider_player_id = e.provider_player_id
           AND e.id IN (SELECT x.id FROM ai.evidence x
                         WHERE x.subject_type IS NULL AND x.player_id IS NULL AND x.provider_player_id > 0
                           AND EXISTS (SELECT 1 FROM core.players q WHERE q.provider_player_id = x.provider_player_id)
                         ORDER BY x.id LIMIT %(batch)s)""",
    """
        UPDATE ai.evidence e SET player_id = p.id FROM core.players p
         WHERE p.provider_player_id = e.provider_player_id
           AND e.id IN (SELECT x.id FROM ai.evidence x
                         WHERE x.subject_type IS NOT NULL AND x.player_id IS NULL AND x.provider_player_id > 0
                           AND EXISTS (SELECT 1 FROM core.players q WHERE q.provider_player_id = x.provider_player_id)
                         ORDER BY x.id LIMIT %(batch)s)""",
)
"""The evidence rows, v1's items (``subject_type IS NULL``) and research v2's claims (``IS NOT NULL``) each by its own statement:
the key is filled on both kinds on purpose and no claim's content is read (``tests/unit/test_typed_evidence_guard.py``, OWN_READERS)."""


@dataclass(slots=True)
class KeysReport:
    players_created: int = 0
    filled: dict[str, int] = field(default_factory=dict)
    left: dict[str, int] = field(default_factory=dict)


def player_key_gaps(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Rows that name a player and still have no ``player_id``, per table (the criterion: 0)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        out = {}
        for table in (*_FILL_SQL, "ai.evidence"):
            cur.execute(f"SELECT count(*) FROM {table} WHERE provider_player_id > 0 AND player_id IS NULL")
            out[table] = int(_one(cur))
        return out


def backfill_player_keys(conn: psycopg.Connection[Any], *, batch: int = 2000, create_missing: bool = False,
                         max_batches: int | None = None) -> KeysReport:
    """Fill ``player_id`` on the old rows, one committed batch at a time (``lock_timeout`` 3 s: a batch that would wait for
    the ingestion gives way and the next run takes it). ``create_missing`` first gives a ``core.players`` row to the squad
    players that have none (identity only)."""
    report = KeysReport()
    with conn.cursor() as cur:
        if create_missing:
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute(CREATE_MISSING_PLAYERS_SQL)
            report.players_created = max(cur.rowcount, 0)
            conn.commit()
        work = [*((t, s) for t, s in _FILL_SQL.items()), *(("ai.evidence", s) for s in _EVIDENCE_FILL_SQL)]
        for table, sql in work:
            done = 0
            n = 0
            while max_batches is None or n < max_batches:
                cur.execute("SET LOCAL lock_timeout = '3s'")
                cur.execute(sql, {"batch": batch})
                changed = max(cur.rowcount, 0)
                conn.commit()
                n += 1
                done += changed
                if changed == 0:
                    break
            report.filled[table] = report.filled.get(table, 0) + done
    report.left = player_key_gaps(conn)
    return report


# ── what is in force ─────────────────────────────────────────────────────────────────────────────────────────────────

def coverage(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """Read-only: what the tables hold now, per entity type and system; the queue; the aliases; the player key."""
    out: dict[str, Any] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        entities = {}
        for etype, (table, _col) in TABLES.items():
            cur.execute(f"SELECT count(*) FROM {table}" + (" WHERE status = 'active'" if etype == "referee" else ""))
            entities[etype] = int(_one(cur))
        out["entities"] = entities
        cur.execute("SELECT entity_type, system, state, count(DISTINCT entity_id) FROM core.entity_ids_live "
                    "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3")
        out["linked"] = [list(r) for r in cur.fetchall()]
        cur.execute("SELECT kind, count(*) FROM core.entity_identity_queue_open GROUP BY 1 ORDER BY 1")
        out["queue_open"] = dict(cur.fetchall())
        cur.execute("SELECT entity_type, source, count(*) FROM core.entity_aliases_live GROUP BY 1, 2 ORDER BY 1, 2")
        out["aliases"] = [list(r) for r in cur.fetchall()]
        cur.execute("SELECT id, source, release, status, loaded_at, counts FROM core.entity_id_loads ORDER BY id DESC "
                    "LIMIT 10")
        out["loads"] = [list(r) for r in cur.fetchall()]
    out["player_key_gaps"] = player_key_gaps(conn)
    return out


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    value: int
    ok: bool
    detail: str = ""


def audit(conn: psycopg.Connection[Any]) -> list[Check]:
    """The invariants and criteria of AD-H01 / H02 / H09 that can be checked without a person."""
    checks: list[Check] = []
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("""SELECT count(*) FROM (SELECT entity_type, external_id FROM core.entity_ids_live
                        WHERE system = 'reep' AND state = 'accepted' GROUP BY 1, 2 HAVING count(DISTINCT entity_id) > 1) x""")
        n = int(_one(cur))
        checks.append(Check("reep id accepted for two of our entities", n, n == 0))
        cur.execute("""SELECT count(*) FROM (SELECT entity_type, entity_id FROM core.entity_ids_live
                        WHERE system = 'reep' AND state = 'accepted' GROUP BY 1, 2 HAVING count(DISTINCT external_id) > 1) x""")
        n = int(_one(cur))
        checks.append(Check("entity (API-Football id) with two accepted Reep ids", n, n == 0))
        cur.execute("""SELECT count(*) FROM (SELECT entity_type, system, namespace, external_id FROM core.entity_ids_live
                        WHERE state = 'accepted' GROUP BY 1, 2, 3, 4 HAVING count(DISTINCT entity_id) > 1) x""")
        n = int(_one(cur))
        checks.append(Check("external id accepted for two entities", n, n == 0))
        for table, source in (("core.team_aliases", "core.team_aliases"), ("core.referee_aliases", "core.referee_aliases")):
            cur.execute(f"SELECT count(*) FROM {table}")
            old = int(_one(cur))
            cur.execute("SELECT count(*) FROM core.entity_aliases_live WHERE source = %s", (source,))
            new = int(_one(cur))
            checks.append(Check(f"aliases of {table} in core.entity_aliases", new, new == old, f"{new} of {old}"))
        cur.execute("""SELECT count(*) FROM (SELECT DISTINCT entity_type FROM core.entity_aliases_live
                        WHERE alias_type = 'official') x""")
        n = int(_one(cur))
        checks.append(Check("searchable entity types with an official name", n, n == len(rules.ENTITY_TYPES)))
    for table, gap in player_key_gaps(conn).items():
        checks.append(Check(f"{table} rows naming a player without player_id", gap, gap == 0))
    return checks


def open_queue(conn: psycopg.Connection[Any], *, kind: str | None = None, limit: int = 30) -> Sequence[tuple[Any, ...]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id, kind, entity_type, entity_a, entity_b, system, namespace, external_id, score, evidence "
                    "FROM core.entity_identity_queue_open WHERE %(k)s::text IS NULL OR kind = %(k)s "
                    "ORDER BY score DESC, id LIMIT %(n)s", {"k": kind, "n": limit})
        return cur.fetchall()
