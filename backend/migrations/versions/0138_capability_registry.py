"""The registry of capabilities (IA-056, plan piece AD-003): a catalog and the chain of each capability's states, append-only

WHY THIS EXISTS
---------------
The plan of the definitive architecture (16 Nov 2026) moves every capability through four states - ``construida`` (built, off),
``en_sombra`` (running in shadow, nothing reaches a reader), ``lista_para_revision`` (its safety passed and its validation has a measured
verdict: the owner may look at it) and ``autorizada`` (the owner signed it) - each with a SAFETY verdict and a VALIDATION verdict with its
sample. Nothing kept that: ``intel.promotions`` signs calibrators, edges, rules and models only (its CHECK admits no capability, revision
0076), and the agents' registry is code. So the registry has tables of its own.

WHAT CHANGES
------------
- ``intel.capabilities``: the catalog, one row per VERSION of a capability's entry (key, plan piece, title, description, the switch that
  governs it, its components). A new version names the one it replaces (``supersedes``) and an entry can be replaced once: versions are a
  chain, never a rewrite.
- ``intel.capability_transitions``: every move of a capability (and every new verdict in the same state), each naming the row before it
  (``previous_id``). The database itself refuses what the rules forbid: skipping a state forward; ``autorizada`` without the owner's
  signature or with a safety that is not ``PASA``; any state above ``construida`` with a safety ``NO PASA``; ``lista_para_revision``
  without a safety ``PASA``; a measured validation without its sample; a system row with a signature or an owner row without one; two
  successors of one row or two first rows of one capability; a row whose ``from_state`` is not the state of the row it names.
- The catalog is seeded with the seven capabilities of the plan that ALREADY run in shadow, each with ONE first transition to
  ``en_sombra`` decided by the system and the observation that shows it (production, read-only, 16 Nov 2026 20:45 UTC, the last seven
  days). Their verdicts are not invented: safety is ``PENDIENTE POR ACCIONES MANUALES`` (the registry has not judged it; the console shows
  the newest rows of the gates beside it) and validation ``PENDIENTE POR DEPENDENCIAS`` (the board of validation by market, AD-K02, does
  not exist yet). What readers already see (the forecast, the knowledge of a finished match) and ``review-v2`` (``FBI_AI_MODE``, until
  AD-002) are NOT seeded: their state would need the owner's word, which nobody has recorded here.

Both tables are append-only (``intel.refuse_change()``, revision 0076). The only foreign keys are between these two tables. Nothing that
exists changes: no switch, no gate, no agent, no pick, no reader reads them (the Admin Console's ``GET /admin/intelligence/capabilities``).

Downgrade: drops both tables (their rows go with them: export them first if the owner has signed any).

Revision ID: 0138
Revises: 0137
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from alembic import op

revision = "0138"
down_revision = "0137"
branch_labels = None
depends_on = None

TABLES = ("capability_transitions", "capabilities")
STATES = ("construida", "en_sombra", "lista_para_revision", "autorizada")
SAFETY = ("PASA", "NO PASA", "PENDIENTE POR ACCIONES MANUALES", "PENDIENTE POR DEPENDENCIAS")
VALIDATION = ("VALIDADO", "NO VALIDADO", "INSUFICIENTE", "PENDIENTE POR ACCIONES MANUALES", "PENDIENTE POR DEPENDENCIAS")
MEASURED = ("VALIDADO", "NO VALIDADO", "INSUFICIENTE")
KEY = "^[a-z][a-z0-9_]{1,47}$"
PIECE = "^AD-([0-9]{3}|[A-Z][0-9]{2})$"
SWITCH = "^FBI_[A-Z0-9_]{2,60}$"
SHA256 = "^[0-9a-f]{64}$"

OBSERVED_AT = "2026-11-16T20:45:00Z"
SEED_REASON = ("Registro de partida (IA-056): ya corre en sombra en producción (observado el 16-nov-2026, solo lectura, últimos 7 días); "
               "el registro aún no ha juzgado su seguridad ni su validación.")
SEED_SAFETY = "PENDIENTE POR ACCIONES MANUALES"
SEED_VALIDATION = "PENDIENTE POR DEPENDENCIAS"

SEED: tuple[dict[str, Any], ...] = (
    {"key": "research_v2", "piece": "AD-C05", "title": "Research v2: investigación por entidad y tema",
     "description": "Busca y extrae afirmaciones tipadas por entidad y tema (extract-v3, claim-v1) detrás de la puerta untrusted-v3, "
                    "al lado de la investigación v1; lo que escribe no mueve ningún estado, paquete ni pick de v1.",
     "switch": "FBI_AI_RESEARCH_V2", "components": ["extract-v3", "claim-v1"],
     "observed": {"switch_word": "shadow", "switch_word_source": "ai.feature_gates fila 13 (switches)", "table": "ai.evidence",
                  "rows": 854, "fixtures": 182, "filter": "subject_type IS NOT NULL"}},
    {"key": "readers", "piece": "AD-D09", "title": "Lectores especialistas: Partido y Estadísticas",
     "description": "Los agentes de Partido y de Estadísticas leen el paquete del partido y alimentan al Council solo dentro de la sombra.",
     "switch": "FBI_AI_AGENTS", "components": ["match-v5", "stats-v4"],
     "observed": {"switch_word": "match,council,stats", "switch_word_source": "ai.feature_gates fila 13 (switches)", "table": "ai.agent_runs",
                  "rows": {"match-v5": 142, "match-v4": 10, "stats-v4": 26, "stats-v3": 3}}},
    {"key": "council", "piece": "AD-D10", "title": "Council: juez council-v1 sobre council-protocol-v1",
     "description": "El juez del Council y su protocolo por reglas deciden la revisión del motor de sombra ma-v1 (FBI_AI_ENGINES); "
                    "nunca suben un estado ni tocan números.",
     "switch": "FBI_AI_AGENTS", "components": ["council-v1", "council-protocol-v1", "ma-v1"],
     "observed": {"switch_word": "match,council,stats", "switch_word_source": "ai.feature_gates fila 13 (switches)",
                  "table": "ai.agent_runs + ai.pick_reviews", "rows": {"council-v1": 178, "ma-v1 (mode shadow)": 375}}},
    {"key": "haiku_arm", "piece": "AD-D10", "title": "Brazo Haiku del Council (ma-v1-h)",
     "description": "El mismo camino del Council con el modelo pequeño, como brazo de comparación; se retira cuando cumpla su criterio.",
     "switch": "FBI_AI_ENGINES", "components": ["ma-v1-h"],
     "observed": {"switch_word": "rules,llm,ma-v1,ma-v1-h", "switch_word_source": "ai.feature_gates fila 13 (switches)",
                  "table": "ai.pick_reviews", "rows": {"ma-v1-h (mode shadow)": 375}}},
    {"key": "family_decisions", "piece": "AD-B07", "title": "Familias de conteos: córners, tarjetas y goles por mitad",
     "description": "Las familias deciden en sombra con versiones propias (decision-fam-v1) que ningún pick, filtro ni lector usa.",
     "switch": "FBI_FAMILY_DECISIONS", "components": ["decision-fam-v1"],
     "observed": {"switch_word": "shadow (la única palabra que las enciende)", "table": "intel.decisions",
                  "rows": 11125, "filter": "decision_version = 'decision-fam-v1'"}},
    {"key": "attribution", "piece": "AD-K03", "title": "Atribución de la sombra (attr-v1)",
     "description": "Clasifica por código qué agente y versión acertó o falló en los partidos terminados; no cambia nada de lo que decide.",
     "switch": "FBI_AI_PM_REVIEWER", "components": ["attr-v1"],
     "observed": {"switch_word": "on", "switch_word_source": "ai.feature_gates fila 13 (switches: pm_reviewer)",
                  "table": "intel.agent_attributions", "rows": 1423}},
    {"key": "chronicle_review", "piece": "AD-F06", "title": "Revisión posterior de la crónica (chronicle-review-v1)",
     "description": "Contrasta la crónica de cada partido terminado con lo que pasó; solo base de datos, sin modelo ni coste; nadie la lee "
                    "para decidir.",
     "switch": None, "components": ["chronicle-review-v1"],
     "observed": {"switch_word": None, "note": "sin interruptor: trabajo horario del worker", "table": "ai.chronicle_reviews",
                  "rows_total": 290, "newest": "2026-11-16T20:03Z"}},
)
"""The capabilities of the plan already running in shadow on 16 Nov 2026. ``fbi.intel.capabilities.CATALOG`` carries the same entries
(``tests/unit/test_capabilities.py`` holds the two equal)."""


def evidence_hash(document: dict[str, Any]) -> str:
    """sha256 of the canonical JSON (sorted keys, no spaces) - the same function as ``fbi.intel.capabilities.evidence_hash``."""
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def seed_document(entry: dict[str, Any]) -> dict[str, Any]:
    """What the first transition of a seeded capability records (and hashes)."""
    return {"safety": SEED_SAFETY, "safety_evidence": {"kind": "capability-seed-v1", "note": "sin juzgar por el registro"},
            "validation": SEED_VALIDATION,
            "validation_evidence": {"kind": "capability-seed-v1", "note": "el tablero de validación por mercado (AD-K02) no existe aún"},
            "validation_sample": None, "reason": SEED_REASON,
            "observed": {"at": OBSERVED_AT, "window_days": 7, **entry["observed"]}}


def _q(text: str | None) -> str:
    return "NULL" if text is None else "'" + text.replace("'", "''") + "'"


def _json(document: Any) -> str:
    return _q(json.dumps(document, sort_keys=True, ensure_ascii=False)) + "::jsonb"


def _words(words: tuple[str, ...]) -> str:
    return ", ".join(_q(w) for w in words)


def _rank(column: str) -> str:
    return f"(CASE {column} " + " ".join(f"WHEN {_q(s)} THEN {i}" for i, s in enumerate(STATES)) + " END)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.capabilities (
            id             BIGSERIAL    PRIMARY KEY,
            key            TEXT         NOT NULL CHECK (key ~ '{KEY}'),
            version        SMALLINT     NOT NULL CHECK (version BETWEEN 1 AND 999),
            supersedes     BIGINT,
            piece          TEXT         NOT NULL CHECK (piece ~ '{PIECE}'),
            title          TEXT         NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
            description    TEXT         NOT NULL CHECK (length(description) BETWEEN 1 AND 1000),
            switch         TEXT         CHECK (switch IS NULL OR switch ~ '{SWITCH}'),
            components     TEXT[]       NOT NULL DEFAULT '{{}}',
            registered_at  TIMESTAMPTZ  NOT NULL,
            registered_by  TEXT         NOT NULL CHECK (registered_by IN ('system', 'owner')),
            code_version   TEXT         CHECK (code_version IS NULL OR length(code_version) BETWEEN 1 AND 64),
            CONSTRAINT capabilities_version_once UNIQUE (key, version),
            CONSTRAINT capabilities_id_key UNIQUE (id, key),
            CONSTRAINT capabilities_chain CHECK ((version = 1) = (supersedes IS NULL)),
            CONSTRAINT capabilities_supersedes_fk FOREIGN KEY (supersedes, key) REFERENCES intel.capabilities (id, key)
        );
        CREATE UNIQUE INDEX intel_capabilities_one_successor ON intel.capabilities (key, COALESCE(supersedes, 0));
        COMMENT ON TABLE intel.capabilities IS
          'The catalog of the registry of capabilities (IA-056, AD-003): one row per version of a capability''s entry - its plan piece, '
          'what it does and the switch that governs it. A new version names the one it replaces (supersedes), once. Append-only.';
        COMMENT ON COLUMN intel.capabilities.switch IS 'The environment switch that governs it (NULL: a job of the worker without one).';

        CREATE TABLE intel.capability_transitions (
            id                   BIGSERIAL    PRIMARY KEY,
            capability_key       TEXT         NOT NULL,
            capability_id        BIGINT       NOT NULL,
            previous_id          BIGINT,
            at                   TIMESTAMPTZ  NOT NULL,
            from_state           TEXT         CHECK (from_state IS NULL OR from_state IN ({_words(STATES)})),
            to_state             TEXT         NOT NULL CHECK (to_state IN ({_words(STATES)})),
            safety               TEXT         NOT NULL CHECK (safety IN ({_words(SAFETY)})),
            safety_evidence      JSONB        NOT NULL CHECK (jsonb_typeof(safety_evidence) = 'object'),
            validation           TEXT         NOT NULL CHECK (validation IN ({_words(VALIDATION)})),
            validation_evidence  JSONB        NOT NULL CHECK (jsonb_typeof(validation_evidence) = 'object'),
            validation_sample    INTEGER      CHECK (validation_sample IS NULL OR validation_sample >= 0),
            observed             JSONB        NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(observed) = 'object'),
            reason               TEXT         NOT NULL CHECK (length(reason) BETWEEN 1 AND 600),
            decided_by           TEXT         NOT NULL CHECK (decided_by IN ('system', 'owner')),
            owner_signature      TEXT         CHECK (owner_signature IS NULL OR length(owner_signature) BETWEEN 10 AND 600),
            code_version         TEXT         CHECK (code_version IS NULL OR length(code_version) BETWEEN 1 AND 64),
            evidence_hash        TEXT         NOT NULL CHECK (evidence_hash ~ '{SHA256}'),
            CONSTRAINT capability_transitions_tip UNIQUE (id, capability_key, to_state),
            CONSTRAINT capability_transitions_catalog_fk FOREIGN KEY (capability_id, capability_key)
                REFERENCES intel.capabilities (id, key),
            CONSTRAINT capability_transitions_previous_fk FOREIGN KEY (previous_id, capability_key, from_state)
                REFERENCES intel.capability_transitions (id, capability_key, to_state),
            CONSTRAINT capability_transitions_genesis CHECK ((previous_id IS NULL) = (from_state IS NULL)),
            CONSTRAINT capability_transitions_first_state CHECK (previous_id IS NOT NULL OR to_state IN ('construida', 'en_sombra')),
            CONSTRAINT capability_transitions_no_skip CHECK (from_state IS NULL OR {_rank('to_state')} <= {_rank('from_state')} + 1),
            CONSTRAINT capability_transitions_signature CHECK ((decided_by = 'owner') = (owner_signature IS NOT NULL)),
            CONSTRAINT capability_transitions_authorised CHECK (to_state <> 'autorizada' OR (decided_by = 'owner' AND safety = 'PASA')),
            CONSTRAINT capability_transitions_review CHECK (to_state NOT IN ('lista_para_revision', 'autorizada') OR safety = 'PASA'),
            CONSTRAINT capability_transitions_safety_holds CHECK (to_state = 'construida' OR safety <> 'NO PASA'),
            CONSTRAINT capability_transitions_sample CHECK (validation NOT IN ({_words(MEASURED)}) OR validation_sample IS NOT NULL),
            CONSTRAINT capability_transitions_safety_evidence CHECK (safety NOT IN ('PASA', 'NO PASA') OR safety_evidence <> '{{}}'::jsonb),
            CONSTRAINT capability_transitions_validation_evidence CHECK (
                validation NOT IN ({_words(MEASURED)}) OR validation_evidence <> '{{}}'::jsonb)
        );
        CREATE UNIQUE INDEX intel_capability_transitions_one_successor
            ON intel.capability_transitions (capability_key, COALESCE(previous_id, 0));
        CREATE INDEX intel_capability_transitions_newest ON intel.capability_transitions (capability_key, id DESC);
        COMMENT ON TABLE intel.capability_transitions IS
          'The chain of states of each capability (IA-056, AD-003): construida -> en_sombra -> lista_para_revision -> autorizada, each row '
          'with its safety and validation verdicts, evidence and sample. One first row and one successor per row; never a skipped state; '
          'autorizada only with the owner''s signature. The registry records: it switches nothing. Append-only.';
        COMMENT ON COLUMN intel.capability_transitions.observed IS
          'What was seen when the row was written (rows of production, the switch''s word), beside the verdicts.';
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON intel.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")
    for entry in SEED:
        components = "ARRAY[" + ", ".join(_q(c) for c in entry["components"]) + "]::text[]"
        op.execute(f"""
            INSERT INTO intel.capabilities (key, version, piece, title, description, switch, components, registered_at, registered_by)
            VALUES ({_q(entry["key"])}, 1, {_q(entry["piece"])}, {_q(entry["title"])}, {_q(entry["description"])},
                    {_q(entry["switch"])}, {components}, now(), 'system')""")
        doc = seed_document(entry)
        op.execute(f"""
            INSERT INTO intel.capability_transitions (capability_key, capability_id, previous_id, at, from_state, to_state, safety,
                safety_evidence, validation, validation_evidence, validation_sample, observed, reason, decided_by, evidence_hash)
            SELECT key, id, NULL, now(), NULL, 'en_sombra', {_q(doc["safety"])}, {_json(doc["safety_evidence"])},
                   {_q(doc["validation"])}, {_json(doc["validation_evidence"])}, NULL, {_json(doc["observed"])}, {_q(doc["reason"])},
                   'system', {_q(evidence_hash(doc))}
              FROM intel.capabilities WHERE key = {_q(entry["key"])} AND version = 1""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in TABLES:
        op.execute(f"DROP TABLE intel.{table}")
