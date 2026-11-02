"""Who was reported missing, and when we learned it: the append-only history of /injuries answers (plan F0, defect 8)

WHY THIS EXISTS
---------------
``core.player_absences`` keeps ONE row per (match, player) and every /injuries answer overwrites it. It answers
"what does the provider say now" and nothing else:

* It cannot say what was known at an earlier moment. A row refreshed after the moment is dropped by
  ``fetched_at <= at``, so a read "as of X" does not see what was known at X if any refresh followed. On 3 Oct 2026 the
  oldest ``fetched_at`` the table held was 29 Sep 2026, for 29,765 matches.
* It cannot say that a player was taken OFF the list. A player the newest answer no longer names keeps his old row, and
  the AI packet, the evidence collector and the dossier read it as an absence that still stands (the Match Center
  already hid such rows from 11 Oct 2026; 44 had been shown on upcoming matches).

``core.player_availability_obs`` is the history those two questions need. It is the first, reduced slice of what plan
F3 calls ``player_availability_obs``: F3 extends this table (more sources, the player's page), it does not replace it.
It is created now because a history can only be written forward: every day without it is a day nobody can ever ask
about.

HOW IT IS WRITTEN (``fbi.ingestion.availability``)
--------------------------------------------------
Each /injuries answer is the provider's complete list for one season at one moment. It is recorded as the CHANGES it
makes against what was known just before it, one row per change:

``LISTED``   the answer names the player for the match, with the type and reason it gives. Written when he was not
             listed, or was listed with a different type, reason or team. An unchanged answer writes nothing.
``CLEARED``  the previous state listed him and this answer, for a match not yet played, no longer names him. Written
             once; type and reason are those of the last listing, so the row says what was cleared. A match already
             played keeps its record: nobody is cleared from it.

What was known at ``at`` about a match: for each player the newest row with ``observed_at <= at``, and of those the
ones that are LISTED. Nothing is ever updated or deleted. ``core.player_absences`` stays exactly as it was, as the
"latest" table the Match Center and the audits read.

DELIBERATE CHOICES
------------------
* ``observed_at`` is when WE asked, not the index time of the payload. The raw store keeps identical bodies once, at the
  first fetch, so an answer that went back to an earlier content (A, then B, then A again) would be dated in the past
  and could never win. That is also why the column is not called ``fetched_at``: the lineage check
  (``fbi.quality.detect.payload_dated_relations``) forbids a ``fetched_at`` later than its payload's, and this is a
  record of observations, not a derived copy of one payload.
* The seed copies every row of ``core.player_absences`` as a LISTED row at its ``fetched_at`` (``origin = 'snapshot'``).
  It claims only what is true: the provider listed that player at that time. When he was first listed, or whether he
  has been cleared since, is exactly what the old table lost. Players it still lists but the newest answer no longer
  names are cleared by the first answer the new code records.
* Additive only: nothing existing is altered. Downgrade drops the table (the seed is a copy; the source is intact).

Revision ID: 0078
Revises: 0077
"""

from __future__ import annotations

from alembic import op

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None

NORMALIZER_VERSION = "availability-v1"

SEED_SQL = f"""
INSERT INTO core.player_availability_obs
       (fixture_id, source, provider_fixture_id, provider_player_id, observed_at, status, provider_team_id,
        player_name, absence_type, reason, payload_hash, origin, normalizer_version)
SELECT a.fixture_id, a.source, a.provider_fixture_id, a.provider_player_id, a.fetched_at, 'LISTED',
       a.provider_team_id, a.player_name, a.absence_type, a.reason, a.payload_hash, 'snapshot',
       '{NORMALIZER_VERSION}'
  FROM core.player_absences a
 WHERE a.fixture_id IS NOT NULL
ON CONFLICT DO NOTHING
"""
"""Rows whose match we do not hold (``fixture_id`` NULL) are not copied: nothing can read them by match."""


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The table is new; the foreign
    # keys take a short lock on core.fixtures and raw.ingestion_payloads.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE core.player_availability_obs (
            fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            source              TEXT        NOT NULL CHECK (source IN ('api-football')),
            provider_player_id  INTEGER     NOT NULL,
            observed_at         TIMESTAMPTZ NOT NULL,
            status              TEXT        NOT NULL CHECK (status IN ('LISTED', 'CLEARED')),
            provider_fixture_id INTEGER     NOT NULL,
            provider_team_id    INTEGER,
            player_name         TEXT,
            absence_type        TEXT,
            reason              TEXT,
            payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
            origin              TEXT        NOT NULL CHECK (origin IN ('answer', 'snapshot')),
            normalizer_version  TEXT        NOT NULL,
            PRIMARY KEY (fixture_id, source, provider_player_id, observed_at)
        )""")
    op.execute("""
        COMMENT ON TABLE core.player_availability_obs IS
        'Who the provider reported missing or doubtful for a match, and when we learned it: one row per CHANGE between
         /injuries answers (LISTED: named, with type and reason; CLEARED: no longer named for a match not yet played).
         The state at a moment is the newest row per player with observed_at <= that moment. Append-only. observed_at
         is when WE asked (not the payload index time); origin snapshot rows are the copy of core.player_absences
         taken when this table was created (plan F0, defect 8).'""")
    op.execute("CREATE INDEX player_availability_obs_player_idx "
               "ON core.player_availability_obs (provider_player_id, observed_at DESC)")
    op.execute(SEED_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS core.player_availability_obs")
