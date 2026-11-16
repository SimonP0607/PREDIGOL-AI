"""The registry of capabilities for the Admin Console (IA-056, AD-003; ``GET /admin/intelligence/capabilities``): read-only.

Every capability of the plan with its state (construida, en_sombra, lista_para_revision, autorizada), its recorded safety and validation
verdicts (validation with its sample), the newest rows of the gates it answers to and its agents' runs of the last seven days
(``fbi.intel.capabilities.overview``). Only the Admin Console serves it (``require_admin``): nothing of it is in any reader's projection."""

from __future__ import annotations

from typing import Any

from fbi.api.envelope import Envelope, ok
from fbi.api.repositories import Conn
from fbi.core.clock import now
from fbi.intel import capabilities as registry


def overview(conn: Conn) -> Envelope[dict[str, Any]]:
    view = registry.overview(conn, at=now())
    return ok(view, count=len(view["capabilities"]))
