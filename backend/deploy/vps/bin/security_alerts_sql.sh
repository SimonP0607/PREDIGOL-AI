#!/usr/bin/env bash
# The queries of security-alerts.sh (S3, alerts 23-26). Each returns ONE number, or "n|ids" where noted. Read-only; the caller runs them with
# psql_q (default_transaction_read_only = on). They count and list ids: the email column of auth.audit_events (it holds whatever was typed in a
# failed login, even a password in the wrong field: R18) and the addresses are never selected.
# shellcheck disable=SC2034  # read by security-alerts.sh and by the tests

# 23. failed sign-ins in the last 5 minutes (login.failed and login.refused)
SQL_FAILED="SELECT count(*) FROM auth.audit_events WHERE action IN ('login.failed', 'login.refused') AND at > now() - interval '5 minutes'"

# 24. accounts put on hold in the last hour: how many, and which ids
SQL_LOCKED="SELECT count(DISTINCT target_user_id) || '|' || coalesce(string_agg(DISTINCT target_user_id::text, ',' ORDER BY target_user_id::text), '') FROM auth.audit_events WHERE action = 'login.locked' AND at > now() - interval '60 minutes'"

# 25. administrators who signed in in the last 10 minutes with a browser+system not seen for that account in the 90 days before.
#     The user agent is compared without its numbers (a browser update is not a new device).
SQL_NEWDEVICE="SELECT count(DISTINCT e.target_user_id) || '|' || coalesce(string_agg(DISTINCT e.target_user_id::text, ',' ORDER BY e.target_user_id::text), '')
  FROM auth.audit_events e JOIN auth.users u ON u.id = e.target_user_id AND u.role = 'SUPER_ADMIN'
 WHERE e.action = 'login.succeeded' AND e.at > now() - interval '10 minutes'
   AND NOT EXISTS (SELECT 1 FROM auth.audit_events o
                    WHERE o.target_user_id = e.target_user_id AND o.action = 'login.succeeded' AND o.id < e.id AND o.at > e.at - interval '90 days'
                      AND regexp_replace(coalesce(o.detail->>'user_agent', ''), '[0-9._]+', '', 'g') = regexp_replace(coalesce(e.detail->>'user_agent', ''), '[0-9._]+', '', 'g'))"

# 26. privileged changes in the last 10 minutes: role changes, a new SUPER_ADMIN, MFA or password resets of an account.
#     :owner is the owner's user id. Result "total|by_someone_else|ids": by_someone_else counts the ones whose actor is an account that is not the owner
#     (no actor = the command line on the server, which only root can run: it is told, but not as SEV1).
SQL_PRIVILEGED="SELECT count(*) || '|' || count(*) FILTER (WHERE actor_user_id IS NOT NULL AND actor_user_id <> :owner) || '|' || coalesce(string_agg(DISTINCT target_user_id::text, ',' ORDER BY target_user_id::text), '')
  FROM auth.audit_events
 WHERE at > now() - interval '10 minutes'
   AND (action IN ('user.role_changed', 'mfa.reset', 'password.reset') OR (action = 'user.created' AND detail->>'role' = 'SUPER_ADMIN'))"

# the owner: PREDIGOL_OWNER_USER_ID when set, else the oldest SUPER_ADMIN account (an account created later never becomes the owner)
SQL_OWNER="SELECT coalesce(min(id), 0) FROM auth.users WHERE role = 'SUPER_ADMIN'"
