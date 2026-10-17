"""truth findings: the 'provider_contradiction' kind the audit already produces

The truth audit (``scripts.truth_audit``) stopped completing on 4 Oct 2026: its result comparison reports a
provider whose score blocks contradict each other (Pafos v Hajduk Split, AET: final 2-0, full time 4-0, extra
time 0-2) as ``provider_contradiction`` (``fbi.truth.findings.Kind``), and the table's CHECK, written in 0048,
refused the whole batch - so the Data Truth page kept showing the last audit that had completed, 21 hours old.
A test now checks that the CHECK accepts every Kind.

Revision ID: 0063
Revises: 0062
"""

from __future__ import annotations

from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None

KINDS = ("mismatch", "missing_in_db", "missing_in_api", "not_stored", "stale", "provider_lag", "inconsistent",
         "provider_contradiction")


def upgrade() -> None:
    kinds = ", ".join(f"'{k}'" for k in KINDS)
    op.execute("ALTER TABLE audit.truth_findings DROP CONSTRAINT IF EXISTS truth_findings_kind_check")
    op.execute(f"ALTER TABLE audit.truth_findings ADD CONSTRAINT truth_findings_kind_check CHECK (kind IN ({kinds}))")


def downgrade() -> None:
    kinds = ", ".join(f"'{k}'" for k in KINDS if k != "provider_contradiction")
    op.execute("UPDATE audit.truth_findings SET kind = 'inconsistent' WHERE kind = 'provider_contradiction'")
    op.execute("ALTER TABLE audit.truth_findings DROP CONSTRAINT IF EXISTS truth_findings_kind_check")
    op.execute(f"ALTER TABLE audit.truth_findings ADD CONSTRAINT truth_findings_kind_check CHECK (kind IN ({kinds}))")
