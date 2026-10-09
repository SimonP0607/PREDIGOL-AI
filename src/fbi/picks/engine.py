"""From a captured price and a forecast made before it, to a candidate - and maybe a shadow pick.

For every consensus the capturer computed (one per captured payload), every
MODEL with a real-time forecast made BEFORE that capture is compared with the
best price in that capture - through its newest forecast, whichever version
made it. A model is re-versioned whenever the code version changes (a docs-only
commit included); judging every version would record the same bet once per
restart, which is what the first real capture showed on 25 Sep 2026 (three
identical shadow picks from three versions of one Elo model):

    candidate  every (forecast, selection, capture) evaluated, kept whatever the decision
    shadow     a candidate the versioned rule selected
    qualified  a shadow pick whose model version beat the market in its own backtest
    published  disabled by the schema
    settled    once the result is in, on the basis the market settles on

Everything a pick claims is traceable: the prediction row (and so the model
version, its input hash and data cut-off), the bookmaker, price and payload of
the odds, the consensus method and instant, the rule version and the code.
Nothing here spends a provider request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.domain.market_probability import DevigMethod, FairProbability
from fbi.domain.odds import DecimalOdds
from fbi.domain.probability import Probability
from fbi.picks import settlement
from fbi.picks.rules import (
    CURRENT_RULE,
    DecisionRule,
    VersionEvidence,
    decide,
    qualify,
    reason_kind,
)
from fbi.picks.value import assess

CONSENSUS_METHOD = DevigMethod.SHIN
STAKE = Decimal("1")
STAKE_POLICY = "flat_1u"
OU_BASELINE = "pinnacle/closing/shin"


@dataclass
class PickReport:
    instants: int = 0
    candidates: int = 0
    already_evaluated: int = 0
    selected: int = 0
    rejected: int = 0
    qualified: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


def _q6(x: Decimal | float) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _conditional(p_win: float, settled: float) -> Probability:
    """P(win) turned into P(win | the bet is settled).

    The market's de-vigged probability is conditional - two selections summing
    to 1 cannot express a push - so this is what the comparison has to be made
    on. A line that cannot push leaves the number untouched.
    """
    if settled <= 0:
        return Probability(0.0)
    return Probability(min(1.0, p_win / settled))


def _instants(conn: psycopg.Connection, since: datetime | None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT m.fixture_id, m.as_of
            FROM market.market_consensus m JOIN core.fixtures f ON f.id = m.fixture_id
            WHERE m.devig_method = %s AND m.as_of < f.kickoff_at AND (%s::timestamptz IS NULL OR m.as_of >= %s)
            ORDER BY m.as_of, m.fixture_id
            """,
            (CONSENSUS_METHOD.value, since, since),
        )
        return list(cur.fetchall())


def _consensus(conn: psycopg.Connection, fixture_id: int, as_of: datetime) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT market_key, selection, line, p_fair, overround, best_odds, best_bookmaker_id, n_bookmakers "
            "FROM market.market_consensus WHERE fixture_id = %s AND as_of = %s AND devig_method = %s",
            (fixture_id, as_of, CONSENSUS_METHOD.value),
        )
        return list(cur.fetchall())


def _forecasts(conn: psycopg.Connection, fixture_id: int, as_of: datetime) -> list[dict[str, Any]]:
    """The newest real-time forecast of every MODEL made before this capture - one version per
    model (the one that made that forecast; the higher id on a tie), never one per version."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH made AS (
                SELECT DISTINCT v.model_id, p.model_version_id, p.data_cutoff_ts
                FROM models.predictions p JOIN models.model_versions v ON v.id = p.model_version_id
                WHERE p.fixture_id = %s AND p.backtest_session_id IS NULL AND p.data_cutoff_ts <= %s
            ), newest AS (
                SELECT DISTINCT ON (model_id) model_id, model_version_id, data_cutoff_ts FROM made
                ORDER BY model_id, data_cutoff_ts DESC, model_version_id DESC
            )
            SELECT p.id, p.model_version_id, p.market_key, p.selection, p.line, p.p_calibrated, p.p_lo, p.p_hi,
                   p.feature_set_hash, p.data_cutoff_ts, p.calibrator_id, p.p_push
            FROM models.predictions p JOIN newest n ON n.model_version_id = p.model_version_id
                 AND n.data_cutoff_ts = p.data_cutoff_ts
            WHERE p.fixture_id = %s AND p.backtest_session_id IS NULL
            """,
            (fixture_id, as_of, fixture_id),
        )
        return list(cur.fetchall())


def _evidence(conn: psycopg.Connection, version_id: int, market_key: str) -> VersionEvidence:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT r.id AS run_id, s.primary_baseline FROM analytics.backtest_runs r
            LEFT JOIN analytics.backtest_sessions s ON s.id = r.session_id
            WHERE r.model_version_id = %s AND r.status = 'completed'
            ORDER BY r.finished_at DESC NULLS LAST, r.id DESC LIMIT 1
            """,
            (version_id,),
        )
        run = cur.fetchone()
        if run is None:
            return VersionEvidence(None, market_key, None, None, None)
        baseline = run["primary_baseline"] if market_key == "1X2" else OU_BASELINE
        cur.execute(
            "SELECT verdict, n_common FROM analytics.backtest_comparisons WHERE backtest_run_id = %s "
            "AND market_key = %s AND baseline_key = %s",
            (run["run_id"], market_key, baseline),
        )
        c = cur.fetchone()
    return VersionEvidence(int(run["run_id"]), market_key, None if c is None else str(c["verdict"]),
                           None if c is None else int(c["n_common"]), baseline)


PriceKey = tuple[int, str, str, Decimal]
"""(bookmaker, market, selection, line): one price series of a fixture."""
CandidateKey = tuple[int, str, str, Decimal, datetime]
"""(prediction, market, selection, line, price captured at): what makes a candidate one (its unique index, with the
decision rule's version)."""


def _price_key(row: dict[str, Any]) -> PriceKey:
    return int(row["best_bookmaker_id"]), str(row["market_key"]), str(row["selection"]), Decimal(row["line"])


def _odds_payloads(conn: psycopg.Connection, fixture_id: int, rows: list[dict[str, Any]],
                   as_of: datetime) -> dict[PriceKey, tuple[str, datetime]]:
    """The newest snapshot at the instant of each consensus row's best price: payload and capture time.

    One round trip for the whole instant: the same lookup per price as before, done inside the database. One query
    per price made every pass about 300,000 round trips; on the server a round trip is about a millisecond (9 Oct
    2026), and a pass took ten minutes.
    """
    wanted = sorted({_price_key(r) for r in rows})
    if not wanted:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT w.bookmaker_id, w.market_key, w.selection, w.line, s.payload_hash, s.captured_at
            FROM unnest(%s::int[], %s::text[], %s::text[], %s::numeric[]) AS w(bookmaker_id, market_key, selection, line)
            CROSS JOIN LATERAL (
                SELECT o.payload_hash, o.captured_at FROM market.odds_snapshots o
                WHERE o.fixture_id = %s AND o.bookmaker_id = w.bookmaker_id AND o.market_key = w.market_key
                  AND o.selection = w.selection AND o.line = w.line AND o.captured_at <= %s
                ORDER BY o.captured_at DESC LIMIT 1
            ) s
            """,
            ([w[0] for w in wanted], [w[1] for w in wanted], [w[2] for w in wanted], [w[3] for w in wanted],
             fixture_id, as_of),
        )
        return {(int(b), str(m), str(sel), Decimal(line)): (str(h), at) for b, m, sel, line, h, at in cur.fetchall()}


def _evaluated(conn: psycopg.Connection, prediction_ids: list[int], rule_version: str) -> set[CandidateKey]:
    """The candidates these forecasts already have under this rule: their insert would do nothing."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT prediction_id, market_key, selection, line, odds_captured_at FROM picks.pick_candidates "
            "WHERE prediction_id = ANY(%s) AND decision_rule_version = %s",
            (prediction_ids, rule_version),
        )
        return {(int(p), str(m), str(sel), Decimal(line), at) for p, m, sel, line, at in cur.fetchall()}


def evaluate_captures(conn: psycopg.Connection, *, run_id: int, code_version: str,
                      since: datetime | None = None, rule: DecisionRule = CURRENT_RULE) -> PickReport:
    report = PickReport()
    for inst in _instants(conn, since):
        fixture_id, as_of = int(inst["fixture_id"]), inst["as_of"]
        report.instants += 1
        consensus = {(r["market_key"], r["selection"], Decimal(r["line"])): r for r in _consensus(conn, fixture_id, as_of)}
        matched = [(f, c) for f in _forecasts(conn, fixture_id, as_of)
                   if (c := consensus.get((f["market_key"], f["selection"], Decimal(f["line"])))) is not None]
        if not matched:
            continue  # no price for any forecast selection in this capture
        payloads = _odds_payloads(conn, fixture_id, [c for _, c in matched], as_of)
        done = _evaluated(conn, sorted({int(f["id"]) for f, _ in matched}), rule.version)
        for f, c in matched:
            payload = payloads.get(_price_key(c))
            if payload is None or payload[1] < f["data_cutoff_ts"]:
                continue  # the forecast must precede the very price it is compared with
            candidate: CandidateKey = (int(f["id"]), str(f["market_key"]), str(f["selection"]), Decimal(f["line"]),
                                       payload[1])
            if candidate in done:
                # Evaluated by an earlier pass (or an earlier instant with the same price): the insert below would
                # do nothing, so it is not sent. Every pass used to send it for every candidate ever made.
                report.already_evaluated += 1
                continue
            done.add(candidate)
            odds = DecimalOdds(Decimal(c["best_odds"]))
            fair = FairProbability(Probability(float(c["p_fair"])), CONSENSUS_METHOD, float(c["overround"]))

            # A push is not a loss and not a win, and the two sides of the
            # comparison count it differently:
            #
            #   market.market_consensus.p_fair comes from de-vigging two or three
            #   selections to sum to 1, so on a line that can push it is
            #   P(win | the bet is settled).
            #
            #   models.predictions.p_calibrated is P(win) outright, with P(push)
            #   in its own column.
            #
            # Comparing them directly would understate the model on every
            # pushable line by exactly the push probability - 66% of the Asian
            # Handicap series and 51% of the Over/Under series - and it would
            # look like a model that disagrees with the market, not like an
            # error. So the EDGE is computed on the conditional probability,
            # while the EXPECTED VALUE uses P(win) and P(push) as they are,
            # because what is staked is staked whether the bet pushes or not.
            push = Probability(float(f["p_push"] or 0))
            settled = 1.0 - push.value
            p_conditional = _conditional(float(f["p_calibrated"]), settled)
            p_lo_conditional = (
                _conditional(float(f["p_lo"]), settled)
                if f["p_lo"] is not None else None
            )
            # The pick stores its interval on the SAME footing as its probability (conditional
            # on the bet settling): a whole line's unconditional upper bound sits below its
            # conditional point, which the table's interval check rightly refuses - and did,
            # for every whole-line pick, from the day quoted lines got intervals (4 Oct 2026).
            p_hi_conditional = (
                _conditional(float(f["p_hi"]), settled)
                if f["p_hi"] is not None else None
            )
            a = assess(p_conditional, odds, fair, p_lo_conditional, push=push)
            reason = decide(a, f["market_key"], rule)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO picks.pick_candidates (run_id, fixture_id, prediction_id, market_key, selection, line,
                        bookmaker_id, market_odds, p_calibrated, p_market_fair, edge, price_edge, ev, ev_adjusted,
                        decision, rejection_reason, decision_rule_version, odds_captured_at, odds_payload_hash,
                        consensus_method, consensus_as_of, data_cutoff_ts, p_push)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (prediction_id, market_key, selection, line, odds_captured_at, decision_rule_version)
                    DO NOTHING RETURNING id
                    """,
                    (run_id, fixture_id, f["id"], f["market_key"], f["selection"], f["line"],
                     c["best_bookmaker_id"], odds.value, _q6(p_conditional.value),
                     _q6(fair.probability.value),
                     a.probability_edge.value if a.probability_edge else None,
                     a.price_edge.value if a.price_edge else None, a.expected_value.per_unit,
                     a.ev_at_lower_bound.per_unit if a.ev_at_lower_bound else None,
                     "rejected" if reason else "selected", reason, rule.version, payload[1], payload[0],
                     CONSENSUS_METHOD.value, as_of, f["data_cutoff_ts"], _q6(push.value)),
                )
                row = cur.fetchone()
            if row is None:
                report.already_evaluated += 1
                continue
            report.candidates += 1
            if reason is not None:
                report.rejected += 1
                bucket = reason_kind(reason)
                report.reasons[bucket] = report.reasons.get(bucket, 0) + 1
                continue
            report.selected += 1
            evidence = _evidence(conn, int(f["model_version_id"]), f["market_key"])
            q = qualify(evidence)
            status = "qualified" if q.qualified else "shadow"
            report.qualified += int(q.qualified)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO picks.picks (candidate_id, fixture_id, market_key, selection, line, model_version_id,
                        calibrator_id, feature_set_hash, data_cutoff_ts, decision_rule_version, code_version,
                        bookmaker_id, market_odds, odds_captured_at, p_model, p_calibrated, p_calibrated_lo,
                        p_calibrated_hi, p_market_fair, fair_odds, edge, price_edge, ev, ev_adjusted, kelly_fraction,
                        stake_units, selection_reason, mode, prediction_id, odds_payload_hash, consensus_method,
                        consensus_as_of, stake_policy, qualification, status, p_push)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'shadow',
                            %s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (row[0], fixture_id, f["market_key"], f["selection"], f["line"], f["model_version_id"],
                     f["calibrator_id"], f["feature_set_hash"], f["data_cutoff_ts"], rule.version, code_version,
                     c["best_bookmaker_id"], odds.value, payload[1], _q6(p_conditional.value),
                     _q6(p_conditional.value),
                     None if p_lo_conditional is None else _q6(p_lo_conditional.value),
                     None if p_hi_conditional is None else _q6(p_hi_conditional.value),
                     _q6(fair.probability.value), a.model_fair_odds,
                     a.probability_edge.value if a.probability_edge else None,
                     a.price_edge.value if a.price_edge else None, a.expected_value.per_unit,
                     a.ev_at_lower_bound.per_unit if a.ev_at_lower_bound else None, a.kelly_fraction, STAKE,
                     json.dumps({"rule": rule.as_dict(), "consensus_bookmakers": int(c["n_bookmakers"])}),
                     f["id"], payload[0], CONSENSUS_METHOD.value, as_of, STAKE_POLICY,
                     json.dumps(q.as_dict(evidence)), status, _q6(push.value)),
                )
                pick_row = cur.fetchone()
                assert pick_row is not None
                pick_id = int(pick_row[0])
                cur.execute("INSERT INTO picks.pick_events (pick_id, from_status, to_status, reason, run_id) "
                            "VALUES (%s, NULL, 'shadow', %s, %s)", (pick_id, f"selected by {rule.version}", run_id))
                if q.qualified:
                    cur.execute("INSERT INTO picks.pick_events (pick_id, from_status, to_status, reason, run_id) "
                                "VALUES (%s, 'shadow', 'qualified', %s, %s)",
                                (pick_id, "the model version beat the market in its backtest", run_id))
                cur.execute("INSERT INTO picks.pick_results (pick_id, result_status) VALUES (%s, 'pending')",
                            (pick_id,))
    return report


@dataclass
class SettlementReport:
    open_picks: int = 0
    settled: int = 0
    still_pending: int = 0
    needs_review: int = 0
    already_settled: int = 0
    """Settled by another pass between this pass's read and its write (the fast path and the pipeline race)."""
    by_status: dict[str, int] = field(default_factory=dict)
    by_fixture: dict[int, int] = field(default_factory=dict)
    """Picks settled by this pass, per fixture: what the settlement-latency record counts."""


OPEN_PICKS_SQL = """
SELECT p.id, p.fixture_id, p.market_key, p.selection, p.line, p.market_odds, p.stake_units, p.status,
       f.status_short, r.reg_goals_home, r.reg_goals_away, r.et_goals_home, r.et_goals_away,
       r.ft_goals_home, r.ft_goals_away, r.source_payload_hash,
       COALESCE(pr.review_reason, '') AS previous_review
  FROM picks.picks p
  JOIN core.fixtures f ON f.id = p.fixture_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = p.fixture_id
  LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
 WHERE p.status <> 'settled' AND (%(fixtures)s::bigint[] IS NULL OR p.fixture_id = ANY(%(fixtures)s))
 ORDER BY p.id
"""


def settle_open_picks(conn: psycopg.Connection, *, run_id: int | None,
                      fixture_ids: list[int] | None = None) -> SettlementReport:
    """Settle every open pick whose match allows it - or only those of ``fixture_ids``.

    Safe to run beside another pass: the pick's own row is claimed first (``status <> 'settled'``
    in the UPDATE), so a pick two passes both read is settled once, by the first to write.
    ``settled_at`` is the wall clock of the write, not the start of the pass.
    """
    report = SettlementReport()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(OPEN_PICKS_SQL, {"fixtures": fixture_ids})
        rows = list(cur.fetchall())
    for p in rows:
        report.open_picks += 1
        result = settlement.settle(
            p["market_key"], p["selection"], Decimal(p["line"]), Decimal(p["market_odds"]), Decimal(p["stake_units"]),
            settlement.MatchState(p["status_short"], p["reg_goals_home"], p["reg_goals_away"],
                                  p.get("et_goals_home"), p.get("et_goals_away"),
                                  p.get("ft_goals_home"), p.get("ft_goals_away")))
        with conn.cursor() as cur:
            if not result.is_final:
                report.still_pending += 1
                if result.review_reason:
                    report.needs_review += 1
                if result.review_reason != (p["previous_review"] or None):
                    cur.execute("UPDATE picks.pick_results SET review_reason = %s WHERE pick_id = %s",
                                (result.review_reason, p["id"]))
                continue
            cur.execute("UPDATE picks.picks SET status = 'settled', status_changed_at = clock_timestamp() "
                        "WHERE id = %s AND status <> 'settled'", (p["id"],))
            if cur.rowcount == 0:
                report.already_settled += 1
                continue
            cur.execute(
                """
                INSERT INTO picks.pick_results (pick_id, result_status, profit_units, settled_at, settled_by,
                    settlement_basis, rule_version, result_payload_hash, review_reason)
                VALUES (%s, %s, %s, clock_timestamp(), %s, %s, %s, %s, NULL)
                ON CONFLICT (pick_id) DO UPDATE SET result_status = EXCLUDED.result_status,
                    profit_units = EXCLUDED.profit_units, settled_at = EXCLUDED.settled_at,
                    settled_by = EXCLUDED.settled_by, settlement_basis = EXCLUDED.settlement_basis,
                    rule_version = EXCLUDED.rule_version, result_payload_hash = EXCLUDED.result_payload_hash,
                    review_reason = NULL
                """,
                (p["id"], result.status.value, result.profit_units, f"worker:{settlement.RULE_VERSION}",
                 settlement.BASIS if result.status is not settlement.Status.VOID else "not_played",
                 settlement.RULE_VERSION, p["source_payload_hash"]),
            )
            cur.execute("INSERT INTO picks.pick_events (pick_id, from_status, to_status, reason, run_id) "
                        "VALUES (%s, %s, 'settled', %s, %s)",
                        (p["id"], p["status"], f"{result.status.value} on {settlement.BASIS}", run_id))
        report.settled += 1
        report.by_status[result.status.value] = report.by_status.get(result.status.value, 0) + 1
        fid = int(p["fixture_id"])
        report.by_fixture[fid] = report.by_fixture.get(fid, 0) + 1
    return report
