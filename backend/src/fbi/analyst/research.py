"""DAILY_RESEARCH_REPORT: what the owner should know about today's picks before kick-off.

Two parts, stored together in ``analytics.ai_reports``:

1. **The data** (always, no LLM): each fixture in the day's pick set and parlays - kick-off,
   the pick as it was frozen, the best price we hold now against it, the injury and line-up
   state we store, kick-off changes and the market's price status. Facts from our own tables.
2. **The research** (when an LLM is configured): team news for those fixtures from the web,
   as CLAIMS with provenance (``fbi.analyst.provenance``) - a claim without a source this run
   retrieved is refused and listed, never shown as fact - and a short summary that cites
   claims [C1] and tool results [T1]. Raw URLs typed by the model are removed: a page enters
   the report only through a source id.

Nothing here changes a probability, a pick or a parlay. Without a key the run is recorded as
``not_configured`` and the report carries part 1 and the list of what is missing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from fbi.analyst import budget
from fbi.analyst import search as web
from fbi.analyst.agent import (
    SYSTEM_PROMPT,
    AnalystConfig,
    LlmClient,
    OutputTool,
    ToolLoop,
    research_tools,
)
from fbi.analyst.provenance import Claim, Rejected, accept_claims
from fbi.analyst.store import AiStore
from fbi.analyst.tools import ToolContext
from fbi.api.repositories import Conn
from fbi.api.repositories.fixtures import latest_quotes
from fbi.api.services import center, matches
from fbi.core.clock import now
from fbi.picks.daily import DAY_TZ, product_day

MAX_FIXTURES = 12
RESEARCH_TOOLS = ("get_fixture", "get_team", "get_standings", "get_injuries", "get_market", "get_prediction",
                  "web_research")
PRICE_DROP = Decimal("0.97")
"""A current best price below 97 % of the pick's is worth saying: the pick's price is gone."""

SCOPE_SQL = """
WITH chosen AS (
    SELECT 'pick' AS kind, s.id AS set_id, i.rank, NULL::text AS parlay, i.fixture_id, i.market_key, i.selection,
           i.line, i.odds, i.p_model, i.p_low, i.p_market, i.ev, i.stage, i.status, i.selected_at
      FROM picks.daily_sets s JOIN picks.daily_set_items i ON i.set_id = s.id
     WHERE s.day = %(day)s AND s.source = %(source)s
    UNION ALL
    SELECT 'parlay_leg', NULL, l.leg_no, p.kind, l.fixture_id, l.market_key, l.selection, l.line, l.odds, l.p_model,
           l.p_low, l.p_market, l.ev, NULL, l.status, l.added_at
      FROM picks.parlays p JOIN picks.parlay_legs l ON l.parlay_id = p.id
     WHERE p.day = %(day)s AND p.source = %(source)s AND p.status <> 'VOID'
)
SELECT ch.*, f.kickoff_at, f.status_group, c.name AS competition, f.home_team_id, th.name AS home,
       f.away_team_id, ta.name AS away
  FROM chosen ch
  JOIN core.fixtures f ON f.id = ch.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 ORDER BY f.kickoff_at, ch.kind, ch.rank
"""

KICKOFF_CHANGES_SQL = """
SELECT observed_at, before_kickoff, after_kickoff FROM core.fixture_kickoff_changes
 WHERE fixture_id = %s AND observed_at > %s ORDER BY observed_at
"""


@dataclass
class Leg:
    kind: str
    set_id: int | None
    rank: int
    parlay: str | None
    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal
    p_model: Decimal
    p_low: Decimal
    p_market: Decimal
    ev: Decimal
    stage: str | None
    status: str
    selected_at: datetime


@dataclass
class FixtureScope:
    fixture_id: int
    kickoff_at: datetime
    status_group: str
    competition: str
    home_id: int
    home: str
    away_id: int
    away: str
    legs: list[Leg] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"fixture_id": self.fixture_id, "kickoff_at": self.kickoff_at.isoformat(),
                "competition": self.competition, "home": {"team_id": self.home_id, "name": self.home},
                "away": {"team_id": self.away_id, "name": self.away},
                "selections": [{"market": g.market_key, "selection": g.selection, "line": str(g.line),
                                "odds": str(g.odds), "from": "pick" if g.kind == "pick" else f"{g.parlay} parlay"}
                               for g in self.legs]}


def choose_source(conn: Conn, day: date) -> Literal["qualified", "evaluation"]:
    """The evaluation set when the day has one with picks - the owner's view, the widest - and
    the qualified set otherwise. The report is the owner's either way."""
    with conn.cursor() as cur:
        cur.execute("SELECT s.source FROM picks.daily_sets s JOIN picks.daily_set_items i ON i.set_id = s.id "
                    "WHERE s.day = %s GROUP BY s.source", (day,))
        sources = {str(r[0]) for r in cur.fetchall()}
    return "qualified" if sources == {"qualified"} else "evaluation"


def load_scope(conn: Conn, *, day: date, source: str) -> list[FixtureScope]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SCOPE_SQL, {"day": day, "source": source})
        rows = list(cur.fetchall())
    out: dict[int, FixtureScope] = {}
    for r in rows:
        fid = int(r["fixture_id"])
        fx = out.get(fid)
        if fx is None:
            if len(out) >= MAX_FIXTURES:
                continue
            fx = out[fid] = FixtureScope(fid, r["kickoff_at"], str(r["status_group"]), str(r["competition"]),
                                         int(r["home_team_id"]), str(r["home"]), int(r["away_team_id"]),
                                         str(r["away"]))
        fx.legs.append(Leg(str(r["kind"]), None if r["set_id"] is None else int(r["set_id"]), int(r["rank"]),
                           r["parlay"], fid, str(r["market_key"]), str(r["selection"]), Decimal(r["line"]),
                           Decimal(r["odds"]), Decimal(r["p_model"]), Decimal(r["p_low"]), Decimal(r["p_market"]),
                           Decimal(r["ev"]), r["stage"], str(r["status"]), r["selected_at"]))
    return list(out.values())


def best_now(conn: Conn, leg: Leg) -> tuple[Decimal, str, datetime] | None:
    """The best price we captured for the leg's selection since it was chosen."""
    best: tuple[Decimal, str, datetime] | None = None
    for q in latest_quotes(conn, leg.fixture_id):
        if (q["market_key"], q["selection"], Decimal(q["line"])) != (leg.market_key, leg.selection, leg.line):
            continue
        if q["captured_at"] <= leg.selected_at:
            continue
        odds = Decimal(q["odds_decimal"])
        if best is None or odds > best[0]:
            best = (odds, str(q["bookmaker"]), q["captured_at"])
    return best


def _pct(x: Decimal | float | None) -> str:
    return "-" if x is None else f"{100 * float(x):.1f} %"


def _local(ts: datetime) -> str:
    return ts.astimezone(DAY_TZ).strftime("%d %b %H:%M")


def _leg_line(leg: Leg) -> str:
    where = f"pick #{leg.rank}" if leg.kind == "pick" else f"parlay {leg.parlay}, pierna {leg.rank}"
    line = "" if leg.line == 0 else f" {leg.line:+g}"
    return (f"{where}: {leg.market_key} {leg.selection}{line} @ {leg.odds} - EV {_pct(leg.ev)}, modelo "
            f"{_pct(leg.p_model)} (bajo {_pct(leg.p_low)}) vs mercado {_pct(leg.p_market)}"
            + (f", etapa {leg.stage}" if leg.stage else "") + f" - {leg.status}")


def data_section(conn: Conn, scope: list[FixtureScope], *, at: datetime, source: str) -> str:
    label = "PrediGol Picks (calificados)" if source == "qualified" else \
        "Modo de evaluación (shadow, solo el dueño lo ve)"
    lines = [f"## Datos de la plataforma - {label}", ""]
    if not scope:
        lines.append("No hay picks ni parlays para este día.")
        return "\n".join(lines) + "\n"
    for fx in scope:
        lines.append(f"### {fx.home} vs {fx.away} - {fx.competition}, {_local(fx.kickoff_at)} (Bogotá)")
        for leg in fx.legs:
            lines.append(f"* {_leg_line(leg)}")
            if leg.status == "PENDING" and fx.status_group == "scheduled":
                now_price = best_now(conn, leg)
                if now_price is None:
                    lines.append("  * Precio: ninguna captura nueva desde la selección.")
                else:
                    odds, book, ts = now_price
                    drop = " - **el precio del pick ya no está**" if odds < leg.odds * PRICE_DROP else ""
                    lines.append(f"  * Mejor precio ahora: {odds} ({book}, {_local(ts)}){drop}")
        env = center.match_center(conn, fx.fixture_id)
        mc = env.data
        if mc is not None:
            n_abs = len(mc.absences.data)
            lines.append(f"* Bajas registradas: {n_abs}" if n_abs else
                         "* Bajas registradas: ninguna guardada (no significa que no haya bajas)")
            lines.append("* Alineaciones: " + ("publicadas" if mc.lineups.data else "aún no publicadas"))
        first_pick = min((g.selected_at for g in fx.legs), default=at)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(KICKOFF_CHANGES_SQL, (fx.fixture_id, first_pick))
            for ch in cur.fetchall():
                lines.append(f"* **Cambio de hora** detectado {_local(ch['observed_at'])}: "
                             f"{_local(ch['before_kickoff'])} -> {_local(ch['after_kickoff'])}")
        markets = {g.market_key for g in fx.legs}
        status = [s for s in matches.price_status(conn, fx.fixture_id, at) if s.market_key in markets]
        if status:
            lines.append("* Estado del precio: " + ", ".join(
                f"{s.market_key}{'' if s.line == 0 else f' {s.line:+g}'} {s.status} ({s.bookmakers} casas)"
                for s in status))
        lines.append("")
    return "\n".join(lines) + "\n"


# ── the research part ───────────────────────────────────────────────────────

class ClaimOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = Field(pattern=r"^C\d{1,3}$")
    claim: str = Field(min_length=5, max_length=600)
    source_ids: list[str] = Field(min_length=1, max_length=3)
    confidence: Literal["CONFIRMED", "REPORTED", "RUMOR"]
    fixture_id: int | None = None
    team_id: int | None = None


class HypothesisOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=5, max_length=160)
    hypothesis: str = Field(min_length=5, max_length=600)
    rationale: str = Field(min_length=5, max_length=1000)


class ReportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=6000)
    claims: list[ClaimOut] = Field(default_factory=list, max_length=40)
    hypotheses: list[HypothesisOut] = Field(default_factory=list, max_length=2)


SUBMIT_REPORT = OutputTool(
    "submit_report",
    "Submit the research note: a short Markdown summary (cite claims as [C1], tool results as [T1]; no URLs, no "
    "betting advice) and the claims, each citing the source ids (S1, ...) web_research returned.",
    {"type": "object", "additionalProperties": False, "required": ["summary", "claims"],
     "properties": {
         "summary": {"type": "string", "maxLength": 6000},
         "claims": {"type": "array", "maxItems": 40, "items": {
             "type": "object", "additionalProperties": False,
             "required": ["ref", "claim", "source_ids", "confidence"],
             "properties": {
                 "ref": {"type": "string", "pattern": "^C[0-9]{1,3}$"},
                 "claim": {"type": "string", "maxLength": 600},
                 "source_ids": {"type": "array", "minItems": 1, "maxItems": 3,
                                "items": {"type": "string", "pattern": "^S[0-9]{1,3}$"}},
                 "confidence": {"type": "string", "enum": ["CONFIRMED", "REPORTED", "RUMOR"]},
                 "fixture_id": {"type": "integer"},
                 "team_id": {"type": "integer"}}}},
         "hypotheses": {"type": "array", "maxItems": 2, "items": {
             "type": "object", "additionalProperties": False, "required": ["title", "hypothesis", "rationale"],
             "properties": {"title": {"type": "string", "maxLength": 160},
                            "hypothesis": {"type": "string", "maxLength": 600},
                            "rationale": {"type": "string", "maxLength": 1000}}}}}},
    ReportOut)

RESEARCH_PROMPT = SYSTEM_PROMPT + """

Today you write the owner's daily research note on the fixtures below (JSON). For each fixture look for team news
published in the last three days that matters before kick-off: injuries, suspensions, expected line-ups, rotation,
motivation, weather, a changed kick-off. Use web_research with short queries (team names plus 'injury', 'line-up',
'news'); use our tools (get_injuries, get_fixture, get_standings, get_market) for what we store. Each claim is one
checkable statement about a team or player, cites 1-3 source ids, and carries the fixture_id and/or team_id it is
about. Grade it CONFIRMED only for an official club, league or federation source, REPORTED for a reputable outlet,
RUMOR otherwise - the server will lower a grade the sources do not support. Do not restate the picks' numbers, do
not say whether to bet. Write the summary in Spanish, at most 12 bullet points. You may propose up to two research
hypotheses (an experiment worth running, never a change to a rule: the owner decides). Finish by calling
submit_report."""

_URL = re.compile(r"https?://\S+")


@dataclass
class ReportResult:
    run_id: int
    report_id: int
    status: str
    day: date
    source: str
    claims: list[Claim] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    markdown: str = ""


def _claims_markdown(claims: list[Claim], ids: dict[str, int], rejected: list[Rejected]) -> list[str]:
    lines: list[str] = []
    if claims:
        lines += ["", "### Fuentes", "", "| Ref | Afirmación | Grado | Fuente | Publicado | Consultado |",
                  "|---|---|---|---|---|---|"]
        for c in claims:
            pub = c.source.published_at or "sin fecha"
            claim = c.claim.replace("|", "/")
            lines.append(f"| {c.ref} (#{ids.get(c.ref, '-')}) | {claim} | {c.grade.name} | "
                         f"[{c.source.publisher}]({c.source.url}) | {pub} | {c.source.retrieved_at} |")
    if rejected:
        lines += ["", "### Afirmaciones rechazadas (sin fuente válida)", ""]
        lines += [f"* {r.ref}: {r.reason}" for r in rejected]
    return lines


def run_daily_report(conn: Conn, *, at: datetime | None = None, day: date | None = None, source: str | None = None,
                     store: AiStore | None = None, config: AnalystConfig | None = None,
                     transport: httpx.BaseTransport | None = None) -> ReportResult:
    """Write today's report: the data part always, the research part when an LLM is configured."""
    at = at or now()
    store = store or AiStore()
    config = config or AnalystConfig.from_env()
    day = day or product_day(at)
    source = source or choose_source(conn, day)
    scope = load_scope(conn, day=day, source=source)
    data = data_section(conn, scope, at=at, source=source)
    header = [f"# Informe diario de investigación - {day:%d %b %Y}", "",
              f"Generado {at.astimezone(DAY_TZ):%d %b %Y %H:%M} (Bogotá). Nada aquí cambia una probabilidad, un pick "
              "o un parlay.", ""]
    missing = config.missing + ([] if web.configured() else ["EXA_API_KEY"])
    if not config.configured or not scope:
        reason = ("no hay picks ni parlays para investigar" if config.configured else
                  "investigación con IA no configurada: faltan " + ", ".join(missing) +
                  " (una cuenta de proveedor es decisión del dueño)")
        status = "ok" if config.configured else "not_configured"
        run_id = store.start("daily_report", model=config.model if config.configured else None, at=at,
                             detail={"day": day.isoformat(), "source": source, "fixtures": len(scope)})
        markdown = "\n".join(header) + data + f"\n## Investigación\n\n{reason[0].upper() + reason[1:]}.\n"
        store.finish(run_id, status=status, at=now(), model=None, detail={"missing": missing, "note": reason})
        report_id = store.report(run_id, day=day, source=source, markdown=markdown, claims=0, at=at)
        return ReportResult(run_id, report_id, status, day, source, markdown=markdown)

    model = config.model
    run_id = store.start("daily_report", model=model, at=at,
                         detail={"day": day.isoformat(), "source": source, "fixtures": len(scope),
                                 "web": web.configured()})
    client = LlmClient(config, transport=transport)
    ctx = ToolContext(conn=conn, at=at, web=web.configured())
    loop = ToolLoop(client, store, ctx, run_id=run_id, system=RESEARCH_PROMPT, tools=research_tools(RESEARCH_TOOLS),
                    output=SUBMIT_REPORT, max_tokens=3000, max_rounds=12)
    content = json.dumps({"day": day.isoformat(), "fixtures": [fx.as_json() for fx in scope],
                          "web_research": "available" if web.configured() else
                          "not configured: no claim can be made today; summarise what our tools show"},
                         ensure_ascii=False)
    status, error = "ok", None
    claims: list[Claim] = []
    rejected: list[Rejected] = []
    ids: dict[str, int] = {}
    proposed: list[int] = []
    summary = ""
    try:
        answer = loop.run(content)
        out = answer.output
        if isinstance(out, ReportOut):
            claims, rejected = accept_claims([c.model_dump() for c in out.claims], ctx.registry,
                                             fixture_ids={fx.fixture_id for fx in scope},
                                             team_ids={t for fx in scope for t in (fx.home_id, fx.away_id)})
            ids = store.claims(run_id, claims)
            proposed = store.hypotheses([h.model_dump() for h in out.hypotheses], run_id=run_id, at=at)
            summary = _URL.sub("[enlace omitido: cite una fuente por su id]", out.summary)
            if answer.unverified_figures:
                summary += ("\n\n*Cifras sin respaldo en una herramienta (no confiar): "
                            + ", ".join(answer.unverified_figures) + "*")
        else:
            status, error = "failed", answer.stopped or "no report submitted"
    except budget.OverBudgetError as exc:
        status, error = "over_budget", str(exc)
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]
    finally:
        client.close()
    answer = loop.answer
    store.finish(run_id, status=status, at=now(), model=model, usage=answer.usage, tool_calls=len(answer.calls),
                 detail={"rounds": answer.rounds, "claims": len(claims), "rejected": [r.ref for r in rejected],
                         "sources": len(ctx.registry.sources), "unverified": answer.unverified_figures,
                         "hypotheses": proposed},
                 error=error)
    research = ["## Investigación (IA)", ""]
    if status == "ok":
        research += [summary.strip(), *_claims_markdown(claims, ids, rejected)]
    else:
        research.append({"over_budget": "El presupuesto mensual de IA se agotó: no se investigó hoy.",
                         "failed": f"La investigación falló ({error}). Solo los datos de la plataforma."}[status])
    markdown = "\n".join(header) + data + "\n" + "\n".join(research) + "\n"
    report_id = store.report(run_id, day=day, source=source, markdown=markdown, claims=len(claims), at=at)
    return ReportResult(run_id, report_id, status, day, source, claims, rejected, markdown)


def due(conn: Conn, *, at: datetime, hour: int = 6) -> bool:
    """Whether today's (Bogotá) report is still to be written: after ``hour`` local and none
    stored for the day yet."""
    local = at.astimezone(DAY_TZ)
    if local.hour < hour:
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM analytics.ai_reports WHERE day = %s LIMIT 1", (local.date(),))
        return cur.fetchone() is None
