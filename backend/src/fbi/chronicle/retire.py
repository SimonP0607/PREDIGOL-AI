"""The safe retirement of the duplicated texts (IA-119, plan piece AD-F05): ``retire-compare-v1``. A PREREGISTERED comparison and the steps.

Nothing here turns anything off. It says, for the same matches, whether the single chronicle (``chronicle-v4``) is at least as good as each
text it would replace - the readers' chronicle (``user-narrative-v3``), the narrative of the brief (``brief-v8``) and the analysis cards
(``match-analysis-v1``) - and, text by text, which EXISTING switch retires it and how it comes back. Each retirement is the owner's act and
signature; none is signed here (``SIGNATURES`` is empty), and no row of any table is deleted: a retired text's table stays, read-only.

THE COMPARISON (written before it is run; the margins are PROPOSALS for the owner to sign):

    population   the matches PrediGol Intelligence analysed in the window for which the single chronicle was attempted (``ai.chronicles``):
                 every text is measured on those same matches
    support      of the answered attempts, those that left a text a reader could be shown (v4: ``ok``/``partial``; v3: ``ok``; the brief:
                 ``ok`` by the model with its narrative) - higher is better; v4 must be BETTER here (its interval above the other's)
    coverage     of the population, the matches with at least one accepted text before kick-off - higher is better
    unsupported  of the accepted texts measured, those with a sentence of a high-risk class (``claim-classes-v1``) the match's content plan
                 does not authorise - the contradictions with the engine («nada en juego» while an objective is open) - lower is better
    stock        of their sentences, the stock phrases (``repeat-check-v1``'s closed list) - lower is better
    cost         US$ per accepted text (no interval: a ratio of sums, said so) - lower is better

    not worse    a rate: v4's 95 % interval (Wilson) reaches the other's rate within ``MARGIN``; the cost: at most ``COST_MARGIN`` above
    sample       at least ``MIN_MATCHES`` matches, or the verdict is INSUFICIENTE

Pure (the rows are read by ``rows_for``, read-only SELECTs)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

from fbi.ai.intervals import wilson
from fbi.chronicle import claims, repetition
from fbi.chronicle import plan as cp
from fbi.narrative.job import fold

VERSION: Final = "retire-compare-v1"
CHRONICLE: Final = "chronicle-v4"
TEXTS: Final[tuple[str, ...]] = ("user-narrative-v3", "brief-v8", "match-analysis-v1")
MIN_MATCHES: Final = 100
MARGIN: Final = 0.05
COST_MARGIN: Final = Decimal("0.10")
"""PROPOSED (unsigned): a rate may be at most five points worse within its interval; a cost at most 10 % higher."""
SIGNATURES: Final[Mapping[str, str]] = {}
"""The owner's signature of each retirement, by text, when given (a commit that records their words). Empty: none is signed."""
SENTENCE: Final = re.compile(r"(?<=[.!?])\s+")

Better = Literal["higher", "lower"]
METRICS: Final[dict[str, Better]] = {"support": "higher", "coverage": "higher", "unsupported": "lower", "stock": "lower", "cost": "lower"}
APPLIES: Final[dict[str, tuple[str, ...]]] = {"user-narrative-v3": tuple(METRICS), "brief-v8": tuple(METRICS), "match-analysis-v1": ("coverage",)}
"""The analysis cards are built by rules (no model, no prose, no cost): only their coverage is compared."""


# ── the steps, one per text, with the switches that exist today ─────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Step:
    text: str
    order: int
    table: str
    switch: str | None
    off: str | None
    back: str
    note: str


STEPS: Final[tuple[Step, ...]] = (
    Step("user-narrative-v3", 1, "ai.user_narratives", "FBI_USER_NARRATIVE", "off",
         "volver a poner FBI_USER_NARRATIVE en la palabra que tenía (on o shadow); sus filas están intactas",
         "su interruptor apaga el trabajo del worker (ya no escribe ni paga) y lo que ven los lectores; C-01 cae a la crónica única o a su "
         "abstención con código"),
    Step("brief-v8", 2, "ai.match_briefs", None, None,
         "nada que volver a encender: no se apagó nada",
         "NO tiene interruptor propio: el brief se escribe dentro del pase del día (fbi.ai.cycle) y además decide la escalada; FBI_AI_MODE=off "
         "apagaría toda la revisión de la IA, no solo su narrativa. Retirar solo la narrativa necesita una pieza aparte con su interruptor"),
    Step("match-analysis-v1", 3, "ai.match_analyses", None, None,
         "nada que volver a encender: no se apagó nada",
         "NO tiene interruptor propio: las tarjetas las construye el ciclo del día por reglas (sin modelo ni coste) y las sirve la ruta del "
         "análisis del partido; retirarlas para lectores necesita una pieza aparte (un interruptor de lector es de la sesión UX)"),
)


def step_state(step: Step, verdict: str | None) -> str:
    """Where a retirement stands: ``sin_interruptor`` (none exists), ``esperando_comparacion``, ``no_cumple``, ``lista_para_firma`` or
    ``firmada`` (only with the owner's signature in ``SIGNATURES``; the switch is still the owner's to change)."""
    if step.switch is None:
        return "sin_interruptor"
    if step.text in SIGNATURES:
        return "firmada"
    if verdict is None or verdict == "INSUFICIENTE":
        return "esperando_comparacion"
    return "lista_para_firma" if verdict == "CUMPLE" else "no_cumple"


# ── what a screen shows: never nothing ──────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Shown:
    kind: Literal["chronicle", "legacy", "abstention"]
    version: str
    """The text's version, or the abstention's code."""


def shown(chronicle: Mapping[str, Any] | None, *, retired: Iterable[str], legacy_ok: bool) -> Shown:
    """What C-01's chronicle slot would show for a match: the single chronicle when it has text; else the readers' chronicle while it is
    not retired and has one; else the abstention with its code (the chronicle's, or ``SIN_PLAN`` when none was even attempted)."""
    if chronicle is not None and chronicle.get("status") in ("ok", "partial") and chronicle.get("content"):
        return Shown("chronicle", str(chronicle.get("version") or CHRONICLE))
    if legacy_ok and "user-narrative-v3" not in set(retired):
        return Shown("legacy", "user-narrative-v3")
    code = None if chronicle is None else chronicle.get("abstention")
    return Shown("abstention", str(code) if code in cp.ABSTENTIONS else cp.NO_PLAN)


# ── the measures ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def sentences_v4(content: Mapping[str, Any]) -> list[str]:
    return [str(s.get("text")) for section in cp.SECTIONS for s in (content.get("es") or {}).get(section) or []]


def sentences_v3(content: Mapping[str, Any]) -> list[str]:
    return [str(s.get("text")) for sec in content.get("es") or [] if isinstance(sec, Mapping) for s in sec.get("sentences") or []]


def sentences_brief(narrative: Mapping[str, Any] | None) -> list[str]:
    out: list[str] = []
    for v in (narrative or {}).values():
        if isinstance(v, str) and v.strip():
            out += [x for x in SENTENCE.split(v.strip()) if x]
    return out


def unauthorised(sentences: Sequence[str], plan: cp.ContentPlan | None) -> list[str] | None:
    """The high-risk classes the sentences state that the plan does not authorise (None: no plan to judge by)."""
    if plan is None:
        return None
    allowed = set(plan.allowed_classes)
    found = {c for s in sentences for c in claims.classes_stated(fold(s), "es")}
    return sorted(c for c in found if c in claims.HIGH_RISK and c not in allowed)


@dataclass
class Tally:
    text: str
    matches: int = 0
    attempts: int = 0
    accepted: int = 0
    covered: int = 0
    measured: int = 0
    unsupported: int = 0
    sentences: int = 0
    stock: int = 0
    cost: Decimal = Decimal(0)
    examples: list[str] = field(default_factory=list)

    def rate(self, metric: str) -> tuple[int, int]:
        return {"support": (self.accepted, self.attempts), "coverage": (self.covered, self.matches),
                "unsupported": (self.unsupported, self.measured), "stock": (self.stock, self.sentences)}[metric]

    def cost_per_accepted(self) -> Decimal | None:
        return None if self.accepted == 0 else (self.cost / self.accepted).quantize(Decimal("0.000001"))

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"text": self.text, "matches": self.matches, "attempts": self.attempts, "accepted": self.accepted,
                               "cost_usd": str(self.cost), "cost_per_accepted_usd": None if self.cost_per_accepted() is None
                               else str(self.cost_per_accepted()), "examples": self.examples[:5]}
        for m in ("support", "coverage", "unsupported", "stock"):
            k, n = self.rate(m)
            ci = wilson(k, n) if n else None
            out[m] = {"k": k, "n": n, "rate": None if not n else round(k / n, 4),
                      "ci95": None if ci is None else [round(ci[0], 4), round(ci[1], 4)]}
        return out


def _text(t: Tally, sentences: Sequence[str], plan: cp.ContentPlan | None) -> None:
    t.sentences += len(sentences)
    t.stock += sum(1 for s in sentences if repetition.generic_formula(s, "") is not None)
    bad = unauthorised(sentences, plan)
    if bad is not None:
        t.measured += 1
        if bad:
            t.unsupported += 1
            if len(t.examples) < 5:
                t.examples.append(", ".join(bad))


def tally(matches: Mapping[int, datetime], rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Tally]:
    """Every text measured on the same matches. ``rows``: by text, its attempts (``fixture_id``, ``created_at``, ``status``, ``cost_usd`` and
    what holds its words); ``chronicle-v4``'s rows carry their ``plan``, which judges every text of the match."""
    out = {name: Tally(name) for name in (CHRONICLE, *TEXTS)}
    plans: dict[int, cp.ContentPlan] = {}
    for r in sorted(rows.get(CHRONICLE, []), key=lambda x: x["created_at"]):
        if r["fixture_id"] in matches and r["created_at"] < matches[r["fixture_id"]] and isinstance(r.get("plan"), Mapping):
            plans[int(r["fixture_id"])] = cp.from_json(r["plan"])
    for name, t in out.items():
        t.matches = len(matches)
        covered: set[int] = set()
        for r in rows.get(name, []):
            fid = int(r["fixture_id"])
            if fid not in matches or r["created_at"] >= matches[fid]:
                continue
            t.cost += Decimal(str(r.get("cost_usd") or 0))
            if name == "match-analysis-v1":
                t.attempts += 1
                t.accepted += 1
                covered.add(fid)
                continue
            if name == CHRONICLE and r.get("status") == "abstained":
                continue  # an abstention is no answered attempt
            t.attempts += 1
            ok = {"chronicle-v4": r.get("status") in ("ok", "partial"), "user-narrative-v3": r.get("status") == "ok",
                  "brief-v8": r.get("status") == "ok" and r.get("engine") == "llm" and bool(sentences_brief(r.get("narrative")))}[name]
            if not ok:
                continue
            t.accepted += 1
            covered.add(fid)
            words = (sentences_v4(r["content"]) if name == CHRONICLE else sentences_v3(r["content"]) if name == "user-narrative-v3"
                     else sentences_brief(r.get("narrative")))
            _text(t, words, plans.get(fid))
        t.covered = len(covered)
    return out


def compare_one(v4: Tally, other: Tally) -> dict[str, Any]:
    """v4 against one text, metric by metric, under the preregistered rule."""
    result: dict[str, Any] = {}
    for metric, better in METRICS.items():
        if metric not in APPLIES.get(other.text, tuple(METRICS)):
            result[metric] = {"verdict": "NO_APLICA"}
            continue
        if metric == "cost":
            mine, theirs = v4.cost_per_accepted(), other.cost_per_accepted()
            if mine is None or theirs is None:
                result[metric] = {"verdict": "INSUFICIENTE"}
            else:
                result[metric] = {"verdict": "NO_PEOR" if mine <= theirs * (1 + COST_MARGIN) else "PEOR", "v4": str(mine), "other": str(theirs)}
            continue
        (k1, n1), (k2, n2) = v4.rate(metric), other.rate(metric)
        if n1 == 0 or n2 == 0:
            result[metric] = {"verdict": "INSUFICIENTE"}
            continue
        lo1, hi1 = wilson(k1, n1) or (0.0, 1.0)
        lo2, hi2 = wilson(k2, n2) or (0.0, 1.0)
        r2 = k2 / n2
        if better == "higher":
            not_worse, ahead = lo1 >= r2 - MARGIN, lo1 > hi2
        else:
            not_worse, ahead = hi1 <= r2 + MARGIN, hi1 < lo2
        result[metric] = {"verdict": "MEJOR" if ahead else "NO_PEOR" if not_worse else "PEOR", "v4": round(k1 / n1, 4), "other": round(r2, 4)}
    return result


def verdict_of(v4: Tally, other: Tally, compared: Mapping[str, Mapping[str, Any]]) -> str:
    """CUMPLE: enough matches, not worse in any measurable metric and better in support (where support applies). NO_CUMPLE otherwise.
    INSUFICIENTE: too few matches."""
    if v4.matches < MIN_MATCHES or other.attempts == 0:
        return "INSUFICIENTE"
    verdicts = {m: str(c["verdict"]) for m, c in compared.items()}
    needs_support = "support" in APPLIES.get(other.text, tuple(METRICS))
    if needs_support and verdicts.get("support") == "INSUFICIENTE":
        return "INSUFICIENTE"
    if "PEOR" in verdicts.values() or (needs_support and verdicts.get("support") != "MEJOR"):
        return "NO_CUMPLE"
    return "CUMPLE"


def report(matches: Mapping[int, datetime], rows: Mapping[str, Sequence[Mapping[str, Any]]], *, since: datetime,
           until: datetime) -> dict[str, Any]:
    tallies = tally(matches, rows)
    v4 = tallies[CHRONICLE]
    against: dict[str, Any] = {}
    for name in TEXTS:
        compared = compare_one(v4, tallies[name])
        verdict = verdict_of(v4, tallies[name], compared)
        step = next(s for s in STEPS if s.text == name)
        against[name] = {"metrics": compared, "verdict": verdict, "step": {"order": step.order, "switch": step.switch, "off": step.off,
                                                                          "state": step_state(step, verdict), "back": step.back,
                                                                          "note": step.note, "table": step.table}}
    return {"version": VERSION, "since": since.isoformat(), "until": until.isoformat(), "matches": len(matches),
            "rule": {"min_matches": MIN_MATCHES, "margin": MARGIN, "cost_margin": str(COST_MARGIN), "signed": False},
            "texts": {k: t.as_json() for k, t in tallies.items()}, "against": against,
            "deleted_rows": 0, "decides": False,
            "note": "compara y no apaga nada; cada retirada es un cambio de interruptor que hace y firma el dueño"}


# ── the rows (read-only) ────────────────────────────────────────────────────────────────────────────────────────────────────

MATCHES_SQL: Final = """
SELECT f.id, f.kickoff_at FROM core.fixtures f
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND EXISTS (SELECT 1 FROM ai.chronicles c WHERE c.fixture_id = f.id)
   AND EXISTS (SELECT 1 FROM ai.fixture_passes fp WHERE fp.fixture_id = f.id AND fp.status IN ('ok', 'partial') AND fp.packet_id IS NOT NULL)
"""
ROWS_SQL: Final[dict[str, str]] = {
    CHRONICLE: "SELECT fixture_id, created_at, status, cost_usd, content, plan, abstention, version FROM ai.chronicles "
               "WHERE fixture_id = ANY(%(ids)s) AND (custom_id IS NULL OR custom_id NOT LIKE 'lineup-update:%%')",
    "user-narrative-v3": "SELECT fixture_id, created_at, status, cost_usd, content FROM ai.user_narratives "
                         "WHERE fixture_id = ANY(%(ids)s) AND version = 'user-narrative-v3'",
    "brief-v8": "SELECT fixture_id, created_at, status, engine, cost_usd, content->'narrative' AS narrative FROM ai.match_briefs "
                "WHERE fixture_id = ANY(%(ids)s) AND version = 'brief-v8'",
    "match-analysis-v1": "SELECT fixture_id, built_at AS created_at, 0 AS cost_usd FROM ai.match_analyses WHERE fixture_id = ANY(%(ids)s)",
}


def rows_for(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> tuple[dict[int, datetime], dict[str, list[dict[str, Any]]]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MATCHES_SQL, {"since": since, "until": until})
        matches = {int(r["id"]): r["kickoff_at"] for r in cur.fetchall()}
        out: dict[str, list[dict[str, Any]]] = {}
        for name, sql in ROWS_SQL.items():
            cur.execute(sql, {"ids": sorted(matches)})
            out[name] = [dict(r) for r in cur.fetchall()]
    return matches, out


__all__ = ["CHRONICLE", "MARGIN", "METRICS", "MIN_MATCHES", "SIGNATURES", "STEPS", "TEXTS", "VERSION", "Shown", "Step", "Tally", "compare_one",
           "report", "rows_for", "shown", "step_state", "tally", "unauthorised", "verdict_of"]
