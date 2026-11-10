"""Points the matches the provider filed under another ground's id at the ground they were played at.

    python -m scripts.reassign_fixture_venue --from-venue 1334 --to-venue 9875 --city Pasching --reason "..."          # dry run
    python -m scripts.reassign_fixture_venue --from-venue 1334 --to-venue 9875 --city Pasching --reason "..." --apply  # write it

10 Nov 2026 (BE-037, grounds of the Matches module): the provider keeps one venue id for two different grounds. Id 143 is
the Raiffeisen Arena of Linz (opened in 2023) and also the LASK's ground at Pasching, which carried the same sponsor name
until then; the 88 matches of 2019-2022 (51 of the LASK, 37 of its second side) were filed under the Linz arena, and the
match page showed "Raiffeisen Arena, Pasching" with the capacity and the address of the Linz arena. ``core.venues`` already
holds both grounds (the provider has a record for each); only the association of those matches was wrong. This moves it:

* only the matches filed under ``--from-venue`` (a core.venues id) whose own city is ``--city`` (the city their payload names,
  compared as everywhere else: case, accents and punctuation aside), never a whole table;
* only when the check below agrees: the ground the matches are filed under is NOT in that city and the ground they go to is;
  anything else is refused with the reason and nothing is written (the id is not a safe witness by itself: this tool does not
  move a match between two grounds of the same city, nor into a ground of another one);
* every match moved is an ``audit.data_repairs`` row of its own (rule ``fixture_venue_reassigned``, field ``venue_id``: the id it
  had, the id it gets, why, which provider ids are involved), and the sync keeps the new id while the provider's payload repeats
  the id it replaced (``fbi.ingestion.fixtures.KEEP_REASSIGNED_VENUE_SQL``): the next /fixtures refresh does not undo it. A venue
  id the provider changes later is taken as before;
* the match keeps the name and the city its payload gave: nothing is rewritten but the association.

A second run finds nothing to do. Nothing is deleted and no ground is created or changed: the rows of the matches are the only
ones touched. To undo it, set ``venue_id`` back to each row's ``before_value`` (the audit rows say which).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.places import cities_compatible, place_key
from fbi.core.version import code_version

RULE = "fixture_venue_reassigned"

VENUES_SQL = "SELECT id, provider_venue_id, name, city FROM core.venues WHERE id = ANY(%s)"

CANDIDATES_SQL = """
SELECT f.id, f.provider_fixture_id, f.venue_name, f.venue_city, f.kickoff_at::date
  FROM core.fixtures f
 WHERE f.venue_id = %s
 ORDER BY f.kickoff_at, f.id
"""

INSERT_REASSIGNED = (
    "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, after_value, reason, "
    "evidence) VALUES (%s, 'core.fixtures', %s, %s, 'venue_id', %s, %s, %s, %s)")


@dataclass(frozen=True, slots=True)
class Venue:
    id: int
    provider_venue_id: int | None
    name: str | None
    city: str | None

    def label(self) -> str:
        return f"core.venues {self.id} ({self.name}, {self.city}; provider id {self.provider_venue_id})"


@dataclass(frozen=True, slots=True)
class Move:
    fixture_id: int
    provider_fixture_id: int
    venue_name: str | None
    city: str
    day: Any


@dataclass
class Plan:
    source: Venue | None = None
    target: Venue | None = None
    moves: list[Move] = field(default_factory=list)
    left: int = 0
    refused: list[str] = field(default_factory=list)
    written: int = 0
    problems: list[str] = field(default_factory=list)


def _venues(conn: psycopg.Connection[Any], ids: list[int]) -> dict[int, Venue]:
    return {int(r[0]): Venue(int(r[0]), None if r[1] is None else int(r[1]), r[2], r[3])
            for r in conn.execute(VENUES_SQL, (ids,)).fetchall()}


def build_plan(conn: psycopg.Connection[Any], source_id: int, target_id: int, city: str) -> Plan:
    plan = Plan()
    key = place_key(city)
    if not key:
        plan.refused.append("--city is empty")
    if source_id == target_id:
        plan.refused.append("--from-venue and --to-venue are the same ground")
    found = _venues(conn, [source_id, target_id])
    plan.source, plan.target = found.get(source_id), found.get(target_id)
    for label, ground, wanted in (("--from-venue", plan.source, source_id), ("--to-venue", plan.target, target_id)):
        if ground is None:
            plan.refused.append(f"{label} core.venues {wanted} does not exist")
    if plan.refused or plan.source is None or plan.target is None:
        return plan
    if not place_key(plan.target.city) or not cities_compatible(plan.target.city, city):
        plan.refused.append(f"the ground they would go to, {plan.target.label()}, is not in '{city}'")
    if not place_key(plan.source.city) or cities_compatible(plan.source.city, city):
        plan.refused.append(f"the ground they are filed under, {plan.source.label()}, is not shown to be in another "
                            f"city than '{city}': nothing says the association is wrong")
    if plan.refused:
        return plan
    for fixture_id, provider_id, venue_name, venue_city, day in conn.execute(CANDIDATES_SQL, (source_id,)).fetchall():
        if place_key(venue_city) == key:
            plan.moves.append(Move(int(fixture_id), int(provider_id), venue_name, str(venue_city), day))
        else:
            plan.left += 1
    return plan


def reassign(conn: psycopg.Connection[Any], source_id: int, target_id: int, city: str, *, reason: str,
             apply: bool) -> Plan:
    plan = build_plan(conn, source_id, target_id, city)
    if apply and plan.moves and not plan.refused and plan.source is not None and plan.target is not None:
        version = code_version()
        with conn.cursor() as cur:
            for m in plan.moves:
                cur.execute("UPDATE core.fixtures SET venue_id = %s WHERE id = %s AND venue_id = %s",
                            (target_id, m.fixture_id, source_id))
                if cur.rowcount != 1:
                    plan.problems.append(f"fixture {m.provider_fixture_id}: its venue changed since it was read - skipped")
                    continue
                cur.execute(INSERT_REASSIGNED, (
                    RULE, m.fixture_id, m.provider_fixture_id, str(source_id), str(target_id), reason,
                    f"payload names '{m.venue_name}' in '{m.city}'; {plan.source.label()} -> {plan.target.label()}; "
                    f"code {version}"))
                plan.written += 1
        conn.commit()
    else:
        conn.rollback()
    return plan


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.runtime.log_level)
    ap = argparse.ArgumentParser(prog="reassign_fixture_venue", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-venue", type=int, required=True, metavar="CORE_VENUE_ID",
                    help="core.venues id the matches are filed under now")
    ap.add_argument("--to-venue", type=int, required=True, metavar="CORE_VENUE_ID",
                    help="core.venues id of the ground they were played at")
    ap.add_argument("--city", required=True, help="the city of those matches (and of the ground they go to)")
    ap.add_argument("--reason", required=True, help="why the association was wrong: written into every audit row")
    ap.add_argument("--apply", action="store_true", help="write it (default: dry run)")
    args = ap.parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        r = reassign(conn, args.from_venue, args.to_venue, args.city, reason=args.reason, apply=args.apply)
    for why in r.refused:
        print(f"REFUSED {why}")
    if r.refused:
        print("nothing written")
        return 2
    first = min((m.day for m in r.moves), default=None)
    last = max((m.day for m in r.moves), default=None)
    print(f"matches to point at {r.target.label() if r.target else '?'}: {len(r.moves)}"
          f" ({first} to {last}); left under {r.source.label() if r.source else '?'}: {r.left}")
    for m in r.moves[:5]:
        print(f"  fixture {m.provider_fixture_id} {m.day} '{m.venue_name}', {m.city}")
    for p in r.problems[:10]:
        print(f"  PROBLEM {p}")
    print(f"written: {r.written} value(s)" if args.apply else "dry run: nothing written; re-run with --apply")
    return 1 if r.problems else 0


if __name__ == "__main__":
    sys.exit(main())
