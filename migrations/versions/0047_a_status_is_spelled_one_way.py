"""a status is spelled one way: repair the fixtures the provider spelled "Canc"

The provider sends the short status as ``"CANC"`` for most cancelled fixtures and as
``"Canc"`` for others (fixture 1438655, AFC Champions League Two 2025, is one); the
same for ``"Abd"``. The status-group map was case-sensitive, so those fell through to
its default: on 4 Oct 2026, 78 cancelled fixtures and one abandoned one were stored as
*scheduled*, past kick-off - most of the "85 fixtures awaiting a result" on the Data
Quality page - and a pick on one of them could never settle (settlement is keyed on
``CANC`` too).

The parsers now upper-case the code at the boundary (``canonical_status``). This
repairs the rows already written, and records every change in a new table,
``audit.data_repairs``, with the value before and after: a repair that leaves no
trace is indistinguishable from corruption.

Only spelling and the group that follows from it change. Kick-off, score and lineage
are left exactly as they were.

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

GROUP_OF = """CASE upper({col})
    WHEN 'TBD' THEN 'scheduled' WHEN 'NS' THEN 'scheduled'
    WHEN '1H' THEN 'live' WHEN 'HT' THEN 'live' WHEN '2H' THEN 'live' WHEN 'ET' THEN 'live'
    WHEN 'BT' THEN 'live' WHEN 'P' THEN 'live' WHEN 'LIVE' THEN 'live' WHEN 'INT' THEN 'live'
    WHEN 'FT' THEN 'finished' WHEN 'AET' THEN 'finished' WHEN 'PEN' THEN 'finished'
    WHEN 'SUSP' THEN 'postponed' WHEN 'PST' THEN 'postponed'
    WHEN 'CANC' THEN 'cancelled' WHEN 'ABD' THEN 'cancelled' WHEN 'AWD' THEN 'cancelled'
    WHEN 'WO' THEN 'cancelled'
END"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.data_repairs (
            id           BIGSERIAL PRIMARY KEY,
            repaired_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            rule         TEXT NOT NULL,
            entity       TEXT NOT NULL,
            entity_id    BIGINT NOT NULL,
            provider_ref BIGINT,
            field        TEXT NOT NULL,
            before_value TEXT,
            after_value  TEXT,
            reason       TEXT NOT NULL,
            evidence     TEXT
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS data_repairs_rule ON audit.data_repairs (rule, repaired_at)")
    op.execute("CREATE INDEX IF NOT EXISTS data_repairs_entity ON audit.data_repairs (entity, entity_id)")
    op.execute("COMMENT ON TABLE audit.data_repairs IS "
               "'Every correction applied to stored data outside normal ingestion: what, before, after, why.'")

    expected = GROUP_OF.format(col="f.status_short")
    op.execute(f"""
        WITH wrong AS (
            SELECT f.id, f.provider_fixture_id, f.status_short AS old_short, f.status_group AS old_group,
                   upper(f.status_short) AS new_short, {expected} AS new_group, f.source_payload_hash
              FROM core.fixtures f
             WHERE f.status_short <> upper(f.status_short)
                OR ({expected} IS NOT NULL AND {expected} <> f.status_group)
        ), fixed AS (
            UPDATE core.fixtures f
               SET status_short = w.new_short,
                   status_group = COALESCE(w.new_group, f.status_group),
                   updated_at = now()
              FROM wrong w
             WHERE f.id = w.id
         RETURNING w.*
        )
        INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, after_value,
                                        reason, evidence)
        SELECT 'status_spelling', 'core.fixtures', id, provider_fixture_id, 'status_short/status_group',
               old_short || ' / ' || old_group, new_short || ' / ' || COALESCE(new_group, old_group),
               'the provider spells some short statuses in mixed case (Canc, Abd); the group map was '
               'case-sensitive and defaulted them to scheduled',
               'migration 0047; source payload ' || COALESCE(source_payload_hash, 'unknown')
          FROM fixed
    """)


def downgrade() -> None:
    # The repaired values are the correct ones; restoring "Canc / scheduled" would put
    # the defect back. Only the table this revision introduced is removed.
    op.execute("DROP TABLE IF EXISTS audit.data_repairs")
