"""users, sessions and roles

The platform gets people. Until now there was one reader - the owner, on his own
machine - and the API answered anyone who could reach it. That stops here:

* ``auth.roles``    the roles that exist. Two today (SUPER_ADMIN, USER); a new one is
                    a row here plus its permissions in ``fbi.auth.roles`` - never a
                    rename of these.
* ``auth.users``    who can sign in. The password is stored as an Argon2id hash and
                    nothing else; the address is kept lower-cased and trimmed, so one
                    person cannot hold two accounts that differ only in case.
* ``auth.sessions`` one row per signed-in browser. The cookie carries a random token;
                    the row is keyed by its SHA-256, so a copy of this table cannot be
                    replayed as a cookie.
* ``auth.audit_events`` who signed in, who failed to, who changed whose role. Written
                    by the API, read by the Admin Console; never by the product pages.

Everything else in the database stays read-only to the product API: these four tables
are the only ones it writes.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE SCHEMA IF NOT EXISTS auth;
COMMENT ON SCHEMA auth IS
  'People and their sessions. The only schema the product API writes to.';

CREATE TABLE auth.roles (
    key          TEXT PRIMARY KEY CHECK (key ~ '^[A-Z][A-Z_]{1,31}$'),
    description  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE auth.roles IS
  'Roles that exist. What each one may do is decided in code (fbi.auth.roles), so that a
   permission can never be granted by editing a row.';
INSERT INTO auth.roles (key, description) VALUES
  ('SUPER_ADMIN', 'Everything: the product, the Admin Console, research, users and system.'),
  ('USER',        'The product: home, matches, live, qualified picks, valid parlays, odds, profile.');

CREATE TABLE auth.users (
    id                   BIGSERIAL PRIMARY KEY,
    email                TEXT NOT NULL
                         CHECK (email = lower(btrim(email)) AND length(email) BETWEEN 3 AND 254
                                AND email ~ '^[^@[:space:]]+@[^@[:space:]]+$'),
    display_name         TEXT NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 80),
    password_hash        TEXT NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
    role                 TEXT NOT NULL DEFAULT 'USER' REFERENCES auth.roles(key),
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    language             TEXT NOT NULL DEFAULT 'es' CHECK (language IN ('es', 'en')),
    timezone             TEXT NOT NULL DEFAULT 'UTC' CHECK (length(timezone) BETWEEN 1 AND 64),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at        TIMESTAMPTZ,
    password_changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_key ON auth.users (email);
COMMENT ON COLUMN auth.users.password_hash IS
  'Argon2id, parameters embedded in the string. The password itself is never stored or logged.';
COMMENT ON COLUMN auth.users.timezone IS
  'IANA name (Europe/Madrid, America/Bogota). The database stays in UTC; this only decides how a time is shown.';

CREATE TABLE auth.sessions (
    id              TEXT PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    user_id         BIGINT NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT,
    user_agent      TEXT CHECK (length(user_agent) <= 300),
    ip              TEXT CHECK (length(ip) <= 64),
    CHECK (expires_at > created_at),
    CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL))
);
CREATE INDEX sessions_user_active_idx ON auth.sessions (user_id) WHERE revoked_at IS NULL;
COMMENT ON COLUMN auth.sessions.id IS
  'SHA-256 (hex) of the token in the cookie. The token is never stored: this table cannot be replayed.';

CREATE TABLE auth.audit_events (
    id              BIGSERIAL PRIMARY KEY,
    at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    action          TEXT NOT NULL CHECK (action ~ '^[a-z][a-z_.]{2,40}$'),
    actor_user_id   BIGINT REFERENCES auth.users(id) ON DELETE SET NULL,
    target_user_id  BIGINT REFERENCES auth.users(id) ON DELETE SET NULL,
    email           TEXT CHECK (length(email) <= 254),
    ip              TEXT CHECK (length(ip) <= 64),
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_events_at_idx ON auth.audit_events (at DESC);
CREATE INDEX audit_events_target_idx ON auth.audit_events (target_user_id, at DESC);
COMMENT ON TABLE auth.audit_events IS
  'Sign-ins, failed sign-ins, sign-outs, role and status changes. Never contains a password or a token.';
"""

DOWNGRADE = """
DROP SCHEMA IF EXISTS auth CASCADE;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
