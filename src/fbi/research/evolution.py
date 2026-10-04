"""The evolution loop: results become memory and proposals - never rule changes.

    result ──► memory (what we learned, with its evidence; superseded, never deleted)
           └─► hypothesis PROPOSED (by the system, the AI or the owner)
                   └─ the owner ACCEPTS or REJECTS it ─► research experiment ─► gate ─► explicit promotion

A bad result does not change a threshold, a model or a pick rule here: it writes down what
was seen and, where the evidence points somewhere, proposes an experiment for the owner to
accept or reject. Experiments run in research (``analytics.experiments``); nothing is
promoted without a passed gate and an explicit promotion (``docs/rebuild/EVOLUTION_LOOP.md``).

The system's proposals are keyed (``dedup_key``): the same evidence proposes once, however
many times the daily monitor sees it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.research.pick_audit import AuditResult
from fbi.research.prospective import ProspectiveResult, SegmentResult
from fbi.research.roles import ROLES

SOURCES = ("research_v2", "prospective", "audit", "owner")
MIN_Z = 3.0
"""How many standard errors an audit figure must be from zero before the system proposes
anything on it."""
CLOSE_TOO_EARLY_MINUTES = 120
"""A 'close' captured more than this long before kick-off is not a closing price."""


class DecisionError(ValueError):
    pass


def remember(conn: psycopg.Connection[Any], *, topic: str, finding: str, evidence: dict[str, Any], source: str,
             at: datetime) -> int | None:
    """Write a finding; the topic's current finding is superseded (kept). An unchanged
    finding writes nothing. Returns the new row's id, or None."""
    if source not in SOURCES:
        raise ValueError(f"unknown memory source {source!r}")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, finding FROM analytics.research_memory WHERE topic = %s AND superseded_by IS NULL "
                    "ORDER BY id DESC LIMIT 1", (topic,))
        current = cur.fetchone()
        if current is not None and current["finding"] == finding:
            return None
        cur.execute("INSERT INTO analytics.research_memory (topic, finding, evidence, source, created_at) "
                    "VALUES (%s,%s,%s,%s,%s) RETURNING id", (topic, finding, Json(evidence), source, at))
        row = cur.fetchone()
        assert row is not None
        new_id = int(row["id"])
        if current is not None:
            cur.execute("UPDATE analytics.research_memory SET superseded_by = %s WHERE id = %s",
                        (new_id, current["id"]))
    return new_id


def propose(conn: psycopg.Connection[Any], *, title: str, hypothesis: str, rationale: str,
            evidence: dict[str, Any], proposed_by: str, at: datetime, key: str | None = None) -> int | None:
    """A hypothesis for the owner. A keyed proposal is made once. Returns its id, or None
    when the same key was proposed before."""
    if proposed_by not in ("ai", "owner", "system"):
        raise ValueError("proposed_by is ai, owner or system")
    if proposed_by == "ai" and key is None:
        key = "ai:" + hashlib.sha256(" ".join(title.lower().split()).encode()).hexdigest()[:24]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, evidence, "
            "dedup_key, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dedup_key) WHERE dedup_key IS NOT "
            "NULL DO NOTHING RETURNING id",
            (proposed_by, title[:160], hypothesis, rationale, Json(evidence), key, at))
        row = cur.fetchone()
    return None if row is None else int(row[0])


def decide(conn: psycopg.Connection[Any], hypothesis_id: int, *, accept: bool, user_id: int, note: str | None,
           at: datetime) -> str:
    """The owner's decision on a PROPOSED hypothesis. Accepting queues an experiment in
    research; it changes no rule, model or pick."""
    status = "ACCEPTED" if accept else "REJECTED"
    with conn.cursor() as cur:
        cur.execute("UPDATE analytics.research_hypotheses SET status = %s, decided_at = %s, decided_by = %s, "
                    "decision_note = %s WHERE id = %s AND status = 'PROPOSED' RETURNING id",
                    (status, at, user_id, None if note is None else note[:500], hypothesis_id))
        if cur.fetchone() is None:
            cur.execute("SELECT status FROM analytics.research_hypotheses WHERE id = %s", (hypothesis_id,))
            row = cur.fetchone()
            raise DecisionError("no such hypothesis" if row is None else f"already {row[0]}")
    return status


def link_experiment(conn: psycopg.Connection[Any], hypothesis_id: int, experiment_id: int, *, done: bool) -> None:
    """An experiment that tests an ACCEPTED hypothesis: RUNNING while it runs, DONE after."""
    with conn.cursor() as cur:
        cur.execute("UPDATE analytics.research_hypotheses SET experiment_ids = array_append(experiment_ids, %s), "
                    "status = %s WHERE id = %s AND status IN ('ACCEPTED', 'RUNNING')",
                    (experiment_id, "DONE" if done else "RUNNING", hypothesis_id))


# ── what the system learns from the results ─────────────────────────────────

def _pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:+.1f} %"


@dataclass
class Learned:
    memory: list[int] = field(default_factory=list)
    proposals: list[int] = field(default_factory=list)


def learn_from_audit(conn: psycopg.Connection[Any], audit: AuditResult, *, at: datetime) -> Learned:
    out = Learned()
    o = audit.overall
    if not o.get("n"):
        return out
    finding = (f"{o['n']} settled shadow picks on {o['fixtures']} matches: realised {_pct(o['roi'])}, claimed EV "
               f"{_pct(o['claimed_ev'])}, EV at the pick {_pct(o.get('ev_at_pick'))}, movement "
               f"{_pct(o.get('movement'))}, EV at our last capture {_pct(o['ev_at_close'])}, luck {_pct(o['luck'])}"
               + ("" if o.get("luck_z") is None else f" (z {o['luck_z']:+.1f} if the close is right)"))
    mid = remember(conn, topic="audit:shadow_picks", finding=finding, evidence={"overall": o, "at": at.isoformat()},
                   source="audit", at=at)
    if mid:
        out.memory.append(mid)
    evp, se = o.get("ev_at_pick"), o.get("ev_at_pick_se")
    if evp is not None and se and evp < 0 and abs(evp / se) >= MIN_Z:
        pid = propose(conn, key="audit:price_only:v1", proposed_by="system", at=at,
                      title="Price-only selection: a candidate only where the best price beats the de-vigged "
                            "consensus",
                      hypothesis="Restricting candidates to prices above the market's own fair price (EV at the "
                                 "pick > 0 by the consensus) gives a non-negative expected return where the model's "
                                 "disagreement with the market does not.",
                      rationale=f"The audit shows the selected picks were already at {_pct(evp)} (±{_pct(se)[1:]}) "
                                "by the market's view when they were taken: the value gate's edge is disagreement, "
                                "not information. Research only - no threshold changes until it passes a gate.",
                      evidence={"ev_at_pick": evp, "se": se, "n": o["n"]})
        if pid:
            out.proposals.append(pid)
    minutes = audit.median_minutes_before
    if minutes is not None and minutes > CLOSE_TOO_EARLY_MINUTES:
        pid = propose(conn, key="audit:close_capture:v1", proposed_by="system", at=at,
                      title="Capture the consensus near kick-off for fixtures with picks",
                      hypothesis="A consensus captured within the last hour before kick-off measures closing-line "
                                 "value; the current one cannot.",
                      rationale=f"Our last consensus before kick-off is a median {minutes / 60:.1f} h before it, "
                                "so 'movement' in the audit is not closing-line value.",
                      evidence={"median_minutes_before_kickoff": minutes})
        if pid:
            out.proposals.append(pid)
    return out


def _segment_finding(r: SegmentResult) -> str:
    c = r.comparison
    assert c is not None
    d = c.logloss_diff
    return (f"{r.model} vs the closing consensus, segment {r.segment}: log loss {d.mean:+.4f} [{d.lo:+.4f}, "
            f"{d.hi:+.4f}] on {r.n_common} matches over {c.n_blocks} days")


def learn_from_prospective(conn: psycopg.Connection[Any], p: ProspectiveResult, *, at: datetime) -> Learned:
    out = Learned()
    for r in p.rows:
        if not r.judged or r.comparison is None:
            continue
        mid = remember(conn, topic=f"prospective:{r.segment}:{r.model}", finding=_segment_finding(r),
                       evidence=r.as_json(), source="prospective", at=at)
        if mid:
            out.memory.append(mid)
        d = r.comparison.logloss_diff
        if d.hi < 0:
            pid = propose(conn, key=f"prospective:beats_close:{r.segment}:{r.model}", proposed_by="system", at=at,
                          title=f"{r.model} beats the close prospectively in {r.segment}: confirm in research",
                          hypothesis=f"{r.model}'s forecasts carry information the closing consensus lacks in "
                                     f"{r.segment}.",
                          rationale=_segment_finding(r) + ". One window is not a result: extend it and test the "
                                    "segment walk-forward before any role changes.",
                          evidence=r.as_json())
            if pid:
                out.proposals.append(pid)
        elif r.w is not None and r.w[1] > 0:
            pid = propose(conn, key=f"prospective:adds_info:{r.segment}:{r.model}", proposed_by="system", at=at,
                          title=f"{r.model} adds information to the close in {r.segment}: test a blend",
                          hypothesis=f"A blend of the close and {r.model} beats the close alone in {r.segment}.",
                          rationale=f"Blend weight {r.w[0]:+.2f} [{r.w[1]:+.2f}, {r.w[2]:+.2f}] above zero.",
                          evidence=r.as_json())
            if pid:
                out.proposals.append(pid)
    return out


PLAN = (
    ("plan:E4:shots", "E4: shots and shots-on-target ratings as features",
     "Shot-based team ratings forecast totals and BTTS better than goal-based ones.",
     "New information, not new algorithms, is what the literature says can add to the market "
     "(docs/research/MODEL_RESEARCH_V2_2026.md, sections 1 and 8)."),
    ("plan:E6:lineups", "E6: line-up and player-strength features",
     "Knowing who plays moves a forecast where the market has not priced it yet.",
     "The second source of new information in the research plan; line-ups are stored from about an hour before "
     "kick-off."),
    ("plan:totals_history", "Historical totals prices, so O/U and BTTS can be judged against a market",
     "Over/Under and BTTS forecasts can be compared with a de-vigged market as 1X2 is.",
     "Research V2 judged 1X2 only: no historical totals price is stored."),
)


def learn_from_v2(conn: psycopg.Connection[Any], *, run: str, champion: str, roles: dict[str, tuple[str, str]],
                  at: datetime) -> Learned:
    """``roles``: model -> (role, reason) of a stored research-V2 run."""
    out = Learned()
    mid = remember(conn, topic="research_v2:champion", finding=f"The market champion is {champion} ({run}).",
                   evidence={"run": run}, source="research_v2", at=at)
    if mid:
        out.memory.append(mid)
    for model, (role, reason) in sorted(roles.items()):
        if role not in ROLES:
            continue
        mid = remember(conn, topic=f"research_v2:role:{model}", finding=f"{model}: {role} - {reason}",
                       evidence={"run": run, "role": role}, source="research_v2", at=at)
        if mid:
            out.memory.append(mid)
        if role == "CHALLENGER":
            pid = propose(conn, key=f"v2:challenger:{model}:{run}", proposed_by="system", at=at,
                          title=f"Review {model} for promotion (CHALLENGER in {run})",
                          hypothesis=f"{model} should feed qualified picks.",
                          rationale=reason + " A challenger waits for an explicit promotion by the owner.",
                          evidence={"run": run})
            if pid:
                out.proposals.append(pid)
    if not any(role == "CHALLENGER" for role, _ in roles.values()):
        for key, title, hypothesis, rationale in PLAN:
            pid = propose(conn, key=key, proposed_by="system", at=at, title=title, hypothesis=hypothesis,
                          rationale=rationale + f" No model beat the market in {run}.", evidence={"run": run})
            if pid:
                out.proposals.append(pid)
    return out
