"""models.match_forecasts says what its stated figure rests on and how much the calibrator weighed each input (plan RP-2.1, findings H01 and H03)

WHY THIS EXISTS
---------------
A stored forecast says whether it was calibrated (``calibration``, ``basis``) and which calibrator did it (``calibrator_id``), but not what that
calibrator is: a champion that corrects the model alone and one that leans on the market's price look the same in the row, and the audit of 10-nov
found the one in use weighs the market 0.50 to 1.30 and the model -0.25 to +0.31. The plan asks that every figure carry a label of its base and the
weights, so that a reader (and the evaluation) can tell «PrediGol's own» from «the market's, relabelled».

WHAT CHANGES (additive; ``lock_timeout`` 10 s; no row is rewritten, no row is deleted, the table stays append-only)
* Five nullable columns: ``figure_label`` (``raw``, ``calibrated_no_market`` or ``calibrated_with_market``), ``cal_method`` (``identity``,
  ``platt`` or ``logit2``) and the weights ``cal_intercept``, ``cal_w_model``, ``cal_w_market`` (the logit-scale coefficients of
  ``fbi.forecasting.figure_base``). A row written before this migration has none of them: it is what it was.
* A row that carries a label must be coherent with what it already says: calibrated exactly when the label is one of the two ``calibrated_*``, a
  method and the three weights exactly when it is calibrated, and ``logit2`` exactly when the label says «with market». The CHECK is added NOT
  VALID (it is enforced for every new row; no existing row is scanned, none of them has a label).

Downgrade drops the check and the columns.

Revision ID: 0181
Revises: 0180
"""

from __future__ import annotations

from alembic import op

revision = "0181"
down_revision = "0180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE models.match_forecasts
            ADD COLUMN figure_label  TEXT,
            ADD COLUMN cal_method    TEXT,
            ADD COLUMN cal_intercept NUMERIC(12,6),
            ADD COLUMN cal_w_model   NUMERIC(12,6),
            ADD COLUMN cal_w_market  NUMERIC(12,6)""")
    op.execute("""
        ALTER TABLE models.match_forecasts
            ADD CONSTRAINT match_forecasts_figure_label_values
                CHECK (figure_label IS NULL OR figure_label IN ('raw', 'calibrated_no_market', 'calibrated_with_market')) NOT VALID,
            ADD CONSTRAINT match_forecasts_cal_method_values
                CHECK (cal_method IS NULL OR cal_method IN ('identity', 'platt', 'logit2')) NOT VALID,
            ADD CONSTRAINT match_forecasts_label_is_coherent
                CHECK (figure_label IS NULL OR (
                       (figure_label = 'raw') = (calibration = 'UNCALIBRATED')
                   AND (figure_label = 'raw') = (cal_method IS NULL)
                   AND (cal_method IS NULL) = (cal_intercept IS NULL)
                   AND (cal_method IS NULL) = (cal_w_model IS NULL)
                   AND (cal_method IS NULL) = (cal_w_market IS NULL)
                   AND (figure_label = 'calibrated_with_market') = (cal_method = 'logit2'))) NOT VALID""")
    op.execute("""
        COMMENT ON COLUMN models.match_forecasts.figure_label IS
        'What the stated figure p rests on: raw (the model''s own number), calibrated_no_market (identity or Platt champion) or
         calibrated_with_market (a logit2 champion, which reads the market''s price). The market''s own number is p_market_used. NULL on
         rows written before RP-2.1.'""")
    op.execute("""
        COMMENT ON COLUMN models.match_forecasts.cal_intercept IS
        'The champion''s weights on the logit scale: logit(p) = cal_intercept + cal_w_model * logit(p_model) + cal_w_market * logit(p_market).
         identity is (0, 1, 0), platt (a, b, 0), logit2 (a, b, c). NULL without a champion.'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE models.match_forecasts
            DROP CONSTRAINT IF EXISTS match_forecasts_label_is_coherent,
            DROP CONSTRAINT IF EXISTS match_forecasts_cal_method_values,
            DROP CONSTRAINT IF EXISTS match_forecasts_figure_label_values,
            DROP COLUMN IF EXISTS cal_w_market,
            DROP COLUMN IF EXISTS cal_w_model,
            DROP COLUMN IF EXISTS cal_intercept,
            DROP COLUMN IF EXISTS cal_method,
            DROP COLUMN IF EXISTS figure_label""")
