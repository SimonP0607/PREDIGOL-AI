"""The deterministic part of the Council v2 (``council-protocol-v1``, IA-012), in SHADOW.

The approved protocol of the Council v2, minus the judge:

    1. positions       the typed stances of the specialists (Match, Statistics) on each selection of a pass of the shadow, with the
                       model's numbers and the market's signals beside them (read only)
    2. weights         each agent weighed by its track record per market family (``weights``): bounded, shrunk towards "no skill",
                       and ZERO for a version the owner did not promote
    3. contradictions  agent against agent, against the model, against the market, and the check "did the model already know?"
                       (``contradictions``), each with a code and the runs and references it rests on
    4. research        whether ONE targeted round is warranted, and on which topics of the closed catalogue (``research_round``)
    5. the judge       untouched: the LLM Council of ``council-v1`` keeps judging; this package computes what it would be given
    6. the output      a typed ``ctx-adj-v1`` adjustment (``fbi.intel.context_adjustment``) - never a number toward a decision

Nothing here calls a model, writes a row, or changes a prompt, a contract, an agent or the orchestrator. Nothing that decides,
publishes or serves a user imports this package (``tests/unit/test_council_isolation.py`` holds the door shut): it is computed and
reported by ``python -m scripts.ia_council_v2`` and read by nobody else.
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "council-protocol-v1"
"""The protocol as a whole. A change to any rule or constant of its modules is a new version, never an edit."""
