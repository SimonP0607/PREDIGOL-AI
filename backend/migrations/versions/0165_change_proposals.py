"""Controlled learning (IA-139, plan piece AD-K07): the system PROPOSES, the owner SIGNS - ``ai.change_proposals``, ``ai.change_signatures``,
``ai.change_applications``, append-only

WHY THIS EXISTS
---------------
The approved principle: nothing is trained, promoted or re-thresholded by itself. Until now that held because nothing proposed anything in a
form that could be signed: the learning console is read-only, the board of AD-K02 says VALIDADO / NO_VALIDADO and stops there. AD-K07 asks for
typed proposals with their evidence, a register of signatures, and every promotion as a new version with its way back.

WHAT CHANGES
------------
* ``ai.change_proposals``: one row per proposal - its kind (``umbral``, ``peso_fuente``, ``promocion_capacidad``, ``retirada``), what it
  changes (``target``, whose prefix must fit the kind), the version in force and the one proposed (never equal; ``rollback_to`` IS the
  version in force, kept), the change, its evidence (figures and references, never third parties' text) and the sha256 of that evidence,
  who proposed it (``system`` or ``owner``) and why. A change that names a probability is refused by the database: no proposal lets a model
  move a probability.
* ``ai.change_signatures``: the owner's decision on a proposal - ``firmada`` or ``rechazada`` - in their own words, ONE per proposal, bound to
  the evidence hash the owner saw (a composite foreign key: a signature of other evidence does not exist).
* ``ai.change_applications``: that a signed proposal took effect (``aplicada``) or was taken back to ``rollback_to`` (``revertida``), recorded
  by the owner. The database refuses a row without a ``firmada`` signature of the same proposal: "0 changes applied without a signature" is
  a constraint, not a promise.

Nothing applies anything: no job, route or agent reads these tables to change a switch, a threshold, a weight or a model. A change still
takes effect only when the owner changes the version or the switch; the row records it.

Append-only (``ai.refuse_change()``). Downgrade: drops the three tables (the proposals and signatures are lost; nothing else changes).

Revision ID: 0165
Revises: 0163
"""

from __future__ import annotations

from alembic import op

revision = "0165"
down_revision = "0163"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
KINDS = ("umbral", "peso_fuente", "promocion_capacidad", "retirada")
PROBABILITY_KEYS = ("p", "probability", "probabilities", "p_model", "p_judged", "p_market", "prob")
TABLES = ("change_proposals", "change_signatures", "change_applications")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE ai.change_proposals (
            id               BIGSERIAL    PRIMARY KEY,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            version          TEXT         NOT NULL CHECK (version ~ '^proposals-v[0-9]+$'),
            kind             TEXT         NOT NULL CHECK (kind IN ({_in(KINDS)})),
            target           TEXT         NOT NULL CHECK (target ~ '^(threshold|source|capability|validation|writer|store):[A-Za-z0-9_.:/*-]{{1,160}}$'),
            current_version  TEXT         NOT NULL CHECK (length(current_version) BETWEEN 1 AND 80),
            proposed_version TEXT         NOT NULL CHECK (length(proposed_version) BETWEEN 1 AND 80),
            rollback_to      TEXT         NOT NULL,
            change           JSONB        NOT NULL CHECK (jsonb_typeof(change) = 'object'),
            evidence         JSONB        NOT NULL CHECK (jsonb_typeof(evidence) = 'object' AND evidence <> '{{}}'::jsonb),
            evidence_refs    JSONB        NOT NULL CHECK (jsonb_typeof(evidence_refs) = 'array' AND jsonb_array_length(evidence_refs) >= 1),
            evidence_hash    TEXT         NOT NULL CHECK (evidence_hash ~ '{SHA256}'),
            proposed_by      TEXT         NOT NULL CHECK (proposed_by IN ('system', 'owner')),
            reason           TEXT         NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 600),
            code_version     TEXT,
            CONSTRAINT change_proposals_new_version CHECK (proposed_version <> current_version),
            CONSTRAINT change_proposals_way_back CHECK (rollback_to = current_version),
            CONSTRAINT change_proposals_kind_target CHECK (
                (kind = 'umbral' AND target ~ '^threshold:')
                OR (kind = 'peso_fuente' AND target ~ '^source:')
                OR (kind = 'promocion_capacidad' AND (target ~ '^capability:' OR target ~ '^validation:'))
                OR (kind = 'retirada' AND (target ~ '^writer:' OR target ~ '^store:'))),
            CONSTRAINT change_proposals_no_probability CHECK (NOT (change ?| ARRAY[{_in(PROBABILITY_KEYS)}])),
            CONSTRAINT change_proposals_once UNIQUE (kind, target, proposed_version, evidence_hash),
            CONSTRAINT change_proposals_id_evidence UNIQUE (id, evidence_hash)
        );
        CREATE INDEX change_proposals_target ON ai.change_proposals (kind, target, id);
        COMMENT ON TABLE ai.change_proposals IS
          'IA-139 (AD-K07): what the system or the owner proposes to change, with its evidence; append-only. A proposal changes nothing: '
          'it waits for the owner''s signature (ai.change_signatures) and its effect is a new version the owner turns on.';

        CREATE TABLE ai.change_signatures (
            id             BIGSERIAL    PRIMARY KEY,
            proposal_id    BIGINT       NOT NULL,
            evidence_hash  TEXT         NOT NULL,
            decision       TEXT         NOT NULL CHECK (decision IN ('firmada', 'rechazada')),
            signed_by      TEXT         NOT NULL CHECK (signed_by = 'owner'),
            signature      TEXT         NOT NULL CHECK (length(btrim(signature)) BETWEEN 10 AND 600),
            signed_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT change_signatures_of_what_was_seen FOREIGN KEY (proposal_id, evidence_hash)
                REFERENCES ai.change_proposals (id, evidence_hash),
            CONSTRAINT change_signatures_once UNIQUE (proposal_id),
            CONSTRAINT change_signatures_key UNIQUE (id, proposal_id, decision)
        );
        COMMENT ON TABLE ai.change_signatures IS
          'IA-139 (AD-K07): the owner''s decision on a proposal (firmada / rechazada), in their own words, bound to the evidence hash '
          'they saw; one per proposal; append-only. A change of mind is a new proposal.';

        CREATE TABLE ai.change_applications (
            id             BIGSERIAL    PRIMARY KEY,
            proposal_id    BIGINT       NOT NULL,
            signature_id   BIGINT       NOT NULL,
            decision       TEXT         NOT NULL DEFAULT 'firmada' CHECK (decision = 'firmada'),
            kind           TEXT         NOT NULL CHECK (kind IN ('aplicada', 'revertida')),
            version        TEXT         NOT NULL CHECK (length(version) BETWEEN 1 AND 80),
            recorded_by    TEXT         NOT NULL CHECK (recorded_by = 'owner'),
            note           TEXT         NOT NULL CHECK (length(btrim(note)) BETWEEN 10 AND 600),
            recorded_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT change_applications_signed FOREIGN KEY (signature_id, proposal_id, decision)
                REFERENCES ai.change_signatures (id, proposal_id, decision),
            CONSTRAINT change_applications_once UNIQUE (proposal_id, kind)
        );
        COMMENT ON TABLE ai.change_applications IS
          'IA-139 (AD-K07): that a SIGNED proposal took effect or was taken back to its rollback_to version, recorded by the owner; '
          'the foreign key refuses a row without a signature firmada of the same proposal; append-only.';
    """)
    for t in TABLES:
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON ai.{t} FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS ai.{t}")
