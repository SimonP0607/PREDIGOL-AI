"""The Wikidata snapshot of stadiums (AD-H04, IA-076): which query, how it is fetched, how the file is pinned and read.

WHAT IS TAKEN. For the Wikidata items of our clubs (AD-H01, ``core.entity_ids``, system ``wikidata``, accepted), their home
venues (P115) with the statement's rank and dates, and of each venue: its labels and aliases in a few languages, coordinates
(P625), capacity (P1083), altitude (P2044), country (P17) and the place it is in (P131). Wikidata is CC0 1.0.

HOW. The full dump is ~130 GB; what is needed is a few thousand items, so the snapshot is made with FEW batched SPARQL
queries (``BATCH`` clubs each, one a minute: the public endpoint limited clients to one request a minute on 16-nov-2026), and
written ONCE to a JSON file: the query version, the time, every query's text and the raw answer. The loader never asks
Wikidata anything: it reads that file, checks its sha256 against the one given, and records the sha256 in the load. A new
snapshot is a new file and a new load; the old one stays.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ENDPOINT: Final = "https://query.wikidata.org/sparql"
QUERY_VERSION: Final = "venue-wd-v1"
LICENSE: Final = "CC0-1.0"
BATCH: Final = 200
RETRIES: Final = 4
"""Attempts per batch: the endpoint answers 429 or 5xx when it is overloaded (a 502 on 17-nov-2026); each retry waits a pause."""
PAUSE_SECONDS: Final = 65.0
USER_AGENT: Final = "predigol-venues/1 (batched stadium snapshot; one request a minute)"
LANGS: Final = ("en", "es", "pt", "fr", "de", "it", "nl", "tr", "mul")
SEP: Final = "\u001f"

QUERY: Final = """SELECT ?team ?venue ?rank ?start ?end
  (GROUP_CONCAT(DISTINCT ?coord; separator="\u001f") AS ?coords)
  (GROUP_CONCAT(DISTINCT STR(?cap); separator="\u001f") AS ?caps)
  (GROUP_CONCAT(DISTINCT STR(?elev); separator="\u001f") AS ?elevs)
  (GROUP_CONCAT(DISTINCT ?name; separator="\u001f") AS ?names)
  (GROUP_CONCAT(DISTINCT ?placeName; separator="\u001f") AS ?places)
  (GROUP_CONCAT(DISTINCT ?countryName; separator="\u001f") AS ?countries)
WHERE {{
  VALUES ?team {{ {values} }}
  ?team p:P115 ?st . ?st ps:P115 ?venue ; wikibase:rank ?rank .
  OPTIONAL {{ ?st pq:P580 ?start }}
  OPTIONAL {{ ?st pq:P582 ?end }}
  OPTIONAL {{ ?venue wdt:P625 ?coord }}
  OPTIONAL {{ ?venue wdt:P1083 ?cap }}
  OPTIONAL {{ ?venue wdt:P2044 ?elev }}
  OPTIONAL {{ ?venue rdfs:label|skos:altLabel ?name . FILTER(LANG(?name) IN ({langs})) }}
  OPTIONAL {{ ?venue wdt:P131 ?place . ?place rdfs:label ?placeName . FILTER(LANG(?placeName) IN ({langs})) }}
  OPTIONAL {{ ?venue wdt:P17 ?country . ?country rdfs:label ?countryName . FILTER(LANG(?countryName) = "en") }}
}}
GROUP BY ?team ?venue ?rank ?start ?end"""


def build_query(team_qids: Sequence[str]) -> str:
    for q in team_qids:
        if not (q.startswith("Q") and q[1:].isdigit()):
            raise ValueError(f"not a Wikidata item: {q!r}")
    langs = ", ".join(f'"{x}"' for x in LANGS)
    return QUERY.format(values=" ".join(f"wd:{q}" for q in team_qids), langs=langs)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


Poster = Callable[[str], Mapping[str, Any]]
"""query text -> the endpoint's JSON answer."""


def http_poster(*, timeout: float = 120.0) -> Poster:
    import httpx

    client = httpx.Client(timeout=timeout, follow_redirects=False,
                          headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})

    def post(query: str) -> Mapping[str, Any]:
        try:
            response = client.post(ENDPOINT, data={"query": query})
        except httpx.TimeoutException as exc:
            raise TransientError(str(exc)) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientError(f"HTTP {response.status_code}")
        response.raise_for_status()
        answer: Mapping[str, Any] = response.json()
        return answer

    return post


class TransientError(Exception):
    """The endpoint is overloaded or did not answer in time: worth another try after a pause."""


def _ask(poster: Poster, query: str, *, retries: int, pause: float, sleep: Callable[[float], None]) -> Mapping[str, Any]:
    for attempt in range(retries):
        try:
            return poster(query)
        except TransientError:
            if attempt == retries - 1:
                raise
            sleep(pause * (attempt + 1))
    raise TransientError("no attempt left")  # pragma: no cover - the loop returns or raises


def fetch_snapshot(team_qids: Iterable[str], out: Path, *, post: Poster | None = None, batch: int = BATCH,
                   pause: float = PAUSE_SECONDS, sleep: Callable[[float], None] = time.sleep,
                   retries: int = RETRIES) -> str:
    """Run the batched queries (one every ``pause`` seconds, a longer pause before a retry) and write the snapshot to
    ``out``; returns its sha256. Nothing is written unless every batch answered."""
    qids = sorted(set(team_qids), key=lambda q: int(q[1:]))
    poster = post or http_poster()
    batches: list[dict[str, Any]] = []
    for i in range(0, len(qids), batch):
        if i:
            sleep(pause)
        chunk = qids[i:i + batch]
        query = build_query(chunk)
        batches.append({"team_qids": chunk, "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                        "query": query, "answer": _ask(poster, query, retries=retries, pause=pause, sleep=sleep)})
    doc = {"query_version": QUERY_VERSION, "endpoint": ENDPOINT, "license": LICENSE,
           "fetched_at": datetime.now(UTC).isoformat(), "batches": batches}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(out)
    return sha256_of(out)


class SnapshotError(Exception):
    """The snapshot file is not the one pinned (sha256), or not of this query version."""


@dataclass(slots=True)
class WdVenue:
    qid: str
    names: set[str] = field(default_factory=set)
    places: set[str] = field(default_factory=set)
    countries: set[str] = field(default_factory=set)
    coords: set[tuple[float, float]] = field(default_factory=set)
    """(latitude, longitude) pairs: Wikidata writes ``Point(lon lat)``."""
    capacities: set[int] = field(default_factory=set)
    elevations: set[float] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class HomeStatement:
    team_qid: str
    venue_qid: str
    rank: str
    """``preferred``, ``normal`` or ``deprecated``."""
    start: str | None
    end: str | None


@dataclass(slots=True)
class Snapshot:
    sha256: str
    fetched_at: datetime
    query_version: str
    venues: dict[str, WdVenue] = field(default_factory=dict)
    homes: dict[str, list[HomeStatement]] = field(default_factory=dict)
    """team QID -> its home-venue statements."""
    teams_asked: set[str] = field(default_factory=set)


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _point(text: str) -> tuple[float, float] | None:
    t = text.strip()
    if not (t.startswith("Point(") and t.endswith(")")):
        return None
    try:
        lon, lat = (float(x) for x in t[6:-1].split())
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _split(b: Mapping[str, Any], key: str) -> list[str]:
    v = b.get(key, {}).get("value", "")
    return [x for x in str(v).split(SEP) if x.strip()]


def parse(doc: Mapping[str, Any], sha256: str) -> Snapshot:
    if doc.get("query_version") != QUERY_VERSION:
        raise SnapshotError(f"snapshot of query version {doc.get('query_version')!r}, this code reads {QUERY_VERSION!r}")
    snap = Snapshot(sha256=sha256, fetched_at=datetime.fromisoformat(str(doc["fetched_at"])),
                    query_version=QUERY_VERSION)
    for batch in doc.get("batches", []):
        snap.teams_asked.update(batch.get("team_qids", []))
        for b in batch["answer"]["results"]["bindings"]:
            team, venue = _qid(b["team"]["value"]), _qid(b["venue"]["value"])
            if not venue.startswith("Q"):
                continue
            rank = str(b["rank"]["value"]).rsplit("#", 1)[-1].replace("Rank", "").lower()
            snap.homes.setdefault(team, []).append(HomeStatement(
                team, venue, rank, b.get("start", {}).get("value"), b.get("end", {}).get("value")))
            v = snap.venues.setdefault(venue, WdVenue(venue))
            v.names.update(x.strip() for x in _split(b, "names"))
            v.places.update(x.strip() for x in _split(b, "places"))
            v.countries.update(x.strip() for x in _split(b, "countries"))
            for c in _split(b, "coords"):
                p = _point(c)
                if p:
                    v.coords.add(p)
            for c in _split(b, "caps"):
                try:
                    cap = int(float(c))
                except ValueError:
                    continue
                if cap > 0:
                    v.capacities.add(cap)
            for c in _split(b, "elevs"):
                try:
                    v.elevations.add(float(c))
                except ValueError:
                    continue
    for team in snap.homes:
        snap.homes[team].sort(key=lambda h: (h.venue_qid, h.rank, h.start or "", h.end or ""))
    return snap


def read_snapshot(path: Path, expected_sha256: str) -> Snapshot:
    digest = sha256_of(path)
    if digest != expected_sha256:
        raise SnapshotError(f"{path.name}: sha256 {digest} is not the expected {expected_sha256}")
    return parse(json.loads(path.read_text(encoding="utf-8")), digest)
