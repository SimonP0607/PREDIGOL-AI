"""Account and access: one-use links for invitations, password recovery and unlocking, and the invited and deleted
states of an account (plan UX, A7)

WHY THIS EXISTS
---------------
Until A7 the owner creates every account with a temporary password handed over by other means (R25 of the security
plan), and a reader who forgets their password depends on the owner. A7 adds the three links a reader receives by
e-mail - an invitation, a password reset and an unlock - and two states of an account: ``invited`` (created by an
invitation, not activated yet) and ``deleted`` (anonymised at the reader's request, with the owner's confirmation).

WHAT CHANGES
------------
- ``auth.account_tokens``: one row per link. The link itself is never stored: the row keeps a random nonce, and the
  messenger derives the link when the e-mail leaves (an HMAC of the row's id and its 256-bit random nonce under the
  server's key, FBI_AUTH_SECRET_KEY) and stores only its SHA-256 - the same link at every retry of the same e-mail,
  and a copy of the database alone cannot produce one. A link works once (``used_at``), until it expires (counted
  from when it was sent: 7 days for an invitation, 30 minutes for a password reset - R25 of the security plan - and
  1 hour for an unlock) and while no newer link of the same kind replaced it (``revoked_at``). No IP, no device, no address: the limits of requests per client live in the API's memory, as a
  hash of short life (plan UX, section 17). Rows are kept 30 days after they were used, expired or replaced (the
  messenger's purge, born dry).
- ``auth.users.status`` admits ``invited`` and ``deleted``. Both keep a random Argon2id hash nobody knows the password
  of, so the rule of ``password_hash`` does not change and neither can sign in.

The worker cannot see the table (db/grants.sql revokes all of ``auth`` from it). Like a session or a recovery code,
a link means nothing without its account (ON DELETE CASCADE) - and an account is never deleted, only anonymised.

Downgrade: only while no account is ``invited`` or ``deleted`` (the previous code knows only ``active`` and
``disabled``); otherwise the way back is the switch (FBI_SELF_SERVICE=0) and not this migration.
"""

from alembic import op

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE auth.account_tokens (
            id             BIGSERIAL   PRIMARY KEY,
            user_id        BIGINT      NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
            purpose        TEXT        NOT NULL CHECK (purpose IN ('invite', 'reset', 'unlock')),
            nonce          BYTEA       NOT NULL CHECK (octet_length(nonce) = 32),
            token_hash     TEXT        UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            sent_at        TIMESTAMPTZ,
            expires_at     TIMESTAMPTZ,
            used_at        TIMESTAMPTZ,
            revoked_at     TIMESTAMPTZ,
            revoked_reason TEXT
                           CHECK (revoked_reason IN ('superseded', 'password_changed', 'account_closed',
                                                     'too_many_codes')),
            CHECK ((token_hash IS NULL) = (sent_at IS NULL)),
            CHECK ((sent_at IS NULL) = (expires_at IS NULL)),
            CHECK (expires_at IS NULL OR expires_at > sent_at),
            CHECK (used_at IS NULL OR sent_at IS NOT NULL),
            CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL)),
            CHECK (used_at IS NULL OR revoked_at IS NULL)
        );
        CREATE INDEX account_tokens_user ON auth.account_tokens (user_id, purpose, created_at DESC);
        COMMENT ON TABLE auth.account_tokens IS
          'One-use links of an account (plan UX, A7): invitation, password reset, unlock. Only the SHA-256 of a link '
          'is stored, set when its e-mail leaves; the link is derived from id and nonce under the server''s key. No '
          'IP, device or address. Kept 30 days after use, expiry or replacement.';

        ALTER TABLE auth.users DROP CONSTRAINT users_status_check;
        ALTER TABLE auth.users ADD CONSTRAINT users_status_check
            CHECK (status IN ('active', 'disabled', 'invited', 'deleted'));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM auth.users WHERE status IN ('invited', 'deleted')) THEN
                RAISE EXCEPTION 'accounts are invited or deleted: the previous code knows only active and disabled. '
                                'Go back with FBI_SELF_SERVICE=0 instead (plan UX, A7, rollback)';
            END IF;
        END
        $guard$;
        ALTER TABLE auth.users DROP CONSTRAINT users_status_check;
        ALTER TABLE auth.users ADD CONSTRAINT users_status_check CHECK (status IN ('active', 'disabled'));
        DROP TABLE auth.account_tokens;
    """)
