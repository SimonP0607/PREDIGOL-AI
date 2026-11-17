"""The credibility of a source by type of fact, kept by version (IA-126, plan piece AD-C08), and the gate of the new extraction protocol
(IA-127, AD-C09)

WHY THIS EXISTS
---------------
``credibility-v1`` learns one number per source and keeps it nowhere: it is recomputed at every reading and cannot be shown, compared or
audited. ``credibility-v2`` learns it per type of fact (out, suspended, starts, available), with its sample and its 95 % interval; the
owner's console and the source's card in the registry read it back, and two versions must be comparable side by side.

The extraction is measured from now on against people's labels on whole pages (``extract-protocol-v1``, the protocol ``AD-C09``), not
against research v1. Its verdict needs a gate of its own: writing it as a row of ``research_v2`` would make it the newest row of that gate
and change what ``fbi.ai.gates.research_mode`` reads - the NO PASA of row 17 must stay what it says.

WHAT CHANGES
------------
* ``ai.source_credibility``: one row per version, moment (``as_of``), source (outlet and tier) and type of fact - resolved and corroborated
  claims, the shrunk value, the raw rate and its Wilson interval, whether it reaches the registered minimum. Append-only
  (``ai.refuse_change()``); a snapshot written twice at the same moment is written once (``source_credibility_once``). Nothing that decides,
  publishes or serves a reader reads it.
* ``ai.feature_gates``: the gate ``extract_protocol`` is admitted (the owner's signature of the protocol and the measured verdicts). No row
  is written here; no other gate's rows are touched.

Downgrade: drops the table and admits the gates as they were (refused while a row of ``extract_protocol`` exists: it would be lost).

Revision ID: 0162
Revises: 0161
"""

from __future__ import annotations

from alembic import op

revision = "0162"
down_revision = "0161"
branch_labels = None
depends_on = None

FACT_TYPES = ("baja", "sancion", "titularidad", "disponible")
TIERS = ("A", "B", "C", "D")
GATES_BEFORE = ("batch", "native_schema", "cache_layout", "gate_a", "battery", "research_v2", "switches", "gate_b", "lab_plan")
NEW_GATES = ("extract_protocol",)
GATES = (*GATES_BEFORE, *NEW_GATES)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE ai.source_credibility (
            id            BIGSERIAL     PRIMARY KEY,
            version       TEXT          NOT NULL CHECK (version ~ '^credibility-v[0-9]+$'),
            digest        TEXT          NOT NULL CHECK (digest ~ '^[0-9a-f]{{12}}$'),
            as_of         TIMESTAMPTZ   NOT NULL,
            outlet        TEXT          NOT NULL CHECK (length(outlet) BETWEEN 1 AND 253),
            tier          TEXT          NOT NULL CHECK (tier IN ({_in(TIERS)})),
            fact_type     TEXT          NOT NULL CHECK (fact_type IN ({_in(FACT_TYPES)})),
            resolved      INTEGER       NOT NULL CHECK (resolved >= 0),
            corroborated  INTEGER       NOT NULL CHECK (corroborated >= 0 AND corroborated <= resolved),
            value         NUMERIC(6,4)  NOT NULL CHECK (value >= 0 AND value <= 1),
            basis         TEXT          NOT NULL CHECK (basis IN ('prior', 'learned')),
            prior         NUMERIC(6,4)  NOT NULL CHECK (prior >= 0 AND prior <= 1),
            rate          NUMERIC(6,4)  CHECK (rate IS NULL OR (rate >= 0 AND rate <= 1)),
            ci_low        NUMERIC(6,4)  CHECK (ci_low IS NULL OR (ci_low >= 0 AND ci_low <= 1)),
            ci_high       NUMERIC(6,4)  CHECK (ci_high IS NULL OR (ci_high >= 0 AND ci_high <= 1)),
            sufficient    BOOLEAN       NOT NULL,
            min_resolved  INTEGER       NOT NULL CHECK (min_resolved >= 1),
            typed         BOOLEAN       NOT NULL,
            detail        JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            code_version  TEXT,
            recorded_at   TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT source_credibility_learned CHECK ((basis = 'prior') = (resolved = 0)),
            CONSTRAINT source_credibility_interval CHECK (
                (resolved = 0 AND rate IS NULL AND ci_low IS NULL AND ci_high IS NULL)
                OR (resolved > 0 AND rate IS NOT NULL AND ci_low IS NOT NULL AND ci_high IS NOT NULL AND ci_low <= ci_high)),
            CONSTRAINT source_credibility_sufficient CHECK (sufficient = (resolved >= min_resolved)),
            CONSTRAINT source_credibility_once UNIQUE (version, as_of, outlet, tier, fact_type)
        );
        CREATE INDEX source_credibility_outlet ON ai.source_credibility (outlet, version, as_of DESC);
        CREATE INDEX source_credibility_as_of ON ai.source_credibility (version, as_of DESC);
        COMMENT ON TABLE ai.source_credibility IS
          'IA-126 (AD-C08): the credibility of each source by type of fact (credibility-v2), as of a moment, with its sample and its '
          'Wilson 95-percent interval; insufficient below the registered minimum. Written by code (FBI_SOURCE_CREDIBILITY=shadow); '
          'append-only; it informs and decides nothing: no status, tier, packet, decision or pick reads it.';
    """)
    op.execute("CREATE TRIGGER source_credibility_append_only BEFORE UPDATE OR DELETE ON ai.source_credibility "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")
    op.execute(f"""
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES)}));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM ai.feature_gates WHERE gate IN ({_in(NEW_GATES)})) THEN
                RAISE EXCEPTION 'ai.feature_gates has rows of the gate extract_protocol: a downgrade would lose them';
            END IF;
        END $$;
        ALTER TABLE ai.feature_gates DROP CONSTRAINT feature_gates_gate_check;
        ALTER TABLE ai.feature_gates ADD CONSTRAINT feature_gates_gate_check CHECK (gate IN ({_in(GATES_BEFORE)}));
    """)
    op.execute("DROP TABLE IF EXISTS ai.source_credibility")
