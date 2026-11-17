"""The Reep v1 release PrediGol reads, pinned (AD-H01): which files, their sha256, how they are fetched and read.

Reep (reep.football, withqwerty) is a register of football identities released under CC0 1.0: each person, team, competition
and stadium has a Reep id and the ids other providers give it (``bridges``), the Wikidata item it was matched to
(``overlay_links``) and the names it goes by (``provider_aliases``, ``overlay_aliases``). IA-041 measured it on 11-nov-2026:
75.7 % of 7,800 current-squad players reach it by their exact API-Football id, 30 of 30 checked by hand.

WHAT IS TAKEN, AND WHAT IS NOT. Only identifiers and names, and only from the downloadable release: never the hosted API (it is
granted on request and paid in production), never a live query to Wikidata, never a page of Transfermarkt - its id is taken
as Reep wrote it, nothing else of it. The files are not kept in the repository (bridges alone is 179 MB compressed): the
loader downloads them on the server into a working folder, checks each against the sha256 pinned HERE, and refuses a file
that differs. A new release is a code change: its stamp and hashes are added to ``RELEASES`` and reviewed like any change.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

BASE_URL: Final = "https://data.reep.football/"
LICENSE: Final = "CC0-1.0"

FILES: Final = ("bridges", "entities", "overlay_links", "overlay_aliases", "provider_aliases", "redirects")
"""The six tables read, each as ``<name>.csv.gz``."""


@dataclass(frozen=True, slots=True)
class PinnedFile:
    key: str
    sha256: str
    bytes: int


@dataclass(frozen=True, slots=True)
class Release:
    stamp: str
    release_sha256: str
    """The sha256 of the release's ``release.json``, which lists every file with its own."""
    files: Mapping[str, PinnedFile]


RELEASES: Final[Mapping[str, Release]] = {
    "2026-10-19.1": Release(
        stamp="2026-10-19.1",
        release_sha256="9aca0c2610571c3a4d788dee4f03e47ff69064fc2fd5a878480a5c6f60668e54",
        files={
            "bridges": PinnedFile("releases/2026-10-19.1/objects/f371198a-5156-463d-9084-059386577dd6/bridges.csv.gz",
                                  "6ee5d8bc5bc25a1030ff62b47e92ae5d2ac0455953886b455a07cfa0ceb6ceea", 178_795_132),
            "entities": PinnedFile("releases/2026-10-19.1/objects/f371198a-5156-463d-9084-059386577dd6/entities.csv.gz",
                                   "ad378745a4538cec847f6f2de05bb73bc6fa19c3f23de418e2f50a66ebbbd40c", 52_514_647),
            "overlay_links": PinnedFile(
                "releases/2026-10-19.1/objects/f371198a-5156-463d-9084-059386577dd6/overlay_links.csv.gz",
                "f88bdef9565536faa9fdfb0f6c8140fe394396b7baa11187c94a6e49600b9f56", 2_755_587),
            "overlay_aliases": PinnedFile(
                "releases/2026-10-19.1/objects/f371198a-5156-463d-9084-059386577dd6/overlay_aliases.csv.gz",
                "300206473a2646e8c01ebb6053d793110ce5574191ac83f10b8f96bc6dc978dc", 25_628_453),
            "provider_aliases": PinnedFile(
                "releases/2026-10-19.1/objects/f371198a-5156-463d-9084-059386577dd6/provider_aliases.csv.gz",
                "ce2447849db75d948fbab0b5df950bbc695de2df88c215f674db21c5b71c04b2", 17_485_020),
            "redirects": PinnedFile("releases/2026-10-19.1/objects/f371198a-5156-463d-9084-059386577dd6/redirects.csv.gz",
                                    "bed068e4e4c8ea6905efa6cac901071daf944c5d65e8de4963d09bacff458e11", 235_912),
        },
    ),
}
DEFAULT_RELEASE: Final = "2026-10-19.1"


class ReleaseMismatchError(Exception):
    """A file (or the release list) does not have the sha256 pinned for it: the release is refused."""


def pinned(stamp: str) -> Release:
    try:
        return RELEASES[stamp]
    except KeyError:
        raise ReleaseMismatchError(f"release {stamp!r} is not pinned in fbi.people.identity.reep.RELEASES") from None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(folder: Path, stamp: str) -> dict[str, str]:
    """Check every file of the release in ``folder`` against its pin; the map name -> sha256 of what was checked."""
    release = pinned(stamp)
    out: dict[str, str] = {}
    listing = folder / "release.json"
    if listing.exists() and sha256_of(listing) != release.release_sha256:
        raise ReleaseMismatchError(f"release.json of {stamp} differs from the pinned sha256")
    for name in FILES:
        path = folder / f"{name}.csv.gz"
        if not path.exists():
            raise ReleaseMismatchError(f"{path.name} is missing from {folder}")
        digest = sha256_of(path)
        if digest != release.files[name].sha256:
            raise ReleaseMismatchError(f"{path.name}: sha256 {digest} is not the pinned {release.files[name].sha256}")
        out[name] = digest
    return out


def check_listing(content: bytes, stamp: str) -> None:
    """The ``release.json`` fetched must be the pinned one and list the pinned files with the pinned hashes."""
    release = pinned(stamp)
    if hashlib.sha256(content).hexdigest() != release.release_sha256:
        raise ReleaseMismatchError(f"release.json of {stamp} differs from the pinned sha256")
    listed = json.loads(content)["files"]
    for name, pin in release.files.items():
        entry = listed.get(f"{name}.csv.gz") or {}
        if entry.get("sha256") != pin.sha256 or entry.get("key") != pin.key:
            raise ReleaseMismatchError(f"release.json lists {name}.csv.gz differently from the pin")


def fetch(folder: Path, stamp: str = DEFAULT_RELEASE, *, timeout: float = 600.0) -> dict[str, str]:
    """Download the release's files into ``folder`` (skipping a file already there with the right hash), then verify."""
    import httpx

    release = pinned(stamp)
    folder.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "predigol-identity/1"}) as client:
        listing = client.get(f"{BASE_URL}releases/{stamp}/release.json")
        listing.raise_for_status()
        check_listing(listing.content, stamp)
        (folder / "release.json").write_bytes(listing.content)
        for name in FILES:
            pin = release.files[name]
            path = folder / f"{name}.csv.gz"
            if path.exists() and sha256_of(path) == pin.sha256:
                continue
            tmp = path.with_suffix(".part")
            with client.stream("GET", BASE_URL + pin.key) as response, tmp.open("wb") as out:
                response.raise_for_status()
                for chunk in response.iter_bytes(1 << 20):
                    out.write(chunk)
            if sha256_of(tmp) != pin.sha256:
                tmp.unlink()
                raise ReleaseMismatchError(f"{name}.csv.gz downloaded with another sha256 than the pinned one")
            tmp.replace(path)
    return verify(folder, stamp)


# ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────

API_NAMESPACES: Final[Mapping[str, str]] = {
    "player": "player", "coach": "coach", "manager": "coach", "team": "team", "competition": "competition",
    "venue": "venue",
}
"""API-Football namespace in Reep -> which of OUR tables the id belongs to (a coach id is a ``coach`` or a ``manager``)."""

TM_NAMESPACES: Final = frozenset({"spieler", "player", "trainer", "manager", "coach", "verein", "wettbewerb", "competition",
                                  "venue", "schiedsrichter", "referee"})
"""Transfermarkt namespaces that name an entity (not a match, a season, a stage, a transfer or an award)."""


@dataclass(frozen=True, slots=True)
class Bridge:
    reep_id: str
    reep_type: str
    confidence: float
    rule: str


@dataclass(frozen=True, slots=True)
class ExternalRef:
    system: str
    namespace: str
    external_id: str
    confidence: float
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Alias:
    text: str
    kind: str
    """The kind Reep gives (``label``, ``initial_name``, ``alias``, ``short_name``, ``official_name``, ``native_label``...)."""
    origin: str
    """``reep`` (provider_aliases) or ``wikidata`` (overlay_aliases, Wikidata's labels as Reep carries them)."""
    language: str | None
    confidence: float | None


@dataclass(slots=True)
class ReepData:
    """What the loader needs from a release: the API-Football bridges and, for the Reep ids they reach, the rest."""

    bridges: dict[tuple[str, int], list[Bridge]] = field(default_factory=lambda: defaultdict(list))
    """(our table, API-Football id) -> the Reep entities that id is bridged to (normally one)."""
    externals: dict[str, list[ExternalRef]] = field(default_factory=lambda: defaultdict(list))
    """Reep id -> its Transfermarkt ids and its Wikidata item."""
    names: dict[str, str] = field(default_factory=dict)
    """Reep id -> canonical name."""
    aliases: dict[str, list[Alias]] = field(default_factory=lambda: defaultdict(list))
    redirects: dict[str, str] = field(default_factory=dict)
    rows_read: dict[str, int] = field(default_factory=dict)

    def resolve(self, reep_id: str) -> str:
        seen = {reep_id}
        while reep_id in self.redirects:
            reep_id = self.redirects[reep_id]
            if reep_id in seen:
                break
            seen.add(reep_id)
        return reep_id


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with gzip.open(path, "rb") as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
        yield from csv.DictReader(text)


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def read(folder: Path, ours: Mapping[str, set[int]] | None = None) -> ReepData:
    """Read the release in ``folder`` (already verified): one pass over the bridges' 10.9 M rows, then the rest only for
    the Reep ids an API-Football id reaches. ``ours`` (our table -> the API-Football ids we hold) keeps only the bridges of
    our entities, which is what bounds the memory (the aliases of every Reep entity would not be needed)."""
    data = ReepData()
    for row in _rows(folder / "redirects.csv.gz"):
        if row["from_id"] and row["to_id"] and row["from_id"] != row["to_id"]:
            data.redirects[row["from_id"]] = row["to_id"]
    data.rows_read["redirects"] = len(data.redirects)

    tm: dict[str, list[ExternalRef]] = defaultdict(list)
    n = 0
    for row in _rows(folder / "bridges.csv.gz"):
        n += 1
        provider = row["provider"]
        if provider == "api_football":
            table = API_NAMESPACES.get(row["namespace"])
            if table is None or not row["external_id"].isdigit():
                continue
            if ours is not None and int(row["external_id"]) not in ours.get(table, ()):
                continue
            data.bridges[(table, int(row["external_id"]))].append(
                Bridge(data.resolve(row["reep_id"]), row["entity_type"], _float(row["confidence"]) or 0.0,
                       row["rule_id"]))
        elif provider == "transfermarkt" and row["namespace"] in TM_NAMESPACES and row["external_id"]:
            tm[data.resolve(row["reep_id"])].append(
                ExternalRef("transfermarkt", row["namespace"], row["external_id"], _float(row["confidence"]) or 0.0))
    data.rows_read["bridges"] = n
    wanted = {b.reep_id for bridges in data.bridges.values() for b in bridges}
    for reep_id in wanted:
        if reep_id in tm:
            data.externals[reep_id].extend(tm[reep_id])
    del tm

    n = 0
    for row in _rows(folder / "overlay_links.csv.gz"):
        n += 1
        reep_id = data.resolve(row["reep_id"])
        if reep_id in wanted and row["qid"].startswith("Q"):
            data.externals[reep_id].append(ExternalRef("wikidata", "", row["qid"], _float(row["confidence"]) or 0.0,
                                                       f"{row['property']}|{row['dob_check']}"))
    data.rows_read["overlay_links"] = n

    n = 0
    for row in _rows(folder / "entities.csv.gz"):
        n += 1
        if row["reep_id"] in wanted and row["canonical_name"]:
            data.names[row["reep_id"]] = row["canonical_name"]
    data.rows_read["entities"] = n

    n = 0
    for row in _rows(folder / "provider_aliases.csv.gz"):
        n += 1
        reep_id = data.resolve(row["reep_id"])
        if reep_id in wanted and row["alias"].strip():
            data.aliases[reep_id].append(Alias(row["alias"].strip(), row["alias_kind"], "reep", None, None))
    data.rows_read["provider_aliases"] = n

    n = 0
    for row in _rows(folder / "overlay_aliases.csv.gz"):
        n += 1
        reep_id = data.resolve(row["reep_id"])
        text = row["alias"].strip()
        if reep_id in wanted and text and not (text.startswith("Q") and text[1:].isdigit()):
            data.aliases[reep_id].append(Alias(text, row["name_source"], "wikidata", row["language"] or None,
                                               _float(row["confidence"])))
    data.rows_read["overlay_aliases"] = n
    return data
