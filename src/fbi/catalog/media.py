"""Competition logos and country flags, read from the stored /leagues payload.

The provider's ``/leagues`` answer carries, per league, its logo and its country's
code and flag. That payload is already in the raw store (it built the catalogue), so
filling ``core.competitions.logo_url / country_code / flag_url`` costs no request.

A league the payload does not describe keeps NULL - "not told", never a guess.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ingestion.payload_store import PayloadStore

CODE_RE = re.compile(r"^[A-Z]{2}(-[A-Z]{2,3})?$")


@dataclass(frozen=True, slots=True)
class LeagueMedia:
    provider_league_id: int
    logo_url: str | None
    country_code: str | None
    flag_url: str | None


@dataclass
class MediaReport:
    payloads_read: int = 0
    leagues_described: int = 0
    competitions_updated: int = 0
    competitions_without_media: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"payloads_read": self.payloads_read, "leagues_described": self.leagues_described,
                "competitions_updated": self.competitions_updated,
                "competitions_without_media": self.competitions_without_media[:20]}


def _https(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("https://") else None


def league_media(body: dict[str, Any]) -> Iterator[LeagueMedia]:
    for item in body.get("response") or []:
        if not isinstance(item, dict):
            continue
        league = item.get("league") or {}
        country = item.get("country") or {}
        league_id = league.get("id")
        if not isinstance(league_id, int):
            continue
        code = country.get("code")
        yield LeagueMedia(
            provider_league_id=league_id,
            logo_url=_https(league.get("logo")),
            country_code=code.upper() if isinstance(code, str) and CODE_RE.match(code.upper()) else None,
            flag_url=_https(country.get("flag")),
        )


LEAGUE_PAYLOADS = """
SELECT hash, file_path, fetched_at FROM raw.ingestion_payloads
 WHERE endpoint IN ('/leagues', 'leagues') AND http_status = 200
 ORDER BY fetched_at DESC
"""


def backfill_competition_media(conn: psycopg.Connection[Any], store: PayloadStore, *, apply: bool) -> MediaReport:
    """Newest payload first: what the provider said most recently about a league wins."""
    report = MediaReport()
    media: dict[int, LeagueMedia] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LEAGUE_PAYLOADS)
        payloads = cur.fetchall()
    for p in payloads:
        try:
            envelope = store.load(str(p["file_path"]))
        except FileNotFoundError:
            continue
        report.payloads_read += 1
        body = envelope.get("body")
        if isinstance(body, dict):
            for described in league_media(body):
                media.setdefault(described.provider_league_id, described)
    report.leagues_described = len(media)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, provider_league_id, name, logo_url, country_code, flag_url FROM core.competitions")
        competitions = cur.fetchall()
    for c in competitions:
        m = media.get(int(c["provider_league_id"]))
        if m is None:
            report.competitions_without_media.append(f"{c['name']} ({c['provider_league_id']})")
            continue
        if (c["logo_url"], c["country_code"], c["flag_url"]) == (m.logo_url, m.country_code, m.flag_url):
            continue
        report.competitions_updated += 1
        if apply:
            conn.execute("UPDATE core.competitions SET logo_url = %s, country_code = %s, flag_url = %s, "
                         "updated_at = now() WHERE id = %s", (m.logo_url, m.country_code, m.flag_url, c["id"]))
    return report
