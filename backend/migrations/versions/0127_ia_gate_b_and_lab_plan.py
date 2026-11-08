"""Plan Maestro IA, Gate B (section 24) - the evidence table learns ``gate_b`` and ``lab_plan``: Gate B can be recorded, and the owner's plan
of the LAB is stored where the code reads it.

``ai.feature_gates`` holds the evidence behind each gate of the AI layer (append-only; the newest row of a gate decides). ``fbi.ai.gate_b``
(``gate-b-v1``) evaluated the functional shadow but could not write its verdict: the CHECK that names the gates (last widened by 0116) did not
know ``gate_b``. Two words are added:

- ``gate_b``: the verdict of Gate B, ``PASA`` or ``NO PASA`` only, written by ``scripts/ia_gate_b.py evaluate --record`` (``decided_by =
  'script'``). A pending verdict is not evidence and is never written.
- ``lab_plan``: the number of LAB days the owner plans to exclude at the start of the shadow, written ONLY by the owner
  (``scripts/ia_gate_b.py set-lab-plan --days N --reason "..." --confirm-owner``, ``decided_by = 'owner'``). It is not a gate (nothing waits for
  it, ``passed`` is always true): the newest row is the figure the LAB check of Gate B compares the excluded days with. Without a row that
  part stays ``PENDIENTE POR ACCIONES MANUALES``; the code never invents it.

The only change is the vocabulary: the CHECK that names the gates. Nothing is written, copied or moved, and the code that ran before this
release finds the table as it left it (it reads the gates it knows). The CHECK is replaced under ``lock_timeout = '10s'`` (the lesson of 0076).

Downgrade: only while no row of ``gate_b`` or ``lab_plan`` exists. The table is append-only (a ledger is evidence, nothing is deleted), so with
them the code goes back and the list stays: the code that ran before never writes nor reads those words. Without them 0116's list comes back,
validated against every row.

Revision ID: 0127
Revises: 0126
"""

from __future__ import annotations

from alembic import op

revision = "0127"
down_revision = "0126"
branch_labels = None
depends_on = None

GATES_BEFORE = ("batch", "native_schema", "cache_layout", "gate_a", "battery", "research_v2", "switches")
"""The gates 0116 left."""
NEW_GATES = ("gate_b", "lab_plan")
"""The words this revision adds: Gate B's verdict and the owner's plan of the LAB."""
GATES = (*GATES_BEFORE, *NEW_GATES)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # The table is written a few times a month, but never wait for its lock longer than 10 s (the lesson of 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES)}));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM ai.feature_gates WHERE gate IN ({_in(NEW_GATES)})) THEN
                RAISE EXCEPTION 'ai.feature_gates holds rows of gate_b or lab_plan (append-only evidence): the code goes back, the list stays';
            END IF;
        END $$;
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES_BEFORE)}));
    """)
