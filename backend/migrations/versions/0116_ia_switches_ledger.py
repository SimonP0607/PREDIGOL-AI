"""Plan Maestro IA, review of phase 2 (M5) - the evidence table learns ``switches``: the ledger of the owner's words.

``ai.feature_gates`` holds the evidence behind each gate of the AI layer (append-only; the newest row of a gate decides). Gate A judges the
optimisations that were IN FORCE during its seven days, and an environment variable changed by hand - ``FBI_AI_NATIVE_SCHEMA=on`` and, a day
later, off again - wrote no row of its own: the gate could only read what the evaluating process held on the day it was evaluated. From now on
the worker appends a row of the gate ``switches`` whenever the words it runs with (the switches, the mode, research v2, the model of each tier,
the three envelopes) differ from the newest row: it is not a gate (nothing waits for it, ``passed`` is always true), it is the trace that a change
of configuration was missing. ``fbi.ai.gate_a`` counts a change of those words as a day the configuration changed, and reads what was in force
from the ledger.

The only change is the vocabulary: the CHECK that names the gates. Nothing is written, copied or moved, and the code that ran before this
release finds the table as it left it (it reads the gates it knows).

Downgrade: the old list comes back NOT VALID, the way 0115, 0113, 0112 and 0073 did it. The rows already written of the new gate stay (nothing is
deleted: a ledger is evidence); the constraint judges only the rows written or changed from then on, and the code that ran before never writes
that gate.

Revision ID: 0116
Revises: 0115
"""

from __future__ import annotations

from alembic import op

revision = "0116"
down_revision = "0115"
branch_labels = None
depends_on = None

GATES = ("batch", "native_schema", "cache_layout", "gate_a", "battery", "research_v2")
"""The gates 0115 left; ``switches`` is the new word."""


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # The table is written a few times a month, but never wait for its lock longer than 10 s (the lesson of 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES)}, 'switches'));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES)})) NOT VALID;
    """)
