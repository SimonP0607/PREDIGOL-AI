#!/usr/bin/env bash
# The CI gate of a release (plan CI/CD, C3): the backend and web folders of the commit to release must have passed the CI on GitHub. A CI run
# is accepted for ANY commit whose folder is byte-for-byte the same tree (a docs-only commit after a green run does not need another 12 minutes).
#
#   backend/deploy/release/gate.sh [--head COMMIT] [--parts backend,web]
# Needs `gh` signed in. Exit 0 = green, 1 = not green (the reason is printed).
set -Eeuo pipefail
HEAD_REF="HEAD" PARTS="backend,web"
while [[ $# -gt 0 ]]; do case "$1" in --head) HEAD_REF="$2"; shift 2 ;; --parts) PARTS="$2"; shift 2 ;; *) echo "unknown $1" >&2; exit 2 ;; esac; done
head="$(git rev-parse --verify "$HEAD_REF^{commit}")"
rc=0
check() { # <part> <workflow name>
  local part="$1" wf="$2" want sha
  want="$(git rev-parse "$head:$part")"
  while read -r sha; do
    [[ -n "$sha" ]] || continue
    git cat-file -e "$sha^{commit}" 2> /dev/null || continue
    if [[ "$(git rev-parse "$sha:$part" 2> /dev/null)" == "$want" ]]; then echo "OK: $wf passed on ${sha:0:12} (same $part tree as ${head:0:12})"; return 0; fi
  done < <(gh run list --workflow "$wf" --status success --limit 60 --json headSha --jq '.[].headSha')
  echo "NOT GREEN: no successful '$wf' run on a commit with the $part tree of ${head:0:12}" >&2; rc=1
}
case ",$PARTS," in *",backend,"*) check backend "Backend CI" ;; esac
case ",$PARTS," in *",web,"*) check web "Web CI" ;; esac
exit $rc