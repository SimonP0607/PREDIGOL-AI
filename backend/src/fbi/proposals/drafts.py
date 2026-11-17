"""The retirements AD-K06 leaves for the owner (IA-138): drafts of ``retirada`` proposals, with the evidence measured before them.

AD-K06 simplifies the old components WITHOUT deleting anything: the four memories are now read through one layer (``fbi.memoryread``),
and what may stop being written - the analysis cards, the paid patterns, the daily notes - is a proposal here, not a change. A draft is
registered only by the owner's command (``scripts/ia_proposals.py drafts --write``) and cannot be SIGNED until its parity was compared
(``evidence.parity = 'igual'``, ``fbi.proposals.sign_problems``): each one says ``pendiente``, because the comparison of what its readers
read before and after the writer stops is the next step, one writer at a time. Its tables are kept, readable, whatever is signed.

Every figure names where and when it was measured. Pure."""

from __future__ import annotations

from typing import Final

from fbi.proposals import Proposal

MEASURED: Final = "2026-11-16"

RETIREMENTS: Final[tuple[Proposal, ...]] = (
    Proposal(
        "retirada", "writer:fbi.ai.analysis", "match-analysis-v1", "match-analysis-v1-retirado",
        {"stops": "ai.match_analyses (escritura)", "keeps": "la tabla y sus filas, legibles"},
        {"rows_14_days": 79336, "matches_14_days": 1382, "rows_per_match": 57, "rows_total_approx": 215000,
         "packets_rows_approx": 195000, "packets_gb_approx": 2.5, "model_cost_usd": 0,
         "readers": ["fbi.picks.user_status", "fbi.api.services.ai_layer"], "duplicates": "las tarjetas del brief",
         "parity": "pendiente", "measured_on": MEASURED},
        ({"table": "ai.match_analyses", "measure": "filas en 14 días y por partido", "on": MEASURED},
         {"table": "ai.match_packets", "measure": "filas y tamaño", "on": MEASURED}),
        "Tarjetas de análisis por reglas: 57 filas por partido que repiten las del brief; un lector (picks.user_status) aún las lee, "
        "por eso se compara antes de retirar.", "owner"),
    Proposal(
        "retirada", "writer:fbi.ai.patterns", "patterns-v1", "patterns-v1-retirado",
        {"stops": "las llamadas de patterns-v1", "keeps": "ai.memory_events y analytics.research_hypotheses, legibles"},
        {"cost_usd_1_15_nov": 0.81, "hypotheses_that_became_rules": 0, "parity": "pendiente", "measured_on": MEASURED},
        ({"table": "ai.usage", "prompt_version": "patterns-v1", "window": "2026-11-01/2026-11-15"},
         {"table": "analytics.research_hypotheses", "measure": "hipótesis que llegaron a regla", "on": MEASURED}),
        "Patrones con modelo: ninguna hipótesis ha llegado a regla; el tablero AD-K02 y la evaluación AD-K01 cubren la pregunta.",
        "owner"),
    Proposal(
        "retirada", "writer:fbi.ai.learning", "learning-v1.2", "learning-v1.2-retirado",
        {"stops": "las notas diarias de aprendizaje con modelo", "keeps": "ai.learning_notes y ai.source_stats, legibles"},
        {"cost_usd_1_15_nov": 0.18, "readers": ["fbi.ai.daily_review", "fbi.api.services.ai_layer", "fbi.api.services.ai_v2"],
         "parity": "pendiente", "measured_on": MEASURED},
        ({"table": "ai.usage", "prompt_version": "learning-", "window": "2026-11-01/2026-11-15"},),
        "Notas diarias de aprendizaje: la evaluación posterior única (eval-sel-v1) y el tablero dicen lo mismo con evidencia medida.",
        "owner"),
)
"""Measured 16 Nov 2026 in production (inventory of the definitive architecture, section 2.4 and 9; the plan's file of AD-K06)."""

__all__ = ["MEASURED", "RETIREMENTS"]
