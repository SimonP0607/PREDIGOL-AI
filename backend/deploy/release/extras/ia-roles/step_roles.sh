#!/usr/bin/env bash
# Release __REL__, after the deploy and its smoke test: the one role of the Plan Maestro IA that only the database SUPERUSER can
# create - predigol_rollback, NOLOGIN, the automatic roll-back of an agent's promotion (sections 25 and 32) - the grants that go with it, and the
# proof, made in the database itself, that it is the database and not a prompt that decides who may write the promotion of an agent.
#
# What it WRITES (all idempotent): the role, the worker's membership of it (SET and not INHERIT) - db/roles.sql, run as the superuser INSIDE the
# database container - and the grants (predigolctl grants, as the owner). Nothing else stays: the proof (roles_proof.sql) inserts rows in
# intel.promotions inside ONE transaction that it rolls back, with ids of its own that consume no sequence value, and this script then counts that no
# agent promotion exists and that none of the proof's rows is left.
#
# Before it does anything: the lock of the deploy (the same one predigolctl takes), the checkout of the release, the revision of the
# database and the policy of migration 0111. Exit statuses: 0 every check OK; 1 a precondition failed (nothing was done); 2 something was done and a
# check is NOT OK (the role and the grants are harmless without the code that uses them: nothing reads them before phase 6). The result is also in
# roles.status. Never prints a key or a password: it reads none.
set -Eeuo pipefail
D=/root/releases/__STAMP__
BE_DIR=/opt/predigol/backend
BE_WANT=__BE_WANT__
cd "$D"
# shellcheck source=/dev/null
. "$BE_DIR/deploy/vps/bin/lib.sh"
BAD=0
section() { echo; echo "== $*"; }
good() { echo "OK: $*"; }
bad() { BAD=$((BAD + 1)); echo "NOT OK: $*"; }
verdict() { if [ "$1" = "$2" ]; then good "$3 = $1"; else bad "$3 = $1, expected $2"; fi; }
refuse() { echo "REFUSED: $*"; echo "refused: $*" > "$D/roles.status"; exit 1; }
# the owner, read-only (a time limit of 20 s); stdin is never read
ro() { docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=20000' predigol-postgres psql -U fbi -d fbi -At -F '|' -v ON_ERROR_STOP=1 "$@" < /dev/null; }
# the superuser, INSIDE the database container (the operator's way in; the owner role is not a superuser)
SU() { docker exec -i -e PGOPTIONS='-c statement_timeout=60000 -c lock_timeout=10000' predigol-postgres psql -U postgres -d fbi -v ON_ERROR_STOP=1 -qX "$@"; }

section "before anything: the lock, the checkout, the revision, the policy"
date -u +%FT%TZ
exclusive deploy
good "the lock of the deploy is ours (no deploy, rollback or import runs)"
[ "$(git -C "$BE_DIR" rev-parse --short=12 HEAD)" = "$BE_WANT" ] || refuse "the backend checkout is not $BE_WANT"
[ -z "$(git -C "$BE_DIR" status --porcelain --untracked-files=no)" ] || refuse "the backend checkout has local changes"
REV=$(ro -c "select version_num from alembic_version") || refuse "the revision could not be read"
[ "${REV:0:4}" = "$(jq -r .latest_migration "$D/RELEASE.json" | cut -c1-4)" ] || refuse "the database is at $REV, not at the migration of the release"
[ "$(ro -c "select count(*) from pg_policies where schemaname = 'intel' and tablename = 'promotions' and policyname = 'promotions_write'")" = "1" ] \
  || refuse "the row policy promotions_write of migration 0111 is not there"
[ "$(SU -At -F '|' -c "select current_user, (select rolsuper from pg_roles where rolname = current_user)" < /dev/null)" = "postgres|t" ] \
  || refuse "the superuser path inside the database container does not answer"
for f in roles.sql grants.sql; do [ -r "$BE_DIR/deploy/vps/db/$f" ] || refuse "db/$f is not in the checkout"; done
[ -r "$D/roles_proof.sql" ] || refuse "roles_proof.sql is not in the package"
good "checkout $BE_WANT, revision $REV, policy promotions_write, superuser path"
echo "started: $(date -u +%FT%TZ)" > "$D/roles.status"
BEFORE_AGENT_ROWS=$(ro -c "select count(*) from intel.promotions where entity = 'agent'") || refuse "intel.promotions could not be read"
echo "agent promotions before: $BEFORE_AGENT_ROWS; intel.promotions rows: $(ro -c "select count(*) from intel.promotions")"
echo "predigol_rollback exists before: $(ro -c "select count(*) from pg_roles where rolname = 'predigol_rollback'")"

section "db/roles.sql as the database superuser (idempotent: the role NOLOGIN, the worker's membership with SET and without INHERIT)"
SU -f - < "$BE_DIR/deploy/vps/db/roles.sql" || { echo "roles: db/roles.sql failed ($(date -u +%FT%TZ))" | tee "$D/roles.status"; exit 2; }
good "db/roles.sql applied"
section "predigolctl grants (db/grants.sql as the owner; idempotent; the block of the rollback role runs now that the role exists)"
predigolctl grants || { echo "roles: predigolctl grants failed ($(date -u +%FT%TZ))" | tee "$D/roles.status"; exit 2; }
good "grants applied"

section "the role, as the catalog shows it (read only)"
verdict "$(ro -c "select rolsuper, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls from pg_roles where rolname = 'predigol_rollback'")" "f|f|f|f|f|f" \
  "predigol_rollback: superuser, createrole, createdb, login, replication, bypassrls"
verdict "$(ro -c "select m.rolname, a.inherit_option, a.set_option, a.admin_option from pg_auth_members a join pg_roles r on r.oid = a.roleid join pg_roles m on m.oid = a.member where r.rolname = 'predigol_rollback' order by 1")" \
  "predigol_worker|f|t|f" "who is a member of predigol_rollback (name, inherit, set, admin)"
verdict "$(ro -c "select pg_has_role('predigol_worker', 'predigol_rollback', 'SET'), pg_has_role('predigol_worker', 'predigol_rollback', 'USAGE'), pg_has_role('predigol_api', 'predigol_rollback', 'SET'), pg_has_role('predigol_api', 'predigol_rollback', 'MEMBER')")" \
  "t|f|f|f" "the worker may become the role, does not hold its privileges until it does; the API cannot (SET, USAGE, SET, MEMBER)"
verdict "$(ro -c "select coalesce(string_agg(n.nspname || '.' || c.relname || ':' || c.relkind::text, ',' order by n.nspname, c.relname), '') from pg_class c join pg_namespace n on n.oid = c.relnamespace where c.relkind in ('r', 'p', 'v', 'm', 'f', 'S') and n.nspname not in ('pg_catalog', 'information_schema', 'pg_toast', 'public') and case when c.relkind = 'S' then has_sequence_privilege('predigol_rollback', c.oid, 'USAGE,SELECT,UPDATE') else has_table_privilege('predigol_rollback', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') end")" \
  "intel.promotions:r,intel.promotions_id_seq:S" "every relation the role reaches with any privilege"
verdict "$(ro -c "select coalesce(string_agg(p, ',' order by p), '') from unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p where has_table_privilege('predigol_rollback', 'intel.promotions', p)")" \
  "INSERT,SELECT" "its privileges on intel.promotions"
verdict "$(ro -c "select coalesce(string_agg(p, ',' order by p), '') from unnest(array['USAGE','SELECT','UPDATE']) p where has_sequence_privilege('predigol_rollback', 'intel.promotions_id_seq', p)")" \
  "SELECT,USAGE" "its privileges on the sequence of intel.promotions"
verdict "$(ro -c "select coalesce(string_agg(nspname, ',' order by nspname), '') from pg_namespace where nspname not like 'pg\\_%' and nspname not in ('information_schema', 'public') and has_schema_privilege('predigol_rollback', oid, 'USAGE')")" \
  "intel" "the schemas it can use (public aside)"
verdict "$(ro -c "select has_table_privilege('predigol_rollback', 'public.alembic_version', 'SELECT')")" "f" "it cannot read the revision table"
verdict "$(ro -c "select relrowsecurity, relforcerowsecurity from pg_class where oid = 'intel.promotions'::regclass")" "t|f" \
  "row security on intel.promotions (on, and not forced: the owner signs)"
verdict "$(ro -c "select count(*) from pg_policies where schemaname = 'intel' and tablename = 'promotions'")" "4" "policies of intel.promotions"

section "the proof (roles_proof.sql): one transaction, rolled back; every case says who acts, what is tried and what must come of it"
WANT_CASES=$(grep -c '"name":' "$D/roles_proof.sql")
rc=0
SU -f - < "$D/roles_proof.sql" > "$D/roles_proof.raw" 2>&1 || rc=$?
sed -n 's/^.*NOTICE:  PROOF|/PROOF|/p' "$D/roles_proof.raw" | tee "$D/roles_proof.out"
grep -v 'NOTICE:  PROOF|' "$D/roles_proof.raw" | grep -v '^$' | head -n 20 || true
verdict "$rc" "0" "exit status of the proof's psql"
verdict "$(grep -c '^PROOF|ok|' "$D/roles_proof.out" || true)" "$WANT_CASES" "cases of the proof that came out as expected, of $WANT_CASES"
verdict "$(grep -c '^PROOF|FAIL|' "$D/roles_proof.out" || true)" "0" "cases of the proof that did not"

section "nothing of the proof stays (read only)"
verdict "$(ro -c "select count(*) from intel.promotions where entity = 'agent'")" "$BEFORE_AGENT_ROWS" "agent promotions after the proof (before: $BEFORE_AGENT_ROWS)"
verdict "$(ro -c "select count(*) from intel.promotions where id < 0")" "0" "rows of intel.promotions with an id of the proof (negative)"
verdict "$(ro -c "select count(*) from pg_stat_activity where datname = 'fbi' and state like 'idle in transaction%'")" "0" "sessions idle in a transaction"

section "result"
if [ "$BAD" -eq 0 ]; then
  echo "roles: every check OK ($(date -u +%FT%TZ))" | tee "$D/roles.status"
  exit 0
fi
echo "roles: $BAD check(s) NOT OK ($(date -u +%FT%TZ))" | tee "$D/roles.status"
exit 2
