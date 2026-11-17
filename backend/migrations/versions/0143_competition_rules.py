"""The versions of the competition rules loaded (IA-072, plan piece AD-B01): one append-only table, and nothing else

WHY THIS EXISTS
---------------
The rules of each competition (format, phases, zones, tie-breakers in order, the tables that decide each zone) live as files under
``config/rules/``, one per competition and version, each with its official source and the day it was checked; ``fbi.competitions.
rules`` reads them. This table records every version that was loaded into production - which file, its sha256, the parameters as
they were - so a reading made on a day can always be traced to the exact rules it used, and a rule found wrong is retired with its
reason in a new row instead of being rewritten.

WHAT CHANGES
------------
- ``core.competition_rules``: one row per (provider league, version, file content). ``state`` is ``coded`` or ``retired``; a
  retired row says why. Loading the same file twice writes nothing (unique on league, version and sha256). Append-only:
  ``core.refuse_rules_change()`` refuses UPDATE and DELETE.

The data is NOT here: ``scripts/ia_rules.py load`` loads the files after the deploy (idempotent). No foreign key: the league is the
provider's id (``core.competitions.provider_league_id``), the one id the repository knows. Nothing reads this table to decide: the
reader uses the files; this is the record.

Downgrade: drops the table and its function (the files stay in the repository).

Revision ID: 0143
Revises: 0139 (provisional: 0140-0142 are in review and not in this tree; it goes on top of the highest when they are merged)
"""

from alembic import op

revision = "0143"
down_revision = "0142"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE FUNCTION core.refuse_rules_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION '%.%: a loaded version of the rules is never edited nor deleted (% refused); add a new version',
                TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP USING ERRCODE = 'check_violation';
        END
        $fn$""")
    op.execute(rf"""
        CREATE TABLE core.competition_rules (
            id              BIGSERIAL    PRIMARY KEY,
            league_id       INTEGER      NOT NULL CHECK (league_id >= 1),
            rules_version   INTEGER      NOT NULL CHECK (rules_version >= 1),
            state           TEXT         NOT NULL CHECK (state IN ('coded', 'retired')),
            reason          TEXT,
            seasons         INTEGER[]    NOT NULL CHECK (cardinality(seasons) >= 1),
            valid_from      DATE,
            valid_to        DATE,
            schema_version  TEXT         NOT NULL CHECK (schema_version = 'competition-rules/1'),
            file_path       TEXT         NOT NULL CHECK (length(file_path) BETWEEN 5 AND 200),
            file_sha256     TEXT         NOT NULL CHECK (file_sha256 ~ '{SHA256}'),
            rules           JSONB        NOT NULL,
            sources         JSONB        NOT NULL CHECK (jsonb_typeof(sources) = 'array' AND jsonb_array_length(sources) >= 1),
            reader_version  TEXT         NOT NULL,
            loaded_at       TIMESTAMPTZ  NOT NULL,
            loaded_by       TEXT         NOT NULL CHECK (loaded_by IN ('loader', 'owner')),
            code_version    TEXT,
            UNIQUE (league_id, rules_version, file_sha256),
            CHECK ((state = 'retired') = (reason IS NOT NULL AND length(btrim(reason)) >= 3)),
            CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
        );
        CREATE INDEX core_competition_rules_league ON core.competition_rules (league_id, rules_version, id DESC);
        COMMENT ON TABLE core.competition_rules IS
          'IA-072: every version of a competition''s rules loaded from config/rules (one file per competition and version, with its '
          'official source). The newest row of a (league, version) is its state; a retired version keeps its reason. Append-only. '
          'The reader uses the files; this is the record of which rules were in production when.';
    """)
    op.execute("CREATE TRIGGER competition_rules_append_only BEFORE UPDATE OR DELETE ON core.competition_rules "
               "FOR EACH ROW EXECUTE FUNCTION core.refuse_rules_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS core.competition_rules")
    op.execute("DROP FUNCTION IF EXISTS core.refuse_rules_change()")
