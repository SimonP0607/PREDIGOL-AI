"""The gate of the extraction measured against people's labels (IA-127, plan piece AD-C09): ``extract_protocol`` in ``ai.feature_gates``.

    sign      THE OWNER'S ACTION: the protocol ``AD-C09`` (``extract-protocol-v1``) as it is registered, signed before the first measurement
              (``decided_by = 'owner'``, ``passed = false``, ``kind = 'protocol-signature'``). Without ``confirm_owner``: a preview, nothing
              written. No code path signs on its own.
    record    the verdict of one measurement of the bank (``fbi.ai.page_bank.score``) as ONE new row (``decided_by = 'script'``,
              ``kind = 'measurement'``), refused without a signature of the protocol as it is now (its fingerprint). ``passed`` is true only
              when the arm that would replace v1 (``page_bank.CANDIDATE_ARM``, the unified road) says PASA. Whatever the verdict, a row.
    status    the signature in force, and the newest verdict.

ROW 17 STAYS. Nothing here reads or writes the gate ``research_v2``: its newest row (row 17, NO PASA, 12-nov) is still what
``fbi.ai.gates.research_mode`` reads, and the panel shows it as it was. And nothing switches on a row of ``extract_protocol``: no switch,
threshold, gate or reader reads it but this module and the panel (``tests/unit/test_extract_protocol_ia127.py`` holds it). A verdict is
annulled by another signed row; no row is deleted (the table refuses it).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import page_bank
from fbi.ai.gates import INSERT_SQL, evidence_hash
from fbi.research import protocol

GATE: Final = "extract_protocol"
SIGNATURE_KIND: Final = "protocol-signature"
MEASUREMENT_KIND: Final = "measurement"
THRESHOLDS: Final[dict[str, Any]] = {"pages": page_bank.QUOTA, "double_share": page_bank.DOUBLE_SHARE, "review": page_bank.REVIEW,
                                     "review_min": page_bank.REVIEW_MIN, "recall_min": page_bank.RECALL_MIN,
                                     "agreement_min": page_bank.AGREEMENT_MIN, "arms": list(page_bank.ARMS),
                                     "candidate_arm": page_bank.CANDIDATE_ARM, "alpha": page_bank.ALPHA}

SIGNATURE_SQL: Final = """
SELECT id, at, evidence FROM ai.feature_gates
 WHERE gate = 'extract_protocol' AND decided_by = 'owner' AND evidence ->> 'kind' = 'protocol-signature'
 ORDER BY at DESC, id DESC LIMIT 1
"""
NEWEST_SQL: Final = "SELECT id, at, passed, evidence FROM ai.feature_gates WHERE gate = 'extract_protocol' ORDER BY at DESC, id DESC LIMIT 1"


def stamp() -> dict[str, Any]:
    return protocol.stamp(page_bank.PROTOCOL)


def _insert(conn: psycopg.Connection[Any], *, passed: bool, evidence: dict[str, Any], at: datetime, decided_by: str,
            code_version: str | None) -> int:
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, (GATE, at, passed, Jsonb(evidence), evidence_hash(evidence), decided_by, code_version))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def signature(conn: psycopg.Connection[Any]) -> dict[str, Any] | None:
    """The newest signature of the owner, and whether it covers the protocol as it is registered now."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SIGNATURE_SQL)
        row = cur.fetchone()
    if row is None:
        return None
    signed = (row["evidence"] or {}).get("protocol") or {}
    return {"row": int(row["id"]), "at": row["at"].isoformat(), "fingerprint": signed.get("fingerprint"),
            "valid": signed.get("fingerprint") == stamp()["fingerprint"] and (row["evidence"] or {}).get("thresholds") == THRESHOLDS}


def sign(conn: psycopg.Connection[Any], *, reason: str, confirm_owner: bool, at: datetime, code_version: str | None = None) -> dict[str, Any]:
    """THE OWNER'S ACTION. Without ``confirm_owner``: what would be written, and nothing written. With it: one row (the caller commits)."""
    signed = stamp()
    evidence: dict[str, Any] = {"kind": SIGNATURE_KIND, "protocol": signed, "thresholds": THRESHOLDS, "bank": page_bank.BANK_VERSION,
                "reason": reason.strip()[:500], "row_17": "research_v2 se conserva tal cual (NO PASA, 12-nov)"}
    if not confirm_owner:
        return {"written": False, "evidence": evidence,
                "lines": ["VISTA PREVIA (sin --confirm-owner): no se ha escrito nada.",
                          f"Se firmaría el protocolo {page_bank.PROTOCOL} ({signed['version']}, huella "
                          f"{str(signed['fingerprint'])[:12]}…) antes de la primera medición."]}
    if not reason.strip():
        raise ValueError("the owner's signature says why (--reason)")
    row = _insert(conn, passed=False, evidence=evidence, at=at, decided_by="owner", code_version=code_version)
    return {"written": True, "row": row, "evidence": evidence}


def record(conn: psycopg.Connection[Any], report: Mapping[str, Any], *, at: datetime, code_version: str | None = None) -> dict[str, Any]:
    """The verdict of one measurement as one row of the gate (the caller commits). Refused without a valid signature, or for a report
    measured under another protocol."""
    sig = signature(conn)
    if sig is None or not sig["valid"]:
        raise PermissionError("the protocol AD-C09 has not been signed by the owner as it is registered now "
                              "(scripts/ia_page_bank.py sign --reason ... --confirm-owner)")
    if (report.get("protocol") or {}).get("fingerprint") != stamp()["fingerprint"]:
        raise ValueError("the report was measured under another protocol")
    arms = {a: v.get("verdict") for a, v in (report.get("arms") or {}).items()}
    passed = arms.get(page_bank.CANDIDATE_ARM) == "PASA"
    evidence = {"kind": MEASUREMENT_KIND, "protocol": stamp(), "signature_row": sig["row"], "verdicts": arms, "report": dict(report)}
    row = _insert(conn, passed=passed, evidence=evidence, at=at, decided_by="script", code_version=code_version)
    return {"row": row, "passed": passed, "verdicts": arms}


def status(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(NEWEST_SQL)
        newest = cur.fetchone()
    return {"gate": GATE, "protocol": stamp(), "signature": signature(conn),
            "newest": None if newest is None else {"row": int(newest["id"]), "at": newest["at"].isoformat(), "passed": bool(newest["passed"]),
                                                   "kind": (newest["evidence"] or {}).get("kind"),
                                                   "verdicts": (newest["evidence"] or {}).get("verdicts")},
            "decides": False}
