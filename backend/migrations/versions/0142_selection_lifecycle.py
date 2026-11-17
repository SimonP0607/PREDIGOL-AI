"""The one cycle of states of a selection (IA-068, plan piece AD-D02): ``intel.selection_lifecycle``, append-only

WHY THIS EXISTS
---------------
Five layers say today where a selection stands, each in its own words: decision-v1 and decision-fam-v1 (``intel.decisions``),
the combined review (``ai.pick_reviews``), ``state-v2``, ``user-status-v2`` and the stages of the day's set. None of them says
«waiting for the line-ups», «withdrawn» or «in play» for a selection on its own. The plan of the definitive architecture (16 Nov
2026) gives every selection ONE chain of ten states - detectado, en_investigacion, en_evaluacion, pendiente_alineaciones,
confirmada_sombra, retirada, descartada, en_juego, liquidada, evaluada (the codes UX's closed list fixed, IA-057).

WHAT CHANGES
------------
- ``intel.selection_lifecycle``: one row per move of a selection's chain - the selection (fixture, market, selection, line), the
  layer whose decisions drive it, the state before and after, a reason from the closed list of the new state, the actor, the
  evaluation (E1-E4) and its version when there is one, the moment it was known and the row of the layer it was read from. Each row
  names the row before it (``previous_id``) and a row has one successor: a chain, never a rewrite. The database itself refuses what
  the machine (``fbi.lifecycle.machine``) forbids: a chain that does not start at ``detectado``; a move that is not one of the
  cycle's (``descartada`` and ``evaluada`` have no way out); a reason that is not one of its state's; a model that takes a selection
  anywhere but down (``retirada``, ``descartada``); an owner's row that is not the authorisation of a confirmed selection with its
  signature, or an authorisation without the owner; a settled row without its result; a row known before the row it follows; a
  ``chain_key`` that does not match its columns.
- Append-only (``intel.refuse_change()``, revision 0076). Its only foreign keys are to itself and to ``core.fixtures``.

Nothing that exists changes: no layer, switch, gate, agent, pick or reader. It starts empty; the shadow writer
(``fbi.lifecycle.store``, worker job ``lifecycle_shadow``) fills it only while ``FBI_LIFECYCLE=shadow`` (``off`` by default).

Downgrade: drops the table and its function (its rows go with it).

Revision ID: 0142
Revises: 0137
"""

from __future__ import annotations

from alembic import op

revision = "0142"
down_revision = "0141"
branch_labels = None
depends_on = None

STATES = ("detectado", "en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "retirada",
          "descartada", "en_juego", "liquidada", "evaluada")
BLOCKERS = ("datos_insuficientes", "sin_modelo", "sin_precio", "mercado_estrecho", "precio_atipico", "contexto_lo_impide",
            "baja_clave_confirmada", "valor_insuficiente", "sin_calibrar", "precio_antiguo", "revision_en_contra",
            "baja_por_confirmar", "riesgo", "otra_del_partido", "sin_motivo_conocido")
REASONS: dict[str, tuple[str, ...]] = {
    "detectado": ("candidato_nuevo",),
    "en_investigacion": ("contexto_pendiente", "hecho_nuevo"),
    "en_evaluacion": ("en_curso", *BLOCKERS),
    "pendiente_alineaciones": ("baja_por_confirmar", "depende_de_alineacion"),
    "confirmada_sombra": ("cumple_todo", "cumple_salvo_validacion", "autorizada_por_dueno"),
    "retirada": (*BLOCKERS, "contexto_pendiente", "alineacion_en_contra", "hecho_en_contra", "partido_no_jugado"),
    "descartada": (*BLOCKERS, "contexto_pendiente", "retirada_al_saque", "sin_alineacion_a_tiempo", "partido_no_jugado",
                   "sin_decision"),
    "en_juego": ("saque",),
    "liquidada": ("resultado",),
    "evaluada": ("evaluacion_posterior",),
}
MOVES: dict[str, tuple[str, ...]] = {
    "detectado": ("en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "descartada"),
    "en_investigacion": ("en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "descartada"),
    "en_evaluacion": ("en_evaluacion", "en_investigacion", "pendiente_alineaciones", "confirmada_sombra", "descartada"),
    "pendiente_alineaciones": ("pendiente_alineaciones", "confirmada_sombra", "retirada", "descartada"),
    "confirmada_sombra": ("confirmada_sombra", "pendiente_alineaciones", "retirada", "en_juego"),
    "retirada": ("en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra", "descartada"),
    "en_juego": ("liquidada",),
    "liquidada": ("evaluada",),
    "descartada": (),
    "evaluada": (),
}
"""A copy of ``fbi.lifecycle.machine`` as of this revision (``tests/unit/test_lifecycle_machine.py`` holds the two equal)."""
RESULTS = ("win", "loss", "push", "void", "half_win", "half_loss")
EVALUATIONS = ("E1", "E2", "E3", "E4")
ACTORS = ("code", "model", "owner")


def _q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _words(words: tuple[str, ...]) -> str:
    return ", ".join(_q(w) for w in words)


def _pairs(pairs: list[tuple[str, str]]) -> str:
    return ", ".join(f"({_q(a)}, {_q(b)})" for a, b in pairs)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    moves = [(a, b) for a in STATES for b in MOVES[a]]
    reasons = [(s, r) for s in STATES for r in REASONS[s]]
    op.execute(rf"""
        CREATE TABLE intel.selection_lifecycle (
            id                  BIGSERIAL     PRIMARY KEY,
            chain_key           TEXT          NOT NULL,
            writer              TEXT          NOT NULL CHECK (writer ~ '^[a-z][a-z0-9.-]{{2,40}}$'),
            fixture_id          BIGINT        NOT NULL REFERENCES core.fixtures(id),
            market_key          TEXT          NOT NULL CHECK (length(market_key) BETWEEN 1 AND 40),
            selection           TEXT          NOT NULL CHECK (length(selection) BETWEEN 1 AND 60),
            line                NUMERIC(6,2)  NOT NULL DEFAULT 0,
            layer               TEXT          NOT NULL CHECK (layer ~ '^decision-[a-z0-9.-]{{1,30}}$'),
            previous_id         BIGINT,
            from_state          TEXT          CHECK (from_state IS NULL OR from_state IN ({_words(STATES)})),
            state               TEXT          NOT NULL CHECK (state IN ({_words(STATES)})),
            reason              TEXT          NOT NULL,
            actor               TEXT          NOT NULL CHECK (actor IN ({_words(ACTORS)})),
            owner_signature     TEXT          CHECK (owner_signature IS NULL OR length(owner_signature) BETWEEN 10 AND 600),
            evaluation          TEXT          CHECK (evaluation IS NULL OR evaluation IN ({_words(EVALUATIONS)})),
            evaluation_version  INTEGER       CHECK (evaluation_version IS NULL OR evaluation_version >= 1),
            settlement_result   TEXT          CHECK (settlement_result IS NULL OR settlement_result IN ({_words(RESULTS)})),
            known_at            TIMESTAMPTZ   NOT NULL,
            recorded_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
            source              TEXT          NOT NULL CHECK (source ~ '^[a-z_]+\.[a-z_]+$'),
            source_id           BIGINT,
            machine_version     TEXT          NOT NULL CHECK (machine_version ~ '^lifecycle-v[0-9]+$'),
            map_version         TEXT          CHECK (map_version IS NULL OR map_version ~ '^lifecycle-map-v[0-9]+$'),
            CONSTRAINT selection_lifecycle_chain_key CHECK (
                chain_key = writer || '|' || fixture_id::text || '|' || market_key || '|' || selection || '|' || line::text),
            CONSTRAINT selection_lifecycle_tip UNIQUE (id, chain_key, state),
            CONSTRAINT selection_lifecycle_previous_fk FOREIGN KEY (previous_id, chain_key, from_state)
                REFERENCES intel.selection_lifecycle (id, chain_key, state),
            CONSTRAINT selection_lifecycle_genesis CHECK ((previous_id IS NULL) = (from_state IS NULL)),
            CONSTRAINT selection_lifecycle_first_state CHECK (previous_id IS NOT NULL OR state = 'detectado'),
            CONSTRAINT selection_lifecycle_move CHECK (from_state IS NULL OR (from_state, state) IN ({_pairs(moves)})),
            CONSTRAINT selection_lifecycle_reason CHECK ((state, reason) IN ({_pairs(reasons)})),
            CONSTRAINT selection_lifecycle_model_only_down CHECK (actor <> 'model' OR state IN ('retirada', 'descartada')),
            CONSTRAINT selection_lifecycle_owner CHECK (
                (actor = 'owner') = (reason = 'autorizada_por_dueno') AND (actor = 'owner') = (owner_signature IS NOT NULL)),
            CONSTRAINT selection_lifecycle_authorisation CHECK (reason <> 'autorizada_por_dueno' OR from_state = 'confirmada_sombra'),
            CONSTRAINT selection_lifecycle_settled CHECK ((state = 'liquidada') = (settlement_result IS NOT NULL)),
            CONSTRAINT selection_lifecycle_evaluation CHECK (evaluation_version IS NULL OR evaluation IS NOT NULL)
        );
        CREATE UNIQUE INDEX intel_selection_lifecycle_one_successor ON intel.selection_lifecycle (chain_key, COALESCE(previous_id, 0));
        CREATE INDEX intel_selection_lifecycle_newest ON intel.selection_lifecycle (chain_key, id DESC);
        CREATE INDEX intel_selection_lifecycle_fixture ON intel.selection_lifecycle (fixture_id);
        CREATE INDEX intel_selection_lifecycle_state ON intel.selection_lifecycle (state, known_at);
        COMMENT ON TABLE intel.selection_lifecycle IS
          'The one cycle of states of each selection (IA-068, AD-D02): detectado -> ... -> evaluada, one row per move, each naming the '
          'row before it, with a reason from the closed list of its state. A model only takes a selection down; the owner only '
          'authorises a confirmed one. The shadow writer reads the current layers and changes none of them. Append-only.';
        COMMENT ON COLUMN intel.selection_lifecycle.chain_key IS
          'writer|fixture|market|selection|line: the chain this row belongs to (the database checks it matches the columns).';
        COMMENT ON COLUMN intel.selection_lifecycle.layer IS 'The decision layer whose verdicts drive the chain (decision-v1, decision-fam-v1 ...).';
        COMMENT ON COLUMN intel.selection_lifecycle.source IS 'The table of the layer the move was read from, and source_id its row.';

        CREATE FUNCTION intel.selection_lifecycle_in_order() RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE before_at TIMESTAMPTZ;
        BEGIN
            IF NEW.previous_id IS NOT NULL THEN
                SELECT known_at INTO before_at FROM intel.selection_lifecycle WHERE id = NEW.previous_id;
                IF before_at IS NOT NULL AND NEW.known_at < before_at THEN
                    RAISE EXCEPTION 'intel.selection_lifecycle: a move known at % cannot follow one known at %', NEW.known_at, before_at
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER selection_lifecycle_in_order BEFORE INSERT ON intel.selection_lifecycle
            FOR EACH ROW EXECUTE FUNCTION intel.selection_lifecycle_in_order();
    """)
    op.execute("CREATE TRIGGER selection_lifecycle_append_only BEFORE UPDATE OR DELETE ON intel.selection_lifecycle "
               "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE intel.selection_lifecycle")
    op.execute("DROP FUNCTION intel.selection_lifecycle_in_order()")
