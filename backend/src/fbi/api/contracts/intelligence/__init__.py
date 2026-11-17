"""The conventions of every PrediGol Intelligence contract (AD-J01, IA-057).

One pattern for the twelve contracts the UX screens read (C-01 ... C-12): two projections served by the server (public
under ``/api/v1/…`` with today's gates, private under ``/api/v1/admin/…`` with ``require_admin``), a seal on every
probability, a version on every contract, a reason for every absence, closed vocabularies, examples in
``tests/fixtures/contracts/intelligence/`` and a generic no-leak test. The owner's guide is
``docs/owner/IA_057_CONTRATO_INTELLIGENCE.md``.

* ``vocab`` - the closed lists.
* ``base`` - the base types.
* ``projection`` - the two projections and the leak check.
* ``versioning`` - additive or breaking, and the version it needs.
* ``registry`` - every contract, registered once.
* ``reference`` - C-00, the reference contract (no route).
"""

from __future__ import annotations

from fbi.api.contracts.intelligence.base import (
    CitedFact,
    DatedFact,
    Freshness,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    MarketValidation,
    Missing,
    PctInterval,
    Probability,
    Source,
    UtcDatetime,
    private,
    rounded_pct,
)
from fbi.api.contracts.intelligence.projection import ProjectionError, leaks, to_public
from fbi.api.contracts.intelligence.registry import CATALOGUE, CONTRACTS, ContractSpec

__all__ = [
    "CATALOGUE",
    "CONTRACTS",
    "CitedFact",
    "ContractSpec",
    "DatedFact",
    "Freshness",
    "IntelligenceContract",
    "IntelligenceModel",
    "ItemList",
    "MarketValidation",
    "Missing",
    "PctInterval",
    "Probability",
    "ProjectionError",
    "Source",
    "UtcDatetime",
    "leaks",
    "private",
    "rounded_pct",
    "to_public",
]
