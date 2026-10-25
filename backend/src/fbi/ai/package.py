"""The package of a match and its slices (Plan Maestro IA, phase 1, sections 15 and 16): ``mcp-v1``.

What it is. The backend writes, once per pass and with no model involved, ONE document about a match - ``contracts.mcp.McpPackage`` - and
gives each agent its SLICE of it: the Match Agent the blocks of goals and result, the Statistics Agent the blocks of corners and cards. It
is derived, by a pure function, from the stored ``packet-v8`` of the pass (``ai.match_packets``, the one the brief of that pass read) and from
one as-of read of PrediGol's forecasts of the counts (``family-v1``). Nothing is estimated, nothing is read that was recorded after the
packet's moment, and the live flow is not touched: the package is a second reader of what the first already stored.

What it adds to the packet.
* A SLICE per reader, each the sub-document of the package that reader needs, and no more: no slice carries data of another family (the
  Match Agent never sees corners and cards, the Statistics Agent never sees a price of goals) - held by tests that read every key.
* The constant explanations that ``packet-v8`` repeats in every match (the notes of each block, the table of weights of the head-to-head)
  are left out: they belong to the system prompt, which is cached once, not to a package that is paid again for every match.
* Evidence as an INDEX: id, kind, subject, state, class of source, day and a short summary that travels as an untrusted block
  (``fbi.ai.untrusted``). No URL, ever: the domain says where it came from.
* The free text of the other blocks (a name, a reason, a round) cleaned in place by the same module; where it reads like an order the text
  is replaced and the place is recorded in ``flags`` for the audit.
* ``blocking``: the reasons no model is called for the match (data not fit for a forecast, a quarantined match).

What it guarantees. ``knowledge_stamps`` finds every moment the package states about what it knows (the time a price, a forecast, a
calendar, a decision was recorded) and a package with one later than its own ``known_at`` is refused (``PackageLeakError``) - the slice
cannot know more than the pass did. An evidence retrieved or published after the moment is left out and counted. A slice is measured in
real tokens (the packet's approximate count times the factor measured in F6, 2.34), has a cap, and when it passes it the plan's cuts are
made in the plan's order - the oldest meetings of the head-to-head, then the long summaries of the evidence - and never an absence, a
line-up or a price. A slice that still does not fit is NOT sent (``Slice.fits`` is false): the match goes on without that agent.

Pure where it can be: ``package_from_packet`` and ``slice_of`` read nothing; ``read_families`` and ``derive`` are the only parts that touch
the database, and read only.
"""

from __future__ import annotations

import copy
import json
import time
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from pydantic import ValidationError

from fbi.ai.contracts.base import MCP
from fbi.ai.contracts.mcp import (
    AVAILABILITY_KINDS,
    BLOCKS,
    NOT_FIT,
    SLICE_BLOCKS,
    SLICE_FAMILIES,
    SLICE_NAMES,
    STATS_EXCLUDED_KINDS,
    Blocking,
    EvidenceItem,
    McpPackage,
    PacketRef,
    PassKind,
    SliceName,
    UntrustedText,
    family_of,
    source_class,
)
from fbi.ai.evidence import domain_of
from fbi.ai.packet import Packet, canonical, content_hash
from fbi.ai.pricing import approx_tokens
from fbi.ai.untrusted import sanitize

VERSION: Final = "package-v1"
"""The code that derives a package. It is part of the idempotency key (``fbi.ai.idempotency``): a change here is a new derivation of the
same packet, never a silent rewrite of an old one."""

REAL_PER_APPROX: Final = Decimal("2.34")
"""Real tokens per approximate token (characters / 4) of a canonical package, as measured against the provider's own count in F6:
``packet-v8`` 6.223 approximate = ≈ 14.600 real. A planning measure, never a bill."""
CAPS: Final[dict[str, int]] = {"match": 18_000, "stats": 18_000}
"""Real tokens a slice may have (section 16). The Council's view (10.000) and the Research Service's (4.000) come with their phases."""

STRING_MAX: Final = 200
"""Characters of any free-text field of the header and the shared blocks (a name, a reason): longer is cut."""
SUMMARY_MAX: Final = 240
SUMMARY_SHORT: Final = 120
SUMMARY_TINY: Final = 60
"""The lengths of an evidence's summary: the package keeps 240, the first cut 120, the second 60."""
EVIDENCE_MAX: Final = 40
H2H_KEEP: Final = (5, 3)
"""The first and the second cut of the head-to-head: the meetings that remain, the most recent."""
EVIDENCE_KEEP: Final = 12
"""The last cut: evidence beyond this many (in order of relevance) goes, unless it says who can play."""
REMOVED: Final = "[text removed]"

# What belongs to a family of counts and to no other (the keys of ``fbi.intel.dossier`` and the packet's ``stats``): the match slice drops
# them, the stats slice keeps only them.
COUNT_TEAM_KEYS: Final = frozenset({"corners", "corners_against", "fouls", "fouls_against", "cards", "reds", "offsides"})
COUNT_PLAYER_KEYS: Final = frozenset({"fouls", "cards"})
COUNT_REFEREE_KEYS: Final = frozenset({"cards_per_match", "reds_per_match", "cards_home_per_match", "cards_away_per_match",
                                       "fouls_per_match"})
COUNT_STATS_KEYS: Final = frozenset({"corners"})
COUNT_WORDS: Final = COUNT_TEAM_KEYS | COUNT_PLAYER_KEYS | COUNT_REFEREE_KEYS | COUNT_STATS_KEYS | {"families"}
"""Every key that is data of the family of counts: none may appear in the match slice (a test reads them all)."""
PROSE_KEYS: Final = frozenset({"note", "weights_note", "weights"})
"""The constant explanations of ``packet-v8``'s blocks."""

LIGHT_BLOCKS: Final = ("standings", "stakes", "schedule", "absences", "lineups", "context", "quality", "factors", "tactics", "travel")
"""What the Statistics Agent reads of what both sides share (the plan's «shared ligero»), besides the referee and the counts."""
STAMP_KEYS: Final = frozenset({"known_at", "data_cutoff_at", "as_of", "opening_as_of", "fetched_at", "retrieved_at", "observed_at",
                               "snapshot_at", "decided_at", "published_at"})
"""The keys that state WHEN the package learnt something (not when a match is played: ``kickoff_at`` is the future by nature)."""

MODEL_MARKET_FAMILIES: Final = SLICE_FAMILIES


class PackageLeakError(ValueError):
    """The package states a moment of knowledge later than its own: it would let an agent know more than the pass did."""

    def __init__(self, late: list[str]) -> None:
        super().__init__(f"{len(late)} stamp(s) later than known_at: " + ", ".join(late[:5]))
        self.late = late


# ── measuring ───────────────────────────────────────────────────────────────────────────────────────────────────────

def real_tokens(document: object) -> int:
    """The real tokens a document costs the provider, estimated: the characters of its canonical form over four, times 2.34, rounded up."""
    approx = approx_tokens(canonical(document))
    return int((Decimal(approx) * REAL_PER_APPROX).to_integral_value(rounding=ROUND_CEILING))


def parse_stamp(value: object) -> datetime | None:
    """A moment from the text a document states it in, in any form ISO 8601 allows (``2026-10-25``, ``20261025T120000Z``...). A moment
    with no zone is read as UTC - the database's - so that it is checked all the same: a stamp that cannot be compared is a stamp that
    cannot be trusted, and a form that is only rare is no reason not to compare it."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def knowledge_stamps(node: object, path: str = "", *, stamped: bool = False) -> list[tuple[str, datetime]]:
    """Every stamp of knowledge in a document: where it is and when. A stamp is a date and time under one of the keys of ``STAMP_KEYS`` or
    anywhere inside the value of one (``data_cutoff_at`` of the models is a dictionary of moments, one per model). Lists are walked and
    their elements share the path of the list."""
    found: list[tuple[str, datetime]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            found.extend(knowledge_stamps(value, here, stamped=stamped or key in STAMP_KEYS))
    elif isinstance(node, list):
        for item in node:
            found.extend(knowledge_stamps(item, path, stamped=stamped))
    elif stamped and (stamp := parse_stamp(node)) is not None:
        found.append((path, stamp))
    return found


def contained_in(small: object, big: object) -> bool:
    """Whether ``small`` is a part of ``big`` and nothing else: every key of a dictionary is in the other with a contained value, every
    element of a list is contained in some element of the other, a scalar is equal and a text is equal or is a cut of it (a prefix and
    the ellipsis ``trim`` writes). The relation a slice has to the package it comes from."""
    if isinstance(small, dict):
        return isinstance(big, dict) and all(k in big and contained_in(v, big[k]) for k, v in small.items())
    if isinstance(small, list):
        return isinstance(big, list) and all(any(contained_in(s, b) for b in big) for s in small)
    if isinstance(small, str) and isinstance(big, str):
        return small == big or (small.endswith("…") and big.startswith(small[:-1]))
    return bool(small == big and type(small) is type(big))


def paths_in(document: object, prefix: str = "") -> set[str]:
    """The dotted paths of the blocks of a slice, which is what ``P:`` references can name (``contracts.base.paths_of`` for a document
    that may hold lists)."""
    found: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            here = f"{prefix}.{key}" if prefix else str(key)
            found.add(here)
            found |= paths_in(value, here)
    return found


# ── cleaning the text that came from outside ────────────────────────────────────────────────────────────────────────

def _clean(node: Any, path: str, flags: list[str]) -> Any:
    """Every text of a block through ``fbi.ai.untrusted``: normalised, stripped of links and invisible characters, cut. A text that reads
    like an order to a model is replaced and its place recorded - a name or a reason is never an instruction, and never worth the risk."""
    if isinstance(node, str):
        cleaned = sanitize(node, origin="provider", max_chars=STRING_MAX)
        if cleaned.instruction_like:
            flags.append(f"{path}:instruction_like")
            return REMOVED
        return cleaned.text
    if isinstance(node, dict):
        return {k: _clean(v, f"{path}.{k}", flags) for k, v in node.items()}
    if isinstance(node, list):
        return [_clean(v, path, flags) for v in node]
    return node


def _without(node: Any, keys: Iterable[str]) -> Any:
    """``node`` without the given keys, at any depth."""
    drop = frozenset(keys)
    if isinstance(node, dict):
        return {k: _without(v, drop) for k, v in node.items() if k not in drop}
    if isinstance(node, list):
        return [_without(v, drop) for v in node]
    return node


def _only(node: object, keys: Iterable[str]) -> dict[str, Any]:
    return {k: v for k, v in node.items() if k in frozenset(keys)} if isinstance(node, dict) else {}


# ── the blocks ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _header(content: Mapping[str, Any]) -> dict[str, Any]:
    f = content.get("fixture") or {}
    header: dict[str, Any] = {
        "fixture_id": f.get("id"), "kickoff_at": f.get("kickoff_at"), "status": f.get("status"),
        "competition": {"name": f.get("competition"), "country": f.get("competition_country"), "type": f.get("competition_type"),
                        "tier": f.get("competition_tier")},
        "season": f.get("season"), "round": f.get("round"), "stage": f.get("stage"),
        "venue": {"name": f.get("venue"), "city": f.get("venue_city"), "country": f.get("venue_country")},
        "neutral": f.get("neutral"), "home": f.get("home"), "away": f.get("away")}
    if content.get("phase"):
        header["phase"] = content["phase"]
    return header


def _quality(content: Mapping[str, Any], known_at: datetime) -> tuple[dict[str, Any], list[Blocking]]:
    """The quality of the data as of the moment: the class of the competition's data, the state of the match's validation - only if it was
    decided by then (the packet reads the CURRENT state, which a later validation may have changed) - and whether the line-ups are
    confirmed. No timestamps: the package states what it knows, not when each thing was written."""
    q = content.get("quality") or {}
    score = q.get("competition_score") or {}
    validation = q.get("fixture_validation") or {}
    validated_at = parse_stamp(validation.get("validated_at"))
    state = validation.get("state") if validated_at is not None and validated_at <= known_at else None
    out = {"class": score.get("class"), "score": score.get("score"), "validation": state,
           "lineups_confirmed": bool(q.get("lineups_confirmed"))}
    blocking: list[Blocking] = []
    if score.get("class") in NOT_FIT:
        blocking.append("PRODUCT_ONLY" if score.get("class") == "PRODUCT_ONLY" else "INSUFFICIENT")
    if state == "QUARANTINED":
        blocking.append("QUARANTINED")
    return out, blocking


def _shared(content: Mapping[str, Any], known_at: datetime) -> tuple[dict[str, Any], list[Blocking]]:
    raw = content.get("dossier")
    dossier: dict[str, Any] = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key in ("standings", "stakes", "scenarios", "form", "elo", "absences", "lineups", "travel", "factors", "h2h", "stats"):
        if content.get(key) is not None:
            out[key] = content[key]
    if isinstance(content.get("schedule"), dict):
        changes = (content.get("fixture") or {}).get("kickoff_changes") or []
        out["schedule"] = {**content["schedule"], "kickoff_changes": changes}
    for name in ("teams", "players", "referee", "context", "tactics"):
        if dossier.get(name):
            out[name] = dossier[name]
    if dossier.get("national"):
        out["national"] = dossier["national"]
    quality, blocking = _quality(content, known_at)
    out["quality"] = quality
    return _without(out, PROSE_KEYS), blocking


def _market(content: Mapping[str, Any]) -> dict[str, Any]:
    block = content.get("market") or {}
    selections = [s for s in block.get("selections") or [] if family_of(str(s.get("market", ""))) is not None]
    return {"selections": selections, "observed": bool(selections)}


def _models(content: Mapping[str, Any], sources: list[dict[str, Any]], model_code: str) -> dict[str, Any]:
    by_model: dict[str, Any] = {}
    for name, block in (content.get("models") or {}).items():
        kept = [s for s in (block or {}).get("selections") or [] if family_of(str(s.get("market", ""))) is not None]
        if kept:
            by_model[name] = {"selections": kept}
    out: dict[str, Any] = {"by_model": by_model}
    forecast = content.get("forecast")
    if isinstance(forecast, dict) and "markets" in forecast:
        out["forecast"] = {"version": forecast.get("version"),
                           "markets": [m for m in forecast["markets"] if family_of(str(m.get("market", ""))) is not None]}
    prov = next((s for s in sources if s.get("block") == "models"), None)
    if prov is not None:
        out["provenance"] = {"versions": prov.get("versions") or {}, "data_cutoff_at": prov.get("data_cutoff_ts") or {}}
    if model_code:
        out["code"] = model_code
    return out


def _evidence(rows: list[dict[str, Any]], known_at: datetime, flags: list[str]) -> tuple[list[EvidenceItem], Counter[str]]:
    items: list[EvidenceItem] = []
    dropped: Counter[str] = Counter()
    if len(rows) > EVIDENCE_MAX:
        dropped["evidence_beyond_the_limit"] += len(rows) - EVIDENCE_MAX
    for row in rows[:EVIDENCE_MAX]:
        retrieved = parse_stamp(row.get("retrieved_at"))
        published = parse_stamp(row.get("published_at"))
        if retrieved is None:
            dropped["evidence_retrieval_time_unknown"] += 1
            continue
        if retrieved > known_at:
            dropped["evidence_retrieved_after_the_moment"] += 1
            continue
        if published is not None and published > known_at:
            dropped["evidence_published_after_the_moment"] += 1
            continue
        domain = domain_of(row.get("url")) or ""
        text = sanitize(row.get("claim"), origin=domain or str(row.get("source") or "provider"), max_chars=SUMMARY_MAX)
        if not text.text:
            dropped["evidence_without_text"] += 1
            continue
        try:
            item = EvidenceItem(
                id=int(row["id"]), kind=row["kind"], side=row.get("side") or "match", player_id=row.get("player_id"),
                status=row["status"], source_class=source_class(row.get("tier"), domain), domain=domain,
                published_on="" if published is None else published.date().isoformat(),
                summary=UntrustedText(untrusted=True, origin=text.origin, text=text.text, truncated=text.truncated,
                                      flags=list(text.flags)))
        except (ValidationError, KeyError, TypeError, ValueError):
            dropped["evidence_malformed"] += 1
            continue
        if text.instruction_like:
            flags.append(f"evidence.{item.id}:instruction_like")
        items.append(item)
    return items, dropped


# ── the package ─────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Package:
    fixture_id: int
    pass_kind: PassKind
    known_at: datetime
    source: PacketRef
    document: dict[str, Any]
    hash: str
    blocking: tuple[str, ...]
    flags: tuple[str, ...]
    dropped: dict[str, int] = field(default_factory=dict)
    elapsed_ms: int = 0

    @property
    def tokens(self) -> int:
        return real_tokens(self.document)


def _compact(document: dict[str, Any]) -> dict[str, Any]:
    """The document without what is empty and costs tokens in every line of the evidence (a ``None`` player, an empty domain, a summary
    that was not cut and has no flags)."""
    for item in document.get("evidence", []):
        for key in ("player_id", "domain", "published_on"):
            if item.get(key) in (None, ""):
                item.pop(key, None)
        summary = item["summary"]
        if not summary.get("truncated"):
            summary.pop("truncated", None)
        if not summary.get("flags"):
            summary.pop("flags", None)
    if not document.get("blocking"):
        document.pop("blocking", None)
    if not document.get("flags"):
        document.pop("flags", None)
    return document


def package_from_packet(packet: Packet, *, pass_kind: PassKind, families: dict[str, Any] | None = None, model_code: str = "",
                        packet_id: int | None = None, source_hash: str | None = None) -> Package:
    """The ``mcp-v1`` package of a packet. Pure: the same packet, families and code give the same package, byte for byte."""
    started = time.perf_counter()
    content: dict[str, Any] = json.loads(canonical(packet.content))
    known_at = packet.as_of
    flags: list[str] = []
    shared, blocking = _shared(content, known_at)
    evidence, dropped = _evidence(content.get("evidence") or [], known_at, flags)
    package = McpPackage(
        contract=MCP, fixture_id=packet.fixture_id, pass_kind=pass_kind, known_at=known_at,
        source=PacketRef(id=packet_id, version=packet.version, hash=source_hash or packet.hash),
        header=_clean(_without(_header(content), PROSE_KEYS), "header", flags),
        shared=_clean(shared, "shared", flags),
        market=_market(content), models=_models(content, packet.sources, model_code),
        families=families or {}, evidence=evidence, missing=sorted(set(packet.missing)), blocking=blocking, flags=flags[:20])
    document = _compact(package.model_dump(mode="json"))
    late = [path for path, stamp in knowledge_stamps(document) if stamp > known_at]
    if late:
        raise PackageLeakError(late)
    return Package(
        fixture_id=packet.fixture_id, pass_kind=pass_kind, known_at=known_at, source=package.source, document=document,
        hash=content_hash(document), blocking=tuple(blocking), flags=tuple(flags), dropped=dict(dropped),
        elapsed_ms=int((time.perf_counter() - started) * 1000))


# ── the slices ──────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Slice:
    """What one agent reads: the blocks of ``SLICE_BLOCKS[name]`` of a package and the words that frame them."""

    name: SliceName
    fixture_id: int
    known_at: datetime
    package_hash: str
    document: dict[str, Any]
    hash: str
    tokens: int
    cap: int
    trimmed: tuple[str, ...] = ()

    @property
    def fits(self) -> bool:
        return self.tokens <= self.cap

    @property
    def blocks(self) -> tuple[str, ...]:
        return tuple(b for b in BLOCKS if b in self.document)

    def measures(self) -> dict[str, Any]:
        """What ``ai.match_runs`` keeps of a slice: never its content, only what can be audited and charted."""
        return {"name": self.name, "hash": self.hash, "tokens": self.tokens, "cap": self.cap, "fits": self.fits,
                "trimmed": list(self.trimmed), "blocks": list(self.blocks)}


def _team_goals(team: Any) -> Any:
    if not isinstance(team, dict):
        return team
    return {k: (_without(v, COUNT_TEAM_KEYS) if k in ("all", "home", "away") else v) for k, v in team.items()}


def goals_view(shared: Mapping[str, Any]) -> dict[str, Any]:
    """The ``shared`` block as the Match Agent reads it: everything but the data of the counts."""
    out: dict[str, Any] = {}
    for key, value in shared.items():
        if key == "referee":
            out[key] = _without(value, COUNT_REFEREE_KEYS)
        elif key == "teams" and isinstance(value, dict):
            out[key] = {side: _team_goals(t) for side, t in value.items()}
        elif key == "players" and isinstance(value, dict):
            out[key] = {side: [_without(p, COUNT_PLAYER_KEYS) for p in players] for side, players in value.items()}
        elif key == "stats" and isinstance(value, dict):
            out[key] = {side: _without(s, COUNT_STATS_KEYS) for side, s in value.items()}
        else:
            out[key] = value
    return out


def counts_view(shared: Mapping[str, Any]) -> dict[str, Any]:
    """The ``shared`` block as the Statistics Agent reads it: the light blocks, the referee in full and the counts of each side."""
    out: dict[str, Any] = {k: shared[k] for k in LIGHT_BLOCKS if k in shared}
    if "referee" in shared:
        out["referee"] = shared["referee"]
    teams = shared.get("teams")
    if isinstance(teams, dict):
        keep = COUNT_TEAM_KEYS | {"n", "n_stats"}
        out["teams"] = {side: {k: (_only(v, keep) if k in ("all", "home", "away") else v)
                               for k, v in t.items() if k in ("n", "all", "home", "away")} for side, t in teams.items()}
    players = shared.get("players")
    if isinstance(players, dict):
        keep_p = COUNT_PLAYER_KEYS | {"id", "name", "starts", "minutes", "importance", "reported_out"}
        out["players"] = {side: [_only(p, keep_p) for p in plist] for side, plist in players.items()}
    stats = shared.get("stats")
    if isinstance(stats, dict):
        out["stats"] = {side: _only(s, COUNT_STATS_KEYS | {"n"}) for side, s in stats.items()}
    return out


def _in_families(selections: list[dict[str, Any]], key: str, families: tuple[str, ...]) -> list[dict[str, Any]]:
    return [s for s in selections if family_of(str(s.get(key, ""))) in families]


def _project(package: Package, name: SliceName) -> dict[str, Any]:
    doc = package.document
    families = SLICE_FAMILIES[name]
    blocks: dict[str, Any] = {}
    for block in SLICE_BLOCKS[name]:
        value = copy.deepcopy(doc[block]) if block in doc else None
        if value is None:
            continue
        if block == "shared":
            value = goals_view(value) if name == "match" else counts_view(value)
        elif block == "market":
            value = {**value, "selections": _in_families(value.get("selections", []), "market", families)}
        elif block == "models":
            by_model = {m: {"selections": _in_families(b.get("selections", []), "market", families)} for m, b in value["by_model"].items()}
            value = {**value, "by_model": {m: b for m, b in by_model.items() if b["selections"]}}
            if "forecast" in value:
                value["forecast"] = {**value["forecast"], "markets": _in_families(value["forecast"].get("markets", []), "market", families)}
        elif block == "evidence" and name == "stats":
            value = [e for e in value if e["kind"] not in STATS_EXCLUDED_KINDS]
        blocks[block] = value
    return {"contract": MCP, "slice": name, "fixture_id": package.fixture_id, "known_at": package.known_at.isoformat(),
            "pass": package.pass_kind, **blocks, "missing": doc["missing"], "blocking": doc.get("blocking", [])}


def _shorten(evidence: list[dict[str, Any]], limit: int) -> bool:
    changed = False
    for item in evidence:
        text = item["summary"]["text"]
        if len(text) > limit:
            cut = text[: limit - 1]
            item["summary"]["text"] = (cut.rsplit(" ", 1)[0] if " " in cut[limit // 2:] else cut).rstrip() + "…"
            item["summary"]["truncated"] = True
            changed = True
    return changed


def _h2h_keep(document: dict[str, Any], keep: int) -> bool:
    meetings = ((document.get("shared") or {}).get("h2h") or {}).get("meetings")
    if not isinstance(meetings, list) or len(meetings) <= keep:
        return False
    meetings.sort(key=lambda m: m.get("days_ago", 0))
    del meetings[keep:]
    return True


def _evidence_tail(document: dict[str, Any], keep: int) -> bool:
    evidence = document.get("evidence")
    if not isinstance(evidence, list):
        return False
    kept: list[dict[str, Any]] = []
    others = 0
    for item in evidence:
        if item["kind"] in AVAILABILITY_KINDS:
            kept.append(item)  # who can play is never cut
        elif others < keep:
            kept.append(item)
            others += 1
    changed = len(kept) != len(evidence)
    document["evidence"] = kept
    return changed


def trim(document: dict[str, Any], cap: int) -> tuple[dict[str, Any], tuple[str, ...]]:
    """The cuts of section 16, in its order, until the document fits: first the oldest meetings of the head-to-head, then the long
    summaries of the evidence (and, last, the evidence beyond the first twelve that says nothing about who can play). The absences, the
    line-ups and the market are never touched. Returns the document and the cuts that were made."""
    steps: list[tuple[str, Any]] = [
        (f"h2h_oldest_keep_{H2H_KEEP[0]}", lambda d: _h2h_keep(d, H2H_KEEP[0])),
        (f"h2h_oldest_keep_{H2H_KEEP[1]}", lambda d: _h2h_keep(d, H2H_KEEP[1])),
        (f"summaries_{SUMMARY_SHORT}", lambda d: _shorten(d.get("evidence", []), SUMMARY_SHORT)),
        (f"summaries_{SUMMARY_TINY}", lambda d: _shorten(d.get("evidence", []), SUMMARY_TINY)),
        (f"evidence_beyond_{EVIDENCE_KEEP}", lambda d: _evidence_tail(d, EVIDENCE_KEEP)),
    ]
    done: list[str] = []
    for name, step in steps:
        if real_tokens(document) <= cap:
            break
        if step(document):
            done.append(name)
    return document, tuple(done)


def slice_of(package: Package, name: SliceName) -> Slice:
    document = _project(package, name)
    cap = CAPS[name]
    trimmed: tuple[str, ...] = ()
    if real_tokens(document) > cap:
        document, trimmed = trim(document, cap)
    return Slice(name=name, fixture_id=package.fixture_id, known_at=package.known_at, package_hash=package.hash, document=document,
                 hash=content_hash(document), tokens=real_tokens(document), cap=cap, trimmed=trimmed)


def slices_of(package: Package) -> dict[str, Slice]:
    return {name: slice_of(package, name) for name in SLICE_NAMES}


# ── reading (the only parts that touch the database; read only) ────────────────────────────────────────────────────

FAMILY_VERSION: Final = "family-v1"
"""``fbi.families.forecast.VERSION`` (a test holds the two equal: this module does not import the worker's)."""
FAMILY_ORDER: Final = {"CORNERS": 0, "CARDS": 1}

FAMILIES_SQL: Final = """
WITH last AS (
    SELECT market_key, line, max(known_at) AS k
      FROM models.match_forecasts
     WHERE fixture_id = %(fixture)s AND version = %(version)s AND family = ANY(%(families)s) AND known_at <= %(at)s
     GROUP BY 1, 2
)
SELECT x.family, x.market_key, x.line, x.model_name, x.calibration, x.basis, x.known_at, x.data_cutoff_ts, x.code_version,
       x.selection, x.p, x.p_lo, x.p_hi
  FROM models.match_forecasts x JOIN last l ON l.market_key = x.market_key AND l.line = x.line AND l.k = x.known_at
 WHERE x.fixture_id = %(fixture)s AND x.version = %(version)s
 ORDER BY x.family, x.market_key, x.line, x.id
"""


def _p(value: Any) -> float | None:
    return None if value is None else round(float(value), 3)


def read_families(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> dict[str, Any]:
    """What PrediGol stated by ``at`` about the corners and the cards of the match (``family-v1``): the newest set of each market written at
    or before the moment. Empty when there is none (a match whose data is not fit has no forecast, and that is no error)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FAMILIES_SQL, {"fixture": fixture_id, "version": FAMILY_VERSION, "families": list(FAMILY_ORDER), "at": at})
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return {}
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault((str(r["family"]), str(r["market_key"]), str(r["line"])), []).append(r)
    markets: list[dict[str, Any]] = []
    for (family, market, line), rs in sorted(grouped.items(), key=lambda kv: (FAMILY_ORDER.get(kv[0][0], 99), kv[0][1], Decimal(kv[0][2]))):
        first = rs[0]
        best = max(rs, key=lambda r: r["p"])
        markets.append({
            "family": family, "market": market, "line": str(line), "model": first["model_name"], "calibration": first["calibration"],
            "basis": first["basis"], "known_at": first["known_at"].isoformat(), "data_cutoff_at": first["data_cutoff_ts"].isoformat(),
            "code": first["code_version"], "likely": best["selection"],
            "outcomes": [{"selection": r["selection"], "p": _p(r["p"]), "p_lo": _p(r["p_lo"]), "p_hi": _p(r["p_hi"])} for r in rs]})
    return {"version": FAMILY_VERSION, "markets": markets}


PACKET_SQL: Final = ("SELECT fixture_id, packet_version, as_of, packet_hash, content, sources, missing, quality "
                     "FROM ai.match_packets WHERE id = %s")


def load_stored(conn: psycopg.Connection[Any], packet_id: int) -> tuple[Packet, str] | None:
    """A stored packet and the hash it was stored under, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PACKET_SQL, (packet_id,))
        row = cur.fetchone()
    if row is None:
        return None
    packet = Packet(fixture_id=int(row["fixture_id"]), as_of=row["as_of"], content=dict(row["content"] or {}),
                    sources=list(row["sources"] or []), missing=list(row["missing"] or []), quality=dict(row["quality"] or {}),
                    version=str(row["packet_version"]))
    return packet, str(row["packet_hash"])


def derive(conn: psycopg.Connection[Any], packet_id: int, *, pass_kind: PassKind, model_code: str = "") -> Package | None:
    """The package of the pass that read stored packet ``packet_id``: the packet, one as-of read of the forecasts of the counts, and the
    pure function. None when the packet does not exist."""
    stored = load_stored(conn, packet_id)
    if stored is None:
        return None
    packet, stored_hash = stored
    families = read_families(conn, packet.fixture_id, at=packet.as_of)
    return package_from_packet(packet, pass_kind=pass_kind, families=families, model_code=model_code, packet_id=packet_id,
                               source_hash=stored_hash)
