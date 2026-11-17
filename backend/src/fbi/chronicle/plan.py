"""The content plan of a match's chronicle, made by CODE (IA-103, plan piece AD-F01): ``content-plan-v1``. Without a plan there is no section.

WHAT IT DOES. For one match at one moment (``at``), from facts PrediGol already holds, it decides what the single chronicle (``chronicle-v4``,
``fbi.chronicle.writer``) may tell, section by section - which facts are MANDATORY, which are OPTIONAL and, when a section has nothing, the
code of its ABSTENTION - and which classes of claim the chronicle may make (``fbi.chronicle.claims``: a class enters only with a fact that
authorises it). A language model never chooses a fact: it is handed the plan and writes from it.

THE SECTIONS, in their one order (``SECTIONS``): what is at stake (``que_se_juega``), how each side arrives (``como_llega``), what this match can
decide (``que_puede_definir``), the statistics (``estadisticas``), the players (``jugadores``), the news (``novedades``), the risks (``riesgos``:
it MAY be empty - a risk is never invented) and what is not known yet (``que_falta``).

THE FACTS, each with an id the chronicle cites, a kind (``claims.KINDS``), its params and its source:

    the story of the packet      ``fbi.api.services.story``: the table, the tie, the form, the streaks, the venue, the expected goals, the
                                 top scorer, the head-to-head, the last results and the named absences (the provider's) - as of the packet
    the scenarios engine         ``scenarios-v2`` (``intel.scenario_readings``, IA-082): what each team still plays for, what is PROVED
                                 decided, and what each result of THIS match does; never its simulated probabilities
    the news                     ``ai.evidence`` BY REFERENCE (``E:<id>``): its status, kind, side and outlet - never its text. The claim is
                                 joined only by the writer, and only for a source the directory lets a model read (``source_policy``)
    the single figure            ``forecast-v2`` (IA-083): a figure enters with its citation (``figure_text.cite``), never as a number to use
    what is missing              by code: the line-ups not out yet, a regulation not coded, a scenarios reading that does not exist

WHAT NEVER ENTERS (``excluded``, each with its reason):

* «nothing at stake» without the engine: a ``stakes_pressure`` of ``settled`` (``stakes-v5``'s word) is dropped
  (``sin_certificacion_motor``); only ``SIN_OBJETIVO_DEMOSTRADO`` of ``scenarios-v2`` authorises the class;
* an objective the engine did not prove (``no_demostrado``) as decided: it is open or it is nothing;
* a fact known after the plan's moment (``posterior_al_plan``) or without a moment (``sin_momento``) - ``known-at-v1``'s rule (AD-A04);
* an outdated news item (``caducada``); a news item of a source no model may read (``fuente_sin_permiso``);
* the provider's reason of an absence as text (it may be a diagnosis): only its kind (injury, suspension, illness...) and its state;
* a rumour as a fact: a RUMOR or CONTRADICTORY item enters only as ``news.rumour`` with its level, in the risks.

THE SCORE of an optional fact: ``0.40 * pertinence + 0.35 * rarity + 0.25 * novelty`` (each 0 to 1). PERTINENCE is by market
(``RELEVANCE``: what a fact says about the result, the goals and both teams scoring) - the highest among the markets of the plan; RARITY is how
unusual the fact is (a long streak, a decided objective, a key absence); NOVELTY is how new it is (a news item of the last day, a fact the
previous plan of the match did not have). The mandatory facts are not ranked: a decided objective, the tie's outlook, a key player out, a
confirmed news item.

Deterministic and pure: the same input gives the same plan, with the same ids and the same ``hash``. No database, no clock, no model.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from fbi.api.services.story import Fact as StoryFact
from fbi.chronicle import claims
from fbi.competitions.scenarios import FACT_NO_OBJECTIVE
from fbi.forecasting.figure_text import cite

VERSION: Final = "content-plan-v1"

SECTIONS: Final[tuple[str, ...]] = ("que_se_juega", "como_llega", "que_puede_definir", "estadisticas", "jugadores", "novedades", "riesgos",
                                    "que_falta")
CAPS: Final[dict[str, int]] = {"que_se_juega": 2, "como_llega": 4, "que_puede_definir": 2, "estadisticas": 2, "jugadores": 3,
                               "novedades": 2, "riesgos": 2, "que_falta": 2}
"""The most sentences a section may have: short paragraphs. A section's real cap is never more than its facts."""
FACTS_PER_SENTENCE: Final = 2
"""Facts planned per sentence of a section's cap (a sentence cites 1 to 4)."""
EMPTY: Final[dict[str, str]] = {"que_se_juega": "SIN_ESCENARIO", "como_llega": "SIN_RESULTADOS", "que_puede_definir": "SIN_ESCENARIO",
                                "estadisticas": "SIN_ESTADISTICAS", "jugadores": "SIN_JUGADORES", "novedades": "SIN_NOVEDADES",
                                "riesgos": "SIN_RIESGOS", "que_falta": "NADA_PENDIENTE"}
"""The abstention of a section with no fact: said, never filled."""
NO_PLAN: Final = "SIN_PLAN"
"""The match has no story (a side without its last results, or no packet): no plan, no chronicle."""
NO_DATA: Final = "SIN_DATOS"
"""The plan has no fact a reader could be told (only what is missing)."""
EMPTY_VERIFICATION: Final = "VERIFICACION_VACIA"
"""The writer wrote, and no sentence stood (``fbi.chronicle.verify``)."""
ABSTENTIONS: Final[tuple[str, ...]] = (NO_PLAN, NO_DATA, EMPTY_VERIFICATION)
"""The abstentions of a whole chronicle (``ai.chronicles.abstention``)."""

MARKETS: Final[tuple[str, ...]] = ("1X2", "OU", "BTTS")
"""The markets a plan is pertinent to by default: the result, the goals and both teams scoring."""
RELEVANCE: Final[dict[str, tuple[float, float, float]]] = {
    "match.intro": (0.3, 0.2, 0.2), "match.kind": (0.6, 0.3, 0.3),
    "table.position": (0.8, 0.3, 0.3), "table.gap": (0.8, 0.3, 0.3), "table.pressure": (0.8, 0.3, 0.3),
    "scenario.no_objective": (0.9, 0.4, 0.4), "scenario.secured": (0.9, 0.4, 0.4), "scenario.lost": (0.9, 0.4, 0.4),
    "scenario.open": (0.9, 0.4, 0.4), "scenario.result_effect": (0.9, 0.4, 0.4),
    "tie.first_leg": (0.9, 0.5, 0.4), "tie.outlook": (0.9, 0.5, 0.4),
    "form": (0.8, 0.6, 0.6), "result": (0.6, 0.6, 0.6), "streak.unbeaten": (0.7, 0.3, 0.3), "streak.winless": (0.7, 0.3, 0.3),
    "venue_record": (0.7, 0.4, 0.4), "xg": (0.5, 0.9, 0.9), "top_scorer": (0.4, 0.7, 0.7),
    "h2h.summary": (0.5, 0.5, 0.5), "h2h.meeting": (0.5, 0.5, 0.5),
    "absence.out": (0.7, 0.6, 0.6), "absence.doubtful": (0.6, 0.5, 0.5),
    "news.confirmed": (0.6, 0.4, 0.4), "news.probable": (0.6, 0.4, 0.4), "news.rumour": (0.5, 0.3, 0.3),
    "figure": (0.0, 0.0, 0.0),
    "unknown.lineups": (0.5, 0.5, 0.5), "unknown.rules": (0.4, 0.1, 0.1), "unknown.scenarios": (0.4, 0.1, 0.1),
}
"""Pertinence of each kind to (1X2, OU, BTTS). A figure is pertinent only to its own market (1.0)."""
PERTINENT_AT: Final = 0.6
"""A fact is listed as pertinent to a market from this weight."""
WEIGHTS: Final = (0.40, 0.35, 0.25)
"""Pertinence, rarity, novelty."""

SECTION_OF: Final[dict[str, str]] = {
    "match.intro": "que_se_juega", "match.kind": "que_se_juega", "table.position": "que_se_juega", "table.gap": "que_se_juega",
    "table.pressure": "que_se_juega", "scenario.no_objective": "que_se_juega", "scenario.secured": "que_se_juega",
    "scenario.lost": "que_se_juega", "scenario.open": "que_se_juega", "tie.first_leg": "que_se_juega",
    "scenario.result_effect": "que_puede_definir", "tie.outlook": "que_puede_definir",
    "form": "como_llega", "result": "como_llega", "streak.unbeaten": "como_llega", "streak.winless": "como_llega",
    "venue_record": "como_llega",
    "xg": "estadisticas", "h2h.summary": "estadisticas", "h2h.meeting": "estadisticas", "figure": "estadisticas",
    "top_scorer": "jugadores", "absence.out": "jugadores",
    "news.confirmed": "novedades", "news.probable": "novedades",
    "absence.doubtful": "riesgos", "news.rumour": "riesgos",
    "unknown.lineups": "que_falta", "unknown.rules": "que_falta", "unknown.scenarios": "que_falta",
}
STORY_KIND: Final[dict[str, str]] = {
    "match_intro": "match.intro", "match_kind": "match.kind", "stakes_zone": "table.position", "stakes_gap_up": "table.gap",
    "stakes_gap_down": "table.gap", "stakes_pressure": "table.pressure", "first_leg": "tie.first_leg", "tie_outlook": "tie.outlook",
    "form": "form", "venue_record": "venue_record", "xg": "xg", "streak_unbeaten": "streak.unbeaten", "streak_winless": "streak.winless",
    "top_scorer": "top_scorer", "h2h": "h2h.summary", "h2h_meeting": "h2h.meeting", "result": "result",
}
"""The story's codes and the kind each becomes. ``absence`` is read on its own; ``key_absences`` is the list the absences already are."""
MANDATORY: Final = frozenset({"scenario.no_objective", "scenario.secured", "scenario.lost", "tie.outlook", "news.confirmed"})
"""Kinds told whenever they are in the plan (a key player out is mandatory too: ``_mandatory``)."""
SKIPPED_PARAMS: Final = frozenset({"reason", "n_effective"})
"""Params of the story never given to the writer: the provider's reason of an absence may be a diagnosis (its ``kind`` is kept)."""

NEWS_KIND: Final[dict[str, str]] = {"CONFIRMED": "news.confirmed", "PROBABLE": "news.probable", "RUMOR": "news.rumour",
                                    "CONTRADICTORY": "news.rumour"}
RUMOUR_LEVEL: Final[dict[str, str]] = {"RUMOR": "rumor", "CONTRADICTORY": "contradictorio"}
DAY: Final = timedelta(hours=24)


# ── what the plan is made from ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class NewsIn:
    """A news item of the match as the packet names it, by reference. Its claim never enters the plan."""

    evidence_id: int
    status: str
    kind: str
    side: str | None
    source: str | None
    retrieved_at: datetime | None
    """Its moment of knowledge (``ai.evidence.retrieved_at``, ``known-at-v1``)."""
    published_at: datetime | None
    content_hash: str | None
    may_read: bool
    """The directory lets a model read its source (``source_policy.can_extract``: ``verificada_autorizada`` and signed)."""


@dataclass(frozen=True, slots=True)
class FigureIn:
    """One single figure of ``forecast-v2`` (``fbi.forecasting.single_figure.Figure``) as the plan needs it."""

    reading_id: str
    market: str
    selection: str
    line: float
    p: float
    seal: str
    version: str


@dataclass(frozen=True, slots=True)
class PlanInput:
    fixture_id: int
    at: datetime
    """The plan's moment: nothing known after it enters."""
    home: str
    away: str
    competition: str
    home_team_id: int | None = None
    away_team_id: int | None = None
    packet_id: int | None = None
    data_at: datetime | None = None
    """The packet's moment (its story facts are known as of it)."""
    story: tuple[StoryFact, ...] = ()
    thin: bool = True
    """The story lacks the last results of a side (``story.Story.thin``): no plan."""
    news: tuple[NewsIn, ...] = ()
    lineups_confirmed: bool | None = None
    scenarios: Mapping[str, Any] | None = None
    """The newest ``scenarios-v2`` reading of the match's competition season known by ``at`` (``intel.scenario_readings.reading``)."""
    figures: tuple[FigureIn, ...] = ()
    markets: tuple[str, ...] = MARKETS
    previous: frozenset[str] = frozenset()
    """The keys (``PlanFact.key``) of the previous plan of the match with OTHER facts: what it did not have is new. When the newest stored
    plan has the same facts, its own ``previous`` is given again (``fbi.chronicle.inputs.previous_keys``), so the same facts always make the
    same plan - and the same chronicle is never paid twice."""


# ── what the plan is ────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PlanFact:
    id: str
    kind: str
    section: str
    side: str | None
    params: Mapping[str, Any]
    source: str
    known_at: datetime | None
    classes: tuple[str, ...]
    markets: tuple[str, ...]
    pertinence: float
    rarity: float
    novelty: float
    score: float
    mandatory: bool
    value: float | None = None
    """A figure's probability (never sent to the writer: the figure text checker needs it)."""

    @property
    def key(self) -> str:
        """What identifies the fact across plans of the match (for novelty): its kind, id and params."""
        return hashlib.sha256(json.dumps([self.kind, self.id, dict(self.params)], sort_keys=True, ensure_ascii=False,
                                         default=str).encode()).hexdigest()[:16]

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "section": self.section, "side": self.side, "params": dict(self.params),
                "source": self.source, "known_at": None if self.known_at is None else self.known_at.isoformat(),
                "classes": list(self.classes), "markets": list(self.markets), "pertinence": self.pertinence, "rarity": self.rarity,
                "novelty": self.novelty, "score": self.score, "mandatory": self.mandatory, "value": self.value, "key": self.key}

    def for_writer(self) -> dict[str, Any]:
        """What the writer is sent of the fact: no score, no probability, no moment."""
        return {"id": self.id, "kind": self.kind, "side": self.side, "params": dict(self.params)}


@dataclass(frozen=True, slots=True)
class SectionPlan:
    code: str
    cap: int
    """The most sentences it may have (0 with an abstention)."""
    mandatory: tuple[str, ...]
    optional: tuple[str, ...]
    abstention: str | None

    @property
    def facts(self) -> tuple[str, ...]:
        return (*self.mandatory, *self.optional)

    def as_json(self) -> dict[str, Any]:
        return {"code": self.code, "cap": self.cap, "mandatory": list(self.mandatory), "optional": list(self.optional),
                "abstention": self.abstention}


@dataclass(frozen=True, slots=True)
class Excluded:
    ref: str
    kind: str
    reason: str

    def as_json(self) -> dict[str, str]:
        return {"ref": self.ref, "kind": self.kind, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ContentPlan:
    fixture_id: int
    at: datetime
    home: str
    away: str
    competition: str
    markets: tuple[str, ...]
    facts: tuple[PlanFact, ...]
    sections: tuple[SectionPlan, ...]
    excluded: tuple[Excluded, ...]
    abstention: str | None
    packet_id: int | None = None
    figure_version: str | None = None
    scenarios_at: str | None = None
    previous: tuple[str, ...] = ()
    """The keys novelty was measured against (sorted)."""
    version: str = VERSION
    classes_version: str = claims.VERSION

    def by_id(self) -> dict[str, PlanFact]:
        return {f.id: f for f in self.facts}

    @property
    def allowed_classes(self) -> list[str]:
        """The classes of claim the chronicle may make: those an included fact authorises."""
        return claims.allowed_classes(f.kind for f in self.facts if self._planned(f.id))

    def _planned(self, fid: str) -> bool:
        return any(fid in s.facts for s in self.sections)

    @property
    def planned(self) -> tuple[PlanFact, ...]:
        """The facts some section plans, in the sections' order."""
        by = self.by_id()
        return tuple(by[i] for s in self.sections for i in s.facts)

    @property
    def names(self) -> tuple[str, ...]:
        """The names of the match and of its planned facts (teams, players, competitions, outlets): a name is never read as a number."""
        out = {self.home, self.away, self.competition}
        for f in self.planned:
            for key in NAME_KEYS:
                value = f.params.get(key)
                if isinstance(value, str):
                    out.add(value)
                elif isinstance(value, list):
                    out.update(v for v in value if isinstance(v, str))
        return tuple(sorted(n for n in out if n))

    def readings(self) -> dict[str, float]:
        """The single figures the plan carries: reading id -> probability (``figure_text.check``)."""
        return {str(f.params["reading_id"]): float(f.value) for f in self.facts if f.kind == "figure" and f.value is not None}

    def as_json(self) -> dict[str, Any]:
        return {"version": self.version, "classes_version": self.classes_version, "classes_hash": claims.table_hash(),
                "fixture_id": self.fixture_id, "at": self.at.isoformat(), "packet_id": self.packet_id,
                "match": {"home": self.home, "away": self.away, "competition": self.competition}, "markets": list(self.markets),
                "figure_version": self.figure_version, "scenarios_at": self.scenarios_at, "previous_keys": list(self.previous),
                "abstention": self.abstention,
                "allowed_classes": self.allowed_classes, "sections": [s.as_json() for s in self.sections],
                "facts": [f.as_json() for f in self.facts], "excluded": [e.as_json() for e in self.excluded]}

    @property
    def hash(self) -> str:
        """The identity of the plan: the same facts, sections and exclusions give the same hash, whatever the clock said (the moments and the
        scores of the facts are not in it; what the scores chose is, in the sections)."""
        body = {k: v for k, v in self.as_json().items() if k not in ("at", "facts")}
        body["facts"] = [{"id": f.id, "kind": f.kind, "section": f.section, "side": f.side, "params": dict(f.params), "source": f.source,
                          "mandatory": f.mandatory, "value": f.value} for f in self.facts]
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


NAME_KEYS: Final = ("team", "home", "away", "player", "players", "competition", "opponent", "source", "objetivo_tabla")


# ── reading the facts ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _num(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x))
    except ValueError:
        return None


def _clip(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 3)


def _rarity(kind: str, params: Mapping[str, Any]) -> float:
    n = _num(params.get("n")) or 0.0
    if kind in claims.SCENARIO_DECIDED or kind in ("tie.outlook", "scenario.result_effect"):
        return 1.0
    if kind in ("streak.unbeaten", "streak.winless"):
        return _clip(n / 8)
    if kind == "form":
        wins, losses = _num(params.get("wins")) or 0, _num(params.get("losses")) or 0
        return 0.8 if n and (wins == n or losses == n) else 0.3
    if kind == "absence.out":
        return 0.8 if params.get("key") else 0.4
    if kind == "absence.doubtful":
        return 0.6 if params.get("key") else 0.3
    return {"match.kind": 0.9, "tie.first_leg": 0.8, "news.confirmed": 0.7, "news.probable": 0.5, "news.rumour": 0.4,
            "top_scorer": 0.5, "scenario.open": 0.5, "table.pressure": 0.5, "table.position": 0.4, "table.gap": 0.4,
            "venue_record": 0.3, "xg": 0.3, "h2h.summary": 0.3, "h2h.meeting": 0.3, "result": 0.2, "figure": 0.2,
            "match.intro": 0.1}.get(kind, 0.2)


def _pertinence(kind: str, params: Mapping[str, Any], markets: Sequence[str]) -> tuple[float, tuple[str, ...]]:
    if kind == "figure":
        mine = str(params.get("market"))
        return (1.0, (mine,)) if mine in markets else (0.0, ())
    weights = dict(zip(MARKETS, RELEVANCE.get(kind, (0.3, 0.3, 0.3)), strict=True))
    wanted = [m for m in markets if m in weights] or list(MARKETS)
    best = max(weights[m] for m in wanted)
    return round(best, 3), tuple(m for m in wanted if weights[m] >= PERTINENT_AT)


def _novelty(kind: str, params: Mapping[str, Any], known_at: datetime | None, at: datetime, key: str,
             previous: frozenset[str]) -> float:
    base = (0.3 if key in previous else 1.0) if previous else 0.5
    if kind.startswith("news.") and known_at is not None:
        age = at - known_at
        base = max(base, 1.0 if age <= DAY else 0.6 if age <= 3 * DAY else 0.3)
    if kind == "result":
        base = max(base, 0.8 if params.get("order") == 1 else 0.4)
    return _clip(base)


def _fact(fid: str, kind: str, side: str | None, params: Mapping[str, Any], *, source: str, known_at: datetime | None,
          inp: PlanInput, value: float | None = None) -> PlanFact:
    clean = {k: v for k, v in params.items() if v is not None and v != "" and k not in SKIPPED_PARAMS}
    pertinence, markets = _pertinence(kind, clean, inp.markets)
    rarity = _rarity(kind, clean)
    draft = PlanFact(fid, kind, SECTION_OF[kind], side, clean, source, known_at, claims.classes_of_kind(kind), markets, pertinence,
                     rarity, 0.0, 0.0, False, value)
    novelty = _novelty(kind, clean, known_at, inp.at, draft.key, inp.previous)
    score = round(WEIGHTS[0] * pertinence + WEIGHTS[1] * rarity + WEIGHTS[2] * novelty, 3)
    mandatory = kind in MANDATORY or (kind == "absence.out" and bool(clean.get("key")))
    return PlanFact(fid, kind, SECTION_OF[kind], side, clean, source, known_at, draft.classes, markets, pertinence, rarity, novelty,
                    score, mandatory, value)


def _unique(fid: str, taken: set[str]) -> str:
    out, i = fid, 2
    while out in taken:
        out, i = f"{fid}~{i}", i + 1
    taken.add(out)
    return out


def story_facts(inp: PlanInput, taken: set[str]) -> tuple[list[PlanFact], list[Excluded]]:
    """The story's facts as plan facts. «Nothing left in the table» (``stakes_pressure: settled``) never enters: only the engine proves it."""
    out: list[PlanFact] = []
    excluded: list[Excluded] = []
    for f in inp.story:
        side = f.params.get("side") if f.params.get("side") in ("home", "away") else None
        if f.code == "absence":
            kind = "absence.doubtful" if f.params.get("status") == "doubtful" else "absence.out"
        elif f.code == "key_absences":
            excluded.append(Excluded(f.ref, f.code, "duplicado"))
            continue
        else:
            maybe = STORY_KIND.get(f.code)
            if maybe is None:
                excluded.append(Excluded(f.ref, f.code, "codigo_desconocido"))
                continue
            kind = maybe
        if kind == "table.pressure" and f.params.get("pressure") == "settled":
            excluded.append(Excluded(f.ref, kind, "sin_certificacion_motor"))
            continue
        params = dict(f.params)
        if kind.startswith("absence."):
            params["source_kind"] = "proveedor"
        out.append(_fact(_unique(f.ref, taken), kind, side, params, source="packet", known_at=inp.data_at, inp=inp))
    return out, excluded


def news_facts(inp: PlanInput, taken: set[str]) -> tuple[list[PlanFact], list[Excluded]]:
    """The news by reference, each with its level. A rumour is a rumour: it enters as ``news.rumour`` and in the risks only."""
    out: list[PlanFact] = []
    excluded: list[Excluded] = []
    for n in sorted(inp.news, key=lambda x: x.evidence_id):
        ref = f"E:{n.evidence_id}"
        kind = NEWS_KIND.get(n.status)
        if kind is None:
            excluded.append(Excluded(ref, f"news.{n.status.lower()}", "caducada" if n.status == "OUTDATED" else "estado_desconocido"))
            continue
        if n.retrieved_at is None:
            excluded.append(Excluded(ref, kind, "sin_momento"))
            continue
        if n.retrieved_at > inp.at or (n.published_at is not None and n.published_at > inp.at):
            excluded.append(Excluded(ref, kind, "posterior_al_plan"))
            continue
        if not n.may_read:
            excluded.append(Excluded(ref, kind, "fuente_sin_permiso"))
            continue
        params: dict[str, Any] = {"evidence_id": n.evidence_id, "status": n.status, "topic": n.kind, "side": n.side,
                                  "source": n.source, "content_hash": n.content_hash,
                                  "published": None if n.published_at is None else n.published_at.date().isoformat()}
        if kind == "news.rumour":
            params["level"] = RUMOUR_LEVEL[n.status]
        out.append(_fact(_unique(ref, taken), kind, n.side, params, source="ai.evidence", known_at=n.retrieved_at, inp=inp))
    return out, excluded


def _reading_at(reading: Mapping[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(reading.get("at")))
    except ValueError:
        return None


def scenario_facts(inp: PlanInput, taken: set[str]) -> tuple[list[PlanFact], list[Excluded], str]:
    """What the engine proved for each team of the match, what is open, and what each result of this match does. The third value is the
    reading's status: ``ok``, ``reglamento_no_codificado``, ``sin_lectura`` (none known by ``at``) or ``posterior_al_plan``."""
    reading = inp.scenarios
    if not reading:
        return [], [], "sin_lectura"
    at = _reading_at(reading)
    if at is None or at > inp.at:
        return [], [Excluded("S:reading", "scenario", "posterior_al_plan" if at is not None else "sin_momento")], "posterior_al_plan"
    status = str(reading.get("status") or "")
    if status != "ok":
        return [], [], status or "sin_lectura"
    out: list[PlanFact] = []
    excluded: list[Excluded] = []
    sides = {"home": (inp.home_team_id, inp.home), "away": (inp.away_team_id, inp.away)}
    teams = reading.get("teams") if isinstance(reading.get("teams"), Mapping) else {}
    for side, (team_id, team) in sides.items():
        if team_id is None:
            continue
        verdict = teams.get(str(team_id)) if isinstance(teams, Mapping) else None
        if isinstance(verdict, Mapping) and verdict.get("demostrado") is True and verdict.get("hecho") == FACT_NO_OBJECTIVE:
            out.append(_fact(_unique(f"S:{side}.sin_objetivo", taken), "scenario.no_objective", side,
                             {"team": team, "hecho": FACT_NO_OBJECTIVE, "alcance": verdict.get("alcance")},
                             source="scenarios-v2", known_at=at, inp=inp))
        for table in reading.get("tables") or []:
            if not isinstance(table, Mapping):
                continue
            row = next((r for r in table.get("teams") or [] if isinstance(r, Mapping) and r.get("team") == team_id), None)
            if row is None:
                continue
            for o in row.get("objetivos") or []:
                if not isinstance(o, Mapping):
                    continue
                ref = f"S:{side}.{table.get('key')}.{o.get('objetivo')}"
                proved = isinstance(o.get("decidido"), Mapping) and o["decidido"].get("demostrado") is True
                state = o.get("estado")
                base = {"team": team, "objetivo": o.get("objetivo"), "tabla": table.get("name") or table.get("key"),
                        "puesto": row.get("puesto"), "puntos": row.get("puntos"), "partidos_restantes": row.get("partidos_restantes")}
                if state in ("conseguido", "descartado") and proved:
                    kind = "scenario.secured" if state == "conseguido" else "scenario.lost"
                    out.append(_fact(_unique(ref, taken), kind, side, base | {"estado": state}, source="scenarios-v2", known_at=at,
                                     inp=inp))
                elif state == "abierto":
                    needs: Mapping[str, Any] = o["necesita"] if isinstance(o.get("necesita"), Mapping) else {}
                    depends: Mapping[str, Any] = o["depende_de"] if isinstance(o.get("depende_de"), Mapping) else {}
                    out.append(_fact(_unique(ref, taken), "scenario.open", side,
                                     base | {"estado": "abierto", "puntos_que_lo_aseguran": needs.get("puntos_que_lo_aseguran"),
                                             "depende_de": depends.get("tipo")},
                                     source="scenarios-v2", known_at=at, inp=inp))
                else:
                    excluded.append(Excluded(ref, "scenario", "no_demostrado"))
            effects = (table.get("matches") or {}).get(str(inp.fixture_id)) if isinstance(table.get("matches"), Mapping) else None
            mine = effects.get(side) if isinstance(effects, Mapping) else None
            rows = mine.get("objetivos") if isinstance(mine, Mapping) else None
            for e in rows if isinstance(rows, list) else []:
                if not isinstance(e, Mapping) or e.get("condicional"):
                    continue
                states = {k: (e.get(k) or {}).get("estado") for k in ("victoria", "empate", "derrota") if isinstance(e.get(k), Mapping)}
                if any(s in ("conseguido", "descartado") for s in states.values()):
                    out.append(_fact(_unique(f"S:{side}.{table.get('key')}.{e.get('objetivo')}.efecto", taken), "scenario.result_effect",
                                     side, {"team": team, "objetivo": e.get("objetivo"), **states}, source="scenarios-v2",
                                     known_at=at, inp=inp))
    return out, excluded, "ok"


CORE_FIGURES: Final[frozenset[tuple[str, str, float]]] = frozenset({
    ("1X2", "Home", 0.0), ("1X2", "Draw", 0.0), ("1X2", "Away", 0.0), ("OU", "Over", 2.5), ("OU", "Under", 2.5), ("BTTS", "Yes", 0.0),
    ("BTTS", "No", 0.0)})
"""The figures a chronicle may repeat: the three the page states (the result, more or less than 2.5 goals, both teams to score)."""


def figure_facts(inp: PlanInput, taken: set[str]) -> list[PlanFact]:
    """The single figures of the plan's markets, each with the one way it may be written (``figure_text.cite``)."""
    out: list[PlanFact] = []
    for g in sorted(inp.figures, key=lambda x: (x.market, x.selection, x.line)):
        if (g.market, g.selection, float(g.line)) not in CORE_FIGURES or g.market not in inp.markets:
            continue
        params = {"market": g.market, "selection": g.selection, "line": g.line or None, "seal": g.seal, "reading_id": g.reading_id,
                  "cita": cite(g.reading_id, g.p, version=g.version)}
        out.append(_fact(_unique(f"F:{g.reading_id}", taken), "figure", None, params, source=g.version, known_at=inp.at, inp=inp,
                         value=g.p))
    return out


def unknown_facts(inp: PlanInput, scenario_status: str, taken: set[str]) -> list[PlanFact]:
    """What is not known yet, said by code: the line-ups, a regulation not coded, a reading of the engine that does not exist."""
    out: list[PlanFact] = []
    if inp.lineups_confirmed is not True:
        out.append(_fact(_unique("U:alineaciones", taken), "unknown.lineups", None, {"confirmadas": False}, source="packet",
                         known_at=inp.data_at, inp=inp))
    if scenario_status == "reglamento_no_codificado":
        out.append(_fact(_unique("U:reglamento", taken), "unknown.rules", None, {"competition": inp.competition}, source="scenarios-v2",
                         known_at=inp.at, inp=inp))
    elif scenario_status in ("sin_lectura", "posterior_al_plan"):
        out.append(_fact(_unique("U:escenarios", taken), "unknown.scenarios", None, {"competition": inp.competition}, source="scenarios-v2",
                         known_at=inp.at, inp=inp))
    return out


# ── the plan ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _sections(facts: Sequence[PlanFact]) -> tuple[tuple[SectionPlan, ...], list[Excluded]]:
    out: list[SectionPlan] = []
    excluded: list[Excluded] = []
    for code in SECTIONS:
        mine = [f for f in facts if f.section == code]
        room = CAPS[code] * FACTS_PER_SENTENCE
        mandatory = [f.id for f in mine if f.mandatory][:room]
        ranked = sorted((f for f in mine if not f.mandatory), key=lambda f: (-f.score, f.id))
        optional = [f.id for f in ranked][: max(0, room - len(mandatory))]
        for f in ranked[len(optional):]:
            excluded.append(Excluded(f.id, f.kind, "fuera_del_tope"))
        for f in [f for f in mine if f.mandatory][room:]:
            excluded.append(Excluded(f.id, f.kind, "fuera_del_tope"))
        chosen = len(mandatory) + len(optional)
        cap = min(CAPS[code], chosen)
        out.append(SectionPlan(code, cap, tuple(mandatory), tuple(optional), None if chosen else EMPTY[code]))
    return tuple(out), excluded


def build(inp: PlanInput) -> ContentPlan:
    """The content plan of the match at ``inp.at``. Without a story there is no plan (``SIN_PLAN``); with only what is missing, no data
    (``SIN_DATOS``)."""
    figure_version = next((g.version for g in inp.figures), None)
    scenarios_at = None if not inp.scenarios else str(inp.scenarios.get("at"))
    if inp.thin or (inp.data_at is not None and inp.data_at > inp.at):
        reason = "posterior_al_plan" if inp.data_at is not None and inp.data_at > inp.at else "sin_historia"
        sections = tuple(SectionPlan(c, 0, (), (), EMPTY[c]) for c in SECTIONS)
        return ContentPlan(inp.fixture_id, inp.at, inp.home, inp.away, inp.competition, inp.markets, (), sections,
                           (Excluded("P:packet", "story", reason),), NO_PLAN, inp.packet_id, figure_version, scenarios_at,
                           tuple(sorted(inp.previous)))
    taken: set[str] = set()
    facts, excluded = story_facts(inp, taken)
    found, dropped, status = scenario_facts(inp, taken)
    facts += found
    excluded += dropped
    news, dropped = news_facts(inp, taken)
    facts += news
    excluded += dropped
    facts += figure_facts(inp, taken)
    facts += unknown_facts(inp, status, taken)
    sections, over = _sections(facts)
    excluded += over
    told = [f for s in sections for f in s.facts if not f.startswith("U:")]
    plan = ContentPlan(inp.fixture_id, inp.at, inp.home, inp.away, inp.competition, inp.markets, tuple(facts), sections,
                       tuple(excluded), None if told else NO_DATA, inp.packet_id, figure_version, scenarios_at,
                       tuple(sorted(inp.previous)))
    return plan


def unsupported_high_risk(plan: ContentPlan) -> list[str]:
    """The high-risk classes the plan allows without a planned fact that authorises them: the criterion of AD-F01 (always empty by
    construction; the replay counts it on real matches)."""
    planned = [f.kind for f in plan.planned]
    return [c for c in plan.allowed_classes if c in claims.HIGH_RISK and not claims.authorises(c, planned)]


def keys(plan: ContentPlan) -> frozenset[str]:
    """The keys of a plan's facts: the ``previous`` of the next plan of the match."""
    return frozenset(f.key for f in plan.facts)


def keys_of_json(plan: Mapping[str, Any]) -> frozenset[str]:
    """The same, from a plan stored as JSON (``ai.chronicles.plan``)."""
    return frozenset(str(f["key"]) for f in plan.get("facts") or [] if isinstance(f, Mapping) and f.get("key"))


def previous_for(current: frozenset[str], stored: Mapping[str, Any] | None) -> frozenset[str]:
    """What the next plan's novelty is measured against, given the newest stored plan of the match: its keys when its facts were others; its
    own ``previous`` when they are the same (the same facts, the same plan)."""
    if not stored:
        return frozenset()
    keys_then = keys_of_json(stored)
    if keys_then == current:
        return frozenset(str(k) for k in stored.get("previous_keys") or ())
    return keys_then


def from_json(doc: Mapping[str, Any]) -> ContentPlan:
    """A stored plan read back (the batch's answer is verified against the very plan it was written from)."""
    facts = tuple(PlanFact(str(f["id"]), str(f["kind"]), str(f["section"]), f.get("side"), dict(f.get("params") or {}), str(f["source"]),
                           None if not f.get("known_at") else datetime.fromisoformat(str(f["known_at"])), tuple(f.get("classes") or ()),
                           tuple(f.get("markets") or ()), float(f["pertinence"]), float(f["rarity"]), float(f["novelty"]),
                           float(f["score"]), bool(f["mandatory"]), None if f.get("value") is None else float(f["value"]))
                  for f in doc.get("facts") or [])
    sections = tuple(SectionPlan(str(s["code"]), int(s["cap"]), tuple(s.get("mandatory") or ()), tuple(s.get("optional") or ()),
                                 s.get("abstention")) for s in doc.get("sections") or [])
    excluded = tuple(Excluded(str(e["ref"]), str(e["kind"]), str(e["reason"])) for e in doc.get("excluded") or [])
    match = doc.get("match") or {}
    return ContentPlan(int(doc["fixture_id"]), datetime.fromisoformat(str(doc["at"])), str(match.get("home")), str(match.get("away")),
                       str(match.get("competition")), tuple(doc.get("markets") or MARKETS), facts, sections, excluded,
                       doc.get("abstention"), doc.get("packet_id"), doc.get("figure_version"), doc.get("scenarios_at"),
                       tuple(str(k) for k in doc.get("previous_keys") or ()), str(doc.get("version") or VERSION), str(doc.get("classes_version") or claims.VERSION))


def mandatory_cited(plan: ContentPlan, cited: Iterable[str]) -> tuple[int, int]:
    """How many of the plan's mandatory facts the chronicle cites, of how many (the plan's coverage)."""
    want = {i for s in plan.sections for i in s.mandatory}
    return len(want & set(cited)), len(want)


__all__ = ["ABSTENTIONS", "CAPS", "EMPTY", "EMPTY_VERIFICATION", "MARKETS", "NO_DATA", "NO_PLAN", "RELEVANCE", "SECTIONS", "VERSION",
           "ContentPlan", "Excluded", "FigureIn", "NewsIn", "PlanFact", "PlanInput", "SectionPlan", "build", "from_json", "keys",
           "keys_of_json", "mandatory_cited", "previous_for", "unsupported_high_risk"]
