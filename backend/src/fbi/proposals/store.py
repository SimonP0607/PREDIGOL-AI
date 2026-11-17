"""The register of proposals and signatures (IA-139, AD-K07): what ``scripts/ia_proposals.py`` reads and writes in revision 0165's tables.

Every function is run by a person at the owner's command; no job, route or agent imports this module (``tests/unit/test_proposals.py``).
A write refuses what ``fbi.proposals.problems`` / ``sign_problems`` refuse, and the database refuses the same again. Nothing here changes a
switch, a threshold, a weight or a model: ``record`` only says that a signed change took effect (or was taken back) when the owner did it."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.proposals import SIGNED, Proposal, Row, problems, sign_problems

INSERT_SQL: Final = """
INSERT INTO ai.change_proposals (version, kind, target, current_version, proposed_version, rollback_to, change, evidence, evidence_refs,
                                 evidence_hash, proposed_by, reason, code_version)
VALUES (%(version)s, %(kind)s, %(target)s, %(current)s, %(proposed)s, %(current)s, %(change)s, %(evidence)s, %(refs)s, %(hash)s, %(by)s,
        %(reason)s, %(code)s)
ON CONFLICT ON CONSTRAINT change_proposals_once DO NOTHING
RETURNING id
"""
LIST_SQL: Final = """
SELECT p.id, p.version, p.kind, p.target, p.current_version, p.proposed_version, p.change, p.evidence, p.evidence_refs, p.reason,
       p.proposed_by, s.decision,
       COALESCE((SELECT array_agg(a.kind ORDER BY a.id) FROM ai.change_applications a WHERE a.proposal_id = p.id), '{}') AS applied
  FROM ai.change_proposals p LEFT JOIN ai.change_signatures s ON s.proposal_id = p.id
 WHERE (%(id)s::bigint IS NULL OR p.id = %(id)s)
 ORDER BY p.id DESC LIMIT %(limit)s
"""
SIGN_SQL: Final = """
INSERT INTO ai.change_signatures (proposal_id, evidence_hash, decision, signed_by, signature)
VALUES (%(id)s, %(hash)s, %(decision)s, 'owner', %(signature)s) RETURNING id
"""
SIGNATURE_SQL: Final = "SELECT id, decision FROM ai.change_signatures WHERE proposal_id = %(id)s"
RECORD_SQL: Final = """
INSERT INTO ai.change_applications (proposal_id, signature_id, kind, version, recorded_by, note)
VALUES (%(id)s, %(signature)s, %(kind)s, %(version)s, 'owner', %(note)s) RETURNING id
"""
UNSIGNED_SQL: Final = """
SELECT count(*) FROM ai.change_applications a
  LEFT JOIN ai.change_signatures s ON s.id = a.signature_id AND s.proposal_id = a.proposal_id AND s.decision = 'firmada'
 WHERE s.id IS NULL
"""
"""Applications without a signature firmada of the same proposal: the criterion of AD-K07 is 0 (the foreign key makes it so)."""


def register(conn: psycopg.Connection[Any], p: Proposal, *, code_version: str | None = None) -> int | None:
    """Append one proposal; None when the same one (kind, target, version, evidence) is already there."""
    found = problems(p)
    if found:
        raise ValueError("; ".join(found))
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {"version": p.version, "kind": p.kind, "target": p.target, "current": p.current_version,
                                 "proposed": p.proposed_version, "change": Jsonb(p.change), "evidence": Jsonb(p.evidence),
                                 "refs": Jsonb(list(p.evidence_refs)), "hash": p.hash, "by": p.proposed_by, "reason": p.reason.strip(),
                                 "code": code_version})
        row = cur.fetchone()
    return None if row is None else int(row[0])


def _proposal(r: dict[str, Any]) -> Proposal:
    return Proposal(str(r["kind"]), str(r["target"]), str(r["current_version"]), str(r["proposed_version"]), dict(r["change"]),
                    dict(r["evidence"]), tuple(dict(x) for x in r["evidence_refs"]), str(r["reason"]), r["proposed_by"], str(r["version"]))


def rows(conn: psycopg.Connection[Any], *, proposal_id: int | None = None, limit: int = 50) -> list[Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LIST_SQL, {"id": proposal_id, "limit": limit})
        return [Row(int(r["id"]), _proposal(r), r["decision"], tuple(r["applied"] or ())) for r in cur.fetchall()]


def sign(conn: psycopg.Connection[Any], proposal_id: int, *, decision: str, signature: str, seen_hash: str) -> int:
    """The owner's decision on a proposal, bound to the evidence hash they were shown."""
    found = rows(conn, proposal_id=proposal_id, limit=1)
    if not found:
        raise ValueError(f"no proposal {proposal_id}")
    issues = sign_problems(found[0].proposal, decision, signature, seen_hash=seen_hash)
    if found[0].decision is not None:
        issues.append(f"proposal {proposal_id} already has the owner's decision ({found[0].decision}): a change of mind is a new proposal")
    if issues:
        raise ValueError("; ".join(issues))
    with conn.cursor() as cur:
        cur.execute(SIGN_SQL, {"id": proposal_id, "hash": seen_hash, "decision": decision, "signature": signature.strip()})
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def record(conn: psycopg.Connection[Any], proposal_id: int, *, kind: str, note: str) -> int:
    """That a SIGNED proposal took effect (``aplicada``: its proposed version) or was taken back (``revertida``: its ``rollback_to``)."""
    found = rows(conn, proposal_id=proposal_id, limit=1)
    if not found:
        raise ValueError(f"no proposal {proposal_id}")
    p = found[0]
    if p.decision != SIGNED:
        raise ValueError(f"proposal {proposal_id} is not signed by the owner: nothing is applied without a signature")
    if kind not in ("aplicada", "revertida"):
        raise ValueError(f"kind is 'aplicada' or 'revertida', not {kind!r}")
    if kind == "revertida" and "aplicada" not in p.applied:
        raise ValueError("only what was applied can be taken back")
    with conn.cursor() as cur:
        cur.execute(SIGNATURE_SQL, {"id": proposal_id})
        sig = cur.fetchone()
        assert sig is not None
        version = p.proposal.proposed_version if kind == "aplicada" else p.proposal.rollback_to
        cur.execute(RECORD_SQL, {"id": proposal_id, "signature": int(sig[0]), "kind": kind, "version": version, "note": note.strip()})
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def summary(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """How many proposals are in each state, and how many applications lack a signature (always 0)."""
    counts: dict[str, int] = defaultdict(int)
    for r in rows(conn, limit=10_000):
        counts[r.status] += 1
    with conn.cursor() as cur:
        cur.execute(UNSIGNED_SQL)
        unsigned = cur.fetchone()
    return {"by_status": dict(counts), "applied_without_signature": int(unsigned[0]) if unsigned else 0}


__all__ = ["INSERT_SQL", "LIST_SQL", "RECORD_SQL", "SIGN_SQL", "UNSIGNED_SQL", "record", "register", "rows", "sign", "summary"]
