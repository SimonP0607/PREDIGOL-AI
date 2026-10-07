"""auth: second factor (TOTP + recovery codes), account lock-out, staged sessions, forced password change

Before the beta goes on the internet (owner's decision of 7 Oct 2026):

* auth.users gains the lock-out counters (failed_logins, locked_until), must_change_password (an account created or
  reset by an administrator signs in once with a temporary password and must choose its own), mfa_required (a
  second factor demanded of this account even when its role does not demand it) and its TOTP secret - encrypted
  with AES-256-GCM under FBI_AUTH_SECRET_KEY, which never enters the database - with the step of the last code
  accepted (a code is never accepted twice).
* auth.sessions gains a stage. A correct password opens a session that can do nothing but finish signing in:
  'mfa' (type the code), 'enroll' (set up the authenticator the role requires) or 'password' (choose a new one).
  Only 'full' reaches the product. A staged session lives ten minutes and allows five wrong codes.
* auth.recovery_codes: single-use codes for a lost phone, stored as keyed hashes.

Every SUPER_ADMIN session open at upgrade time is revoked: the role now requires a second factor, and a session
opened before would otherwise skip it until it expired (up to seven days). Signing in again is all it costs.

Downgrade drops the second factor and the stages. Staged sessions are deleted first: without the stage column
they would become full sessions.

Revision ID: 0070
Revises: 0069
"""

from __future__ import annotations

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None

UPGRADE = r"""
ALTER TABLE auth.users
    ADD COLUMN failed_logins         INTEGER NOT NULL DEFAULT 0 CHECK (failed_logins >= 0),
    ADD COLUMN locked_until          TIMESTAMPTZ,
    ADD COLUMN must_change_password  BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN mfa_required          BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN totp_secret           BYTEA,
    ADD COLUMN totp_enabled_at       TIMESTAMPTZ,
    ADD COLUMN totp_last_step        BIGINT,
    ADD CONSTRAINT users_totp_consistent CHECK ((totp_secret IS NULL) = (totp_enabled_at IS NULL));
COMMENT ON COLUMN auth.users.totp_secret IS
  'AES-256-GCM under FBI_AUTH_SECRET_KEY (never stored in the database), the user id as associated data.';
COMMENT ON COLUMN auth.users.totp_last_step IS
  'Time step (30 s) of the last code accepted: that code and older ones are refused - no replay.';
COMMENT ON COLUMN auth.users.locked_until IS
  'After lock_threshold consecutive failures (password or code) sign-in is refused until then.';

ALTER TABLE auth.sessions
    ADD COLUMN stage                TEXT NOT NULL DEFAULT 'full'
                                    CHECK (stage IN ('mfa', 'enroll', 'password', 'full')),
    ADD COLUMN mfa_attempts         SMALLINT NOT NULL DEFAULT 0 CHECK (mfa_attempts >= 0),
    ADD COLUMN pending_totp_secret  BYTEA,
    ADD COLUMN mfa_verified_at      TIMESTAMPTZ;
COMMENT ON COLUMN auth.sessions.stage IS
  'full reaches the product; mfa / enroll / password can only finish signing in (and live ten minutes).';

CREATE TABLE auth.recovery_codes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    code_hash   TEXT NOT NULL CHECK (code_hash ~ '^[0-9a-f]{64}$'),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    used_at     TIMESTAMPTZ
);
CREATE UNIQUE INDEX recovery_codes_user_hash_key ON auth.recovery_codes (user_id, code_hash);
CREATE INDEX recovery_codes_unused_idx ON auth.recovery_codes (user_id) WHERE used_at IS NULL;
COMMENT ON TABLE auth.recovery_codes IS
  'Single-use codes for a lost authenticator. HMAC-SHA256 keyed from FBI_AUTH_SECRET_KEY; the codes themselves are
   shown once and never stored.';

UPDATE auth.sessions s SET revoked_at = now(), revoked_reason = 'second_factor_introduced'
FROM auth.users u
WHERE u.id = s.user_id AND u.role = 'SUPER_ADMIN' AND s.revoked_at IS NULL;
"""

DOWNGRADE = r"""
DELETE FROM auth.sessions WHERE stage <> 'full';
DROP TABLE IF EXISTS auth.recovery_codes;
ALTER TABLE auth.sessions
    DROP COLUMN IF EXISTS mfa_verified_at,
    DROP COLUMN IF EXISTS pending_totp_secret,
    DROP COLUMN IF EXISTS mfa_attempts,
    DROP COLUMN IF EXISTS stage;
ALTER TABLE auth.users
    DROP CONSTRAINT IF EXISTS users_totp_consistent,
    DROP COLUMN IF EXISTS totp_last_step,
    DROP COLUMN IF EXISTS totp_enabled_at,
    DROP COLUMN IF EXISTS totp_secret,
    DROP COLUMN IF EXISTS mfa_required,
    DROP COLUMN IF EXISTS must_change_password,
    DROP COLUMN IF EXISTS locked_until,
    DROP COLUMN IF EXISTS failed_logins;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
