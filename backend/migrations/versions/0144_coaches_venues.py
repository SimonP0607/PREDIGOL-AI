"""Current coach and corrections of open careers; stadiums with coordinates and altitude; match -> stadium links (plan 2026:
AD-H03 and AD-H04; IA-075 and IA-076)

WHY THIS EXISTS
---------------
Coaches (AD-H03). The provider's careers do not say who coaches a team now: on 16-nov-2026, of 4,531 teams with an open
career (no end date) in the newest snapshot of each coach, 3,127 had two or more. The match sheet does say it
(``core.fixture_lineups.provider_coach_id``), with a date. ``fbi.people.current_coach`` reads the answer from the sheets; what
this revision adds is where the CORRECTIONS of the careers the sheets contradict are kept - beside the provider's rows, never
over them.

Stadiums (AD-H04). ``core.venues`` has no coordinates and no altitude (no column), and only 425 of 1,288 matches of the next
14 days point at their stadium by id (the provider sends a name without an id for the rest). The coordinates come from a
versioned snapshot of Wikidata (CC0) reached through the Wikidata item of the home club (AD-H01, ``core.entity_ids``); the
altitude from the Copernicus DEM GLO-90 at those coordinates; the link of a match without an id from rules with their method
written down, and a review queue for what they cannot decide.

WHAT IS ADDED (nothing existing is rewritten; no column of a provider table)
-----------------------------------------------------------------------------
``core.coach_career_corrections``  a correction of one row of ``core.coach_careers`` (its key): ``close`` with the end date and
    its basis, or ``retract`` of an earlier correction. Append-only.
``core.coach_careers_audited``     view: the newest snapshot of each coach's careers with the provider's end date, the corrected
    one and which is in force (``effective_end_date``, ``end_date_source``).
``core.venue_geo_loads``           one load per Wikidata snapshot (its sha256), with the DEM used and the licences; a load can be
    retired (its status: the only UPDATE).
``core.venue_geo``                 a stadium's Wikidata item, coordinates, altitude, Wikidata capacity, method, confidence and
    evidence, per load. Append-only.
``core.fixture_venue_links``       the stadium a match without a provider id was linked to, by which rule. Append-only.
``core.venue_review_queue`` / ``core.venue_review_decisions``  what the rules left to a person, and what the person decided.
Views ``core.venue_geo_live`` and ``core.fixture_venue_resolved``: what is in force now.

Nothing here is read by the reader, a model, a forecast, a pick or a settlement. ``core.fixtures.venue_id``,
``core.venues`` and ``core.coach_careers`` are not touched: the provider's data stays as it came.

Downgrade drops what was added (the loads can be rebuilt from the snapshot; the corrections and the decisions of people are what
would be lost, so take the usual backup first).

Revision ID: 0144
Revises: 0141
"""

from __future__ import annotations

from alembic import op

revision = "0144"
down_revision = "0143"
branch_labels = None
depends_on = None

APPEND_ONLY = ("coach_career_corrections", "venue_geo", "fixture_venue_links", "venue_review_queue",
               "venue_review_decisions")


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). Only new tables and views; the foreign
    # keys take a short SHARE ROW EXCLUSIVE on core.coach_careers, core.venues, core.fixtures and core.teams.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE OR REPLACE FUNCTION core.coaches_venues_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.coaches_venues_maintenance', true), '') = 'on' THEN
                RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END IF;
            RAISE EXCEPTION '%: rows are never changed or deleted (a correction, a load or a decision adds a row)',
                TG_TABLE_NAME USING ERRCODE = 'check_violation';
        END
        $fn$""")

    # ── AD-H03 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE core.coach_career_corrections (
            id                BIGSERIAL   PRIMARY KEY,
            provider_coach_id INTEGER     NOT NULL,
            observed_at       TIMESTAMPTZ NOT NULL,
            ordinal           SMALLINT    NOT NULL,
            team_id           BIGINT      NOT NULL REFERENCES core.teams(id),
            action            TEXT        NOT NULL CHECK (action IN ('close', 'retract')),
            end_date          DATE,
            basis             TEXT        CHECK (basis IN ('last_lineup', 'before_successor', 'manual')),
            retracts_id       BIGINT      REFERENCES core.coach_career_corrections(id),
            rules_version     TEXT        NOT NULL CHECK (length(btrim(rules_version)) > 0),
            evidence          JSONB       NOT NULL DEFAULT '{}'::jsonb,
            decided_by        TEXT        NOT NULL CHECK (length(btrim(decided_by)) > 0),
            note              TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT coach_career_corrections_row FOREIGN KEY (provider_coach_id, observed_at, ordinal)
                REFERENCES core.coach_careers (provider_coach_id, observed_at, ordinal),
            CONSTRAINT coach_career_corrections_shape CHECK (
                (action = 'close' AND end_date IS NOT NULL AND basis IS NOT NULL AND retracts_id IS NULL)
                OR (action = 'retract' AND end_date IS NULL AND retracts_id IS NOT NULL))
        )""")
    op.execute("CREATE UNIQUE INDEX coach_career_corrections_one_close ON core.coach_career_corrections "
               "(provider_coach_id, observed_at, ordinal, rules_version) WHERE action = 'close'")
    op.execute("CREATE UNIQUE INDEX coach_career_corrections_one_retract ON core.coach_career_corrections (retracts_id) "
               "WHERE action = 'retract'")
    op.execute("CREATE INDEX coach_career_corrections_team ON core.coach_career_corrections (team_id)")
    op.execute("""
        COMMENT ON TABLE core.coach_career_corrections IS
        'AD-H03 (IA-075): a correction of one row of core.coach_careers, which is never changed. close = the career ended on
         end_date (basis last_lineup: his last match on that bench; before_successor: an upper bound, the day before his
         successor''s run of match sheets began; manual: a person). retract = an earlier correction withdrawn. A new snapshot of
         the provider is a new row and is judged again: a correction holds for the exact row it names.'""")
    op.execute("""
        CREATE VIEW core.coach_careers_audited AS
        SELECT k.provider_coach_id, k.observed_at, k.ordinal, k.coach_id, k.provider_team_id, k.team_id, k.team_name,
               k.start_date, k.end_date AS provider_end_date, c.end_date AS corrected_end_date,
               coalesce(k.end_date, c.end_date) AS effective_end_date,
               CASE WHEN k.end_date IS NOT NULL THEN 'provider' WHEN c.end_date IS NOT NULL THEN 'correction' END
                   AS end_date_source,
               c.id AS correction_id, c.basis AS correction_basis
          FROM core.coach_careers k
          LEFT JOIN LATERAL (
                SELECT x.id, x.end_date, x.basis FROM core.coach_career_corrections x
                 WHERE x.provider_coach_id = k.provider_coach_id AND x.observed_at = k.observed_at
                   AND x.ordinal = k.ordinal AND x.action = 'close'
                   AND NOT EXISTS (SELECT 1 FROM core.coach_career_corrections r
                                    WHERE r.action = 'retract' AND r.retracts_id = x.id)
                 ORDER BY x.created_at DESC, x.id DESC LIMIT 1) c ON true
         WHERE k.observed_at = (SELECT max(x.observed_at) FROM core.coach_careers x
                                 WHERE x.provider_coach_id = k.provider_coach_id)""")
    op.execute("""
        COMMENT ON VIEW core.coach_careers_audited IS
        'AD-H03 (IA-075): core.coach_spells (newest snapshot of each coach) with the provider''s end date, the corrected one
         and the one in force. A career is open now when effective_end_date IS NULL.'""")

    # ── AD-H04 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE core.venue_geo_loads (
            id              BIGSERIAL   PRIMARY KEY,
            source          TEXT        NOT NULL CHECK (source IN ('wikidata')),
            snapshot_name   TEXT        NOT NULL CHECK (length(btrim(snapshot_name)) > 0),
            snapshot_sha256 TEXT        NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
            fetched_at      TIMESTAMPTZ NOT NULL,
            query_version   TEXT        NOT NULL,
            rules_version   TEXT        NOT NULL CHECK (length(btrim(rules_version)) > 0),
            dem             TEXT,
            licenses        JSONB       NOT NULL DEFAULT '{}'::jsonb,
            counts          JSONB       NOT NULL DEFAULT '{}'::jsonb,
            status          TEXT        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
            loaded_by       TEXT        NOT NULL CHECK (length(btrim(loaded_by)) > 0),
            loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            retired_by      TEXT,
            retired_at      TIMESTAMPTZ,
            retire_note     TEXT,
            CONSTRAINT venue_geo_loads_once UNIQUE (snapshot_sha256, rules_version),
            CONSTRAINT venue_geo_loads_retired CHECK ((status = 'retired') = (retired_at IS NOT NULL))
        )""")
    op.execute("""
        COMMENT ON TABLE core.venue_geo_loads IS
        'AD-H04 (IA-076): one load of stadium geography from a Wikidata snapshot (CC0), pinned by its sha256, with the DEM the
         altitude was read from (Copernicus GLO-90, its notice in licenses). Retiring a load (status, retired_*) hides its rows:
         the only UPDATE of these tables.'""")
    op.execute("""
        CREATE TABLE core.venue_geo (
            id                BIGSERIAL     PRIMARY KEY,
            load_id           BIGINT        NOT NULL REFERENCES core.venue_geo_loads(id),
            venue_id          BIGINT        NOT NULL REFERENCES core.venues(id),
            qid               TEXT          NOT NULL CHECK (qid ~ '^Q[0-9]+$'),
            latitude          NUMERIC(9,6)  CHECK (latitude BETWEEN -90 AND 90),
            longitude         NUMERIC(9,6)  CHECK (longitude BETWEEN -180 AND 180),
            elevation_m       NUMERIC(6,1)  CHECK (elevation_m BETWEEN -450 AND 5000),
            elevation_source  TEXT          CHECK (elevation_source IN ('copernicus_glo90', 'wikidata_p2044')),
            elevation_check   TEXT          CHECK (elevation_check IN ('agrees', 'disagrees', 'no_wikidata', 'no_dem')),
            capacity_wikidata INTEGER       CHECK (capacity_wikidata > 0),
            method            TEXT          NOT NULL CHECK (method IN ('home_venue_name', 'home_venue_city', 'manual')),
            confidence        NUMERIC(4,3)  NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            rules_version     TEXT          NOT NULL,
            evidence          JSONB         NOT NULL DEFAULT '{}'::jsonb,
            known_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT venue_geo_once UNIQUE (load_id, venue_id),
            CONSTRAINT venue_geo_pair CHECK ((latitude IS NULL) = (longitude IS NULL)),
            CONSTRAINT venue_geo_elevation_source CHECK ((elevation_m IS NULL) = (elevation_source IS NULL))
        )""")
    op.execute("CREATE INDEX venue_geo_venue ON core.venue_geo (venue_id, known_at DESC)")
    op.execute("CREATE INDEX venue_geo_qid ON core.venue_geo (qid)")
    op.execute("""
        COMMENT ON TABLE core.venue_geo IS
        'AD-H04 (IA-076): where a stadium is. qid = its Wikidata item, reached through the item of a club whose home it is
         (P115); latitude/longitude = its P625; elevation_m = the Copernicus DEM GLO-90 at those coordinates (a surface model:
         roofs and stands are in it, so it is the altitude to about +-30 m), checked against Wikidata P2044 when it has one;
         capacity_wikidata = P1083 when Wikidata gives one value (the provider''s capacity stays in core.venues).'""")

    op.execute("""
        CREATE TABLE core.fixture_venue_links (
            id            BIGSERIAL    PRIMARY KEY,
            fixture_id    BIGINT       NOT NULL REFERENCES core.fixtures(id),
            venue_id      BIGINT       NOT NULL REFERENCES core.venues(id),
            method        TEXT         NOT NULL CHECK (method IN ('provider_history_team', 'provider_history_city',
                                                                  'home_ground', 'venue_name_city', 'manual')),
            confidence    NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            rules_version TEXT         NOT NULL CHECK (length(btrim(rules_version)) > 0),
            evidence      JSONB        NOT NULL DEFAULT '{}'::jsonb,
            known_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT fixture_venue_links_once UNIQUE (fixture_id, rules_version, venue_id)
        )""")
    op.execute("CREATE INDEX fixture_venue_links_fixture ON core.fixture_venue_links (fixture_id, known_at DESC)")
    op.execute("""
        COMMENT ON TABLE core.fixture_venue_links IS
        'AD-H04 (IA-076): the stadium of a match whose payload names one without an id (core.fixtures.venue_id NULL, which is
         never written here). method says which rule: provider_history_team = the provider gave that id to the same name for
         the same home club in another match; provider_history_city = to the same name and city in other matches;
         home_ground = the home club''s own ground, same name; venue_name_city = the one stadium of that name in that city.'""")

    op.execute("""
        CREATE TABLE core.venue_review_queue (
            id            BIGSERIAL   PRIMARY KEY,
            kind          TEXT        NOT NULL CHECK (kind IN ('venue_qid', 'fixture_venue')),
            subject_id    BIGINT      NOT NULL CHECK (subject_id > 0),
            reason        TEXT        NOT NULL CHECK (length(btrim(reason)) > 0),
            candidates    JSONB       NOT NULL DEFAULT '[]'::jsonb,
            rules_version TEXT        NOT NULL,
            load_id       BIGINT      REFERENCES core.venue_geo_loads(id),
            raised_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT venue_review_queue_once UNIQUE (kind, subject_id, reason, rules_version)
        )""")
    op.execute("""
        CREATE TABLE core.venue_review_decisions (
            id         BIGSERIAL   PRIMARY KEY,
            queue_id   BIGINT      NOT NULL REFERENCES core.venue_review_queue(id),
            decision   TEXT        NOT NULL CHECK (decision IN ('accept', 'reject', 'dismiss', 'undo')),
            chosen     TEXT,
            decided_by TEXT        NOT NULL CHECK (length(btrim(decided_by)) > 0),
            note       TEXT,
            decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT venue_review_decisions_choice CHECK (decision <> 'accept' OR chosen IS NOT NULL)
        )""")
    op.execute("CREATE INDEX venue_review_decisions_queue ON core.venue_review_decisions (queue_id, decided_at DESC)")
    op.execute("""
        COMMENT ON TABLE core.venue_review_queue IS
        'AD-H04 (IA-076): what the rules left to a person. venue_qid: subject = core.venues.id, candidates = Wikidata items;
         fixture_venue: subject = core.fixtures.id, candidates = core.venues ids. The newest decision (core.venue_review_decisions)
         of an item is in force; undo takes the one before it back.'""")

    op.execute("""
        CREATE VIEW core.venue_review_open AS
        SELECT q.* FROM core.venue_review_queue q
         WHERE coalesce((SELECT d.decision FROM core.venue_review_decisions d WHERE d.queue_id = q.id
                          ORDER BY d.decided_at DESC, d.id DESC LIMIT 1), 'undo') = 'undo'""")

    op.execute("""
        CREATE VIEW core.venue_geo_live AS
        SELECT DISTINCT ON (g.venue_id) g.venue_id, g.qid, g.latitude, g.longitude, g.elevation_m, g.elevation_source,
               g.elevation_check, g.capacity_wikidata, g.method, g.confidence, g.rules_version, g.evidence, g.load_id,
               l.snapshot_name, l.fetched_at AS source_fetched_at, g.known_at
          FROM core.venue_geo g JOIN core.venue_geo_loads l ON l.id = g.load_id
         WHERE l.status = 'active'
           AND NOT EXISTS (
                SELECT 1 FROM core.venue_review_queue q
                 CROSS JOIN LATERAL (SELECT d.decision, d.chosen FROM core.venue_review_decisions d WHERE d.queue_id = q.id
                                      ORDER BY d.decided_at DESC, d.id DESC LIMIT 1) d
                 WHERE q.kind = 'venue_qid' AND q.subject_id = g.venue_id AND d.decision = 'reject' AND d.chosen = g.qid)
         ORDER BY g.venue_id, g.known_at DESC, g.id DESC""")
    op.execute("""
        COMMENT ON VIEW core.venue_geo_live IS
        'AD-H04 (IA-076): the geography in force for each stadium: the newest row of an active load that no person rejected.'""")

    op.execute("""
        CREATE VIEW core.fixture_venue_resolved AS
        SELECT f.id AS fixture_id,
               coalesce(f.venue_id, h.venue_id, k.venue_id) AS venue_id,
               CASE WHEN f.venue_id IS NOT NULL THEN 'provider' WHEN h.venue_id IS NOT NULL THEN 'manual'
                    WHEN k.venue_id IS NOT NULL THEN k.method END AS method,
               CASE WHEN f.venue_id IS NOT NULL THEN 1.0 WHEN h.venue_id IS NOT NULL THEN 1.0 ELSE k.confidence END
                   AS confidence,
               k.rules_version
          FROM core.fixtures f
          LEFT JOIN LATERAL (
                SELECT d.chosen::bigint AS venue_id FROM core.venue_review_queue q
                  JOIN LATERAL (SELECT x.decision, x.chosen FROM core.venue_review_decisions x WHERE x.queue_id = q.id
                                 ORDER BY x.decided_at DESC, x.id DESC LIMIT 1) d ON true
                 WHERE q.kind = 'fixture_venue' AND q.subject_id = f.id AND d.decision = 'accept'
                   AND d.chosen ~ '^[0-9]+$'
                 ORDER BY q.raised_at DESC LIMIT 1) h ON f.venue_id IS NULL
          LEFT JOIN LATERAL (
                SELECT l.venue_id, l.method, l.confidence, l.rules_version FROM core.fixture_venue_links l
                 WHERE l.fixture_id = f.id
                   AND NOT EXISTS (
                        SELECT 1 FROM core.venue_review_queue q
                          JOIN LATERAL (SELECT x.decision, x.chosen FROM core.venue_review_decisions x
                                         WHERE x.queue_id = q.id ORDER BY x.decided_at DESC, x.id DESC LIMIT 1) d ON true
                         WHERE q.kind = 'fixture_venue' AND q.subject_id = f.id AND d.decision = 'reject'
                           AND d.chosen = l.venue_id::text)
                 ORDER BY l.known_at DESC, l.id DESC LIMIT 1) k ON f.venue_id IS NULL AND h.venue_id IS NULL""")
    op.execute("""
        COMMENT ON VIEW core.fixture_venue_resolved IS
        'AD-H04 (IA-076): the stadium of every match: the provider''s id when it sent one (method provider), else what a person
         accepted (manual), else the newest inferred link nobody rejected (its rule). Read it filtered by fixture_id.'""")

    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON core.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION core.coaches_venues_guard()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for view in ("fixture_venue_resolved", "venue_geo_live", "venue_review_open", "coach_careers_audited"):
        op.execute(f"DROP VIEW IF EXISTS core.{view}")
    for table in ("venue_review_decisions", "venue_review_queue", "fixture_venue_links", "venue_geo", "venue_geo_loads",
                  "coach_career_corrections"):
        op.execute(f"DROP TABLE IF EXISTS core.{table}")
    op.execute("DROP FUNCTION IF EXISTS core.coaches_venues_guard()")
