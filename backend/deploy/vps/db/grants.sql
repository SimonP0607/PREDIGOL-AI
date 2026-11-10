-- What the worker and the API may do in the database - least privilege, never a superuser for the application.
--
--   fbi              OWNS the database and every object in it: migrations, backups, maintenance. NOSUPERUSER.
--   predigol_worker  the worker: reads and writes every data schema (core, market, features, models, picks, raw,
--                    audit, analytics ...). No DDL, nothing in auth or customer, never the migration ledger.
--   predigol_api     the API: reads what it shows; writes only accounts (auth, their one-use links included -
--                    plan UX, A7), the customer's own data (customer: consents, privacy requests - A4; the
--                    messages to readers and their choices - A5; product analytics - A6; the membership - A8), a
--                    user's own records (picks.user_*) and the Admin Console's few tables (AI layer, research
--                    decisions, the evidence-ledger verdicts, the AI decision layer's run requests). Never ai.*
--                    results: those are the worker's, append-only.
--                    The messenger (plan UX, A5) runs with this role: it also drafts the owner's notices
--                    (audit.notifications), records its cycles in the job ledger (raw.ingestion_runs), keeps
--                    the product analytics' daily aggregate and retention (A6), records the notices of a
--                    membership's end (A8), keeps the readers' feedback's retention (B6) and writes and sends the
--                    readers' notices on their devices (B7).
--   predigol_rollback  (NOLOGIN, created by the operator: db/roles.sql) the automatic roll-back of an agent's promotion:
--                    reads intel.promotions and inserts into it, nothing else anywhere. Which row it may insert is the
--                    row policy of migration 0111, not this file: the worker reaches the role with SET ROLE.
--   predigol_learning  (NOLOGIN, created by the operator: db/roles.sql) the Learning Analyst (phase 5): reads and inserts hypotheses
--                    (analytics.research_hypotheses) and nothing else anywhere - in particular nothing in intel.promotions.
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

-- The incident register (S3, bin/incident-dump.sh and bin/incident.sh): the owner role writes and reads it; the application never does. The loop above
-- hands the API SELECT and the worker every privilege on every table of every schema, so for these objects it is taken back, after every migration.
DO $incidents$
BEGIN
  IF to_regclass('audit.incident_events') IS NOT NULL THEN
    REVOKE ALL ON audit.incident_events FROM predigol_api, predigol_worker;
    REVOKE ALL ON SEQUENCE audit.incident_events_id_seq FROM predigol_api, predigol_worker;
  END IF;
  IF to_regclass('audit.incidents') IS NOT NULL THEN
    REVOKE ALL ON audit.incidents FROM predigol_api, predigol_worker;
  END IF;
END
$incidents$;

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
    -- what a reader has seen of the welcome tour and the guides (fbi.customer.guides, UX-032): deleted with the rest of
    -- what the reader keeps when their account is anonymised
    'customer.guide_progress:INSERT, UPDATE, DELETE',
    'audit.notifications:INSERT', 'raw.ingestion_runs:INSERT, UPDATE',
    -- the calls to endpoints on their way out, a count per day and kind of caller (fbi.api.services.deprecated, BE-033)
    'audit.deprecated_api_use:INSERT, UPDATE',
    -- product analytics (fbi.customer.events, plan UX, A6): the API records a reader's events; the messenger
    -- recomputes the daily aggregate and, once the owner switches the purge on, deletes what is past its retention
    -- (raw events 90 days, aggregates 13 months)
    'customer.product_events:INSERT, DELETE', 'customer.activity_daily:INSERT, UPDATE, DELETE',
    -- the membership (fbi.customer.membership, plan UX, A8): the owner's payments, periods and their events, and the
    -- messenger's notices of a period's end - recorded, never edited or deleted (the tables' own triggers refuse it)
    'customer.payments:INSERT', 'customer.membership_periods:INSERT', 'customer.membership_events:INSERT',
    -- the coupons of the membership (fbi.customer.discounts, UX-005): the owner creates one and may disable it (the only
    -- change its own trigger allows, once); a reader holding one is recorded, never edited or deleted
    'customer.coupons:INSERT, UPDATE', 'customer.coupon_redemptions:INSERT',
    -- a reader's favourite leagues and teams (fbi.customer.favorites, plan UX, A13): chosen or removed, never edited; deleted
    -- with the rest of what the reader keeps when the account is anonymised (A7)
    'customer.favorites:INSERT, DELETE',
    -- what readers think of PrediGol (fbi.customer.feedback, plan UX, B6): the survey answered or closed, «¿Te sirvió?»
    -- answered and changed; deleted when the account is anonymised (A7) and, once the owner switches the purge on, by the
    -- messenger past its 24 months
    'customer.feedback:INSERT, UPDATE, DELETE',
    -- the readers' notices on their devices (fbi.customer.push and fbi.messaging.push_jobs, plan UX, B7): a browser allowed
    -- and revoked (never edited otherwise), a match's bell rung, changed and taken away, the queue written and its fate
    -- recorded; all deleted when the account is anonymised (A7) and, once the owner switches the purge on, by the messenger
    -- (notices past 90 days, revoked browsers past 30)
    'customer.push_subscriptions:INSERT, UPDATE, DELETE', 'customer.match_alerts:INSERT, UPDATE, DELETE',
    'customer.push_notices:INSERT, UPDATE, DELETE',
    -- each customer's state of the day (fbi.customer.lifecycle, plan UX, B11): written once a day by the messenger, never edited
    -- (the table's own trigger refuses it); deleted only when the account is anonymised (A7) and, once the owner switches the
    -- purge on, past its 24 months - both under the maintenance switch
    'customer.lifecycle_snapshots:INSERT, DELETE',
    -- the owner's communiqués (fbi.customer.announcements, plan UX, 4.3): written and published from the console, hidden again
    -- (never deleted: a trigger refuses it); what was done to each is a line of the record, append-only
    'customer.announcements:INSERT, UPDATE', 'customer.announcement_log:INSERT',
    -- a reader's request for access, «ya pagué» (plan del flujo de usuario, tramo 1, UX-027): made by the reader, decided by the
    -- owner (status, decision), blanked of the payer's name and note when the account is anonymised; never deleted (a trigger
    -- refuses it) and never edited once decided
    'customer.payment_requests:INSERT, UPDATE',
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

-- The Learning Analyst (Plan Maestro IA, phase 5): the same way - nothing until the operator creates the role, and then only the hypotheses table
-- (and its sequence). It has no privilege on intel.promotions and no schema but analytics; the worker reaches the role with SET ROLE and holds none
-- of its privileges until it asks.
DO $learning$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predigol_learning') THEN
    RAISE NOTICE 'grants: the role predigol_learning does not exist (yet) - skipped (db/roles.sql creates it)';
    RETURN;
  END IF;
  IF to_regclass('analytics.research_hypotheses') IS NULL THEN
    RAISE NOTICE 'grants: analytics.research_hypotheses does not exist (yet) - skipped';
    RETURN;
  END IF;
  GRANT USAGE ON SCHEMA analytics TO predigol_learning;
  GRANT SELECT, INSERT ON analytics.research_hypotheses TO predigol_learning;
  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO predigol_learning', pg_get_serial_sequence('analytics.research_hypotheses', 'id'));
END
$learning$;
