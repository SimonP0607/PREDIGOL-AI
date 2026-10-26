-- What the worker and the API may do in the database - least privilege, never a superuser for the application.
--
--   fbi              OWNS the database and every object in it: migrations, backups, maintenance. NOSUPERUSER.
--   predigol_worker  the worker: reads and writes every data schema (core, market, features, models, picks, raw,
--                    audit, analytics ...). No DDL, nothing in auth, never the migration ledger.
--   predigol_api     the API: reads what it shows; writes only accounts (auth), a user's own records
--                    (picks.user_*) and the Admin Console's few tables (AI layer, research decisions, the
--                    evidence-ledger verdicts, the AI decision layer's run requests). Never ai.* results: those
--                    are the worker's, append-only.
--   predigol_rollback  (NOLOGIN, created by the operator: db/roles.sql) the automatic roll-back of an agent's promotion:
--                    reads intel.promotions and inserts into it, nothing else anywhere. Which row it may insert is the
--                    row policy of migration 0111, not this file: the worker reaches the role with SET ROLE.
--
-- Run as the owner after EVERY migration (bin/predigolctl does: deploy, import). Idempotent. A table a future
-- migration adds is covered at once by the default privileges below, and re-granted explicitly the next run.
-- The roles themselves are created once, by db/initdb/10-predigol-roles.sh, when the data folder is new.

DO $grants$
DECLARE
  s text;
BEGIN
  FOR s IN
    SELECT nspname FROM pg_namespace
    WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema'
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO predigol_api, predigol_worker', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO predigol_api', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE fbi IN SCHEMA %I GRANT SELECT ON TABLES TO predigol_api', s);
    IF s = 'auth' THEN
      EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA auth FROM predigol_worker';
      EXECUTE 'REVOKE USAGE ON SCHEMA auth FROM predigol_worker';
    ELSE
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO predigol_worker', s);
      EXECUTE format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA %I TO predigol_worker', s);
      EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE fbi IN SCHEMA %I '
                     'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO predigol_worker', s);
      EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE fbi IN SCHEMA %I '
                     'GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO predigol_worker', s);
    END IF;
  END LOOP;
END
$grants$;

-- The migration ledger: read by both (the health check shows the revision), written only by the owner.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.alembic_version FROM predigol_worker, predigol_api;

-- The API's writes.
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA auth TO predigol_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA auth TO predigol_api;
ALTER DEFAULT PRIVILEGES FOR ROLE fbi IN SCHEMA auth GRANT INSERT, UPDATE, DELETE ON TABLES TO predigol_api;
ALTER DEFAULT PRIVILEGES FOR ROLE fbi IN SCHEMA auth GRANT USAGE, SELECT ON SEQUENCES TO predigol_api;

DO $api_writes$
DECLARE
  t text;
  seq regclass;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    -- a user's own records (fbi.userdata)
    'picks.user_picks:INSERT, UPDATE, DELETE', 'picks.user_parlays:INSERT, UPDATE, DELETE',
    'picks.user_parlay_legs:INSERT, UPDATE, DELETE',
    -- the AI layer and the owner's research decisions (fbi.analyst, fbi.research.evolution)
    'analytics.ai_runs:INSERT, UPDATE', 'analytics.ai_claims:INSERT, UPDATE', 'analytics.ai_reports:INSERT, UPDATE',
    'analytics.ai_pick_flags:INSERT, UPDATE', 'analytics.research_hypotheses:INSERT, UPDATE',
    'analytics.research_memory:INSERT, UPDATE',
    -- the owner's "run now" for the AI decision layer: a queued request the worker picks up (fbi.ai.cycle)
    'ai.run_requests:INSERT',
    -- the owner's verdict on an evidence-ledger entry (Admin Console, Data truth)
    'audit.evidence_ledger:UPDATE',
    -- the owner's decisions in the referee queue: merge, undo, split, reject, reopen, rename (fbi.people.referees). A person
    -- moves aliases between referees and decides pairs; the rules' own pass (the worker) is the only one that makes aliases.
    'core.referees:INSERT, UPDATE', 'core.referee_aliases:UPDATE', 'core.referee_candidates:INSERT, UPDATE, DELETE',
    'core.referee_events:INSERT, UPDATE'
  ]
  LOOP
    IF to_regclass(split_part(t, ':', 1)) IS NULL THEN
      RAISE NOTICE 'grants: % does not exist (yet) - skipped', split_part(t, ':', 1);
      CONTINUE;
    END IF;
    EXECUTE format('GRANT %s ON %s TO predigol_api', split_part(t, ':', 2), split_part(t, ':', 1));
    FOR seq IN
      SELECT d.objid::regclass FROM pg_depend d JOIN pg_class c ON c.oid = d.objid
      WHERE d.refobjid = split_part(t, ':', 1)::regclass AND c.relkind = 'S' AND d.deptype IN ('a', 'i')
    LOOP
      EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO predigol_api', seq);
    END LOOP;
  END LOOP;
END
$api_writes$;

-- The automatic roll-back of an agent's promotion (Plan Maestro IA, sections 25 and 32). The role does not exist until the operator
-- creates it (db/roles.sql), so until then there is nothing to grant. It gets nothing by default: only what is named here.
DO $rollback$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predigol_rollback') THEN
    RAISE NOTICE 'grants: the role predigol_rollback does not exist (yet) - skipped (db/roles.sql creates it)';
    RETURN;
  END IF;
  IF to_regclass('intel.promotions') IS NULL THEN
    RAISE NOTICE 'grants: intel.promotions does not exist (yet) - skipped';
    RETURN;
  END IF;
  GRANT USAGE ON SCHEMA intel TO predigol_rollback;
  GRANT SELECT, INSERT ON intel.promotions TO predigol_rollback;
  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO predigol_rollback', pg_get_serial_sequence('intel.promotions', 'id'));
END
$rollback$;
