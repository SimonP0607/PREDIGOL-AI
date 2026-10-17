-- Run once on the PRIMARY (it replicates to the replica).
-- psql -U fbi -d fbi -v ro_pw="'...'" -v repl_pw="'...'" -f roles.sql
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD :repl_pw;

CREATE ROLE fbi_ro WITH LOGIN PASSWORD :ro_pw;
GRANT CONNECT ON DATABASE fbi TO fbi_ro;
ALTER ROLE fbi_ro SET default_transaction_read_only = on;
ALTER ROLE fbi_ro SET statement_timeout = '10s';

-- Product schemas only. raw.* (provider payloads, redistribution-restricted)
-- and ops/credential-bearing tables are deliberately NOT granted.
DO $$
DECLARE s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['core','market','odds','predictions','picks','quality','catalog'] LOOP
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA %I TO fbi_ro', s);
      EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO fbi_ro', s);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO fbi_ro', s);
    END IF;
  END LOOP;
END $$;
