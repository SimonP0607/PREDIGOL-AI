"""The reduced Council of the shadow (IA-124, plan piece AD-D10): ``ai.council_reduced``, append-only

WHY THIS EXISTS
---------------
The deterministic protocol of the Council (``council-protocol-v1``) is computed only on demand and keeps nothing, and the judge with a model
(``council-v1``) reads every selection of every pass of the shadow. The plan makes the rules the default and the judge the exception: only a
material contradiction, with value at stake and time to read three times, calls it, and its majority can only lower. Without a row per
selection nobody can tell that every selection was aggregated by the rules, that the judge was wanted only where a material contradiction
was recorded, or that the Council never raised a state.

WHAT CHANGES
------------
``ai.council_reduced``: one row per pass of the shadow (``ai.match_runs``), candidate and version (``council-reduced-v1``): the rules'
``ctx-adj-v1`` verdict and cd-v1 word, whether the judge was wanted and why (the material findings), what it was (``not_needed``,
``not_asked``, ``asked``), the majority of its three readings, the final verdict and where it came from (``rules`` or ``judge``). The
database refuses a final verdict above the rules' (``council_reduced_only_lowers``), a judge's word without a judge's reading and a row after
the kick-off. Every detail is in ``detail``. Written by code (``FBI_COUNCIL_REDUCED=shadow``); nothing that decides, publishes or serves a
reader reads it.

Append-only (``ai.refuse_change()``). One row per pass, candidate and version (``council_reduced_once``).

Downgrade: drops the table (the rows are lost; every other table stays as it is).

Revision ID: 0161
Revises: 0160
"""

from __future__ import annotations

from alembic import op

revision = "0161"
down_revision = "0160"
branch_labels = None
depends_on = None

VERDICTS = ("CONFIRMA", "RESERVA", "BLOQUEA", "FALTA_INFO", "SIN_COUNCIL")
WORDS = ("APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN")
JUDGE_STATUS = ("not_needed", "not_asked", "asked")
SOURCES = ("rules", "judge")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _rank(column: str) -> str:
    """decision-v1's order of the states an adjustment leads to (``ctx-adj-v1``: BLOQUEA rejects, FALTA_INFO investigates, RESERVA cautions,
    CONFIRMA and SIN_COUNCIL leave the state as it is)."""
    return f"(CASE {column} WHEN 'BLOQUEA' THEN 0 WHEN 'FALTA_INFO' THEN 1 WHEN 'RESERVA' THEN 2 ELSE 3 END)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE ai.council_reduced (
            id              BIGSERIAL     PRIMARY KEY,
            version         TEXT          NOT NULL CHECK (version ~ '^council-reduced-v[0-9]+$'),
            protocol        TEXT          NOT NULL CHECK (protocol ~ '^council-protocol-v[0-9]+$'),
            match_run_id    BIGINT        NOT NULL REFERENCES ai.match_runs(id),
            fixture_id      BIGINT        NOT NULL REFERENCES core.fixtures(id),
            pass_kind       TEXT          NOT NULL CHECK (length(pass_kind) BETWEEN 1 AND 20),
            package_hash    TEXT,
            deliberated_at  TIMESTAMPTZ   NOT NULL,
            kickoff_at      TIMESTAMPTZ   NOT NULL,
            candidate       TEXT          NOT NULL CHECK (candidate ~ '^c[1-9][0-9]{{0,2}}$'),
            family          TEXT          NOT NULL CHECK (length(family) BETWEEN 1 AND 20),
            market_key      TEXT          NOT NULL CHECK (length(market_key) BETWEEN 1 AND 40),
            selection       TEXT          NOT NULL CHECK (length(selection) BETWEEN 1 AND 60),
            line            NUMERIC(6,2)  NOT NULL,
            rules_verdict   TEXT          NOT NULL CHECK (rules_verdict IN ({_in(VERDICTS)})),
            rules_word      TEXT          NOT NULL CHECK (rules_word IN ({_in(WORDS)})),
            judge_wanted    BOOLEAN       NOT NULL,
            judge_status    TEXT          NOT NULL CHECK (judge_status IN ({_in(JUDGE_STATUS)})),
            material        TEXT[]        NOT NULL,
            majority        TEXT          CHECK (majority IS NULL OR majority IN ('APPROVE', 'DOWNGRADE', 'REJECT')),
            final_verdict   TEXT          NOT NULL CHECK (final_verdict IN ({_in(VERDICTS)})),
            source          TEXT          NOT NULL CHECK (source IN ({_in(SOURCES)})),
            detail          JSONB         NOT NULL,
            code_version    TEXT,
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT council_reduced_before_kickoff CHECK (deliberated_at < kickoff_at),
            CONSTRAINT council_reduced_wanted CHECK (judge_wanted = (judge_status <> 'not_needed')),
            CONSTRAINT council_reduced_material CHECK (judge_wanted = false OR cardinality(material) > 0),
            CONSTRAINT council_reduced_judge CHECK (judge_status = 'asked' OR (majority IS NULL AND source = 'rules')),
            CONSTRAINT council_reduced_only_lowers CHECK (
                (source = 'rules' AND final_verdict = rules_verdict)
                OR (source = 'judge' AND majority IS NOT NULL AND {_rank('final_verdict')} < {_rank('rules_verdict')})),
            CONSTRAINT council_reduced_once UNIQUE (version, match_run_id, candidate)
        );
        CREATE INDEX council_reduced_fixture ON ai.council_reduced (fixture_id);
        CREATE INDEX council_reduced_deliberated ON ai.council_reduced (deliberated_at);
        COMMENT ON TABLE ai.council_reduced IS
          'IA-124 (AD-D10): the reduced Council of the shadow (council-reduced-v1 on council-protocol-v1): the rules by default, the '
          'judge only on a material contradiction with value and time, three readings and a majority, and only to lower. Written by '
          'code (FBI_COUNCIL_REDUCED=shadow); append-only; nothing that decides, publishes or serves a reader reads it.';
    """)
    op.execute("CREATE TRIGGER council_reduced_append_only BEFORE UPDATE OR DELETE ON ai.council_reduced "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS ai.council_reduced")
