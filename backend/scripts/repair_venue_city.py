"""Venue city repairs for the grounds the venue control flags, from RAW only (0 provider requests).

    python -m scripts.repair_venue_city                 # dry run: what would change, nothing written
    python -m scripts.repair_venue_city --venue 80      # only core.venues 80 (the id GET /matches/{id} shows)
    python -m scripts.repair_venue_city --apply         # write it, one audit.data_repairs row per value

7 Nov 2026 (plan of the Matches module, C1): Valencia v Real Madrid showed "Estadio de Mestalla, Valdivia". The
control (``fbi.truth.venues``, part of the truth audit) says which grounds have a city their evidence contradicts;
this script proposes, and with ``--apply`` writes, the correction that evidence supports - nothing else:

1. ``venue_city_from_provider`` - ``core.venues.city`` of a flagged ground whose newest stored provider record of the
   venue (``/venues?id``, ``/teams?id`` of a club whose ground it is, or the payload the row was written from; the
   file re-hashed against its index first) names another city: that city. Not when most of the fixture payloads
   that name the ground contradict that record as well: then it is listed as undecided and nothing is written.
2. ``fixture_venue_city`` - ``core.fixtures.venue_city`` of a home match the control flags (its payload names the
   club's ground in a city fewer of the club's home matches there give than give the ground's city): the city those
   matches give. The match page shows a fixture's own city first, so the venue's alone would not change it.

Undecided grounds are printed with their evidence: the provider's own record says the stored city (to be reported to
the provider: correcting it by hand would be undone by the next /venues or /teams refresh), or no stored payload names
a city. Nothing is deleted, RAW is only read; every value changed is one ``audit.data_repairs`` row (before, after,
why, the evidence). A second run finds nothing to do.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.places import cities_compatible, place_key
from fbi.core.version import code_version
from fbi.storage.payload_store import PayloadStore
from fbi.truth.venues import CityVerdict, Ground, collect, judge_city, odd_fixtures, reference_city

RULE_VENUE = "venue_city_from_provider"
RULE_FIXTURE = "fixture_venue_city"
REPO = Path(__file__).resolve().parents[1]

INSERT_REPAIR = (
    "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, after_value, reason, "
    "evidence) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)")


@dataclass(frozen=True, slots=True)
class VenueFix:
    venue_id: int
    provider_venue_id: int | None
    label: str
    before: str | None
    after: str
    evidence: str


@dataclass(frozen=True, slots=True)
class FixtureFix:
    provider_fixture_id: int
    label: str
    before: str
    after: str
    evidence: str


@dataclass
class Plan:
    grounds: int = 0
    flagged: int = 0
    venues: list[VenueFix] = field(default_factory=list)
    fixtures: list[FixtureFix] = field(default_factory=list)
    undecided: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    written: int = 0


def _fixtures_contradict(g: Ground, city: str) -> bool:
    """Most fixture payloads that name the ground give a city incompatible with ``city``."""
    named = sum(fc.n for fc in g.fixture_cities)
    agree = sum(fc.n for fc in g.fixture_cities if cities_compatible(fc.city, city))
    return named > 0 and 2 * agree < named


def plan_ground(g: Ground, verdict_city: CityVerdict, plan: Plan) -> None:
    """What the evidence supports for one ground (``verdict_city``: its ``judge_city`` verdict)."""
    p = g.provider
    if verdict_city.finding is not None:
        plan.flagged += 1
        if verdict_city.provider_disagrees and p is not None and p.city:
            if _fixtures_contradict(g, p.city):
                plan.undecided.append(f"{g.label}: stored '{g.city}', the provider's record ({p.source()}) says "
                                      f"'{p.city}', but most fixture payloads naming the ground say otherwise")
            else:
                plan.venues.append(VenueFix(g.venue_id, g.provider_venue_id, g.label, g.city, p.city,
                                            f"{p.source()} ({p.file_path})"))
        elif p is not None and p.city:
            plan.undecided.append(f"{g.label}: stored '{g.city}', and the provider's own record ({p.source()}) says "
                                  f"the same; {verdict_city.finding.note}")
        else:
            plan.undecided.append(f"{g.label}: stored '{g.city}', no stored provider record names a city; "
                                  f"{verdict_city.finding.note}")
    for odd in odd_fixtures(g, reference_city(g, verdict_city)):
        plan.fixtures.append(FixtureFix(
            odd.provider_fixture_id, f"fixture {odd.provider_fixture_id} at {g.label}", odd.city, odd.expected,
            f"{odd.others} other home matches of the club at {g.label} name '{odd.expected}'"
            + (f"; the provider's record of the venue: {p.source()}" if p is not None else "")))


def build_plan(conn: psycopg.Connection[Any], store: PayloadStore, venue_ids: list[int] | None = None) -> Plan:
    got = collect(conn, store, venue_ids=venue_ids)
    plan = Plan(grounds=len(got.grounds), problems=list(got.problems))
    for g in got.grounds:
        plan_ground(g, judge_city(g, got.atlas), plan)
    return plan


def repair(conn: psycopg.Connection[Any], raw_root: Path, *, apply: bool,
           venue_ids: list[int] | None = None) -> Plan:
    plan = build_plan(conn, PayloadStore(raw_root), venue_ids)
    version = code_version()
    if apply:
        with conn.cursor() as cur:
            for v in plan.venues:
                cur.execute("UPDATE core.venues SET city = %s WHERE id = %s AND city IS NOT DISTINCT FROM %s",
                            (v.after, v.venue_id, v.before))
                if cur.rowcount != 1:
                    plan.problems.append(f"{v.label}: city changed since it was read - skipped")
                    continue
                cur.execute(INSERT_REPAIR, (
                    RULE_VENUE, "core.venues", v.venue_id, v.provider_venue_id, "city", v.before, v.after,
                    "the venue control (fbi.truth.venues) found the stored city contradicted; restored from the "
                    "newest stored provider record of the venue", f"{v.evidence}; code {version}"))
                plan.written += 1
            for f in plan.fixtures:
                cur.execute("UPDATE core.fixtures SET venue_city = %s WHERE provider_fixture_id = %s "
                            "AND venue_city IS NOT DISTINCT FROM %s RETURNING id",
                            (f.after, f.provider_fixture_id, f.before))
                row = cur.fetchone()
                if row is None:
                    plan.problems.append(f"{f.label}: venue_city changed since it was read - skipped")
                    continue
                cur.execute(INSERT_REPAIR, (
                    RULE_FIXTURE, "core.fixtures", int(row[0]), f.provider_fixture_id, "venue_city", f.before,
                    f.after, "the venue control (fbi.truth.venues) found this home match's city given by no other "
                    "home match of the club at its ground; set to the city those matches give", f"{f.evidence}; "
                    f"code {version}"))
                plan.written += 1
        conn.commit()
    else:
        conn.rollback()
    return plan


def _show(v: str | None) -> str:
    return "NULL" if v is None or not place_key(v) else f"'{v}'"


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.runtime.log_level)
    ap = argparse.ArgumentParser(prog="repair_venue_city", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the corrections (default: dry run)")
    ap.add_argument("--venue", type=int, action="append", metavar="CORE_VENUE_ID",
                    help="only this core.venues id (repeatable)")
    args = ap.parse_args(argv)
    root = Path(settings.runtime.raw_store_dir)
    root = root if root.is_absolute() else REPO / root
    with psycopg.connect(settings.database.psycopg_url) as conn:
        r = repair(conn, root, apply=args.apply, venue_ids=args.venue)
    print(f"grounds checked: {r.grounds}; city contradicted: {r.flagged}; venue cities to restore: {len(r.venues)}; "
          f"fixture cities to set: {len(r.fixtures)}; undecided: {len(r.undecided)}")
    for v in r.venues:
        print(f"  VENUE   {v.label}: city {_show(v.before)} -> '{v.after}'  [{v.evidence}]")
    for f in r.fixtures:
        print(f"  FIXTURE {f.label}: venue_city {_show(f.before)} -> '{f.after}'  [{f.evidence}]")
    for u in r.undecided:
        print(f"  UNDECIDED {u}")
    for p in r.problems[:10]:
        print(f"  PROBLEM {p}")
    print(f"written: {r.written} value(s)" if args.apply else "dry run: nothing written; re-run with --apply")
    return 1 if r.problems else 0


if __name__ == "__main__":
    sys.exit(main())
