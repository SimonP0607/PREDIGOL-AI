"""The calibrators of the counts and the owner's signature (IA-095, plan piece AD-B07): two append-only tables, and nothing else

WHY THIS EXISTS
---------------
``count-cal-v1`` (``fbi.countcal.calibrator``) calibrates the ladder of lines of the corners and the cards of ``family-v1``: one
logistic map of the probability of «over L» per family (corners total, corners per team, cards total, cards per team). Its verdict
comes from the preregistered protocol ``AD-B07`` (VALIDADO, NO VALIDADO, INSUFICIENTE). It does NOT go to ``intel.calibrators``:
that table holds binary calibrators of one selection (``p_model`` and ``p_market`` -> ``apply_params``), and the readers of that
table - the prospective evaluation, the automatic promotion candidates, the drift watch - would read a count calibrator as one of
theirs. A count calibrator has its own table, and its role its own record: nothing is promoted except by the owner's signature.

WHAT CHANGES
------------
- ``intel.count_calibrators``: one row per fit of a family's calibrator - its parameters, the moment it knew (``known_at``), the
  window and sample it was fitted on, the verdict of the protocol and the protocol's stamp (key, version, fingerprint), the LAB
  summary. Append-only (``ai.refuse_change()``).
- ``intel.count_calibrator_signatures``: the owner's word on one calibrator - CHAMPION (it may calibrate the family's numbers in the
  private evaluation) or RETIRED - with who signed and the signature text. Append-only. The database refuses a CHAMPION for a
  calibrator whose verdict is not VALIDADO (``intel.count_signature_needs_validated()``).

Nothing reads them to decide, publish or price; no reader of the product reads them. No data is written by the migration.

Downgrade: drops the two tables and the function.

Revision ID: 0152
Revises: 0149 (provisional: the highest revision in this tree; it goes on top of the highest when the branches are merged)
"""

from alembic import op

revision = "0152"
down_revision = "0151"
branch_labels = None
depends_on = None

FAMILIES = ("corners_total", "corners_side", "cards_total", "cards_side")
VERDICTS = ("VALIDADO", "NO VALIDADO", "INSUFICIENTE")
ROLES = ("CHAMPION", "RETIRED")


def _words(words: tuple[str, ...]) -> str:
    return ", ".join("'" + w.replace("'", "''") + "'" for w in words)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.count_calibrators (
            id            BIGSERIAL    PRIMARY KEY,
            family        TEXT         NOT NULL CHECK (family IN ({_words(FAMILIES)})),
            measure       TEXT         NOT NULL CHECK (measure IN ('corners_ft', 'cards_lines_ft')),
            version       TEXT         NOT NULL CHECK (version ~ '^count-cal-v[0-9]+$'),
            method        TEXT         NOT NULL CHECK (method = 'survival-logit'),
            params        JSONB        NOT NULL CHECK (jsonb_typeof(params) = 'object'),
            known_at      TIMESTAMPTZ  NOT NULL,
            fitted_at     TIMESTAMPTZ  NOT NULL,
            train_from    DATE,
            train_to      DATE,
            n_matches     INTEGER      NOT NULL CHECK (n_matches >= 0),
            verdict       TEXT         NOT NULL CHECK (verdict IN ({_words(VERDICTS)})),
            protocol      JSONB        NOT NULL CHECK (protocol ? 'fingerprint'),
            report        JSONB        NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(report) = 'object'),
            code_version  TEXT,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CHECK (fitted_at >= known_at),
            CHECK (train_to IS NULL OR train_from <= train_to)
        );
        CREATE INDEX intel_count_calibrators_family ON intel.count_calibrators (family, known_at DESC);
        COMMENT ON TABLE intel.count_calibrators IS
          'IA-095: count-cal-v1, the calibrator of the ladder of lines of one family of counts (corners or cards, total or per team) of '
          'family-v1, fitted walk-forward on out-of-sample predictions known before known_at; verdict and protocol from the '
          'preregistered protocol AD-B07. Append-only. Its role is the newest row of intel.count_calibrator_signatures.';

        CREATE TABLE intel.count_calibrator_signatures (
            id             BIGSERIAL    PRIMARY KEY,
            calibrator_id  BIGINT       NOT NULL REFERENCES intel.count_calibrators(id),
            role           TEXT         NOT NULL CHECK (role IN ({_words(ROLES)})),
            signed_by      TEXT         NOT NULL CHECK (length(signed_by) BETWEEN 2 AND 80),
            signature      TEXT         NOT NULL CHECK (length(signature) BETWEEN 10 AND 600),
            at             TIMESTAMPTZ  NOT NULL,
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        CREATE INDEX intel_count_calibrator_signatures_cal ON intel.count_calibrator_signatures (calibrator_id, at DESC);
        COMMENT ON TABLE intel.count_calibrator_signatures IS
          'IA-095: the owner''s signature on a count calibrator: CHAMPION (it may calibrate its family in the private evaluation, '
          'AD-E03) or RETIRED. Append-only; a CHAMPION needs a VALIDADO verdict (count_signature_needs_validated).';

        CREATE FUNCTION intel.count_signature_needs_validated() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF NEW.role = 'CHAMPION' AND NOT EXISTS (
                SELECT 1 FROM intel.count_calibrators c WHERE c.id = NEW.calibrator_id AND c.verdict = 'VALIDADO') THEN
                RAISE EXCEPTION 'a count calibrator becomes CHAMPION only with the verdict VALIDADO of its protocol';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("CREATE TRIGGER count_calibrators_append_only BEFORE UPDATE OR DELETE ON intel.count_calibrators "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")
    op.execute("CREATE TRIGGER count_calibrator_signatures_append_only BEFORE UPDATE OR DELETE ON intel.count_calibrator_signatures "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")
    op.execute("CREATE TRIGGER count_calibrator_signatures_validated BEFORE INSERT ON intel.count_calibrator_signatures "
               "FOR EACH ROW EXECUTE FUNCTION intel.count_signature_needs_validated()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS intel.count_calibrator_signatures")
    op.execute("DROP TABLE IF EXISTS intel.count_calibrators")
    op.execute("DROP FUNCTION IF EXISTS intel.count_signature_needs_validated()")
