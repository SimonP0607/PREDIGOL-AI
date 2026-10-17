"""settled detail changes: a finished match's detail as it was before a newer payload replaced it

The detail tables (events, line-ups and their players, team and player statistics) hold the newest provider
payload's view of a match: an in-play list is replaced every minute, and the settled re-read after the final
whistle may still change a finished match. RAW keeps every payload, but the previous NORMALIZED rows of a
finished match were not kept anywhere - the restore test of 4 Oct 2026 (``post-api-contract-v3``) found
``core.fixture_events`` 11 rows shorter than the dump four minutes earlier (nine in-play lists replaced).

``audit.keep_settled_detail`` keeps, for a FINISHED match only, every detail row a later payload changes or
removes - the whole row as it was, with the payload it came from - in ``audit.settled_detail_changes``. An
update that changes only the provenance columns (the same values in a newer payload) or an internal link
(``coach_id``) is not a change. In-play replacements are not kept here: RAW has each of them, and the live
state is a snapshot by nature. The event and line-up lists are written change-only
(``fbi.ingestion.details``), so a re-read that says the same thing touches nothing.

Revision ID: 0061
Revises: 0060
"""

from __future__ import annotations

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

TRIGGERS = {
    "core.fixture_events": ("payload_hash", "fetched_at"),
    "core.fixture_lineup_players": (),
    "core.fixture_lineups": ("payload_hash", "fetched_at", "coach_id"),
    "core.fixture_team_stats": ("payload_hash", "fetched_at", "dropped_fields"),
    "core.fixture_player_stats": ("payload_hash", "fetched_at"),
}
"""Each detail table and the columns that are provenance or links, not the provider's values."""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.settled_detail_changes (
            id          BIGSERIAL   PRIMARY KEY,
            changed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            table_name  TEXT        NOT NULL,
            fixture_id  BIGINT      NOT NULL,
            op          TEXT        NOT NULL CHECK (op IN ('UPDATE', 'DELETE')),
            old_row     JSONB       NOT NULL,
            new_row     JSONB,
            reason      TEXT        NOT NULL
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS settled_detail_changes_fixture "
               "ON audit.settled_detail_changes (fixture_id, changed_at)")
    op.execute("COMMENT ON TABLE audit.settled_detail_changes IS "
               "'A finished match''s detail row as it was before a newer provider payload changed or removed it "
               "(trigger audit.keep_settled_detail, migration 0061): the normalized history the current-state "
               "detail tables do not keep. Every payload is in RAW as well.'")
    op.execute("""
        CREATE OR REPLACE FUNCTION audit.keep_settled_detail() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            o jsonb := to_jsonb(OLD);
            n jsonb;
            i int;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM core.fixtures f
                            WHERE f.id = OLD.fixture_id AND f.status_group = 'finished') THEN
                RETURN NULL;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                n := to_jsonb(NEW);
                FOR i IN 0 .. TG_NARGS - 1 LOOP
                    o := o - TG_ARGV[i];
                    n := n - TG_ARGV[i];
                END LOOP;
                IF o = n THEN
                    RETURN NULL;
                END IF;
            END IF;
            INSERT INTO audit.settled_detail_changes (table_name, fixture_id, op, old_row, new_row, reason)
            VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, OLD.fixture_id, TG_OP, to_jsonb(OLD),
                    CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(NEW) END,
                    CASE WHEN TG_OP = 'UPDATE'
                         THEN 'a newer provider payload changed this detail of a finished match'
                         ELSE 'a newer provider payload replaced the list this row belonged to' END);
            RETURN NULL;
        END $$""")
    for table, ignored in TRIGGERS.items():
        args = ", ".join(f"'{c}'" for c in ignored)
        op.execute(f"DROP TRIGGER IF EXISTS keep_settled_detail ON {table}")
        op.execute(f"CREATE TRIGGER keep_settled_detail AFTER UPDATE OR DELETE ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION audit.keep_settled_detail({args})")


def downgrade() -> None:
    for table in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS keep_settled_detail ON {table}")
    op.execute("DROP FUNCTION IF EXISTS audit.keep_settled_detail()")
    # audit.settled_detail_changes is evidence: it is kept on downgrade.
