"""The readers of the labelled bank (IA-030): the candidates of each bank for a window, and the facts a sampled sentence cites.

Read only: every statement is a SELECT, and the script opens its connection with ``default_transaction_read_only``. Nothing here samples or
scores (that is ``fbi.ai.label_bank``, pure).

The bank reads BOTH kinds of evidence on purpose - the items of ``extract-v1`` (no ``subject_type``) and the claims of research v2
(``extract-v2``, ``extract-v3``: a ``subject_type``) - each by its own statement, because measuring each extractor against the page it cites is
the point (``tests/unit/test_typed_evidence_guard.py`` lists it among the readers that choose a kind on purpose). What it reads goes to a sheet a
person labels and nowhere else: no packet, card, decision or pick imports this module."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import label_bank

FactsOf = Callable[..., Mapping[str, Mapping[str, Any]]]
"""How the facts of a packet are read for its references: ``facts_of(conn, content=, home_id=, away_id=, kickoff=, data_at=)`` -> ref ->
{code, params}. Injected by the caller (``scripts/ia_label_bank.py`` gives the chronicle's own ``fbi.api.services.story.story_of``): the AI
package never imports the API layer (``tests/unit/test_architecture.py``)."""

_COLUMNS: Final = """
SELECT e.id, e.kind, e.claim, e.claim_type, e.subject_type, e.subject_id, e.provider_player_id, e.team_id, e.fixture_id,
       e.source_url, e.source_domain, e.source_name, e.published_at, e.retrieved_at, e.status,
       e.attributes->>'extract_version' AS extract_version, e.attributes->>'assertion' AS assertion,
       e.attributes->>'applies_to' AS applies_to, e.attributes->>'player_name' AS player_name,
       e.attributes->>'result_title' AS result_title,
       coalesce(e.attributes->>'instruction_like', 'false') = 'true' AS instruction_like,
       t.name AS team_name, th.name AS home_name, ta.name AS away_name, f.kickoff_at"""
_JOINS: Final = """
  LEFT JOIN core.teams t ON t.id = e.team_id
  LEFT JOIN core.fixtures f ON f.id = e.fixture_id
  LEFT JOIN core.teams th ON th.id = f.home_team_id
  LEFT JOIN core.teams ta ON ta.id = f.away_team_id"""
_WINDOW: Final = """
   AND e.origin = 'web' AND e.attributes ? 'extract_version'
   AND e.retrieved_at >= %(since)s AND e.retrieved_at < %(until)s
   AND (%(versions)s::text[] IS NULL OR e.attributes->>'extract_version' = ANY(%(versions)s::text[]))
 ORDER BY e.id"""

CLAIMS_V1_SQL: Final = f"{_COLUMNS}\n  FROM ai.evidence e{_JOINS}\n WHERE e.subject_type IS NULL{_WINDOW}"
"""The items ``extract-v1`` wrote from web pages in the window (v1 never writes a subject)."""
CLAIMS_TYPED_SQL: Final = f"{_COLUMNS}\n  FROM ai.evidence e{_JOINS}\n WHERE e.subject_type IS NOT NULL{_WINDOW}"
"""The claims research v2's extractor (``extract-v2``, ``extract-v3``) wrote in the window. The provider's own items (``origin = 'provider'``)
are not a model's and are in neither statement."""

SENTENCES_SQL: Final = """
SELECT r.id AS review_id, r.fixture_id, r.narrative_id, r.version, r.created_at, r.status AS review_status, r.outcome, r.packet_id,
       it.value AS item, f.kickoff_at, th.name AS home_name, ta.name AS away_name
  FROM ai.chronicle_reviews r
  CROSS JOIN LATERAL jsonb_array_elements(r.items) AS it(value)
  JOIN core.fixtures f ON f.id = r.fixture_id
  LEFT JOIN core.teams th ON th.id = f.home_team_id
  LEFT JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE r.created_at >= %(since)s AND r.created_at < %(until)s
   AND r.id = (SELECT x.id FROM ai.chronicle_reviews x WHERE x.narrative_id = r.narrative_id ORDER BY x.created_at DESC, x.id DESC LIMIT 1)
 ORDER BY r.id
"""
"""Every sentence of the newest review of each chronicle reviewed in the window, with the review's verdict and checks."""

PACKET_SQL: Final = """
SELECT pk.content, pk.as_of, f.kickoff_at, f.home_team_id, f.away_team_id
  FROM ai.match_packets pk JOIN core.fixtures f ON f.id = pk.fixture_id WHERE pk.id = %(packet)s
"""
"""The packet a chronicle was written from and its moment (``as_of``: the narrative's ``data_at``), which never change."""

_CITED: Final = "SELECT id, kind, claim, status, source_url, source_domain, attributes->>'player_name' AS player_name"
CITED_V1_SQL: Final = f"{_CITED} FROM ai.evidence WHERE id = ANY(%(ids)s) AND subject_type IS NULL"
CITED_TYPED_SQL: Final = f"{_CITED} FROM ai.evidence WHERE id = ANY(%(ids)s) AND subject_type IS NOT NULL"
"""The news items a sampled sentence CITED, by id, of each kind."""


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def claims(conn: psycopg.Connection[Any], *, since: datetime, until: datetime,
           versions: Sequence[str] | None = None) -> list[label_bank.Candidate]:
    """The candidates of the claims bank: the items of v1 and the claims of research v2, each read by its own statement."""
    params = {"since": since, "until": until, "versions": None if not versions else list(versions)}
    rows = [*_rows(conn, CLAIMS_V1_SQL, params), *_rows(conn, CLAIMS_TYPED_SQL, params)]
    return [label_bank.claim_candidate(r) for r in sorted(rows, key=lambda r: int(r["id"]))]


def sentences(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> list[label_bank.Candidate]:
    return [label_bank.sentence_candidate(r) for r in _rows(conn, SENTENCES_SQL, {"since": since, "until": until})]


def cite(conn: psycopg.Connection[Any], rows: Sequence[MutableMapping[str, Any]], facts_of: FactsOf) -> None:
    """Fill ``cited`` of the sampled sentences: each reference with the fact it pointed to when the chronicle was written - a ``P:`` reference
    as the story of its packet tells it (``facts_of``: the chronicle's own function), an ``E:`` reference as the piece of evidence (its claim,
    its kind, its page). A reference that cannot be found is said so; nothing is guessed."""
    ids = sorted({int(ref[2:]) for r in rows for ref in r.get("refs") or [] if isinstance(ref, str) and ref.startswith("E:") and ref[2:].isdigit()})
    evidence: dict[int, dict[str, Any]] = {}
    if ids:
        for sql in (CITED_V1_SQL, CITED_TYPED_SQL):
            evidence |= {int(e["id"]): e for e in _rows(conn, sql, {"ids": ids})}
    stories: dict[int, dict[str, dict[str, Any]]] = {}
    for r in rows:
        packet = r.get("packet_id")
        facts: dict[str, dict[str, Any]] = {}
        if packet is not None:
            if int(packet) not in stories:
                found = _rows(conn, PACKET_SQL, {"packet": int(packet)})
                stories[int(packet)] = {} if not found or not isinstance(found[0]["content"], dict) else {
                    str(k): dict(v) for k, v in facts_of(conn, content=found[0]["content"], home_id=int(found[0]["home_team_id"]),
                                                         away_id=int(found[0]["away_team_id"]), kickoff=found[0]["kickoff_at"],
                                                         data_at=found[0]["as_of"]).items()}
            facts = stories[int(packet)]
        cited: list[dict[str, Any]] = []
        for ref in r.get("refs") or []:
            ref = str(ref)
            if ref.startswith("E:") and ref[2:].isdigit():
                e = evidence.get(int(ref[2:]))
                cited.append({"ref": ref, "found": e is not None} | ({} if e is None else {
                    "kind": e["kind"], "claim": " ".join(str(e["claim"] or "").split()), "status": e["status"], "player": e["player_name"],
                    "source_url": e["source_url"], "source_domain": e["source_domain"]}))
            else:
                fact = facts.get(ref)
                cited.append({"ref": ref, "found": fact is not None} | ({} if fact is None else fact))
        r["cited"] = cited
