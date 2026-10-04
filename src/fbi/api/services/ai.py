"""The AI layer in the Admin Console: is it configured, what it cost this month, the daily
research report with its claims, and the pick reviewer's flags. Read only; the runs are written
by ``fbi.analyst`` through its own connection."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fbi.analyst import budget
from fbi.analyst import search as web
from fbi.analyst.agent import AnalystConfig
from fbi.api.contracts.analyst import (
    AiBudget,
    AiClaimRow,
    AiFlagRow,
    AiFlags,
    AiReport,
    AiRunRow,
    AiStatus,
)
from fbi.api.envelope import DataStatus, Envelope, listing, ok, unavailable
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now
from fbi.picks.daily import product_day

RUN_COLS = ("id, kind, model, started_at, finished_at, status, input_tokens, output_tokens, cost_usd, tool_calls, "
            "error, detail")

SCHEDULE = {
    "daily_report": "every day at 06:00 Bogotá (and on demand)",
    "pick_review": "every hour for today's and tomorrow's sets (rules always; the model when configured)",
    "research_monitor": "every day at 07:00 Bogotá: prospective evaluation, pick audit, memory, hypotheses",
    "research_v2": "weekly (Monday 04:00 Bogotá) when the code changed or the last run is 4+ weeks old",
}

REPORT_SQL = """
SELECT rep.id, rep.run_id, rep.day, rep.source, rep.markdown, rep.created_at, r.status AS run_status, r.model,
       r.cost_usd
  FROM analytics.ai_reports rep JOIN analytics.ai_runs r ON r.id = rep.run_id
 WHERE rep.day = %(day)s AND (%(source)s::text IS NULL OR rep.source = %(source)s)
 ORDER BY rep.id DESC LIMIT 1
"""

FLAGS_SQL = """
WITH s AS (SELECT id FROM picks.daily_sets WHERE day = %(day)s AND source = %(source)s),
runs AS (
    SELECT DISTINCT ON (r.detail->>'engine') r.id, r.detail->>'engine' AS engine
      FROM analytics.ai_runs r JOIN s ON r.detail->>'set_id' = s.id::text
     WHERE r.kind = 'pick_review' AND r.status = 'ok'
     ORDER BY r.detail->>'engine', r.id DESC
)
SELECT f.id, f.run_id, runs.engine, f.set_id, f.rank, f.fixture_id, th.name || ' vs ' || ta.name AS match, f.code,
       f.severity, f.note, f.claim_ids, f.created_at
  FROM analytics.ai_pick_flags f
  JOIN runs ON runs.id = f.run_id
  JOIN core.fixtures fx ON fx.id = f.fixture_id
  JOIN core.teams th ON th.id = fx.home_team_id
  JOIN core.teams ta ON ta.id = fx.away_team_id
 ORDER BY f.rank NULLS LAST, runs.engine, f.id
"""


def _run(r: dict[str, object]) -> AiRunRow:
    return AiRunRow.model_validate(r)


def status(conn: Conn, *, at: datetime | None = None) -> Envelope[AiStatus]:
    at = at or now()
    cfg = AnalystConfig.from_env()
    spent = budget.spent_this_month(conn, at=at)
    cap = budget.monthly_budget()
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    asked = fetch_one(conn, "SELECT count(*) AS n FROM analytics.ai_runs WHERE kind = 'ask' AND started_at >= %s "
                            "AND status <> 'not_configured'", (day,))
    last = [_run(r) for r in fetch_all(conn, f"SELECT DISTINCT ON (kind) {RUN_COLS} FROM analytics.ai_runs "
                                             "ORDER BY kind, id DESC")]
    missing = cfg.missing + ([] if web.configured() else ["EXA_API_KEY"])
    body = AiStatus(llm_configured=cfg.configured, model=cfg.model, search_configured=web.configured(),
                    missing=missing,
                    budget=AiBudget(month=at.strftime("%Y-%m"), cap_usd=cap, spent_usd=spent,
                                    left_usd=max(Decimal(0), cap - spent)),
                    questions_today=int(asked["n"]) if asked else 0, questions_per_day=cfg.questions_per_day,
                    last_runs=last, schedule=SCHEDULE)
    if not cfg.configured:
        return unavailable(body, "No LLM is configured on the API host (" + ", ".join(cfg.missing) + " unset): the "
                           "daily report carries the platform's data only, and the pick reviewer runs its rules "
                           "only. Creating a provider account is the owner's decision.")
    return ok(body)


def runs(conn: Conn, *, kind: str | None, limit: int) -> Envelope[list[AiRunRow]]:
    rows = fetch_all(conn, f"SELECT {RUN_COLS} FROM analytics.ai_runs WHERE (%(k)s::text IS NULL OR kind = %(k)s) "
                           "ORDER BY id DESC LIMIT %(n)s", {"k": kind, "n": limit})
    return listing([_run(r) for r in rows], empty_reason="No AI run recorded yet.")


def report(conn: Conn, *, day: date | None, source: str | None, at: datetime | None = None
           ) -> Envelope[AiReport | None]:
    day = day or product_day(at or now())
    r = fetch_one(conn, REPORT_SQL, {"day": day, "source": source})
    if r is None:
        return unavailable(None, f"No research report for {day:%d %b %Y} yet: it is written at 06:00 Bogotá, or "
                                 "on demand.", status=DataStatus.EMPTY)
    claims = [AiClaimRow.model_validate(c) for c in fetch_all(
        conn, "SELECT id, fixture_id, team_id, claim, source_url, also_urls, publisher, published_at, retrieved_at, "
              "confidence FROM analytics.ai_claims WHERE run_id = %s ORDER BY id", (r["run_id"],))]
    return ok(AiReport(id=int(r["id"]), run_id=int(r["run_id"]), day=r["day"], source=r["source"],
                       markdown=r["markdown"], claims=claims, created_at=r["created_at"],
                       run_status=r["run_status"], model=r["model"], cost_usd=r["cost_usd"]))


def flags(conn: Conn, *, day: date | None, source: str, at: datetime | None = None) -> Envelope[AiFlags]:
    day = day or product_day(at or now())
    s = fetch_one(conn, "SELECT id FROM picks.daily_sets WHERE day = %s AND source = %s", (day, source))
    rows = fetch_all(conn, FLAGS_SQL, {"day": day, "source": source}) if s else []
    body = AiFlags(day=day, source=source, set_id=None if s is None else int(s["id"]),  # type: ignore[arg-type]
                   flags=[AiFlagRow.model_validate(r) for r in rows])
    if s is None:
        return unavailable(body, f"No {source} pick set for {day:%d %b %Y}.", status=DataStatus.EMPTY)
    if not rows:
        return unavailable(body, "No flag on this set: the rules found nothing to point at, and the model has not "
                                 "flagged anything (or is not configured).", status=DataStatus.EMPTY)
    return ok(body)
