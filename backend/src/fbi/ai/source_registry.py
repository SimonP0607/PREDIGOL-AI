"""The registry of sources (IA-062, plan piece AD-C01): the world directory of football sources (version 2, 2.001 sources) and the
list of excluded domains, kept as VERSIONED DATA in the repository and loaded into the database by ``scripts/ia_sources_load.py``.

    config/sources/directorio_v2_2026-11-16.json   the directory: 2.001 sources, the 52 fields of each one, sorted by id (one per line)
    config/sources/exclusion_dominios_2026-11-16.csv   the domains Exa brought in 60 days of production, each with its class

Both files are PINNED: the loader reads only bytes whose sha256 is the one written here (``DIRECTORY``, ``EXCLUSION``), so a file
changed by hand is refused, and a new directory is a new file with a new pin - never an edit of this one.

What the database keeps (migration 0139, every table append-only):

* ``ai.source_registry_versions`` - one row per file loaded (its kind, name, sha256, rows and counts). The version is named after the
  content, so loading the same file twice writes nothing the second time. The newest version of each kind is the one in force.
* ``ai.source_registry`` - one row per source and version: state, family, the four permissions, the authority per type of claim, the
  date of the last review, and the whole record (``record``) as the directory wrote it.
* ``ai.domain_rules`` - one row per domain and version of the exclusion list: its class and what the policy does with it
  (``block`` for the four safe classes, ``review`` for the doubtful ones, ``none`` for the rest, which are only classified).
* ``ai.source_signoffs`` - the owner's signatures: «identified» is not «authorised», and only the owner moves a source to authorised
  (``fbi.ai.source_policy`` treats an authorised source without a signature as pending).

``ai.sources`` (402 domains, ``tiers-v1``) is NOT changed: the tier of the evidence still comes from it. ``derived_tier`` says what
tier the directory would give each domain, so the difference can be reviewed and signed before anything reads it (``ia_sources_load
tiers``)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

CONFIG_DIR: Final = Path(__file__).resolve().parents[3] / "config" / "sources"


@dataclass(frozen=True, slots=True)
class Pinned:
    kind: str
    file: str
    sha256: str
    version: str

    @property
    def path(self) -> Path:
        return CONFIG_DIR / self.file


DIRECTORY: Final = Pinned("directory", "directorio_v2_2026-11-16.json",
                          "f20a78e6e40e36e80313a25e59e49a140852eda8359aeb6a79f813462736e876", "dir-v2-2026-11-16-f20a78e6e40e")
"""The directory v2 (16-nov-2026). Its ``origin_sha256`` is the hash of the JSON the directory was delivered as; this file is the same
records, sorted by id, one per line (a test reads both ways)."""
EXCLUSION: Final = Pinned("exclusion", "exclusion_dominios_2026-11-16.csv",
                          "76212b115bf8a1858755e0fac36dc444b1962d735f49ad1a4ace774097e5fe5b", "excl-v1-2026-11-16-76212b115bf8")
"""The exclusion list (16-nov-2026): 570 rows, 559 domains (eleven domains come twice, with the same class: their counts add up)."""

STATES: Final = ("verificada_autorizada", "verificada_pendiente_derechos", "solo_referencia", "no_comprobada", "bloqueada")
FAMILIES: Final = ("A", "B", "C", "D", "E")
CLASSES: Final = ("apuestas_o_pronosticos", "resultados_sin_redaccion", "contenido_generado_o_baja_calidad", "no_futbol_u_otro",
                  "agregador_o_refrito", "dudoso", "medio_real", "oficial", "datos_reconocidos")
BLOCKED_CLASSES: Final = frozenset({"apuestas_o_pronosticos", "resultados_sin_redaccion", "contenido_generado_o_baja_calidad",
                                    "no_futbol_u_otro"})
"""The four classes blocked at once (measured in production on 16-nov-2026, 60 days, n = 9.238 results: 33,1 % of the results and
24 of the 553 useful ones). The owner signs the list; ``dudoso`` waits for review."""
REVIEW_CLASSES: Final = frozenset({"dudoso"})
AUTHORITY_LEVELS: Final = ("confirma", "informa", "solo_rumor", "sin_autoridad")
CLAIM_TYPES: Final = ("lesiones", "convocatorias", "alineaciones", "sanciones", "fichajes", "declaraciones", "resultados",
                      "calendario", "reglamento", "arbitraje", "estadisticas", "contexto", "analisis", "rumores")
"""The types of claim the directory gives authority for (``autoridad_por_afirmacion``)."""
DOMAIN_RE: Final = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class RegistryError(ValueError):
    """A file that is not the pinned one, or a record that breaks the registry's vocabulary."""


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_pinned(pin: Pinned, *, data: bytes | None = None) -> bytes:
    raw = pin.path.read_bytes() if data is None else data
    got = sha256_of(raw)
    if got != pin.sha256:
        raise RegistryError(f"{pin.file}: sha256 {got[:12]}..., pinned {pin.sha256[:12]}... (a changed file is a new version, not an edit)")
    return raw


def normalize_domain(raw: str | None) -> str | None:
    """``www.Marca.com`` -> ``marca.com``; None for what is not a host name."""
    if not raw:
        return None
    d = raw.strip().lower().rstrip(".")
    d = d.removeprefix("www.")
    return d if DOMAIN_RE.match(d) else None


def parse_authority(raw: str | None) -> dict[str, dict[str, str]]:
    """``"lesiones:informa; declaraciones:informa (cita); rumores:solo_rumor"`` -> ``{"lesiones": {"level": "informa"}, "declaraciones":
    {"level": "informa", "note": "cita"}, ...}``. A part without a known level is refused: authority is never guessed."""
    out: dict[str, dict[str, str]] = {}
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part:
            continue
        claim, sep, value = part.partition(":")
        claim, value = claim.strip(), value.strip()
        m = re.match(r"^([a-z_]+)\s*(?:\((.+)\))?$", value)
        if not sep or not claim or m is None or m.group(1) not in AUTHORITY_LEVELS:
            raise RegistryError(f"authority {part!r}: not «type:level»")
        entry = {"level": m.group(1)}
        if m.group(2):
            entry["note"] = m.group(2).strip()
        out[claim] = entry
    return out


@dataclass(frozen=True, slots=True)
class Source:
    """One source of the directory, as the policy reads it."""

    source_id: str
    domain: str
    name: str
    family: str
    source_type: str
    state: str
    automated_access: str
    ai_extraction: str
    storage: str
    publication: str
    authority: Mapping[str, Mapping[str, str]]
    last_reviewed: date | None
    country: str = ""
    official_of: str | None = None
    record: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ai_reserved(self) -> bool:
        """Robots or terms reserve the text from AI (51 + 20 in the directory), or the terms forbid automated reading (18)."""
        return self.ai_extraction.startswith("reserva_ia") or self.automated_access == "prohibido_terminos"

    def record_hash(self) -> str:
        return sha256_of(json.dumps(dict(self.record), sort_keys=True, ensure_ascii=False).encode())


def source_of(record: Mapping[str, Any]) -> Source:
    """A record of the directory, checked against the registry's vocabulary."""
    sid = str(record.get("id") or "").strip()
    domain = normalize_domain(str(record.get("dominio") or ""))
    state = str(record.get("estado_verificacion") or "")
    family = str(record.get("familia") or "")
    if not sid or domain is None:
        raise RegistryError(f"record {sid or '?'}: no id or no valid domain ({record.get('dominio')!r})")
    if state not in STATES:
        raise RegistryError(f"record {sid}: unknown state {state!r}")
    if family not in FAMILIES:
        raise RegistryError(f"record {sid}: unknown family {family!r}")
    reviewed_raw = str(record.get("fecha_ultima_revision") or "")
    try:
        reviewed = date.fromisoformat(reviewed_raw) if reviewed_raw else None
    except ValueError as exc:
        raise RegistryError(f"record {sid}: last review {reviewed_raw!r} is not a date") from exc
    kind = str(record.get("tipo") or "")
    return Source(source_id=sid, domain=domain, name=str(record.get("nombre") or sid), family=family, source_type=kind, state=state,
                  automated_access=str(record.get("permiso_acceso_automatizado") or "no_revisado"),
                  ai_extraction=str(record.get("permiso_extraccion_ia") or "no_revisado"),
                  storage=str(record.get("permiso_almacenamiento") or ""), publication=str(record.get("permiso_publicacion") or ""),
                  authority=parse_authority(str(record.get("autoridad_por_afirmacion") or "")), last_reviewed=reviewed,
                  country=str(record.get("pais") or ""), official_of=str(record.get("nombre") or sid) if kind == "oficial" else None,
                  record=dict(record))


@dataclass(frozen=True, slots=True)
class Directory:
    version: str
    sha256: str
    origin_sha256: str
    sources: tuple[Source, ...]

    def counts(self) -> dict[str, Any]:
        return {"sources": len(self.sources), "states": dict(sorted(Counter(s.state for s in self.sources).items())),
                "families": dict(sorted(Counter(s.family for s in self.sources).items())),
                "ai_reserved": sum(1 for s in self.sources if s.ai_reserved),
                "domains": len({s.domain for s in self.sources})}


def parse_directory(raw: bytes, *, version: str, sha256: str) -> Directory:
    body = json.loads(raw.decode("utf-8"))
    if body.get("format") != "predigol-source-directory/1":
        raise RegistryError(f"not a source directory: format {body.get('format')!r}")
    fields = list(body["fields"])
    rows = [dict(zip(fields, r, strict=True)) for r in body["rows"]]
    if len(rows) != int(body["count"]):
        raise RegistryError(f"{len(rows)} rows, the file says {body['count']}")
    sources = tuple(source_of(r) for r in rows)
    ids = Counter(s.source_id for s in sources)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise RegistryError(f"duplicated ids: {dup[:5]}")
    return Directory(version, sha256, str(body.get("origin_sha256") or ""), sources)


def bundled_directory() -> Directory:
    return parse_directory(read_pinned(DIRECTORY), version=DIRECTORY.version, sha256=DIRECTORY.sha256)


@dataclass(frozen=True, slots=True)
class DomainRule:
    domain: str
    domain_class: str
    action: str
    results: int = 0
    evidences: int = 0
    useful: int = 0
    reason: str = ""
    country: str = ""


def action_of(domain_class: str) -> str:
    return "block" if domain_class in BLOCKED_CLASSES else "review" if domain_class in REVIEW_CLASSES else "none"


def parse_exclusion(raw: bytes) -> tuple[DomainRule, ...]:
    """The exclusion list: one rule per domain. A domain listed twice (the eleven of the file) keeps its class - two classes for one
    domain is refused - and adds its counts."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter=";")
    merged: dict[str, DomainRule] = {}
    for row in reader:
        domain = normalize_domain(row.get("dominio"))
        klass = str(row.get("clase") or "").strip()
        if domain is None:
            raise RegistryError(f"exclusion: {row.get('dominio')!r} is not a domain")
        if klass not in CLASSES:
            raise RegistryError(f"exclusion: {domain} has unknown class {klass!r}")
        n = [int(row.get(k) or 0) for k in ("resultados", "evidencias", "utiles")]
        old = merged.get(domain)
        if old is not None and old.domain_class != klass:
            raise RegistryError(f"exclusion: {domain} has two classes ({old.domain_class}, {klass})")
        if old is None:
            merged[domain] = DomainRule(domain, klass, action_of(klass), n[0], n[1], n[2], str(row.get("motivo") or "").strip(),
                                        str(row.get("pais_probable") or "").strip())
        else:
            merged[domain] = DomainRule(domain, klass, old.action, old.results + n[0], old.evidences + n[1], old.useful + n[2],
                                        old.reason, old.country)
    return tuple(sorted(merged.values(), key=lambda r: r.domain))


def bundled_exclusion() -> tuple[DomainRule, ...]:
    return parse_exclusion(read_pinned(EXCLUSION))


def exclusion_counts(rules: Sequence[DomainRule]) -> dict[str, Any]:
    return {"domains": len(rules), "classes": dict(sorted(Counter(r.domain_class for r in rules).items())),
            "actions": dict(sorted(Counter(r.action for r in rules).items()))}


# ── what the directory would say of ai.sources' tiers (a report; nothing reads it yet) ─────────────────────────────────────────────

LEAGUE_WORDS: Final = ("liga", "league", "lega", "ligue", "bundesliga", "eredivisie", "serie a", "premier", "primeira", "superlig",
                       "mls", "dimayor", "brasileir", "j.league", "k league", "championship", "allsvenskan", "ekstraklasa", "serien",
                       "division", "divisão")
CONFEDERATIONS: Final = ("fifa", "uefa", "conmebol", "concacaf", "caf", "afc", "ofc")


def derived_tier(source: Source) -> str:
    """The tier of ``tiers-v1`` (``ai.sources``) the directory implies: an official source of a club is ``club``, of a league or
    competition ``competition``, of a federation or confederation ``official``; a data provider is ``provider``; the rest is ``media``."""
    if source.source_type == "oficial":
        scope = str(source.record.get("ambito") or "")
        if scope == "club":
            return "club"
        name = source.name.lower()
        if any(w in name.replace("(", " ").replace(")", " ").split() for w in CONFEDERATIONS) or "federa" in name:
            return "official"
        text = f"{name} {source.record.get('especialidad') or ''}".lower()
        return "competition" if any(w in text for w in LEAGUE_WORDS) and "federa" not in text else "official"
    if source.source_type == "datos":
        return "provider"
    return "media"


# ── the database (migration 0139) ─────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class LoadResult:
    kind: str
    version: str
    created: bool
    rows: int
    counts: dict[str, Any]


def _version_exists(conn: psycopg.Connection[Any], version: str) -> bool:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT 1 FROM ai.source_registry_versions WHERE version = %s", (version,))
        return cur.fetchone() is not None


def _newest(conn: psycopg.Connection[Any], kind: str) -> str | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT version FROM ai.source_registry_versions WHERE kind = %s ORDER BY loaded_at DESC, seq DESC LIMIT 1", (kind,))
        row = cur.fetchone()
    return None if row is None else str(row[0])


def load_directory(conn: psycopg.Connection[Any], directory: Directory, *, at: datetime, file_name: str, code_version: str | None = None
                   ) -> LoadResult:
    """Idempotent: a version already loaded writes nothing. Otherwise the version and its 2.001 rows in one transaction."""
    counts = directory.counts()
    if _version_exists(conn, directory.version):
        return LoadResult("directory", directory.version, False, 0, counts)
    previous = _newest(conn, "directory")
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.source_registry_versions (version, kind, file_name, file_sha256, origin_sha256, rows, counts, previous, "
                    "loaded_at, loaded_by, code_version) VALUES (%s, 'directory', %s, %s, %s, %s, %s, %s, %s, 'loader', %s)",
                    (directory.version, file_name, directory.sha256, directory.origin_sha256 or None, len(directory.sources), Jsonb(counts),
                     previous, at, code_version))
        cur.executemany(
            "INSERT INTO ai.source_registry (version, source_id, domain, name, family, source_type, country, official_of, state, "
            "automated_access, ai_extraction, storage, publication, authority, last_reviewed, record, record_sha256) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(directory.version, s.source_id, s.domain, s.name, s.family, s.source_type, s.country or None, s.official_of, s.state,
              s.automated_access, s.ai_extraction, s.storage, s.publication, Jsonb(dict(s.authority)), s.last_reviewed, Jsonb(dict(s.record)),
              s.record_hash()) for s in directory.sources])
    return LoadResult("directory", directory.version, True, len(directory.sources), counts)


def load_exclusion(conn: psycopg.Connection[Any], rules: Sequence[DomainRule], *, version: str, sha256: str, at: datetime, file_name: str,
                   code_version: str | None = None) -> LoadResult:
    counts = exclusion_counts(rules)
    if _version_exists(conn, version):
        return LoadResult("exclusion", version, False, 0, counts)
    previous = _newest(conn, "exclusion")
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.source_registry_versions (version, kind, file_name, file_sha256, rows, counts, previous, loaded_at, "
                    "loaded_by, code_version) VALUES (%s, 'exclusion', %s, %s, %s, %s, %s, %s, 'loader', %s)",
                    (version, file_name, sha256, len(rules), Jsonb(counts), previous, at, code_version))
        cur.executemany("INSERT INTO ai.domain_rules (version, domain, domain_class, action, results, evidences, useful, reason, country) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        [(version, r.domain, r.domain_class, r.action, r.results, r.evidences, r.useful, r.reason or None, r.country or None)
                         for r in rules])
    return LoadResult("exclusion", version, True, len(rules), counts)


def load_bundled(conn: psycopg.Connection[Any], *, at: datetime, code_version: str | None = None) -> list[LoadResult]:
    """What the server runs after a deploy (``python -m scripts.ia_sources_load load``): the pinned directory and exclusion list."""
    return [load_directory(conn, bundled_directory(), at=at, file_name=DIRECTORY.file, code_version=code_version),
            load_exclusion(conn, bundled_exclusion(), version=EXCLUSION.version, sha256=EXCLUSION.sha256, at=at, file_name=EXCLUSION.file,
                           code_version=code_version)]


def current_versions(conn: psycopg.Connection[Any]) -> tuple[str | None, str | None]:
    return _newest(conn, "directory"), _newest(conn, "exclusion")


SOURCE_COLUMNS: Final = ("source_id", "domain", "name", "family", "source_type", "state", "automated_access", "ai_extraction", "storage",
                         "publication", "authority", "last_reviewed", "country", "official_of")


def read_directory(conn: psycopg.Connection[Any], version: str) -> tuple[Source, ...]:
    """The sources of one loaded version, without the full record (the policy does not need it)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(f"SELECT {', '.join(SOURCE_COLUMNS)} FROM ai.source_registry WHERE version = %s ORDER BY source_id", (version,))
        rows = cur.fetchall()
    return tuple(Source(source_id=str(r[0]), domain=str(r[1]), name=str(r[2]), family=str(r[3]), source_type=str(r[4]), state=str(r[5]),
                        automated_access=str(r[6]), ai_extraction=str(r[7]), storage=str(r[8]), publication=str(r[9]),
                        authority=dict(r[10] or {}), last_reviewed=r[11], country=str(r[12] or ""), official_of=r[13]) for r in rows)


def read_rules(conn: psycopg.Connection[Any], version: str) -> tuple[DomainRule, ...]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT domain, domain_class, action, results, evidences, useful, coalesce(reason, ''), coalesce(country, '') "
                    "FROM ai.domain_rules WHERE version = %s ORDER BY domain", (version,))
        return tuple(DomainRule(str(r[0]), str(r[1]), str(r[2]), int(r[3]), int(r[4]), int(r[5]), str(r[6]), str(r[7]))
                     for r in cur.fetchall())


def signed_sources(conn: psycopg.Connection[Any]) -> frozenset[str]:
    """The sources whose NEWEST signature is an authorisation by the owner (a later ``revoke`` takes it back)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT DISTINCT ON (source_id) source_id, decision FROM ai.source_signoffs WHERE source_id IS NOT NULL "
                    "ORDER BY source_id, at DESC, id DESC")
        return frozenset(str(s) for s, d in cur.fetchall() if d == "authorize")


def sign(conn: psycopg.Connection[Any], *, source_ids: Iterable[str], decision: str, version: str, at: datetime, reason: str) -> int:
    """The owner's signature (``ia_sources_load sign ... --confirm-owner``): one row per source, never an update."""
    if decision not in ("authorize", "revoke"):
        raise RegistryError(f"unknown decision {decision!r}")
    ids = sorted(set(source_ids))
    if not ids:
        return 0
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT source_id, state FROM ai.source_registry WHERE version = %s AND source_id = ANY(%s)", (version, ids))
        found = {str(s): str(st) for s, st in cur.fetchall()}
        missing = [i for i in ids if i not in found]
        if missing:
            raise RegistryError(f"not in {version}: {missing[:5]}")
        if decision == "authorize":
            wrong = [i for i in ids if found[i] != "verificada_autorizada"]
            if wrong:
                raise RegistryError(f"only a source the directory found «verificada_autorizada» can be signed: {wrong[:5]}")
        cur.executemany("INSERT INTO ai.source_signoffs (source_id, decision, registry_version, decided_by, at, reason) "
                        "VALUES (%s, %s, %s, 'owner', %s, %s)", [(i, decision, version, at, reason) for i in ids])
    return len(ids)


def sign_exclusion(conn: psycopg.Connection[Any], *, version: str, at: datetime, reason: str) -> None:
    """The owner's signature of the exclusion list as a whole (the card asks for it; the filter does not wait for it)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.source_signoffs (source_id, decision, registry_version, decided_by, at, reason) "
                    "VALUES (NULL, 'exclusion_list', %s, 'owner', %s, %s)", (version, at, reason))


__all__ = ["BLOCKED_CLASSES", "CLAIM_TYPES", "DIRECTORY", "EXCLUSION", "STATES", "Directory", "DomainRule", "LoadResult", "Pinned",
           "RegistryError", "Source", "bundled_directory", "bundled_exclusion", "current_versions", "derived_tier", "load_bundled",
           "normalize_domain", "parse_authority", "parse_directory", "parse_exclusion", "read_directory", "read_rules", "sign",
           "sign_exclusion", "signed_sources"]
