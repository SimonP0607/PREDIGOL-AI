"""The estimated starters, kept (IA-094, plan piece AD-D04): ``intel.lineup_estimates``, append-only

WHY THIS EXISTS
---------------
There is no «probable line-up» stored anywhere (production, 16 Nov 2026): before the official line-up (20 minutes before kick-off at the
median, AD-D05) nothing says, with data and a source, how likely each player is to start. ``lineup-estimate-v1``
(``fbi.players.lineup_estimate``) estimates it from recent minutes, confirmed absences (IA-091) and facts «titular» with their rung; this
revision keeps each estimate with its moment, so that the models that need it (AD-B08, AD-D03) and the evaluation E3 (AD-D07) can read
what was known then, and so that it can be measured against the official line-up.

WHAT CHANGES
------------
``intel.lineup_estimates``: one row per player, side, match and evaluation (``E1``, T-24 to T-12 h; ``E4``, before the engine's floor of
10 minutes) - the probability that he starts and that he plays, his expected minutes, the basis (recent minutes, a confirmed absence, a
fact «titular», the official sheet), the sample behind the share, the absence's state and basis (one of four words: no health detail),
the rung and ids of the facts it used, the seal (``sin_calibrar`` until the owner signs a competition), the versions, and the moment.
Append-only (``ai.refuse_change()``, as every table of the plan). Nothing reads it but the owner's script; no reader, pick or decision.

Downgrade: drops the table (the estimates are lost; nothing else depends on them).

Revision ID: 0151
Revises: 0150
"""

from __future__ import annotations

from alembic import op

revision = "0151"
down_revision = "0150"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
EVALUATIONS = ("E1", "E4")
BASES = ("confirmed_starter", "confirmed_bench", "not_in_lineup", "baja_confirmada", "minutos_recientes", "con_hecho_titular")
STATUSES = ("disponible", "duda", "baja", "sancionado")
AVAILABILITY_BASES = ("oficial", "proveedor", "dos_origenes", "un_medio")
RUNGS = ("oficial", "dos_origenes", "un_medio", "rumor")
SEALS = ("calibrada", "sin_calibrar")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.lineup_estimates (
            id                  BIGSERIAL    PRIMARY KEY,
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            team_id             BIGINT       NOT NULL REFERENCES core.teams(id),
            provider_player_id  INTEGER      NOT NULL CHECK (provider_player_id > 0),
            evaluation          TEXT         NOT NULL CHECK (evaluation IN ({_in(EVALUATIONS)})),
            known_at            TIMESTAMPTZ  NOT NULL,
            kickoff_at          TIMESTAMPTZ  NOT NULL,
            position            TEXT         NOT NULL CHECK (position IN ('G', 'D', 'M', 'F', '?')),
            p_start             NUMERIC(5,4) NOT NULL CHECK (p_start >= 0 AND p_start <= 1),
            p_play              NUMERIC(5,4) NOT NULL CHECK (p_play >= 0 AND p_play <= 1),
            expected_minutes    NUMERIC(5,1) NOT NULL CHECK (expected_minutes >= 0 AND expected_minutes <= 130),
            basis               TEXT         NOT NULL CHECK (basis IN ({_in(BASES)})),
            sample              INTEGER      NOT NULL CHECK (sample >= 0),
            share               NUMERIC(5,4) CHECK (share IS NULL OR (share >= 0 AND share <= 1)),
            started_last        BOOLEAN,
            absence_status      TEXT         CHECK (absence_status IS NULL OR absence_status IN ({_in(STATUSES)})),
            absence_basis       TEXT         CHECK (absence_basis IS NULL OR absence_basis IN ({_in(AVAILABILITY_BASES)})),
            fact_rung           TEXT         CHECK (fact_rung IS NULL OR fact_rung IN ({_in(RUNGS)})),
            fact_ids            BIGINT[]     NOT NULL DEFAULT '{{}}',
            seal                TEXT         NOT NULL CHECK (seal IN ({_in(SEALS)})),
            lineup_confirmed    BOOLEAN      NOT NULL,
            history_matches     INTEGER      NOT NULL CHECK (history_matches >= 0),
            start_model_samples INTEGER      NOT NULL CHECK (start_model_samples >= 0),
            start_model_fitted  BOOLEAN      NOT NULL,
            version             TEXT         NOT NULL CHECK (version ~ '^lineup-estimate-v[0-9]+$'),
            model               TEXT         NOT NULL CHECK (model ~ '^player-engine-v[0-9]+$'),
            input_hash          TEXT         NOT NULL CHECK (input_hash ~ '{SHA256}'),
            code_version        TEXT,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT lineup_estimates_before_kickoff CHECK (known_at < kickoff_at),
            CONSTRAINT lineup_estimates_absence_pair CHECK ((absence_status IS NULL) = (absence_basis IS NULL)),
            CONSTRAINT lineup_estimates_play CHECK (p_play >= p_start),
            CONSTRAINT lineup_estimates_out CHECK (basis <> 'baja_confirmada' OR (p_start = 0 AND p_play = 0)),
            CONSTRAINT lineup_estimates_once UNIQUE (fixture_id, team_id, provider_player_id, evaluation, version)
        );
        CREATE INDEX lineup_estimates_fixture ON intel.lineup_estimates (fixture_id, evaluation, team_id);
        CREATE INDEX lineup_estimates_kickoff ON intel.lineup_estimates (kickoff_at);
        COMMENT ON TABLE intel.lineup_estimates IS
          'IA-094 (AD-D04): the estimated starters of a tracked match at E1 and E4 (lineup-estimate-v1): recent minutes, confirmed '
          'absences and facts with their rung; sealed sin_calibrar until the owner signs a competition. Shadow only '
          '(FBI_LINEUP_ESTIMATE); append-only; nothing reads it to decide or publish; no health detail.';
    """)
    op.execute("CREATE TRIGGER lineup_estimates_append_only BEFORE UPDATE OR DELETE ON intel.lineup_estimates "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS intel.lineup_estimates")
