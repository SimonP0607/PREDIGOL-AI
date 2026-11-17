"""When each official line-up was first seen (IA-069, plan piece AD-D05): one column that is never rewritten, one table of arrivals

WHY THIS EXISTS
---------------
``core.fixture_lineups`` holds the newest provider payload's view of a side's line-up: every read rewrites ``fetched_at``
(``fbi.ingestion.details``, ``ON CONFLICT ... DO UPDATE SET ... fetched_at = EXCLUDED.fetched_at``). So the instant the line-up
first reached us is lost as soon as it is read again, and nobody can say what the system knew at each moment before kick-off,
nor how long before kick-off each competition's line-ups arrive.

WHAT CHANGES
------------
- ``core.fixture_lineups.first_seen_at``: the fetch instant of the payload that first wrote the row. Set once, on INSERT, to
  the row's own ``fetched_at`` (unless the writer gave one), and never changed after: a BEFORE UPDATE trigger
  (``core.keep_lineup_first_seen``) puts the stored value back whatever an UPDATE says, for every writer (the live follow,
  the pre-match read, the post-match reads, backfill, reprocess). Rows that exist before this migration keep NULL: their
  first sighting was overwritten and is not reconstructed (NULL means «unknown», never a guess).
- ``core.fixture_lineup_arrivals``: append-only, one row each time a side's line-up is observed with a content different from
  the previous observation (formation, coach, players, numbers, positions, grid, starters). An identical re-send adds
  nothing; a corrected starter adds a row. ``channel`` says who observed it: the detail writers (``detail_writer``) or the
  pre-match watch (``lineup_watch``, off by default). UPDATE and DELETE are refused (``core.refuse_arrival_change``).

No foreign keys: ``core.fixtures`` and ``raw.ingestion_payloads`` are written all the time (the lesson of 0076, 0100 and
0110); the ids are kept by the code that writes them. The keep_settled_detail audit trigger (0061) is unaffected: the new
column never changes on UPDATE, so an update of a finished match's line-up compares as before.

Downgrade: drops the trigger, the function and the column, and the arrivals table. Nothing that existed before changes.

Revision ID: 0140
Revises: 0137
"""

from alembic import op

revision = "0140"
down_revision = "0139"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE core.fixture_lineups ADD COLUMN first_seen_at TIMESTAMPTZ;
        COMMENT ON COLUMN core.fixture_lineups.first_seen_at IS
          'IA-069: the fetch instant of the payload that first wrote this side''s line-up. Written once (INSERT), never '
          'rewritten (trigger keep_lineup_first_seen). NULL: the row predates migration 0140 and its first sighting is unknown.';

        CREATE FUNCTION core.keep_lineup_first_seen() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                NEW.first_seen_at := coalesce(NEW.first_seen_at, NEW.fetched_at);
            ELSE
                NEW.first_seen_at := OLD.first_seen_at;
            END IF;
            RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER fixture_lineups_first_seen BEFORE INSERT OR UPDATE ON core.fixture_lineups
            FOR EACH ROW EXECUTE FUNCTION core.keep_lineup_first_seen();

        CREATE FUNCTION core.refuse_arrival_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.history_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION '%.%: append-only (% refused)', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'check_violation';
        END
        $fn$;
    """)
    op.execute(rf"""
        CREATE TABLE core.fixture_lineup_arrivals (
            id             BIGSERIAL    PRIMARY KEY,
            fixture_id     BIGINT       NOT NULL CHECK (fixture_id >= 1),
            team_side      TEXT         NOT NULL CHECK (team_side IN ('home', 'away')),
            source         TEXT         NOT NULL CHECK (source IN ('api-football')),
            observed_at    TIMESTAMPTZ  NOT NULL,
            kickoff_at     TIMESTAMPTZ  NOT NULL,
            content_hash   TEXT         NOT NULL CHECK (content_hash ~ '{SHA256}'),
            starters_hash  TEXT         NOT NULL CHECK (starters_hash ~ '{SHA256}'),
            starters       SMALLINT     NOT NULL CHECK (starters BETWEEN 0 AND 99),
            players        SMALLINT     NOT NULL CHECK (players BETWEEN 0 AND 99),
            formation      TEXT         CHECK (formation IS NULL OR length(formation) <= 32),
            channel        TEXT         NOT NULL CHECK (channel IN ('detail_writer', 'lineup_watch')),
            payload_hash   TEXT         NOT NULL CHECK (length(payload_hash) BETWEEN 1 AND 128),
            run_id         BIGINT,
            recorded_at    TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp()
        );
        CREATE UNIQUE INDEX fixture_lineup_arrivals_once
            ON core.fixture_lineup_arrivals (fixture_id, team_side, source, observed_at, content_hash);
        CREATE INDEX fixture_lineup_arrivals_latest
            ON core.fixture_lineup_arrivals (fixture_id, team_side, source, observed_at DESC, id DESC);
        CREATE INDEX fixture_lineup_arrivals_kickoff ON core.fixture_lineup_arrivals (kickoff_at);
        COMMENT ON TABLE core.fixture_lineup_arrivals IS
          'IA-069 (AD-D05): each observation of a side''s line-up whose content differs from the previous observation of that '
          'side (an identical re-send adds nothing; a corrected starter adds a row). Append-only. kickoff_at is the kick-off '
          'as stored when observed. No reader of the product reads it.';
        COMMENT ON COLUMN core.fixture_lineup_arrivals.observed_at IS
          'The fetch instant of the payload (the payload index''s, as the detail writers use).';
        COMMENT ON COLUMN core.fixture_lineup_arrivals.channel IS
          'Who observed it: detail_writer (the follow, the pre-match read, the post-match reads) or lineup_watch (IA-069 watch).';
        COMMENT ON COLUMN core.fixture_lineup_arrivals.fixture_id IS 'core.fixtures.id (no foreign key: that table is busy).';
        CREATE TRIGGER fixture_lineup_arrivals_append_only BEFORE UPDATE OR DELETE ON core.fixture_lineup_arrivals
            FOR EACH ROW EXECUTE FUNCTION core.refuse_arrival_change();
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DROP TABLE core.fixture_lineup_arrivals;
        DROP FUNCTION core.refuse_arrival_change();
        DROP TRIGGER fixture_lineups_first_seen ON core.fixture_lineups;
        DROP FUNCTION core.keep_lineup_first_seen();
        ALTER TABLE core.fixture_lineups DROP COLUMN first_seen_at;
    """)
