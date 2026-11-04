"""The readers' notices on their devices: Web Push, the bell of a match and the queue (plan UX, B7 and section 34)

WHY THIS EXISTS
---------------
The result of what a reader saved, the line-ups of their teams, a reminder they asked for, a word on their account:
useful notices, asked for in context, with categories, quiet hours and a daily ceiling - and switched off in a tap. On an
iPhone they need the installed app (iOS 16.4 or later). PrediGol sends them itself, with its own VAPID keys (P12), no
intermediate provider. Nothing of PrediGol Intelligence reads these tables (the worker cannot: db/grants.sql treats
``customer`` as ``auth``).

WHAT CHANGES
------------
- ``customer.push_subscriptions``: one row per browser a reader allowed - the push service's URL and what the browser gave
  to encrypt a notice for it alone (``p256dh``, its public key, and ``auth``, the value it shares with PrediGol: the
  names of the W3C Push API), the browser's family and system, whether it
  was the installed app, the last delivery that worked. Revoked, never edited: by the reader (``unsubscribed``), by the
  push service (``gone``: 404 or 410), by another account taking the same browser (``replaced``) or after failing again
  and again (``failing``). Only one live row per URL.
- ``customer.match_alerts``: the bell of a match - «avísame N minutos antes» (15, 30 or 60), one per reader and match.
- ``customer.push_notices``: the queue - one notice per reader and ``dedup_key`` (never twice, whatever the devices),
  its category, its words in the reader's language (a title and a line, no personal detail beyond what the reader saved),
  the page of PrediGol it opens (a path: never another site, not even as ``//host``), from when it may go (``not_before``: the quiet hours) and until when it is worth sending
  (``expires_at``), and its fate: sent (to how many devices) or dropped (and why).
- ``customer.preferences.push_off``: the categories the reader switched off (result, lineup, digest, account).

The foreign keys to ``auth.users`` are ON DELETE RESTRICT: an account is anonymised, never deleted (A7) - and these rows go
then. A match's bell goes with the match (a fixture deleted by the provider's correction).

Downgrade: drops the three tables and the column only while no reader has a device, a bell or a notice. With them the
code goes back and the tables stay (FBI_PUSH=0 is the rollback: nothing sent, the invitation hidden).
"""

from alembic import op

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE customer.push_subscriptions (
            id              BIGSERIAL   PRIMARY KEY,
            user_id         BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            endpoint        TEXT        NOT NULL CHECK (char_length(endpoint) BETWEEN 12 AND 1024 AND endpoint ~ '^https?://'),
            p256dh          TEXT        NOT NULL CHECK (p256dh ~ '^[A-Za-z0-9_-]{86,88}$'),
            auth            TEXT        NOT NULL CHECK (auth ~ '^[A-Za-z0-9_-]{21,24}$'),
            family          TEXT        NOT NULL CHECK (family IN ('chrome', 'firefox', 'safari', 'edge', 'other')),
            system          TEXT        NOT NULL CHECK (system IN ('android', 'ios', 'windows', 'macos', 'linux', 'other')),
            installed       BOOLEAN     NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_ok_at      TIMESTAMPTZ,
            failures        SMALLINT    NOT NULL DEFAULT 0 CHECK (failures >= 0),
            revoked_at      TIMESTAMPTZ,
            revoked_reason  TEXT        CHECK (revoked_reason IN ('unsubscribed', 'gone', 'replaced', 'failing')),
            CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL))
        );
        CREATE UNIQUE INDEX push_subscriptions_one_live ON customer.push_subscriptions (endpoint) WHERE revoked_at IS NULL;
        CREATE INDEX push_subscriptions_of_reader ON customer.push_subscriptions (user_id) WHERE revoked_at IS NULL;
        COMMENT ON TABLE customer.push_subscriptions IS
          'The browsers a reader allowed to receive PrediGol''s notices (plan UX, B7): the push service''s URL and the '
          'browser''s p256dh and auth, which encrypt a notice for it alone. Revoked, never edited. Never read by '
          'PrediGol Intelligence. Deleted when the account is anonymised (A7).';

        CREATE TABLE customer.match_alerts (
            user_id         BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            fixture_id      BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            minutes_before  SMALLINT    NOT NULL DEFAULT 30 CHECK (minutes_before IN (15, 30, 60)),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, fixture_id)
        );
        CREATE INDEX match_alerts_by_fixture ON customer.match_alerts (fixture_id);
        COMMENT ON TABLE customer.match_alerts IS
          'The bell of a match (plan UX, B7): «avísame N minutos antes», asked for by the reader. Following a team (the '
          'star, A13) is something else. Deleted when the account is anonymised (A7).';

        CREATE TABLE customer.push_notices (
            id          BIGSERIAL   PRIMARY KEY,
            user_id     BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            category    TEXT        NOT NULL CHECK (category IN ('result', 'lineup', 'digest', 'reminder', 'account', 'test')),
            dedup_key   TEXT        NOT NULL CHECK (dedup_key ~ '^[a-z_]+:[A-Za-z0-9:_-]{1,100}$'),
            title       TEXT        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
            body        TEXT        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 300),
            url         TEXT        NOT NULL CHECK (url ~ '^/([A-Za-z0-9_?=&#.-][A-Za-z0-9/_?=&#.-]{0,198})?$'),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            not_before  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at  TIMESTAMPTZ NOT NULL,
            status      TEXT        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'dropped')),
            sent_at     TIMESTAMPTZ,
            devices     SMALLINT    CHECK (devices >= 0),
            dropped     TEXT        CHECK (dropped IN ('expired', 'daily_cap', 'no_device', 'category_off', 'failed')),
            CHECK ((status = 'sent') = (sent_at IS NOT NULL AND devices IS NOT NULL)),
            CHECK ((status = 'dropped') = (dropped IS NOT NULL)),
            CHECK (expires_at > created_at),
            UNIQUE (user_id, dedup_key)
        );
        CREATE INDEX push_notices_due ON customer.push_notices (not_before) WHERE status = 'queued';
        CREATE INDEX push_notices_sent_by_reader ON customer.push_notices (user_id, sent_at) WHERE status = 'sent';
        CREATE INDEX push_notices_by_date ON customer.push_notices (created_at);
        COMMENT ON TABLE customer.push_notices IS
          'The queue of the readers'' notices (plan UX, B7): one per reader and dedup_key, its words in the reader''s '
          'language, from when it may go (the quiet hours) and until when it is worth sending; sent or dropped and why. '
          'Deleted when the account is anonymised (A7); kept 90 days.';

        ALTER TABLE customer.preferences
            ADD COLUMN push_off TEXT[] NOT NULL DEFAULT '{}'
                CHECK (push_off <@ ARRAY['result', 'lineup', 'digest', 'account']::TEXT[]);
        COMMENT ON COLUMN customer.preferences.push_off IS
          'The categories of notices on their devices the reader switched off (plan UX, B7).';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.push_subscriptions) OR EXISTS (SELECT 1 FROM customer.match_alerts)
               OR EXISTS (SELECT 1 FROM customer.push_notices)
               OR EXISTS (SELECT 1 FROM customer.preferences WHERE push_off <> '{}') THEN
                RAISE EXCEPTION 'customer.push_subscriptions, customer.match_alerts or customer.push_notices hold readers'' '
                                'devices, bells or notices: the code goes back, the tables stay';
            END IF;
        END $$;
        ALTER TABLE customer.preferences DROP COLUMN push_off;
        DROP TABLE customer.push_notices;
        DROP TABLE customer.match_alerts;
        DROP TABLE customer.push_subscriptions;
    """)
