"""The replay bank of the deliberations (IA-047, plan piece ``INT-C02``): stored runs of the shadow, asked again.

What it is for. Comparing a variant of an agent or of the Council against the agent in force needs the same
inputs for both, and the shadow gives each pass ONE question, asked once. The bank takes the stored runs of
the shadow (``ai.agent_runs``, ``run_kind = 'shadow'``) whose input can be derived again byte for byte from
what the database keeps - the stored packet, the as-of read of the forecasts, the selections production
reviewed, the decisions of the families, the stored answers of the agents the Council read - and asks the
same question again through the Message Batches route of the LAB workspace.

    bank       ``fbi.ai.replay.bank``: which stored runs can be rebuilt, the request each one was sent, and why
               the others cannot (a closed code per run). Read-only.
    harness    ``fbi.ai.replay.harness``: the plan (what would be asked and what it costs), the run (one batch
               of the LAB, all or nothing, only with the owner's confirmation and a registered protocol), the
               handler that keeps the raw answer of each ask, and the collection of the answers into the
               bank's own tables.
    measure    ``fbi.ai.replay.measure``: how much a replay agrees with what was stored, against how much the
               same call asked twice agrees with itself (the rule of the equivalence of Gate A).

What it never does. It writes no row of ``ai.agent_runs``, ``ai.agent_tasks``, ``ai.match_runs``,
``ai.pick_reviews`` or ``ai.feature_gates``: the shadow, its sample, the switches, the envelopes and the
anchor of Gate B are read, never moved. Its rows live in ``ai.replay_bank_items``, ``ai.replay_runs``,
``ai.replay_results`` and ``ai.replay_assessments`` (migration 0135). It never changes a model, a prompt, a
schema or an effort: a stored run whose question the code in force cannot ask again is excluded, with its
reason, and never asked in another way.
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "replay-bank-v1"
"""The method of the bank: which runs it admits, how it rebuilds them and how it names its asks. It is the
``bank_version`` of its rows and the ``prompt_version`` of its asks in ``ai.batch_items`` and ``ai.usage``
(never an agent's prompt label, so that no reader of the shadow's costs counts a replay as the shadow's).
A change of the method is a new version, never an edit."""
SAME: Final = "same"
"""The variant that is the stored run itself: the same agent version, prompt, schema, model and effort, asked
the same request. The reproducibility gate measures it; a variant of ``INT-C03`` or ``INT-C05`` gets its own
name."""
REPEATS: Final = 2
"""How many times each admitted run is asked again: the second ask is the yardstick (what repeating the same
call changes)."""
PROTOCOL_KEY: Final = "INT-C02"
"""The protocol a run with spend requires (``fbi.research.protocol.require``)."""

__all__ = ["PROTOCOL_KEY", "REPEATS", "SAME", "VERSION"]
