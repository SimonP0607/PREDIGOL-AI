-- PrediGol Intelligence - Plan Maestro IA, Phase 0: the baseline, READ ONLY.
--
-- Run it against the production database in a read-only session with a time limit (see scripts/ia_baseline.sh):
--     psql --csv -U fbi -d fbi -f ia_baseline.sql
-- Every statement is a SELECT; the whole script runs in one READ ONLY transaction that is rolled back at the end.
-- Nothing here writes, locks beyond a share lock, or calls a provider. The output is a series of sections, each
-- introduced by a line "### <name>" followed by a CSV table, so a program can split and read them (the report in
-- docs/owner/IA_BASELINE_F0.md is made from this output and says which run it came from).
--
-- The window is "the last 30 days where available": the AI layer v2 (ai.usage, ai.day_plans, ai.match_briefs ...) only
-- exists since the middle of October 2026, so the first section says how many days each table really has. Days are
-- Bogota days (America/Bogota), the unit the AI works in; a UTC day is given where the budget code uses it.

\set ON_ERROR_STOP off
\pset null ''
\pset footer off

BEGIN READ ONLY;
SET LOCAL statement_timeout = '90s';
SET LOCAL lock_timeout = '2s';

\echo ### meta
SELECT now() AT TIME ZONE 'UTC' AS now_utc,
       current_database() AS db,
       (SELECT version_num FROM alembic_version LIMIT 1) AS migration,
       pg_size_pretty(pg_database_size(current_database())) AS db_size,
       current_setting('transaction_read_only') AS read_only,
       (SELECT now() - interval '30 days') AT TIME ZONE 'UTC' AS window_from_utc;

\echo ### availability
SELECT t AS "table", n AS rows, first_at AT TIME ZONE 'UTC' AS first_utc, last_at AT TIME ZONE 'UTC' AS last_utc,
       round(extract(epoch FROM (last_at - first_at)) / 86400.0, 2) AS days_spanned
  FROM (
    SELECT 'ai.usage' t, count(*) n, min(at) first_at, max(at) last_at FROM ai.usage
    UNION ALL SELECT 'analytics.ai_runs', count(*), min(started_at), max(started_at) FROM analytics.ai_runs
    UNION ALL SELECT 'ai.day_plans', count(*), min(created_at), max(created_at) FROM ai.day_plans
    UNION ALL SELECT 'ai.fixture_passes', count(*), min(started_at), max(started_at) FROM ai.fixture_passes
    UNION ALL SELECT 'ai.match_briefs', count(*), min(created_at), max(created_at) FROM ai.match_briefs
    UNION ALL SELECT 'ai.match_packets', count(*), min(built_at), max(built_at) FROM ai.match_packets
    UNION ALL SELECT 'ai.pick_reviews', count(*), min(reviewed_at), max(reviewed_at) FROM ai.pick_reviews
    UNION ALL SELECT 'ai.evidence', count(*), min(retrieved_at), max(retrieved_at) FROM ai.evidence
    UNION ALL SELECT 'ai.research_cache', count(*), min(fetched_at), max(fetched_at) FROM ai.research_cache
    UNION ALL SELECT 'ai.cycles', count(*), min(started_at), max(started_at) FROM ai.cycles
    UNION ALL SELECT 'ai.budget_alerts', count(*), min(created_at), max(created_at) FROM ai.budget_alerts
    UNION ALL SELECT 'ai.pick_postmortems', count(*), min(created_at), max(created_at) FROM ai.pick_postmortems
    UNION ALL SELECT 'intel.decisions', count(*), min(known_at), max(known_at) FROM intel.decisions
    UNION ALL SELECT 'intel.decision_outcomes', count(*), min(settled_at), max(settled_at) FROM intel.decision_outcomes
    UNION ALL SELECT 'intel.postmortems', count(*), min(created_at), max(created_at) FROM intel.postmortems
  ) a
 ORDER BY 1;

\echo ### spend_by_day_provider
-- Claude and Exa, per Bogota day, as the budget code adds them up (ai.usage + the older analyst runs).
SELECT (at AT TIME ZONE 'America/Bogota')::date AS day_bogota, provider, count(*) AS calls,
       sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(cached_tokens) AS cached_tokens,
       sum(searches) AS searches, round(sum(cost_usd), 4) AS cost_usd
  FROM ai.usage WHERE at >= now() - interval '30 days'
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo ### spend_by_day_utc
-- The same by UTC day: the month and the day of ai/usage.py are UTC-based in places.
SELECT (at AT TIME ZONE 'UTC')::date AS day_utc, count(*) AS calls, round(sum(cost_usd), 4) AS cost_usd,
       round(sum(cost_usd) FILTER (WHERE provider <> 'exa' AND purpose <> 'web_search'), 4) AS claude_usd,
       round(sum(cost_usd) FILTER (WHERE provider = 'exa' OR purpose = 'web_search'), 4) AS search_usd
  FROM ai.usage WHERE at >= now() - interval '30 days'
 GROUP BY 1 ORDER BY 1;

\echo ### analyst_runs_spend
SELECT (started_at AT TIME ZONE 'UTC')::date AS day_utc, kind, status, count(*) AS runs,
       sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, round(sum(cost_usd), 4) AS cost_usd
  FROM analytics.ai_runs WHERE started_at >= now() - interval '30 days'
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

\echo ### usage_by_purpose_model
SELECT purpose, tier, provider, model, prompt_version, count(*) AS calls,
       count(*) FILTER (WHERE status = 'ok') AS ok,
       sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(cached_tokens) AS cached_tokens,
       sum(searches) AS searches, round(sum(cost_usd), 4) AS cost_usd,
       round(avg(cost_usd), 6) AS avg_cost_usd,
       round(avg(input_tokens)) AS avg_input, round(avg(output_tokens)) AS avg_output
  FROM ai.usage WHERE at >= now() - interval '30 days'
 GROUP BY 1, 2, 3, 4, 5 ORDER BY cost_usd DESC;

\echo ### usage_by_day_purpose
SELECT (at AT TIME ZONE 'America/Bogota')::date AS day_bogota, purpose, tier, model, count(*) AS calls,
       sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(cached_tokens) AS cached_tokens,
       round(sum(cost_usd), 4) AS cost_usd
  FROM ai.usage WHERE at >= now() - interval '30 days'
 GROUP BY 1, 2, 3, 4 ORDER BY 1, cost_usd DESC;

\echo ### usage_status
SELECT purpose, status, count(*) AS calls, round(sum(cost_usd), 4) AS cost_usd,
       left(coalesce(min(error), ''), 80) AS example_error
  FROM ai.usage WHERE at >= now() - interval '30 days'
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo ### usage_latency
SELECT purpose, model, count(*) FILTER (WHERE latency_ms IS NOT NULL) AS timed,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)) AS p50_ms,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY latency_ms)) AS p90_ms,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)) AS p95_ms,
       max(latency_ms) AS max_ms
  FROM ai.usage WHERE at >= now() - interval '30 days' AND latency_ms IS NOT NULL
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo ### input_tokens_distribution
SELECT purpose, model, count(*) AS calls,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY input_tokens)) AS p50_input,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY input_tokens)) AS p95_input,
       max(input_tokens) AS max_input,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY output_tokens)) AS p50_output,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY output_tokens)) AS p95_output,
       max(output_tokens) AS max_output
  FROM ai.usage WHERE at >= now() - interval '30 days' AND provider <> 'exa' AND purpose <> 'web_search'
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo ### implied_price_per_mtok
-- cost / tokens per model, to check the price table of ai/pricing.py against what the ledger really charged.
SELECT model, count(*) AS calls, sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,
       sum(cached_tokens) AS cached_tokens, round(sum(cost_usd), 4) AS cost_usd
  FROM ai.usage WHERE at >= now() - interval '30 days' AND provider <> 'exa' AND purpose <> 'web_search'
 GROUP BY 1 ORDER BY 1;

\echo ### calls_per_fixture_day
-- How many paid calls and how much money one match absorbs in a Bogota day (calls that name a fixture).
WITH per AS (
  SELECT (at AT TIME ZONE 'America/Bogota')::date AS day, fixture_id, purpose, count(*) AS calls,
         sum(cost_usd) AS cost
    FROM ai.usage
   WHERE at >= now() - interval '30 days' AND fixture_id IS NOT NULL
   GROUP BY 1, 2, 3
)
SELECT purpose, count(*) AS fixture_days, round(avg(calls), 2) AS avg_calls,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY calls) AS p50_calls,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY calls) AS p90_calls, max(calls) AS max_calls,
       count(*) FILTER (WHERE calls >= 2) AS fixture_days_with_2plus,
       round(avg(cost), 5) AS avg_cost_usd, round(percentile_cont(0.9) WITHIN GROUP (ORDER BY cost)::numeric, 5) AS p90_cost_usd
  FROM per GROUP BY 1 ORDER BY 1;

\echo ### cost_per_fixture_day
WITH per AS (
  SELECT (at AT TIME ZONE 'America/Bogota')::date AS day, fixture_id, sum(cost_usd) AS cost, count(*) AS calls
    FROM ai.usage
   WHERE at >= now() - interval '30 days' AND fixture_id IS NOT NULL
   GROUP BY 1, 2
)
SELECT day AS day_bogota, count(*) AS fixtures, sum(calls) AS calls, round(sum(cost), 4) AS cost_usd,
       round(avg(cost), 5) AS avg_cost_per_fixture,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cost)::numeric, 5) AS p50_cost,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY cost)::numeric, 5) AS p90_cost,
       round(max(cost), 5) AS max_cost
  FROM per GROUP BY 1 ORDER BY 1;

\echo ### repeated_input_hash
-- Paid calls whose input_hash was already paid for the same purpose and fixture (an identical input paid twice).
WITH u AS (
  SELECT id, at, purpose, fixture_id, input_hash, cost_usd,
         row_number() OVER (PARTITION BY purpose, fixture_id, input_hash ORDER BY at, id) AS nth
    FROM ai.usage
   WHERE at >= now() - interval '30 days' AND input_hash IS NOT NULL AND fixture_id IS NOT NULL
         AND provider <> 'exa'
)
SELECT purpose, count(*) AS calls_with_hash, count(*) FILTER (WHERE nth > 1) AS repeated,
       round(sum(cost_usd) FILTER (WHERE nth > 1), 4) AS repeated_cost_usd, round(sum(cost_usd), 4) AS cost_usd
  FROM u GROUP BY 1 ORDER BY 1;

\echo ### briefs_by_day
SELECT (created_at AT TIME ZONE 'America/Bogota')::date AS day_bogota, pass, engine, status, model,
       count(*) AS briefs, count(DISTINCT fixture_id) AS fixtures, count(DISTINCT input_hash) AS distinct_inputs,
       count(DISTINCT packet_id) AS distinct_packets, round(sum(cost_usd), 4) AS cost_usd,
       count(*) FILTER (WHERE escalate) AS escalated
  FROM ai.match_briefs WHERE created_at >= now() - interval '30 days'
 GROUP BY 1, 2, 3, 4, 5 ORDER BY 1, 2, 3, 4, 5;

\echo ### briefs_per_fixture_day
-- Briefs that were written per match and Bogota day (a brief is stored only when its input changed).
WITH per AS (
  SELECT (created_at AT TIME ZONE 'America/Bogota')::date AS day, fixture_id, count(*) AS briefs,
         count(*) FILTER (WHERE engine = 'llm') AS llm_briefs, count(DISTINCT packet_id) AS packets,
         count(DISTINCT input_hash) AS inputs
    FROM ai.match_briefs WHERE created_at >= now() - interval '30 days'
   GROUP BY 1, 2
)
SELECT day AS day_bogota, count(*) AS fixtures, sum(briefs) AS briefs, round(avg(briefs), 2) AS avg_per_fixture,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY briefs) AS p50, percentile_cont(0.9) WITHIN GROUP (ORDER BY briefs) AS p90,
       max(briefs) AS max_per_fixture, count(*) FILTER (WHERE briefs >= 2) AS fixtures_with_2plus,
       count(*) FILTER (WHERE briefs >= 4) AS fixtures_with_4plus, sum(llm_briefs) AS llm_briefs
  FROM per GROUP BY 1 ORDER BY 1;

\echo ### briefs_content_changes
-- For fixtures with two or more LLM briefs in a day: how many of the later briefs carry the same reasons,
-- uncertainty, data quality and escalate flag as the previous one (a re-read that concluded the same thing).
WITH b AS (
  SELECT fixture_id, (created_at AT TIME ZONE 'America/Bogota')::date AS day, created_at, id,
         escalate, uncertainty, data_quality, reasons, pass,
         lag(escalate) OVER w AS p_escalate, lag(uncertainty) OVER w AS p_unc, lag(data_quality) OVER w AS p_dq,
         lag(reasons) OVER w AS p_reasons
    FROM ai.match_briefs
   WHERE created_at >= now() - interval '30 days' AND engine = 'llm' AND status = 'ok'
  WINDOW w AS (PARTITION BY fixture_id, (created_at AT TIME ZONE 'America/Bogota')::date ORDER BY created_at, id)
)
SELECT day AS day_bogota, count(*) FILTER (WHERE p_escalate IS NOT NULL) AS later_briefs,
       count(*) FILTER (WHERE p_escalate IS NOT NULL AND escalate = p_escalate AND uncertainty IS NOT DISTINCT FROM p_unc
                        AND data_quality IS NOT DISTINCT FROM p_dq AND reasons = p_reasons) AS same_conclusion
  FROM b GROUP BY 1 ORDER BY 1;

\echo ### passes
SELECT day AS day_bogota, pass, status, count(*) AS passes, count(*) FILTER (WHERE escalated) AS escalated,
       round(sum(cost_usd), 4) AS cost_usd,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (finished_at - started_at)))::numeric, 1) AS p50_seconds,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (finished_at - started_at)))::numeric, 1) AS p95_seconds
  FROM ai.fixture_passes WHERE day >= (now() - interval '30 days')::date
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

\echo ### pass_timing_vs_kickoff
-- When each pass finished relative to the kickoff (minutes before): the 'final' pass must end before T-15.
SELECT pass, count(*) AS passes,
       round(percentile_cont(0.05) WITHIN GROUP (ORDER BY extract(epoch FROM (kickoff_at - finished_at)) / 60)::numeric, 1) AS p05_min_before_ko,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (kickoff_at - finished_at)) / 60)::numeric, 1) AS p50_min_before_ko,
       count(*) FILTER (WHERE kickoff_at - finished_at < interval '15 minutes') AS finished_after_t_minus_15
  FROM ai.fixture_passes WHERE day >= (now() - interval '30 days')::date AND status IN ('ok', 'partial')
 GROUP BY 1 ORDER BY 1;

\echo ### day_plans
SELECT day, stage, version, created_at AT TIME ZONE 'UTC' AS created_utc, fixtures_total, fixtures_with_market,
       jsonb_array_length(universe) AS universe_len,
       (budget ->> 'state') AS budget_state, (budget ->> 'daily_usd') AS daily_usd, (budget ->> 'cap_usd') AS cap_usd,
       left(budget::text, 220) AS budget_head
  FROM ai.day_plans WHERE day >= (now() - interval '30 days')::date ORDER BY day, stage;

\echo ### reviews_by_day
SELECT (reviewed_at AT TIME ZONE 'America/Bogota')::date AS day_bogota, engine, mode, status, count(*) AS reviews,
       count(DISTINCT fixture_id) AS fixtures,
       count(DISTINCT (fixture_id, market_key, selection, line)) AS selections,
       count(*) FILTER (WHERE decision = 'APPROVE') AS approve, count(*) FILTER (WHERE decision = 'DOWNGRADE') AS downgrade,
       count(*) FILTER (WHERE decision = 'REJECT') AS reject, count(*) FILTER (WHERE decision = 'ABSTAIN') AS abstain,
       round(sum(cost_usd), 4) AS cost_usd
  FROM ai.pick_reviews WHERE reviewed_at >= now() - interval '30 days'
 GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;

\echo ### reviews_per_selection
-- How many reviews one selection (candidate) gets, and what an LLM-reviewed candidate costs.
-- The 'combined' row repeats the cost of the model row it was made from, so only engine = 'llm' rows are summed
-- (adding both counted every model review twice: 120 USD against the 61 USD of ai.usage in the first run).
WITH per AS (
  SELECT fixture_id, market_key, selection, line, count(*) AS reviews,
         sum(cost_usd) FILTER (WHERE engine = 'llm') AS cost,
         count(*) FILTER (WHERE engine = 'llm') AS llm_reviews
    FROM ai.pick_reviews WHERE reviewed_at >= now() - interval '30 days'
   GROUP BY 1, 2, 3, 4
)
SELECT count(*) AS selections, sum(reviews) AS reviews, round(avg(reviews), 2) AS avg_reviews, max(reviews) AS max_reviews,
       count(*) FILTER (WHERE llm_reviews > 0) AS selections_with_llm,
       round(sum(cost), 4) AS cost_usd,
       round(sum(cost) FILTER (WHERE llm_reviews > 0) / nullif(count(*) FILTER (WHERE llm_reviews > 0), 0), 5) AS cost_per_llm_selection
  FROM per;

\echo ### decisions_by_day
SELECT (known_at AT TIME ZONE 'America/Bogota')::date AS day_bogota, checkpoint, state, count(*) AS decisions,
       count(DISTINCT fixture_id) AS fixtures, count(DISTINCT (fixture_id, market_key, selection, line)) AS selections,
       count(*) FILTER (WHERE review_id IS NOT NULL) AS with_ai_review,
       count(*) FILTER (WHERE context_status = 'FULL') AS ctx_full,
       count(*) FILTER (WHERE context_status = 'PARTIAL') AS ctx_partial,
       count(*) FILTER (WHERE context_status = 'LIMITED') AS ctx_limited,
       count(*) FILTER (WHERE context_status = 'PENDING') AS ctx_pending,
       count(*) FILTER (WHERE context_status = 'AI_OFF') AS ctx_ai_off
  FROM intel.decisions WHERE known_at >= now() - interval '30 days'
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

\echo ### candidates_by_day
-- Candidate volume: distinct selections the decision layer evaluated per Bogota day, and fixtures with candidates.
SELECT (known_at AT TIME ZONE 'America/Bogota')::date AS day_bogota,
       count(DISTINCT (fixture_id, market_key, selection, line)) AS candidate_selections,
       count(DISTINCT fixture_id) AS fixtures_with_candidates,
       count(DISTINCT (fixture_id, market_key, selection, line)) FILTER (WHERE state NOT IN ('RECHAZADO')) AS not_rejected,
       count(*) AS decision_rows
  FROM intel.decisions WHERE known_at >= now() - interval '30 days'
 GROUP BY 1 ORDER BY 1;

\echo ### decision_families
SELECT market_key, count(*) AS decisions, count(DISTINCT fixture_id) AS fixtures,
       count(DISTINCT (fixture_id, market_key, selection, line)) AS selections
  FROM intel.decisions WHERE known_at >= now() - interval '30 days'
 GROUP BY 1 ORDER BY 2 DESC;

\echo ### clv_by_state
SELECT d.state, count(*) AS settled, round(avg(o.clv), 5) AS mean_clv, round(stddev_samp(o.clv), 5) AS sd_clv,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY o.clv)::numeric, 5) AS median_clv,
       count(*) FILTER (WHERE o.result_status = 'win') AS wins, count(*) FILTER (WHERE o.result_status = 'loss') AS losses,
       round(sum(o.profit_flat), 3) AS profit_flat
  FROM intel.decision_outcomes o JOIN intel.decisions d ON d.id = o.decision_id
 WHERE d.known_at >= now() - interval '30 days' AND o.clv IS NOT NULL
 GROUP BY 1 ORDER BY 2 DESC;

\echo ### clv_by_day
SELECT (o.settled_at AT TIME ZONE 'America/Bogota')::date AS day_bogota, count(*) AS settled,
       round(avg(o.clv), 5) AS mean_clv, round(stddev_samp(o.clv), 5) AS sd_clv
  FROM intel.decision_outcomes o JOIN intel.decisions d ON d.id = o.decision_id
 WHERE d.known_at >= now() - interval '30 days' AND o.clv IS NOT NULL
 GROUP BY 1 ORDER BY 1;

\echo ### clv_by_review_decision
-- CLV of the selections by what the AI review said (APPROVE / DOWNGRADE / REJECT / ABSTAIN / unreviewed).
SELECT coalesce(r.decision, 'UNREVIEWED') AS ai_decision, coalesce(r.engine, '-') AS engine, count(*) AS settled,
       round(avg(o.clv), 5) AS mean_clv, round(stddev_samp(o.clv), 5) AS sd_clv
  FROM intel.decision_outcomes o JOIN intel.decisions d ON d.id = o.decision_id
  LEFT JOIN ai.pick_reviews r ON r.id = d.review_id
 WHERE d.known_at >= now() - interval '30 days' AND o.clv IS NOT NULL
 GROUP BY 1, 2 ORDER BY 3 DESC;

\echo ### packets_by_day
SELECT (built_at AT TIME ZONE 'America/Bogota')::date AS day_bogota, packet_version, count(*) AS packets,
       count(DISTINCT fixture_id) AS fixtures, round(avg(approx_tokens)) AS avg_approx_tokens,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY approx_tokens)) AS p95_approx_tokens, max(approx_tokens) AS max_approx_tokens,
       round(avg(pg_column_size(content))) AS avg_bytes
  FROM ai.match_packets WHERE built_at >= now() - interval '30 days'
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo ### evidence_by_day
SELECT (retrieved_at AT TIME ZONE 'America/Bogota')::date AS day_bogota, origin, kind, status, count(*) AS evidence,
       sum(seen_count) AS seen, count(DISTINCT fixture_id) AS fixtures
  FROM ai.evidence WHERE retrieved_at >= now() - interval '30 days'
 GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;

\echo ### evidence_per_fixture
WITH per AS (
  SELECT fixture_id, count(*) AS n FROM ai.evidence
   WHERE retrieved_at >= now() - interval '30 days' AND fixture_id IS NOT NULL GROUP BY 1
)
SELECT count(*) AS fixtures_with_evidence, round(avg(n), 2) AS avg_evidence, percentile_cont(0.5) WITHIN GROUP (ORDER BY n) AS p50,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY n) AS p90, max(n) AS max_evidence FROM per;

\echo ### research_cache
SELECT scope, count(*) AS rows, sum(hits) AS hits, count(*) FILTER (WHERE hits > 0) AS rows_hit,
       count(*) FILTER (WHERE expires_at > now()) AS live,
       round(avg(extract(epoch FROM (expires_at - fetched_at)) / 3600.0), 1) AS avg_ttl_hours
  FROM ai.research_cache GROUP BY 1 ORDER BY 1;

\echo ### exa_searches_by_day
SELECT (at AT TIME ZONE 'America/Bogota')::date AS day_bogota, count(*) AS calls, sum(searches) AS searches,
       round(sum(cost_usd), 4) AS cost_usd, count(*) FILTER (WHERE status <> 'ok') AS not_ok,
       count(DISTINCT fixture_id) AS fixtures
  FROM ai.usage WHERE at >= now() - interval '30 days' AND (provider = 'exa' OR purpose = 'web_search')
 GROUP BY 1 ORDER BY 1;

\echo ### cycles
SELECT kind, status, mode, budget_state, count(*) AS cycles, round(sum(cost_usd), 4) AS cost_usd,
       round(avg(extract(epoch FROM (finished_at - started_at)))::numeric, 1) AS avg_seconds,
       round(max(extract(epoch FROM (finished_at - started_at)))::numeric, 1) AS max_seconds
  FROM ai.cycles WHERE started_at >= now() - interval '30 days'
 GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;

\echo ### budget_alerts
SELECT month, threshold, created_at AT TIME ZONE 'UTC' AS created_utc, spent_usd, budget_usd FROM ai.budget_alerts ORDER BY month, threshold;

\echo ### usage_by_pass
-- Which pass each paid call belongs to (the pass of that match whose window holds the call) and how much of it was made
-- with the match four hours or more away: the part that could wait for a Batch result (Plan Maestro IA, Phase 0).
WITH u AS (
  SELECT id, at, purpose, tier, model, fixture_id, cost_usd
    FROM ai.usage
   WHERE at >= now() - interval '30 days' AND fixture_id IS NOT NULL AND provider <> 'exa'
), p AS (
  SELECT u.*, fp.pass, fp.kickoff_at
    FROM u LEFT JOIN LATERAL (
      SELECT pass, kickoff_at FROM ai.fixture_passes f
       WHERE f.fixture_id = u.fixture_id AND f.started_at - interval '1 minute' <= u.at AND f.finished_at + interval '1 minute' >= u.at
       ORDER BY f.started_at DESC LIMIT 1) fp ON true
)
SELECT purpose, tier, model, coalesce(pass, 'outside_a_pass') AS pass, count(*) AS calls, round(sum(cost_usd), 4) AS cost_usd,
       count(*) FILTER (WHERE kickoff_at - at >= interval '4 hours') AS calls_ko_4h_plus,
       round(sum(cost_usd) FILTER (WHERE kickoff_at - at >= interval '4 hours'), 4) AS cost_ko_4h_plus
  FROM p GROUP BY 1, 2, 3, 4 ORDER BY 6 DESC;

\echo ### cache_potential
-- Calls that came after another call of the same purpose and model: for the same fixture (the match data repeats) and
-- for any fixture (the instructions repeat), within 5 minutes (cache TTL by default) and within 1 hour (extended TTL).
WITH u AS (
  SELECT id, at, purpose, model, fixture_id, input_tokens, cost_usd,
         at - lag(at) OVER (PARTITION BY purpose, model, fixture_id ORDER BY at, id) AS gap_same_fixture,
         at - lag(at) OVER (PARTITION BY purpose, model ORDER BY at, id) AS gap_any
    FROM ai.usage
   WHERE at >= now() - interval '30 days' AND fixture_id IS NOT NULL AND provider <> 'exa'
)
SELECT purpose, model, count(*) AS calls, round(sum(cost_usd), 4) AS cost_usd, sum(input_tokens) AS input_tokens,
       count(*) FILTER (WHERE gap_same_fixture <= interval '5 minutes') AS same_fixture_5m,
       count(*) FILTER (WHERE gap_same_fixture <= interval '1 hour') AS same_fixture_1h,
       sum(input_tokens) FILTER (WHERE gap_same_fixture <= interval '5 minutes') AS tokens_same_fixture_5m,
       count(*) FILTER (WHERE gap_any <= interval '5 minutes') AS any_fixture_5m,
       count(*) FILTER (WHERE gap_any <= interval '1 hour') AS any_fixture_1h
  FROM u GROUP BY 1, 2 ORDER BY 4 DESC;

\echo ### review_calls_per_candidate_pass
-- Model reviews paid per fixture and pass: how many candidates of one match are reviewed in one pass.
WITH r AS (
  SELECT f.fixture_id, f.day, f.pass, count(*) AS calls
    FROM ai.fixture_passes f
    JOIN ai.usage u ON u.fixture_id = f.fixture_id AND u.purpose = 'pick_review'
                   AND u.at BETWEEN f.started_at - interval '1 minute' AND f.finished_at + interval '1 minute'
   WHERE f.day >= (now() - interval '30 days')::date
   GROUP BY 1, 2, 3
)
SELECT pass, count(*) AS fixture_passes_with_reviews, round(avg(calls), 2) AS avg_calls,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY calls) AS p50_calls,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY calls) AS p90_calls, max(calls) AS max_calls
  FROM r GROUP BY 1 ORDER BY 1;

\echo ### month_to_date_utc
SELECT date_trunc('month', now() AT TIME ZONE 'UTC')::date AS month,
       round(sum(cost_usd), 4) AS usage_usd,
       round(sum(cost_usd) FILTER (WHERE provider <> 'exa' AND purpose <> 'web_search'), 4) AS claude_usd,
       round(sum(cost_usd) FILTER (WHERE provider = 'exa' OR purpose = 'web_search'), 4) AS exa_usd,
       count(*) AS calls
  FROM ai.usage WHERE (at AT TIME ZONE 'UTC') >= date_trunc('month', now() AT TIME ZONE 'UTC');

ROLLBACK;
\echo ### end
