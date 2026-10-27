"""Plan Maestro IA, Phase 2 - the evidence learns who it is about and how long it lives, and the research cache learns one scope.

Research v2 keeps one answer per entity and topic, shared by every match and every agent, so a piece of evidence must say which entity it is
about (``subject_type`` + ``subject_id``), what kind of claim it is (``claim_type``: the words of ``claim-v1``), how reliable its source is
as a class (``source_class``: the words of ``mcp-v1``) and until when it can be reused without asking again (``fresh_until``). The cache
needs a scope for the answers of an entity (``entity``).

Everything is additive: the five columns are NULL for every row written before and for every row the code that ran before writes (it does
not know them), nothing is copied, moved or rewritten, and the vocabularies are CHECKs that name the words of the code (a test holds the
two together). The immutability guard of the evidence (``ai.evidence_guard``, 0072) learns the five columns: they are content, and the
content of evidence never changes - a claim is typed when it is written, never afterwards.

Downgrade: the old list of scopes comes back NOT VALID (the rows already written of the new scope stay: a cache row is not worth a failed
downgrade, and the code that ran before never reads it). The columns and the guard stay as they are: the older code writes NULL in the columns
and the guard only adds rules about them, so leaving them is harmless, while dropping them would delete the typing of what was read.

Revision ID: 0114
Revises: 0113
"""

from __future__ import annotations

from alembic import op

revision = "0114"
down_revision = "0113"
branch_labels = None
depends_on = None

CLAIM_TYPES = ("OUT", "DOUBT", "AVAILABLE", "STARTER", "SUSPENSION", "COACH", "SCHEDULE", "VENUE", "OTHER")
SUBJECT_TYPES = ("TEAM", "PLAYER", "COACH", "REFEREE", "MATCH", "COMPETITION")
SOURCE_CLASSES = ("OFFICIAL", "PROVIDER", "JOURNALIST", "RELIABLE_MEDIA", "LOCAL_MEDIA", "AGGREGATOR", "SOCIAL", "UNKNOWN")
OLD_SCOPES = ("fixture", "team", "player", "url", "story", "search")

CONTENT = ("fixture_id", "team_id", "provider_player_id", "kind", "claim", "origin", "source_name", "source_url", "source_domain", "source_tier",
           "author", "published_at", "retrieved_at", "event_at", "story_key", "content_hash", "payload_hash", "confidence", "relevance", "attributes")
NEW_CONTENT = ("claim_type", "subject_type", "subject_id", "source_class", "fresh_until")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _tuple(prefix: str, columns: tuple[str, ...]) -> str:
    return ", ".join(f"{prefix}.{c}" for c in columns)


def _guard(columns: tuple[str, ...]) -> str:
    """The guard of 0072 with the columns given as the content that never changes."""
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
    # Both tables are small and written a few times a minute at most, but never wait for a lock longer than 10 s (the lesson of 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.evidence
            ADD COLUMN IF NOT EXISTS claim_type   TEXT CHECK (claim_type IN ({_in(CLAIM_TYPES)})),
            ADD COLUMN IF NOT EXISTS subject_type TEXT CHECK (subject_type IN ({_in(SUBJECT_TYPES)})),
            ADD COLUMN IF NOT EXISTS subject_id   BIGINT CHECK (subject_id IS NULL OR subject_id > 0),
            ADD COLUMN IF NOT EXISTS source_class TEXT CHECK (source_class IN ({_in(SOURCE_CLASSES)})),
            ADD COLUMN IF NOT EXISTS fresh_until  TIMESTAMPTZ;
        ALTER TABLE ai.evidence DROP CONSTRAINT IF EXISTS evidence_subject_pair;
        ALTER TABLE ai.evidence ADD CONSTRAINT evidence_subject_pair CHECK ((subject_type IS NULL) = (subject_id IS NULL));
        CREATE INDEX IF NOT EXISTS ai_evidence_subject ON ai.evidence (subject_type, subject_id, retrieved_at DESC)
            WHERE subject_type IS NOT NULL;
        COMMENT ON COLUMN ai.evidence.fresh_until IS
          'Until when what was retrieved can be reused without asking again (research v2; NULL for v1 rows).';
        {_guard((*CONTENT, *NEW_CONTENT))}
        ALTER TABLE ai.research_cache DROP CONSTRAINT research_cache_scope_check;
        ALTER TABLE ai.research_cache ADD CONSTRAINT research_cache_scope_check CHECK (scope IN ({_in(OLD_SCOPES)}, 'entity'));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.research_cache DROP CONSTRAINT research_cache_scope_check;
        ALTER TABLE ai.research_cache ADD CONSTRAINT research_cache_scope_check CHECK (scope IN ({_in(OLD_SCOPES)})) NOT VALID;
    """)
