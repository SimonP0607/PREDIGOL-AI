#!/usr/bin/env bash
# Builds the package ("kit") of ONE release, from the monorepo, the same way every time (plan CI/CD, phase C3).
#
#   backend/deploy/release/build_kit.sh --rel NAME --from-be SHA12 [--from-web SHA12] [--head COMMIT]
#                                       [--parts backend|web|backend,web] [--spec FILE.json] [--extras DIR] [--out DIR]
#                                       [--from-server HOST]   (reads --from-be / --from-web from the server's checkouts)
#
# What production runs is not this repository's history but a line of "release commits": for each part (backend, web) one commit per
# release whose tree is the folder (HEAD:backend, HEAD:web) and whose parent is the previous release commit (refs/release/backend-NAME,
# refs/release/web-NAME, kept in this repository). This script makes the next link of each line, a git bundle that holds only that link
# (prerequisite: the commit production runs), the server-side scripts of deploy/release/templates/server with the names, commits and parts
# filled in, RELEASE.json (what the scripts read: commits, new migrations, model-code fingerprints and the guard's verdict, and the
# release's own checks from --spec) and the two lists of hashes. It touches neither the server nor the database: it only writes the folder
# <out>/<stamp>-<name>/ and the two refs/release refs (the same commit-tree always gives the same commit, so building twice is harmless).
#
# Nothing here decides to release: that is ship.sh (after gate.sh) and, above all, the owner's word.
set -Eeuo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REL="" HEAD_REF="HEAD" FROM_BE="" FROM_WEB="" PARTS="backend" EXTRAS="" OUT="" SPEC="" FROM_SERVER="" ALLOW_UNCOVERED=0
die() { echo "build_kit: $*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rel) REL="$2"; shift 2 ;;
    --head) HEAD_REF="$2"; shift 2 ;;
    --from-be) FROM_BE="$2"; shift 2 ;;
    --from-web) FROM_WEB="$2"; shift 2 ;;
    --from-server) FROM_SERVER="$2"; shift 2 ;;
    --parts) PARTS="$2"; shift 2 ;;
    --spec) SPEC="$2"; shift 2 ;;
    --extras) EXTRAS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --allow-uncovered) ALLOW_UNCOVERED=1; shift ;;
    *) die "unknown argument $1" ;;
  esac
done
[[ "$REL" =~ ^[a-z0-9][a-z0-9-]{1,40}$ ]] || die "--rel NAME: lowercase letters, digits and dashes (e.g. f11, ia-p05)"
repo="$(git rev-parse --show-toplevel)"
cd "$repo"
head="$(git rev-parse --verify "$HEAD_REF^{commit}")"
if [[ -n "$FROM_SERVER" ]]; then
  FROM_BE="$(ssh -o BatchMode=yes "$FROM_SERVER" 'git -C /opt/predigol/backend rev-parse --short=12 HEAD')"
  FROM_WEB="$(ssh -o BatchMode=yes "$FROM_SERVER" 'git -C /opt/predigol/web rev-parse --short=12 HEAD')"
fi
[[ -n "$FROM_BE" && -n "$FROM_WEB" ]] || die "--from-be and --from-web (or --from-server HOST): the commits production runs"
releases() { case ",$PARTS," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
ref_of() { git for-each-ref --format='%(objectname) %(refname)' refs/release/ | awk -v p="$1" 'index($1, p) == 1 {print $2; exit}'; }
ensure_base() { # <part> <sha12> <dir on the server>: the ref of the release commit production runs; fetched from the server when this clone lacks it
  local ref; ref="$(ref_of "$2")"
  if [[ -z "$ref" && -n "$FROM_SERVER" ]]; then
    git fetch -q "$FROM_SERVER:$3" HEAD && [[ "$(git rev-parse --short=12 FETCH_HEAD)" == "$2" ]] || die "the server's $1 checkout is not $2"
    git update-ref "refs/release/$1-production-$2" FETCH_HEAD; ref="refs/release/$1-production-$2"
  fi
  [[ -n "$ref" ]] || die "no refs/release/* ref starts with $2 (the $1 production runs): use --from-server HOST or fetch the release refs"
  echo "$ref"
}
base_be_ref="$(ensure_base backend "$FROM_BE" /opt/predigol/backend)"; base_web_ref="$(ensure_base web "$FROM_WEB" /opt/predigol/web)"
base_be="$(git rev-parse "$base_be_ref")"; base_web="$(git rev-parse "$base_web_ref")"

# The release commit of a part: tree = the folder at HEAD, parent = what production runs. Author and dates are fixed by the HEAD commit,
# so the same HEAD always gives the same release commit.
cdate="$(git show -s --format=%cI "$head")"
mk() { # <part> <base>
  GIT_AUTHOR_NAME="PrediGol release" GIT_AUTHOR_EMAIL="release@predigol.invalid" GIT_COMMITTER_NAME="PrediGol release" \
    GIT_COMMITTER_EMAIL="release@predigol.invalid" GIT_AUTHOR_DATE="$cdate" GIT_COMMITTER_DATE="$cdate" \
    git commit-tree "$head:$1" -p "$2" -m "release $REL: $1 (monorepo ${head:0:12})"
}
OUT="${OUT:-$repo/../releases}"; mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%dT%H%MZ)-$REL"; KIT="$OUT/$STAMP"; [[ ! -e "$KIT" ]] || die "$KIT exists"
mkdir -p "$KIT"

BE_WANT="${FROM_BE}"; WEB_WANT="${FROM_WEB}"
if releases backend; then
  [[ "$(git rev-parse "$head:backend")" != "$(git rev-parse "$base_be^{tree}")" ]] || die "nothing changed in the backend since $FROM_BE"
  rel_be="$(mk backend "$base_be")"; git update-ref "refs/release/backend-$REL" "$rel_be"
  git bundle create "$KIT/backend_$REL.bundle" "refs/release/backend-$REL" "^$base_be" > /dev/null 2>&1
  git bundle verify "$KIT/backend_$REL.bundle" > /dev/null 2>&1 || die "the backend bundle does not verify"
  BE_WANT="$(git rev-parse --short=12 "$rel_be")"
fi
if releases web; then
  [[ "$(git rev-parse "$head:web")" != "$(git rev-parse "$base_web^{tree}")" ]] || die "nothing changed in the web since $FROM_WEB"
  rel_web="$(mk web "$base_web")"; git update-ref "refs/release/web-$REL" "$rel_web"
  git bundle create "$KIT/web_$REL.bundle" "refs/release/web-$REL" "^$base_web" > /dev/null 2>&1
  git bundle verify "$KIT/web_$REL.bundle" > /dev/null 2>&1 || die "the web bundle does not verify"
  WEB_WANT="$(git rev-parse --short=12 "$rel_web")"
fi

# What the scripts need to know about the backend's migrations and model code.
mig_num() { git ls-tree -r --name-only "$1" -- migrations/versions | sed -n 's#.*/\([0-9]\{4\}\)_.*\.py$#\1#p' | sort | tail -n 1; }
after_ref="$base_be"; releases backend && after_ref="refs/release/backend-$REL"
latest_migration="$(mig_num "$after_ref")"; revision_before="$(mig_num "$base_be")"
migrations_new="$(git diff --name-only --diff-filter=A "$base_be" "$after_ref" -- migrations/versions | sed 's#.*/##; s#\.py$##' | sort | jq -R . | jq -s .)"
gitdir="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
guard="$(mktemp)"; trap 'rm -f "$guard"' EXIT
git show "$head:backend/scripts/model_code_guard.py" > "$guard"   # the guard of the commit being released, not of whatever is checked out
fp() { python3 "$guard" fingerprint "git=$1" --git-dir "$gitdir"; }
mc_before="$(fp "$base_be")"; mc_after="$(fp "$after_ref")"
gstatus="$(python3 "$guard" check --before "git=$base_be" --after "git=$after_ref" --git-dir "$gitdir" --mode stop 2>&1)" && grc=0 || grc=$?
if [[ $grc -eq 4 && $ALLOW_UNCOVERED -ne 1 ]]; then die "the model-code guard stops this release (UNCOVERED): the model code changes and the ledger does not put it in force
$gstatus"; fi
[[ $grc -eq 0 || $grc -eq 4 ]] || die "the model-code guard could not look (status $grc): $gstatus"
cp "$guard" "$KIT/model_code_guard.py"

# Scripts: the templates with the release's names, then the extras (a file of the same name replaces the template's).
render() { sed -e "s|__STAMP__|$STAMP|g" -e "s|__REL__|$REL|g" -e "s|__PARTS__|$PARTS|g" -e "s|__BE_FROM__|$FROM_BE|g" -e "s|__BE_WANT__|$BE_WANT|g" \
  -e "s|__WEB_FROM__|$FROM_WEB|g" -e "s|__WEB_WANT__|$WEB_WANT|g" -e "s|__MODEL_FP__|$mc_after|g" "$1" > "$2"; chmod 755 "$2"; }
for f in "$here"/templates/server/*; do render "$f" "$KIT/$(basename "$f")"; done
if [[ -n "$EXTRAS" ]]; then for f in "$EXTRAS"/*; do [[ -f "$f" ]] && render "$f" "$KIT/$(basename "$f")"; done; fi
if grep -l '__[A-Z_]*__' "$KIT"/*.sh > /dev/null 2>&1; then die "a token was left unfilled in: $(grep -l '__[A-Z_]*__' "$KIT"/*.sh | xargs -n1 basename | tr '\n' ' ')"; fi
for f in "$KIT"/*.sh; do bash -n "$f" || die "$(basename "$f") has a syntax error"; done

# RELEASE.json: the facts, then the release's own checks (--spec: {"precheck": {...}, "verify_checks": [...], "verify_env": [...]}).
jq -n --arg rel "$REL" --arg at "$(date -u +%FT%TZ)" --arg head "$head" --arg parts "$PARTS" --arg beF "$FROM_BE" --arg beW "$BE_WANT" \
  --arg wF "$FROM_WEB" --arg wW "$WEB_WANT" --arg rb "$revision_before" --arg lm "$latest_migration" --argjson mn "$migrations_new" \
  --arg mb "$mc_before" --arg ma "$mc_after" --arg gs "$gstatus" '{
    release: $rel, created_at: $at, source: {commit: $head}, parts: ($parts | split(",")),
    backend: {from: $beF, want: $beW}, web: {from: $wF, want: $wW},
    revision_before: $rb, latest_migration: $lm, migrations_new: $mn,
    model_code: {before: $mb, after: $ma, mode: "stop", status: ($gs | split("\n")[0])},
    precheck: {}, verify_checks: [], verify_env: []}' > "$KIT/RELEASE.json"
if [[ -n "$SPEC" ]]; then jq -s '.[0] * .[1]' "$KIT/RELEASE.json" "$SPEC" > "$KIT/RELEASE.json.new" && mv "$KIT/RELEASE.json.new" "$KIT/RELEASE.json"; fi

(cd "$KIT" && shopt -s nullglob && files=(model_code_guard.py RELEASE.json *.bundle) && sha256sum "${files[@]}" > SHA256SUMS && sha256sum model_code_guard.py ./*.sh > SCRIPTS.sha256)
echo "kit: $KIT"
echo "  release $REL from monorepo ${head:0:12}; parts: $PARTS"
echo "  backend $FROM_BE -> $BE_WANT; web $FROM_WEB -> $WEB_WANT; migrations: $revision_before -> $latest_migration (new: $(jq -r '. | length' <<< "$migrations_new"))"
echo "  model code: $mc_before -> $mc_after ($(head -n 1 <<< "$gstatus"))"