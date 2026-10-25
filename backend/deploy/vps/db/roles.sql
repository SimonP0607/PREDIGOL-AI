-- The roles that only the DATABASE SUPERUSER can create, for a cluster that already exists (a new one gets them from
-- db/initdb/10-predigol-roles.sh, which carries the same statements). Idempotent.
--
--   predigol_rollback   NOLOGIN. The automatic roll-back of an agent's promotion (Plan Maestro IA, sections 25 and 32). It reads
--                       intel.promotions and writes ONE kind of row in it: the demotion, by the system, of the agent that is the
--                       champion of a family right now. The row policy of migration 0111 says exactly which row, and grants.sql
--                       gives the role its privileges. The worker reaches it with SET ROLE: the membership carries SET and not
--                       INHERIT, so the worker does not get the role's privileges until it asks for them, and then it has ONLY
--                       those - it cannot promote, and it cannot write any other entity.
--
-- Run it as the superuser, inside the database container, from the checkout (the same way grants.sql travels, on stdin):
--
--   docker compose ... exec -T postgres psql -U postgres -d fbi -v ON_ERROR_STOP=1 -qX -f - < db/roles.sql
--
-- then apply the grants (predigolctl grants).

DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predigol_worker') THEN
    RAISE EXCEPTION 'the role predigol_worker does not exist: this is not a PrediGol cluster';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predigol_rollback') THEN
    CREATE ROLE predigol_rollback NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$roles$;
COMMENT ON ROLE predigol_rollback IS 'PrediGol: writes only the automatic demotion of a champion agent in intel.promotions (reached with SET ROLE)';
GRANT predigol_rollback TO predigol_worker WITH INHERIT FALSE, SET TRUE;
