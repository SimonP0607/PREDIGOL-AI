-- PrediGol Intelligence - Plan Maestro RP, RP-0.1: the frozen baseline of 22 indicators, READ ONLY.
--
-- Run it on the production server with scripts/intel_baseline.sh (read-only session, statement time limit):
--     psql --csv -v cut="'2026-11-26 03:15:00+00'" -v base_before="'2026-11-24 00:00:00+00'" -f intel_baseline.sql
-- Every statement is a SELECT. Output: sections "### <name>" each followed by a CSV table; scripts/intel_baseline_report.py
-- splits them, hashes every section and writes docs/intelligence/baseline/baseline-v1.json.
--
-- Two fixed parameters make a second run with the same cut give the same hash:
--   :cut          the freeze moment. Every row read is bounded by it (known_at / at / created_at <= cut), so what was
--                 written afterwards does not move the number. Sections marked "live" read state that cannot be bounded
--                 (the heartbeat of the worker); they are reported but left out of the repeatability check.
--   :base_before  the fixed competition set: tracked competitions created before this moment (the 24-nov set, before the
--                 expansion batches of the 25-nov). Competitions added later are reported apart in section competitions_new,
--                 because adding them moves every percentage without anything having changed.
--
-- Definitions are written here once so that the "after" is measured with the same query. Where the 24-nov audit gave a number
-- by a query that was not kept, this file fixes its own definition and says so: the two are NOT comparable and the final report
-- must not present the difference as an improvement.

\set ON_ERROR_STOP off
\pset null ''
\pset footer off

BEGIN READ ONLY;
SET LOCAL statement_timeout = '150s';
SET LOCAL lock_timeout = '2s';

\echo ### meta
SELECT :cut::timestamptz AT TIME ZONE 'UTC' AS cut_utc,
       :base_before::timestamptz AT TIME ZONE 'UTC' AS base_before_utc,
       (SELECT version_num FROM alembic_version LIMIT 1) AS migration,
       current_setting('transaction_read_only') AS read_only,
       'intel-baseline-v1' AS definition_version;

\echo ### competitions_base
SELECT c.id, c.name, c.country, c.tier FROM core.competitions c
 WHERE c.is_tracked AND c.created_at < :base_before::timestamptz ORDER BY c.id;

\echo ### competitions_new
SELECT count(*) AS tracked_after_base FROM core.competitions c
 WHERE c.is_tracked AND c.created_at >= :base_before::timestamptz AND c.created_at <= :cut::timestamptz;

\echo ### i01_i02_forecast_vs_market
-- I1 raw model vs market and I2 the figure shown vs market: mean log-loss difference (model minus market, positive = worse
-- than the market) on the 1X2 of finished matches of the base set. Forecast: forecast-v1, last set known >= 180 minutes before
-- kickoff; market: Shin consensus, last one >= 180 minutes before kickoff (the 3-hour "previous reference").
WITH fx AS (SELECT f.id, f.kickoff_at, r.outcome_1x2 o FROM core.fixtures f
            JOIN core.fixture_results r ON r.fixture_id = f.id
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND c.created_at < :base_before::timestamptz
              AND r.outcome_1x2 IS NOT NULL AND f.kickoff_at < :cut::timestamptz),
fc AS (SELECT DISTINCT ON (m.fixture_id, m.selection) m.fixture_id, m.selection, m.p_model, m.p
       FROM models.match_forecasts m JOIN fx ON fx.id = m.fixture_id
       WHERE m.market_key = '1X2' AND m.version = 'forecast-v1' AND m.known_at <= fx.kickoff_at - interval '180 minutes'
       ORDER BY m.fixture_id, m.selection, m.known_at DESC),
mk AS (SELECT DISTINCT ON (c.fixture_id, c.selection) c.fixture_id, c.selection, c.p_fair
       FROM market.market_consensus c JOIN fx ON fx.id = c.fixture_id
       WHERE c.market_key = '1X2' AND c.devig_method = 'shin' AND c.as_of <= fx.kickoff_at - interval '180 minutes'
       ORDER BY c.fixture_id, c.selection, c.as_of DESC)
SELECT count(DISTINCT fx.id) AS matches,
       round(avg(-ln(fc.p_model) + ln(mk.p_fair))::numeric, 4) AS raw_minus_market,
       round((stddev(-ln(fc.p_model) + ln(mk.p_fair)) / sqrt(count(*)))::numeric, 4) AS raw_se,
       round(avg(-ln(fc.p) + ln(mk.p_fair))::numeric, 4) AS shown_minus_market,
       round((stddev(-ln(fc.p) + ln(mk.p_fair)) / sqrt(count(*)))::numeric, 4) AS shown_se
  FROM fx JOIN fc ON fc.fixture_id = fx.id AND fc.selection = fx.o
          JOIN mk ON mk.fixture_id = fx.id AND mk.selection = fc.selection;

\echo ### i03_calibration_by_family
-- I3 distance between what was said and what happened, by family: mean judged probability minus observed frequency, points.
SELECT layer, family, count(*) AS n, round(avg(p_judged)::numeric, 4) AS mean_p, round(avg(hit)::numeric, 4) AS freq,
       round((100 * (avg(p_judged) - avg(hit)))::numeric, 2) AS gap_points
  FROM intel.selection_evaluations
 WHERE hit IS NOT NULL AND p_judged IS NOT NULL AND decided_at <= :cut::timestamptz
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo ### i04_loss_vs_market_by_family
-- I4 log-loss minus market log-loss by family (positive = worse than the market), with standard error.
SELECT layer, family, count(*) AS n, round(avg(log_loss - market_log_loss)::numeric, 4) AS loss_minus_market,
       round((stddev(log_loss - market_log_loss) / sqrt(count(*)))::numeric, 4) AS se
  FROM intel.selection_evaluations
 WHERE log_loss IS NOT NULL AND market_log_loss IS NOT NULL AND decided_at <= :cut::timestamptz
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo ### i05_by_competition_level
-- I5 calibrated difference by competition level: the newest evaluation report that has level segments.
SELECT source, model_name, market_key, segment_key AS level, n, round(skill::numeric, 4) AS skill,
       round(skill_low::numeric, 4) AS skill_low, round(skill_high::numeric, 4) AS skill_high, verdict
  FROM analytics.evaluation_segments
 WHERE segment_kind = 'level'
   AND report_id = (SELECT max(report_id) FROM analytics.evaluation_segments WHERE segment_kind = 'level')
 ORDER BY market_key, segment_key LIMIT 80;

\echo ### i06_coherence
-- I6 violations of the eight coherence tests: not measured continuously today (the audit says so). RP-2.2 creates the
-- nightly measure; this row stays empty on purpose so the "before" is "not measured", not zero.
SELECT 'not_measured' AS state, 'RP-2.2 adds the nightly audit' AS note;

\echo ### i07_close_minutes
-- I7 minutes from the last Shin consensus to kickoff, matches of the base set finished in the 30 days before the cut.
WITH fx AS (SELECT f.id, f.kickoff_at FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND c.created_at < :base_before::timestamptz
              AND f.kickoff_at >= :cut::timestamptz - interval '30 days' AND f.kickoff_at < :cut::timestamptz),
last AS (SELECT fx.id, fx.kickoff_at, max(m.as_of) AS as_of FROM fx
         JOIN market.market_consensus m ON m.fixture_id = fx.id AND m.market_key = '1X2' AND m.devig_method = 'shin'
          AND m.as_of <= fx.kickoff_at GROUP BY 1, 2)
SELECT count(*) AS matches,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM kickoff_at - as_of) / 60))::numeric, 1) AS median_min,
       round((percentile_cont(0.1) WITHIN GROUP (ORDER BY extract(epoch FROM kickoff_at - as_of) / 60))::numeric, 1) AS p10_min,
       round((percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM kickoff_at - as_of) / 60))::numeric, 1) AS p90_min,
       count(*) FILTER (WHERE kickoff_at - as_of <= interval '30 minutes') AS within_30_min
  FROM last;

\echo ### i08_research_coverage_played
-- I8 share of matches played in the 7 days before the cut (base set) that had a web search paid before kickoff.
WITH fx AS (SELECT f.id, f.kickoff_at FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND c.created_at < :base_before::timestamptz
              AND f.kickoff_at >= :cut::timestamptz - interval '7 days' AND f.kickoff_at < :cut::timestamptz)
SELECT count(*) AS matches,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ai.usage u WHERE u.fixture_id = fx.id AND u.purpose = 'web_search'
                                      AND u.at <= fx.kickoff_at)) AS with_web_search,
       round((100.0 * count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ai.usage u WHERE u.fixture_id = fx.id
              AND u.purpose = 'web_search' AND u.at <= fx.kickoff_at)) / NULLIF(count(*), 0))::numeric, 1) AS pct
  FROM fx;

\echo ### i09_researched_before_match_day
-- I9 of the matches in the 7 days after the cut (base set), how many had a web search made on an earlier Bogota day.
-- The level-A list is the owner's priority list (decision D2); until RP-5.4 fixes it, all base matches are counted.
WITH fx AS (SELECT f.id, f.kickoff_at FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND c.created_at < :base_before::timestamptz
              AND f.kickoff_at >= :cut::timestamptz AND f.kickoff_at < :cut::timestamptz + interval '7 days')
SELECT count(*) AS matches,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ai.usage u WHERE u.fixture_id = fx.id AND u.purpose = 'web_search'
              AND u.at <= :cut::timestamptz
              AND (u.at AT TIME ZONE 'America/Bogota')::date < (fx.kickoff_at AT TIME ZONE 'America/Bogota')::date)) AS searched_before_day
  FROM fx;

\echo ### i10_facts_per_researched_match
-- I10 confirmed web facts per researched match, evidence retrieved in the 14 days before the cut.
SELECT count(DISTINCT fixture_id) AS researched_matches,
       count(*) FILTER (WHERE status = 'CONFIRMED') AS confirmed_facts,
       count(*) AS web_facts,
       round((count(*) FILTER (WHERE status = 'CONFIRMED'))::numeric / NULLIF(count(DISTINCT fixture_id), 0), 2) AS confirmed_per_match
  FROM ai.evidence
 WHERE origin = 'web' AND fixture_id IS NOT NULL AND retrieved_at > :cut::timestamptz - interval '14 days'
   AND retrieved_at <= :cut::timestamptz;

\echo ### i11_unknown_tier_share
-- I11 share of web facts whose source tier is unknown, 30 days before the cut.
SELECT coalesce(source_tier, 'NULL') AS tier, count(*) AS facts,
       round((100.0 * count(*) / sum(count(*)) OVER ())::numeric, 1) AS pct
  FROM ai.evidence
 WHERE origin = 'web' AND retrieved_at > :cut::timestamptz - interval '30 days' AND retrieved_at <= :cut::timestamptz
 GROUP BY 1 ORDER BY 2 DESC;

\echo ### i12_stories_with_own_text
-- I12 stories with their own verified text.
SELECT (SELECT count(DISTINCT story_key) FROM news.stories WHERE at <= :cut::timestamptz) AS stories,
       (SELECT count(DISTINCT story_key) FROM news.story_texts WHERE at <= :cut::timestamptz) AS stories_with_text,
       (SELECT count(*) FROM news.items WHERE seen_at <= :cut::timestamptz) AS items,
       (SELECT count(DISTINCT source_domain) FROM news.items WHERE seen_at <= :cut::timestamptz) AS item_domains,
       (SELECT count(*) FROM ai.evidence WHERE item_id IS NOT NULL AND retrieved_at <= :cut::timestamptz) AS evidence_with_item;

\echo ### i13_complete_texts
-- I13 chronicles of the 14 days before the cut that arrive complete (status ok), by route.
SELECT route, status, count(*) AS n,
       round((100.0 * count(*) / sum(count(*)) OVER ())::numeric, 1) AS pct_of_total
  FROM ai.chronicles
 WHERE created_at > :cut::timestamptz - interval '14 days' AND created_at <= :cut::timestamptz
 GROUP BY 1, 2 ORDER BY 3 DESC;

\echo ### i14_unsupported_claims
-- I14 claims without support in a sample of 50: not measured today; RP-7.4 defines the sample and the reader.
SELECT 'not_measured' AS state, 'RP-7.4 defines the 50-text sample' AS note;

\echo ### i15_cost_per_analyzed_match
-- I15 AI cost per match analysed, 7 days before the cut (matches with at least one paid call that names a fixture).
SELECT round(sum(cost_usd)::numeric, 4) AS cost_usd, count(DISTINCT fixture_id) AS fixtures,
       round((sum(cost_usd) / NULLIF(count(DISTINCT fixture_id), 0))::numeric, 4) AS usd_per_fixture,
       round(sum(cost_usd) FILTER (WHERE fixture_id IS NULL)::numeric, 4) AS cost_without_fixture
  FROM ai.usage WHERE at > :cut::timestamptz - interval '7 days' AND at <= :cut::timestamptz;

\echo ### i16_cost_per_confirmed_fact
-- I16 cost of searching and extracting per confirmed web fact, 7 days before the cut. EXP-E8 refines it per source type.
SELECT (SELECT round(sum(cost_usd)::numeric, 4) FROM ai.usage
         WHERE purpose IN ('web_search', 'evidence_extraction') AND at > :cut::timestamptz - interval '7 days' AND at <= :cut::timestamptz) AS search_extraction_usd,
       (SELECT count(*) FROM ai.evidence WHERE origin = 'web' AND status = 'CONFIRMED'
          AND retrieved_at > :cut::timestamptz - interval '7 days' AND retrieved_at <= :cut::timestamptz) AS confirmed_web_facts;

\echo ### i17_review_share_of_spend
-- I17 share of the AI spend that goes to reviewing candidates, by purpose, 7 days before the cut.
SELECT purpose, count(*) AS calls, round(sum(cost_usd)::numeric, 4) AS cost_usd,
       round((100.0 * sum(cost_usd) / sum(sum(cost_usd)) OVER ())::numeric, 1) AS pct
  FROM ai.usage WHERE at > :cut::timestamptz - interval '7 days' AND at <= :cut::timestamptz
 GROUP BY 1 ORDER BY 3 DESC;

\echo ### i17b_review_verdicts
SELECT decision, count(*) AS n FROM ai.pick_reviews
 WHERE reviewed_at > :cut::timestamptz - interval '7 days' AND reviewed_at <= :cut::timestamptz AND engine = 'llm'
 GROUP BY 1 ORDER BY 2 DESC;

\echo ### i18_hypotheses
-- I18 hypotheses without destination (PROPOSED) out of all.
SELECT status, count(*) AS n, count(*) FILTER (WHERE proposed_by <> 'system') AS by_ai FROM analytics.research_hypotheses
 WHERE created_at <= :cut::timestamptz GROUP BY 1 ORDER BY 2 DESC;

\echo ### i19_experiments_since_4_oct
-- I19 experiments started since 5-oct, and the newest start; verdicts live in research_status / gate.
SELECT count(*) AS experiments_total, max(started_at) AS last_started,
       count(*) FILTER (WHERE started_at >= '2026-10-05'::timestamptz) AS since_5_oct,
       count(*) FILTER (WHERE started_at >= '2026-10-05'::timestamptz AND gate IS NOT NULL) AS since_5_oct_with_gate
  FROM analytics.experiments WHERE started_at <= :cut::timestamptz;

\echo ### i20_runs_by_status_7d
-- I20 runs of the ledger by status in the 7 days before the cut.
SELECT status, count(*) AS runs FROM raw.ingestion_runs
 WHERE started_at > :cut::timestamptz - interval '7 days' AND started_at <= :cut::timestamptz GROUP BY 1 ORDER BY 2 DESC;

\echo ### i20b_jobs_outside_ledger_live
-- LIVE. Scheduled jobs in the worker heartbeat that have no row in the ledger in the 30 days before the cut.
WITH hb AS (SELECT jsonb_object_keys(jobs) AS job FROM raw.worker_heartbeats WHERE stopped_at IS NULL
            AND last_beat_at > now() - interval '10 minutes')
SELECT (SELECT count(DISTINCT job) FROM hb) AS jobs_in_heartbeat,
       (SELECT count(DISTINCT job) FROM hb WHERE job NOT IN
          (SELECT DISTINCT job_name FROM raw.ingestion_runs WHERE started_at > :cut::timestamptz - interval '30 days')) AS jobs_outside_ledger;

\echo ### i21_parlays_30d
-- I21 parlays in shadow of the 30 days before the cut: calibration error is not measurable until RP-11.1.
SELECT count(*) AS parlays, round(avg(p_joint)::numeric, 4) AS mean_p_joint, round(avg(combined_odds)::numeric, 2) AS mean_odds,
       round(avg(n_legs)::numeric, 2) AS mean_legs, 'not_measured' AS calibration_error
  FROM intel.parlays_v6 WHERE recorded_at > :cut::timestamptz - interval '30 days' AND recorded_at <= :cut::timestamptz;

\echo ### i22_latency
-- I22 latency of the Intelligence routes: measured in-process by scripts/baseline_snapshot.py (timings_ms in its manifest).
SELECT 'measured_outside_sql' AS state, 'baseline_snapshot.py manifest timings_ms' AS note;

ROLLBACK;
