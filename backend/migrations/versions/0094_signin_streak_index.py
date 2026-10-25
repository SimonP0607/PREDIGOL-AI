"""An index for an address's sign-in streak (plan UX, A1; R12)

WHY THIS EXISTS
---------------
A1 locks every address that fails to sign in by the account's rule - with or without an account, so the answers never
tell which addresses have one (R12). The streak of an address is read from ``auth.audit_events``, which records every
failure with its address and is shared by the API's worker processes (a count kept in one process's memory locked an
address without an account later than one with: review of A1). Read through the time index alone, every sign-in
attempt scanned thirty days of the whole trail - a cost an attacker could grow at will with failures of invented
addresses (second review of A1).

WHAT CHANGES
------------
One partial index: ``auth.audit_events (email, at DESC)`` for the five actions a streak is made of (a wrong password,
a wrong second-factor code, and what ends a streak: a finished sign-in, an unlock, a password reset). Reading an
address's streak becomes reading that address's rows. No row is written or changed; the code before A1 never reads it.
The trail is small (a few rows per sign-in): the index builds at once, inside the migration's transaction.

Downgrade: drops the index. Nothing depends on it but the speed of ``fbi.auth.store.address_streak``.
"""

from alembic import op

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None

ACTIONS = "'login.failed', 'mfa.failed', 'login.succeeded', 'user.unlocked', 'password.reset'"


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"CREATE INDEX IF NOT EXISTS audit_events_signin_idx ON auth.audit_events (email, at DESC) "
               f"WHERE action IN ({ACTIONS})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP INDEX IF EXISTS auth.audit_events_signin_idx")
