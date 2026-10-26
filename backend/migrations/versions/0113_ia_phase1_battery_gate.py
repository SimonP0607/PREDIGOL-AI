"""Plan Maestro IA, Phase 1 - the evidence table of the optimisations learns a gate: the adversarial battery.

``ai.feature_gates`` holds the evidence behind each gate of the AI layer (append-only; the newest row of a gate decides). Phase 1 adds the
gate ``battery``: the measurement of ``fbi.ai.battery`` (the prompts that read text someone else wrote, attacked with text written to be read
by a model), which Gate B of the plan needs green.

The only change is the vocabulary: the CHECK that names the gates. Nothing is written, copied or moved, and the code that ran before this
phase finds the table as it left it (it reads the gates it knows).

Downgrade: the old list comes back NOT VALID, the way 0112 and 0073 did it. The rows already written of the new gate stay (nothing is deleted:
a measurement is evidence); the constraint judges only the rows written or changed from then on, and the code that ran before never writes
that gate.

Revision ID: 0113
Revises: 0112
"""

from __future__ import annotations

from alembic import op

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None

GATES = ("batch", "native_schema", "cache_layout", "gate_a")
"""The gates 0110 left; ``battery`` is the new one."""


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # The table is written a few times a month, but never wait for its lock longer than 10 s (the lesson of 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES)}, 'battery'));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES)})) NOT VALID;
    """)
