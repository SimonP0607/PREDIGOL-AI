"""data-quality registry: what the provider said, and what we could not use

THE RULE THIS TABLE EXISTS TO SERVE
-----------------------------------
    RAW  ->  NORMALIZED  ->  QUALITY ISSUE / TRANSFORMATION

so that "what API-Football said" and "what we made of it" stay distinguishable.
Until now the second half had nowhere to go, and the code did the one thing the
project forbids: it fixed the provider quietly. Three examples from our own
source, all found by reading it rather than by a failure:

  * ``ingestion/details.py`` sets shots_on_target to NULL when it exceeds
    shots_total, and passes_accurate to NULL when it exceeds passes. A real
    inconsistency in the provider's data became a missing value in ours, with
    nothing recording that it had ever been there.
  * ``backfill.py`` logs unknown statistic types and moves on, so a new provider
    field looks identical to one we never received.
  * six fixtures decided on penalties have no derivable 90-minute score, and
    fifteen line-ups arrived with fewer than eleven starters. Both are facts
    about the provider's data. Neither had anywhere to be written down.

WHAT THE REGISTRY IS
--------------------
``audit.data_quality_codes``   the catalogue of codes, so a code is a known
                               thing with a default severity rather than a free
                               string that drifts.
``audit.data_quality_issues``  one row per (code, entity, field, observed value).
                               Structured columns, not a JSON dump: ``field``,
                               ``observed``, ``expected``, and the numeric pair
                               when the values are numbers, so "every fixture
                               where shots_on_target exceeded shots_total by more
                               than 3" is a WHERE clause. ``details`` is capped
                               at 4 kB by a CHECK precisely so it cannot become
                               the place everything is dumped.

``core.fixture_team_stats`` also gains ``dropped_fields``: the schema's own CHECK
forbids ``shots_on_target > shots``, so the value genuinely cannot be stored -
but naming the column that was dropped makes the NULL readable without opening
the raw payload, and makes the table comment true again.

It is deliberately NOT ``audit.data_quality_checks``, which already exists and
records that a check RAN (passed, expected, actual, denominator). Checks say we
looked; issues say what we found. Both are needed, and until now neither had a
writer.

IDEMPOTENCE
-----------
``fingerprint`` is a hash of what makes an issue THE SAME issue: code, entity,
field and observed value. Re-running detection bumps ``occurrences`` and
``last_seen_at`` instead of writing a second row, so a nightly sweep does not
inflate its own numbers.

A RESOLUTION HAS TO SAY SOMETHING
---------------------------------
``status = 'resolved'`` requires both ``resolved_at`` and ``resolution``, and
``wont_fix`` requires ``resolution`` too. An issue cannot be made to disappear
without a sentence explaining why - which is the same discipline as
``is_validated_close`` requiring ``close_validation_method``.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE audit.data_quality_codes (
    code             TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL,
    default_severity TEXT NOT NULL CHECK (default_severity IN ('info','warning','error','critical')),
    is_provider_fact BOOLEAN NOT NULL DEFAULT true
);
COMMENT ON COLUMN audit.data_quality_codes.is_provider_fact IS
  'true cuando el problema es un hecho sobre los datos del proveedor (no lo
   arreglamos, lo registramos). false cuando es un fallo nuestro de ingesta.';

INSERT INTO audit.data_quality_codes (code, name, description, default_severity, is_provider_fact) VALUES
 ('PROVIDER_INCONSISTENCY','Provider inconsistency',
  'Dos campos del proveedor se contradicen (shots_on_target > shots_total, '
  'passes_accurate > passes, marcador de descanso mayor que el final). Se '
  'registra el valor observado; NO se corrige.', 'warning', true),
 ('INCOMPLETE_LINEUP','Incomplete line-up',
  'La alineacion recibida tiene menos de once titulares, o le falta formacion o '
  'entrenador. No se rellena: se marca.', 'warning', true),
 ('RESULT_UNRESOLVED','Result unresolved',
  'El partido termino pero el marcador que necesitamos no es derivable: penales '
  '(PEN) sin desglose, o final sin goles publicados.', 'error', true),
 ('MISSING_DETAIL','Missing detail',
  'Un dataset de detalle esperado para un partido jugado no existe: eventos, '
  'alineaciones, estadisticas de equipo o de jugador.', 'warning', true),
 ('NORMALIZATION_REJECTED','Normalization rejected',
  'El proveedor envio un valor que el limite no pudo convertir en dominio: una '
  'linea que no es multiplo de 0.25, una cuota fuera de rango, una seleccion '
  'que no pertenece al mercado.', 'warning', true),
 ('UNKNOWN_PROVIDER_ENTITY','Unknown provider entity',
  'El proveedor nombro algo que no conocemos: un bet sin mapear, un tipo de '
  'estadistica nuevo, una casa de apuestas o un equipo sin referencia.', 'info', true),
 ('STALE_DATA','Stale data',
  'Lo que tenemos deberia haberse actualizado y no lo ha hecho: un partido '
  'proximo sin precios recientes, un resultado pendiente mucho despues del pitido.',
  'warning', false),
 ('LINEAGE_BROKEN','Lineage broken',
  'Una fila normalizada no se puede trazar hasta el payload que la produjo, o el '
  'fichero crudo que dice tener no esta en el almacen.', 'error', false);

CREATE TABLE audit.data_quality_issues (
    id                 BIGSERIAL   PRIMARY KEY,
    code               TEXT        NOT NULL REFERENCES audit.data_quality_codes(code),
    severity           TEXT        NOT NULL CHECK (severity IN ('info','warning','error','critical')),
    entity_type        TEXT        NOT NULL,
    entity_id          BIGINT,
    provider           TEXT        NOT NULL DEFAULT 'api-football',
    provider_entity_id BIGINT,
    payload_hash       TEXT        REFERENCES raw.ingestion_payloads(hash),
    run_id             BIGINT      REFERENCES raw.ingestion_runs(id),
    field              TEXT,
    observed           TEXT,
    expected           TEXT,
    observed_number    NUMERIC,
    expected_number    NUMERIC,
    detail             TEXT,
    details            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    fingerprint        TEXT        NOT NULL UNIQUE,
    occurrences        INTEGER     NOT NULL DEFAULT 1 CHECK (occurrences >= 1),
    detected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    status             TEXT        NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open','acknowledged','resolved','wont_fix','superseded')),
    resolved_at        TIMESTAMPTZ,
    resolution         TEXT,
    CONSTRAINT issue_entity_is_identified
        CHECK (entity_id IS NOT NULL OR provider_entity_id IS NOT NULL OR payload_hash IS NOT NULL),
    CONSTRAINT issue_resolution_is_explained
        CHECK (status <> 'resolved' OR (resolved_at IS NOT NULL AND resolution IS NOT NULL)),
    CONSTRAINT issue_wont_fix_is_explained
        CHECK (status <> 'wont_fix' OR resolution IS NOT NULL),
    CONSTRAINT issue_last_seen_is_not_before_detection
        CHECK (last_seen_at >= detected_at),
    CONSTRAINT issue_details_stay_small
        CHECK (length(details::text) <= 4096)
);
COMMENT ON TABLE audit.data_quality_issues IS
  'Lo que el proveedor dijo y no pudimos usar tal cual. NUNCA se arregla el dato
   en silencio: se normaliza lo que se puede y lo demas se registra aqui.';
COMMENT ON COLUMN audit.data_quality_issues.payload_hash IS
  'El payload_id que pedia el mandato: en este esquema el id de un payload ES su
   hash (clave primaria de raw.ingestion_payloads).';
COMMENT ON COLUMN audit.data_quality_issues.provider_entity_id IS
  'El id del proveedor, que a veces es lo unico que tenemos: una entidad que no
   hemos normalizado todavia no tiene entity_id nuestro.';
COMMENT ON COLUMN audit.data_quality_issues.details IS
  'Solo lo que no tiene columna. Limitado a 4 kB por CHECK: si algo se repite,
   merece una columna, no un JSON mas grande.';
COMMENT ON CONSTRAINT issue_entity_is_identified ON audit.data_quality_issues IS
  'Un problema sin sujeto no es accionable: hace falta nuestro id, el del
   proveedor, o al menos el payload donde aparecio.';

CREATE INDEX data_quality_issues_open
    ON audit.data_quality_issues (code, severity, last_seen_at DESC)
    WHERE status IN ('open','acknowledged');
CREATE INDEX data_quality_issues_entity
    ON audit.data_quality_issues (entity_type, entity_id) WHERE entity_id IS NOT NULL;
CREATE INDEX data_quality_issues_provider_entity
    ON audit.data_quality_issues (entity_type, provider_entity_id) WHERE provider_entity_id IS NOT NULL;
CREATE INDEX data_quality_issues_payload
    ON audit.data_quality_issues (payload_hash) WHERE payload_hash IS NOT NULL;
CREATE INDEX data_quality_issues_run ON audit.data_quality_issues (run_id) WHERE run_id IS NOT NULL;

-- audit.data_quality_checks gana lo que le faltaba para ser util: el denominador.
ALTER TABLE audit.data_quality_checks
    ADD COLUMN population   BIGINT,
    ADD COLUMN offenders    BIGINT,
    ADD COLUMN issues_opened INTEGER NOT NULL DEFAULT 0,
    ADD CONSTRAINT check_offenders_fit_the_population
        CHECK (offenders IS NULL OR population IS NULL OR offenders <= population);
COMMENT ON COLUMN audit.data_quality_checks.population IS
  'Sobre cuantas filas se ejecuto la comprobacion. Sin denominador no hay
   porcentaje: NULL significa "no se pudo establecer", no cero.';
COMMENT ON COLUMN audit.data_quality_checks.offenders IS
  'Cuantas de esas filas fallaron. issues_opened puede ser menor: una incidencia
   ya registrada se actualiza, no se duplica.';

-- Que un NULL se pueda leer sin abrir el payload crudo.
ALTER TABLE core.fixture_team_stats
    ADD COLUMN dropped_fields TEXT[] NOT NULL DEFAULT '{}',
    ADD CONSTRAINT team_stats_dropped_fields_are_named
        CHECK (array_position(dropped_fields, NULL) IS NULL);
COMMENT ON COLUMN core.fixture_team_stats.dropped_fields IS
  'Campos que el proveedor SI envio y que no pudimos guardar porque contradecian
   a otro campo (shots_on_target > shots). Sin esto, el comentario de la tabla
   -"NULL = la fuente no lo reporto"- era falso justo en esas celdas. El valor
   observado queda en audit.data_quality_issues y en el payload crudo.';
COMMENT ON TABLE core.fixture_team_stats IS
  'Team match statistics per source. NULL means the source did not report it -
   never zero - UNLESS the column is named in dropped_fields, which means it was
   reported and contradicted another field. Written with the payload they came
   from; a newer payload for the same fixture and source replaces the row.';

-- Un resumen honesto, para /health/quality y el API de solo lectura.
CREATE VIEW audit.open_quality_issues AS
SELECT i.code,
       c.name             AS code_name,
       c.is_provider_fact,
       i.severity,
       i.entity_type,
       count(*)           AS issues,
       sum(i.occurrences) AS occurrences,
       min(i.detected_at) AS first_detected_at,
       max(i.last_seen_at) AS last_seen_at
  FROM audit.data_quality_issues i
  JOIN audit.data_quality_codes  c ON c.code = i.code
 WHERE i.status IN ('open','acknowledged')
 GROUP BY i.code, c.name, c.is_provider_fact, i.severity, i.entity_type;
COMMENT ON VIEW audit.open_quality_issues IS
  'Cuenta incidencias y ocurrencias por separado: 15 alineaciones incompletas
   vistas tres veces cada una son 15 problemas, no 45.';
"""

DOWNGRADE = """
DROP VIEW IF EXISTS audit.open_quality_issues;
ALTER TABLE audit.data_quality_checks
    DROP CONSTRAINT IF EXISTS check_offenders_fit_the_population;
ALTER TABLE audit.data_quality_checks
    DROP COLUMN IF EXISTS issues_opened,
    DROP COLUMN IF EXISTS offenders,
    DROP COLUMN IF EXISTS population;
ALTER TABLE core.fixture_team_stats
    DROP CONSTRAINT IF EXISTS team_stats_dropped_fields_are_named;
ALTER TABLE core.fixture_team_stats DROP COLUMN IF EXISTS dropped_fields;
DROP TABLE IF EXISTS audit.data_quality_issues;
DROP TABLE IF EXISTS audit.data_quality_codes;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
