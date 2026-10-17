"""Venue identity repairs, from what is stored and from RAW only (0 provider requests).

    python -m scripts.repair_venue_identity            # dry run: what would change, nothing written
    python -m scripts.repair_venue_identity --apply    # write it, one audit.data_repairs row per value

Two PrediGol faults found on 5 Oct 2026 while completing /venues:

1. **Id 0 taken as a venue.** The provider sends ``"venue": {"id": 0, "name": ...}`` when it has no venue id.
   ``ensure_venues`` keyed a venue on it: one ``core.venues`` row (provider_venue_id 0) that 1,046 fixtures of 154
   different stadiums pointed at, so a Bundesliga match was shown at "Estadio Banorte, Mexico City". The fixtures
   and teams pointing at it lose the pointer (``venue_id`` NULL); the venue each fixture payload named stays on the
   fixture (``venue_name`` / ``venue_city``, revision 0065). The row itself is kept, unreferenced: history is not
   deleted.
2. **A fixture block renamed a venue.** ``ensure_venues`` overwrote a known venue's name and city with whatever a
   fixture payload called it. A venue described by /teams or /venues (``source_payload_hash``) gets back the name
   and city of the payload that described it - the file verified against its indexed hash first; one that fails is
   reported and skipped.

Every value changed is one ``audit.data_repairs`` row (before, after, why, the evidence). Nothing is deleted, RAW is
only read.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.ingestion.payload_store import PayloadStore, body_hash

RULE_ZERO = "venue_id_zero"
RULE_NAME = "venue_name_from_source"
REPO = Path(__file__).resolve().parents[1]

POINTERS_SQL = """
SELECT 'core.fixtures' AS entity, f.id, f.provider_fixture_id AS provider_ref, f.venue_id, v.provider_venue_id, v.name
  FROM core.fixtures f JOIN core.venues v ON v.id = f.venue_id WHERE v.provider_venue_id <= 0
UNION ALL
SELECT 'core.teams', t.id, t.provider_team_id, t.venue_id, v.provider_venue_id, v.name
  FROM core.teams t JOIN core.venues v ON v.id = t.venue_id WHERE v.provider_venue_id <= 0
 ORDER BY 1, 2
"""

DESCRIBED_SQL = """
SELECT v.id, v.provider_venue_id, v.name, v.city, v.source_payload_hash, p.endpoint, p.file_path
  FROM core.venues v JOIN raw.ingestion_payloads p ON p.hash = v.source_payload_hash
 WHERE v.provider_venue_id > 0
 ORDER BY v.source_payload_hash, v.id
"""


@dataclass
class Report:
    pointers: dict[str, int] = field(default_factory=dict)
    described: int = 0
    payloads_read: int = 0
    renamed: int = 0
    city_restored: int = 0
    not_in_payload: int = 0
    problems: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


def _text(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def venue_in(body: dict[str, Any], provider_venue_id: int) -> dict[str, Any] | None:
    """The venue block with this id in a /teams answer (``{"team", "venue"}`` entries) or a /venues one."""
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        block = entry.get("venue") if isinstance(entry.get("venue"), dict) else entry
        if isinstance(block, dict) and block.get("id") == provider_venue_id:
            return block
    return None


def repair(conn: psycopg.Connection[Any], raw_root: Path, *, apply: bool) -> Report:
    report = Report()
    version = code_version()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(POINTERS_SQL)
        pointers = cur.fetchall()
        for p in pointers:
            report.pointers[p["entity"]] = report.pointers.get(p["entity"], 0) + 1
            if apply:
                cur.execute(f"UPDATE {p['entity']} SET venue_id = NULL WHERE id = %s AND venue_id = %s",
                            (p["id"], p["venue_id"]))
                cur.execute(
                    "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, "
                    "after_value, reason, evidence) VALUES (%s, %s, %s, %s, 'venue_id', %s, NULL, %s, %s)",
                    (RULE_ZERO, p["entity"], p["id"], p["provider_ref"], str(p["venue_id"]),
                     "the provider's venue id 0 means 'no id': it was keyed as one venue shared by 154 stadiums; "
                     "the fixture keeps the venue its payload named (venue_name/venue_city)",
                     f"core.venues {p['venue_id']} (provider_venue_id {p['provider_venue_id']}, '{p['name']}'); "
                     f"code {version}"))
        cur.execute(DESCRIBED_SQL)
        described = cur.fetchall()
    report.described = len(described)
    store = PayloadStore(raw_root)
    bodies: dict[str, dict[str, Any] | None] = {}
    with conn.cursor() as cur:
        for v in described:
            h = str(v["source_payload_hash"])
            if h not in bodies:
                body: dict[str, Any] | None = None
                try:
                    env = store.load(str(v["file_path"]))
                    raw = env.get("body")
                    if body_hash(raw) != h:
                        report.problems.append(f"{v['file_path']}: does not re-hash to {h[:12]} - skipped")
                    elif isinstance(raw, dict):
                        body = raw
                except FileNotFoundError:
                    report.problems.append(f"{v['file_path']}: indexed but not in the raw store")
                bodies[h] = body
                report.payloads_read += 1
            body = bodies[h]
            if body is None:
                continue
            block = venue_in(body, int(v["provider_venue_id"]))
            if block is None:
                report.not_in_payload += 1
                continue
            name, city = _text(block.get("name")), _text(block.get("city"))
            changes = []
            if name is not None and name != v["name"]:
                changes.append(("name", v["name"], name))
                report.renamed += 1
            if city is not None and city != v["city"]:
                changes.append(("city", v["city"], city))
                report.city_restored += 1
            if changes and len(report.examples) < 12:
                report.examples.append(f"venue {v['provider_venue_id']}: " + "; ".join(
                    f"{f} '{a}' -> '{b}'" for f, a, b in changes))
            if apply:
                for fld, before, after in changes:
                    cur.execute(f"UPDATE core.venues SET {fld} = %s WHERE id = %s", (after, v["id"]))
                    cur.execute(
                        "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, "
                        "after_value, reason, evidence) VALUES (%s, 'core.venues', %s, %s, %s, %s, %s, %s, %s)",
                        (RULE_NAME, v["id"], v["provider_venue_id"], fld, before, after,
                         "a fixture's venue block had overwritten the venue's own name or city; restored from the "
                         "payload that described the venue",
                         f"{v['endpoint']} payload {h} ({v['file_path']}); code {version}"))
    if apply:
        conn.commit()
    else:
        conn.rollback()
    return report


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.runtime.log_level)
    ap = argparse.ArgumentParser(prog="repair_venue_identity", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    root = Path(settings.runtime.raw_store_dir)
    root = root if root.is_absolute() else REPO / root
    with psycopg.connect(settings.database.psycopg_url) as conn:
        r = repair(conn, root, apply=args.apply)
    print(f"pointers to a venue with id 0: {r.pointers or 'none'}")
    print(f"described venues: {r.described} ({r.payloads_read} source payloads read); names restored: {r.renamed}, "
          f"cities restored: {r.city_restored}, not found in their payload: {r.not_in_payload}")
    for e in r.examples:
        print("  " + e)
    for p in r.problems[:10]:
        print("  PROBLEM " + p)
    print("written" if args.apply else "dry run: re-run with --apply")
    return 1 if r.problems else 0


if __name__ == "__main__":
    sys.exit(main())
