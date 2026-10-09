"""QUÉ APRENDIÓ PREDIGOL HOY: every morning, what yesterday's results taught - written down with its evidence, never
acted on.

From the post-mortems of the matches played on a Bogotá day (``fbi.ai.pick_postmortem``, ``fbi.ai.postmortem``)
and the evidence of that day, the notes (``ai.learning_notes``, once per day and kind):

    summary    how many selections were studied, approved, kept with caution, rejected - and how each did
    approved   the approved selections that lost, by class (model, context, data, market, execution, variance)
    rejected   the rejected selections that would have won, and those rejected rightly
    context    the reports that proved wrong and the absences nobody reported
    news       which news the line-ups confirmed and which they contradicted, by source level
    injuries   the losses with a key absence on the chosen side
    market     the closing-line value of the approved prices, the moves against them
    model      the model against the closing market on the studied selections
    sources    the day's sources: how often they came up, what was kept and what discarded
    lesson     at most three lessons a language model draws from the notes above, each citing the notes it rests on
               (refused when it cites none)

An observation is not a rule: OBSERVATION -> PATTERN -> HYPOTHESIS -> SAMPLE -> EXPERIMENT -> BACKTEST -> SHADOW ->
MARKET COMPARISON -> the owner's approval. This module stops at the first step; patterns over many days become
hypotheses (``fbi.ai.patterns``), and nothing here changes a model, a rule or a pick.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fbi.ai.calendar import day_bounds
from fbi.ai.config import AiSettings
from fbi.ai.prompts import LEARNING_SCHEMA, LEARNING_SYSTEM, LEARNING_VERSION
from fbi.ai.providers.base import JsonRequest, LlmProvider
from fbi.ai.text import plain
from fbi.ai.usage import UsageLedger, call_json

VERSION = "learning-v1"
CLASS_ES = {"MODEL_ERROR": "error del modelo", "CONTEXT_ERROR": "error de contexto", "DATA_ERROR": "error de datos",
            "MARKET_ERROR": "el mercado sabía algo", "EXECUTION_ERROR": "error de ejecución",
            "NORMAL_VARIANCE": "varianza normal", "UNKNOWN": "sin datos para juzgar"}

PM_SQL = """
SELECT pm.id, pm.fixture_id, pm.market_key, pm.selection, pm.line, pm.roles, pm.decision, pm.settled, pm.verdict,
       pm.classification, pm.odds, pm.close_odds, pm.clv, pm.p_model, pm.p_market, pm.answers, pm.evidence,
       th.name || ' - ' || ta.name AS match
  FROM ai.pick_postmortems pm JOIN core.fixtures f ON f.id = pm.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND pm.version = 'pm-v2'
 ORDER BY pm.id
"""

EVIDENCE_CHECKS_SQL = """
SELECT pm.id, ev->>'tier' AS tier, ev->>'origin' AS origin, ev->>'verdict' AS verdict
  FROM ai.postmortems pm JOIN core.fixtures f ON f.id = pm.fixture_id,
       jsonb_array_elements(pm.findings->'evidence') ev
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
"""

SOURCES_SQL = """
SELECT e.source_domain AS domain, e.source_tier AS tier, count(*) AS evidence,
       count(*) FILTER (WHERE e.status IN ('CONFIRMED', 'PROBABLE')) AS useful,
       count(*) FILTER (WHERE e.status IN ('RUMOR', 'OUTDATED', 'CONTRADICTORY')) AS discarded
  FROM ai.evidence e
 WHERE e.origin = 'web' AND e.source_domain IS NOT NULL AND e.retrieved_at >= %(start)s AND e.retrieved_at < %(end)s
 GROUP BY 1, 2
"""


def refresh_source_stats(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> int:
    """The day's evidence per domain into ``ai.source_stats`` (results and cost were counted when searched)."""
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SOURCES_SQL, {"start": start, "end": end})
        rows = [dict(r) for r in cur.fetchall()]
    with conn.cursor(row_factory=tuple_row) as cur:
        for r in rows:
            cur.execute("INSERT INTO ai.source_stats (day, domain, tier, evidence, useful, discarded, computed_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (day, domain) DO UPDATE SET "
                        "tier = EXCLUDED.tier, evidence = EXCLUDED.evidence, useful = EXCLUDED.useful, "
                        "discarded = EXCLUDED.discarded, computed_at = EXCLUDED.computed_at",
                        (day, r["domain"], r["tier"], int(r["evidence"]), int(r["useful"]), int(r["discarded"]), at))
    return len(rows)


@dataclass
class Note:
    kind: str
    title: str
    body: str
    n: int
    evidence: dict[str, Any] = field(default_factory=dict)


def _pct(x: float) -> str:
    return f"{100 * x:.0f} %"


def notes_for(pms: list[dict[str, Any]], checks: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[Note]:
    """The day's deterministic notes (pure: rows in, notes out)."""
    out: list[Note] = []
    if not pms:
        return out
    verdicts = Counter(p["verdict"] for p in pms)
    ids = [int(p["id"]) for p in pms]
    approved = [p for p in pms if p["decision"] == "APPROVE"]
    caution = [p for p in pms if p["decision"] == "DOWNGRADE"]
    rejected = [p for p in pms if p["decision"] == "REJECT"]
    out.append(Note(
        "summary", f"Se estudiaron {len(pms)} selecciones del día",
        f"Aprobadas {len(approved)} ({verdicts['approved_won']} ganadas, {verdicts['approved_lost']} perdidas); con "
        f"cautela {len(caution)} ({verdicts['caution_won']} ganadas, {verdicts['caution_lost']} perdidas); rechazadas "
        f"{len(rejected)} ({verdicts['rejected_would_have_won']} habrían ganado, {verdicts['rejected_correctly']} "
        f"rechazadas con acierto); sin revisión {verdicts['unreviewed_won'] + verdicts['unreviewed_lost']}.",
        len(pms), {"postmortems": ids, "verdicts": dict(verdicts)}))
    lost = [p for p in pms if p["verdict"] in ("approved_lost", "caution_lost")]
    if lost:
        classes = Counter(p["classification"] or "UNKNOWN" for p in lost)
        body = "; ".join(f"{CLASS_ES.get(c, c)}: {n}" for c, n in classes.most_common())
        out.append(Note("approved", f"{len(lost)} aprobadas o con cautela perdieron",
                        f"Por clase: {body}. Una pérdida no es un patrón: se acumula hasta tener muestra.", len(lost),
                        {"postmortems": [int(p["id"]) for p in lost], "classes": dict(classes)}))
    would = [p for p in pms if p["verdict"] == "rejected_would_have_won"]
    right = [p for p in pms if p["verdict"] == "rejected_correctly"]
    if would or right:
        examples = ", ".join(f"{p['match']} ({p['market_key']} {p['selection']})" for p in would[:3])
        out.append(Note("rejected", f"Rechazos: {len(right)} acertados, {len(would)} habrían ganado",
                        ("Habrían ganado: " + examples + ". " if would else "") +
                        "La calidad de los rechazos se juzga sobre muchos partidos en el shadow, no en un día.",
                        len(would) + len(right),
                        {"postmortems": [int(p["id"]) for p in would + right], "would_have_won": len(would),
                         "rejected_correctly": len(right)}))
    info = [p for p in pms if ((p["answers"] or {}).get("information") or {}).get("answer") == "sí"]
    if info:
        out.append(Note("context", f"La información falló en {len(info)} selecciones",
                        "Reportes que resultaron falsos o titulares ausentes sin reporte: " +
                        "; ".join(str(((p["answers"] or {}).get("information") or {}).get("detail", ""))[:120]
                                  for p in info[:3]) + ".", len(info),
                        {"postmortems": [int(p["id"]) for p in info]}))
    if checks:
        by: dict[str, Counter[str]] = {}
        for c in checks:
            by.setdefault(str(c["tier"]), Counter())[str(c["verdict"])] += 1
        parts = [f"{tier}: {v['right']} confirmadas y {v['wrong']} desmentidas por la alineación"
                 for tier, v in sorted(by.items()) if v["right"] or v["wrong"]]
        if parts:
            n = sum(v["right"] + v["wrong"] for v in by.values())
            out.append(Note("news", "Qué noticias confirmó la alineación", "; ".join(parts) + ".", n,
                            {"postmortem_findings": sorted({int(c["id"]) for c in checks}),
                             "by_tier": {t: dict(v) for t, v in by.items()}}))
    injured = [p for p in pms if p["verdict"] in ("approved_lost", "caution_lost", "unreviewed_lost")
               and ((p["answers"] or {}).get("key_absence") or {}).get("answer") == "sí"]
    if injured:
        out.append(Note("injuries", f"{len(injured)} pérdidas con una baja clave en el lado elegido",
                        "; ".join(f"{p['match']}: {((p['answers'] or {}).get('key_absence') or {}).get('detail')}"
                                  for p in injured[:3]) + ".", len(injured),
                        {"postmortems": [int(p["id"]) for p in injured]}))
    clv = [float(p["clv"]) for p in approved if p["clv"] is not None]
    against = [p for p in pms if p["clv"] is not None and float(p["clv"]) <= -0.03]
    if clv or against:
        mean = sum(clv) / len(clv) if clv else None
        out.append(Note("market", "El mercado frente a las cuotas tomadas",
                        (f"CLV medio de las aprobadas {100 * mean:+.1f} % ({len(clv)}). " if mean is not None else "") +
                        f"El cierre se movió 3 % o más en contra en {len(against)} selecciones.",
                        len(clv) + len(against),
                        {"postmortems": [int(p["id"]) for p in against], "mean_clv_approved": mean}))
    gaps = [(float(p["p_model"]) - float((p["answers"] or {}).get("model", {}).get("data", {}).get("p_close") or 0))
            for p in pms if p["p_model"] is not None
            and ((p["answers"] or {}).get("model") or {}).get("data", {}).get("p_close") is not None]
    model_errors = [p for p in pms if p["classification"] == "MODEL_ERROR"]
    if gaps:
        out.append(Note("model", "El modelo frente al cierre del mercado",
                        f"Diferencia media modelo - cierre {100 * sum(gaps) / len(gaps):+.1f} puntos en {len(gaps)} "
                        f"selecciones; errores del modelo: {len(model_errors)}.", len(gaps),
                        {"postmortems": [int(p["id"]) for p in model_errors], "mean_gap": sum(gaps) / len(gaps)}))
    if sources:
        best = sorted(sources, key=lambda s: (-int(s["useful"]), str(s["domain"])))[:3]
        worst = sorted((s for s in sources if int(s["discarded"]) > 0), key=lambda s: -int(s["discarded"]))[:3]
        out.append(Note("sources", f"{len(sources)} fuentes aportaron evidencia",
                        "Más útiles: " + ", ".join(f"{s['domain']} ({s['useful']})" for s in best) +
                        (". Más descartadas: " + ", ".join(f"{s['domain']} ({s['discarded']})" for s in worst)
                         if worst else "") + ".", sum(int(s["evidence"]) for s in sources),
                        {"domains": [s["domain"] for s in sources]}))
    return out


class Lesson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=600)
    note_refs: list[int] = Field(min_length=1, max_length=10)
    n: int = Field(ge=0)


class Lessons(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lessons: list[Lesson] = Field(default_factory=list, max_length=3)


@dataclass
class LearningReport:
    notes: int = 0
    lessons: int = 0
    rejected: list[str] = field(default_factory=list)


def _store(conn: psycopg.Connection[Any], note: Note, *, day: date, at: datetime, engine: str, key: str,
           usage_ids: list[int] | None = None) -> int | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.learning_notes (day, created_at, version, kind, title, body, n, evidence, engine, "
                    "usage_ids, dedup_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
                    (day, at, VERSION, note.kind, note.title[:200], note.body[:1200], note.n,
                     Jsonb(json.loads(json.dumps(note.evidence, default=str))), engine, usage_ids or [], key))
        row = cur.fetchone()
    return None if row is None else int(row[0])


def learn_day(conn: psycopg.Connection[Any], *, day: date, at: datetime, settings: AiSettings | None = None,
              use_llm: bool = True, ledger: UsageLedger | None = None, provider: tuple[LlmProvider, str] | None = None,
              transport: httpx.BaseTransport | None = None) -> LearningReport:
    """The notes of one Bogotá day's results (once per day and kind) and at most three lessons."""
    settings = settings or AiSettings.from_env()
    report = LearningReport()
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PM_SQL, {"start": start, "end": end})
        pms = [dict(r) for r in cur.fetchall()]
        cur.execute(EVIDENCE_CHECKS_SQL, {"start": start, "end": end})
        checks = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT domain, tier, results, evidence, useful, discarded, cost_usd FROM ai.source_stats "
                    "WHERE day = %s", (day,))
        sources = [dict(r) for r in cur.fetchall()]
    stored: dict[int, Note] = {}
    for note in notes_for(pms, checks, sources):
        nid = _store(conn, note, day=day, at=at, engine="rules", key=f"ln:{day}:{note.kind}")
        if nid is not None:
            stored[nid] = note
            report.notes += 1
    if not (use_llm and stored and (settings.llm_configured or provider is not None)):
        return report
    body = json.dumps({"day": day.isoformat(), "notes": [{"id": i, "kind": n.kind, "title": n.title, "body": n.body,
                                                          "n": n.n} for i, n in stored.items()]},
                      ensure_ascii=False)
    call = call_json(conn, settings, tier="analysis", purpose="learning",
                     request=JsonRequest(LEARNING_SYSTEM, body, LEARNING_SCHEMA, "submit_lessons", max_tokens=4000),
                     at=at, prompt_version=LEARNING_VERSION, input_hash=f"{VERSION}:{day}", ledger=ledger,
                     transport=transport, provider=provider)
    if call.result is None:
        return report
    try:
        parsed = Lessons.model_validate(call.result.data)
    except ValidationError:
        report.rejected.append("invalid output")
        return report
    for i, lesson in enumerate(parsed.lessons):
        refs = [r for r in lesson.note_refs if r in stored]
        if not refs:
            report.rejected.append(lesson.title)
            continue
        if _store(conn, Note("lesson", plain(lesson.title), plain(lesson.body), lesson.n, {"note_refs": refs}), day=day,
                  at=at,
                  engine="llm", key=f"ln:{day}:lesson:{i}",
                  usage_ids=[call.usage_id] if call.usage_id else []) is not None:
            report.lessons += 1
    return report
