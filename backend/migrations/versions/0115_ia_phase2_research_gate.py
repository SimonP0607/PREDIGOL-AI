"""Plan Maestro IA, Phase 2 - the evidence table of the optimisations learns a gate: research v2.

``ai.feature_gates`` holds the evidence behind each gate of the AI layer (append-only; the newest row of a gate decides). Phase 2 adds the gate
``research_v2``: the measurement of the week in which the research of an entity (``fbi.ai.entity_research``) ran beside v1's research, without
anyone reading what it wrote. ``FBI_AI_RESEARCH_V2=on`` - v2 replaces v1's research and the packet shows what it wrote - holds only while the
newest row of this gate says it passed (``fbi.ai.gates.research_mode``).

The only change is the vocabulary: the CHECK that names the gates. Nothing is written, copied or moved, and the code that ran before this
phase finds the table as it left it (it reads the gates it knows).

Downgrade: the old list comes back NOT VALID, the way 0113, 0112 and 0073 did it. The rows already written of the new gate stay (nothing is
deleted: a measurement is evidence); the constraint judges only the rows written or changed from then on, and the code that ran before never
writes that gate.

Revision ID: 0115
Revises: 0114
"""

from __future__ import annotations

from alembic import op

revision = "0115"
down_revision = "0114"
branch_labels = None
depends_on = None

GATES = ("batch", "native_schema", "cache_layout", "gate_a", "battery")
"""The gates 0113 left; ``research_v2`` is the new one."""


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # The table is written a few times a month, but never wait for its lock longer than 10 s (the lesson of 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES)}, 'research_v2'));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES)})) NOT VALID;
    """)
