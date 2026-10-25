-- What the worker and the API may do in the database - least privilege, never a superuser for the application.
--
--   fbi              OWNS the database and every object in it: migrations, backups, maintenance. NOSUPERUSER.
--   predigol_worker  the worker: reads and writes every data schema (core, market, features, models, picks, raw,
--                    audit, analytics ...). No DDL, nothing in auth or customer, never the migration ledger.
--   predigol_api     the API: reads what it shows; writes only accounts (auth, their one-use links included -
--                    plan UX, A7), the customer's own data (customer: consents, privacy requests - A4; the
--                    messages to readers and their choices - A5; product analytics - A6), a user's own records
--                    (picks.user_*) and the Admin Console's few tables (AI layer, research decisions, the
--                    evidence-ledger verdicts, the AI decision layer's run requests). Never ai.* results: those
--                    are the worker's, append-only.
--                    The messenger (plan UX, A5) runs with this role: it also drafts the owner's notices
--                    (audit.notifications), records its cycles in the job ledger (raw.ingestion_runs) and keeps
--                    the product analytics' daily aggregate and retention (A6).
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
    ELSIF s = 'customer' THEN
      -- The customer's own data (plan UX, A4) is treated as auth is: the worker of PrediGol Intelligence never reads
      -- it. Its sequences and the default privileges too, so a table a later migration adds never reaches the worker,
      -- even after a run of an older version of this file.
      EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA customer FROM predigol_worker';
      EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA customer FROM predigol_worker';
      EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE fbi IN SCHEMA customer REVOKE ALL ON TABLES FROM predigol_worker';
      EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE fbi IN SCHEMA customer REVOKE ALL ON SEQUENCES FROM predigol_worker';
      EXECUTE 'REVOKE USAGE ON SCHEMA customer FROM predigol_worker';
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
    -- the customer's own data (fbi.customer, plan UX, A4): a consent and a request's message are never edited or
    -- deleted (the tables' own triggers refuse it too); a request's status changes
    'customer.consents:INSERT', 'customer.support_tickets:INSERT, UPDATE', 'customer.ticket_messages:INSERT',
    -- the messages to readers and their choices (fbi.messaging, plan UX, A5): a queued message's fate changes, it
    -- is never deleted (the table's own triggers refuse it too); the owner's notices the messenger drafts (the
    -- worker's notifier sends them) and the messenger's cycles in the job ledger
    'customer.messages_outbox:INSERT, UPDATE',
    -- a reader's choices; deleted with the rest of what the reader keeps when their account is anonymised at their
    -- request, with the owner's confirmation (fbi.auth.anonymize, plan UX, A7)
    'customer.preferences:INSERT, UPDATE, DELETE',
    'audit.notifications:INSERT', 'raw.ingestion_runs:INSERT, UPDATE',
    -- product analytics (fbi.customer.events, plan UX, A6): the API records a reader's events; the messenger
    -- recomputes the daily aggregate and, once the owner switches the purge on, deletes what is past its retention
    -- (raw events 90 days, aggregates 13 months)
    'customer.product_events:INSERT, DELETE', 'customer.activity_daily:INSERT, UPDATE, DELETE',
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
