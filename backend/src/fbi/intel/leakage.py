"""Data-leakage audit - ``leak-audit-v3``: did any decision use something that was not known at its ``known_at``?

Run every night over the decisions taken on a Bogotá day, and in the tests. One row per rule
(``intel.audit_checks``): how many decisions were checked and how many violate it, with examples. The rules:

    known_before_kickoff     known_at < kick-off
    price_known              price_at <= known_at (the consensus row the price came from was captured by then)
    pick_known               the pick (the model's probability) was created, and its data cut off, by known_at
    calibrator_known         the calibrator was fitted by known_at, on results settled before it was fitted
    review_known             the AI review the decision read was made by known_at
    evidence_known           every evidence item it cites was retrieved (and, when dated, published) by known_at
    consensus_known          the de-vigged consensus at the price's timestamp exists and was captured by known_at
    tie_legs_known           (v2, plan F2) the AI packets built on the day: every earlier leg of its tie that the packet
                             cites kicked off before the match (so it is not the match itself, nor a later leg) and had
                             its result recorded by the packet's moment. Counted per cited leg; the examples are packet
                             ids, not decision ids. The first rule that reads packets: what a tie went on to decide is never
                             a pre-match input (``fbi.competitions.context`` is the one door; this is the nightly proof).
    referee_known            (v3, plan F3) the AI packets built on the day that name a referee: the provider's observation the
                             name comes from (``fixture.referee_seen_at``) is not later than the packet's moment, is a row that
                             exists (in ``core.fixture_officials`` when the packet carries a referee id, in ``core.fixture_facts``
                             when it kept the string), and no newer observation of the provider existed by the packet's moment
                             (a packet that read an older answer than the one the provider had given). A name with no moment
                             cannot be found among the rows, so it is a violation too. It never looks at WHO the
                             spelling is today: a merge or a split changes the person, not what the provider said when. Packets
                             without the field (built by an earlier version) are not read. Examples are packet ids.
    national_known           (v3, plan F3) the AI packets built on the day that carry the people of a national-team match
                             (``dossier.national``, ``fbi.intel.national``): every match the block cites - the previous match
                             whose sheet stands in for the call-up, the last club match of a player's form, the last squad and the
                             last cap of his record - kicked off before the match of the packet and had its result recorded by the
                             packet's moment; a block that says its squad is the match's own sheet had it fetched by then; and no
                             day it gives for a club (``since``, ``last_seen``) is later than the day of the packet. One check
                             per cited fact. Examples are packet ids.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds

VERSION = "leak-audit-v3"

BASE = "SELECT d.* FROM intel.decisions d WHERE d.known_at >= %(start)s AND d.known_at < %(end)s"

PACKETS = ("SELECT m.id, m.fixture_id, m.as_of, m.content FROM ai.match_packets m "
           "WHERE m.built_at >= %(start)s AND m.built_at < %(end)s")

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
    "tie_legs_known": f"""
        WITH p AS ({PACKETS}), l AS (
            SELECT p.id AS packet_id, p.as_of, p.fixture_id, (x ->> 'fixture_id')::bigint AS leg_id
              FROM p CROSS JOIN LATERAL jsonb_array_elements(
                     CASE WHEN jsonb_typeof(p.content #> '{{phase,tie,previous}}') = 'array'
                          THEN p.content #> '{{phase,tie,previous}}' ELSE '[]'::jsonb END) AS x),
        c AS (
            SELECT l.packet_id,
                   (r.settled_at IS NULL OR r.settled_at > l.as_of OR g.id IS NULL
                    OR g.kickoff_at >= f.kickoff_at) AS bad
              FROM l JOIN core.fixtures f ON f.id = l.fixture_id
                     LEFT JOIN core.fixtures g ON g.id = l.leg_id
                     LEFT JOIN core.fixture_results r ON r.fixture_id = l.leg_id)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
    "referee_known": f"""
        WITH p AS ({PACKETS}), r AS (
            SELECT p.id AS packet_id, p.fixture_id, p.as_of,
                   (p.content #>> '{{fixture,referee_id}}')::bigint AS referee_id,
                   (p.content #>> '{{fixture,referee_seen_at}}')::timestamptz AS seen
              FROM p WHERE jsonb_exists(p.content -> 'fixture', 'referee_seen_at')
                       AND jsonb_typeof(p.content #> '{{fixture,referee}}') = 'string'),
        c AS (
            SELECT r.packet_id,
                   (r.seen > r.as_of
                    OR NOT CASE WHEN r.referee_id IS NOT NULL THEN
                        EXISTS (SELECT 1 FROM core.fixture_officials o
                                 WHERE o.fixture_id = r.fixture_id AND o.role = 'referee' AND o.observed_at = r.seen)
                        AND NOT EXISTS (SELECT 1 FROM core.fixture_officials n
                                         WHERE n.fixture_id = r.fixture_id AND n.role = 'referee'
                                           AND n.observed_at > r.seen AND n.observed_at <= r.as_of)
                    ELSE
                        EXISTS (SELECT 1 FROM core.fixture_facts x
                                 WHERE x.fixture_id = r.fixture_id AND x.observed_at = r.seen AND x.referee IS NOT NULL)
                    END) AS bad
              FROM r)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
    "national_known": f"""
        WITH p AS ({PACKETS}), s AS (
            SELECT p.id AS packet_id, p.fixture_id, p.as_of, v.side, p.content #> ARRAY['dossier', 'national', v.side] AS blk
              FROM p CROSS JOIN (VALUES ('home'), ('away')) AS v(side)
             WHERE jsonb_typeof(p.content #> ARRAY['dossier', 'national', v.side, 'players']) = 'array'),
        pl AS (
            SELECT s.packet_id, s.fixture_id, s.as_of, x FROM s CROSS JOIN LATERAL jsonb_array_elements(s.blk -> 'players') AS x),
        cited AS (
            SELECT s.packet_id, s.fixture_id, s.as_of, (s.blk ->> 'squad_fixture')::bigint AS leg FROM s WHERE s.blk ->> 'squad' = 'last_match'
            UNION ALL SELECT pl.packet_id, pl.fixture_id, pl.as_of, (pl.x #>> '{{form,last_fixture}}')::bigint FROM pl
                       WHERE pl.x #>> '{{form,last_fixture}}' IS NOT NULL
            UNION ALL SELECT pl.packet_id, pl.fixture_id, pl.as_of, (pl.x #>> '{{caps,last_squad_fixture}}')::bigint FROM pl
                       WHERE pl.x #>> '{{caps,last_squad_fixture}}' IS NOT NULL
            UNION ALL SELECT pl.packet_id, pl.fixture_id, pl.as_of, (pl.x #>> '{{caps,last_cap_fixture}}')::bigint FROM pl
                       WHERE pl.x #>> '{{caps,last_cap_fixture}}' IS NOT NULL),
        c AS (
            SELECT k.packet_id, (r.settled_at IS NULL OR r.settled_at > k.as_of OR g.kickoff_at >= f.kickoff_at) AS bad
              FROM cited k JOIN core.fixtures f ON f.id = k.fixture_id
                   LEFT JOIN core.fixtures g ON g.id = k.leg LEFT JOIN core.fixture_results r ON r.fixture_id = k.leg
            UNION ALL
            SELECT s.packet_id, NOT EXISTS (SELECT 1 FROM core.fixture_lineups l WHERE l.fixture_id = s.fixture_id
                                              AND l.team_side = s.side AND l.fetched_at <= s.as_of)
              FROM s WHERE s.blk ->> 'squad' = 'lineup'
            UNION ALL
            SELECT pl.packet_id, ((pl.x #>> '{{club,since}}')::date > (pl.as_of AT TIME ZONE 'UTC')::date
                                  OR (pl.x #>> '{{club,last_seen}}')::date > (pl.as_of AT TIME ZONE 'UTC')::date)
              FROM pl WHERE jsonb_typeof(pl.x -> 'club') = 'object')
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
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
