"""The factual evaluation of the single chronicle (IA-118, plan piece AD-F06): ``chronicle-review-v2`` and ``chronicle-metrics-v1``.

WHY A SECOND VERSION. ``chronicle-review-v1`` (``fbi.chronicle.review``) judges the readers' chronicle (``user-narrative-v3``) and found 0
evaluable claims in 3,761 sentences of 270 chronicles (14 days): its references point at the packet's story, and almost all of it is history.
The single chronicle (``chronicle-v4``) cites the facts of its CONTENT PLAN by id, each with its kind, side and params, and the plan is kept
with the chronicle (``ai.chronicles.plan``). So v2 is redesigned on the CITED FACTS:

* SUPPORT, sentence by sentence: every fact a sentence cites is in the stored plan, planned for a section, and known before the chronicle
  was written (``known_at``). A sentence that fails is ``sin_apoyo`` - the rate the protocol of AD-F06 holds to zero;
* what the match can REFUTE, fact by fact: an absence or a doubt against who played (``review.checks_of``, v1's own judgement, reused); a news
  item about a player the same way (by its provider id); what the scenarios engine PROVED (an objective secured or lost, nothing at stake,
  what this result does) against its first reading after the match; the update after the line-up (``lineup-update-v1``: «starts», «on the
  bench», «not listed») against the sheet and the minutes;
* everything else (form, table, head-to-head, figures, what was missing) describes the match: ``not_evaluable``, never a hit.

The METRICS of each chronicle (``chronicle-metrics-v1``): the support of the verifier (sentences that stood of those proposed), the support of
this audit, the coverage of the plan (its mandatory facts cited), the stock phrases and the repetitions (``repeat-check-v1``), and the counts
of what held and what was contradicted. Nothing calls a model; nothing reads the internet; nothing decides: the row goes to
``ai.chronicle_reviews`` (``chronicle_id``, revision 0159) beside v1's, which go on as they are.

SWITCH ``FBI_CHRONICLE_REVIEW_V2``: ``off`` (default) - nothing; ``shadow`` - the worker runs it hourly. Append-only; nothing reads it to decide."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg
from psycopg.types.json import Jsonb

from fbi.api.services import story as story_service
from fbi.chronicle import plan as cp
from fbi.chronicle import review
from fbi.chronicle.review import (
    CONTRADICTED,
    HELD,
    NOT_CHECKABLE,
    NOT_EVALUABLE,
    PENDING,
    Check,
    Squad,
)
from fbi.competitions.scenarios import FACT_NO_OBJECTIVE
from fbi.observability.trace import match_trace_id

VERSION: Final = "chronicle-review-v2"
METRICS_VERSION: Final = "chronicle-metrics-v1"
SWITCH: Final = "FBI_CHRONICLE_REVIEW_V2"
JOB: Final = "chronicle_review_v2"
UNSUPPORTED: Final = "sin_apoyo"
SETTLE: Final = review.SETTLE
LOOKBACK: Final = review.LOOKBACK
LIMIT: Final = 200
AFTER_MATCH: Final = timedelta(hours=2)
"""A reading of the scenarios engine computed this long after kick-off is «after the match»."""

Mode = Literal["off", "shadow"]


def mode(env: Mapping[str, str] | None = None) -> Mode:
    raw = (os.environ if env is None else env).get(SWITCH, "")
    return "shadow" if raw.strip().lower() == "shadow" else "off"


# ── support ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def support(fact_ids: Sequence[str], plan: cp.ContentPlan, *, written_at: datetime) -> str | None:
    """Why a sentence is not supported by its plan (None: it is)."""
    if not fact_ids:
        return "no cita ningún hecho"
    by = plan.by_id()
    planned = {f.id for f in plan.planned}
    for fid in fact_ids:
        if fid.startswith("A:"):
            continue  # the line-up's own fact (the update)
        f = by.get(fid)
        if f is None:
            return f"{fid}: no está en el plan"
        if fid not in planned:
            return f"{fid}: no está planificado en ninguna sección"
        if f.known_at is not None and f.known_at > written_at:
            return f"{fid}: conocido después de escribir la crónica"
    return None


# ── what the scenarios engine proved, against its reading after the match ───────────────────────────────────────────────────

def _objective(reading: Mapping[str, Any], table_key: str, team_id: int, objective: str) -> str | None:
    for t in reading.get("tables") or []:
        if not isinstance(t, Mapping) or str(t.get("key")) != table_key:
            continue
        for row in t.get("teams") or []:
            if isinstance(row, Mapping) and row.get("team") == team_id:
                for o in row.get("objetivos") or []:
                    if isinstance(o, Mapping) and str(o.get("objetivo")) == objective:
                        return str(o.get("estado"))
    return None


def _parts(fid: str) -> tuple[str, str, str] | None:
    """``S:<side>.<table>.<objective>[.efecto]`` -> (side, table, objective)."""
    body = fid.split("~")[0].removeprefix("S:").removesuffix(".efecto")
    side, _, rest = body.partition(".")
    table, _, objective = rest.rpartition(".")
    return (side, table, objective) if side in ("home", "away") and table and objective else None


def check_scenario(f: cp.PlanFact, *, after: Mapping[str, Any] | None, team_ids: Mapping[str, int],
                   result: tuple[int, int] | None) -> Check:
    """A proved claim of the engine against its first reading after the match."""
    if after is None or after.get("status") != "ok":
        return Check(f.id, "scenario", NOT_CHECKABLE, "no reading of the engine after the match")
    team = team_ids.get(f.side or "")
    if team is None:
        return Check(f.id, "scenario", NOT_CHECKABLE, "the side's team is unknown")
    if f.kind == "scenario.no_objective":
        verdict = (after.get("teams") or {}).get(str(team)) if isinstance(after.get("teams"), Mapping) else None
        still = isinstance(verdict, Mapping) and verdict.get("demostrado") is True and verdict.get("hecho") == FACT_NO_OBJECTIVE
        return Check(f.id, "scenario", HELD if still else CONTRADICTED, "still nothing at stake" if still else "the engine finds an objective")
    parts = _parts(f.id)
    if parts is None:
        return Check(f.id, "scenario", NOT_CHECKABLE, "the fact names no table")
    _side, table, objective = parts
    now = _objective(after, table, team, objective)
    if now is None:
        return Check(f.id, "scenario", NOT_CHECKABLE, "the objective is not in the reading after the match")
    if f.kind in ("scenario.secured", "scenario.lost"):
        said = str(f.params.get("estado"))
        return Check(f.id, "scenario", HELD if now == said else CONTRADICTED, f"{said} -> {now}")
    if f.kind == "scenario.result_effect":
        if result is None:
            return Check(f.id, "scenario", PENDING, "no result yet")
        mine, theirs = result if f.side == "home" else (result[1], result[0])
        outcome = "victoria" if mine > theirs else "derrota" if mine < theirs else "empate"
        effect = f.params.get(outcome)
        if effect not in ("conseguido", "descartado"):
            return Check(f.id, "scenario", NOT_EVALUABLE, f"{outcome}: the chronicle said nothing decided")
        return Check(f.id, "scenario", HELD if now == effect else CONTRADICTED, f"{outcome}: {effect} -> {now}")
    return Check(f.id, "scenario", NOT_EVALUABLE, "an open objective describes")


# ── the update after the line-up ────────────────────────────────────────────────────────────────────────────────────────────

def check_update(sentence: Mapping[str, Any], plan: cp.ContentPlan, squad: Squad) -> Check:
    """«starts», «on the bench», «not listed» of ``lineup-update-v1`` against the sheet and the minutes."""
    kind = str(sentence.get("kind") or "")
    fid = next((x for x in sentence.get("facts") or [] if not str(x).startswith("A:")), None)
    f = plan.by_id().get(str(fid)) if fid else None
    if kind == "alineacion" or f is None or ":" not in kind:
        return Check(str(fid or "A:"), "lineup", NOT_EVALUABLE, "the hour of the line-up")
    state = kind.split(":", 1)[1]
    if not squad.have_lineups:
        return Check(f.id, "lineup", PENDING, "no sheet")
    found = squad.by_name(str(f.side), str(f.params.get("player") or ""))
    if not found:
        return Check(f.id, "lineup", HELD if state == "no_convocado" else CONTRADICTED, "not in the sheet")
    starter = any(p.starter for p in found)
    ok = (state == "titular" and starter) or (state == "suplente" and not starter)
    return Check(f.id, "lineup", HELD if ok else CONTRADICTED, "starter" if starter else "bench")


# ── one chronicle ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _absences(plan: cp.ContentPlan) -> dict[str, story_service.Fact]:
    """The plan's absences as ``review.checks_of`` reads them (the side, the player, out or in doubt)."""
    out: dict[str, story_service.Fact] = {}
    for f in plan.facts:
        if f.kind.startswith("absence."):
            params = {**f.params, "side": f.side, "status": "doubtful" if f.kind == "absence.doubtful" else "out"}
            out[f.id] = story_service.Fact(f.id, "absence", "absence", params)
    return out


def judge_sentence(text: str, facts: Sequence[str], plan: cp.ContentPlan, *, written_at: datetime, squad: Squad,
                   evidence: Mapping[int, Mapping[str, Any]], team_ids: Mapping[str, int], after: Mapping[str, Any] | None,
                   result: tuple[int, int] | None) -> dict[str, Any]:
    by = plan.by_id()
    absences = _absences(plan)
    checks: list[Check] = []
    for fid in facts:
        f = by.get(fid)
        if f is not None and f.kind.startswith("absence."):
            checks += review.checks_of([fid], absences=absences, evidence={}, squad=squad, home=0, away=0)
        elif f is not None and f.kind.startswith("news.") and "evidence_id" in f.params:
            got = review.checks_of([f"E:{int(f.params['evidence_id'])}"], absences={}, evidence=evidence, squad=squad, home=0, away=0)
            checks += [Check(fid, c.code, c.verdict, c.detail) for c in got]
        elif f is not None and f.kind in ("scenario.no_objective", "scenario.secured", "scenario.lost", "scenario.result_effect"):
            checks.append(check_scenario(f, after=after, team_ids=team_ids, result=result))
        else:
            checks.append(Check(fid, "context", NOT_EVALUABLE, "history or context: it describes the match"))
    why = support(facts, plan, written_at=written_at)
    verdict = UNSUPPORTED if why is not None else review.verdict_of(checks)
    return {"text": text, "facts": list(facts), "supported": why is None, "unsupported_why": why, "verdict": verdict,
            "checks": [c.as_json() for c in checks]}


def metrics_of(row_metrics: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``chronicle-metrics-v1``: the measures of one chronicle the protocol of AD-F06 reads."""
    found = row_metrics.get("repetition")
    rep: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    chronicle = [i for i in items if i.get("part") == "chronicle"]
    supported = sum(1 for i in items if i["supported"])
    verdicts = Counter(str(i["verdict"]) for i in items)
    refs = Counter(str(c["verdict"]) for i in items for c in i["checks"])
    mandatory = row_metrics.get("mandatory")
    return {
        "version": METRICS_VERSION, "sentences": len(items), "chronicle_sentences": len(chronicle),
        "update_sentences": len(items) - len(chronicle), "supported": supported, "unsupported": len(items) - supported,
        "support_audit": None if not items else round(supported / len(items), 4),
        "support_verifier": row_metrics.get("support"), "proposed": row_metrics.get("proposed"), "kept": row_metrics.get("kept"),
        "plan_coverage": None if not mandatory else round(int(row_metrics.get("mandatory_cited") or 0) / int(mandatory), 4),
        "mandatory": mandatory, "mandatory_cited": row_metrics.get("mandatory_cited"),
        "generic_rate": rep.get("generic_rate"), "repeat_rate": rep.get("repeat_rate"), "repetition_mode": rep.get("mode"),
        "by_sentence": dict(sorted(verdicts.items())), "by_reference": dict(sorted(refs.items())),
        "firm_claims": refs[HELD] + refs[CONTRADICTED], "held": refs[HELD], "contradicted": refs[CONTRADICTED],
        "note": "un hecho que se sostuvo no causó el resultado; casi toda crónica describe",
    }


def review_items(content: Mapping[str, Any], plan: cp.ContentPlan, **kw: Any) -> list[dict[str, Any]]:
    """Every Spanish sentence of the chronicle (the English one says the same) and of its update, judged."""
    items: list[dict[str, Any]] = []
    update = content.get("actualizacion") if isinstance(content.get("actualizacion"), Mapping) else None
    superseded = {(s["section"], int(s["index"])) for s in (update or {}).get("superseded") or [] if isinstance(s, Mapping)}
    for section in cp.SECTIONS:
        for i, s in enumerate((content.get("es") or {}).get(section) or []):
            item = judge_sentence(str(s.get("text")), [str(x) for x in s.get("facts") or []], plan, **kw)
            items.append({"part": "chronicle", "section": section, "index": i, "superseded": (section, i) in superseded, **item})
    for i, s in enumerate((update or {}).get("sentences") or []):
        facts = [str(x) for x in s.get("facts") or []]
        why = support(facts, plan, written_at=kw["written_at"])
        check = check_update(s, plan, kw["squad"])
        verdict = UNSUPPORTED if why is not None else check.verdict
        items.append({"part": "update", "section": "actualizacion", "index": i, "superseded": False, "text": s.get("es"),
                      "facts": facts, "supported": why is None, "unsupported_why": why, "verdict": verdict, "checks": [check.as_json()]})
    return items


# ── the database ────────────────────────────────────────────────────────────────────────────────────────────────────────────

DUE_SQL: Final = """
SELECT c.id AS chronicle_id, c.fixture_id, c.version, c.packet_id, c.created_at, c.content, c.plan, c.metrics,
       f.kickoff_at, f.home_team_id, f.away_team_id, f.competition_season_id
  FROM (SELECT DISTINCT ON (x.fixture_id) x.id, x.fixture_id, x.version, x.packet_id, x.created_at, x.content, x.plan, x.metrics
          FROM ai.chronicles x JOIN core.fixtures g ON g.id = x.fixture_id
         WHERE x.status IN ('ok', 'partial') AND x.created_at < g.kickoff_at AND g.status_group = 'finished'
           AND g.kickoff_at >= %(since)s AND g.kickoff_at <= %(until)s AND x.packet_id IS NOT NULL
         ORDER BY x.fixture_id, x.created_at DESC, x.id DESC) c
  JOIN core.fixtures f ON f.id = c.fixture_id
 WHERE NOT EXISTS (SELECT 1 FROM ai.chronicle_reviews r WHERE r.chronicle_id = c.id AND r.version = %(version)s)
 ORDER BY f.kickoff_at
 LIMIT %(limit)s
"""
"""The newest chronicle each finished match had before its kick-off (its update included), when this version has not reviewed it."""
AFTER_SQL: Final = """
SELECT reading FROM intel.scenario_readings
 WHERE competition_season_id = %(cs)s AND computed_at >= %(after)s AND computed_at <= %(at)s
 ORDER BY computed_at, id LIMIT 1
"""
"""The engine's first reading after the match (``intel_scenario_readings_season``)."""
INSERT_SQL: Final = """
INSERT INTO ai.chronicle_reviews (fixture_id, narrative_id, chronicle_id, version, created_at, narrative_version, packet_id, trace_id, status,
                                  outcome, items, summary, picks)
VALUES (%(fixture)s, NULL, %(chronicle)s, %(version)s, %(at)s, %(chronicle_version)s, %(packet)s, %(trace)s, %(status)s,
        %(outcome)s, %(items)s, %(summary)s, %(picks)s)
ON CONFLICT (chronicle_id, version) WHERE chronicle_id IS NOT NULL DO NOTHING
RETURNING id
"""


def _evidence_ids(plan: cp.ContentPlan, content: Mapping[str, Any]) -> list[int]:
    cited = {str(x) for section in cp.SECTIONS for s in (content.get("es") or {}).get(section) or [] for x in s.get("facts") or []}
    by = plan.by_id()
    return sorted({int(by[x].params["evidence_id"]) for x in cited if x in by and "evidence_id" in by[x].params})


@dataclass
class RunReport:
    due: int = 0
    written: int = 0
    waiting: int = 0
    unsupported: int = 0
    firm: int = 0
    contradicted: int = 0
    failed: int = 0
    ids: list[int] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def review_one(conn: psycopg.Connection[Any], due: Mapping[str, Any], *, at: datetime) -> dict[str, Any] | None:
    """The review of one chronicle, or None while the match has nothing to judge it by (no line-ups and no minutes yet)."""
    fixture = int(due["fixture_id"])
    result = review.rows_of(conn, review.RESULT_SQL, {"fixture": fixture})
    if not result or result[0]["reg_goals_home"] is None or result[0]["reg_goals_away"] is None:
        return None
    squad = review.squad_of(review.rows_of(conn, review.LINEUP_SQL, {"fixture": fixture}),
                            review.rows_of(conn, review.STATS_SQL, {"fixture": fixture}))
    if not squad.ready:
        return None
    plan = cp.from_json(due["plan"])
    content: Mapping[str, Any] = due["content"]
    evidence = {int(r["id"]): r for r in review.rows_of(conn, review.EVIDENCE_SQL, {"ids": _evidence_ids(plan, content)})}
    after = None
    if due["competition_season_id"] is not None:
        found = review.rows_of(conn, AFTER_SQL, {"cs": int(due["competition_season_id"]), "after": due["kickoff_at"] + AFTER_MATCH, "at": at})
        after = found[0]["reading"] if found and isinstance(found[0]["reading"], Mapping) else None
    score = (int(result[0]["reg_goals_home"]), int(result[0]["reg_goals_away"]))
    items = review_items(content, plan, written_at=due["created_at"], squad=squad, evidence=evidence,
                         team_ids={"home": int(due["home_team_id"]), "away": int(due["away_team_id"])}, after=after, result=score)
    metrics = due["metrics"] if isinstance(due["metrics"], Mapping) else {}
    picks = [{"decision_id": None if r["decision_id"] is None else int(r["decision_id"]), "postmortem_version": r["version"],
              "market": r["market_key"], "selection": r["selection"], "line": r["line"], "outcome": r["outcome"],
              "decision_quality": r["decision_quality"], "verdict": r["verdict"]} for r in review.rows_of(conn, review.PICKS_SQL, {"fixture": fixture})]
    return {"fixture_id": fixture, "chronicle_id": int(due["chronicle_id"]), "chronicle_version": str(due["version"]),
            "packet_id": int(due["packet_id"]), "status": "reviewed",
            "outcome": {"home_goals": score[0], "away_goals": score[1], "line_ups": squad.have_lineups, "minutes": squad.have_minutes,
                        "scenarios_after": after is not None},
            "items": items, "summary": metrics_of(metrics, items), "picks": picks}


def store(conn: psycopg.Connection[Any], r: Mapping[str, Any], *, at: datetime) -> int | None:
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {
            "fixture": r["fixture_id"], "chronicle": r["chronicle_id"], "version": VERSION, "at": at, "chronicle_version": r["chronicle_version"],
            "packet": r["packet_id"], "trace": str(match_trace_id(int(r["fixture_id"]))), "status": r["status"], "outcome": Jsonb(r["outcome"]),
            "items": Jsonb(r["items"]), "summary": Jsonb(r["summary"]), "picks": Jsonb(r["picks"])})
        row = cur.fetchone()
    return None if row is None else int(row[0])


def run(conn: psycopg.Connection[Any], *, at: datetime, apply: bool = True, limit: int = LIMIT) -> RunReport:
    """Reviews the chronicles of the matches that finished at least ``SETTLE`` ago. ``apply=False`` judges and writes nothing."""
    report = RunReport()
    due = review.rows_of(conn, DUE_SQL, {"since": at - LOOKBACK - SETTLE, "until": at - SETTLE, "version": VERSION, "limit": limit})
    report.due = len(due)
    for row in due:
        conn.execute("SAVEPOINT chronicle_v2_one")
        try:
            judged = review_one(conn, row, at=at)
            stored = store(conn, judged, at=at) if (judged is not None and apply) else None
            conn.execute("RELEASE SAVEPOINT chronicle_v2_one")
        except Exception as exc:  # one chronicle that cannot be judged leaves nothing behind and holds back no other
            conn.execute("ROLLBACK TO SAVEPOINT chronicle_v2_one")
            conn.execute("RELEASE SAVEPOINT chronicle_v2_one")
            report.failed += 1
            report.failures.append(f"chronicle {row.get('chronicle_id')}: {type(exc).__name__}: {exc}"[:300])
            continue
        if judged is None:
            report.waiting += 1
            continue
        report.unsupported += int(judged["summary"]["unsupported"])
        report.firm += int(judged["summary"]["firm_claims"])
        report.contradicted += int(judged["summary"]["contradicted"])
        if not apply or stored is not None:
            report.written += 1
            if stored is not None:
                report.ids.append(stored)
    return report


__all__ = ["JOB", "METRICS_VERSION", "SWITCH", "UNSUPPORTED", "VERSION", "RunReport", "check_scenario", "check_update", "judge_sentence",
           "metrics_of", "mode", "review_items", "review_one", "run", "store", "support"]
