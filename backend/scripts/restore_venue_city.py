"""Gives back the city of the home matches a past ``fixture_venue_city`` repair changed, once a person has checked it was wrong.

    python -m scripts.restore_venue_city --venue 1334 --venue 3220 --reason "..."          # dry run: nothing written
    python -m scripts.restore_venue_city --venue 1334 --venue 3220 --reason "..." --apply  # write it

9 Nov 2026 (review of the doubtful grounds, BE-029): ``scripts.repair_venue_city`` set the city of 97 old home matches
from the majority of the club's other matches at "the same ground". Two of those grounds are not what the rule took them
for: the LASK matches of 2019-2022 at "Raiffeisen Arena" were played in Pasching (the Linz stadium of the same name opened
in 2023), and the Independiente del Valle matches at the Estadio Banco Guayaquil are in Sangolquí, not in Quito. The
provider's own value was the right one. This puts it back:

* only the fixtures of the ``--venue`` ids given (core.venues ids), never a whole table;
* only those whose current ``venue_city`` is still the value a ``fixture_venue_city`` repair wrote (``after_value``): a
  city changed since by the provider or by hand is left alone;
* the value restored is that repair's ``before_value``, and every one is an ``audit.data_repairs`` row of its own
  (rule ``fixture_venue_city_restored``: the city it had, the city it gets, why, which repair row it undoes);
* ``scripts.repair_venue_city`` does not repair a match again while its city is the one restored here.

A second run finds nothing to do. Nothing is deleted; the repair rows being undone stay as they were.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version

RULE_REPAIR = "fixture_venue_city"
RULE_RESTORED = "fixture_venue_city_restored"

CANDIDATES_SQL = """
SELECT d.id AS repair_id, f.id AS fixture_id, f.provider_fixture_id, f.venue_id, f.venue_name, f.venue_city,
       d.before_value, d.after_value
  FROM core.fixtures f
  JOIN LATERAL (SELECT r.id, r.before_value, r.after_value FROM audit.data_repairs r
                 WHERE r.rule = %(rule)s AND r.entity = 'core.fixtures' AND r.entity_id = f.id
                   AND r.field = 'venue_city'
                 ORDER BY r.id DESC LIMIT 1) d ON true
 WHERE f.venue_id = ANY(%(venues)s)
 ORDER BY f.provider_fixture_id
"""
"""Per fixture of the venues asked, its newest ``fixture_venue_city`` repair (the one that last set the city)."""

INSERT_RESTORED = (
    "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, after_value, reason, "
    "evidence) VALUES (%s, 'core.fixtures', %s, %s, 'venue_city', %s, %s, %s, %s)")


@dataclass(frozen=True, slots=True)
class Restore:
    fixture_id: int
    provider_fixture_id: int
    venue_id: int
    venue_name: str | None
    current: str
    restored: str
    repair_id: int


@dataclass
class Plan:
    restores: list[Restore] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    written: int = 0
    problems: list[str] = field(default_factory=list)


def build_plan(conn: psycopg.Connection[Any], venue_ids: list[int]) -> Plan:
    plan = Plan()
    rows = conn.execute(CANDIDATES_SQL, {"rule": RULE_REPAIR, "venues": venue_ids}).fetchall()
    for repair_id, fixture_id, pid, venue_id, venue_name, current, before, after in rows:
        if before is None or not str(before).strip():
            plan.skipped.append(f"fixture {pid}: the repair has no value to give back")
        elif current != after:
            plan.skipped.append(f"fixture {pid}: its city is '{current}', no longer the '{after}' the repair wrote")
        else:
            plan.restores.append(Restore(int(fixture_id), int(pid), int(venue_id), venue_name, current, str(before),
                                         int(repair_id)))
    return plan


def restore(conn: psycopg.Connection[Any], venue_ids: list[int], *, reason: str, apply: bool) -> Plan:
    plan = build_plan(conn, venue_ids)
    if apply:
        version = code_version()
        with conn.cursor() as cur:
            for r in plan.restores:
                cur.execute("UPDATE core.fixtures SET venue_city = %s WHERE id = %s AND venue_city IS NOT DISTINCT FROM %s",
                            (r.restored, r.fixture_id, r.current))
                if cur.rowcount != 1:
                    plan.problems.append(f"fixture {r.provider_fixture_id}: venue_city changed since it was read - skipped")
                    continue
                cur.execute(INSERT_RESTORED, (
                    RULE_RESTORED, r.fixture_id, r.provider_fixture_id, r.current, r.restored, reason,
                    f"undoes audit.data_repairs id {r.repair_id} (rule {RULE_REPAIR}); core.venues {r.venue_id}; "
                    f"code {version}"))
                plan.written += 1
        conn.commit()
    else:
        conn.rollback()
    return plan


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.runtime.log_level)
    ap = argparse.ArgumentParser(prog="restore_venue_city", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venue", type=int, action="append", required=True, metavar="CORE_VENUE_ID",
                    help="core.venues id whose repaired matches get their city back (repeatable)")
    ap.add_argument("--reason", required=True, help="why the repair was wrong: written into every audit row")
    ap.add_argument("--apply", action="store_true", help="write it (default: dry run)")
    args = ap.parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        r = restore(conn, args.venue, reason=args.reason, apply=args.apply)
    by_pair: dict[tuple[int, str, str], int] = {}
    for x in r.restores:
        key = (x.venue_id, x.current, x.restored)
        by_pair[key] = by_pair.get(key, 0) + 1
    print(f"matches to give back their city: {len(r.restores)}; left alone: {len(r.skipped)}")
    for (venue, cur, back), n in sorted(by_pair.items()):
        print(f"  core.venues {venue}: '{cur}' -> '{back}' x{n}")
    for s in r.skipped[:20]:
        print(f"  SKIPPED {s}")
    for p in r.problems[:10]:
        print(f"  PROBLEM {p}")
    print(f"written: {r.written} value(s)" if args.apply else "dry run: nothing written; re-run with --apply")
    return 1 if r.problems else 0


if __name__ == "__main__":
    sys.exit(main())
