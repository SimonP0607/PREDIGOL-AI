"""The owner's communiqués to readers: a banner, an entry of Novedades, a Telegram post, a critical e-mail (plan de cierre UX, 4.3)

WHY THIS EXISTS
---------------
The owner needs to tell readers something the product cannot tell by itself: a maintenance window, an incident, an update
worth reading, a general word. The closing plan (4.3) gives that a console with four closed kinds - ``maintenance``,
``incident``, ``update`` and ``general`` (there is no «promotion») - a preview, a double confirmation, a daily cap and a
record. It is the owner's words, written in both languages; nothing here is computed from the models, the picks or any
reader's data.

WHAT CHANGES
------------
- ``customer.announcements``: one row per communiqué - its kind, its title and text in Spanish and English, the dates it
  is shown between, where it goes (the banner of the app, the entries of Novedades, the Telegram channel, an e-mail to
  every reader) and its state: ``draft`` (editable), ``published`` and ``retracted`` (hidden again; never deleted). The
  rules of the plan are CHECKs of the table, not only of the code: only an update goes to Novedades, only a maintenance or
  an incident can be critical, and an e-mail goes only if the communiqué is critical. The confirmation of a publication
  is a code the owner receives in the preview and sends back with a typed word: the table keeps its hash and its expiry.
- ``customer.announcement_log``: what was done to each communiqué and by whom (created, edited, previewed, published,
  retracted, the Telegram post and the e-mails queued), append-only (a trigger refuses to change or delete a line).
- Neither table may be deleted from: a trigger refuses it. History is never erased.

Nothing is written by this revision. ``customer`` is the API's schema (the worker cannot read it); the grants are
db/grants.sql.

Downgrade: drops both tables - only while no communiqué was ever created (with them the code goes back and the tables
stay: nothing reads them).
"""

from alembic import op

revision = "0124"
down_revision = "0123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE customer.announcements (
            id                 BIGSERIAL PRIMARY KEY,
            kind               TEXT        NOT NULL CHECK (kind IN ('maintenance', 'incident', 'update', 'general')),
            title_es           TEXT        NOT NULL CHECK (char_length(title_es) BETWEEN 3 AND 80),
            title_en           TEXT        NOT NULL CHECK (char_length(title_en) BETWEEN 3 AND 80),
            body_es            TEXT        NOT NULL CHECK (char_length(body_es) BETWEEN 3 AND 600),
            body_en            TEXT        NOT NULL CHECK (char_length(body_en) BETWEEN 3 AND 600),
            starts_at          TIMESTAMPTZ NOT NULL,
            ends_at            TIMESTAMPTZ NOT NULL,
            to_banner          BOOLEAN     NOT NULL DEFAULT TRUE,
            to_updates         BOOLEAN     NOT NULL DEFAULT FALSE,
            to_telegram        BOOLEAN     NOT NULL DEFAULT FALSE,
            to_email           BOOLEAN     NOT NULL DEFAULT FALSE,
            critical           BOOLEAN     NOT NULL DEFAULT FALSE,
            status             TEXT        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'retracted')),
            created_by         BIGINT      NOT NULL,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            confirm_hash       TEXT,
            confirm_expires_at TIMESTAMPTZ,
            published_by       BIGINT,
            published_at       TIMESTAMPTZ,
            retracted_by       BIGINT,
            retracted_at       TIMESTAMPTZ,
            CHECK (ends_at > starts_at),
            CHECK (NOT to_updates OR kind = 'update'),
            CHECK (NOT critical OR kind IN ('maintenance', 'incident')),
            CHECK (NOT to_email OR critical),
            CHECK (to_banner OR to_updates OR to_telegram OR to_email),
            CHECK ((status = 'published') = (published_at IS NOT NULL) OR status = 'retracted'),
            CHECK ((status = 'retracted') = (retracted_at IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX announcements_active ON customer.announcements (status, starts_at, ends_at)")
    op.execute(r"""
        CREATE TABLE customer.announcement_log (
            id              BIGSERIAL PRIMARY KEY,
            announcement_id BIGINT      NOT NULL REFERENCES customer.announcements (id),
            action          TEXT        NOT NULL CHECK (action IN
                ('created', 'edited', 'previewed', 'published', 'retracted', 'telegram', 'emails')),
            actor_user_id   BIGINT,
            detail          JSONB       NOT NULL DEFAULT '{}'::jsonb,
            at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX announcement_log_by_announcement ON customer.announcement_log (announcement_id, at)")
    op.execute(r"""
        CREATE FUNCTION customer.announcements_never_deleted() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION 'communiqués and their record are never deleted';
        END
        $fn$
    """)
    op.execute("""
        CREATE TRIGGER announcements_no_delete BEFORE DELETE ON customer.announcements
        FOR EACH ROW EXECUTE FUNCTION customer.announcements_never_deleted()
    """)
    op.execute(r"""
        CREATE FUNCTION customer.announcement_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION 'the record of communiqués is append-only';
        END
        $fn$
    """)
    op.execute("""
        CREATE TRIGGER announcement_log_append_only BEFORE UPDATE OR DELETE ON customer.announcement_log
        FOR EACH ROW EXECUTE FUNCTION customer.announcement_log_append_only()
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.announcements) THEN
                RAISE EXCEPTION 'communiqués exist: they are never deleted; the code goes back and the tables stay';
            END IF;
        END
        $$
    """)
    op.execute("DROP TABLE customer.announcement_log")
    op.execute("DROP TABLE customer.announcements")
    op.execute("DROP FUNCTION customer.announcement_log_append_only()")
    op.execute("DROP FUNCTION customer.announcements_never_deleted()")
