"""Which external id belongs to which of our entities, and what waits for a person (AD-H01, ``entid-v1``). Pure functions.

THE RULES (Doc 3, §Perfiles de jugadores e identidad entre fuentes), from the input to the rows
-------------------------------------------------------------------------------------------------
1. **Only by id.** An entity of ours reaches Reep through the API-Football id we already store (``provider_player_id``,
   ``provider_team_id``...) and a bridge of the pinned release. A name never links anything by itself: there is no rule here
   that looks a name up.
2. **One id, one entity.** An API-Football id that Reep bridges to two Reep entities links nothing and goes to the queue
   (``bridge_conflict``). An external id (Reep, Wikidata, Transfermarkt) that two of OUR entities would get goes to the queue
   for both (``shared_external``) and is linked to neither until a person decides: it is usually the provider holding one
   person under two ids, sometimes a wrong bridge.
3. **Minors are not linked.** A player whose birth date says he is under 18 on the day of the load gets nothing (Reep itself
   withholds 9,116 known minors from v1).
4. **The name must not contradict the id.** The names on both sides have to share a surname (or an initial and a surname for
   ``M. Salah``); if they do not, the link is stored as ``pending`` and queued (``name_mismatch``). A team, competition or
   stadium is compared without the words every club has.
5. **Externals ride on the Reep link.** The Wikidata item and the Transfermarkt ids are the ones Reep has for that Reep
   entity, with confidence = bridge x link; a pending Reep link makes them pending too.

HOMONYMS (``plan_homonyms``). Two of our players with the same name are two people unless something else says otherwise:
13,456 names are repeated among 196,445 players (production, 16-nov-2026). Only two cases go to a person: the same name and
the same birth date (``possible_duplicate``: the provider may hold one man twice), and the same name with birth dates 1 to 5
days apart (``near_birth_date``: a typing error, or two people). Twins (same surname and birth date, other given names) and a
father and son (same name, a generation apart) are never queued.

Everything is deterministic: the order of the input does not change the output.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from fbi.people.identity import names as nm
from fbi.people.identity.reep import Alias, ReepData

VERSION: Final = "entid-v1"

ENTITY_TYPES: Final = ("player", "team", "coach", "competition", "referee", "venue")
PERSONS: Final = frozenset({"player", "coach", "referee"})
SYSTEMS: Final = ("reep", "wikidata", "transfermarkt")
ALIAS_TYPES: Final = ("official", "full", "short", "code", "nickname", "transliteration", "localized", "former",
                      "alternative")
QUEUE_KINDS: Final = ("bridge_conflict", "shared_external", "name_mismatch", "possible_duplicate", "near_birth_date")
MINOR_AGE: Final = 18
NEAR_DAYS: Final = 5

_REEP_KIND: Final[Mapping[str, str]] = {"official_name": "official", "label": "full", "initial_name": "short",
                                        "short_name": "short", "alias": "alternative", "canonical": "full"}


@dataclass(frozen=True, slots=True)
class Ours:
    """One of our entities as the rules see it."""

    entity_type: str
    entity_id: int
    provider_id: int | None
    names: tuple[str, ...]
    """The provider's name first, then the others we hold (first and last name)."""
    birth_date: date | None = None
    firstname: str | None = None


@dataclass(frozen=True, slots=True)
class IdRow:
    entity_type: str
    entity_id: int
    system: str
    namespace: str
    external_id: str
    method: str
    """``exact_bridge`` (API-Football id -> Reep) or ``bridge_chain`` (Reep -> Wikidata / Transfermarkt)."""
    confidence: float
    review: str
    """``accepted`` or ``pending`` (waits for a person)."""
    evidence: Mapping[str, object] = field(default_factory=dict)

    @property
    def link_key(self) -> tuple[str, int, str, str, str]:
        return (self.entity_type, self.entity_id, self.system, self.namespace, self.external_id)

    @property
    def row_key(self) -> str:
        return digest(*self.link_key, self.review)


@dataclass(frozen=True, slots=True)
class QueueItem:
    kind: str
    entity_type: str
    entity_a: int
    entity_b: int | None
    system: str | None
    namespace: str | None
    external_id: str | None
    score: float
    evidence: Mapping[str, object] = field(default_factory=dict)

    @property
    def item_key(self) -> str:
        if self.entity_b is not None:  # a pair is one question whatever external raised it
            return f"{self.kind}:{self.entity_type}:{self.entity_a}:{self.entity_b}"
        return f"{self.kind}:{self.entity_type}:{self.entity_a}:{self.system}:{self.namespace}:{self.external_id}"


@dataclass(frozen=True, slots=True)
class AliasRow:
    entity_type: str
    entity_id: int
    alias: str
    alias_key: str
    alias_type: str
    languages: tuple[str, ...]
    script: str
    source: str
    source_detail: str
    via_external: str | None
    """The Reep id the alias came through: it is shown only while that link is accepted. None for our own names."""
    confidence: float | None = None

    @property
    def row_key(self) -> str:
        return digest(self.entity_type, self.entity_id, self.alias, self.alias_type, self.source, self.source_detail,
                      self.via_external or "")


@dataclass(slots=True)
class Plan:
    ids: list[IdRow] = field(default_factory=list)
    queue: list[QueueItem] = field(default_factory=list)
    aliases: list[AliasRow] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:32]


def age_on(birth: date, day: date) -> int:
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def is_minor(entity: Ours, day: date) -> bool:
    return entity.entity_type == "player" and entity.birth_date is not None and age_on(entity.birth_date, day) < MINOR_AGE


def reep_names(data: ReepData, reep_id: str) -> list[str]:
    out = [data.names[reep_id]] if reep_id in data.names else []
    out += [a.text for a in data.aliases.get(reep_id, ()) if a.origin == "reep"
            or nm.script_of(a.text) == "latin"]
    return out


def alias_rows(entity: Ours, reep_id: str, canonical: str | None, aliases: Sequence[Alias]) -> list[AliasRow]:
    """The names a Reep entity brings to one of ours, one row per (text, type): languages merged, the best confidence."""
    merged: dict[tuple[str, str, str], tuple[set[str], float | None]] = {}
    items: list[tuple[str, str, str, str | None, float | None]] = []
    if canonical:
        items.append((canonical, "full", "reep", None, None))
    for a in aliases:
        if a.origin == "reep":
            items.append((a.text, _REEP_KIND.get(a.kind, "alternative"), "reep", a.language, a.confidence))
        else:
            kind = "official" if a.kind == "official_name" else (
                "localized" if nm.script_of(a.text) == "latin" else "transliteration")
            items.append((a.text, kind, "wikidata", a.language, a.confidence))
    for text, kind, source, language, confidence in items:
        if not nm.alias_key(text):
            continue
        langs, best = merged.get((text, kind, source), (set(), None))
        if language:
            langs.add(language)
        if confidence is not None:
            best = confidence if best is None else max(best, confidence)
        merged[(text, kind, source)] = (langs, best)
    return [AliasRow(entity.entity_type, entity.entity_id, text, nm.alias_key(text), kind, tuple(sorted(langs)),
                     nm.script_of(text), source, "", reep_id, conf)
            for (text, kind, source), (langs, conf) in sorted(merged.items())]


def plan_links(entities: Iterable[Ours], data: ReepData, *, as_of: date) -> Plan:
    """Rules 1-5 over our entities and a release: the id rows, the queue, the aliases they bring."""
    plan = Plan()
    candidates: list[IdRow] = []
    entity_aliases: dict[tuple[str, int], list[AliasRow]] = {}
    for entity in sorted(entities, key=lambda e: (e.entity_type, e.entity_id)):
        plan.stats[f"{entity.entity_type}:entities"] += 1
        if entity.provider_id is None:
            continue
        bridges = data.bridges.get((entity.entity_type, entity.provider_id), [])
        if not bridges:
            plan.stats[f"{entity.entity_type}:unbridged"] += 1
            continue
        reep_ids = sorted({b.reep_id for b in bridges})
        if len(reep_ids) > 1:
            plan.stats[f"{entity.entity_type}:bridge_conflict"] += 1
            plan.queue.append(QueueItem("bridge_conflict", entity.entity_type, entity.entity_id, None, "reep", "",
                                        ",".join(reep_ids), 0.5, {"api_football": entity.provider_id,
                                                                  "reep_ids": reep_ids}))
            continue
        if is_minor(entity, as_of):
            plan.stats[f"{entity.entity_type}:withheld_minor"] += 1
            continue
        reep_id = reep_ids[0]
        bridge = max((b for b in bridges if b.reep_id == reep_id), key=lambda b: (b.confidence, b.rule))
        theirs = reep_names(data, reep_id)
        compatible = not theirs or nm.names_compatible(entity.names, theirs, person=entity.entity_type in PERSONS)
        review = "accepted" if compatible else "pending"
        evidence: dict[str, object] = {"api_football": entity.provider_id, "rule": bridge.rule,
                                       "reep_type": bridge.reep_type, "reep_name": data.names.get(reep_id)}
        if not compatible:
            plan.stats[f"{entity.entity_type}:name_mismatch"] += 1
            plan.queue.append(QueueItem("name_mismatch", entity.entity_type, entity.entity_id, None, "reep", "", reep_id,
                                        0.4, {**evidence, "ours": list(entity.names)}))
        candidates.append(IdRow(entity.entity_type, entity.entity_id, "reep", "", reep_id, "exact_bridge",
                                round(bridge.confidence, 3), review, evidence))
        seen: set[tuple[str, str, str]] = set()
        for ext in sorted(data.externals.get(reep_id, ()), key=lambda x: (x.system, x.namespace, x.external_id,
                                                                            -x.confidence)):
            k = (ext.system, ext.namespace, ext.external_id)
            if k in seen:
                continue
            seen.add(k)
            ev: dict[str, object] = {"via": reep_id}
            if ext.detail:
                ev["link"] = ext.detail
            candidates.append(IdRow(entity.entity_type, entity.entity_id, ext.system, ext.namespace, ext.external_id,
                                    "bridge_chain", round(bridge.confidence * ext.confidence, 3), review, ev))
        entity_aliases[(entity.entity_type, entity.entity_id)] = alias_rows(
            entity, reep_id, data.names.get(reep_id), data.aliases.get(reep_id, ()))

    # rule 2, second half: an external id two of our entities would get is linked to neither
    holders: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for row in candidates:
        holders[(row.entity_type, row.system, row.namespace, row.external_id)].append(row.entity_id)
    shared = {k: sorted(set(v)) for k, v in holders.items() if len(set(v)) > 1}
    pairs: dict[tuple[str, int, int], tuple[str, str, str]] = {}
    for (etype, system, namespace, external), ids in sorted(shared.items()):
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                current = pairs.get((etype, a, b))
                if current is None or SYSTEMS.index(system) < SYSTEMS.index(current[0]):
                    pairs[(etype, a, b)] = (system, namespace, external)
    for (etype, a, b), (system, namespace, external) in sorted(pairs.items()):
        plan.stats[f"{etype}:shared_external_pairs"] += 1
        plan.queue.append(QueueItem("shared_external", etype, a, b, system, namespace, external, 0.9,
                                    {"system": system, "external_id": external}))
    for row in candidates:
        if (row.entity_type, row.system, row.namespace, row.external_id) in shared and row.review != "pending":
            row = IdRow(row.entity_type, row.entity_id, row.system, row.namespace, row.external_id, row.method,
                        row.confidence, "pending", {**row.evidence, "shared": True})
        plan.ids.append(row)
    for row in plan.ids:
        plan.stats[f"{row.entity_type}:{row.system}:{row.review}"] += 1
    linked = {(r.entity_type, r.entity_id) for r in plan.ids if r.system == "reep" and r.review == "accepted"}
    for key in sorted(entity_aliases):
        plan.stats[f"{key[0]}:linked"] += key in linked
        plan.aliases.extend(entity_aliases[key])
    plan.stats["aliases"] = len(plan.aliases)
    return plan


def _given(entity: Ours) -> set[str]:
    return {t for t in nm.tokens(entity.firstname) if t not in nm.PARTICLES}


def plan_homonyms(players: Iterable[Ours]) -> tuple[list[QueueItem], dict[str, int]]:
    """The pairs of same-named players a person should look at (see the module docstring)."""
    groups: dict[str, list[Ours]] = defaultdict(list)
    for p in players:
        key = nm.alias_key(p.names[0]) if p.names else ""
        if key:
            groups[key].append(p)
    stats: dict[str, int] = defaultdict(int)
    out: list[QueueItem] = []
    for key in sorted(groups):
        members = groups[key]
        if len(members) < 2:
            continue
        stats["names_repeated"] += 1
        stats["players_in_repeated_names"] += len(members)
        dated = sorted((m for m in members if m.birth_date is not None), key=lambda m: (m.birth_date, m.entity_id))
        stats["players_without_birth_date"] += len(members) - len(dated)
        for i, a in enumerate(dated):
            for b in dated[i + 1:]:
                assert a.birth_date is not None and b.birth_date is not None
                days = (b.birth_date - a.birth_date).days
                if days > NEAR_DAYS:
                    break
                ga, gb = _given(a), _given(b)
                if ga and gb and not (ga & gb):
                    stats["twins_or_siblings_skipped"] += 1
                    continue
                lo, hi = sorted((a.entity_id, b.entity_id))
                kind = "possible_duplicate" if days == 0 else "near_birth_date"
                stats[kind] += 1
                out.append(QueueItem(kind, "player", lo, hi, None, None, None, 0.9 if days == 0 else 0.6,
                                     {"name": key, "days_apart": days,
                                      "birth_dates": [str(a.birth_date), str(b.birth_date)]}))
    return out, dict(stats)
