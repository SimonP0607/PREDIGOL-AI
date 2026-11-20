-- One measure of the size of the database into audit.db_size_history (plan PM, PM-01-02, migration 0168). Run as the owner by the storage
-- report (bin/storage-report.sh, four times a day) through stdin, like grants.sql. The only write of that report: sizes, never content.
--
--   db_bytes      pg_database_size of this database
--   schema_bytes  {schema: bytes} - pg_total_relation_size (table, indexes, TOAST) of every table, partition and materialised view
--   top_tables    [{name, bytes}] - the twelve largest, as the report's own list
--
-- Before migration 0168 the table does not exist: a notice, nothing written, no error. A second run in the same second writes nothing.
SET statement_timeout = '60s';
SET lock_timeout = '5s';
DO $db_size$
BEGIN
  IF to_regclass('audit.db_size_history') IS NULL THEN
    RAISE NOTICE 'db_size_history: audit.db_size_history does not exist (yet) - skipped (migration 0168)';
    RETURN;
  END IF;
  EXECUTE $insert$
    WITH rel AS (
      SELECT n.nspname AS schema, n.nspname || '.' || c.relname AS name, pg_total_relation_size(c.oid) AS bytes
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE c.relkind IN ('r', 'm') AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'
    )
    INSERT INTO audit.db_size_history (measured_at, database_name, db_bytes, schema_bytes, top_tables, source)
    SELECT date_trunc('second', now()), current_database(), pg_database_size(current_database()),
           (SELECT coalesce(jsonb_object_agg(schema, bytes), '{}'::jsonb)
              FROM (SELECT schema, sum(bytes)::bigint AS bytes FROM rel GROUP BY schema) s),
           (SELECT coalesce(jsonb_agg(jsonb_build_object('name', name, 'bytes', bytes) ORDER BY bytes DESC, name), '[]'::jsonb)
              FROM (SELECT name, bytes FROM rel ORDER BY bytes DESC, name LIMIT 12) t),
           'storage-report'
    ON CONFLICT (measured_at) DO NOTHING
  $insert$;
END
$db_size$;
