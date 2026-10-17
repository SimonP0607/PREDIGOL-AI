"""Data-leakage audit - ``leak-audit-v1``: did any decision use something that was not known at its ``known_at``?

Run every night over the decisions taken on a Bogotá day, and in the tests. One row per rule
(``intel.audit_checks``): how many decisions were checked and how many violate it, with examples. The rules:

    known_before_kickoff     known_at < kick-off
    price_known              price_at <= known_at (the consensus row the price came from was captured by then)
    pick_known               the pick (the model's probability) was created, and its data cut off, by known_at
    calibrator_known         the calibrator was fitted by known_at, on results settled before it was fitted
    review_known             the AI review the decision read was made by known_at
    evidence_known           every evidence item it cites was retrieved (and, when dated, published) by known_at
    consensus_known          the de-vigged consensus at the price's timestamp exists and was captured by known_at
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds

VERSION = "leak-audit-v1"

BASE = "SELECT d.* FROM intel.decisions d WHERE d.known_at >= %(start)s AND d.known_at < %(end)s"

RULES: dict[str, str] = {
    "known_before_kickoff": f"""
        WITH d AS ({BASE}) SELECT count(*) AS n, count(*) FILTER (WHERE NOT (d.known_at < d.kickoff_at)) AS bad,
               (array_agg(d.id) FILTER (WHERE NOT (d.known_at < d.kickoff_at)))[1:5] AS examples FROM d""",
    "price_known": f"""
        WITH d AS ({BASE}) SELECT count(*) FILTER (WHERE d.price_at IS NOT NULL) AS n,
               count(*) FILTER (WHERE d.price_at > d.known_at) AS bad,
               (array_agg(d.id) FILTER (WHERE d.price_at > d.known_at))[1:5] AS examples FROM d""",
    "pick_known": f"""
        WITH d AS ({BASE}) SELECT count(*) AS n,
               count(*) FILTER (WHERE p.created_at > d.known_at OR p.data_cutoff_ts > d.known_at) AS bad,
               (array_agg(d.id) FILTER (WHERE p.created_at > d.known_at OR p.data_cutoff_ts > d.known_at))[1:5]
                 AS examples
          FROM d JOIN picks.picks p ON p.id = d.pick_id""",
    "calibrator_known": f"""
        WITH d AS ({BASE}) SELECT count(*) AS n,
               count(*) FILTER (WHERE c.fitted_at > d.known_at OR (c.settled_max IS NOT NULL
                                AND c.settled_max >= c.known_at)) AS bad,
               (array_agg(d.id) FILTER (WHERE c.fitted_at > d.known_at OR (c.settled_max IS NOT NULL
                                AND c.settled_max >= c.known_at)))[1:5] AS examples
          FROM d JOIN intel.calibrators c ON c.id = d.calibrator_id""",
    "review_known": f"""
        WITH d AS ({BASE}) SELECT count(*) AS n, count(*) FILTER (WHERE r.reviewed_at > d.known_at) AS bad,
               (array_agg(d.id) FILTER (WHERE r.reviewed_at > d.known_at))[1:5] AS examples
          FROM d JOIN ai.pick_reviews r ON r.id = d.review_id""",
    "evidence_known": f"""
        WITH d AS ({BASE}), e AS (
            SELECT d.id AS decision_id, d.known_at, ev.retrieved_at, ev.published_at
              FROM d CROSS JOIN LATERAL unnest(d.evidence_ids) AS x(eid) JOIN ai.evidence ev ON ev.id = x.eid)
        SELECT count(*) AS n,
               count(*) FILTER (WHERE e.retrieved_at > e.known_at OR e.published_at > e.known_at) AS bad,
               (array_agg(DISTINCT e.decision_id) FILTER (WHERE e.retrieved_at > e.known_at
                                                          OR e.published_at > e.known_at))[1:5] AS examples FROM e""",
    "consensus_known": f"""
        WITH d AS ({BASE}) SELECT count(*) FILTER (WHERE d.price_at IS NOT NULL) AS n,
               count(*) FILTER (WHERE d.price_at IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM market.market_consensus m WHERE m.fixture_id = d.fixture_id
                      AND m.market_key = d.market_key AND m.selection = d.selection AND m.line = d.line
                      AND m.as_of = d.price_at AND m.devig_method = 'shin' AND m.as_of <= d.known_at)) AS bad,
               (array_agg(d.id) FILTER (WHERE d.price_at IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM market.market_consensus m WHERE m.fixture_id = d.fixture_id
                      AND m.market_key = d.market_key AND m.selection = d.selection AND m.line = d.line
                      AND m.as_of = d.price_at AND m.devig_method = 'shin' AND m.as_of <= d.known_at)))[1:5]
                 AS examples FROM d""",
}


def audit_day(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> dict[str, dict[str, Any]]:
    start, end = day_bounds(day)
    out: dict[str, dict[str, Any]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for rule, sql in RULES.items():
            cur.execute(sql, {"start": start, "end": end})
            r = cur.fetchone() or {}
            n, bad = int(r.get("n") or 0), int(r.get("bad") or 0)
            examples = [int(x) for x in (r.get("examples") or [])]
            out[rule] = {"checked": n, "violations": bad, "examples": examples}
            cur.execute("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations, "
                        "examples) VALUES (%s,%s,%s,%s,%s,%s,%s)", (day, at, VERSION, rule, n, bad, Jsonb(examples)))
    return out
