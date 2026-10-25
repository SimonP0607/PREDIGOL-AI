"""Plan Maestro IA, Phase 1 - the ledger of the AI jobs learns the one that writes the state of each match.

``ai.cycles`` is the ledger of the jobs of the AI layer: one row per run, what it saw, what it did, what it cost. The job that derives the package
of every pass and writes the state of the match (``fbi.ai.match_runs``, phase 1: no model, so no cost) keeps its runs there, under the kind
``package``, beside the others - the Admin Console reads the latest run of each kind from that one place.

The only change is the vocabulary: the CHECK that names the kinds of cycle. Nothing is written, copied or moved, and the code that ran before
this phase finds the table as it left it.

Downgrade: the old list comes back NOT VALID, the way 0073 did it. The rows already written of the new kind stay (nothing is deleted); the
constraint judges only the rows written or changed from then on, and the code that ran before never writes that kind. A cycle of the new kind
still 'running' (a worker killed in the middle of one) is closed first as failed, the way the recovery of a stopped worker closes it: the
recovery of the code that ran before updates every cycle left running in one statement, and a row the constraint refuses would stop it for
the others too.

Revision ID: 0112
Revises: 0111
"""

from __future__ import annotations

from alembic import op

revision = "0112"
down_revision = "0111"
branch_labels = None
depends_on = None

KINDS = ("analysis", "postmortem", "learning", "evaluation", "day_start", "prepare")
"""The kinds 0073 left (``fbi.ai.cycle`` opens each of them); ``package`` is the new one."""


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # On a live database the worker opens and closes a cycle several times an hour: never wait for its lock longer than 10 s (the lesson of 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.cycles DROP CONSTRAINT cycles_kind_check;
        ALTER TABLE ai.cycles ADD CONSTRAINT cycles_kind_check CHECK (kind IN ({_in(KINDS)}, 'package'));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        UPDATE ai.cycles SET status = 'failed', finished_at = started_at, error = 'interrupted: the schema went back before the cycle finished'
         WHERE kind = 'package' AND status = 'running'
    """)
    op.execute(f"""
        ALTER TABLE ai.cycles DROP CONSTRAINT cycles_kind_check;
        ALTER TABLE ai.cycles ADD CONSTRAINT cycles_kind_check CHECK (kind IN ({_in(KINDS)})) NOT VALID;
    """)
