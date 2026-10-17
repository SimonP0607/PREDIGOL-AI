"""fixture and result lineage: which payload wrote this row, and when

A Match Center that shows a score has to be able to say where the score came
from. Until now it could not: core.fixtures and core.fixture_results carried no
reference to the payload that produced them, so the chain

    provider response -> raw file -> hash -> normalised row

was broken at the last link for exactly the rows a user looks at.

Each row now records the hash of the payload that last wrote it and that
payload's fetch time. The fetch time is also what makes writes monotonic: an
older payload - a replay, a late retry - may never overwrite what a newer one
already established. Without that guard, re-normalising a stored response from
the 12th would silently turn a finished match back into a scheduled one.

Rows written before this revision keep NULL lineage. That is the truth - the
link was not recorded - and it is reported as such rather than guessed.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE core.fixtures
    ADD COLUMN source_payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN source_fetched_at   TIMESTAMPTZ;
ALTER TABLE core.fixtures ADD CONSTRAINT fixtures_lineage_pair_check
    CHECK ((source_payload_hash IS NULL) = (source_fetched_at IS NULL));

ALTER TABLE core.fixture_results
    ADD COLUMN source_payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN source_fetched_at   TIMESTAMPTZ;
ALTER TABLE core.fixture_results ADD CONSTRAINT fixture_results_lineage_pair_check
    CHECK ((source_payload_hash IS NULL) = (source_fetched_at IS NULL));

COMMENT ON COLUMN core.fixtures.source_payload_hash IS
  'Hash of the raw payload that last wrote this row (raw.ingestion_payloads).
   NULL for rows written before revision 0015: the link was not recorded then.';
COMMENT ON COLUMN core.fixtures.source_fetched_at IS
  'When that payload was fetched. Writes are monotonic on it: an older payload
   never overwrites a row a newer one already wrote.';
COMMENT ON COLUMN core.fixture_results.source_payload_hash IS
  'Hash of the raw payload the score was read from.';
"""

DOWNGRADE = """
ALTER TABLE core.fixture_results DROP CONSTRAINT IF EXISTS fixture_results_lineage_pair_check;
ALTER TABLE core.fixture_results DROP COLUMN IF EXISTS source_fetched_at;
ALTER TABLE core.fixture_results DROP COLUMN IF EXISTS source_payload_hash;
ALTER TABLE core.fixtures DROP CONSTRAINT IF EXISTS fixtures_lineage_pair_check;
ALTER TABLE core.fixtures DROP COLUMN IF EXISTS source_fetched_at;
ALTER TABLE core.fixtures DROP COLUMN IF EXISTS source_payload_hash;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
