"""The triage of the hypotheses waiting for a decision (plan RP-8.2, finding H24). The proposal is pure; applying it is the owner's act.

96 hypotheses were proposed (84 by the AI, 12 by the system) and none decided, because they all say the same few things in other words: a draw is overrated,
high odds are overrated, a change of kick-off time breaks the pick, unreported absences should be a feature. This module groups them by VARIABLE AND DIRECTION
(the same variable pushed the same way is the same hypothesis), keeps the best-evidenced one of each group as its representative and gives every hypothesis a
destination, with its reason, so that the owner decides the whole block at once (decision D5):

* ``experiment``: the representative of a group that is worth testing (at most ``MAX_EXPERIMENTS``, the ones with the most matches behind them). Approving
  it queues an experiment; no experiment starts before its protocol is registered (``fbi.research.exp_protocol``).
* ``keep``: stays proposed and is read again at the next triage (a group that did not make the cut, or one the rules cannot classify).
* ``archive``: put aside WITH its reason by one of the five rules of the plan: ``duplicada`` (same variable and direction as another: it is merged into the
  representative and both pieces of evidence are kept), ``ya_respondida`` (an experiment with a verdict covers it), ``no_comprobable`` (asks for a datum that
  does not exist and will not be acquired), ``sin_muestra`` (needs more matches than the segment produces in a season) and ``fuera_de_alcance`` (proposes lowering
  a threshold or touching a probability without an experiment). Archiving is a state, never a deletion, and may be reopened (``fbi.research.cycle_state``).

Nothing here changes a model, a probability, a pick or a threshold. The rules are keyword rules, deliberately plain: what they cannot classify is kept for a
person, never guessed. ``apply`` writes only what the owner approved, only through the transitions the graph allows him, and refuses a plan that does not
match the hypotheses as they are now.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.types.json import Jsonb

from fbi.research import cycle_state

VERSION: Final = "triage-v1"
MAX_EXPERIMENTS: Final = 5
"""At most this many groups go to experiment per triage: each needs its protocol, its sample and its clock."""
UNTRIAGED_LIMIT: Final = 20
"""The permanent threshold of the plan: never more than this many proposed hypotheses without a triage."""

Destination = Literal["experiment", "keep", "archive"]
Rule = Literal["duplicada", "ya_respondida", "no_comprobable", "sin_muestra", "fuera_de_alcance"]
RULES: Final[tuple[Rule, ...]] = ("duplicada", "ya_respondida", "no_comprobable", "sin_muestra", "fuera_de_alcance")
DESTINATIONS: Final[tuple[Destination, ...]] = ("experiment", "keep", "archive")
UNCLASSIFIED: Final = "sin_clasificar"


def plain(text: str) -> str:
    """Lower case, without accents, one space: what the rules read."""
    folded = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"\s+", " ", "".join(c for c in folded if not unicodedata.combining(c))).strip()


@dataclass(frozen=True, slots=True)
class Item:
    """A hypothesis as the triage reads it."""

    id: int
    title: str
    text: str
    status: str
    proposed_by: str
    target: str
    n_matches: int | None = None

    def words(self) -> str:
        return plain(f"{self.title} {self.text}")


@dataclass(frozen=True, slots=True)
class Decision:
    id: int
    destination: Destination
    group: str
    direction: str
    reason: str
    rule: Rule | None = None
    merged_into: int | None = None


# ── the variable and the direction ──────────────────────────────────────────────────────────────────────────────────────────────────────────

_SIGNAL = re.compile(r"la senal '([a-z_]+)' anticipa perdidas")
_BLEND = re.compile(r"^([a-z_0-9]+) adds information to the close in ([a-z_]+): test a blend")
_SHRINK: Final = r"sobre|infla|calibr|encog|contrac|sesgo|extrem|limit"

_RULES: Final[tuple[tuple[str, str, str], ...]] = (
    ("kickoff_changed", "usar_como_senal", r"kickoff_changed|cambios? de hora(rio)?|cambio de hora del partido"),
    ("unreported_absences", "usar_como_feature", r"ausencias? no reportadas?|alertas? de ausencia no reportada"),
    ("correlated_lines", "tratar_como_una_sola", r"lineas? (ah|ah/dc) correlacionadas|ah/dc correlacionadas"),
    ("reviewer_too_lenient", "endurecer_el_revisor", r"revisor.*(aprueb|approve|sobreconfiad|falla)|(aprueba|approve) .*sin senales"),
    ("reviewer_too_strict", "relajar_el_revisor", r"revisor|rechaz|reject|downgrade|degrada|penalizacion"),
    ("p_model_draw", "encoger_hacia_el_mercado", rf"empate.*({_SHRINK})|({_SHRINK}).*empate|empates"),
    ("p_model_lines_under_ah", "encoger_hacia_el_mercado", rf"(under|asian|asiatic|\bah\b|handicap|btts no|over/under|\bou\b).*({_SHRINK})|({_SHRINK}).*(under|asian|\bah\b|handicap)"),
    ("p_model_high_odds", "encoger_hacia_el_mercado", r"cuotas? (altas?|largas?)|cuota alta|>=3|≥3"),
    ("p_model_divergence", "encoger_hacia_el_mercado", r"divergencia|discrepancia|p_model/p_close"),
)

_NOT_CHECKABLE: Final = re.compile(r"clima|lluvia|meteorolog|estado del campo|cesped|terreno de juego")
_OUT_OF_SCOPE: Final = re.compile(r"(bajar|rebajar|relajar|reducir) (el )?umbral|umbral a la baja|aplicar (directamente|sin experimento)|sin experimento")


def classify(item: Item) -> tuple[str, str]:
    """The variable and the direction a hypothesis is about, or (``sin_clasificar``, ``?``) when no rule reads it."""
    words = item.words()
    title = plain(item.title)
    if m := _SIGNAL.search(title):
        return f"signal:{m.group(1)}", "exigir_como_filtro"
    if m := _BLEND.search(title):
        return f"blend:{m.group(1)}:{m.group(2)}", "mezclar_con_el_cierre"
    for key, direction, pattern in _RULES:
        if re.search(pattern, title) or re.search(pattern, words):
            return key, direction
    return UNCLASSIFIED, "?"


# ── the proposal ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _rank(item: Item) -> tuple[int, int]:
    """Best evidenced first (most matches), then the oldest."""
    return (-(item.n_matches or 0), item.id)


def propose(items: Iterable[Item], *, answered: Mapping[str, str] | None = None, unreachable: Mapping[str, str] | None = None,
            max_experiments: int = MAX_EXPERIMENTS) -> list[Decision]:
    """A destination, with its reason, for every PROPOSED hypothesis. Ones in any other state are not read.

    ``answered`` maps a group (``p_model_draw``, ``blend:`` as a prefix) to the experiment with a verdict that covers it; ``unreachable`` maps a group to why its
    sample cannot be reached in a season. Both come from outside because they are measurements, not words: empty, the rules ``ya_respondida`` and
    ``sin_muestra`` simply do not fire."""
    answered, unreachable = answered or {}, unreachable or {}
    waiting = sorted((i for i in items if i.status == "PROPOSED"), key=lambda i: i.id)
    out: dict[int, Decision] = {}
    groups: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for it in waiting:
        key, direction = classify(it)
        words = it.words()
        if _NOT_CHECKABLE.search(words):
            out[it.id] = Decision(it.id, "archive", key, direction, "pide un dato que no existe y no se va a adquirir (clima o estado del campo)", "no_comprobable")
        elif _OUT_OF_SCOPE.search(words):
            out[it.id] = Decision(it.id, "archive", key, direction, "propone bajar un umbral o tocar una probabilidad sin experimento", "fuera_de_alcance")
        elif (cover := next((e for g, e in answered.items() if key == g or key.startswith(g)), None)) is not None:
            out[it.id] = Decision(it.id, "archive", key, direction, f"ya la responde el veredicto de {cover}", "ya_respondida")
        elif key == UNCLASSIFIED:
            out[it.id] = Decision(it.id, "keep", key, direction, "ninguna regla la clasifica: la lee una persona en el siguiente triage")
        elif key in unreachable:
            out[it.id] = Decision(it.id, "archive", key, direction, f"sin muestra alcanzable: {unreachable[key]}", "sin_muestra")
        else:
            groups[(key, direction)].append(it)
    ranked: list[tuple[Item, tuple[str, str], list[Item]]] = []
    for (key, direction), members in groups.items():
        members.sort(key=_rank)
        ranked.append((members[0], (key, direction), members))
    ranked.sort(key=lambda r: (_rank(r[0]), r[1]))
    for position, (rep, (key, direction), members) in enumerate(ranked):
        many = len(members)
        if position < max_experiments:
            out[rep.id] = Decision(rep.id, "experiment", key, direction,
                                   f"representante de {many} hipótesis sobre lo mismo ({many - 1} fusionadas); la de más partidos detrás: {rep.n_matches or 'sin dato'}")
        else:
            out[rep.id] = Decision(rep.id, "keep", key, direction, f"representante de {many} hipótesis sobre lo mismo; no entra en los {max_experiments} experimentos de este triage")
        for other in members[1:]:
            out[other.id] = Decision(other.id, "archive", key, direction, f"misma variable y mismo sentido que #{rep.id}: se fusiona y se conserva la evidencia de ambas",
                                     "duplicada", merged_into=rep.id)
    return [out[i] for i in sorted(out)]


def summary(decisions: Sequence[Decision]) -> dict[str, Any]:
    """The counts the owner decides on: by destination, by rule, and one row per group."""
    by_destination = {d: sum(1 for x in decisions if x.destination == d) for d in DESTINATIONS}
    by_rule = {r: sum(1 for x in decisions if x.rule == r) for r in RULES}
    groups: dict[tuple[str, str], list[Decision]] = defaultdict(list)
    for d in decisions:
        groups[(d.group, d.direction)].append(d)
    rows = [{"group": g, "direction": s, "n": len(ds), "representative": next((d.id for d in ds if d.destination != "archive"), None),
             "destinations": sorted({d.destination for d in ds})} for (g, s), ds in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    return {"version": VERSION, "total": len(decisions), "by_destination": by_destination, "by_rule": by_rule, "groups": rows}


def plan_fingerprint(decisions: Sequence[Decision]) -> str:
    """A fingerprint of the proposal: what the owner approves is exactly this list."""
    canonical = json.dumps([asdict(d) for d in decisions], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{VERSION}\n{canonical}".encode()).hexdigest()


def lines(decisions: Sequence[Decision], items: Mapping[int, Item] | None = None) -> list[str]:
    s = summary(decisions)
    out = [f"Triage de hipótesis ({VERSION}): {s['total']} en espera", "  destino: " + ", ".join(f"{k} {v}" for k, v in s["by_destination"].items()),
           "  reglas de archivo: " + ", ".join(f"{k} {v}" for k, v in s["by_rule"].items()), "Grupos (variable, sentido, cuántas):"]
    for g in s["groups"]:
        out.append(f"  {g['n']:>3}  {g['group']} · {g['direction']}  → {'/'.join(g['destinations'])}" + (f"  (representante #{g['representative']})" if g["representative"] else ""))
    out.append(f"Huella de la propuesta: {plan_fingerprint(decisions)}")
    if items:
        out.append("Una por una:")
        for d in decisions:
            title = items[d.id].title[:80] if d.id in items else ""
            out.append(f"  #{d.id:<4} {d.destination:<10} {d.rule or '-':<16} {title} — {d.reason}")
    return out


# ── reading and applying ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def read(conn: psycopg.Connection[Any]) -> list[Item]:
    """Every hypothesis not yet decided, as the triage reads it."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, title, COALESCE(hypothesis, '') || ' ' || COALESCE(rationale, ''), status, proposed_by, target, "
                    "NULLIF(evidence->>'n_matches', '')::numeric::int FROM analytics.research_hypotheses WHERE status = 'PROPOSED' ORDER BY id")
        return [Item(int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), None if r[6] is None else int(r[6])) for r in cur.fetchall()]


def untriaged(conn: psycopg.Connection[Any]) -> int:
    """How many proposed hypotheses carry no triage in their history: the plan's permanent threshold is ``UNTRIAGED_LIMIT``."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM analytics.research_hypotheses h WHERE h.status = 'PROPOSED' AND NOT EXISTS ("
                    "SELECT 1 FROM jsonb_array_elements(h.stage_history) e WHERE e ? 'triage')")
        row = cur.fetchone()
    return 0 if row is None else int(row[0])


class PlanRefusedError(ValueError):
    """The plan to apply does not match the hypotheses as they are, or was not signed by the owner."""


def apply(conn: psycopg.Connection[Any], decisions: Sequence[Decision], *, claimed_fingerprint: str, user_id: int, at: datetime,
          confirmed_by_owner: bool) -> dict[str, int]:
    """Write what the owner approved, in one transaction: the plan must carry its own fingerprint and every hypothesis in it must still be PROPOSED.

    ``experiment`` → ACCEPTED (the owner's approval of the experiment; the experiment itself waits for its protocol); ``archive`` → ARCHIVED with the rule and,
    for a duplicate, the hypothesis it was merged into; ``keep`` → still PROPOSED, with the triage noted so it is not counted as waiting. Every move goes
    through ``cycle_state.check`` as the owner's."""
    if not confirmed_by_owner:
        raise PlanRefusedError("la aplica solo el dueño: falta su confirmación")
    if plan_fingerprint(decisions) != claimed_fingerprint:
        raise PlanRefusedError("la huella no es la de la propuesta que se le mostró al dueño")
    done: dict[str, int] = dict.fromkeys(DESTINATIONS, 0)
    with conn.transaction(), conn.cursor() as cur:
        for d in decisions:
            cur.execute("SELECT status FROM analytics.research_hypotheses WHERE id = %s FOR UPDATE", (d.id,))
            row = cur.fetchone()
            if row is None or row[0] != "PROPOSED":
                raise PlanRefusedError(f"#{d.id} ya no está en espera ({'no existe' if row is None else row[0]}): se pide una propuesta nueva")
            target = {"experiment": cycle_state.ACCEPTED, "archive": cycle_state.ARCHIVED, "keep": cycle_state.PROPOSED}[d.destination]
            if target != cycle_state.PROPOSED:
                cycle_state.check(cycle_state.PROPOSED, target, by="owner")
            entry = {"from": "PROPOSED", "to": target, "at": at.isoformat(), "by": user_id, "note": d.reason[:500],
                     "triage": {"version": VERSION, "destination": d.destination, "group": d.group, "direction": d.direction, "rule": d.rule,
                                "merged_into": d.merged_into}}
            if d.destination == "keep":
                cur.execute("UPDATE analytics.research_hypotheses SET stage_history = stage_history || %s::jsonb WHERE id = %s", (Jsonb([entry]), d.id))
            else:
                cur.execute("UPDATE analytics.research_hypotheses SET status = %s, decided_at = %s, decided_by = %s, decision_note = %s, "
                            "stage_history = stage_history || %s::jsonb WHERE id = %s", (target, at, user_id, d.reason[:500], Jsonb([entry]), d.id))
            done[d.destination] += 1
    return done


__all__ = [
    "DESTINATIONS",
    "MAX_EXPERIMENTS",
    "RULES",
    "UNCLASSIFIED",
    "UNTRIAGED_LIMIT",
    "VERSION",
    "Decision",
    "Item",
    "PlanRefusedError",
    "apply",
    "classify",
    "lines",
    "plain",
    "plan_fingerprint",
    "propose",
    "read",
    "summary",
    "untriaged",
]
