"""near-close provenance: every stored price traceable back to the request

WHAT WAS MISSING
----------------
``market.odds_snapshots`` carries ``payload_hash`` and is therefore traceable:
from a price you can reach the payload, the file on disk, the endpoint, the
sanitised params and the ingestion run that asked for it.
``market.near_close_snapshots`` carried none of that. It is the table the model
comparison and every "did we beat the price?" question will lean on, and it could
not answer where its numbers came from.

Worse, nothing tied a near-close row to the series it is supposed to project. A
row could claim a price at an instant that the series never recorded, and no
constraint would notice.

THE CHAIN, NOW ENFORCED
-----------------------
    ingestion run -> raw payload (hash, file, endpoint, params, fetched_at)
                  -> normalized snapshot in market.odds_snapshots
                  -> near-close projection
                  -> fixture, bookmaker, market, selection, line, captured_at

Three things make it hold:

1. ``payload_hash NOT NULL REFERENCES raw.ingestion_payloads(hash)`` - the same
   link the series already had.
2. A trigger on insert and update: the exact price a near-close row names must
   exist in ``market.odds_snapshots`` (same fixture, bookmaker, market,
   selection, line and instant) AND agree with it - odds, minutes_to_ko, source
   and payload_hash. So a near-close row can never claim a price the series
   never held, nor restate one differently.
3. A DEFERRABLE constraint trigger on delete: removing a series row while a
   near-close row still projects it is refused at commit, after any cascade from
   core.fixtures has had its turn.

A composite foreign key onto the series primary key would have been the obvious
way to do (2), and PostgreSQL does allow a foreign key onto a partitioned table.
It was tried and rejected: the constraint takes a dependency on every leaf
partition, so ``DROP TABLE market.odds_snapshots_2026_11`` then fails with
"other objects depend on it". Locking partition management behind a constraint
that has to be dropped at the worst possible moment is not worth the small
amount of extra strictness, and the triggers cover both directions anyway.

``materialised_at`` records when WE computed the projection, which is not
``captured_at``, the instant the provider's price is from. Keeping them separate
is what stops a re-materialisation from looking like a new observation.

THE NAME STAYS NEAR_CLOSE
-------------------------
This is still not a closing line, and revision 0004 explains at length why.
``is_validated_close`` still defaults to false and still requires
``close_validation_method`` to be set before anything may claim otherwise.

MIGRATING EXISTING ROWS
-----------------------
``payload_hash`` is backfilled from the series row each near-close row projects.
That is not invention: same fixture, same bookmaker, same market, same selection,
same line, same instant - it is the same observation. A row with no such series
row cannot be given a provenance it never had, so the migration REFUSES rather
than guessing, and names how many rows are involved. (Measured before writing
this: 0 such rows exist, and 0 near-close rows exist at all.)

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE market.near_close_snapshots
    ADD COLUMN payload_hash    TEXT,
    ADD COLUMN materialised_at TIMESTAMPTZ NOT NULL DEFAULT now();

COMMENT ON COLUMN market.near_close_snapshots.payload_hash IS
  'El payload del proveedor del que sale este precio. Cierra la cadena
   run -> payload -> snapshot -> near_close.';
COMMENT ON COLUMN market.near_close_snapshots.materialised_at IS
  'Cuando NOSOTROS calculamos esta proyeccion. NO es captured_at, que es el
   instante del precio del proveedor. Separarlos evita que rematerializar
   parezca una observacion nueva.';

-- La procedencia se toma de la fila de la serie que esta fila proyecta.
UPDATE market.near_close_snapshots n
   SET payload_hash = o.payload_hash
  FROM market.odds_snapshots o
 WHERE o.fixture_id   = n.fixture_id
   AND o.bookmaker_id = n.bookmaker_id
   AND o.market_key   = n.market_key
   AND o.selection    = n.selection
   AND o.line         = n.line
   AND o.captured_at  = n.captured_at;

-- Lo que no se puede trazar no se inventa: la migracion se niega.
DO $do$
DECLARE orphans BIGINT;
BEGIN
    SELECT count(*) INTO orphans FROM market.near_close_snapshots WHERE payload_hash IS NULL;
    IF orphans > 0 THEN
        RAISE EXCEPTION
            '% near-close row(s) have no matching row in market.odds_snapshots, so their '
            'provenance cannot be established. They are not migrated: decide explicitly '
            'whether to delete them or to re-capture, and record the decision.', orphans;
    END IF;
END
$do$;

ALTER TABLE market.near_close_snapshots
    ALTER COLUMN payload_hash SET NOT NULL,
    ADD CONSTRAINT near_close_payload_exists
        FOREIGN KEY (payload_hash) REFERENCES raw.ingestion_payloads(hash);

CREATE INDEX near_close_snapshots_payload ON market.near_close_snapshots (payload_hash);

-- Que la comprobacion de linea hable primero: los triggers BEFORE se disparan
-- en orden alfabetico y "linea imposible" es un diagnostico mas util que
-- "no hay snapshot que proyectar" cuando ambos son ciertos.
ALTER TRIGGER near_close_snapshots_line_is_valid ON market.near_close_snapshots
    RENAME TO near_close_line_is_valid;

-- La proyeccion tiene que coincidir con la serie, no solo existir en ella.
CREATE FUNCTION market.assert_near_close_projects_the_series() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE
    s RECORD;
BEGIN
    SELECT odds_decimal, minutes_to_ko, source, payload_hash INTO s
      FROM market.odds_snapshots
     WHERE fixture_id = NEW.fixture_id AND bookmaker_id = NEW.bookmaker_id
       AND market_key = NEW.market_key AND selection = NEW.selection
       AND line = NEW.line AND captured_at = NEW.captured_at;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no snapshot for % % % % at %, so there is nothing to project',
            NEW.market_key, NEW.selection, NEW.line, NEW.bookmaker_id, NEW.captured_at
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF s.odds_decimal <> NEW.odds_decimal OR s.minutes_to_ko <> NEW.minutes_to_ko
       OR s.source <> NEW.source OR s.payload_hash <> NEW.payload_hash THEN
        RAISE EXCEPTION
            'near-close row disagrees with the snapshot it projects (odds %/%, minutes %/%, '
            'source %/%, payload %/%)',
            NEW.odds_decimal, s.odds_decimal, NEW.minutes_to_ko, s.minutes_to_ko,
            NEW.source, s.source, left(NEW.payload_hash, 12), left(s.payload_hash, 12)
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$fn$;
COMMENT ON FUNCTION market.assert_near_close_projects_the_series() IS
  'La clave ajena prueba que la fila de la serie existe; esto prueba que no la
   hemos reescrito con otros valores. Distingue lo que dijo el proveedor de lo
   que interpretamos nosotros.';

CREATE TRIGGER near_close_projects_the_series
    BEFORE INSERT OR UPDATE ON market.near_close_snapshots
    FOR EACH ROW EXECUTE FUNCTION market.assert_near_close_projects_the_series();

-- Y en el otro sentido: no se borra la evidencia dejando la conclusion.
CREATE FUNCTION market.assert_no_orphan_near_close() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF EXISTS (SELECT 1 FROM market.near_close_snapshots n
                WHERE n.fixture_id = OLD.fixture_id AND n.bookmaker_id = OLD.bookmaker_id
                  AND n.market_key = OLD.market_key AND n.selection = OLD.selection
                  AND n.line = OLD.line AND n.captured_at = OLD.captured_at) THEN
        RAISE EXCEPTION
            'a near-close row still projects the snapshot % % % at % that this statement '
            'deleted; delete the projection first or keep the snapshot',
            OLD.market_key, OLD.selection, OLD.line, OLD.captured_at
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NULL;
END;
$fn$;
COMMENT ON FUNCTION market.assert_no_orphan_near_close() IS
  'DEFERRABLE a proposito: un DELETE de core.fixtures cascadea a las dos tablas
   en un orden que no controlamos, asi que la comprobacion espera al commit.';

CREATE CONSTRAINT TRIGGER near_close_not_orphaned
    AFTER DELETE ON market.odds_snapshots
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION market.assert_no_orphan_near_close();

-- La cadena completa, consultable.
CREATE VIEW market.near_close_lineage AS
SELECT n.fixture_id,
       f.provider_fixture_id,
       f.kickoff_at,
       n.bookmaker_id,
       b.provider_bookmaker_id,
       b.name              AS bookmaker_name,
       n.market_key,
       m.is_model_enabled  AS market_is_model_enabled,
       n.selection,
       n.line,
       n.odds_decimal,
       n.captured_at,
       n.minutes_to_ko,
       n.source,
       n.is_validated_close,
       n.close_validation_method,
       n.materialised_at,
       n.payload_hash,
       p.endpoint,
       p.params            AS request_params,
       p.fetched_at        AS payload_fetched_at,
       p.http_status,
       p.file_path         AS payload_file,
       p.bytes             AS payload_bytes,
       r.id                AS run_id,
       r.job_name,
       r.started_at        AS run_started_at,
       r.status            AS run_status
  FROM market.near_close_snapshots n
  JOIN core.fixtures          f ON f.id   = n.fixture_id
  JOIN market.bookmakers      b ON b.id   = n.bookmaker_id
  JOIN market.markets         m ON m.key  = n.market_key
  JOIN raw.ingestion_payloads p ON p.hash = n.payload_hash
  JOIN raw.ingestion_runs     r ON r.id   = p.run_id;
COMMENT ON VIEW market.near_close_lineage IS
  'La cadena que pidio el mandato, de una sola consulta: peticion (run, endpoint,
   params) -> payload crudo (hash, fichero) -> snapshot normalizado -> near_close
   -> fixture, casa, mercado, captured_at. Sin secretos: params esta saneado en
   origen.';
"""

DOWNGRADE = """
DROP VIEW IF EXISTS market.near_close_lineage;
DROP TRIGGER IF EXISTS near_close_not_orphaned ON market.odds_snapshots;
DROP FUNCTION IF EXISTS market.assert_no_orphan_near_close();
DROP TRIGGER IF EXISTS near_close_projects_the_series ON market.near_close_snapshots;
DROP FUNCTION IF EXISTS market.assert_near_close_projects_the_series();
DROP INDEX IF EXISTS market.near_close_snapshots_payload;
ALTER TRIGGER near_close_line_is_valid ON market.near_close_snapshots
    RENAME TO near_close_snapshots_line_is_valid;
ALTER TABLE market.near_close_snapshots
    DROP CONSTRAINT IF EXISTS near_close_payload_exists;
ALTER TABLE market.near_close_snapshots
    DROP COLUMN IF EXISTS materialised_at,
    DROP COLUMN IF EXISTS payload_hash;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
