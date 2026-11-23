/// <reference types="bun" />
/**
 * Plan de correcciones UX, AP-A08: the flow's nodes take their state from the job ledger and the AI's runs, a stopped or failing
 * job turns its own node and no other, every job the worker opens belongs to a stage, and the diagram has its list.
 */
import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import type { JobHealth } from "@/lib/api/v1/types";
import type { AiRunRow } from "@/lib/api/v1/types_ai";
import { setLocale } from "@/lib/i18n";
import { PIPELINE_CATALOG, t } from "./pipelineText";
import { PipelineDiagram, PipelineList } from "./PipelineFlow";
import {
  ERROR_MINUTES,
  flowFigures,
  jobState,
  LATE_MINUTES,
  learningFigures,
  nodeFigures,
  STAGE_JOBS,
  STAGES,
  unmapped,
} from "./flowStages";

const NOW = Date.parse("2026-11-23T15:00:00Z");
const minutesAgo = (m: number) => new Date(NOW - m * 60000).toISOString();

function job(type: string, over: Partial<JobHealth> = {}): JobHealth {
  return {
    job_type: type,
    runs_24h: 10,
    failed_24h: 0,
    partial_24h: 0,
    api_calls_24h: 0,
    last_status: "completed",
    last_started_at: minutesAgo(3),
    last_success_at: minutesAgo(3),
    last_error: null,
    mean_duration_ms: 1000,
    next_run_at: new Date(NOW + 5 * 60000).toISOString(),
    ...over,
  };
}

function ai(status: AiRunRow["status"], at = minutesAgo(30)): AiRunRow {
  return {
    id: 1,
    kind: "daily_report",
    model: null,
    started_at: at,
    finished_at: at,
    status,
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: "0",
    tool_calls: 0,
    error: null,
    detail: {},
  };
}

const stateOf = (figures: ReturnType<typeof nodeFigures>, stage: (typeof STAGES)[number]) =>
  figures.find((n) => n.stage === stage)?.state;

describe("the state of a job", () => {
  test("a job whose last run ended badly is in error", () => {
    for (const status of ["failed", "aborted", "interrupted", "stale"]) {
      expect(jobState(job("odds_capture", { last_status: status }), NOW)).toBe("error");
    }
  });

  test("a job that is a little overdue is late; a long overdue one is in error", () => {
    const over = (m: number) => job("odds_capture", { next_run_at: minutesAgo(m) });
    expect(jobState(over(LATE_MINUTES - 1), NOW)).toBe("ok");
    expect(jobState(over(LATE_MINUTES + 1), NOW)).toBe("late");
    expect(jobState(over(ERROR_MINUTES + 1), NOW)).toBe("error");
  });

  test("failures or partial runs in the day make it late; a manual job (no next run) is judged by its last run", () => {
    expect(jobState(job("odds_capture", { failed_24h: 2 }), NOW)).toBe("late");
    expect(jobState(job("odds_capture", { partial_24h: 1 }), NOW)).toBe("late");
    expect(jobState(job("historical_backfill", { next_run_at: null }), NOW)).toBe("ok");
  });
});

describe("the nodes", () => {
  test("a stopped job turns its own node red and leaves the others as they were", () => {
    const jobs = [
      job("fixtures_sync"),
      job("quality_sweep"),
      job("feature_build", { last_status: "stale" }),
      job("pick_settlement"),
    ];
    const f = nodeFigures(jobs, NOW);
    expect(stateOf(f, "models")).toBe("error");
    expect(f.find((n) => n.stage === "models")?.worstJob).toBe("feature_build");
    expect(stateOf(f, "sources")).toBe("ok");
    expect(stateOf(f, "validation")).toBe("ok");
    expect(stateOf(f, "settlement")).toBe("ok");
  });

  test("a node with several jobs takes the worst one, and sums what ran and what failed", () => {
    const f = nodeFigures(
      [
        job("fixtures_sync", { runs_24h: 5, last_started_at: minutesAgo(10) }),
        job("odds_capture", { runs_24h: 7, failed_24h: 2, last_started_at: minutesAgo(1) }),
      ],
      NOW,
    );
    const sources = f.find((n) => n.stage === "sources");
    expect(sources?.state).toBe("late");
    expect(sources?.runs24h).toBe(12);
    expect(sources?.errors24h).toBe(2);
    expect(sources?.lastRunAt).toBe(minutesAgo(1));
    expect(sources?.worstJob).toBe("odds_capture");
  });

  test("a node the ledger has not seen says «sin datos»; publication is always closed", () => {
    const f = nodeFigures([], NOW);
    expect(f.map((n) => n.stage)).toEqual([...STAGES]);
    expect(stateOf(f, "models")).toBe("none");
    expect(stateOf(f, "publication")).toBe("closed");
  });

  test("learning reads the AI's runs", () => {
    expect(learningFigures([], NOW).state).toBe("none");
    expect(learningFigures([ai("ok")], NOW).state).toBe("ok");
    expect(learningFigures([ai("failed")], NOW).state).toBe("error");
    expect(learningFigures([ai("over_budget")], NOW).state).toBe("late");
    expect(learningFigures([ai("not_configured")], NOW).state).toBe("none");
    // the newest run decides
    expect(
      learningFigures([ai("failed", minutesAgo(600)), ai("ok", minutesAgo(5))], NOW).state,
    ).toBe("ok");
    expect(stateOf(flowFigures([], [ai("ok")], NOW), "learning")).toBe("ok");
  });

  test("every job the worker opens belongs to a stage, and none to two", () => {
    const all = Object.values(STAGE_JOBS).flat();
    expect(new Set(all).size).toBe(all.length);
    const path = join(
      import.meta.dir,
      "..",
      "..",
      "..",
      "backend",
      "apps",
      "worker",
      "scheduler.py",
    );
    if (!existsSync(path)) return; // the web checked out alone
    const source = readFileSync(path, "utf8");
    const block = /WORKER_JOB_TYPES = frozenset\(\{([\s\S]*?)\}\)/.exec(source)?.[1] ?? "";
    const worker = [...block.matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1] as string);
    expect(worker.length).toBeGreaterThan(40);
    expect(worker.filter((type) => !all.includes(type))).toEqual([]);
  });

  test("a job no stage claims is listed apart", () => {
    expect(unmapped([job("fixtures_sync"), job("a_job_from_tomorrow")])).toEqual([
      "a_job_from_tomorrow",
    ]);
  });
});

describe("the diagram and its list", () => {
  const figures = flowFigures(
    [job("feature_build", { last_status: "failed" }), job("fixtures_sync")],
    [],
    NOW,
  );

  test("both languages say every stage, every state and every line", () => {
    const flat = (o: Record<string, unknown>, p = ""): string[] =>
      Object.entries(o).flatMap(([k, v]) =>
        typeof v === "string" ? [p + k] : flat(v as Record<string, unknown>, `${p}${k}.`),
      );
    expect(flat(PIPELINE_CATALOG.es).sort()).toEqual(flat(PIPELINE_CATALOG.en).sort());
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const stage of STAGES) expect(t(`pipeline.stage.${stage}`)).not.toContain("pipeline.");
    }
    setLocale("es");
  });

  test("the list has the eleven stages in order, each a link with its state; the diagram is for wide screens only", () => {
    setLocale("es");
    const list = renderToStaticMarkup(<PipelineList figures={figures} onOpen={() => undefined} />);
    expect(list.match(/<li/g)?.length).toBe(11);
    expect(list.indexOf("Fuentes")).toBeLessThan(list.indexOf("Ingesta"));
    expect(list.indexOf("Selección")).toBeLessThan(list.indexOf("Aprendizaje"));
    expect(list).toContain('data-state="error"');
    expect(list).toContain("Cerrada");
    expect(list).toContain("md:hidden");
    const svg = renderToStaticMarkup(
      <PipelineDiagram figures={figures} onOpen={() => undefined} />,
    );
    expect(svg).toContain("hidden h-auto w-full md:block");
    expect(svg.match(/data-testid="flow-node-/g)?.length).toBe(11);
    expect(svg).toContain("Con error");
  });
});
