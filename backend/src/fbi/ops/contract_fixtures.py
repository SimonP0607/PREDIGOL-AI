"""Extract sanitised provider payloads from the raw store, as test fixtures.

A normaliser tested only against hand-written JSON is tested against what we
BELIEVE the provider sends. Two faults this session came from exactly that gap:
Asian Handicap's sign, and the in-play bet namespace. Both were found by reading
real payloads, not by reading documentation.

So the contract tests get real ones - trimmed to a couple of entries per payload so
the repository stays small, and sanitised so nothing secret or personal can ride
along. And because they are files, the tests have **no Internet dependency**: they
keep working when the provider is down, when the plan changes, and in CI.

What sanitising removes:
  * the whole ``params`` block of the stored envelope, keeping only the endpoint.
    The raw store already strips the API key (it travels as a header), and this
    removes any query value as well, belt and braces;
  * every key whose name suggests a credential, anywhere in the body;
  * long logo and image URLs, which are noise.

What it deliberately KEEPS: ids, names, scores, odds, coverage flags, statistic
type strings. Those ARE the contract - a fixture with the names changed would test
nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.storage.payload_store import PayloadStore

log = structlog.get_logger(__name__)

SECRET_KEY_PATTERN = re.compile(
    r"key|token|secret|password|passwd|authorization|auth|credential|bearer|session|cookie",
    re.IGNORECASE,
)
REDACTED = "[REDACTED]"
URL_KEYS = frozenset({"logo", "flag", "photo", "image"})

MAX_ENTRIES = 2
"""Entries kept from each payload's ``response`` list. Enough to test a list and a
pair; small enough that the fixtures are readable in a diff."""


@dataclass
class ExtractReport:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    redactions: int = 0
    bytes_written: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"written": self.written, "skipped": self.skipped, "redactions": self.redactions,
                "bytes_written": self.bytes_written}


def sanitise(value: Any, report: ExtractReport) -> Any:
    """Walk the body, redacting anything that looks like a credential."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, inner in value.items():
            if SECRET_KEY_PATTERN.search(str(key)):
                out[str(key)] = REDACTED
                report.redactions += 1
                continue
            if str(key).lower() in URL_KEYS and isinstance(inner, str):
                out[str(key)] = f"https://example.invalid/{key}.png"
                continue
            out[str(key)] = sanitise(inner, report)
        return out
    if isinstance(value, list):
        return [sanitise(v, report) for v in value]
    return value


def trim(body: dict[str, Any], *, max_entries: int = MAX_ENTRIES) -> dict[str, Any]:
    """Keep the payload's shape and the first couple of entries.

    ``results`` is rewritten to the trimmed length on purpose: a fixture claiming
    380 results while carrying two would be a lie about the provider, and some
    normalisers compare the two.
    """
    out = dict(body)
    response = out.get("response")
    if isinstance(response, list) and len(response) > max_entries:
        out["response"] = response[:max_entries]
        out["results"] = len(out["response"])
        out["_trimmed_from"] = len(response)
    return out


def extract(
    conn: psycopg.Connection,
    raw_root: Path,
    out_dir: Path,
    *,
    endpoints: dict[str, str],
    max_entries: int = MAX_ENTRIES,
) -> ExtractReport:
    """One fixture per named endpoint: ``{name: SQL predicate on params}``.

    The predicate picks WHICH payload of that endpoint to take, so a caller can ask
    for "the /fixtures payload that used ids" rather than whichever came first.
    """
    report = ExtractReport()
    store = PayloadStore(raw_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in endpoints.items():
        endpoint, _, predicate = spec.partition("|")
        sql = ("SELECT hash, endpoint, params, fetched_at, http_status, results_count, file_path "
               "FROM raw.ingestion_payloads WHERE endpoint = %s AND http_status = 200 ")
        if predicate:
            sql += f"AND {predicate} "
        sql += "ORDER BY results_count DESC, fetched_at DESC LIMIT 1"
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (endpoint,))
            row = cur.fetchone()
        if row is None:
            report.skipped.append(f"{name}: no stored payload for {endpoint}")
            continue
        try:
            envelope = store.load(str(row["file_path"]))
        except FileNotFoundError:
            report.skipped.append(f"{name}: {row['file_path']} is indexed but not in the store")
            continue
        body = envelope.get("body")
        if not isinstance(body, dict):
            report.skipped.append(f"{name}: the stored body is not an object")
            continue
        fixture = {
            "_source": {
                "endpoint": str(row["endpoint"]),
                "payload_sha256": str(row["hash"]),
                "fetched_at": row["fetched_at"].isoformat(),
                "http_status": int(row["http_status"]),
                "results_in_full_payload": int(row["results_count"]),
                "note": "Trimmed and sanitised from our own raw store. Params are NOT kept.",
            },
            "body": sanitise(trim(body, max_entries=max_entries), report),
        }
        path = out_dir / f"{name}.json"
        text = json.dumps(fixture, indent=1, sort_keys=False, ensure_ascii=False) + "\n"
        path.write_text(text)
        report.written.append(str(path.name))
        report.bytes_written += len(text.encode())
    log.info("contract_fixtures.extracted", **report.as_dict())
    return report


DEFAULT_ENDPOINTS: dict[str, str] = {
    "fixtures_by_league_season": "/fixtures|NOT (params ? 'ids') AND params ? 'league'",
    "fixture_details_ids": "/fixtures|params ? 'ids'",
    "fixtures_by_date": "/fixtures|params ? 'date'",
    "odds_prematch": "/odds|params ? 'fixture'",
    "odds_live_bets": "/odds/live/bets|true",
    "leagues_coverage": "/leagues|true",
    "standings": "/standings|true",
    "injuries": "/injuries|true",
    "teams": "/teams|true",
}
