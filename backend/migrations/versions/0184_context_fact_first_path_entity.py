"""A context fact of the FIRST path names its entity by the row's own identifiers (plan RP-4.1): the check of ``fact_schema`` no longer asks it for a ``subject_type``

WHY THIS EXISTS
---------------
0180 made a row written under ``context-fact-v1`` complete or refused, and one of its demands is a ``subject_type``. But in ``ai.evidence`` a
``subject_type`` is also what separates what research v2 wrote from what v1 decides: the first are read apart (``TYPED_SQL``) and shown in a packet only
while research v2 is on; the second (``LOAD_SQL``) are always decided and shown. A provider's report that migrated to the schema with a ``subject_type`` would
leave the path v1 reads it by: its injuries and line-ups would vanish from the packet and from the state decisions. Nothing was migrated for that reason.

WHAT CHANGES (the check gets looser; no row is written or rewritten; ``lock_timeout`` 10 s)
* ``evidence_fact_complete`` accepts, besides a ``subject_type``, a row of the first path: origin ``provider``, ``web`` or ``owner``, no ``claim_type``,
  no ``subject_type`` and at least one of ``fixture_id``, ``team_id`` or ``provider_player_id`` (the entity such a row has always named). Everything the check
  demanded stays demanded: a side, a validity, the source's date, a source with a name.
* The code says the same (``factor_schema.names_its_entity``); a test holds that the two agree.

No existing row can fail the new check: those with ``fact_schema`` set already had a ``subject_type``.

Downgrade: the strict check comes back NOT VALID (a row written under the looser one stays: a fact is not worth a failed downgrade).

Revision ID: 0184
Revises: 0183
"""

from __future__ import annotations

from alembic import op

revision = "0184"
down_revision = "0183"
branch_labels = None
depends_on = None

FIRST_PATH = ("provider", "web", "owner")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_fact_complete;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_fact_complete CHECK (
            fact_schema IS NULL OR (side IS NOT NULL AND fresh_until IS NOT NULL AND published_at IS NOT NULL AND length(btrim(source_name)) > 0
                                    AND (subject_type IS NOT NULL
                                         OR (claim_type IS NULL AND subject_id IS NULL AND origin IN ({_in(FIRST_PATH)})
                                             AND (fixture_id IS NOT NULL OR team_id IS NOT NULL OR provider_player_id IS NOT NULL)))));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_fact_complete;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_fact_complete CHECK (
            fact_schema IS NULL OR (side IS NOT NULL AND fresh_until IS NOT NULL AND published_at IS NOT NULL AND subject_type IS NOT NULL
                                    AND length(btrim(source_name)) > 0)) NOT VALID;
    """)
