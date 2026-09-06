"""Permanent anti-regression tests for the V2 schema.

These are the sixteen checks from docs/rebuild/schema_v2/999_constraint_tests.sql,
converted from a one-off psql script into a suite that runs on every commit,
plus the extra invariants introduced by the near-close naming rules.

Each test demonstrates that a specific structural defect of the legacy system is
IMPOSSIBLE in V2 - not by programmer discipline, but because PostgreSQL refuses
the write. Every test is independent: the connection is rolled back afterwards,
so a failing negative case can no longer poison the ids of the next test the way
the original script did.

If one of these fails, the schema has regressed. Do not "fix the test".
"""

from __future__ import annotations

import psycopg
import pytest

from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_accepted, must_be_rejected, scalar

CALIBRATOR_COLS = (
    "model_version_id,market_key,scope,method,params,n_train,train_from,train_to,"
    "n_val,val_from,val_to,val_ece,val_mce,val_brier,val_logloss,reliability_weight"
)
BACKTEST_COLS = (
    "name,model_version_id,competition_ids,test_from,test_to,protocol,"
    "train_window,code_version,dataset_hash,n_samples,accuracy_pct,brier_score,logloss,ece"
)
PICK_COLS = (
    "candidate_id,fixture_id,market_key,selection,model_version_id,calibrator_id,"
    "feature_set_hash,data_cutoff_ts,decision_rule_version,code_version,bookmaker_id,"
    "market_odds,odds_captured_at,p_model,p_calibrated,p_calibrated_lo,p_calibrated_hi,"
    "p_market_fair,fair_odds,edge,price_edge,ev,ev_adjusted,kelly_fraction,stake_units,"
    "selection_reason"
)


def _valid_calibrator(cur: psycopg.Cursor, seed: Seed) -> int:
    cur.execute(
        f"INSERT INTO models.calibrators ({CALIBRATOR_COLS}) VALUES "
        "(%s,'1X2','global','isotonic','{}',1000,'2020-01-01','2024-06-30',"
        "500,'2024-07-01','2025-06-30',0.018,0.04,0.19,0.58,0.82) RETURNING id",
        (seed.model_version_id,),
    )
    return scalar(cur)


def _valid_prediction(cur: psycopg.Cursor, seed: Seed, calibrator_id: int) -> int:
    cur.execute(
        "INSERT INTO models.predictions "
        "(fixture_id,model_version_id,calibrator_id,market_key,selection,"
        " p_raw,p_calibrated,p_lo,p_hi,feature_set_hash,data_cutoff_ts) "
        "VALUES (%s,%s,%s,'1X2','Home',0.52,0.49,0.44,0.54,'fh','2026-09-15 18:00Z') RETURNING id",
        (seed.fixture_id, seed.model_version_id, calibrator_id),
    )
    return scalar(cur)


def _selected_candidate(cur: psycopg.Cursor, seed: Seed, prediction_id: int) -> int:
    cur.execute(
        "INSERT INTO picks.pick_candidates "
        "(run_id,fixture_id,prediction_id,market_key,selection,bookmaker_id,market_odds,"
        " p_calibrated,p_market_fair,edge,price_edge,ev,ev_adjusted,decision) "
        "VALUES (%s,%s,%s,'1X2','Home',%s,2.10,0.49,0.465,0.025,0.014,0.029,0.024,'selected') "
        "RETURNING id",
        (seed.run_id, seed.fixture_id, prediction_id, seed.bookmaker_id),
    )
    return scalar(cur)


def _valid_pick(
    cur: psycopg.Cursor,
    seed: Seed,
    candidate_id: int,
    calibrator_id: int,
    *,
    market_odds: str = "2.10",
    data_cutoff_ts: str = "2026-09-15 18:00Z",
) -> int:
    cur.execute(
        f"INSERT INTO picks.picks ({PICK_COLS}) VALUES "
        "(%s,%s,'1X2','Home',%s,%s,'fh',%s,'r1','abc',%s,%s,'2026-09-15 18:05Z',"
        " 0.52,0.49,0.44,0.54,0.465,2.04,0.025,0.014,0.029,0.024,0.012,0.5,'{\"why\":\"price_edge>0\"}') "
        "RETURNING id",
        (
            candidate_id,
            seed.fixture_id,
            seed.model_version_id,
            calibrator_id,
            data_cutoff_ts,
            seed.bookmaker_id,
            market_odds,
        ),
    )
    return scalar(cur)


# ═══════════════════════════════════════════════════════════════════════════════
# The odds time series
# ═══════════════════════════════════════════════════════════════════════════════


def test_t1_same_selection_at_three_instants_coexists(db: psycopg.Connection, seed: Seed) -> None:
    """T1 - legacy had a UNIQUE with no temporal component, so each sync
    OVERWROTE the previous price. Four months of history became one row."""
    with must_be_accepted(db) as cur:
        cur.executemany(
            "INSERT INTO market.odds_snapshots VALUES (%s,%s,'1X2','Home',0,%s,%s,%s,%s,%s)",
            [
                (seed.fixture_id, seed.bookmaker_id, "2.10", "2026-09-12 19:00Z", 4320, "prematch", seed.payload_hash),
                (seed.fixture_id, seed.bookmaker_id, "2.05", "2026-09-14 19:00Z", 1440, "prematch", seed.payload_hash),
                (seed.fixture_id, seed.bookmaker_id, "1.95", "2026-09-15 18:48Z", 12, "live", seed.payload_hash),
            ],
        )
        cur.execute(
            "SELECT count(*) FROM market.odds_snapshots WHERE fixture_id = %s", (seed.fixture_id,)
        )
        assert scalar(cur) == 3


def test_t1b_identical_capture_instant_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    """The temporal PK must still forbid a true duplicate."""
    with must_be_rejected(db, "same selection twice at the same captured_at") as cur:
        for _ in range(2):
            cur.execute(
                "INSERT INTO market.odds_snapshots VALUES (%s,%s,'1X2','Home',0,2.10,"
                "'2026-09-12 19:00Z',4320,'prematch',%s)",
                (seed.fixture_id, seed.bookmaker_id, seed.payload_hash),
            )


@pytest.mark.parametrize("bad_odds", ["1.000", "0.500", "1000.000"])
def test_odds_outside_the_plausible_range_are_rejected(
    db: psycopg.Connection, seed: Seed, bad_odds: str
) -> None:
    with must_be_rejected(db, f"odds_decimal = {bad_odds}") as cur:
        cur.execute(
            "INSERT INTO market.odds_snapshots VALUES (%s,%s,'1X2','Home',0,%s,"
            "'2026-09-12 19:00Z',4320,'prematch',%s)",
            (seed.fixture_id, seed.bookmaker_id, bad_odds, seed.payload_hash),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Calibration - the legacy's largest silent failure
# ═══════════════════════════════════════════════════════════════════════════════


def test_t2_calibrator_without_validation_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    """T2 - 128 of the legacy's 152 calibrators had n_val NULL."""
    with must_be_rejected(db, "calibrator with n_val NULL") as cur:
        cur.execute(
            f"INSERT INTO models.calibrators ({CALIBRATOR_COLS}) VALUES "
            "(%s,'1X2','global','isotonic','{}',1000,'2020-01-01','2024-06-30',"
            "NULL,'2024-07-01','2025-06-30',0.01,0.02,0.2,0.6,0.8)",
            (seed.model_version_id,),
        )


def test_t3_holdout_that_is_not_later_in_time_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    """T3 - exact ECE = 0.0 in 134 legacy calibrators, because they were
    evaluated on the very data they were fitted on."""
    with must_be_rejected(db, "val_from earlier than train_to") as cur:
        cur.execute(
            f"INSERT INTO models.calibrators ({CALIBRATOR_COLS}) VALUES "
            "(%s,'1X2','global','isotonic','{}',1000,'2020-01-01','2024-06-30',"
            "500,'2023-01-01','2024-01-01',0.01,0.02,0.2,0.6,0.8)",
            (seed.model_version_id,),
        )


def test_t4_calibrator_with_a_later_temporal_holdout_is_accepted(
    db: psycopg.Connection, seed: Seed
) -> None:
    with must_be_accepted(db) as cur:
        assert _valid_calibrator(cur, seed) > 0


def test_calibrator_below_the_minimum_sample_sizes_is_rejected(
    db: psycopg.Connection, seed: Seed
) -> None:
    """n_train >= 200 and n_val >= 100: a calibrator fitted on a handful of
    matches is noise wearing a probability's clothes."""
    for n_train, n_val, label in ((199, 500, "n_train"), (1000, 99, "n_val")):
        with must_be_rejected(db, f"{label} below minimum") as cur:
            cur.execute(
                f"INSERT INTO models.calibrators ({CALIBRATOR_COLS}) VALUES "
                "(%s,'1X2','global','isotonic','{}',%s,'2020-01-01','2024-06-30',"
                "%s,'2024-07-01','2025-06-30',0.01,0.02,0.2,0.6,0.8)",
                (seed.model_version_id, n_train, n_val),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Backtesting - accuracy is not profitability
# ═══════════════════════════════════════════════════════════════════════════════


def test_t5_roi_without_stake_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    """T5 - the bug that produced a believed 57% ROI: the legacy wrote accuracy
    into a column called roi_pct, with no stake behind it."""
    with must_be_rejected(db, "roi_pct with no total_stake_units") as cur:
        cur.execute(
            f"INSERT INTO analytics.backtest_runs ({BACKTEST_COLS},roi_pct) VALUES "
            "('bt1',%s,'{1}','2024-08-01','2025-06-30','walk_forward','4s','abc','d1',"
            "5000,57.66,0.21,0.65,0.11,57.66)",
            (seed.model_version_id,),
        )


def test_t6_backtest_without_economics_stores_null_not_zero(
    db: psycopg.Connection, seed: Seed
) -> None:
    """T6 - "not measurable" must be NULL. Zero is a claim; NULL is the truth."""
    with must_be_accepted(db) as cur:
        cur.execute(
            f"INSERT INTO analytics.backtest_runs ({BACKTEST_COLS}) VALUES "
            "('bt2',%s,'{1}','2024-08-01','2025-06-30','walk_forward','4s','abc','d1',"
            "5000,57.66,0.21,0.65,0.11) RETURNING roi_pct, n_bets, near_close_lv_mean",
            (seed.model_version_id,),
        )
        assert cur.fetchone() == (None, None, None)


def test_bets_counted_without_naming_the_odds_source_is_rejected(
    db: psycopg.Connection, seed: Seed
) -> None:
    with must_be_rejected(db, "n_bets with odds_source NULL") as cur:
        cur.execute(
            f"INSERT INTO analytics.backtest_runs ({BACKTEST_COLS},n_bets) VALUES "
            "('bt3',%s,'{1}','2024-08-01','2025-06-30','walk_forward','4s','abc','d1',"
            "5000,57.66,0.21,0.65,0.11,120)",
            (seed.model_version_id,),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Predictions
# ═══════════════════════════════════════════════════════════════════════════════


def test_t7_probability_outside_zero_one_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_rejected(db, "p_calibrated = 1.4") as cur:
        cur.execute(
            "INSERT INTO models.predictions "
            "(fixture_id,model_version_id,market_key,selection,p_raw,p_calibrated,p_lo,p_hi,"
            " feature_set_hash,data_cutoff_ts) "
            "VALUES (%s,%s,'1X2','Home',1.4,1.4,1.3,1.5,'fh','2026-09-15 18:00Z')",
            (seed.fixture_id, seed.model_version_id),
        )


def test_t8_a_valid_prediction_is_accepted(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_accepted(db) as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        assert _valid_prediction(cur, seed, calibrator_id) > 0


def test_interval_that_does_not_contain_the_point_estimate_is_rejected(
    db: psycopg.Connection, seed: Seed
) -> None:
    """p_lo <= p_calibrated <= p_hi. Uncertainty that excludes its own estimate
    is a coding error, and the fractional Kelly stake depends on p_lo."""
    with must_be_rejected(db, "p_lo above p_calibrated") as cur:
        cur.execute(
            "INSERT INTO models.predictions "
            "(fixture_id,model_version_id,market_key,selection,p_raw,p_calibrated,p_lo,p_hi,"
            " feature_set_hash,data_cutoff_ts) "
            "VALUES (%s,%s,'1X2','Home',0.52,0.49,0.60,0.70,'fh','2026-09-15 18:00Z')",
            (seed.fixture_id, seed.model_version_id),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Pick candidates - no selection without a price, no rejection without a reason
# ═══════════════════════════════════════════════════════════════════════════════


def test_t9_selected_candidate_without_a_price_is_rejected(
    db: psycopg.Connection, seed: Seed
) -> None:
    """T9 - all 16 picks of the legacy value engine had offered_odds NULL.
    A bet with no price cannot be evaluated, ever."""
    with must_be_rejected(db, "selected candidate with market_odds NULL") as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        cur.execute(
            "INSERT INTO picks.pick_candidates "
            "(run_id,fixture_id,prediction_id,market_key,selection,p_calibrated,decision) "
            "VALUES (%s,%s,%s,'DC','1X',0.79,'selected')",
            (seed.run_id, seed.fixture_id, prediction_id),
        )


def test_t10_rejected_candidate_without_a_reason_is_rejected(
    db: psycopg.Connection, seed: Seed
) -> None:
    with must_be_rejected(db, "rejected candidate with rejection_reason NULL") as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        cur.execute(
            "INSERT INTO picks.pick_candidates "
            "(run_id,fixture_id,prediction_id,market_key,selection,p_calibrated,decision) "
            "VALUES (%s,%s,%s,'DC','1X',0.79,'rejected')",
            (seed.run_id, seed.fixture_id, prediction_id),
        )


def test_t11_selected_candidate_with_a_price_is_accepted(
    db: psycopg.Connection, seed: Seed
) -> None:
    with must_be_accepted(db) as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        assert _selected_candidate(cur, seed, prediction_id) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Picks - price, traceability and no look-ahead
# ═══════════════════════════════════════════════════════════════════════════════


def test_t12_pick_at_odds_of_one_or_less_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_rejected(db, "market_odds = 1.00") as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        candidate_id = _selected_candidate(cur, seed, prediction_id)
        _valid_pick(cur, seed, candidate_id, calibrator_id, market_odds="1.00")


def test_t13_data_cutoff_after_the_price_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    """T13 - look-ahead bias made structurally impossible: a decision may not
    use information that appeared after the price it was taken at."""
    with must_be_rejected(db, "data_cutoff_ts later than odds_captured_at") as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        candidate_id = _selected_candidate(cur, seed, prediction_id)
        _valid_pick(cur, seed, candidate_id, calibrator_id, data_cutoff_ts="2026-09-15 19:30Z")


def test_t14_a_complete_traceable_priced_pick_is_accepted(
    db: psycopg.Connection, seed: Seed
) -> None:
    with must_be_accepted(db) as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        candidate_id = _selected_candidate(cur, seed, prediction_id)
        pick_id = _valid_pick(cur, seed, candidate_id, calibrator_id)
        cur.execute("SELECT mode FROM picks.picks WHERE id = %s", (pick_id,))
        assert scalar(cur) == "shadow", "a new pick must default to shadow, never live"


def test_the_same_candidate_cannot_become_two_picks(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_rejected(db, "two picks from one candidate") as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        candidate_id = _selected_candidate(cur, seed, prediction_id)
        _valid_pick(cur, seed, candidate_id, calibrator_id)
        _valid_pick(cur, seed, candidate_id, calibrator_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Settlement
# ═══════════════════════════════════════════════════════════════════════════════


def test_t15_half_win_settlement_is_accepted(db: psycopg.Connection, seed: Seed) -> None:
    """T15 - the legacy only had win/loss/void, which cannot settle an Asian
    handicap or any half-line correctly."""
    with must_be_accepted(db) as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        candidate_id = _selected_candidate(cur, seed, prediction_id)
        pick_id = _valid_pick(cur, seed, candidate_id, calibrator_id)
        cur.execute(
            "INSERT INTO picks.pick_results (pick_id,result_status,profit_units,settled_at) "
            "VALUES (%s,'half_win',0.55,now()) RETURNING result_status",
            (pick_id,),
        )
        assert scalar(cur) == "half_win"


def test_t16_settled_result_without_profit_or_date_is_rejected(
    db: psycopg.Connection, seed: Seed
) -> None:
    with must_be_rejected(db, "result 'win' with profit_units NULL") as cur:
        calibrator_id = _valid_calibrator(cur, seed)
        prediction_id = _valid_prediction(cur, seed, calibrator_id)
        candidate_id = _selected_candidate(cur, seed, prediction_id)
        pick_id = _valid_pick(cur, seed, candidate_id, calibrator_id)
        cur.execute(
            "INSERT INTO picks.pick_results (pick_id,result_status) VALUES (%s,'win')",
            (pick_id,),
        )
