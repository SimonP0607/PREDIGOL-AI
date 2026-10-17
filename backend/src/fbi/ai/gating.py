"""When may an AI decision change what users see? Only when BOTH hold:

1. the owner switched it on: ``FBI_AI_MODE=enforce``;
2. the AI's own prospective evaluation passed its gate (``fbi.ai.shadow``): over enough settled
   selections, what the reviews rejected did measurably worse than what they approved, and filtering did
   not cost closing-line value or calibration.

Otherwise the layer is in SHADOW: every decision is recorded and shown to the owner, and the picks of the
day, the parlays and the analysis cards that users see are exactly what they would be without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.config import AiSettings


@dataclass(frozen=True, slots=True)
class Enforcement:
    enforced: bool
    reason: str
    gate: dict[str, Any] | None = None


def enforcement(conn: psycopg.Connection[Any], settings: AiSettings) -> Enforcement:
    if settings.mode != "enforce":
        return Enforcement(False, f"mode_{settings.mode}")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT gate, created_at, engine FROM ai.shadow_reports WHERE engine = 'combined' "
                    "ORDER BY created_at DESC, id DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return Enforcement(False, "no_shadow_report")
    gate = dict(row["gate"] or {})
    if gate.get("verdict") != "pass":
        return Enforcement(False, "shadow_gate_not_passed", gate)
    return Enforcement(True, "enforced", gate)
