"""The facts each evaluation used (IA-122, plan piece AD-G08, contract C-07): two append-only tables of ``intel``, written with the evaluation

WHY THIS EXISTS
---------------
97,7 % of the web evidence is already linked to a match and 90,9 % to a team, but there is no way back from an analysis to the news it
read (production, 16-nov-2026, n = 5.721). Contract C-07 («Fuentes del análisis») needs that way back - the facts an evaluation E1-E4 took
into account, each with its relation to the analysis (``a_favor``, ``en_contra``, ``contexto``, ``no_usada``) and the moment it was known -
and the plan forbids the easy way of building it: a relation drawn AFTER the decision, from what is known today, would show the analysis as
having used facts it could not see (the temporal leak of AD-A04). So the list is written by the evaluation itself, at the moment of its
decision, by the validator of ``fbi.factlinks`` (``link-v1``): a link needs the entity by its id, a literal quote that names it and a fact
dated inside the match's window.

WHAT CHANGES
------------
- ``intel.eval_source_lists``: one row per evaluation (``intel.eval_runs``) - how many facts it looked at, how many the validator linked
  and refused, by relation - so an evaluation without facts says so (an empty list is a row, not an absence).
- ``intel.eval_sources``: one row per fact looked at - linked (with its entity, level, relation and what it did to each selection) or
  refused with the validator's reason (``homonimo``, ``fuera_de_ventana``, ``sin_cita_literal`` ...). The quote itself is not copied: it
  stays in ``ai.evidence``; only the name it was found under.

The guard ``intel.eval_sources_at_decision()`` (BEFORE INSERT on both) refuses a row that is not written in the same transaction as its
evaluation (``now()`` must equal the run's ``created_at``), that names another match or step, that belongs to a failed run, or - for a fact
- whose ``fact_known_at`` is after the moment the evaluation decided as of: no relation is ever written afterwards. Both tables are
append-only (``ai.refuse_change()``).

Downgrade: drops the two tables and the guard (the lists are lost; the evaluations stay).

Revision ID: 0160
Revises: 0159
"""

from __future__ import annotations

from alembic import op

revision = "0160"
down_revision = "0159"
branch_labels = None
depends_on = None

EVALUATIONS = ("E1", "E2", "E3", "E4")
RELATIONS = ("a_favor", "en_contra", "contexto", "no_usada")
LEVELS = ("oficial", "dos_origenes", "declaracion", "un_medio", "rumor")
WARNINGS = ("contradiccion",)
REJECTIONS = ("posterior_a_la_decision", "otro_partido", "sin_entidad", "entidad_ajena", "sin_cita_literal", "cita_sin_nombre",
              "homonimo", "sin_fecha", "fuera_de_ventana")
ENTITY_TYPES = ("team", "player")
SOURCE_TYPES = ("oficial", "agencia", "prensa")
E2_ACTIONS = ("recalcula", "anota")
TABLES = ("eval_source_lists", "eval_sources")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.eval_source_lists (
            id                  BIGSERIAL    PRIMARY KEY,
            run_id              BIGINT       NOT NULL UNIQUE REFERENCES intel.eval_runs(id),
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            evaluation          TEXT         NOT NULL CHECK (evaluation IN ({_in(EVALUATIONS)})),
            evaluation_version  INTEGER      NOT NULL CHECK (evaluation_version >= 1),
            known_at            TIMESTAMPTZ  NOT NULL,
            candidates          INTEGER      NOT NULL CHECK (candidates >= 0),
            linked              INTEGER      NOT NULL CHECK (linked >= 0),
            rejected            INTEGER      NOT NULL CHECK (rejected >= 0),
            by_relation         JSONB        NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(by_relation) = 'object'),
            by_rejection        JSONB        NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(by_rejection) = 'object'),
            version             TEXT         NOT NULL CHECK (version ~ '^link-v[0-9]+$'),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT eval_source_lists_add_up CHECK (linked + rejected = candidates)
        );
        CREATE INDEX eval_source_lists_fixture ON intel.eval_source_lists (fixture_id, id DESC);
        COMMENT ON TABLE intel.eval_source_lists IS
          'IA-122 (AD-G08, C-07): one row per evaluation E1-E4 - the facts it looked at, linked and refused by the validator link-v1. '
          'Written in the transaction of the evaluation (intel.eval_sources_at_decision); append-only.';

        CREATE TABLE intel.eval_sources (
            id                  BIGSERIAL    PRIMARY KEY,
            list_id             BIGINT       NOT NULL REFERENCES intel.eval_source_lists(id),
            run_id              BIGINT       NOT NULL REFERENCES intel.eval_runs(id),
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            evidence_id         BIGINT       NOT NULL,
            item_id             BIGINT,
            linked              BOOLEAN      NOT NULL,
            rejection           TEXT         CHECK (rejection IN ({_in(REJECTIONS)})),
            relation            TEXT         CHECK (relation IN ({_in(RELATIONS)})),
            level               TEXT         CHECK (level IN ({_in(LEVELS)})),
            warning             TEXT         CHECK (warning IN ({_in(WARNINGS)})),
            entity_type         TEXT         CHECK (entity_type IN ({_in(ENTITY_TYPES)})),
            entity_id           BIGINT       CHECK (entity_id >= 1),
            team_id             BIGINT,
            provider_player_id  INTEGER,
            named_as            TEXT         CHECK (length(btrim(named_as)) BETWEEN 1 AND 120),
            kind                TEXT         NOT NULL CHECK (length(kind) BETWEEN 1 AND 40),
            assertion           TEXT         CHECK (length(assertion) BETWEEN 1 AND 40),
            source_name         TEXT         NOT NULL CHECK (length(btrim(source_name)) BETWEEN 1 AND 200),
            source_url          TEXT         CHECK (source_url ~ '^https?://' AND length(source_url) <= 2000),
            source_tier         TEXT         NOT NULL CHECK (length(source_tier) BETWEEN 1 AND 40),
            source_type         TEXT         NOT NULL CHECK (source_type IN ({_in(SOURCE_TYPES)})),
            fact_at             TIMESTAMPTZ,
            fact_known_at       TIMESTAMPTZ  NOT NULL,
            decided_at          TIMESTAMPTZ  NOT NULL,
            e2_action           TEXT         CHECK (e2_action IN ({_in(E2_ACTIONS)})),
            selections          JSONB        NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(selections) = 'array'),
            version             TEXT         NOT NULL CHECK (version ~ '^link-v[0-9]+$'),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT eval_sources_once UNIQUE (run_id, evidence_id),
            CONSTRAINT eval_sources_known_before_decision CHECK (fact_known_at <= decided_at),
            CONSTRAINT eval_sources_dated_before_decision CHECK (fact_at IS NULL OR fact_at <= decided_at),
            CONSTRAINT eval_sources_linked_or_refused CHECK (linked = (rejection IS NULL)),
            CONSTRAINT eval_sources_relation_only_when_linked CHECK (linked = (relation IS NOT NULL)),
            CONSTRAINT eval_sources_link_needs_its_three CHECK (
                NOT linked OR (entity_type IS NOT NULL AND entity_id IS NOT NULL AND named_as IS NOT NULL AND fact_at IS NOT NULL)),
            CONSTRAINT eval_sources_level_or_warning CHECK (NOT linked OR (level IS NOT NULL) <> (warning IS NOT NULL)),
            CONSTRAINT eval_sources_a_rumour_is_not_used CHECK (level IS DISTINCT FROM 'rumor' OR relation IS NULL OR relation = 'no_usada')
        );
        CREATE INDEX eval_sources_fixture ON intel.eval_sources (fixture_id, run_id);
        CREATE INDEX eval_sources_item ON intel.eval_sources (item_id) WHERE item_id IS NOT NULL;
        COMMENT ON TABLE intel.eval_sources IS
          'IA-122 (AD-G08, C-07): each fact an evaluation looked at, linked by link-v1 (entity by id, a literal quote naming it, dated '
          'inside the match window) with its relation to the analysis, or refused with the reason. fact_known_at <= decided_at always; '
          'written with the evaluation, never afterwards; append-only. The quote stays in ai.evidence.';

        CREATE FUNCTION intel.eval_sources_at_decision() RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            r RECORD;
        BEGIN
            SELECT fixture_id, evaluation, evaluation_version, known_at, status, created_at INTO r
              FROM intel.eval_runs WHERE id = NEW.run_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'intel.%: no evaluation %', TG_TABLE_NAME, NEW.run_id USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF r.created_at <> now() THEN
                RAISE EXCEPTION 'intel.%: the facts of an evaluation are written with it, in its transaction - never afterwards',
                    TG_TABLE_NAME USING ERRCODE = 'check_violation';
            END IF;
            IF r.status = 'fallida' THEN
                RAISE EXCEPTION 'intel.%: a failed evaluation used no fact', TG_TABLE_NAME USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.fixture_id <> r.fixture_id THEN
                RAISE EXCEPTION 'intel.%: the evaluation is of another match', TG_TABLE_NAME USING ERRCODE = 'check_violation';
            END IF;
            IF TG_TABLE_NAME = 'eval_source_lists' THEN
                IF NEW.known_at <> r.known_at OR NEW.evaluation <> r.evaluation OR NEW.evaluation_version <> r.evaluation_version THEN
                    RAISE EXCEPTION 'intel.eval_source_lists: the list says another moment or step than its evaluation'
                        USING ERRCODE = 'check_violation';
                END IF;
            ELSIF NEW.decided_at <> r.known_at THEN
                RAISE EXCEPTION 'intel.eval_sources: decided_at is the moment its evaluation read as of' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER {table}_at_decision BEFORE INSERT ON intel.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION intel.eval_sources_at_decision()")
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON intel.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS intel.{table}")
    op.execute("DROP FUNCTION IF EXISTS intel.eval_sources_at_decision()")
