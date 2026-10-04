"""The pick reviewer: FLAGS ONLY.

It reads the day's pick set and emits flags - a code, a severity, a note and the claims behind
it - into ``analytics.ai_pick_flags``. There is no path from here to a probability, a stake, a
pick or a parlay: the output schema has no such field (unknown fields are refused) and the
table has no such column. A flag is something for the owner to look at, nothing more.

Two reviewers write flags:

* **rules** (always, no LLM): facts we can check ourselves - the kick-off moved after the pick
  was chosen (``kickoff_change``), the best price we hold now is below the pick's
  (``stale_price``), no bookmaker of ours prices the market any more (``data_gap``). A new rules
  run is stored only when its flags differ from the set's last ones.
* **the model** (when configured, and the day's research report has claims): it sees the picks'
  facts and the CLAIMS of that report - graded, with publisher and dates - never raw web text,
  and has no tools. A flag about news (injury, line-up, suspension, rotation, motivation,
  weather) must cite at least one of those claims, or it is refused. It runs again only when
  the picks or the claims changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

import httpx
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from fbi.analyst import budget
from fbi.analyst.agent import SYSTEM_PROMPT, AnalystConfig, LlmClient, OutputTool, ToolLoop
from fbi.analyst.research import KICKOFF_CHANGES_SQL, PRICE_DROP, Leg, best_now, load_scope
from fbi.analyst.store import AiStore, FlagRow
from fbi.analyst.tools import ToolContext
from fbi.api.repositories import Conn
from fbi.api.services import matches
from fbi.core.clock import now
from fbi.picks.daily import DAY_TZ, product_day

Code = Literal["injury_news", "lineup_uncertain", "suspension", "rotation_risk", "motivation", "stale_price",
               "data_gap", "kickoff_change", "weather", "other"]
NEEDS_EVIDENCE = frozenset({"injury_news", "lineup_uncertain", "suspension", "rotation_risk", "motivation",
                            "weather"})


class FlagOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rank: int = Field(ge=1, le=5)
    code: Code
    severity: Literal["info", "warn", "review"]
    note: str = Field(min_length=3, max_length=500)
    claim_refs: list[str] = Field(default_factory=list, max_length=5)


class FlagsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flags: list[FlagOut] = Field(default_factory=list, max_length=25)


SUBMIT_FLAGS = OutputTool(
    "submit_flags",
    "Submit flags for the picks, by rank. Flags only: you cannot change a probability, a price, a stake or a pick.",
    {"type": "object", "additionalProperties": False, "required": ["flags"],
     "properties": {"flags": {"type": "array", "maxItems": 25, "items": {
         "type": "object", "additionalProperties": False, "required": ["rank", "code", "severity", "note"],
         "properties": {
             "rank": {"type": "integer", "minimum": 1, "maximum": 5},
             "code": {"type": "string", "enum": ["injury_news", "lineup_uncertain", "suspension", "rotation_risk",
                                                 "motivation", "stale_price", "data_gap", "kickoff_change",
                                                 "weather", "other"]},
             "severity": {"type": "string", "enum": ["info", "warn", "review"]},
             "note": {"type": "string", "maxLength": 500},
             "claim_refs": {"type": "array", "maxItems": 5, "items": {"type": "string"}}}}}}},
    FlagsOut)

REVIEW_PROMPT = SYSTEM_PROMPT + """

You review the day's picks against the research claims below (JSON). For each pick, flag what the owner should look
at before kick-off: news that the pick's numbers cannot know (an injury, a suspension, an uncertain line-up,
rotation, motivation, weather). Every such flag cites the claim refs it rests on. Severity: info (worth knowing),
warn (it may matter), review (look before kick-off). No flag is a fine answer. You cannot change anything: you only
flag. Write each note in Spanish, one sentence. Call submit_flags exactly once."""

CLAIMS_SQL = """
SELECT c.id, c.fixture_id, c.team_id, c.claim, c.publisher, c.published_at, c.confidence
  FROM analytics.ai_claims c
 WHERE c.run_id = (SELECT r.id FROM analytics.ai_runs r JOIN analytics.ai_reports rep ON rep.run_id = r.id
                    WHERE r.kind = 'daily_report' AND r.status = 'ok' AND rep.day = %(day)s
                    ORDER BY r.id DESC LIMIT 1)
 ORDER BY c.id
"""

SETS_SQL = "SELECT id, day, source FROM picks.daily_sets WHERE day = %(day)s AND source = %(source)s"


@dataclass
class ReviewResult:
    set_id: int | None
    rules_run: int | None = None
    model_run: int | None = None
    flags: list[FlagRow] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    status: str = "ok"


def _signature(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]


def rule_flags(conn: Conn, legs: list[Leg], *, at: datetime, kickoff: dict[int, datetime]) -> list[FlagRow]:
    out: list[FlagRow] = []
    for leg in legs:
        if leg.kind != "pick" or leg.status != "PENDING" or kickoff[leg.fixture_id] <= at:
            continue
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(KICKOFF_CHANGES_SQL, (leg.fixture_id, leg.selected_at))
            changes = list(cur.fetchall())
        if changes:
            last = changes[-1]
            out.append(FlagRow(leg.set_id, leg.rank, leg.fixture_id, "kickoff_change", "warn",
                               f"La hora de inicio cambió después de elegir el pick: "
                               f"{last['before_kickoff'].astimezone(DAY_TZ):%d %b %H:%M} -> "
                               f"{last['after_kickoff'].astimezone(DAY_TZ):%d %b %H:%M} (Bogotá)."))
        best = best_now(conn, leg)
        if best is not None and best[0] < leg.odds * PRICE_DROP:
            out.append(FlagRow(leg.set_id, leg.rank, leg.fixture_id, "stale_price", "info",
                               f"El mejor precio que tenemos ahora es {best[0]} ({best[1]}), por debajo del "
                               f"{leg.odds} del pick: ese precio ya no está disponible."))
        status = {(s.market_key, s.line): s.status for s in matches.price_status(conn, leg.fixture_id, at)}
        if status.get((leg.market_key, leg.line)) == "PRICE_UNAVAILABLE":
            out.append(FlagRow(leg.set_id, leg.rank, leg.fixture_id, "data_gap", "info",
                               "Ninguna casa de las que capturamos cotiza ya este mercado."))
    return out


def _model_flags(raw: FlagsOut, *, ranks: dict[int, Leg], claim_ids: dict[str, int]
                 ) -> tuple[list[FlagRow], list[str]]:
    flags: list[FlagRow] = []
    rejected: list[str] = []
    for f in raw.flags:
        leg = ranks.get(f.rank)
        if leg is None:
            rejected.append(f"rank {f.rank}: no such pick")
            continue
        refs = [claim_ids[r] for r in f.claim_refs if r in claim_ids]
        if f.code in NEEDS_EVIDENCE and not refs:
            rejected.append(f"rank {f.rank} {f.code}: no claim cited")
            continue
        flags.append(FlagRow(leg.set_id, f.rank, leg.fixture_id, f.code, f.severity, " ".join(f.note.split()),
                             tuple(refs)))
    return flags, rejected


def run_pick_review(conn: Conn, *, at: datetime | None = None, day: date | None = None, source: str = "evaluation",
                    store: AiStore | None = None, config: AnalystConfig | None = None,
                    transport: httpx.BaseTransport | None = None) -> ReviewResult:
    at = at or now()
    store = store or AiStore()
    config = config or AnalystConfig.from_env()
    day = day or product_day(at)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SETS_SQL, {"day": day, "source": source})
        set_row = cur.fetchone()
    if set_row is None:
        return ReviewResult(None, status="no_set")
    set_id = int(set_row["id"])
    scope = load_scope(conn, day=day, source=source)
    legs = [g for fx in scope for g in fx.legs if g.kind == "pick" and g.set_id == set_id]
    kickoff = {fx.fixture_id: fx.kickoff_at for fx in scope}
    result = ReviewResult(set_id)

    # rules: stored when they changed
    flags = rule_flags(conn, legs, at=at, kickoff=kickoff)
    sig = _signature({"set": set_id, "flags": sorted((f.rank, f.code, f.note) for f in flags)})
    last = store.latest_run("pick_review", where="AND detail->>'engine' = 'rules' AND detail->>'set_id' = %s",
                            params=(str(set_id),))
    if last is None or (last.get("detail") or {}).get("signature") != sig:
        run_id = store.start("pick_review", model=None, at=at, detail={"engine": "rules", "set_id": str(set_id),
                                                                       "signature": sig, "day": day.isoformat()})
        store.flags(run_id, flags, at=at)
        store.finish(run_id, status="ok", at=now(), model=None, detail={"flags": len(flags)})
        result.rules_run = run_id
        result.flags += flags

    # the model: only with claims to weigh, and only when the picks or the claims changed
    if not config.configured:
        return result
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CLAIMS_SQL, {"day": day})
        claims = [dict(r) for r in cur.fetchall()]
    fixtures = {g.fixture_id for g in legs}
    teams = {t for fx in scope if fx.fixture_id in fixtures for t in (fx.home_id, fx.away_id)}
    claims = [c for c in claims if c["fixture_id"] in fixtures or c["team_id"] in teams]
    pending = [g for g in legs if g.status == "PENDING" and kickoff[g.fixture_id] > at]
    if not claims or not pending:
        return result
    refs = {f"C{i}": int(c["id"]) for i, c in enumerate(claims, start=1)}
    sig = _signature({"set": set_id, "legs": [(g.rank, g.fixture_id, g.market_key, g.selection, str(g.line))
                                              for g in pending], "claims": sorted(refs.values())})
    last = store.latest_run("pick_review", where="AND detail->>'engine' = 'model' AND detail->>'set_id' = %s",
                            params=(str(set_id),))
    if last is not None and (last.get("detail") or {}).get("signature") == sig and last.get("status") == "ok":
        return result
    model = config.model
    run_id = store.start("pick_review", model=model, at=at,
                         detail={"engine": "model", "set_id": str(set_id), "signature": sig, "day": day.isoformat()})
    content = json.dumps({
        "picks": [{"rank": g.rank, "fixture_id": g.fixture_id, "kickoff_at": kickoff[g.fixture_id].isoformat(),
                   "match": next(f"{fx.home} vs {fx.away}" for fx in scope if fx.fixture_id == g.fixture_id),
                   "market": g.market_key, "selection": g.selection, "line": str(g.line), "odds": str(g.odds)}
                  for g in pending],
        "claims": [{"ref": ref, "claim": c["claim"], "grade": c["confidence"], "publisher": c["publisher"],
                    "published_at": None if c["published_at"] is None else c["published_at"].isoformat(),
                    "fixture_id": c["fixture_id"], "team_id": c["team_id"]}
                   for ref, c in zip(refs, claims, strict=True)]}, ensure_ascii=False)
    client = LlmClient(config, transport=transport)
    loop = ToolLoop(client, store, ToolContext(conn=conn, at=at, web=False), run_id=run_id, system=REVIEW_PROMPT,
                    tools=[], output=SUBMIT_FLAGS, max_tokens=1500, max_rounds=2, force_output=True)
    status, error = "ok", None
    try:
        answer = loop.run(content)
        if isinstance(answer.output, FlagsOut):
            model_flags, rejected = _model_flags(answer.output, ranks={g.rank: g for g in pending}, claim_ids=refs)
            store.flags(run_id, model_flags, at=at)
            result.flags += model_flags
            result.rejected = rejected
        else:
            status, error = "failed", answer.stopped or "no flags submitted"
    except budget.OverBudgetError as exc:
        status, error = "over_budget", str(exc)
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]
    finally:
        client.close()
    store.finish(run_id, status=status, at=now(), model=model, usage=loop.answer.usage, tool_calls=0,
                 detail={"flags": len(result.flags), "rejected": result.rejected}, error=error)
    result.model_run = run_id
    result.status = status
    return result


def review_days(at: datetime) -> list[date]:
    """Today and tomorrow (Bogotá): a set is reviewed until its matches start."""
    d = product_day(at)
    return [d, d + timedelta(days=1)]
