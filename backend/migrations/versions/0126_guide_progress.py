"""What each reader has seen of the welcome tour and of the guides of each screen (plan UX-032; PLAN_BIENVENIDA_RECORRIDO)

WHY THIS EXISTS
---------------
The product is getting one engine of guides (UX-033 to UX-035): an optional general tour, an optional first-visit guide for
each screen, and the first guide of Perfil, which is owed once. Each is shown once per person and per version, can be paused
and resumed, and can be shown again from Ayuda. That needs to be remembered per person, not per browser (a phone and a
laptop are one reader; Safari may clear a page's storage after a week of not visiting) and with more than «seen»: when,
which step, and which version of the content. ``customer.preferences.hints_seen`` is a list of bare marks (and already
holds dismissed suggestions and market order), so it cannot say any of that.

WHAT CHANGES
------------
- ``customer.guide_progress``: one row per reader and guide (a closed list of ten: ``general``, ``home``, ``matches``,
  ``live``, ``match``, ``picks``, ``parlays``, ``odds``, ``my_picks``, ``profile``) with the version of the content seen, its
  status (``pending``: the screen was visited and the guide not yet shown; ``in_progress``; ``completed``; ``skipped``), the
  last step reached, when the screen was first visited, when the guide was started, completed or skipped. The closed lists
  and the coherence of the dates are CHECKs of the table, not only of the code.
- ``customer.preferences.guides_auto``: the reader's own switch «mostrar guías al entrar a cada pantalla» (on by default).

Functional state, needed to show each guide once: it is kept for every reader, it goes out in «Copia de tus datos» and it is
deleted when the account is anonymised. It is never used for analytics (the four ``guide_*`` events of the closed catalog
are the only measurement, and only with consent).

``customer`` is the API's schema (the worker cannot read it); the grants are deploy/vps/db/grants.sql. Every foreign key to
``auth.users`` is ON DELETE RESTRICT (an account is anonymised, never deleted).

Downgrade: drops the table and the column only while no reader has a row and nobody switched the guides off (with them the
code goes back and the table stays: nothing reads it).
"""

from alembic import op

revision = "0126"
down_revision = "0125"
branch_labels = None
depends_on = None

GUIDES = ("general", "home", "matches", "live", "match", "picks", "parlays", "odds", "my_picks", "profile")
STATUSES = ("pending", "in_progress", "completed", "skipped")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE customer.guide_progress (
            user_id        BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            guide          TEXT        NOT NULL CHECK (guide IN ({_in(GUIDES)})),
            version        SMALLINT    NOT NULL CHECK (version BETWEEN 1 AND 99),
            status         TEXT        NOT NULL CHECK (status IN ({_in(STATUSES)})),
            step           SMALLINT    NOT NULL DEFAULT 0 CHECK (step BETWEEN 0 AND 9),
            first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at     TIMESTAMPTZ,
            completed_at   TIMESTAMPTZ,
            skipped_at     TIMESTAMPTZ,
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, guide),
            CHECK ((status = 'pending') = (started_at IS NULL)),
            CHECK ((status = 'completed') = (completed_at IS NOT NULL)),
            CHECK ((status = 'skipped') = (skipped_at IS NOT NULL))
        );
        COMMENT ON TABLE customer.guide_progress IS
          'What a reader has seen of each guide (the general tour and the first visit to each screen), per version of the '
          'content. pending: the screen was visited and the guide not yet shown. completed does not go back within a '
          'version. Functional state: in the reader''s export, deleted when the account is anonymised, never used for analytics.';

        ALTER TABLE customer.preferences ADD COLUMN guides_auto BOOLEAN NOT NULL DEFAULT TRUE;
        COMMENT ON COLUMN customer.preferences.guides_auto IS
          'The reader''s own switch: show the guide of each screen on the first visit (on by default).';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.guide_progress)
               OR EXISTS (SELECT 1 FROM customer.preferences WHERE NOT guides_auto) THEN
                RAISE EXCEPTION 'readers have guide progress or switched the guides off: the code goes back and the table stays';
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE customer.preferences DROP COLUMN guides_auto")
    op.execute("DROP TABLE customer.guide_progress")
