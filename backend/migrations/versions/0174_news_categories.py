"""Four more categories of a story: awards, ceremonies, controversies and current affairs (C-06 1.1; AP-N01 to AP-N06)

WHY THIS EXISTS
---------------
The plan of corrections UX/UI asks the news for general stories too, not only those of a match: awards (premios), ceremonies and draws
(ceremonias), controversies (polemicas) and general current affairs (actualidad), next to the transfers (fichajes) and national teams
(selecciones) the front page already has. The classifier (``fbi.news.classify``, ``classify-v2``) gives them from the story's titles and
entities; this revision only lets ``news.stories.category`` hold them.

WHAT CHANGES
------------
Only the list of allowed values of ``news.stories.category``: the eight of 0146 and the four new ones, the constraint replaced, added NOT
VALID and then validated in the migration's one transaction (the lock of the DROP, waited for at most 10 s, is held while the small table
is read; only the news worker writes it and the news routes read it). No row is written; no story changes its category here.

Downgrade puts the eight back only while no story has a new category (the table keeps every version: it never rewrites one).

Revision ID: 0174
Revises: 0173
"""

from __future__ import annotations

from alembic import op

revision = "0174"
down_revision = "0173"
branch_labels = None
depends_on = None

CATEGORIES_BEFORE = ("fichajes", "bajas_y_sanciones", "declaraciones", "resultados_y_proximos", "selecciones", "colombia",
                     "internacional", "competiciones")
NEW_CATEGORIES = ("premios", "ceremonias", "polemicas", "actualidad")
CATEGORIES = CATEGORIES_BEFORE + NEW_CATEGORIES


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE news.stories DROP CONSTRAINT stories_category_check;
        ALTER TABLE news.stories ADD CONSTRAINT stories_category_check CHECK (category IN ({_in(CATEGORIES)})) NOT VALID;
    """)
    op.execute("ALTER TABLE news.stories VALIDATE CONSTRAINT stories_category_check")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM news.stories WHERE category IN ({_in(NEW_CATEGORIES)})) THEN
                RAISE EXCEPTION 'news.stories has stories of the categories of 0174: a downgrade would refuse them';
            END IF;
        END $$;
        ALTER TABLE news.stories DROP CONSTRAINT stories_category_check;
        ALTER TABLE news.stories ADD CONSTRAINT stories_category_check CHECK (category IN ({_in(CATEGORIES_BEFORE)}));
    """)
