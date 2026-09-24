"""outbound notifications: every message the bot would send, and what happened to it

One row per event, deduplicated by a key derived from the event (pick 42
created, run 118 failed...), so a notifier that runs every ten minutes never
announces the same thing twice. A row records the channel and the outcome:
sent, failed (with the reason, never the token), or skipped because no
channel is configured - which is the state until a Telegram token exists.

The bot informs. It has no way to place a bet and there is no table here that
could ask it to.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE audit.notifications (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT        NOT NULL CHECK (kind IN ('shadow_pick', 'pick_settled', 'first_capture',
                                                     'capture_failed', 'worker_down')),
    dedup_key   TEXT        NOT NULL UNIQUE,
    title       TEXT        NOT NULL,
    body        TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel     TEXT,
    status      TEXT        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'skipped', 'failed')),
    attempts    INTEGER     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    sent_at     TIMESTAMPTZ,
    last_error  TEXT,
    CHECK (status <> 'sent' OR (sent_at IS NOT NULL AND channel IS NOT NULL)),
    CHECK (status <> 'failed' OR last_error IS NOT NULL)
);
CREATE INDEX ON audit.notifications (status, created_at);
COMMENT ON TABLE audit.notifications IS
  'Every message the notifier produced and its fate. Informational only: nothing here can place a bet.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS audit.notifications;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
