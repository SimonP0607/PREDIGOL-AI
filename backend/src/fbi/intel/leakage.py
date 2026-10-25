"""Data-leakage audit - ``leak-audit-v7``: did any decision use something that was not known at its ``known_at``?

Run every night over the decisions taken on a Bogotá day, and in the tests. One row per rule
(``intel.audit_checks``): how many decisions were checked and how many violate it, with examples. The rules:

    known_before_kickoff     known_at < kick-off
    price_known              price_at <= known_at (the consensus row the price came from was captured by then)
    pick_known               the pick (the model's probability) was created, and its data cut off, by known_at
    calibrator_known         the calibrator was fitted by known_at, on results settled before it was fitted
    review_known             the AI review the decision read was made by known_at
    evidence_known           every evidence item it cites was retrieved (and, when dated, published) by known_at
    consensus_known          the de-vigged consensus at the price's timestamp exists and was captured by known_at (v7: only the decisions
                             of the pipeline's own layer, ``decision-v1``: a family prices from the quotes of the books, not from this table)
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
    absences_known           (v3, plan F3) the AI packets built on the day that list absent players (``absences``): every player
                             listed was named by an answer of the provider recorded by the packet's moment
                             (``core.player_availability_obs``), that answer is the newest one about him by then - a player a later
                             answer cleared has recovered, and a packet that still lists him read a row that was no longer true - and
                             the kind of absence is the one the answer gave. One check per listed player. Examples are packet ids.
    forecast_known           (v4, plan F5) the AI packets built on the day that carry PrediGol's forecast (``forecast``,
                             ``models.match_forecasts``): each market's set was written (``known_at``) by the packet's moment, is a
                             row that exists for that fixture, market, line and model, and no newer set of that market existed
                             by the packet's moment (a packet that read an older forecast than the one PrediGol had stated).
                             One check per market cited. Examples are packet ids.
    calendar_known           (v5, plan F4) the AI packets built on the day that carry the calendar of a team in every competition
                             (``schedule.calendar``, ``fbi.competitions.team_calendar``): the reading of a team's list the packet
                             says it used (``fetched_at``) is a row that exists for that team, is not later than the packet's moment
                             and is the newest one by then (a minute of leeway for a reading that was being committed); a side that
                             says «never read» had no reading by then; a side that says it is whole (``complete``) was read at most
                             96 hours before the moment. And every match the block cites (``recent``, ``upcoming``) is a row that
                             exists with the kick-off cited: one PrediGol follows (``core.fixtures``) that kicked off before the
                             moment or was recorded by it, one it does not (``core.calendar_matches``) that kicked off before the
                             moment or was observed by it - so a cup tie announced after the packet was built was never in it. One
                             check per side and per match cited. Examples are packet ids.
    h2h_known                (v6, plan F6) the AI packets built on the day that carry the weighted head-to-head (``h2h.meetings``,
                             ``fbi.intel.h2h``): every meeting the block cites is a row that exists, between the two sides of the
                             packet's match, played to a result (``FT`` / ``AET`` / ``PEN``), kicked off before the match, had its result
                             recorded by the packet's moment, and is as old as the block says (``days_ago``, counted from the match's
                             kick-off); a meeting for which the block claims to know whether a coach changed had a match sheet
                             fetched by then. And, one check per packet, no meeting that was known by the moment was left out in
                             favour of an older one (the last eight, or all when there are fewer). Examples are packet ids.
    scenarios_known          (v6, plan F6) the AI packets built on the day that carry the scenarios of the match (``scenarios``,
                             ``fbi.intel.scenarios``): the table the effect of the match is computed on is a snapshot that
                             exists, was taken by the packet's moment and not after the kick-off, and holds each side with the
                             rank, points and games played the block cites (one check for the snapshot and one per side); and
                             the reading of a second leg uses the aggregate of the packet's own ``phase`` block - the earlier legs
                             the packet knew - and its statements about the margins are the arithmetic of that aggregate (one check
                             per packet). Examples are packet ids.
    tactics_known            (v6, plan F6) the AI packets built on the day that carry the observable tactics of each side
                             (``dossier.tactics``, ``fbi.intel.tactics``): every match the block cites as its sample is a row that
                             exists, of the team, kicked off before the match and within the window, with its result recorded by
                             the packet's moment; every match it says it read the events of has an event fetched by then, and every
                             match it says it read the sheet of has a line-up of that team fetched by then (a row the post-match job rewrote
                             after the moment, in a match already settled by then, is a re-read and counts as fetched by then: see
                             ``_reread``). And, one check per side
                             and packet, the sample is at most the last ``N`` matches and none known by the moment was left out in
                             favour of an older one, what was read is inside the sample, the goals the block counts are the goals
                             of the 90 minutes of the matches it read events of (from their results), and its half-time sample is the
                             matches of the sample whose result has a half-time score. Examples are packet ids.
    factors_known            (v6, plan F6) the AI packets built on the day that carry the status of each context factor (``factors``,
                             ``fbi.intel.factors``): for every factor the packet lists, the status it states, the decision it cites
                             and the experiment that decision names are exactly those of the newest decision about that factor at
                             that version that had been taken by the packet's moment - so a validation decided after the moment is
                             not in the packet, a retired one is not still there, a decision that exists is not left out, and a
                             factor with no decision is DESCRIPTIVE (a packet that says it could not read the registry is not read
                             here: it states DESCRIPTIVE for everything, the safe side). And, one check per block that says its own
                             ``status`` (the head-to-head, the scenarios, the tactics), that status and the block's ``version`` are
                             the ones the packet's factor entry states - so a validation of another version of the code is not used
                             for this one. Examples are packet ids.
    family_forecast_known    (v7, plan F11) the decisions the FAMILIES took on the day (``decision-fam-v1``, ``fbi.familydecisions``): the
                             forecast each one cites (``filters``, ``model``, ``data.forecast_id``) is a row that exists for that match,
                             model, market, line and selection, was written (``known_at``) and had its data cut off by the decision's
                             moment, and no newer forecast of that selection by the same model existed by then (a decision that read an
                             older forecast than the one that stood). A decision that cites none is a violation. Examples are decision ids.
    family_price_known       (v7, plan F11) the same decisions' price: the bookmaker it names had quoted that very price for that selection
                             and line, before the match, by the decision's moment (``captured_at``). Whether it was still the book's price
                             then is not asked: a payload read again by a newer extractor writes its quotes with the instant it was
                             fetched, so a quote can appear for a moment the decision could not have known of, and taking an older price
                             is staleness, not a leak. This is what ``consensus_known`` is for the pipeline's layer (a family prices from
                             the quotes of the books, not from the consensus table). Examples are decision ids.

The other rules over decisions (``known_before_kickoff``, ``price_known``, ``pick_known``, ``calibrator_known``, ``review_known``,
``evidence_known``) read the decisions of every layer: a family's row has no pick, calibrator, review or evidence and drops out of the rules
that join them, and must still be written before the kick-off and with a price captured by then.

Every rule is ONE statement over the whole Bogotá day, so it has to stay linear in the number of packets (a night has some 11,000, each
citing up to two lists of ten matches): to compare what a packet cited with what it should have cited, build one list per packet
(``array_agg`` per packet, ``<> ALL`` against it, ``min`` of the kick-offs) and join it once; never probe a CTE or a sub-query once per
row, because a probe of a materialised CTE scans it again for every row. The first texts of ``h2h_known`` and ``tactics_known`` did
that, and the nightly run of 24 Oct 2026 (``intel.runs`` 1081) was still inside them after hours. ``tests/integration/test_leak_audit_scale.py`` runs both
over thousands of packets against a time limit and over small worlds against the frozen first texts
(``tests/integration/leakage_reference.py``), which must give the same verdict for every packet.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds
from fbi.core import match_state
from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.intel import factors, h2h, tactics

VERSION = "leak-audit-v7"

FINISHED = "ARRAY[" + ", ".join(f"'{code}'" for code in sorted(match_state.FINISHED)) + "]"
"""The stored states of a match played to a result, as a SQL array (constants of ``fbi.core.match_state``, not user input)."""

BASE = "SELECT d.* FROM intel.decisions d WHERE d.known_at >= %(start)s AND d.known_at < %(end)s"

PACKETS = ("SELECT m.id, m.fixture_id, m.as_of, m.content FROM ai.match_packets m "
           "WHERE m.built_at >= %(start)s AND m.built_at < %(end)s")

STATED = ", ".join(
    f"('{f.key}', ARRAY[{', '.join(repr(k) for k in (*f.block, 'status'))}], ARRAY[{', '.join(repr(k) for k in (*f.block, 'version'))}])"
    for f in factors.CATALOGUE if f.states)
"""The context factors whose block says its own ``status`` and ``version``, with the paths of both in the packet: (key, status path,
version path) rows of a SQL VALUES list, from the catalogue's constants."""


def _int(base: str, path: str, *, side: bool = False) -> str:
    """The SQL for an integer at ``path`` of the JSON ``base`` (``{a,b}`` is a path; ``{side,x}`` takes the side from the
    ``v.side`` of the query): NULL when it is absent or not a whole number, so a packet written by hand can fail a rule and never
    stop the audit."""
    keys = path.strip("{}").split(",")
    arr = "ARRAY[" + ", ".join("v.side" if (side and k == "side") else f"'{k}'" for k in keys) + "]"
    text = f"({base} #>> {arr})"
    return f"CASE WHEN {text} ~ '^-?[0-9]{{1,9}}$' THEN {text}::bigint END"


def _reread(row: str) -> str:
    """The SQL that says a row of ``core.fixture_events`` / ``core.fixture_lineups`` (the alias ``row``) that was written after the moment
    of the packet (``f.as_of``) is a re-read, not a later read: the match had its result by then (``r.settled_at``) and the payload the
    row came from is one the post-match job asked for (``core.detail_asks``). That job reads every finished match again 26 hours after its
    kick-off, which moves ``fetched_at`` of its line-ups and, when the provider corrected them, rewrites its events; the packets built
    between the final whistle and that read read the rows as they were."""
    return (f"(r.settled_at <= f.as_of AND EXISTS (SELECT 1 FROM core.detail_asks da "
            f"WHERE da.fixture_id = {row}.fixture_id AND da.payload_hash = {row}.payload_hash))")


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
        WITH d AS ({BASE} AND d.decision_version = %(core)s) SELECT count(*) FILTER (WHERE d.price_at IS NOT NULL) AS n,
               count(*) FILTER (WHERE d.price_at IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM market.market_consensus m WHERE m.fixture_id = d.fixture_id
                      AND m.market_key = d.market_key AND m.selection = d.selection AND m.line = d.line
                      AND m.as_of = d.price_at AND m.devig_method = 'shin' AND m.as_of <= d.known_at)) AS bad,
               (array_agg(d.id) FILTER (WHERE d.price_at IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM market.market_consensus m WHERE m.fixture_id = d.fixture_id
                      AND m.market_key = d.market_key AND m.selection = d.selection AND m.line = d.line
                      AND m.as_of = d.price_at AND m.devig_method = 'shin' AND m.as_of <= d.known_at)))[1:5]
                 AS examples FROM d""",
    "family_forecast_known": f"""
        WITH d AS ({BASE} AND d.decision_version = %(families)s), t AS (
            SELECT d.id, d.known_at, d.fixture_id, d.model_name, d.market_key, d.selection, d.line,
                   jsonb_path_query_first(d.filters, '$[*] ? (@.key == "model").data.forecast_id') #>> '{{}}' AS cited
              FROM d),
        c AS (
            SELECT t.id, t.known_at, t.fixture_id, t.model_name, t.market_key, t.selection, t.line,
                   CASE WHEN t.cited ~ '^[0-9]{{1,18}}$' THEN t.cited::bigint END AS forecast_id
              FROM t),
        k AS (
            SELECT c.id, (mf.id IS NOT NULL AND mf.known_at <= c.known_at AND mf.data_cutoff_ts <= c.known_at
                          AND NOT EXISTS (SELECT 1 FROM models.match_forecasts n
                                           WHERE n.fixture_id = mf.fixture_id AND n.version = mf.version AND n.model_name = mf.model_name
                                             AND n.market_key = mf.market_key AND n.line = mf.line AND n.selection = mf.selection
                                             AND n.known_at <= c.known_at AND (n.known_at, n.id) > (mf.known_at, mf.id))) AS ok
              FROM c LEFT JOIN models.match_forecasts mf
                     ON mf.id = c.forecast_id AND mf.fixture_id = c.fixture_id AND mf.model_name = c.model_name
                    AND mf.market_key = c.market_key AND mf.selection = c.selection AND mf.line = c.line)
        SELECT count(*) AS n, count(*) FILTER (WHERE NOT k.ok) AS bad,
               (array_agg(k.id ORDER BY k.id) FILTER (WHERE NOT k.ok))[1:5] AS examples FROM k""",
    "family_price_known": f"""
        WITH d AS ({BASE} AND d.decision_version = %(families)s AND d.odds IS NOT NULL), k AS (
            SELECT d.id, EXISTS (
                SELECT 1 FROM market.odds_quotes x JOIN market.market_definitions md ON md.id = x.definition_id
                 WHERE x.fixture_id = d.fixture_id AND x.bookmaker_id = d.bookmaker_id AND md.market_key = d.market_key
                   AND md.scope = 'prematch' AND x.selection = d.selection AND x.line = d.line
                   AND x.odds_decimal = d.odds AND x.captured_at <= d.known_at) AS ok
              FROM d)
        SELECT count(*) AS n, count(*) FILTER (WHERE NOT k.ok) AS bad,
               (array_agg(k.id ORDER BY k.id) FILTER (WHERE NOT k.ok))[1:5] AS examples FROM k""",
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
    "absences_known": f"""
        WITH p AS ({PACKETS}), a AS (
            SELECT p.id AS packet_id, p.fixture_id, p.as_of, (e.x ->> 'player_id')::bigint AS player_id, e.x ->> 'type' AS kind
              FROM p CROSS JOIN (VALUES ('home'), ('away')) AS v(side)
                   CROSS JOIN LATERAL jsonb_array_elements(
                       CASE WHEN jsonb_typeof(p.content #> ARRAY['absences', v.side, 'players']) = 'array'
                            THEN p.content #> ARRAY['absences', v.side, 'players'] ELSE '[]'::jsonb END) AS e(x)
             WHERE jsonb_typeof(e.x) = 'object' AND (e.x ->> 'player_id') ~ '^[0-9]{{1,15}}$'),
        c AS (
            SELECT a.packet_id,
                   NOT EXISTS (SELECT 1 FROM core.player_availability_obs o
                                WHERE o.fixture_id = a.fixture_id AND o.source = 'api-football'
                                  AND o.provider_player_id = a.player_id AND o.status = 'LISTED' AND o.observed_at <= a.as_of
                                  AND o.absence_type IS NOT DISTINCT FROM a.kind
                                  AND NOT EXISTS (SELECT 1 FROM core.player_availability_obs n
                                                   WHERE n.fixture_id = o.fixture_id AND n.source = o.source
                                                     AND n.provider_player_id = o.provider_player_id
                                                     AND n.observed_at > o.observed_at AND n.observed_at <= a.as_of)) AS bad
              FROM a)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
    "forecast_known": f"""
        WITH p AS ({PACKETS}), m AS (
            SELECT p.id AS packet_id, p.fixture_id, p.as_of, p.content #>> '{{forecast,version}}' AS version,
                   x ->> 'market' AS market, (x ->> 'line')::numeric AS line, (x ->> 'known_at')::timestamptz AS known_at,
                   x ->> 'model' AS model
              FROM p CROSS JOIN LATERAL jsonb_array_elements(
                     CASE WHEN jsonb_typeof(p.content #> '{{forecast,markets}}') = 'array'
                          THEN p.content #> '{{forecast,markets}}' ELSE '[]'::jsonb END) AS x
             WHERE jsonb_typeof(x) = 'object'),
        c AS (
            SELECT m.packet_id,
                   (m.known_at IS NULL OR m.known_at > m.as_of
                    OR NOT EXISTS (SELECT 1 FROM models.match_forecasts f
                                    WHERE f.fixture_id = m.fixture_id AND f.version = m.version AND f.market_key = m.market
                                      AND f.line = m.line AND f.known_at = m.known_at AND f.model_name = m.model)
                    OR EXISTS (SELECT 1 FROM models.match_forecasts n
                                WHERE n.fixture_id = m.fixture_id AND n.version = m.version AND n.market_key = m.market
                                  AND n.line = m.line AND n.known_at > m.known_at AND n.known_at <= m.as_of)) AS bad
              FROM m)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
    "calendar_known": f"""
        WITH p AS ({PACKETS}), s AS (
            SELECT p.id AS packet_id, p.as_of, v.side,
                   (SELECT t.provider_team_id FROM core.teams t
                     WHERE t.id = CASE WHEN (p.content #>> ARRAY['fixture', v.side, 'id']) ~ '^[0-9]{{1,15}}$'
                                       THEN (p.content #>> ARRAY['fixture', v.side, 'id'])::bigint END) AS tp,
                   (p.content #>> ARRAY['schedule', 'calendar', v.side, 'fetched_at'])::timestamptz AS fetched_at,
                   COALESCE((p.content #>> ARRAY['schedule', 'calendar', v.side, 'complete'])::boolean, false) AS whole
              FROM p CROSS JOIN (VALUES ('home'), ('away')) AS v(side)
             WHERE jsonb_typeof(p.content #> ARRAY['schedule', 'calendar', v.side]) = 'object'),
        m AS (
            SELECT p.id AS packet_id, p.as_of, k.kind, e.x AS entry,
                   CASE WHEN (e.x ->> 'provider_fixture_id') ~ '^[0-9]{{1,15}}$' THEN (e.x ->> 'provider_fixture_id')::bigint END AS fx,
                   (e.x ->> 'kickoff_at')::timestamptz AS kickoff
              FROM p CROSS JOIN (VALUES ('home'), ('away')) AS v(side) CROSS JOIN (VALUES ('recent'), ('upcoming')) AS k(kind)
                   CROSS JOIN LATERAL jsonb_array_elements(
                       CASE WHEN jsonb_typeof(p.content #> ARRAY['schedule', v.side, k.kind]) = 'array'
                            THEN p.content #> ARRAY['schedule', v.side, k.kind] ELSE '[]'::jsonb END) AS e(x)
             WHERE jsonb_typeof(e.x) = 'object'),
        c AS (
            SELECT s.packet_id,
                   CASE WHEN s.tp IS NULL THEN true
                        WHEN s.fetched_at IS NULL THEN
                            s.whole OR EXISTS (SELECT 1 FROM core.calendar_fetches f
                                                WHERE f.provider_team_id = s.tp AND f.fetched_at <= s.as_of - interval '1 minute')
                        ELSE
                            s.fetched_at > s.as_of
                            OR NOT EXISTS (SELECT 1 FROM core.calendar_fetches f
                                            WHERE f.provider_team_id = s.tp AND f.fetched_at = s.fetched_at)
                            OR EXISTS (SELECT 1 FROM core.calendar_fetches n
                                        WHERE n.provider_team_id = s.tp AND n.fetched_at > s.fetched_at
                                          AND n.fetched_at <= s.as_of - interval '1 minute')
                            OR (s.whole AND s.as_of - s.fetched_at > interval '96 hours')
                   END AS bad
              FROM s
            UNION ALL
            SELECT m.packet_id,
                   m.fx IS NULL OR m.kickoff IS NULL OR NOT CASE
                       WHEN (m.entry ->> 'followed') = 'true' THEN
                           EXISTS (SELECT 1 FROM core.fixtures f
                                    WHERE f.provider_fixture_id = m.fx
                                      AND ((m.kind = 'recent' AND m.kickoff < m.as_of)
                                           OR (m.kind = 'upcoming' AND (f.created_at <= m.as_of OR m.kickoff <= m.as_of))))
                       ELSE
                           EXISTS (SELECT 1 FROM core.calendar_matches x
                                    WHERE x.provider_fixture_id = m.fx AND x.kickoff_at = m.kickoff
                                      AND ((m.kind = 'recent' AND x.kickoff_at < m.as_of)
                                           OR (m.kind = 'upcoming' AND (x.observed_at <= m.as_of OR x.kickoff_at <= m.as_of))))
                   END
              FROM m)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
    "h2h_known": f"""
        WITH p AS ({PACKETS}), b AS (
            SELECT p.id AS packet_id, p.as_of, p.content -> 'h2h' AS blk,
                   (p.content #>> '{{fixture,kickoff_at}}')::timestamptz AS kickoff,
                   CASE WHEN (p.content #>> '{{fixture,home,id}}') ~ '^[0-9]{{1,15}}$' THEN (p.content #>> '{{fixture,home,id}}')::bigint END AS home_id,
                   CASE WHEN (p.content #>> '{{fixture,away,id}}') ~ '^[0-9]{{1,15}}$' THEN (p.content #>> '{{fixture,away,id}}')::bigint END AS away_id
              FROM p WHERE jsonb_typeof(p.content #> '{{h2h,meetings}}') = 'array'),
        m AS (
            SELECT b.packet_id, b.as_of, b.kickoff, b.home_id, b.away_id,
                   CASE WHEN (x ->> 'fixture_id') ~ '^[0-9]{{1,15}}$' THEN (x ->> 'fixture_id')::bigint END AS leg,
                   CASE WHEN (x ->> 'days_ago') ~ '^[0-9]{{1,6}}$' THEN (x ->> 'days_ago')::int END AS days_ago,
                   (jsonb_typeof(x #> '{{coach_changed,home}}') = 'boolean'
                    OR jsonb_typeof(x #> '{{coach_changed,away}}') = 'boolean') AS coach_claim
              FROM b CROSS JOIN LATERAL jsonb_array_elements(b.blk -> 'meetings') AS x WHERE jsonb_typeof(x) = 'object'),
        ml AS (
            SELECT m.packet_id, array_agg(m.leg) FILTER (WHERE m.leg IS NOT NULL) AS legs, min(g2.kickoff_at) AS first_kick
              FROM m LEFT JOIN core.fixtures g2 ON g2.id = m.leg GROUP BY m.packet_id),
        c AS (
            SELECT m.packet_id,
                   (g.id IS NULL OR g.kickoff_at >= m.kickoff OR r.settled_at IS NULL OR r.settled_at > m.as_of
                    OR NOT (g.status_short = ANY({FINISHED}))
                    OR NOT ((g.home_team_id = m.home_id AND g.away_team_id = m.away_id)
                            OR (g.home_team_id = m.away_id AND g.away_team_id = m.home_id))
                    OR m.days_ago IS DISTINCT FROM floor(extract(epoch FROM (m.kickoff - g.kickoff_at)) / 86400)::int
                    OR (m.coach_claim AND NOT EXISTS (SELECT 1 FROM core.fixture_lineups l
                                                       WHERE l.fixture_id = m.leg AND l.fetched_at <= m.as_of))) AS bad
              FROM m LEFT JOIN core.fixtures g ON g.id = m.leg LEFT JOIN core.fixture_results r ON r.fixture_id = m.leg
            UNION ALL
            SELECT b.packet_id,
                   EXISTS (SELECT 1 FROM core.fixtures g JOIN core.fixture_results r ON r.fixture_id = g.id
                            WHERE ((g.home_team_id = b.home_id AND g.away_team_id = b.away_id)
                                   OR (g.home_team_id = b.away_id AND g.away_team_id = b.home_id))
                              AND g.kickoff_at < b.kickoff AND r.settled_at <= b.as_of AND g.status_short = ANY({FINISHED})
                              AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
                              AND g.id <> ALL (COALESCE(ml.legs, ARRAY[]::bigint[]))
                              AND (jsonb_array_length(b.blk -> 'meetings') < {h2h.N} OR g.kickoff_at > ml.first_kick)) AS bad
              FROM b LEFT JOIN ml ON ml.packet_id = b.packet_id)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
    "scenarios_known": f"""
        WITH p AS ({PACKETS}), b AS (
            SELECT p.id AS packet_id, p.as_of, (p.content #>> '{{fixture,kickoff_at}}')::timestamptz AS kickoff,
                   (p.content #>> '{{scenarios,table,snapshot_at}}')::timestamptz AS snap,
                   p.content #>> '{{scenarios,table,group}}' AS grp, p.content #> '{{scenarios,table}}' AS tbl
              FROM p WHERE jsonb_typeof(p.content #> '{{scenarios,table}}') = 'object'),
        t AS (
            SELECT b.packet_id, (b.snap IS NULL OR b.snap > b.as_of OR b.snap > b.kickoff) AS bad FROM b
            UNION ALL
            SELECT b.packet_id,
                   NOT EXISTS (SELECT 1 FROM core.standings st
                                WHERE st.snapshot_at = b.snap AND st.group_key = b.grp
                                  AND st.team_id = {_int("b.tbl", "{side,team_id}", side=True)}
                                  AND st.rank = {_int("b.tbl", "{side,rank_now}", side=True)}
                                  AND st.points = {_int("b.tbl", "{side,points_now}", side=True)}
                                  AND st.played = {_int("b.tbl", "{side,played}", side=True)}) AS bad
              FROM b CROSS JOIN (VALUES ('home'), ('away')) AS v(side) WHERE jsonb_typeof(b.tbl -> v.side) = 'object'),
        l AS (
            SELECT p.id AS packet_id, {_int("p.content", "{scenarios,tie,lead_home_side}")} AS lead,
                   {_int("p.content", "{scenarios,tie,aggregate_before,home_side}")} AS ah,
                   {_int("p.content", "{scenarios,tie,aggregate_before,away_side}")} AS aa,
                   {_int("p.content", "{phase,tie,aggregate_before,home_side}")} AS ph,
                   {_int("p.content", "{phase,tie,aggregate_before,away_side}")} AS pa,
                   {_int("p.content", "{scenarios,tie,home_side,ahead_if_margin_at_least}")} AS h_ahead,
                   {_int("p.content", "{scenarios,tie,home_side,level_if_margin}")} AS h_level,
                   {_int("p.content", "{scenarios,tie,home_side,behind_if_margin_at_most}")} AS h_behind,
                   {_int("p.content", "{scenarios,tie,away_side,ahead_if_margin_at_least}")} AS a_ahead,
                   {_int("p.content", "{scenarios,tie,away_side,level_if_margin}")} AS a_level,
                   {_int("p.content", "{scenarios,tie,away_side,behind_if_margin_at_most}")} AS a_behind
              FROM p WHERE p.content #>> '{{scenarios,tie,kind}}' = 'second_leg'
                       AND jsonb_typeof(p.content #> '{{scenarios,tie,aggregate_before}}') = 'object'),
        k AS (
            SELECT l.packet_id,
                   (l.ah IS DISTINCT FROM l.ph OR l.aa IS DISTINCT FROM l.pa OR l.lead IS DISTINCT FROM l.ah - l.aa
                    OR l.h_ahead IS DISTINCT FROM 1 - l.lead OR l.h_level IS DISTINCT FROM -l.lead
                    OR l.h_behind IS DISTINCT FROM -l.lead - 1 OR l.a_ahead IS DISTINCT FROM l.lead + 1
                    OR l.a_level IS DISTINCT FROM l.lead OR l.a_behind IS DISTINCT FROM l.lead - 1) AS bad
              FROM l)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples
          FROM (SELECT * FROM t UNION ALL SELECT * FROM k) c""",
    "tactics_known": f"""
        WITH p AS ({PACKETS}), b AS (
            SELECT p.id AS packet_id, p.as_of, (p.content #>> '{{fixture,kickoff_at}}')::timestamptz AS kickoff, v.side,
                   CASE WHEN (p.content #>> ARRAY['fixture', v.side, 'id']) ~ '^[0-9]{{1,15}}$'
                        THEN (p.content #>> ARRAY['fixture', v.side, 'id'])::bigint END AS team,
                   p.content #> ARRAY['dossier', 'tactics', v.side] AS blk
              FROM p CROSS JOIN (VALUES ('home'), ('away')) AS v(side)
             WHERE jsonb_typeof(p.content #> ARRAY['dossier', 'tactics', v.side, 'fixtures']) = 'array'),
        f AS (
            SELECT b.packet_id, b.side, b.team, b.kickoff, b.as_of, b.blk,
                   CASE WHEN (x #>> '{{}}') ~ '^[0-9]{{1,15}}$' THEN (x #>> '{{}}')::bigint END AS fid
              FROM b CROSS JOIN LATERAL jsonb_array_elements(b.blk -> 'fixtures') AS x),
        e AS (
            SELECT b.packet_id, b.side, b.team,
                   CASE WHEN (x #>> '{{}}') ~ '^[0-9]{{1,15}}$' THEN (x #>> '{{}}')::bigint END AS fid
              FROM b CROSS JOIN LATERAL jsonb_array_elements(
                       CASE WHEN jsonb_typeof(b.blk #> '{{read,events}}') = 'array' THEN b.blk #> '{{read,events}}'
                            ELSE '[]'::jsonb END) AS x),
        s AS (
            SELECT e.packet_id, e.side,
                   sum(CASE WHEN g.home_team_id = e.team THEN r.reg_goals_home ELSE r.reg_goals_away END) AS gf,
                   sum(CASE WHEN g.home_team_id = e.team THEN r.reg_goals_away ELSE r.reg_goals_home END) AS ga
              FROM e JOIN core.fixtures g ON g.id = e.fid JOIN core.fixture_results r ON r.fixture_id = g.id GROUP BY 1, 2),
        fl AS (
            SELECT f.packet_id, f.side, array_agg(f.fid) FILTER (WHERE f.fid IS NOT NULL) AS fids, min(g2.kickoff_at) AS first_kick
              FROM f LEFT JOIN core.fixtures g2 ON g2.id = f.fid GROUP BY f.packet_id, f.side),
        ht AS (
            SELECT f.packet_id, f.side, count(*) AS n
              FROM f JOIN core.fixture_results r ON r.fixture_id = f.fid
             WHERE r.ht_goals_home IS NOT NULL AND r.ht_goals_away IS NOT NULL GROUP BY f.packet_id, f.side),
        c AS (
            SELECT f.packet_id,
                   (g.id IS NULL OR f.team IS NULL OR NOT (g.home_team_id = f.team OR g.away_team_id = f.team)
                    OR g.kickoff_at >= f.kickoff OR g.kickoff_at < f.kickoff - interval '{tactics.WINDOW.days} days'
                    OR r.settled_at IS NULL OR r.settled_at > f.as_of
                    OR (COALESCE((f.blk #> '{{read,events}}') @> to_jsonb(f.fid), false)
                        AND NOT EXISTS (SELECT 1 FROM core.fixture_events ev
                                         WHERE ev.fixture_id = f.fid AND (ev.fetched_at <= f.as_of OR {_reread("ev")})))
                    OR (COALESCE((f.blk #> '{{read,sheets}}') @> to_jsonb(f.fid), false)
                        AND NOT EXISTS (SELECT 1 FROM core.fixture_lineups l
                                         WHERE l.fixture_id = f.fid AND (l.fetched_at <= f.as_of OR {_reread("l")})
                                           AND l.team_side = CASE WHEN g.home_team_id = f.team THEN 'home' ELSE 'away' END))) AS bad
              FROM f LEFT JOIN core.fixtures g ON g.id = f.fid LEFT JOIN core.fixture_results r ON r.fixture_id = f.fid
            UNION ALL
            SELECT b.packet_id,
                   (b.team IS NULL OR jsonb_array_length(b.blk -> 'fixtures') > {tactics.N}
                    OR {_int("b.blk", "{n}")} IS DISTINCT FROM jsonb_array_length(b.blk -> 'fixtures')
                    OR NOT COALESCE((b.blk -> 'fixtures') @> COALESCE(b.blk #> '{{read,events}}', '[]'::jsonb)
                                    AND (b.blk -> 'fixtures') @> COALESCE(b.blk #> '{{read,sheets}}', '[]'::jsonb), false)
                    OR COALESCE({_int("b.blk", "{goals,total_for}")}, 0) IS DISTINCT FROM COALESCE(s.gf, 0)
                    OR COALESCE({_int("b.blk", "{goals,total_against}")}, 0) IS DISTINCT FROM COALESCE(s.ga, 0)
                    OR COALESCE({_int("b.blk", "{with_the_score,half_time,n}")}, 0) IS DISTINCT FROM COALESCE(ht.n, 0)) AS bad
              FROM b LEFT JOIN s ON s.packet_id = b.packet_id AND s.side = b.side
                     LEFT JOIN ht ON ht.packet_id = b.packet_id AND ht.side = b.side
            UNION ALL
            SELECT b.packet_id,
                   EXISTS (SELECT 1 FROM core.fixtures g JOIN core.fixture_results r ON r.fixture_id = g.id
                            WHERE (g.home_team_id = b.team OR g.away_team_id = b.team) AND g.kickoff_at < b.kickoff
                              AND g.kickoff_at >= b.kickoff - interval '{tactics.WINDOW.days} days' AND r.settled_at <= b.as_of
                              AND g.id <> ALL (COALESCE(fl.fids, ARRAY[]::bigint[]))
                              AND (jsonb_array_length(b.blk -> 'fixtures') < {tactics.N} OR g.kickoff_at > fl.first_kick)) AS bad
              FROM b LEFT JOIN fl ON fl.packet_id = b.packet_id AND fl.side = b.side)
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
    "factors_known": f"""
        WITH p AS ({PACKETS}), e AS (
            SELECT p.id AS packet_id, p.as_of, x.key, x.val
              FROM p CROSS JOIN LATERAL jsonb_each(p.content -> 'factors') AS x(key, val)
             WHERE jsonb_typeof(p.content -> 'factors') = 'object' AND jsonb_typeof(x.val) = 'object'
               AND (p.content #> '{{factors,error}}') IS NULL),
        c AS (
            SELECT e.packet_id,
                   ((e.val ->> 'status') IS DISTINCT FROM COALESCE(r.status, 'DESCRIPTIVE')
                    OR {_int("e.val", "{decision,id}")} IS DISTINCT FROM r.id
                    OR (e.val #>> '{{decision,experiment}}') IS DISTINCT FROM (r.evidence ->> 'experiment')) AS bad
              FROM e LEFT JOIN LATERAL (
                       SELECT d.id, d.status, d.evidence FROM intel.context_factors d
                        WHERE d.factor = e.key AND d.version = (e.val ->> 'version') AND d.decided_at <= e.as_of
                        ORDER BY d.id DESC LIMIT 1) r ON true
            UNION ALL
            SELECT p.id, ((p.content #>> k.status_path) IS DISTINCT FROM (p.content #>> ARRAY['factors', k.key, 'status'])
                          OR (p.content #>> k.version_path) IS DISTINCT FROM (p.content #>> ARRAY['factors', k.key, 'version'])) AS bad
              FROM p CROSS JOIN (VALUES {STATED}) AS k(key, status_path, version_path)
             WHERE (p.content #>> k.status_path) IS NOT NULL AND jsonb_typeof(p.content -> 'factors') = 'object')
        SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad,
               (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] AS examples FROM c""",
}


def audit_day(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> dict[str, dict[str, Any]]:
    start, end = day_bounds(day)
    out: dict[str, dict[str, Any]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for rule, sql in RULES.items():
            cur.execute(sql, {"start": start, "end": end, "core": DECISION_CORE, "families": DECISION_FAMILIES})
            r = cur.fetchone() or {}
            n, bad = int(r.get("n") or 0), int(r.get("bad") or 0)
            examples = [int(x) for x in (r.get("examples") or [])]
            out[rule] = {"checked": n, "violations": bad, "examples": examples}
            cur.execute("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations, "
                        "examples) VALUES (%s,%s,%s,%s,%s,%s,%s)", (day, at, VERSION, rule, n, bad, Jsonb(examples)))
    return out
