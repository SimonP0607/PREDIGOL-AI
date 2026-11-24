/**
 * The flow of PrediGol, node by node (plan de correcciones UX, AP-A08): the ledger's job types gathered into the eleven stages
 * of the journey of a pick - Fuentes → Ingesta → Validación → Modelos → Calibración → Valor → Intelligence → Selección →
 * Publicación → Liquidación → Aprendizaje - and the state of each, read from ``GET /admin/ops/jobs`` (what ran, what failed,
 * when it last succeeded and when it runs next). Pure: no network, no clock of its own (``now`` comes in).
 *
 * The grouping is the owner's reading of the worker's ledger (apps/worker/scheduler.py, WORKER_JOB_TYPES); a job type the
 * map does not know yet is not drawn in any node and is counted apart, so a new job is never silently hidden.
 */
import type { JobHealth } from "@/lib/api/v1/types";
import type { AiRunRow } from "@/lib/api/v1/types_ai";

export const STAGES = [
  "sources",
  "ingest",
  "validation",
  "models",
  "calibration",
  "value",
  "intelligence",
  "selection",
  "publication",
  "settlement",
  "learning",
] as const;
export type Stage = (typeof STAGES)[number];

/** The worker's job types of each stage. «Publicación» has none: it is closed, and says so. */
export const STAGE_JOBS: Readonly<Record<Stage, readonly string[]>> = {
  sources: [
    "fixtures_sync",
    "results_sync",
    "odds_capture",
    "live_odds_capture",
    "live_match_capture",
    "reference_refresh",
    "catalogue_refresh",
    "post_match_detail",
    "historical_backfill",
    "signals_ingest",
  ],
  ingest: [
    "odds_quotes_extract",
    "odds_book_build",
    "odds_book_refresh",
    "stats_documents",
    "player_history",
    "referee_identity",
    "competition_structure",
    "availability_refresh",
    "lineup_watch",
    "context_refresh",
    "context_due",
    "results_repair",
    "final_prematch",
  ],
  validation: [
    "quality_sweep",
    "historical_validation",
    "synthetic_journey",
    "availability_shadow",
  ],
  models: [
    "feature_build",
    "elo_refresh",
    "family_forecasts",
    "match_knowledge",
    "player_forecast_shadow",
    "lineup_estimate_shadow",
    "scenarios_shadow",
  ],
  calibration: ["eval_cycle_shadow", "eval_cycle_e3"],
  value: ["decision_v2_shadow", "parlay_v6_shadow"],
  intelligence: [
    "research_monitor",
    "research_v2",
    "news_stories",
    "council_reduced_shadow",
    "source_credibility_shadow",
    "chronicle_v4",
    "chronicle_update",
    "chronicle_review",
    "chronicle_review_v2",
    "user_narrative",
    "lifecycle_shadow",
  ],
  selection: ["pick_pipeline", "selection_eval_shadow"],
  publication: [],
  settlement: ["pick_settlement", "selection_settle_shadow"],
  learning: [],
};

/** Where a tap on each node leads. The learning node opens the day's learning on this very page. */
export const STAGE_LINK: Readonly<Record<Stage, { to: string; hash?: string }>> = {
  sources: { to: "/admin/operation" },
  ingest: { to: "/admin/data-quality" },
  validation: { to: "/admin/data-truth" },
  models: { to: "/admin/models" },
  calibration: { to: "/admin/learning", hash: "tab=calibration" },
  value: { to: "/admin/intelligence" },
  intelligence: { to: "/admin/intelligence" },
  selection: { to: "/admin/picks" },
  publication: { to: "/admin/picks" },
  settlement: { to: "/admin/picks" },
  learning: { to: "/admin/learning", hash: "tab=learned" },
};

export type NodeState = "ok" | "late" | "error" | "none" | "closed";

/** A job overdue by more than this (its next run, from the worker's last beat, is already past) is late, then in error. */
export const LATE_MINUTES = 15;
export const ERROR_MINUTES = 60;
const BAD_STATUS = new Set(["failed", "aborted", "interrupted", "stale"]);

export interface NodeFigures {
  stage: Stage;
  state: NodeState;
  /** The most recent start among the node's jobs. */
  lastRunAt: string | null;
  /** Runs and failures in the last 24 hours, summed over the node's jobs. */
  runs24h: number;
  errors24h: number;
  /** The jobs of the node the ledger has seen. */
  jobs: number;
  /** The job that puts the node in the state it is in (the worst one), when it is not «ok». */
  worstJob: string | null;
}

const RANK: Readonly<Record<NodeState, number>> = { none: 0, ok: 1, late: 2, error: 3, closed: 0 };

/** The state of one job: error when its last run did not end well or it is long overdue; late when it failed or was partial
 *  in the day, or is a little overdue. */
export function jobState(job: JobHealth, now: number): NodeState {
  if (job.last_status && BAD_STATUS.has(job.last_status)) return "error";
  if (job.next_run_at) {
    const overdue = (now - Date.parse(job.next_run_at)) / 60000;
    if (overdue > ERROR_MINUTES) return "error";
    if (overdue > LATE_MINUTES) return "late";
  }
  if (job.failed_24h > 0 || job.partial_24h > 0) return "late";
  return "ok";
}

export function nodeFigures(jobs: readonly JobHealth[], now: number): NodeFigures[] {
  const byType = new Map(jobs.map((j) => [j.job_type, j]));
  return STAGES.map((stage) => {
    if (stage === "publication") {
      return {
        stage,
        state: "closed",
        lastRunAt: null,
        runs24h: 0,
        errors24h: 0,
        jobs: 0,
        worstJob: null,
      };
    }
    const seen = STAGE_JOBS[stage].flatMap((type) => {
      const j = byType.get(type);
      return j ? [j] : [];
    });
    let state: NodeState = "none";
    let worstJob: string | null = null;
    for (const j of seen) {
      const s = jobState(j, now);
      if (RANK[s] > RANK[state]) {
        state = s;
        worstJob = s === "ok" ? null : j.job_type;
      }
    }
    const last = seen
      .map((j) => j.last_started_at)
      .filter((v): v is string => v !== null)
      .sort()
      .at(-1);
    return {
      stage,
      state,
      lastRunAt: last ?? null,
      runs24h: seen.reduce((n, j) => n + j.runs_24h, 0),
      errors24h: seen.reduce((n, j) => n + j.failed_24h, 0),
      jobs: seen.length,
      worstJob,
    };
  });
}

/** «Aprendizaje» has no job of its own in the ledger: it is the AI's runs (the day's report, the review of the picks). A run that
 *  failed is an error; one stopped by the budget is late; an AI that is not configured has nothing to say yet. */
export function learningFigures(runs: readonly AiRunRow[], now: number): NodeFigures {
  const sorted = [...runs].sort((a, b) => b.started_at.localeCompare(a.started_at));
  const day = runs.filter((r) => now - Date.parse(r.started_at) < 24 * 3600 * 1000);
  const last = sorted[0];
  const state: NodeState = !last
    ? "none"
    : last.status === "failed"
      ? "error"
      : last.status === "over_budget"
        ? "late"
        : last.status === "not_configured"
          ? "none"
          : "ok";
  return {
    stage: "learning",
    state,
    lastRunAt: last?.started_at ?? null,
    runs24h: day.length,
    errors24h: day.filter((r) => r.status === "failed").length,
    jobs: runs.length ? 1 : 0,
    worstJob: state === "error" || state === "late" ? (last?.kind ?? null) : null,
  };
}

/** Every node of the flow, from the ledger and the AI's runs. */
export function flowFigures(
  jobs: readonly JobHealth[],
  aiRuns: readonly AiRunRow[],
  now: number,
): NodeFigures[] {
  return nodeFigures(jobs, now).map((n) =>
    n.stage === "learning" ? learningFigures(aiRuns, now) : n,
  );
}

/** The ledger's job types no stage claims: shown apart so a new job is never hidden. */
export function unmapped(jobs: readonly JobHealth[]): string[] {
  const known = new Set(Object.values(STAGE_JOBS).flat());
  return jobs.map((j) => j.job_type).filter((type) => !known.has(type));
}
