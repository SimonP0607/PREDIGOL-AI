"""The news store (IA-080, plan piece AD-G01): the schema ``news`` - five append-only tables - and one nullable column of ``ai.evidence``

WHY THIS EXISTS
---------------
Today every news card is read from ``ai.evidence``: 5.721 web claims in 14 days, with no author, no picture and no article as an entity
(production, 16-nov-2026). The plan's news module (Doc 2, «La noticia y la historia»; contracts C-06 and C-07 of the UX plan) needs the
article as its own row, grouped into stories, with the people and teams it names. The names are the ones agreed with UX: ``news.items``
is the owner's ``news.articles``, ``news.item_story`` his ``news.article_story``, ``news.item_entities`` his ``news.mentions``; his
``news.claims`` is NOT a parallel table - the claims stay in ``ai.evidence``, which learns ``item_id``; and the registry of sources is the
one of IA-062 (``ai.source_registry``), not a new one.

WHAT CHANGES
------------
- ``news.feeds``: the RSS feeds and sitemaps of each source of the directory, versioned (a change is version n+1, never an edit).
- ``news.items``: one row per article and version of its content. Its identity is the sha256 of its canonical URL (the database checks
  the hash); a new content of the same URL is a new version, the same content again is nothing (``UNIQUE (url_sha256, content_sha256)``).
  Each row carries a COPY of what the source policy allowed when it was seen (``store_level``, ``publish_level``, ``ai_reserved``, the
  state and the registry's version) and four dates: published, seen, of the fact, valid until. There is no column for an article's text
  or picture: the source's own title and author are metadata (private), never shown before the lawyer answers.
- ``news.stories``: one row per story and version - the own headline and summary (empty until AD-G04), category, level, language and
  country (AD-G03) and its moderation state (AD-G05: a story withdrawn at a request is a new version, and so is putting it back).
- ``news.item_story``: which story an item belongs to; the newest row of an item decides (moving it is a new row).
- ``news.item_entities``: the teams, players and others an item names, with role, method and confidence; the newest row of an item and
  entity decides (a link taken back is a new row with ``active = false``).
- ``ai.evidence.item_id``: the article a claim was read from. Nullable, no default (instant: no row is rewritten); the foreign key is
  added NOT VALID and validated after (every row is NULL). It is content: the guard of 0072/0114 learns it, so it is written when the
  claim is inserted and never afterwards - the 20.756 rows already there (16-nov-2026) stay NULL forever.

All five tables are append-only (``ai.refuse_change()``, as every audit table since 0072; the static test of IA-059 demands it for
``news``). Nothing fills them yet: the ingestion of AD-G02 will, in shadow.

Downgrade: the guard of 0114 comes back, the column and the five tables are dropped, and so is the schema. What was written in them is lost
with them (nothing that decides or is served reads them before AD-G07).

Revision ID: 0146
Revises: 0139 (provisional: the head of this branch; the merge re-chains it)
"""

from __future__ import annotations

from alembic import op

revision = "0146"
down_revision = "0145"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
DOMAIN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
URL = "^https?://"
LANG = "^[a-z]{2,3}$"
STORY_KEY = "^st-[a-z0-9][a-z0-9-]{3,62}$"
WRITER = "^[a-z0-9][a-z0-9._:+-]{1,79}$"

# The words of the code (fbi.news.vocab): tests/unit/test_news_vocab.py holds the two together.
FEED_KINDS = ("rss", "atom", "sitemap", "news_sitemap")
FOUND_VIA = ("rss", "sitemap", "search", "official", "manual")
SOURCE_STATES = ("verificada_autorizada", "verificada_pendiente_derechos", "solo_referencia", "no_comprobada", "bloqueada",
                 "desconocida", "excluida")
STORE_LEVELS = ("facts", "link")
PUBLISH_LEVELS = ("summary", "link", "none")
CATEGORIES = ("fichajes", "bajas_y_sanciones", "declaraciones", "resultados_y_proximos", "selecciones", "colombia", "internacional",
              "competiciones")
LEVELS = ("oficial", "dos_origenes", "declaracion", "un_medio", "rumor")
CLAIM_TYPES = ("lesiones", "convocatorias", "alineaciones", "sanciones", "fichajes", "declaraciones", "resultados", "calendario",
               "reglamento", "arbitraje", "estadisticas", "contexto", "analisis", "rumores")
STATUSES = ("activa", "en_moderacion", "retirada")
GROUP_METHODS = ("url", "huella", "similitud", "entidades", "idiomas", "manual")
ENTITY_TYPES = ("team", "player", "coach", "referee", "competition", "fixture", "venue")
ROLES = ("protagonista", "mencionado")
LINK_METHODS = ("plantilla", "alias", "proveedor", "manual")
DECIDERS = ("system", "owner")
TABLES = ("feeds", "items", "stories", "item_story", "item_entities")

# The content of a claim as the guard of 0114 knows it; item_id joins it here.
CONTENT = ("fixture_id", "team_id", "provider_player_id", "kind", "claim", "origin", "source_name", "source_url", "source_domain", "source_tier",
           "author", "published_at", "retrieved_at", "event_at", "story_key", "content_hash", "payload_hash", "confidence", "relevance", "attributes",
           "claim_type", "subject_type", "subject_id", "source_class", "fresh_until")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _tuple(prefix: str, columns: tuple[str, ...]) -> str:
    return ", ".join(f"{prefix}.{c}" for c in columns)


def _guard(columns: tuple[str, ...]) -> str:
    """The guard of 0072 and 0114, with the columns given as the content that never changes."""
    return f"""
        CREATE OR REPLACE FUNCTION ai.evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF coalesce(current_setting('fbi.ai_maintenance', true), '') = 'on' THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'ai.evidence: rows are never deleted' USING ERRCODE = 'check_violation';
            END IF;
            IF ({_tuple("NEW", columns)})
               IS DISTINCT FROM
               ({_tuple("OLD", columns)}) THEN
                RAISE EXCEPTION 'ai.evidence: the content of evidence never changes (store a new row)'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status OR NEW.status_reason IS DISTINCT FROM OLD.status_reason THEN
                NEW.status_history := OLD.status_history || jsonb_build_array(jsonb_build_object(
                    'status', OLD.status, 'reason', OLD.status_reason, 'from', OLD.status_changed_at,
                    'until', NEW.status_changed_at));
            ELSE
                NEW.status_history := OLD.status_history;
            END IF;
            RETURN NEW;
        END
        $fn$;
    """


def _hash_of(column: str) -> str:
    return f"encode(sha256(convert_to({column}, 'UTF8')), 'hex')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE SCHEMA news;
        COMMENT ON SCHEMA news IS
          'IA-080 (AD-G01): the news store - feeds, articles (items), stories and the entities an article names. Every table is '
          'append-only; a change is a new row. The claims of an article stay in ai.evidence (item_id).';

        CREATE TABLE news.feeds (
            id             BIGSERIAL    PRIMARY KEY,
            url_sha256     TEXT         NOT NULL CHECK (url_sha256 ~ '{SHA256}'),
            version        INTEGER      NOT NULL CHECK (version >= 1),
            previous_id    BIGINT       REFERENCES news.feeds(id),
            url            TEXT         NOT NULL CHECK (url ~ '{URL}' AND length(url) <= 2000),
            kind           TEXT         NOT NULL CHECK (kind IN ({_in(FEED_KINDS)})),
            source_id      TEXT         NOT NULL CHECK (length(source_id) BETWEEN 1 AND 120),
            source_domain  TEXT         NOT NULL CHECK (source_domain ~ '{DOMAIN}'),
            lang           TEXT         CHECK (lang ~ '{LANG}'),
            country        TEXT         CHECK (length(country) BETWEEN 1 AND 60),
            active         BOOLEAN      NOT NULL DEFAULT true,
            at             TIMESTAMPTZ  NOT NULL,
            added_by       TEXT         NOT NULL CHECK (added_by IN ('loader', 'owner', 'system')),
            reason         TEXT         CHECK (length(reason) BETWEEN 1 AND 300),
            UNIQUE (url_sha256, version),
            CHECK ((version = 1) = (previous_id IS NULL)),
            CONSTRAINT feeds_url_identity CHECK (url_sha256 = {_hash_of('url')})
        );
        COMMENT ON TABLE news.feeds IS
          'IA-080: the RSS feeds and sitemaps of a source of the directory (ai.source_registry, by source_id), one row per feed and version. '
          'The newest version of a url_sha256 is in force; active = false takes the feed out. Whether it may be read is the source policy''s '
          'decision at the moment of reading (fbi.ai.source_policy.can_fetch), not this table''s.';

        CREATE TABLE news.items (
            id                    BIGSERIAL    PRIMARY KEY,
            url_sha256            TEXT         NOT NULL CHECK (url_sha256 ~ '{SHA256}'),
            version               INTEGER      NOT NULL CHECK (version >= 1),
            previous_id           BIGINT       REFERENCES news.items(id),
            url                   TEXT         NOT NULL CHECK (url ~ '{URL}' AND length(url) <= 2000),
            canonical_url         TEXT         NOT NULL CHECK (canonical_url ~ '{URL}' AND length(canonical_url) <= 2000),
            canon_version         TEXT         NOT NULL CHECK (canon_version ~ '{WRITER}'),
            content_sha256        TEXT         NOT NULL CHECK (content_sha256 ~ '{SHA256}'),
            fingerprint_version   TEXT         NOT NULL CHECK (fingerprint_version ~ '{WRITER}'),
            simhash               BIGINT,
            feed_id               BIGINT       REFERENCES news.feeds(id),
            found_via             TEXT         NOT NULL CHECK (found_via IN ({_in(FOUND_VIA)})),
            source_id             TEXT         CHECK (length(source_id) BETWEEN 1 AND 120),
            source_domain         TEXT         NOT NULL CHECK (source_domain ~ '{DOMAIN}'),
            source_name           TEXT         NOT NULL CHECK (length(btrim(source_name)) BETWEEN 1 AND 200),
            source_state          TEXT         NOT NULL CHECK (source_state IN ({_in(SOURCE_STATES)})),
            ai_reserved           BOOLEAN      NOT NULL,
            store_level           TEXT         NOT NULL CHECK (store_level IN ({_in(STORE_LEVELS)})),
            publish_level         TEXT         NOT NULL CHECK (publish_level IN ({_in(PUBLISH_LEVELS)})),
            registry_version      TEXT         NOT NULL CHECK (length(registry_version) BETWEEN 1 AND 200),
            policy_version        TEXT         NOT NULL CHECK (policy_version ~ '{WRITER}'),
            source_title          TEXT         CHECK (length(source_title) BETWEEN 1 AND 300),
            author                TEXT         CHECK (length(author) BETWEEN 1 AND 200),
            lang                  TEXT         CHECK (lang ~ '{LANG}'),
            published_at          TIMESTAMPTZ,
            published_day_only    BOOLEAN      NOT NULL DEFAULT false,
            published_structured  BOOLEAN      NOT NULL DEFAULT false,
            seen_at               TIMESTAMPTZ  NOT NULL,
            event_at              TIMESTAMPTZ,
            valid_until           TIMESTAMPTZ,
            written_by            TEXT         NOT NULL CHECK (written_by ~ '{WRITER}'),
            UNIQUE (url_sha256, version),
            UNIQUE (url_sha256, content_sha256),
            CHECK ((version = 1) = (previous_id IS NULL)),
            CONSTRAINT items_url_identity CHECK (url_sha256 = {_hash_of('canonical_url')}),
            CONSTRAINT items_published_before_seen CHECK (published_at IS NULL OR published_at <= seen_at),
            CHECK (published_at IS NOT NULL OR NOT (published_day_only OR published_structured)),
            CHECK (valid_until IS NULL OR event_at IS NULL OR valid_until >= event_at),
            CONSTRAINT items_summary_needs_facts CHECK (publish_level <> 'summary' OR (store_level = 'facts' AND NOT ai_reserved)),
            CONSTRAINT items_reserved_link_only CHECK (NOT ai_reserved OR store_level = 'link'),
            CONSTRAINT items_facts_only_authorised CHECK (source_state = 'verificada_autorizada' OR store_level = 'link')
        );
        CREATE INDEX news_items_content ON news.items (content_sha256);
        CREATE INDEX news_items_seen ON news.items (seen_at DESC);
        CREATE INDEX news_items_published ON news.items (published_at DESC) WHERE published_at IS NOT NULL;
        CREATE INDEX news_items_domain ON news.items (source_domain, seen_at DESC);
        COMMENT ON TABLE news.items IS
          'IA-080: an article as PrediGol saw it, one row per canonical URL and version of its content (url_sha256 = sha256 of '
          'canonical_url; the same content twice is one row). store_level, publish_level, ai_reserved, source_state and registry_version '
          'are a COPY of the source policy at seen_at (a source the policy lets keep nothing is never stored); a reader takes the stricter '
          'of the copy and the policy in force. No text and no picture of a third party: source_title and author are private metadata.';
        COMMENT ON COLUMN news.items.published_structured IS
          'The publication date came as structured data (feed, sitemap, page metadata), not guessed: only those enter «Última hora».';
        COMMENT ON COLUMN news.items.simhash IS 'The near-duplicate fingerprint of AD-G02 (64 bits); NULL until it computes it.';

        CREATE TABLE news.stories (
            id              BIGSERIAL    PRIMARY KEY,
            story_key       TEXT         NOT NULL CHECK (story_key ~ '{STORY_KEY}'),
            version         INTEGER      NOT NULL CHECK (version >= 1),
            previous_id     BIGINT       REFERENCES news.stories(id),
            at              TIMESTAMPTZ  NOT NULL,
            first_seen_at   TIMESTAMPTZ  NOT NULL,
            event_at        TIMESTAMPTZ,
            valid_until     TIMESTAMPTZ,
            claim_type      TEXT         CHECK (claim_type IN ({_in(CLAIM_TYPES)})),
            category        TEXT         CHECK (category IN ({_in(CATEGORIES)})),
            level           TEXT         CHECK (level IN ({_in(LEVELS)})),
            lang            TEXT         CHECK (lang ~ '{LANG}'),
            country         TEXT         CHECK (length(country) BETWEEN 1 AND 60),
            headline_es     TEXT         CHECK (length(btrim(headline_es)) BETWEEN 5 AND 120),
            headline_en     TEXT         CHECK (length(btrim(headline_en)) BETWEEN 5 AND 120),
            summary_es      TEXT         CHECK (length(btrim(summary_es)) BETWEEN 10 AND 600),
            summary_en      TEXT         CHECK (length(btrim(summary_en)) BETWEEN 10 AND 600),
            text_version    TEXT         CHECK (text_version ~ '{WRITER}'),
            status          TEXT         NOT NULL DEFAULT 'activa' CHECK (status IN ({_in(STATUSES)})),
            status_reason   TEXT         CHECK (length(btrim(status_reason)) BETWEEN 3 AND 500),
            decided_by      TEXT         NOT NULL CHECK (decided_by IN ({_in(DECIDERS)})),
            written_by      TEXT         NOT NULL CHECK (written_by ~ '{WRITER}'),
            UNIQUE (story_key, version),
            UNIQUE (id, story_key),
            CHECK ((version = 1) = (previous_id IS NULL)),
            CHECK (at >= first_seen_at),
            CHECK (valid_until IS NULL OR event_at IS NULL OR valid_until >= event_at),
            CHECK (text_version IS NOT NULL OR num_nonnulls(headline_es, headline_en, summary_es, summary_en) = 0),
            CHECK (status = 'activa' OR status_reason IS NOT NULL),
            CHECK (status <> 'retirada' OR decided_by = 'owner')
        );
        CREATE INDEX news_stories_at ON news.stories (at DESC);
        COMMENT ON TABLE news.stories IS
          'IA-080: a story - the articles that tell the same fact - one row per story_key and version; the newest version is in force. '
          'headline/summary are PrediGol''s own (AD-G04, empty until then); category, level, lang, country are AD-G03''s; status is the '
          'moderation (AD-G05): retirada hides it at a request, recorded by the owner, and a later version puts it back. Nothing is deleted.';

        CREATE TABLE news.item_story (
            id               BIGSERIAL     PRIMARY KEY,
            item_id          BIGINT        NOT NULL REFERENCES news.items(id),
            story_id         BIGINT        NOT NULL,
            story_key        TEXT          NOT NULL,
            at               TIMESTAMPTZ   NOT NULL,
            active           BOOLEAN       NOT NULL DEFAULT true,
            method           TEXT          NOT NULL CHECK (method IN ({_in(GROUP_METHODS)})),
            score            NUMERIC(4,3)  CHECK (score BETWEEN 0 AND 1),
            grouper_version  TEXT          NOT NULL CHECK (grouper_version ~ '{WRITER}'),
            decided_by       TEXT          NOT NULL CHECK (decided_by IN ({_in(DECIDERS)})),
            FOREIGN KEY (story_id, story_key) REFERENCES news.stories(id, story_key)
        );
        CREATE INDEX news_item_story_item ON news.item_story (item_id, id DESC);
        CREATE INDEX news_item_story_story ON news.item_story (story_key, id DESC);
        COMMENT ON TABLE news.item_story IS
          'IA-080: the story of an item. The newest row of an item decides; moving it to another story is a new row, and active = false '
          'takes it out of any. story_id is the version of the story when the link was made; story_key is the story.';

        CREATE TABLE news.item_entities (
            id               BIGSERIAL     PRIMARY KEY,
            item_id          BIGINT        NOT NULL REFERENCES news.items(id),
            entity_type      TEXT          NOT NULL CHECK (entity_type IN ({_in(ENTITY_TYPES)})),
            entity_id        BIGINT        NOT NULL CHECK (entity_id >= 1),
            name_seen        TEXT          CHECK (length(btrim(name_seen)) BETWEEN 1 AND 120),
            role             TEXT          NOT NULL CHECK (role IN ({_in(ROLES)})),
            method           TEXT          NOT NULL CHECK (method IN ({_in(LINK_METHODS)})),
            confidence       NUMERIC(4,3)  NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            active           BOOLEAN       NOT NULL DEFAULT true,
            linker_version   TEXT          NOT NULL CHECK (linker_version ~ '{WRITER}'),
            at               TIMESTAMPTZ   NOT NULL
        );
        CREATE INDEX news_item_entities_item ON news.item_entities (item_id, entity_type, entity_id, id DESC);
        CREATE INDEX news_item_entities_entity ON news.item_entities (entity_type, entity_id, at DESC);
        COMMENT ON TABLE news.item_entities IS
          'IA-080: who an item names (the owner''s «mentions»): role protagonista or mencionado, how it was linked (plantilla: the closed '
          'world of a squad; alias; proveedor: an id the provider gave; manual) and with what confidence. entity_id is PrediGol''s own id '
          '(core.teams.id, core.players.id ...), never the provider''s. The newest row of an item and entity decides; active = false takes '
          'the link back.';
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON news.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")

    # ai.evidence (20.756 rows, 29 MB on 16-nov-2026): nullable, no default - instant; the key NOT VALID, then validated (every row NULL).
    op.execute("ALTER TABLE ai.evidence ADD COLUMN item_id BIGINT")
    op.execute("ALTER TABLE ai.evidence ADD CONSTRAINT evidence_item_fk FOREIGN KEY (item_id) REFERENCES news.items(id) NOT VALID")
    op.execute("ALTER TABLE ai.evidence VALIDATE CONSTRAINT evidence_item_fk")
    op.execute("CREATE INDEX ai_evidence_item ON ai.evidence (item_id) WHERE item_id IS NOT NULL")
    op.execute("COMMENT ON COLUMN ai.evidence.item_id IS "
               "'IA-080: the article (news.items) the claim was read from. Written when the claim is inserted and never afterwards (it is "
               "content, ai.evidence_guard); NULL for every row written before revision 0146 - they are not filled in.'")
    op.execute(_guard((*CONTENT, "item_id")))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(_guard(CONTENT))
    op.execute("ALTER TABLE ai.evidence DROP COLUMN IF EXISTS item_id")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS news.{table}")
    op.execute("DROP SCHEMA IF EXISTS news")
