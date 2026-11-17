"""The player forecasts, kept (IA-129, plan piece AD-B08): ``intel.player_forecasts``, append-only

WHY THIS EXISTS
---------------
``player-engine-v1`` priced every player market and kept nothing: no forecast of a player could be checked after the match against what
was known before it. ``player-engine-v2`` (``fbi.players.v2``) prices each market as expected minutes x rate per 90 x the probability
that he starts, taking that probability from the estimated starters (``lineup-estimate-v1``, AD-D04), and this revision keeps every
forecast with its moment, its versions and the sample behind it.

WHAT CHANGES
------------
``intel.player_forecasts``: one row per player, family, line, match and evaluation (``E1``, T-24 to T-12 h; ``E4``, T-20 to T-10 min) -
P(count > line) unconditional and if he plays, the mean, the start and bench probabilities, the minutes if he starts and if he comes on,
the expected minutes, the rate per 90 (his own, the prior, the opponent's factor) with its 90-minute units, the dispersion, the basis
and sample of the start probability, whether the official sheet was read, the seal, the versions and the moment. Append-only
(``ai.refuse_change()``). Nothing reads it but the owner's script: no reader, pick or decision. Only availability states enter (one of
the estimate's bases), never a health detail.

Downgrade: drops the table (the forecasts are lost; nothing else depends on them).

Revision ID: 0163
Revises: 0162
"""

from __future__ import annotations

from alembic import op

revision = "0163"
down_revision = "0162"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
EVALUATIONS = ("E1", "E4")
FAMILIES = ("player_goals", "player_assists", "player_shots", "player_shots_on", "player_fouls", "player_cards", "keeper_saves")
STATS = ("goals", "assists", "shots", "shots_on", "fouls", "cards", "saves")
BASES = ("confirmed_starter", "confirmed_bench", "not_in_lineup", "baja_confirmada", "minutos_recientes", "con_hecho_titular")
SEALS = ("calibrada", "sin_calibrar")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.player_forecasts (
            id                  BIGSERIAL    PRIMARY KEY,
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id),
            team_id             BIGINT       NOT NULL REFERENCES core.teams(id),
            opponent_id         BIGINT       NOT NULL REFERENCES core.teams(id),
            provider_player_id  INTEGER      NOT NULL CHECK (provider_player_id > 0),
            evaluation          TEXT         NOT NULL CHECK (evaluation IN ({_in(EVALUATIONS)})),
            known_at            TIMESTAMPTZ  NOT NULL,
            kickoff_at          TIMESTAMPTZ  NOT NULL,
            position            TEXT         NOT NULL CHECK (position IN ('G', 'D', 'M', 'F', '?')),
            family              TEXT         NOT NULL CHECK (family IN ({_in(FAMILIES)})),
            stat                TEXT         NOT NULL CHECK (stat IN ({_in(STATS)})),
            line                NUMERIC(4,1) NOT NULL CHECK (line > 0 AND line % 1 = 0.5),
            p_over              NUMERIC(5,4) NOT NULL CHECK (p_over >= 0 AND p_over <= 1),
            p_over_if_plays     NUMERIC(5,4) CHECK (p_over_if_plays IS NULL OR (p_over_if_plays >= 0 AND p_over_if_plays <= 1)),
            mean                NUMERIC(8,4) NOT NULL CHECK (mean >= 0),
            p_start             NUMERIC(5,4) NOT NULL CHECK (p_start >= 0 AND p_start <= 1),
            p_sub               NUMERIC(5,4) NOT NULL CHECK (p_sub >= 0 AND p_sub <= 1),
            p_play              NUMERIC(5,4) NOT NULL CHECK (p_play >= 0 AND p_play <= 1),
            minutes_start       NUMERIC(5,1) NOT NULL CHECK (minutes_start >= 0 AND minutes_start <= 130),
            minutes_sub         NUMERIC(5,1) NOT NULL CHECK (minutes_sub >= 0 AND minutes_sub <= 130),
            expected_minutes    NUMERIC(5,1) NOT NULL CHECK (expected_minutes >= 0 AND expected_minutes <= 130),
            per90               NUMERIC(8,4) NOT NULL CHECK (per90 >= 0),
            player_per90        NUMERIC(8,4) NOT NULL CHECK (player_per90 >= 0),
            prior_per90         NUMERIC(8,4) NOT NULL CHECK (prior_per90 >= 0),
            opponent_factor     NUMERIC(6,3) NOT NULL CHECK (opponent_factor > 0),
            nineties            NUMERIC(8,2) NOT NULL CHECK (nineties >= 0),
            phi                 NUMERIC(8,4) NOT NULL CHECK (phi >= 0),
            start_basis         TEXT         NOT NULL CHECK (start_basis IN ({_in(BASES)})),
            start_sample        INTEGER      NOT NULL CHECK (start_sample >= 0),
            lineup_confirmed    BOOLEAN      NOT NULL,
            seal                TEXT         NOT NULL CHECK (seal IN ({_in(SEALS)})),
            tail                NUMERIC(9,6) NOT NULL CHECK (tail >= 0),
            history_matches     INTEGER      NOT NULL CHECK (history_matches >= 0),
            version             TEXT         NOT NULL CHECK (version ~ '^player-engine-v[0-9]+$'),
            estimate_version    TEXT         NOT NULL CHECK (estimate_version ~ '^lineup-estimate-v[0-9]+$'),
            input_hash          TEXT         NOT NULL CHECK (input_hash ~ '{SHA256}'),
            code_version        TEXT,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT player_forecasts_before_kickoff CHECK (known_at < kickoff_at),
            CONSTRAINT player_forecasts_play CHECK (p_play >= p_start),
            CONSTRAINT player_forecasts_no_play CHECK (p_play > 0 OR p_over = 0),
            CONSTRAINT player_forecasts_official CHECK (start_basis NOT IN ('confirmed_starter', 'confirmed_bench', 'not_in_lineup')
                                                        OR p_start IN (0, 1)),
            CONSTRAINT player_forecasts_once UNIQUE (fixture_id, provider_player_id, evaluation, family, line, version)
        );
        CREATE INDEX player_forecasts_fixture ON intel.player_forecasts (fixture_id, evaluation, team_id);
        CREATE INDEX player_forecasts_kickoff ON intel.player_forecasts (kickoff_at);
        COMMENT ON TABLE intel.player_forecasts IS
          'IA-129 (AD-B08): player-engine-v2 forecasts of every player market at E1 and E4: expected minutes x rate per 90 (with its '
          'sample) x the start probability of lineup-estimate-v1. Shadow only (FBI_PLAYER_ENGINE_V2); append-only; nothing reads it '
          'to decide or publish; no health detail.';
    """)
    op.execute("CREATE TRIGGER player_forecasts_append_only BEFORE UPDATE OR DELETE ON intel.player_forecasts "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS intel.player_forecasts")
