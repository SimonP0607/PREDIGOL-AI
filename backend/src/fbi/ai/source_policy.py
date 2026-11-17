"""Access policy per source (IA-063, plan piece AD-C02): ONE place in the code decides what may be done with a page of a source.

    can_fetch(source)                  read it automatically (our own request: RSS, sitemap, API, robots respected)
    can_extract(source)                give its text to a model
    can_store(source)                  what of it may be kept: ``facts`` (extracted facts with a short quote), ``link`` (title, date,
                                       link) or ``none``
    can_publish(source, claim_type)    what of it may be shown: ``summary`` (own headline and summary, attributed), ``link`` or ``none``,
                                       and the authority of the source for that type of claim (``confirma``, ``informa``...)

``source`` is a ``Standing``: what the registry (``fbi.ai.source_registry``) says of the host of a page - its state in the directory v2,
its permissions, whether the owner signed it, and whether the exclusion list names it. The table (directory v2, section 6):

    state                          fetch  extract  store   publish
    verificada_autorizada (signed) yes    yes      facts   summary
    verificada_autorizada (not yet signed by the owner)  -> as pending
    verificada_pendiente_derechos  no     no       link    link
    solo_referencia                no     NEVER    link    link
    no_comprobada / bloqueada      no     no       none    none
    not in the directory           no     no       none    none
    excluded (exclusion list)      no     no       none    none

Three rules apply them, from the hardest:

1. **AI reservation - always, whatever the switches say.** A source whose robots or terms reserve its text from AI, whose terms forbid
   automated reading, or that the directory left as «solo referencia» (77 sources of the directory v2) NEVER reaches a model, and its text
   is not kept (in the EU that reservation removes the text-and-data-mining exception, Directive 2019/790, art. 4.3). Also when the
   registry cannot be read at all: then nothing reaches a model (closed on failure).
2. **Exclusion list - ``FBI_SOURCE_EXCLUSION``** (``enforce`` by default | ``shadow`` | ``off``). The four safe classes (betting and
   tips, results without writing, generated content, not football: 117 domains, ``exa.ai`` itself included) are taken out of Exa's
   results before anything reads them. ``shadow`` only records what it would take out; ``off`` neither takes out nor records.
3. **Only authorised sources pass - ``FBI_SOURCE_POLICY``** (``shadow`` by default | ``enforce``). Applied today it would leave the
   research with 3 sources, so by default it only RECORDS, per page, what it would have blocked and why (``ai.source_policy_log``); the
   owner signs ``enforce`` once the terms of the pending sources have been read.

Every block and every «would block» is a row of ``ai.source_policy_log`` (append-only): when, which path (``v1``, ``v2``,
``analyst``), which page, which source and state, why, and whether it was applied. The record is best effort: a database that refuses
the row (a read-only connection) never stops the research, and the decision is the same with or without the row.

Nothing here reads a key, calls a model or the web, or changes a probability, a threshold, a tier or a pick."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import tuple_row

from fbi.ai import source_registry as registry
from fbi.analyst.search import SearchResult

POLICY_ENV: Final = "FBI_SOURCE_POLICY"
EXCLUSION_ENV: Final = "FBI_SOURCE_EXCLUSION"
VERSION: Final = "source-policy-v1"

Mode = Literal["shadow", "enforce"]
ExclusionMode = Literal["off", "shadow", "enforce"]
StoreLevel = Literal["facts", "link", "none"]
PublishLevel = Literal["summary", "link", "none"]
Outcome = Literal["blocked", "would_block"]

AUTHORISED: Final = "verificada_autorizada"
UNKNOWN: Final = "desconocida"
"""The state of a host the directory does not have."""
REVIEW_STATES: Final = ("verificada_pendiente_derechos", "solo_referencia")
"""What may be kept and shown as a link (title, date, link)."""
STRICTNESS: Final = {"solo_referencia": 0, "bloqueada": 1, "no_comprobada": 2, "verificada_pendiente_derechos": 3, AUTHORISED: 4}
"""When the directory has a domain twice (8 domains: ``dimayor.com.co`` four times, ``bernama.com`` as pending and as reference...), the
strictest record decides."""
RESTRICTED_ACCESS: Final = frozenset({"restringido_robots", "prohibido_terminos"})
CLAIM_TYPE_OF: Final[dict[str, str]] = {
    # claim-v1 (research v2)
    "OUT": "lesiones", "DOUBT": "lesiones", "AVAILABLE": "lesiones", "STARTER": "alineaciones", "SUSPENSION": "sanciones",
    "COACH": "contexto", "SCHEDULE": "calendario", "VENUE": "calendario", "OTHER": "contexto",
    # the kinds of ai.evidence (research v1)
    "injury": "lesiones", "doubtful": "lesiones", "suspension": "sanciones", "lineup": "alineaciones", "coach": "contexto",
    "news": "contexto", "transfer": "fichajes", "motivation": "contexto", "weather": "contexto", "travel": "contexto",
    "schedule": "calendario", "other": "contexto",
}
"""The words of the code for a type of claim, in the directory's (``autoridad_por_afirmacion``). A directory word is taken as it is."""


def policy_mode(env: Mapping[str, str] | None = None) -> Mode:
    """``FBI_SOURCE_POLICY``: only the word ``enforce`` enforces; anything else (unset, a typo) is ``shadow``."""
    raw = (os.environ if env is None else env).get(POLICY_ENV, "")
    return "enforce" if raw.strip().lower() == "enforce" else "shadow"


def exclusion_mode(env: Mapping[str, str] | None = None) -> ExclusionMode:
    """``FBI_SOURCE_EXCLUSION``: ``off`` and ``shadow`` are the two ways back; anything else (unset, a typo) is ``enforce``."""
    raw = (os.environ if env is None else env).get(EXCLUSION_ENV, "").strip().lower()
    return "off" if raw == "off" else "shadow" if raw == "shadow" else "enforce"


def host_of(url_or_domain: str | None) -> str | None:
    if not url_or_domain:
        return None
    from urllib.parse import urlsplit

    raw = url_or_domain.strip()
    host = urlsplit(raw).hostname if "://" in raw else raw.split("/", 1)[0].split(":", 1)[0]
    return registry.normalize_domain(host or "")


def suffixes(host: str) -> list[str]:
    """``a.b.marca.com`` -> ``a.b.marca.com``, ``b.marca.com``, ``marca.com`` (never the bare top-level domain)."""
    parts = host.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


@dataclass(frozen=True, slots=True)
class Standing:
    """What the registry says of the host of a page."""

    host: str | None
    domain: str | None
    """The registered domain that matched (the most specific one), or None."""
    state: str
    source_id: str | None = None
    signed: bool = False
    ai_reserved: bool = False
    automated_access: str = "no_revisado"
    rule_class: str | None = None
    rule_action: str | None = None
    authority: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    registry_version: str | None = None

    @property
    def excluded(self) -> bool:
        return self.rule_action == "block"

    @property
    def authorised(self) -> bool:
        """Authorised by the directory AND signed by the owner, and not reserved: the only standing that passes strictly."""
        return self.state == AUTHORISED and self.signed and not self.ai_reserved and not self.excluded

    @property
    def hard_reason(self) -> str | None:
        """Why a page of this source never reaches a model, whatever the switches say."""
        if self.state == "solo_referencia" or self.ai_reserved:
            return "ai_reserved"
        return None


@dataclass(frozen=True, slots=True)
class Permission:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class Publication:
    level: PublishLevel
    claim_type: str
    authority: str
    """``confirma`` | ``informa`` | ``solo_rumor`` | ``sin_autoridad`` | ``desconocida`` (the directory does not say)."""
    note: str | None = None


def _not_authorised(source: Standing) -> str:
    if source.excluded:
        return f"excluded:{source.rule_class}"
    if source.hard_reason:
        return source.hard_reason
    if source.state == AUTHORISED and not source.signed:
        return "unsigned"
    return f"not_authorised:{source.state}"


def can_fetch(source: Standing) -> Permission:
    if source.authorised and source.automated_access not in RESTRICTED_ACCESS:
        return Permission(True, "authorised")
    return Permission(False, "robots" if source.authorised else _not_authorised(source))


def can_extract(source: Standing) -> Permission:
    return Permission(True, "authorised") if source.authorised else Permission(False, _not_authorised(source))


def can_store(source: Standing) -> StoreLevel:
    if source.authorised:
        return "facts"
    if source.excluded:
        return "none"
    if source.state in REVIEW_STATES or source.state == AUTHORISED or source.ai_reserved:
        return "link"
    return "none"


def can_publish(source: Standing, claim_type: str | None = None) -> Publication:
    word = CLAIM_TYPE_OF.get(claim_type or "", claim_type or "contexto")
    entry = source.authority.get(word) or {}
    authority = str(entry.get("level") or "desconocida")
    note = entry.get("note")
    level: PublishLevel = "summary" if source.authorised else "link" if can_store(source) == "link" else "none"
    return Publication(level, word, authority, None if note is None else str(note))


class SourcePolicy:
    """The registry as the policy reads it: the strictest record per domain, the exclusion rules, the owner's signatures."""

    def __init__(self, sources: Iterable[registry.Source], rules: Iterable[registry.DomainRule], signed: Iterable[str] = (), *,
                 directory_version: str | None, exclusion_version: str | None, origin: str) -> None:
        self.directory_version = directory_version
        self.exclusion_version = exclusion_version
        self.origin = origin
        self.signed = frozenset(signed)
        self.by_domain: dict[str, registry.Source] = {}
        for s in sources:
            old = self.by_domain.get(s.domain)
            if old is None or (s.ai_reserved, -STRICTNESS[s.state]) > (old.ai_reserved, -STRICTNESS[old.state]):
                self.by_domain[s.domain] = s
        self.rules = {r.domain: r for r in rules}

    @property
    def version(self) -> str:
        return f"{self.directory_version or '-'}+{self.exclusion_version or '-'}"

    def standing(self, url_or_domain: str | None) -> Standing:
        host = host_of(url_or_domain)
        if host is None:
            return Standing(None, None, UNKNOWN, registry_version=self.version)
        for candidate in suffixes(host):  # the most specific registered domain decides; a block rule wins a tie
            rule = self.rules.get(candidate)
            source = self.by_domain.get(candidate)
            if rule is not None and (rule.action == "block" or source is None):
                return Standing(host, candidate, "excluida" if rule.action == "block" else UNKNOWN, rule_class=rule.domain_class,
                                rule_action=rule.action, registry_version=self.version)
            if source is not None:
                return Standing(host, candidate, source.state, source.source_id, source.source_id in self.signed, source.ai_reserved,
                                source.automated_access, None if rule is None else rule.domain_class,
                                None if rule is None else rule.action, source.authority, self.version)
        return Standing(host, None, UNKNOWN, registry_version=self.version)


# ── loading: the database first, the pinned files of the image when it has no version, closed when neither ──────────────────────

_lock = threading.Lock()
_from_db: dict[tuple[str, str, frozenset[str]], SourcePolicy] = {}
_bundled: dict[str, tuple[tuple[registry.Source, ...], tuple[registry.DomainRule, ...]]] = {}


def _bundled_parts() -> tuple[tuple[registry.Source, ...], tuple[registry.DomainRule, ...]]:
    with _lock:
        if "parts" not in _bundled:
            _bundled["parts"] = (registry.bundled_directory().sources, registry.bundled_exclusion())
        return _bundled["parts"]


def load(conn: psycopg.Connection[Any] | None) -> SourcePolicy | None:
    """The policy in force: the newest loaded versions in the database; for a part the database does not have yet (before the loader
    ran, or a database without migration 0139), the pinned file of the image - the same data; None when not even those can be read (the
    caller then lets nothing reach a model)."""
    dir_v: str | None = None
    excl_v: str | None = None
    signed: frozenset[str] = frozenset()
    if conn is not None:
        try:
            with conn.transaction():
                dir_v, excl_v = registry.current_versions(conn)
                signed = registry.signed_sources(conn)
                key = (dir_v or "", excl_v or "", signed)
                with _lock:
                    cached = _from_db.get(key)
                if cached is not None:
                    return cached
                sources = registry.read_directory(conn, dir_v) if dir_v else None
                rules = registry.read_rules(conn, excl_v) if excl_v else None
        except Exception:  # a database without migration 0139, a refused query, a connection that is not one: the image's files decide
            dir_v = excl_v = None
            signed = frozenset()
            sources = rules = None
    else:
        sources = rules = None
    try:
        if sources is None or rules is None:
            b_sources, b_rules = _bundled_parts()
            if sources is None:
                sources, dir_v = b_sources, f"bundled:{registry.DIRECTORY.version}"
            if rules is None:
                rules, excl_v = b_rules, f"bundled:{registry.EXCLUSION.version}"
    except (OSError, ValueError):
        return None
    policy = SourcePolicy(sources, rules, signed, directory_version=dir_v, exclusion_version=excl_v,
                          origin="db" if not (dir_v or "").startswith("bundled") and not (excl_v or "").startswith("bundled") else "bundled")
    if conn is not None and policy.origin == "db":
        with _lock:
            _from_db.clear()  # one version in force at a time
            _from_db[(dir_v or "", excl_v or "", signed)] = policy
    return policy


def reset_cache() -> None:
    with _lock:
        _from_db.clear()
        _bundled.clear()


# ── applying it to a list of pages, and recording what it did ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Event:
    action: str
    outcome: Outcome
    reason: str
    hard: bool
    url: str
    standing: Standing


@dataclass
class Screened:
    kept: list[SearchResult]
    events: list[Event]
    mode: Mode
    exclusion: ExclusionMode
    registry_version: str

    @property
    def blocked(self) -> int:
        return sum(1 for e in self.events if e.outcome == "blocked")

    @property
    def would_block(self) -> int:
        return sum(1 for e in self.events if e.outcome == "would_block")

    def read(self, urls: Iterable[str]) -> Screened:
        """The events worth a row once the caller has chosen what it reads: every page kept away, and of the pages it would keep away
        only the ones that WERE read (a page left for a later pass is recorded when it is read, not at every pass that sees it)."""
        chosen = set(urls)
        return replace(self, events=[e for e in self.events if e.outcome == "blocked" or e.url in chosen])


def screen(policy: SourcePolicy | None, results: Sequence[SearchResult], *, mode: Mode | None = None,
           exclusion: ExclusionMode | None = None) -> Screened:
    """The pages of ``results`` that may be given to a model, in their order, and an event for each one that is - or would be - kept away.
    Pure: nothing is written (``record`` writes the events)."""
    mode = mode or policy_mode()
    exclusion = exclusion or exclusion_mode()
    kept: list[SearchResult] = []
    events: list[Event] = []
    version = "unavailable" if policy is None else policy.version
    for r in results:
        if policy is None:
            events.append(Event("extract", "blocked", "registry_unavailable", True, r.url, Standing(host_of(r.url), None, UNKNOWN)))
            continue
        st = policy.standing(r.url)
        if st.hard_reason and not st.excluded:
            events.append(Event("extract", "blocked", st.hard_reason, True, r.url, st))
            continue
        listed = st.excluded and exclusion != "off"
        if listed:
            outcome: Outcome = "blocked" if exclusion == "enforce" else "would_block"
            events.append(Event("extract", outcome, f"excluded:{st.rule_class}", False, r.url, st))
            if outcome == "blocked":
                continue
        verdict = can_extract(st)
        if not verdict.allowed and not listed:  # one event per page: an excluded page already has its own
            outcome = "blocked" if mode == "enforce" else "would_block"
            events.append(Event("extract", outcome, verdict.reason, False, r.url, st))
            if outcome == "blocked":
                continue
        kept.append(r)
    return Screened(kept, events, mode, exclusion, version)


def for_storage(policy: SourcePolicy | None, results: Sequence[SearchResult], *, mode: Mode | None = None,
                exclusion: ExclusionMode | None = None) -> list[SearchResult]:
    """What of a search may be kept in the research cache. The text of a reserved source - and of an excluded one, while the exclusion is
    not ``off`` - is never kept (its title, date and link are); with the policy in ``enforce``, the text of every source that is not
    authorised is not kept either, and a source with nothing to keep (``none``) is left out. Without a registry, only the links."""
    mode = mode or policy_mode()
    exclusion = exclusion or exclusion_mode()
    out: list[SearchResult] = []
    for r in results:
        if policy is None:
            out.append(replace(r, snippet=""))
            continue
        st = policy.standing(r.url)
        if mode == "enforce":
            level = can_store(st)
            if level == "none":
                continue
            out.append(r if level == "facts" else replace(r, snippet=""))
        elif st.hard_reason or (st.excluded and exclusion != "off"):
            out.append(replace(r, snippet=""))
        else:
            out.append(r)
    return out


INSERT_SQL: Final = ("INSERT INTO ai.source_policy_log (at, policy_version, mode, exclusion_mode, path, action, outcome, reason, hard, url, "
                     "host, domain, source_id, state, rule_class, registry_version, fixture_id) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")


def record(conn: psycopg.Connection[Any] | None, screened: Screened, *, at: datetime, path: str, fixture_id: int | None = None) -> int:
    """The events of a screening, one row each. Best effort, inside a savepoint: a connection that refuses the rows (the API's role,
    which may not write ``ai.*``) changes nothing of what the screening decided, and leaves the caller's transaction as it was."""
    if conn is None or not screened.events:
        return 0
    rows = [(at, VERSION, screened.mode, screened.exclusion, path, e.action, e.outcome, e.reason[:120], e.hard, e.url[:2000],
             e.standing.host, e.standing.domain, e.standing.source_id, e.standing.state, e.standing.rule_class, screened.registry_version,
             fixture_id) for e in screened.events]
    try:
        with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
            cur.executemany(INSERT_SQL, rows)
    except Exception:  # best effort, by design: the decision was already applied; a row that cannot be written is not a failure of it
        return 0
    return len(rows)


def guard(conn: psycopg.Connection[Any] | None, results: Sequence[SearchResult], *, at: datetime, path: str,
          fixture_id: int | None = None, policy: SourcePolicy | None = None,
          loader: Callable[[psycopg.Connection[Any] | None], SourcePolicy | None] = load) -> list[SearchResult]:
    """The one call the research paths make before a model reads pages: load the policy, screen, record, return what may be read."""
    screened = screen(policy if policy is not None else loader(conn), results)
    record(conn, screened, at=at, path=path, fixture_id=fixture_id)
    return screened.kept


__all__ = ["EXCLUSION_ENV", "POLICY_ENV", "VERSION", "Event", "Permission", "Publication", "Screened", "SourcePolicy", "Standing",
           "can_extract", "can_fetch", "can_publish", "can_store", "exclusion_mode", "for_storage", "guard", "host_of", "load",
           "policy_mode", "record", "reset_cache", "screen"]
