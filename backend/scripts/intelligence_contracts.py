"""The shape and version of every Intelligence contract, kept in a file so that no change of shape slips in unversioned.

AD-J01 (IA-057): an additive change raises the contract's minor version, one that breaks it raises the major (and goes with
the web in the same PR). ``tests/snapshots/intelligence_contracts.json`` keeps, for each registered contract, its version
and the facts of the JSON Schema of each projection (``fbi.api.contracts.intelligence.versioning``);
``tests/unit/test_intelligence_contract_versions.py`` fails when the code and the file disagree, and says which version the
change needs.

    python -m scripts.intelligence_contracts check
    python -m scripts.intelligence_contracts write --reason "IA-0NN: C-01 adds the scenarios (1.1.0)"

``write`` refuses without a reason, when nothing changed, and when a contract's version does not match its change.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fbi.api.contracts.intelligence.registry import CONTRACTS
from fbi.api.contracts.intelligence.versioning import (
    Bump,
    required_bump,
    schema_facts,
    version_problem,
)

SNAPSHOT = Path(__file__).resolve().parents[1] / "tests" / "snapshots" / "intelligence_contracts.json"


def current() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for spec in CONTRACTS:
        public = spec.public
        found[spec.id] = {
            "version": spec.version,
            "public": sorted(schema_facts(public.model_json_schema(mode="serialization"))) if public else None,
            "private": sorted(schema_facts(spec.private.model_json_schema(mode="serialization"))),
        }
    return found


def stored() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return data


def bump_of(old: dict[str, Any], new: dict[str, Any]) -> Bump:
    """The largest change across the two projections (a projection that appears or disappears breaks the contract)."""
    order: list[Bump] = ["none", "minor", "major"]
    worst: Bump = "none"
    for projection in ("public", "private"):
        before, after = old.get(projection), new.get(projection)
        if before is None and after is None:
            continue
        bump: Bump = "major" if before is None or after is None else required_bump(set(before), set(after))
        worst = max(worst, bump, key=order.index)
    return worst


def problems(kept: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """Why the code's contracts cannot replace the kept ones (empty: they can)."""
    found: list[str] = []
    for contract in sorted(kept.keys() - now.keys()):
        found.append(f"{contract}: kept in the snapshot but no longer registered - a contract is never removed silently")
    for contract, new in sorted(now.items()):
        old = kept.get(contract)
        if old is None:
            continue
        bump = bump_of(old, new)
        if problem := version_problem(old["version"], new["version"], bump):
            found.append(f"{contract}: {problem}")
    return found


def differences(kept: dict[str, Any], now: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for contract in sorted(kept.keys() | now.keys()):
        old, new = kept.get(contract), now.get(contract)
        if old == new:
            continue
        if old is None or new is None:
            lines.append(f"{contract}: {'new' if old is None else 'removed'}")
            continue
        if old["version"] != new["version"]:
            lines.append(f"{contract}: version {old['version']} -> {new['version']}")
        for projection in ("public", "private"):
            before, after = set(old.get(projection) or []), set(new.get(projection) or [])
            lines += [f"{contract} {projection}: - {fact}" for fact in sorted(before - after)]
            lines += [f"{contract} {projection}: + {fact}" for fact in sorted(after - before)]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["check", "write"])
    parser.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    now = current()
    kept = stored() if SNAPSHOT.exists() else {"contracts": {}, "changes": []}
    found = problems(kept["contracts"], now)
    diff = differences(kept["contracts"], now)
    if args.action == "check":
        for line in found + diff:
            print(line)
        return 1 if found or diff else 0
    if len(args.reason.strip()) < 10:
        print("a change of the snapshot needs a reason of at least 10 characters", file=sys.stderr)
        return 2
    if found:
        print("\n".join(found), file=sys.stderr)
        return 2
    if not diff:
        print("nothing changed: the snapshot is current", file=sys.stderr)
        return 2
    changes = [*kept["changes"], {"date": datetime.now(UTC).date().isoformat(), "reason": args.reason.strip()}]
    SNAPSHOT.write_text(json.dumps({"contracts": now, "changes": changes}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print("\n".join(diff))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
