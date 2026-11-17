"""The chronicle after the official line-up, and the why of each selection (IA-116, plan piece AD-F03). Pure: by template, NO model.

TWO TEXTS, both versioned and timed, both from the same facts as the chronicle:

``lineup-update-v1`` - the paragraph added when the official line-up arrives (E3 of ``eval-cycle-v1``). It is written by TEMPLATE from the
facts of E3 (who starts, who is on the bench, who is not listed) set against the facts the chronicle's plan already holds about players - an
absence (``absence.out``), a doubt (``absence.doubtful``) and the top scorer (``top_scorer``). No model runs in E3's window (it must last under
two minutes; AD-D06): this module has no model to call. Each sentence cites the plan's fact and the line-up's (``A:<side>``). A chronicle's
sentence the line-up makes outdated - a player it said was out who starts - is listed as ``superseded`` (section and index): it is never
rewritten (the earlier chronicle stays legible as it was) and the update is what corrects it, at its hour.

``selection-why-v1`` - the why of each selection the evaluation cycle judged at E3: one sentence from the record of decision-v2 as E3 left it
(``intel.eval_verdicts``: state, reason, the decision it judged with), then the chronicle's own sentences about that market CITED by their
index (the plan's facts carry the markets they are pertinent to), each copied as the verifier let it stand - or the update's sentence when
the line-up superseded it. Every phrase carries its ORIGIN (``decision``, ``chronicle`` or ``update``): a phrase without one is not written.
The explanation cannot contradict the chronicle: it says nothing the chronicle or the decision did not.

No betting language, no promise of return, no number but the line-up's hour and the line of a market (``tests`` hold the templates to the
verifier's own list of forbidden words). Nothing here reaches a reader: the rows go to ``ai.chronicles`` in shadow (``update_job``)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from fbi.chronicle.plan import SECTIONS, ContentPlan, PlanFact
from fbi.chronicle.review import fold as fold_name
from fbi.core.calendar import DAY_TZ

VERSION: Final = "lineup-update-v1"
WHY_VERSION: Final = "selection-why-v1"
PLAYER_KINDS: Final = ("absence.out", "absence.doubtful", "top_scorer")
"""The plan's facts about a player the line-up can confirm or overturn."""
MAX_CITED: Final = 3
"""Chronicle sentences cited per selection: the first ones of the sections' order that touch its market."""

STARTS, BENCH, NOT_LISTED, NOT_PLACED = "titular", "suplente", "no_convocado", "sin_ubicar"


# ── the line-up E3 read ──────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Player:
    side: str
    provider_id: int
    name: str
    starter: bool


@dataclass(frozen=True, slots=True)
class LineUp:
    """The official line-up as E3 read it: the run, its moment, and each side's sheet (starters and bench)."""

    run_id: int
    cause_key: str
    at: datetime
    """When the line-up was first seen (E3's ``trigger_at``)."""
    known_at: datetime
    """When E3 judged it (the update is written after this)."""
    players: tuple[Player, ...]
    sides: tuple[str, ...]
    """The sides whose sheet is known."""

    def status(self, side: str, name: str) -> str:
        if side not in self.sides:
            return NOT_PLACED
        wanted = fold_name(name)
        found = [p for p in self.players if p.side == side and fold_name(p.name) == wanted]
        if found:
            return STARTS if any(p.starter for p in found) else BENCH
        words = {w for w in wanted.split() if len(w) >= 4}
        if any(words & set(fold_name(p.name).split()) for p in self.players if p.side == side):
            return NOT_PLACED  # a name spelled another way would look the same: never guessed
        return NOT_LISTED


# ── the paragraph ────────────────────────────────────────────────────────────────────────────────────────────────────────────

TEMPLATES: Final[dict[tuple[str, str], tuple[str, str]]] = {
    ("absence.out", STARTS): ("{player} ({team}), que el proveedor de datos daba como baja, figura como titular en la alineación oficial.",
                              "{player} ({team}), listed as out by the data provider, is in the official starting line-up."),
    ("absence.out", BENCH): ("{player} ({team}), que el proveedor de datos daba como baja, está entre los suplentes de la alineación oficial.",
                             "{player} ({team}), listed as out by the data provider, is among the substitutes of the official line-up."),
    ("absence.out", NOT_LISTED): ("{player} ({team}) no figura en la alineación oficial, como indicaba el proveedor de datos.",
                                  "{player} ({team}) is not in the official line-up, as the data provider said."),
    ("absence.doubtful", STARTS): ("{player} ({team}), que estaba en duda, figura como titular en la alineación oficial.",
                                   "{player} ({team}), who was a doubt, is in the official starting line-up."),
    ("absence.doubtful", BENCH): ("{player} ({team}), que estaba en duda, empieza en el banco.",
                                  "{player} ({team}), who was a doubt, starts on the bench."),
    ("absence.doubtful", NOT_LISTED): ("{player} ({team}), que estaba en duda, no figura en la alineación oficial.",
                                       "{player} ({team}), who was a doubt, is not in the official line-up."),
    ("top_scorer", STARTS): ("{player}, máximo goleador de {team}, figura como titular.", "{player}, top scorer of {team}, starts."),
    ("top_scorer", BENCH): ("{player}, máximo goleador de {team}, empieza en el banco.", "{player}, top scorer of {team}, starts on the bench."),
    ("top_scorer", NOT_LISTED): ("{player}, máximo goleador de {team}, no figura en la alineación oficial.",
                                 "{player}, top scorer of {team}, is not in the official line-up."),
}
"""The sentence of each fact and what the line-up says of it. Every pair is held to the verifier's forbidden words (tests)."""
OVERTURNS: Final = frozenset({("absence.out", STARTS), ("absence.out", BENCH), ("absence.doubtful", STARTS), ("absence.doubtful", BENCH),
                              ("absence.doubtful", NOT_LISTED), ("top_scorer", BENCH), ("top_scorer", NOT_LISTED)})
"""What makes a chronicle's sentence about that fact outdated: it is then ``superseded`` by the update."""


def _hour(at: datetime) -> str:
    return at.astimezone(DAY_TZ).strftime("%H:%M")


def _team(plan: ContentPlan, f: PlanFact) -> str:
    team = f.params.get("team")
    if isinstance(team, str) and team:
        return team
    return plan.home if f.side == "home" else plan.away


def opening(plan: ContentPlan, lineup: LineUp) -> dict[str, Any]:
    hour = _hour(lineup.at)
    if set(lineup.sides) >= {"home", "away"}:
        es = f"Las alineaciones oficiales se conocieron a las {hour} (hora de Bogotá)."
        en = f"The official line-ups were known at {hour} (Bogotá time)."
    else:
        side = lineup.sides[0] if lineup.sides else "home"
        team = plan.home if side == "home" else plan.away
        es = f"La alineación oficial de {team} se conoció a las {hour} (hora de Bogotá); la del rival aún no."
        en = f"The official line-up of {team} was known at {hour} (Bogotá time); the opponent's is not out yet."
    return {"es": es, "en": en, "facts": [f"A:{s}" for s in sorted(lineup.sides)], "kind": "alineacion"}


@dataclass(frozen=True, slots=True)
class Update:
    content: dict[str, Any]
    """The block ``actualizacion`` of the chronicle's new version."""
    told: Mapping[str, dict[str, Any]]
    """By the plan's fact id: the update's sentence about it (the why cites it instead of a superseded sentence)."""
    superseded: tuple[tuple[str, int], ...]


def _cites(content: Mapping[str, Any], fact_ids: Iterable[str]) -> list[tuple[str, int]]:
    wanted = set(fact_ids)
    out: list[tuple[str, int]] = []
    for section in SECTIONS:
        for i, s in enumerate((content.get("es") or {}).get(section) or []):
            if wanted & set(s.get("facts") or []):
                out.append((section, i))
    return out


def paragraph(plan: ContentPlan, lineup: LineUp, chronicle: Mapping[str, Any] | None, *, chronicle_id: int | None) -> Update:
    """The update of a chronicle (``chronicle``: its verified content, None when it abstained) for the line-up E3 read."""
    sentences = [opening(plan, lineup)]
    told: dict[str, dict[str, Any]] = {}
    unplaced: list[str] = []
    overturned: list[str] = []
    for f in plan.planned:
        if f.kind not in PLAYER_KINDS or f.side not in ("home", "away") or not isinstance(f.params.get("player"), str):
            continue
        state = lineup.status(f.side, str(f.params["player"]))
        if state == NOT_PLACED:
            unplaced.append(f.id)
            continue
        es, en = TEMPLATES[(f.kind, state)]
        names = {"player": f.params["player"], "team": _team(plan, f)}
        s = {"es": es.format(**names), "en": en.format(**names), "facts": [f.id, f"A:{f.side}"], "kind": f"{f.kind}:{state}"}
        sentences.append(s)
        told[f.id] = s
        if (f.kind, state) in OVERTURNS:
            overturned.append(f.id)
    superseded = tuple(_cites(chronicle, overturned)) if chronicle else ()
    content = {
        "version": VERSION, "at": lineup.known_at.isoformat(), "lineup_at": lineup.at.isoformat(), "e3_run_id": lineup.run_id,
        "cause_key": lineup.cause_key, "sides": list(lineup.sides), "base_chronicle_id": chronicle_id,
        "es": [s["es"] for s in sentences], "en": [s["en"] for s in sentences],
        "sentences": sentences, "superseded": [{"section": a, "index": b} for a, b in superseded], "unplaced": unplaced,
    }
    return Update(content, told, superseded)


# ── the why of a selection ──────────────────────────────────────────────────────────────────────────────────────────────────

PLAN_MARKET: Final[dict[str, str]] = {"1X2": "1X2", "DC": "1X2", "AH": "1X2", "OU": "OU", "BTTS": "BTTS"}
"""The plan's market a selection's market is told under (the result, the goals, both teams scoring)."""

STATE_WORDS: Final[dict[str, tuple[str, str]]] = {
    "confirmada_sombra": ("queda confirmada en la sombra", "stays confirmed in the shadow"),
    "pendiente_alineaciones": ("sigue a la espera de la alineación", "is still waiting for the line-up"),
    "retirada": ("queda retirada", "is withdrawn"),
    "en_evaluacion": ("sigue en evaluación", "is still under evaluation"),
    "en_investigacion": ("sigue en revisión de contexto", "is still being looked into"),
    "descartada": ("queda descartada", "is discarded"),
    "detectado": ("queda detectada, sin evaluar", "is detected, not evaluated yet"),
}
REASON_WORDS: Final[dict[str, tuple[str, str]]] = {
    "cumple_todo": ("cumple todos los criterios del motor", "it meets every criterion of the engine"),
    "cumple_salvo_validacion": ("cumple los criterios del motor salvo la validación de su mercado",
                                "it meets the engine's criteria except the validation of its market"),
    "depende_de_alineacion": ("depende de jugadores cuya alineación aún no se conoce", "it depends on players whose line-up is not known yet"),
    "baja_por_confirmar": ("una baja de la que depende aún no está confirmada", "an absence it depends on is not confirmed yet"),
    "alineacion_en_contra": ("la alineación oficial deja fuera a jugadores de los que depende", "the official line-up leaves out players it depends on"),
    "valor_insuficiente": ("la diferencia entre la cifra de PrediGol y el precio del mercado no llega al mínimo del motor",
                           "the gap between PrediGol's figure and the market price does not reach the engine's minimum"),
    "precio_antiguo": ("el precio disponible es demasiado antiguo", "the available price is too old"),
    "sin_precio": ("no hay precio de mercado vigente", "there is no current market price"),
    "datos_insuficientes": ("faltan datos para evaluarla", "data to evaluate it is missing"),
    "sin_modelo": ("no hay cifra del modelo para este mercado", "there is no model figure for this market"),
    "mercado_estrecho": ("el mercado tiene muy pocas casas", "the market has too few bookmakers"),
    "precio_atipico": ("el precio del mercado es atípico", "the market price is atypical"),
    "contexto_lo_impide": ("el contexto del partido lo impide", "the match's context prevents it"),
    "baja_clave_confirmada": ("hay una baja clave confirmada", "a key absence is confirmed"),
    "sin_calibrar": ("su cifra no está calibrada", "its figure is not calibrated"),
    "revision_en_contra": ("la revisión está en contra", "the review is against it"),
    "riesgo": ("el motor registra un riesgo", "the engine records a risk"),
    "otra_del_partido": ("ya hay otra selección del mismo partido", "there is already another selection of the same match"),
    "en_curso": ("la evaluación sigue en curso", "the evaluation is still going on"),
    "contexto_pendiente": ("falta contexto del partido", "context of the match is missing"),
    "hecho_nuevo": ("hay un hecho nuevo por revisar", "there is a new fact to look at"),
    "hecho_en_contra": ("un hecho nuevo va en contra", "a new fact goes against it"),
    "partido_no_jugado": ("el partido no se juega como estaba previsto", "the match is not played as planned"),
    "candidato_nuevo": ("es un candidato nuevo", "it is a new candidate"),
}
"""The closed words of each state and reason (``fbi.lifecycle.machine``). A reason not here is told as one the system records without words."""
UNKNOWN_REASON: Final = ("el sistema registra un motivo sin descripción", "the system records a reason without a description")


@dataclass(frozen=True, slots=True)
class Selection:
    """One selection as E3 left it (``intel.eval_verdicts``)."""

    verdict_id: int
    market_key: str
    selection: str
    line: float
    state: str
    reason: str
    verdict: str
    decision_id: int | None


def label(s: Selection, plan: ContentPlan) -> tuple[str, str]:
    """The selection in words (no code): «victoria de Millonarios», «más de 2,5 goles»..."""
    line = f"{s.line:g}"
    line_es = line.replace(".", ",")
    home, away = plan.home, plan.away
    words: dict[tuple[str, str], tuple[str, str]] = {
        ("1X2", "Home"): (f"victoria de {home}", f"{home} to win"), ("1X2", "Draw"): ("empate", "a draw"),
        ("1X2", "Away"): (f"victoria de {away}", f"{away} to win"),
        ("OU", "Over"): (f"más de {line_es} goles", f"over {line} goals"), ("OU", "Under"): (f"menos de {line_es} goles", f"under {line} goals"),
        ("BTTS", "Yes"): ("marcan los dos equipos", "both teams score"), ("BTTS", "No"): ("no marcan los dos equipos", "not both teams score"),
        ("DC", "1X"): (f"{home} o empate", f"{home} or a draw"), ("DC", "X2"): (f"{away} o empate", f"{away} or a draw"),
        ("DC", "12"): (f"{home} o {away}", f"{home} or {away}"),
        ("AH", "Home"): (f"{home} con hándicap asiático {line_es}", f"{home} on the Asian handicap {line}"),
        ("AH", "Away"): (f"{away} con hándicap asiático {line_es}", f"{away} on the Asian handicap {line}"),
    }
    return words.get((s.market_key, s.selection), (f"{s.market_key} {s.selection} {line_es}", f"{s.market_key} {s.selection} {line}"))


def _pertinent(plan: ContentPlan, market: str | None, fact_ids: Iterable[str]) -> bool:
    by = plan.by_id()
    for fid in fact_ids:
        f = by.get(fid)
        if f is not None and market is not None and market in f.markets:
            return True
    return False


def why(s: Selection, plan: ContentPlan, chronicle: Mapping[str, Any] | None, update: Update, *, chronicle_id: int | None,
        at: datetime) -> dict[str, Any]:
    """The why of one selection: the decision's sentence, then the chronicle's sentences about its market (by index) or the update's."""
    name_es, name_en = label(s, plan)
    state_es, state_en = STATE_WORDS.get(s.state, (f"queda en el estado {s.state.replace('_', ' ')}", f"is {s.state.replace('_', ' ')}"))
    reason_es, reason_en = REASON_WORDS.get(s.reason, UNKNOWN_REASON)
    phrases: list[dict[str, Any]] = [{
        "es": f"Tras la alineación oficial, «{name_es}» {state_es}: {reason_es}.",
        "en": f"After the official line-up, «{name_en}» {state_en}: {reason_en}.",
        "origin": {"kind": "decision", "verdict_id": s.verdict_id, "decision_id": s.decision_id, "state": s.state, "reason": s.reason}}]
    market = PLAN_MARKET.get(s.market_key)
    superseded = set(update.superseded)
    for section in SECTIONS:
        for i, sentence in enumerate(((chronicle or {}).get("es") or {}).get(section) or []):
            if len(phrases) > MAX_CITED or not _pertinent(plan, market, sentence.get("facts") or []):
                continue
            if (section, i) in superseded:
                newer = next((update.told[f] for f in sentence.get("facts") or [] if f in update.told), None)
                if newer is None:
                    continue
                phrases.append({"es": newer["es"], "en": newer["en"],
                                "origin": {"kind": "update", "version": VERSION, "facts": newer["facts"], "replaces": [section, i]}})
                continue
            en_text = ((chronicle or {}).get("en") or {}).get(section, [])[i]["text"]
            phrases.append({"es": sentence["text"], "en": en_text,
                            "origin": {"kind": "chronicle", "chronicle_id": chronicle_id, "section": section, "index": i}})
    return {"version": WHY_VERSION, "at": at.isoformat(), "verdict_id": s.verdict_id, "decision_id": s.decision_id,
            "market_key": s.market_key, "selection": s.selection, "line": s.line, "state": s.state, "reason": s.reason,
            "verdict": s.verdict, "phrases": phrases}


def without_origin(explanations: Sequence[Mapping[str, Any]]) -> list[str]:
    """The phrases of the explanations that carry no origin (the criterion of AD-F03: none)."""
    out: list[str] = []
    for e in explanations:
        for p in e.get("phrases") or []:
            o = p.get("origin") if isinstance(p, Mapping) else None
            if not isinstance(o, Mapping) or o.get("kind") not in ("decision", "chronicle", "update"):
                out.append(str(p.get("es") if isinstance(p, Mapping) else p))
    return out


def content_of(base: Mapping[str, Any] | None, update: Update, explanations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The new version of the chronicle: the verified sections as they were (when there were), the update and the whys."""
    out: dict[str, Any] = {}
    if base:
        out["es"], out["en"] = base.get("es") or {}, base.get("en") or {}
    out["actualizacion"] = update.content
    out["selecciones"] = list(explanations)
    return out


def input_hash(base_id: int | None, lineup: LineUp, explanations: Sequence[Mapping[str, Any]]) -> str:
    body = {"v": VERSION, "why": WHY_VERSION, "base": base_id, "run": lineup.run_id, "key": lineup.cause_key,
            "selections": [e["verdict_id"] for e in explanations]}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


__all__ = ["MAX_CITED", "PLAN_MARKET", "REASON_WORDS", "STATE_WORDS", "TEMPLATES", "VERSION", "WHY_VERSION", "LineUp", "Player",
           "Selection", "Update", "content_of", "input_hash", "label", "opening", "paragraph", "why", "without_origin"]
