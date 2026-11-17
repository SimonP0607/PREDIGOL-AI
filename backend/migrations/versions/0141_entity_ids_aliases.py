"""External identity, aliases and one player key (plan 2026: AD-H01, AD-H02, AD-H09; IA-071)

WHY THIS EXISTS
---------------
PrediGol only stores the API-Football id of a player, team, coach, competition or stadium: no Wikidata item, no Transfermarkt
id, no Reep id (production, 16-nov-2026: not a single column of them). IA-041 measured the bridge on 11-nov-2026: 75.7 % of
7,800 current-squad players reach the open register Reep v1 (CC0) by their exact API-Football id, 30 of 30 right by hand.
Names are scattered: ``core.team_aliases`` (119 rows), ``core.referee_aliases`` (9,936 spellings of 6,111 referees), and the
name columns of each table. And a player has two keys: squads and claims carry ``provider_player_id``, favourites and
statistics ``core.players.id``; a position comes in two vocabularies (``Midfielder`` and ``M``).

WHAT IS ADDED (nothing existing is rewritten)
-------------------------------------------------
``core.entity_id_loads``   one row per LOAD: a pinned Reep release (with the sha256 of its list and of each file) or a sync
    of our own names (``source = core``). A load can be RETIRED (its status), which hides what it added and brings back what
    it retired: that is how a bad release is taken back, without deleting a row.
``core.entity_ids``        an external id of one of our entities (``entity_type`` + our ``entity_id``): system (reep,
    wikidata, transfermarkt), namespace, id, method, confidence, the rules' review (accepted / pending), evidence, the load.
    Only identifiers: of Transfermarkt nothing but the id as Reep wrote it.
``core.entity_aliases``    a name of one of our entities: text, normalised key, type (official, full, short, code, nickname,
    transliteration, localized, former, alternative), languages, script, source, the Reep id it came through.
``core.entity_identity_retirements``  (load, row) pairs: the rows a later load no longer has. Rows are never updated.
``core.entity_identity_queue`` / ``_queue_seen``  the questions for a person (one id to two entities, two entities to one id,
    a name that contradicts its id, two players with the same name and birth date or 1-5 days apart) and the loads that raised
    each one.
``core.entity_identity_decisions``  what a person decided (accept, reject, same, different, dismiss) and its undo.
Views ``core.entity_ids_live``, ``core.entity_aliases_live``, ``core.entity_identity_queue_open``: what is in force now.
``core.position_group(text)``  the one vocabulary of positions (``fbi.players.positions``): goalkeeper, defender, midfielder,
    forward, or NULL.
``player_id`` on ``core.squad_members`` and ``ai.evidence`` (AD-H09): ``core.players.id`` for the ``provider_player_id`` of the
    row, kept by a trigger (``core.player_key_fill``) and filled for the old rows by ``python -m scripts.entity_identity
    player-keys`` in batches, outside ``fixtures_sync``. ``provider_player_id`` stays, as an attribute. The trigger only ever
    writes ``player_id``: the content guard of ``ai.evidence`` does not look at it, so no claim changes.

The new tables are append-only (a trigger refuses UPDATE and DELETE outside maintenance), except the status of a load.
Nothing here is read by the reader, a model, a forecast, a pick or a settlement.

Downgrade drops what was added (the loads can be rebuilt from the pinned release; the decisions of people are the only thing
that would be lost, so take the usual backup first).

Revision ID: 0141
Revises: 0137
"""

from __future__ import annotations

from alembic import op

revision = "0141"
down_revision = "0140"
branch_labels = None
depends_on = None

ENTITY_TYPES = "('player', 'team', 'coach', 'competition', 'referee', 'venue')"
SYSTEMS = "('reep', 'wikidata', 'transfermarkt')"
ALIAS_TYPES = ("('official', 'full', 'short', 'code', 'nickname', 'transliteration', 'localized', 'former', "
               "'alternative')")
QUEUE_KINDS = "('bridge_conflict', 'shared_external', 'name_mismatch', 'possible_duplicate', 'near_birth_date')"

POSITION_GROUP_SQL = """
CREATE OR REPLACE FUNCTION core.position_group(raw TEXT) RETURNS TEXT LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
SELECT CASE btrim(regexp_replace(lower(btrim(raw)), '[^a-z0-9]+', ' ', 'g'))
    WHEN 'goalkeeper' THEN 'goalkeeper' WHEN 'g' THEN 'goalkeeper' WHEN 'gk' THEN 'goalkeeper'
    WHEN 'keeper' THEN 'goalkeeper' WHEN 'portero' THEN 'goalkeeper' WHEN 'arquero' THEN 'goalkeeper'
    WHEN 'defender' THEN 'defender' WHEN 'd' THEN 'defender' WHEN 'df' THEN 'defender'
    WHEN 'defensa' THEN 'defender' WHEN 'defensor' THEN 'defender'
    WHEN 'centre back' THEN 'defender' WHEN 'center back' THEN 'defender' WHEN 'cb' THEN 'defender'
    WHEN 'left back' THEN 'defender' WHEN 'lb' THEN 'defender' WHEN 'right back' THEN 'defender'
    WHEN 'rb' THEN 'defender' WHEN 'left wing back' THEN 'defender' WHEN 'right wing back' THEN 'defender'
    WHEN 'midfielder' THEN 'midfielder' WHEN 'm' THEN 'midfielder' WHEN 'mf' THEN 'midfielder'
    WHEN 'centrocampista' THEN 'midfielder' WHEN 'mediocampista' THEN 'midfielder' WHEN 'volante' THEN 'midfielder'
    WHEN 'defensive midfield' THEN 'midfielder' WHEN 'cdm' THEN 'midfielder' WHEN 'dm' THEN 'midfielder'
    WHEN 'central midfield' THEN 'midfielder' WHEN 'cm' THEN 'midfielder' WHEN 'attacking midfield' THEN 'midfielder'
    WHEN 'cam' THEN 'midfielder' WHEN 'am' THEN 'midfielder' WHEN 'left midfield' THEN 'midfielder'
    WHEN 'right midfield' THEN 'midfielder'
    WHEN 'attacker' THEN 'forward' WHEN 'forward' THEN 'forward' WHEN 'f' THEN 'forward' WHEN 'fw' THEN 'forward'
    WHEN 'striker' THEN 'forward' WHEN 'delantero' THEN 'forward' WHEN 'atacante' THEN 'forward'
    WHEN 'left winger' THEN 'forward' WHEN 'lw' THEN 'forward' WHEN 'right winger' THEN 'forward'
    WHEN 'rw' THEN 'forward' WHEN 'centre forward' THEN 'forward' WHEN 'center forward' THEN 'forward'
    WHEN 'cf' THEN 'forward' WHEN 'st' THEN 'forward' WHEN 'second striker' THEN 'forward' WHEN 'ss' THEN 'forward'
    ELSE NULL END
$fn$"""


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The new tables take no lock on
    # anything; the two ADD COLUMN take a short ACCESS EXCLUSIVE on core.squad_members and ai.evidence (a nullable column
    # with no default is a catalogue change) and the foreign keys a short SHARE ROW EXCLUSIVE on core.players.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE OR REPLACE FUNCTION core.entity_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.identity_maintenance', true), '') = 'on' THEN
                RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END IF;
            RAISE EXCEPTION '%: rows are never changed or deleted (a load adds rows; a later load or a retirement hides them)',
                TG_TABLE_NAME USING ERRCODE = 'check_violation';
        END
        $fn$""")

    op.execute("""
        CREATE TABLE core.entity_id_loads (
            id             BIGSERIAL   PRIMARY KEY,
            source         TEXT        NOT NULL CHECK (source IN ('reep', 'core')),
            release        TEXT        NOT NULL CHECK (length(btrim(release)) > 0),
            release_sha256 TEXT        CHECK (release_sha256 IS NULL OR release_sha256 ~ '^[0-9a-f]{64}$'),
            files          JSONB       NOT NULL DEFAULT '{}'::jsonb,
            license        TEXT,
            rules_version  TEXT        NOT NULL CHECK (length(btrim(rules_version)) > 0),
            status         TEXT        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
            counts         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            loaded_by      TEXT        NOT NULL CHECK (length(btrim(loaded_by)) > 0),
            loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            retired_by     TEXT,
            retired_at     TIMESTAMPTZ,
            retire_note    TEXT,
            CONSTRAINT entity_id_loads_once UNIQUE (source, release, rules_version),
            CONSTRAINT entity_id_loads_reep_pinned CHECK (source <> 'reep' OR release_sha256 IS NOT NULL),
            CONSTRAINT entity_id_loads_retired CHECK ((status = 'retired') = (retired_at IS NOT NULL))
        )""")
    op.execute("""
        COMMENT ON TABLE core.entity_id_loads IS
        'One load of external identity or names (AD-H01/H02, IA-071): source reep = a Reep v1 release (CC0) pinned by the
         sha256 of its release.json and of each file (fbi.people.identity.reep.RELEASES), loaded once per rules version;
         source core = a sync of our own names and of the old alias tables. counts says what it added and retired. Retiring a
         load (status, retired_*) hides the rows it added and brings back the ones it retired: the only UPDATE of these tables.'""")

    op.execute(f"""
        CREATE TABLE core.entity_ids (
            id          BIGSERIAL    PRIMARY KEY,
            load_id     BIGINT       NOT NULL REFERENCES core.entity_id_loads(id),
            row_key     TEXT         NOT NULL,
            entity_type TEXT         NOT NULL CHECK (entity_type IN {ENTITY_TYPES}),
            entity_id   BIGINT       NOT NULL CHECK (entity_id > 0),
            system      TEXT         NOT NULL CHECK (system IN {SYSTEMS}),
            namespace   TEXT         NOT NULL DEFAULT '',
            external_id TEXT         NOT NULL CHECK (length(btrim(external_id)) > 0),
            method      TEXT         NOT NULL CHECK (method IN ('exact_bridge', 'bridge_chain')),
            confidence  NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            review      TEXT         NOT NULL CHECK (review IN ('accepted', 'pending')),
            evidence    JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
            known_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX entity_ids_entity ON core.entity_ids (entity_type, entity_id)")
    op.execute("CREATE INDEX entity_ids_external ON core.entity_ids (system, external_id)")
    op.execute("CREATE INDEX entity_ids_row_key ON core.entity_ids (row_key)")
    op.execute("CREATE INDEX entity_ids_load ON core.entity_ids (load_id)")
    op.execute("""
        COMMENT ON TABLE core.entity_ids IS
        'An external id of one of our entities (AD-H01): entity_type + entity_id is ours (core.players.id, core.teams.id,
         core.coaches.id, core.competitions.id, core.referees.id, core.venues.id); system/namespace/external_id is theirs (reep;
         wikidata QID; transfermarkt with its namespace: spieler, trainer, verein...). method exact_bridge: our API-Football id
         is bridged to that Reep entity in the release; bridge_chain: the Wikidata item or Transfermarkt id Reep has for it.
         review is what the rules decided (pending = waits in core.entity_identity_queue); what a person decided is in
         core.entity_identity_decisions; what is in force now is core.entity_ids_live. Never updated or deleted.'""")

    op.execute(f"""
        CREATE TABLE core.entity_aliases (
            id            BIGSERIAL    PRIMARY KEY,
            load_id       BIGINT       NOT NULL REFERENCES core.entity_id_loads(id),
            row_key       TEXT         NOT NULL,
            entity_type   TEXT         NOT NULL CHECK (entity_type IN {ENTITY_TYPES}),
            entity_id     BIGINT       NOT NULL CHECK (entity_id > 0),
            alias         TEXT         NOT NULL CHECK (length(btrim(alias)) > 0),
            alias_key     TEXT         NOT NULL CHECK (length(alias_key) > 0),
            alias_type    TEXT         NOT NULL CHECK (alias_type IN {ALIAS_TYPES}),
            languages     TEXT[]       NOT NULL DEFAULT '{{}}',
            script        TEXT         NOT NULL CHECK (script IN ('latin', 'cyrillic', 'greek', 'arabic', 'hebrew', 'cjk',
                                                                  'hangul', 'other')),
            source        TEXT         NOT NULL CHECK (source IN ('api_football', 'reep', 'wikidata', 'core.team_aliases',
                                                                  'core.referee_aliases', 'core.referees')),
            source_detail TEXT         NOT NULL DEFAULT '',
            via_external  TEXT,
            confidence    NUMERIC(4,3) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
            known_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX entity_aliases_key ON core.entity_aliases (alias_key, entity_type)")
    op.execute("CREATE INDEX entity_aliases_entity ON core.entity_aliases (entity_type, entity_id)")
    op.execute("CREATE INDEX entity_aliases_row_key ON core.entity_aliases (row_key)")
    op.execute("CREATE INDEX entity_aliases_load ON core.entity_aliases (load_id)")
    op.execute("""
        COMMENT ON TABLE core.entity_aliases IS
        'Every name of one of our entities (AD-H02): the one table the search, the linking of mentions and the profiles read
         names from. alias as written; alias_key = fbi.people.identity.names.alias_key (lower case, no accents on Latin letters,
         no punctuation; other scripts keep their letters). source api_football = our own provider''s names (core.players.name,
         first and last name...), core.team_aliases / core.referee_aliases / core.referees = the old tables, absorbed and kept in
         step by each core sync (they are still written and are not dropped); reep / wikidata = names of the Reep entity the
         entity is linked to (via_external): shown only while that link is accepted (core.entity_aliases_live). A name alone
         never links a mention: AD-C06 validates. Never updated or deleted.'""")

    op.execute("""
        CREATE TABLE core.entity_identity_retirements (
            load_id BIGINT NOT NULL REFERENCES core.entity_id_loads(id),
            kind    TEXT   NOT NULL CHECK (kind IN ('id', 'alias')),
            row_id  BIGINT NOT NULL,
            PRIMARY KEY (kind, row_id, load_id)
        )""")
    op.execute("""
        COMMENT ON TABLE core.entity_identity_retirements IS
        'Rows of core.entity_ids (kind id) or core.entity_aliases (kind alias) that a later load of the same source no longer
         has: hidden while that load is active. Never updated or deleted.'""")

    op.execute(f"""
        CREATE TABLE core.entity_identity_queue (
            id            BIGSERIAL    PRIMARY KEY,
            item_key      TEXT         NOT NULL UNIQUE,
            source        TEXT         NOT NULL CHECK (source IN ('reep', 'core')),
            kind          TEXT         NOT NULL CHECK (kind IN {QUEUE_KINDS}),
            entity_type   TEXT         NOT NULL CHECK (entity_type IN {ENTITY_TYPES}),
            entity_a      BIGINT       NOT NULL,
            entity_b      BIGINT,
            system        TEXT,
            namespace     TEXT,
            external_id   TEXT,
            score         REAL         NOT NULL CHECK (score >= 0),
            evidence      JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
            rules_version TEXT         NOT NULL,
            first_load_id BIGINT       NOT NULL REFERENCES core.entity_id_loads(id),
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT entity_identity_queue_pair CHECK (entity_b IS NULL OR entity_a < entity_b)
        )""")
    op.execute("""
        CREATE TABLE core.entity_identity_queue_seen (
            queue_id BIGINT NOT NULL REFERENCES core.entity_identity_queue(id),
            load_id  BIGINT NOT NULL REFERENCES core.entity_id_loads(id),
            PRIMARY KEY (queue_id, load_id)
        )""")
    op.execute("CREATE INDEX entity_identity_queue_seen_load ON core.entity_identity_queue_seen (load_id)")
    op.execute("""
        COMMENT ON TABLE core.entity_identity_queue IS
        'The questions for a person (AD-H01): bridge_conflict (an API-Football id Reep bridges to two entities: nothing linked),
         shared_external (two of our entities would get the same external id: linked to neither; entity_a < entity_b),
         name_mismatch (the names contradict the id: the link waits as pending), possible_duplicate / near_birth_date (two
         players with the same name and the same birth date, or 1-5 days apart: the provider may hold one man twice).
         queue_seen says which loads raised each one; open = undecided and raised by the newest active load of its source.'""")

    op.execute(f"""
        CREATE TABLE core.entity_identity_decisions (
            id          BIGSERIAL   PRIMARY KEY,
            queue_id    BIGINT      REFERENCES core.entity_identity_queue(id),
            action      TEXT        NOT NULL CHECK (action IN ('accept', 'reject', 'same', 'different', 'dismiss', 'undo')),
            entity_type TEXT        CHECK (entity_type IS NULL OR entity_type IN {ENTITY_TYPES}),
            entity_id   BIGINT,
            system      TEXT        CHECK (system IS NULL OR system IN {SYSTEMS}),
            namespace   TEXT,
            external_id TEXT,
            undoes      BIGINT      REFERENCES core.entity_identity_decisions(id),
            actor       TEXT        NOT NULL CHECK (length(btrim(actor)) > 0),
            note        TEXT,
            at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT entity_identity_decisions_link CHECK (
                action NOT IN ('accept', 'reject')
                OR (entity_type IS NOT NULL AND entity_id IS NOT NULL AND system IS NOT NULL AND namespace IS NOT NULL
                    AND external_id IS NOT NULL)),
            CONSTRAINT entity_identity_decisions_undo CHECK ((action = 'undo') = (undoes IS NOT NULL)),
            CONSTRAINT entity_identity_decisions_target CHECK (action = 'undo' OR action IN ('accept', 'reject')
                                                               OR queue_id IS NOT NULL)
        )""")
    op.execute("CREATE INDEX entity_identity_decisions_link ON core.entity_identity_decisions "
               "(entity_type, entity_id, system, external_id) WHERE action IN ('accept', 'reject')")
    op.execute("CREATE INDEX entity_identity_decisions_queue ON core.entity_identity_decisions (queue_id) "
               "WHERE queue_id IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX entity_identity_decisions_undone ON core.entity_identity_decisions (undoes) "
               "WHERE undoes IS NOT NULL")
    op.execute("""
        COMMENT ON TABLE core.entity_identity_decisions IS
        'What a person decided about external identity (AD-H01): accept / reject one link (entity + system + namespace +
         external id), with the queue item it answers when there is one; same / different / dismiss a question of the queue;
         undo takes back one decision (undoes). The latest decision on a link that is not undone wins, over every later load:
         a rejected link stays rejected when the next release brings it again. actor is admin:<user> or script:<name>.'""")

    for table in ("entity_ids", "entity_aliases", "entity_identity_retirements", "entity_identity_queue",
                  "entity_identity_queue_seen", "entity_identity_decisions"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON core.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION core.entity_identity_guard()")

    op.execute("""
        CREATE VIEW core.entity_ids_live AS
        SELECT i.id, i.entity_type, i.entity_id, i.system, i.namespace, i.external_id, i.method, i.confidence, i.review,
               CASE d.action WHEN 'accept' THEN 'accepted' WHEN 'reject' THEN 'rejected' ELSE i.review END AS state,
               d.id AS decision_id, i.evidence, i.load_id, l.release, i.known_at
          FROM core.entity_ids i
          JOIN core.entity_id_loads l ON l.id = i.load_id AND l.status = 'active'
          LEFT JOIN LATERAL (
                SELECT x.id, x.action FROM core.entity_identity_decisions x
                 WHERE x.action IN ('accept', 'reject') AND x.entity_type = i.entity_type AND x.entity_id = i.entity_id
                   AND x.system = i.system AND x.namespace = i.namespace AND x.external_id = i.external_id
                   AND NOT EXISTS (SELECT 1 FROM core.entity_identity_decisions u WHERE u.undoes = x.id)
                 ORDER BY x.id DESC LIMIT 1) d ON true
         WHERE NOT EXISTS (SELECT 1 FROM core.entity_identity_retirements r
                             JOIN core.entity_id_loads rl ON rl.id = r.load_id AND rl.status = 'active'
                            WHERE r.kind = 'id' AND r.row_id = i.id)""")
    op.execute("""
        COMMENT ON VIEW core.entity_ids_live IS
        'The external ids in force: rows of active loads not retired by an active load, with state = the latest decision of a
         person on the link (accepted / rejected) or else the rules'' review (accepted / pending). Readers use state =
         ''accepted''.'""")

    op.execute("""
        CREATE VIEW core.entity_aliases_live AS
        SELECT a.id, a.entity_type, a.entity_id, a.alias, a.alias_key, a.alias_type, a.languages, a.script, a.source,
               a.source_detail, a.via_external, a.confidence, a.load_id, a.known_at
          FROM core.entity_aliases a
          JOIN core.entity_id_loads l ON l.id = a.load_id AND l.status = 'active'
         WHERE NOT EXISTS (SELECT 1 FROM core.entity_identity_retirements r
                             JOIN core.entity_id_loads rl ON rl.id = r.load_id AND rl.status = 'active'
                            WHERE r.kind = 'alias' AND r.row_id = a.id)
           AND (a.via_external IS NULL
                OR EXISTS (SELECT 1 FROM core.entity_ids_live i
                            WHERE i.entity_type = a.entity_type AND i.entity_id = a.entity_id AND i.system = 'reep'
                              AND i.external_id = a.via_external AND i.state = 'accepted'))""")
    op.execute("""
        COMMENT ON VIEW core.entity_aliases_live IS
        'The names in force: rows of active loads not retired by an active load; a name that came through a Reep link only
         while that link is accepted.'""")

    op.execute("""
        CREATE VIEW core.entity_identity_queue_open AS
        SELECT q.*
          FROM core.entity_identity_queue q
         WHERE NOT EXISTS (SELECT 1 FROM core.entity_identity_decisions d
                            WHERE d.queue_id = q.id AND d.action <> 'undo'
                              AND NOT EXISTS (SELECT 1 FROM core.entity_identity_decisions u WHERE u.undoes = d.id))
           AND EXISTS (SELECT 1 FROM core.entity_identity_queue_seen s
                        WHERE s.queue_id = q.id
                          AND s.load_id = (SELECT max(l.id) FROM core.entity_id_loads l
                                            WHERE l.source = q.source AND l.status = 'active'))""")
    op.execute("""
        COMMENT ON VIEW core.entity_identity_queue_open IS
        'The questions waiting for a person: no decision in force, and raised again by the newest active load of their source
         (a question a later release no longer raises closes by itself).'""")

    op.execute(POSITION_GROUP_SQL)
    op.execute("""
        COMMENT ON FUNCTION core.position_group(TEXT) IS
        'The one vocabulary of positions (AD-H09; the same table as fbi.players.positions): goalkeeper, defender, midfielder,
         forward, or NULL when the text is not a position (SUB, U, empty).'""")

    # AD-H09: one player key. A nullable column with no default: no rewrite of the table.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.player_key_fill() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF NEW.provider_player_id IS NULL OR NEW.provider_player_id <= 0 THEN
                NEW.player_id := NULL;
            ELSE
                NEW.player_id := (SELECT p.id FROM core.players p WHERE p.provider_player_id = NEW.provider_player_id);
            END IF;
            RETURN NEW;
        END
        $fn$""")
    op.execute("""
        COMMENT ON FUNCTION core.player_key_fill() IS
        'AD-H09: player_id is always core.players.id of the row''s provider_player_id (NULL while the player has no row there).
         Derived, never typed: whatever a writer puts in player_id is replaced.'""")
    for table, trigger in (("core.squad_members", "squad_members_player_key"), ("ai.evidence", "evidence_player_key")):
        op.execute(f"ALTER TABLE {table} ADD COLUMN player_id BIGINT REFERENCES core.players(id) ON DELETE SET NULL")
        op.execute(f"CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION core.player_key_fill()")
        op.execute(f"COMMENT ON COLUMN {table}.player_id IS "
                   "'AD-H09: core.players.id of provider_player_id (the one player key of the graph), kept by the trigger "
                   "core.player_key_fill; the old rows are filled by scripts.entity_identity player-keys. NULL: the player "
                   "has no core.players row yet.'")
    op.execute("CREATE INDEX squad_members_player_id ON core.squad_members (player_id) WHERE player_id IS NOT NULL")
    op.execute("CREATE INDEX ai_evidence_player_id ON ai.evidence (player_id) WHERE player_id IS NOT NULL")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TRIGGER IF EXISTS evidence_player_key ON ai.evidence")
    op.execute("DROP TRIGGER IF EXISTS squad_members_player_key ON core.squad_members")
    op.execute("ALTER TABLE ai.evidence DROP COLUMN IF EXISTS player_id")
    op.execute("ALTER TABLE core.squad_members DROP COLUMN IF EXISTS player_id")
    op.execute("DROP FUNCTION IF EXISTS core.player_key_fill()")
    op.execute("DROP FUNCTION IF EXISTS core.position_group(TEXT)")
    op.execute("DROP VIEW IF EXISTS core.entity_identity_queue_open")
    op.execute("DROP VIEW IF EXISTS core.entity_aliases_live")
    op.execute("DROP VIEW IF EXISTS core.entity_ids_live")
    for table in ("entity_identity_decisions", "entity_identity_queue_seen", "entity_identity_queue",
                  "entity_identity_retirements", "entity_aliases", "entity_ids", "entity_id_loads"):
        op.execute(f"DROP TABLE IF EXISTS core.{table}")
    op.execute("DROP FUNCTION IF EXISTS core.entity_identity_guard()")
