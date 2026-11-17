"""decision-v2's shadow, kept (IA-093, plan piece AD-D01): ``intel.decision_v2_moments`` and ``intel.decisions_v2``, append-only

WHY THIS EXISTS
---------------
decision-v2 (``fbi.decision``) decides every market with one engine, but only in a replay that a person runs and that writes nothing:
in ``intel.decisions`` there are 0 rows of it (production, 16 Nov 2026, n = 107.109 rows). Nothing can be measured against the close,
the lifecycle cannot follow it and the evaluations E1-E4 (AD-D06) have nowhere to write their version. This revision gives it a place
of its own, beside ``intel.decisions`` and never inside it.

WHAT CHANGES
------------
``intel.decision_v2_moments``: one row per match and moment at which the shadow decided - the trigger (``E1``, T-24 to T-12 h;
``E4``, the last moment before kick-off at which the engine still decides; ``mirror``, a moment at which decision-v1 decided), the
configuration it decided under (ruleset, price, probability and its version) with its key, how many candidates and decisions, the
typed evidence of the match it cited and the fingerprint of the world it read.

``intel.decisions_v2``: one row per decision of that moment - its selection, state, reason and codes, the number it judged (source,
version, seal), the price with its source, age and state, the inputs with their time (no input is later than ``known_at``: the
database refuses a price or a model cut-off after it), the evidence it cited, every stage (the engine's ``as_json``) and the previous
decision of the same selection under the same configuration (``previous_id``), so each selection is a chain of versions.

The cycle of states (``intel.selection_lifecycle``, revision 0142) names the table each move was read from in ``source``, and its CHECK
only let letters and ``_`` after the schema: ``intel.decisions_v2`` has a digit. The CHECK is widened to a table name that may carry
digits after its first letter - nothing else of that table changes, and every row it holds already meets the new rule.

Both new tables append-only (``ai.refuse_change()``, as every table of the plan, the static test of IA-059). Nothing reads them but the shadow
itself (its chain in ``intel.selection_lifecycle`` goes through the cycle's own API) and the owner's script. ``intel.decisions`` is
not touched.

Downgrade: drops both tables (the shadow's rows are lost; ``intel.decisions`` and every layer stay as they are) and puts the cycle's
CHECK back as it was, ``NOT VALID`` (the cycle is append-only: a chain the shadow wrote stays, and only new rows are held to it).

Revision ID: 0150
Revises: 0149
"""

from __future__ import annotations

from alembic import op

revision = "0150"
down_revision = "0149"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
TRIGGERS = ("E1", "E4", "mirror")
EVALUATIONS = ("E1", "E2", "E3", "E4")
STATES = ("REJECTED", "ABSTAIN", "WATCH", "CAUTION", "RECOMMENDED")
PRICE_STATES = ("vigente", "antiguo", "sin_precio")
LIFECYCLE_SOURCE = r"^[a-z_]+\.[a-z][a-z0-9_]*$"
"""The cycle's ``source``: a schema and a table, the table's name may carry digits after its first letter (``intel.decisions_v2``)."""
LIFECYCLE_SOURCE_0142 = r"^[a-z_]+\.[a-z_]+$"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.decision_v2_moments (
            id                  BIGSERIAL    PRIMARY KEY,
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            trigger             TEXT         NOT NULL CHECK (trigger IN ({_in(TRIGGERS)})),
            evaluation          TEXT         CHECK (evaluation IS NULL OR evaluation IN ({_in(EVALUATIONS)})),
            evaluation_version  INTEGER      CHECK (evaluation_version IS NULL OR evaluation_version >= 1),
            known_at            TIMESTAMPTZ  NOT NULL,
            kickoff_at          TIMESTAMPTZ  NOT NULL,
            mirrored_version    TEXT         CHECK (mirrored_version IS NULL OR mirrored_version ~ '^decision-[a-z0-9.-]{{1,30}}$'),
            config_key          TEXT         NOT NULL CHECK (config_key ~ '^[a-z0-9.:|_-]{{3,200}}$'),
            config              JSONB        NOT NULL,
            candidates          INTEGER      NOT NULL CHECK (candidates >= 0),
            decided             INTEGER      NOT NULL CHECK (decided >= 0),
            evidence            JSONB        NOT NULL DEFAULT '[]'::jsonb,
            world_hash          TEXT         NOT NULL CHECK (world_hash ~ '{SHA256}'),
            writer_version      TEXT         NOT NULL CHECK (writer_version ~ '^decision-v2-shadow-v[0-9]+$'),
            code_version        TEXT,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT decision_v2_moments_mirror CHECK ((trigger = 'mirror') = (mirrored_version IS NOT NULL)),
            CONSTRAINT decision_v2_moments_evaluation CHECK (
                (trigger = 'mirror' AND evaluation IS NULL) OR (trigger <> 'mirror' AND evaluation = trigger)),
            CONSTRAINT decision_v2_moments_version CHECK ((evaluation IS NULL) = (evaluation_version IS NULL)),
            CONSTRAINT decision_v2_moments_before_kickoff CHECK (known_at < kickoff_at),
            CONSTRAINT decision_v2_moments_counts CHECK (decided <= candidates),
            CONSTRAINT decision_v2_moments_once UNIQUE (fixture_id, trigger, known_at, config_key)
        );
        CREATE INDEX decision_v2_moments_fixture ON intel.decision_v2_moments (fixture_id, trigger, known_at DESC);
        CREATE INDEX decision_v2_moments_kickoff ON intel.decision_v2_moments (kickoff_at);
        COMMENT ON TABLE intel.decision_v2_moments IS
          'IA-093 (AD-D01): each match and moment at which decision-v2 decided in the shadow (E1, E4 or a mirror of a decision-v1 '
          'moment), with its configuration, its counts, the evidence it cited and the fingerprint of what it read. Shadow only '
          '(FBI_DECISION_V2); append-only; nothing reads it to decide or publish.';

        CREATE TABLE intel.decisions_v2 (
            id                  BIGSERIAL    PRIMARY KEY,
            moment_id           BIGINT       NOT NULL REFERENCES intel.decision_v2_moments(id),
            previous_id         BIGINT       REFERENCES intel.decisions_v2(id),
            chain_key           TEXT         NOT NULL CHECK (length(chain_key) BETWEEN 10 AND 400),
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            family              TEXT         NOT NULL CHECK (length(family) BETWEEN 1 AND 40),
            market_key          TEXT         NOT NULL CHECK (length(market_key) BETWEEN 1 AND 40),
            selection           TEXT         NOT NULL CHECK (length(selection) BETWEEN 1 AND 60),
            line                NUMERIC(6,2) NOT NULL,
            model_hint          TEXT,
            model               TEXT         NOT NULL,
            known_at            TIMESTAMPTZ  NOT NULL,
            kickoff_at          TIMESTAMPTZ  NOT NULL,
            trigger             TEXT         NOT NULL CHECK (trigger IN ({_in(TRIGGERS)})),
            evaluation          TEXT         CHECK (evaluation IS NULL OR evaluation IN ({_in(EVALUATIONS)})),
            evaluation_version  INTEGER      CHECK (evaluation_version IS NULL OR evaluation_version >= 1),
            checkpoint          TEXT         NOT NULL,
            state               TEXT         NOT NULL CHECK (state IN ({_in(STATES)})),
            reason              TEXT         NOT NULL,
            codes               TEXT[]       NOT NULL,
            label               TEXT         CHECK (label IS NULL OR label IN ('PICK_PREMIUM', 'CANDIDATO_PARLAY')),
            version             TEXT         NOT NULL CHECK (version = 'decision-v2'),
            rules               TEXT         NOT NULL CHECK (rules ~ '^decision-v2\.[0-9]+$'),
            config_key          TEXT         NOT NULL,
            probability_source  TEXT         NOT NULL CHECK (probability_source IN ('own', 'common')),
            probability_version TEXT,
            p_model             NUMERIC(7,6) NOT NULL CHECK (p_model >= 0 AND p_model <= 1),
            p_cal               NUMERIC(7,6) CHECK (p_cal IS NULL OR (p_cal >= 0 AND p_cal <= 1)),
            calibration         TEXT,
            price_source        TEXT         NOT NULL CHECK (price_source IN ('consensus', 'book')),
            odds                NUMERIC(10,4),
            p_market            NUMERIC(7,6),
            price_at            TIMESTAMPTZ,
            price_age_minutes   NUMERIC(10,2),
            price_state         TEXT         CHECK (price_state IS NULL OR price_state IN ({_in(PRICE_STATES)})),
            model_cutoff        TIMESTAMPTZ,
            context_status      TEXT         NOT NULL,
            inputs              JSONB        NOT NULL,
            evidence            JSONB        NOT NULL,
            decision            JSONB        NOT NULL,
            input_hash          TEXT         NOT NULL CHECK (input_hash ~ '{SHA256}'),
            mirror_of           BIGINT,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT decisions_v2_no_later_price CHECK (price_at IS NULL OR price_at <= known_at),
            CONSTRAINT decisions_v2_no_later_model CHECK (model_cutoff IS NULL OR model_cutoff <= known_at),
            CONSTRAINT decisions_v2_before_kickoff CHECK (known_at < kickoff_at),
            CONSTRAINT decisions_v2_version CHECK ((evaluation IS NULL) = (evaluation_version IS NULL)),
            CONSTRAINT decisions_v2_previous CHECK (previous_id IS NULL OR previous_id < id)
        );
        CREATE UNIQUE INDEX decisions_v2_once ON intel.decisions_v2
            (moment_id, family, market_key, selection, line, COALESCE(model_hint, ''));
        CREATE INDEX decisions_v2_chain ON intel.decisions_v2 (chain_key, known_at DESC, id DESC);
        CREATE INDEX decisions_v2_fixture ON intel.decisions_v2 (fixture_id, known_at);
        COMMENT ON TABLE intel.decisions_v2 IS
          'IA-093 (AD-D01): every decision of decision-v2 in the shadow, with its stages, the number and price it judged (with their '
          'times), the evidence it cited and the previous version of the same selection. Never read to decide, stake or publish; '
          'intel.decisions is not touched. Append-only.';
        COMMENT ON COLUMN intel.decisions_v2.mirror_of IS
          'For a mirror moment: the id of the decision-v1 row of the same selection at the same moment, when there is one.';
    """)
    op.execute("CREATE TRIGGER decision_v2_moments_append_only BEFORE UPDATE OR DELETE ON intel.decision_v2_moments "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")
    op.execute("CREATE TRIGGER decisions_v2_append_only BEFORE UPDATE OR DELETE ON intel.decisions_v2 "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")
    op.execute(rf"""
        ALTER TABLE intel.selection_lifecycle DROP CONSTRAINT selection_lifecycle_source_check;
        ALTER TABLE intel.selection_lifecycle ADD CONSTRAINT selection_lifecycle_source_check
            CHECK (source ~ '{LIFECYCLE_SOURCE}');
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        ALTER TABLE intel.selection_lifecycle DROP CONSTRAINT selection_lifecycle_source_check;
        ALTER TABLE intel.selection_lifecycle ADD CONSTRAINT selection_lifecycle_source_check
            CHECK (source ~ '{LIFECYCLE_SOURCE_0142}') NOT VALID;
    """)
    op.execute("DROP TABLE IF EXISTS intel.decisions_v2")
    op.execute("DROP TABLE IF EXISTS intel.decision_v2_moments")
