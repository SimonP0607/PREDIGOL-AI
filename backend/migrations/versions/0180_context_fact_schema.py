"""ai.evidence learns the one schema of a context fact (plan RP-4.1, finding H16): the new kinds, the origin «own calculation», the side a fact affects

WHY THIS EXISTS
---------------
88 % of the facts of ``ai.evidence`` are about availability: there is no kind for what a team plays for, for a rotation, a statement, the referee, the
formation or the competition's format, and nothing says whom a fact affects. The plan asks that every NEW fact carry seven attributes (source, its
date, entity, state, validity, evidence, relation to the match) and belong to one of five categories (``fbi.ai.factor_schema``). The store is the
same one - no second table - and what it already holds stays as it is.

WHAT CHANGES (additive; ``lock_timeout`` 10 s; no row is rewritten)
* ``kind`` accepts six more words (``stakes``, ``rotation``, ``statement``, ``referee``, ``formation``, ``format``) and ``origin`` one more
  (``own_calc``: a fact PrediGol calculated from data already in the database).
* Two nullable columns: ``side`` (``home``, ``away``, ``both`` or ``match``: whom the fact affects) and ``fact_schema`` (``context-fact-v1``: the
  fact was written under the schema and is complete). Validity is the column that already exists (``fresh_until``).
* A fact with ``fact_schema`` set must be complete (a side, a validity, the source's date, an entity, a source with a name): the database refuses it
  otherwise. The new kinds and the new origin exist only under the schema. A row without ``fact_schema`` - every row written before, and everything
  the code that ran before writes - is exactly what it was.
* The content guard of the table (``ai.evidence_guard``) learns the two columns: they are content, and the content of evidence never changes.

The category of a fact is NOT a column: it follows from the state, which changes as a fact is corroborated or goes stale (``factor_schema.category_of``).

Downgrade: the old lists come back NOT VALID (rows already written with a new word stay: a fact is not worth a failed downgrade); the columns and the
guard stay, as in 0114.

Revision ID: 0180
Revises: 0179
"""

from __future__ import annotations

from alembic import op

revision = "0180"
down_revision = "0179"
branch_labels = None
depends_on = None

OLD_KINDS = ("injury", "suspension", "doubtful", "lineup", "coach", "news", "transfer", "motivation", "weather", "travel", "schedule", "other")
NEW_KINDS = ("stakes", "rotation", "statement", "referee", "formation", "format")
OLD_ORIGINS = ("provider", "web", "owner")
SIDES = ("home", "away", "both", "match")

CONTENT = ("fixture_id", "team_id", "provider_player_id", "kind", "claim", "origin", "source_name", "source_url", "source_domain", "source_tier",
           "author", "published_at", "retrieved_at", "event_at", "story_key", "content_hash", "payload_hash", "confidence", "relevance", "attributes",
           "claim_type", "subject_type", "subject_id", "source_class", "fresh_until", "item_id")
NEW_CONTENT = ("side", "fact_schema")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _tuple(prefix: str, columns: tuple[str, ...]) -> str:
    return ", ".join(f"{prefix}.{c}" for c in columns)


def _guard(columns: tuple[str, ...]) -> str:
    """The guard of 0114 with the columns given as the content that never changes."""
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


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.evidence
            ADD COLUMN IF NOT EXISTS side        TEXT CHECK (side IN ({_in(SIDES)})),
            ADD COLUMN IF NOT EXISTS fact_schema TEXT CHECK (fact_schema = 'context-fact-v1');
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_kind_check;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_kind_check CHECK (kind IN ({_in((*OLD_KINDS, *NEW_KINDS))}));
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_origin_check;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_origin_check CHECK (origin IN ({_in((*OLD_ORIGINS, "own_calc"))}));
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_fact_complete;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_fact_complete CHECK (
            fact_schema IS NULL OR (side IS NOT NULL AND fresh_until IS NOT NULL AND published_at IS NOT NULL AND subject_type IS NOT NULL
                                    AND length(btrim(source_name)) > 0));
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_new_words_need_schema;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_new_words_need_schema CHECK (
            fact_schema IS NOT NULL OR (kind IN ({_in(OLD_KINDS)}) AND origin IN ({_in(OLD_ORIGINS)})));
        COMMENT ON COLUMN ai.evidence.side IS
          'Whom the fact affects: home, away, both or match (context-fact-v1; NULL for rows written before).';
        COMMENT ON COLUMN ai.evidence.fact_schema IS
          'The fact was written under the one schema of a context fact and is complete: seven attributes (source, its date, entity, state, validity, '
          'evidence, relation). NULL for every row written before it.';
        {_guard((*CONTENT, *NEW_CONTENT))}
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_new_words_need_schema;
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_kind_check;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_kind_check CHECK (kind IN ({_in(OLD_KINDS)})) NOT VALID;
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_origin_check;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_origin_check CHECK (origin IN ({_in(OLD_ORIGINS)})) NOT VALID;
    """)
