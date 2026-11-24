"""The Spanish and English names of national teams and competitions as aliases (C-10 1.1; AP-B02, AP-B07, AP-E02)

WHY THIS EXISTS
---------------
The search v2 (``/search/v2``, C-10) finds an entity by its own name and by the rows of ``core.entity_aliases``. The provider names
national teams in English and competitions in English or in their own language, so a reader who types «España», «Inglaterra»,
«Alemania» or «Mundial» found nothing of its own and the web had to translate on its side (AP-B02's local fallback). The names now
come from a reviewed table in the code (``fbi.people.identity.localized``: Unicode CLDR 48 country names, the four UK nations and
the competitions written by hand) and enter ``core.entity_aliases`` with the load of our own names (``scripts.entity_identity
sync-core``), as ``alias_type`` ``localized`` with their language - a type the table already allows.

WHAT CHANGES
------------
Only the list of allowed values of ``core.entity_aliases.source``: ``localized`` is added. The constraint is replaced by one with
the old values plus the new one, added NOT VALID and then validated (the validation reads the table under a lock that lets reads
and writes go on). No row is written, no column or other table is touched.

Downgrade puts the old list back only while no row has the new source: the table is append-only, so it never deletes an alias
(retire the load that added them first, or restore the backup).

Revision ID: 0173
Revises: 0172
"""

from __future__ import annotations

from alembic import op

revision = "0173"
down_revision = "0172"
branch_labels = None
depends_on = None

SOURCES_BEFORE = ("api_football", "reep", "wikidata", "core.team_aliases", "core.referee_aliases", "core.referees")
NEW_SOURCES = ("localized",)
SOURCES = SOURCES_BEFORE + NEW_SOURCES


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE core.entity_aliases DROP CONSTRAINT entity_aliases_source_check;
        ALTER TABLE core.entity_aliases ADD CONSTRAINT entity_aliases_source_check CHECK (source IN ({_in(SOURCES)})) NOT VALID;
    """)
    op.execute("ALTER TABLE core.entity_aliases VALIDATE CONSTRAINT entity_aliases_source_check")
    op.execute("""
        COMMENT ON CONSTRAINT entity_aliases_source_check ON core.entity_aliases IS
        'Where an alias comes from. localized (0173, C-10 1.1): the reviewed Spanish and English names of national teams and
         competitions of fbi.people.identity.localized, loaded with our own names (sync-core).'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM core.entity_aliases WHERE source IN ({_in(NEW_SOURCES)})) THEN
                RAISE EXCEPTION 'core.entity_aliases has rows of the source localized: it is append-only, retire their load or restore the backup';
            END IF;
        END $$;
        ALTER TABLE core.entity_aliases DROP CONSTRAINT entity_aliases_source_check;
        ALTER TABLE core.entity_aliases ADD CONSTRAINT entity_aliases_source_check CHECK (source IN ({_in(SOURCES_BEFORE)}));
    """)
