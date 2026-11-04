#!/bin/bash
# Runs ONCE, when PostgreSQL initialises an empty data folder (docker-entrypoint-initdb.d), as the superuser
# `postgres` - the only superuser, used by nobody but the operator inside this container. Creates the database
# and the roles PrediGol uses (what each may do: ../grants.sql):
#
#   fbi              owns the database and every object in it (migrations, backups, maintenance); NOSUPERUSER
#   predigol_worker  the worker
#   predigol_api     the API
#   predigol_rollback  NOLOGIN: the automatic roll-back of an agent's promotion (../roles.sql carries the same statements for a
#                    cluster that already exists); the worker reaches it with SET ROLE
#   predigol_learning  NOLOGIN: the Learning Analyst writes hypotheses and nothing else (no promotion); reached with SET ROLE as well
#
# The passwords come from the env file through docker-compose.yml (PREDIGOL_DB_*_PASSWORD), never from here.
set -Eeuo pipefail
: "${PREDIGOL_DB_OWNER_PASSWORD:?}" "${PREDIGOL_DB_WORKER_PASSWORD:?}" "${PREDIGOL_DB_API_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$PREDIGOL_DB_OWNER_PASSWORD" -v worker_pw="$PREDIGOL_DB_WORKER_PASSWORD" \
  -v api_pw="$PREDIGOL_DB_API_PASSWORD" <<'SQL'
CREATE ROLE fbi LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'owner_pw';
CREATE ROLE predigol_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'worker_pw';
CREATE ROLE predigol_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'api_pw';
COMMENT ON ROLE fbi IS 'PrediGol: owner of the database and its objects (migrations, backups, maintenance)';
COMMENT ON ROLE predigol_worker IS 'PrediGol worker: DML on the data schemas, no DDL, nothing in auth';
COMMENT ON ROLE predigol_api IS 'PrediGol API: reads; writes accounts, user records and the admin console tables';
CREATE ROLE predigol_rollback NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
COMMENT ON ROLE predigol_rollback IS 'PrediGol: writes only the automatic demotion of a champion agent in intel.promotions (reached with SET ROLE)';
GRANT predigol_rollback TO predigol_worker WITH INHERIT FALSE, SET TRUE;
CREATE ROLE predigol_learning NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
COMMENT ON ROLE predigol_learning IS 'PrediGol: the Learning Analyst writes only hypotheses (analytics.research_hypotheses), never a promotion (reached with SET ROLE)';
GRANT predigol_learning TO predigol_worker WITH INHERIT FALSE, SET TRUE;

CREATE DATABASE fbi OWNER fbi;
REVOKE ALL ON DATABASE fbi FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE fbi TO predigol_worker, predigol_api;
-- The Admin Console's System page reads the activity and statistics views.
GRANT pg_read_all_stats TO predigol_api;

-- A forgotten open transaction holds locks and stops autovacuum: end it.
ALTER ROLE predigol_api SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE predigol_api SET statement_timeout = '30s';
ALTER ROLE predigol_worker SET idle_in_transaction_session_timeout = '30min';

\connect fbi
-- Nobody but the owner creates objects; the owner owns public too.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO fbi;
SQL
echo "predigol: roles fbi, predigol_worker, predigol_api, predigol_rollback, predigol_learning and database fbi created"
