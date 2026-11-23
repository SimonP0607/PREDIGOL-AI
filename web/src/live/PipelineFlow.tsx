/**
 * The path of a pick, as a diagram (plan de correcciones UX, AP-A08; sheet AD12; decision D13's «Noche de partido» look): eleven
 * stages from the data outside to what PrediGol learns, each with its state (up to date, late, in error, no data), the last run,
 * how many ran and how many failed. A tap leads to the stage's own page. It refreshes every 60 s and changes nothing: it only reads
 * the job ledger and the AI's runs. Where the diagram does not fit (a phone) the same stages are a list - the list is also what a
 * screen reader and the keyboard walk - and one stage failing to read never blanks the page: the failure is said in words.
 */
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Clock,
  Lock,
  RefreshCw,
  XOctagon,
} from "lucide-react";
import type { ReactNode } from "react";
import { v1 } from "@/lib/api/v1/client";
import { formatDateTime, formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import {
  flowFigures,
  STAGE_LINK,
  unmapped,
  type NodeFigures,
  type NodeState,
  type Stage,
} from "./flowStages";
import { t } from "./pipelineText";

const REFRESH_MS = 60_000;

const STAGE_NAME: Readonly<Record<Stage, string>> = {
  sources: "pipeline.stage.sources",
  ingest: "pipeline.stage.ingest",
  validation: "pipeline.stage.validation",
  models: "pipeline.stage.models",
  calibration: "pipeline.stage.calibration",
  value: "pipeline.stage.value",
  intelligence: "pipeline.stage.intelligence",
  selection: "pipeline.stage.selection",
  publication: "pipeline.stage.publication",
  settlement: "pipeline.stage.settlement",
  learning: "pipeline.stage.learning",
};
const STAGE_WHAT: Readonly<Record<Stage, string>> = {
  sources: "pipeline.what.sources",
  ingest: "pipeline.what.ingest",
  validation: "pipeline.what.validation",
  models: "pipeline.what.models",
  calibration: "pipeline.what.calibration",
  value: "pipeline.what.value",
  intelligence: "pipeline.what.intelligence",
  selection: "pipeline.what.selection",
  publication: "pipeline.what.publication",
  settlement: "pipeline.what.settlement",
  learning: "pipeline.what.learning",
};
const STATE_WORD: Readonly<Record<NodeState, string>> = {
  ok: "pipeline.state.ok",
  late: "pipeline.state.late",
  error: "pipeline.state.error",
  none: "pipeline.state.none",
  closed: "pipeline.state.closed",
};

/** The colour of a state: a token of the system, so light and dark both read. The word and the symbol say it too. */
const STATE_VAR: Readonly<Record<NodeState, string>> = {
  ok: "var(--color-positive)",
  late: "var(--color-warning)",
  error: "var(--color-negative)",
  none: "var(--color-border-strong)",
  closed: "var(--color-gold)",
};
const STATE_TEXT: Readonly<Record<NodeState, string>> = {
  ok: "text-positive",
  late: "text-warning",
  error: "text-negative",
  none: "text-muted-foreground",
  closed: "text-gold",
};

function StateIcon({ state, className }: { state: NodeState; className?: string }): ReactNode {
  const c = cn("h-4 w-4 shrink-0", className);
  if (state === "ok") return <CheckCircle2 aria-hidden className={c} />;
  if (state === "late") return <Clock aria-hidden className={c} />;
  if (state === "error") return <XOctagon aria-hidden className={c} />;
  if (state === "closed") return <Lock aria-hidden className={c} />;
  return <CircleDashed aria-hidden className={c} />;
}

/** What a stage says about itself, in one line: the last run, or that it has none. */
function lastLine(n: NodeFigures): string {
  if (n.state === "closed") return t("pipeline.closedNote");
  return n.lastRunAt
    ? t("pipeline.last", { when: formatDateTime(n.lastRunAt) })
    : t("pipeline.never");
}

function countsLine(n: NodeFigures): string | null {
  return n.state === "closed" || n.state === "none"
    ? null
    : t("pipeline.counts", { runs: n.runs24h, errors: n.errors24h });
}

// The diagram's grid: four columns, three rows, read as a snake (left to right, right to left, left to right).
const W = 200;
const H = 104;
const GAP = 40;
const COL = (c: number) => 20 + c * (W + GAP);
const ROW = (r: number) => 12 + r * (H + 44);
const SLOT: readonly { col: number; row: number }[] = [
  { col: 0, row: 0 },
  { col: 1, row: 0 },
  { col: 2, row: 0 },
  { col: 3, row: 0 },
  { col: 3, row: 1 },
  { col: 2, row: 1 },
  { col: 1, row: 1 },
  { col: 0, row: 1 },
  { col: 0, row: 2 },
  { col: 1, row: 2 },
  { col: 2, row: 2 },
];

function arrows(): ReactNode[] {
  return SLOT.slice(0, -1).map((a, i) => {
    const b = SLOT[i + 1] as { col: number; row: number };
    const ax = COL(a.col) + W / 2;
    const ay = ROW(a.row) + H / 2;
    const bx = COL(b.col) + W / 2;
    const by = ROW(b.row) + H / 2;
    let d: string;
    if (a.row === b.row) {
      const dir = b.col > a.col ? 1 : -1;
      d = `M ${ax + (dir * W) / 2} ${ay} L ${bx - (dir * W) / 2} ${by}`;
    } else {
      d = `M ${ax} ${ay + H / 2} L ${bx} ${by - H / 2}`;
    }
    return (
      <path
        key={i}
        d={d}
        fill="none"
        stroke="var(--color-border-strong)"
        strokeWidth={2}
        markerEnd="url(#flow-arrow)"
      />
    );
  });
}

function Node({
  n,
  slot,
  onOpen,
}: {
  n: NodeFigures;
  slot: { col: number; row: number };
  onOpen: () => void;
}) {
  const x = COL(slot.col);
  const y = ROW(slot.row);
  const name = t(STAGE_NAME[n.stage]);
  const word = t(STATE_WORD[n.state]);
  return (
    <a
      href={STAGE_LINK[n.stage].to}
      onClick={(e) => {
        e.preventDefault();
        onOpen();
      }}
      aria-label={`${name}: ${word}. ${lastLine(n)}`}
      data-testid={`flow-node-${n.stage}`}
      data-state={n.state}
      className="outline-none [&:focus-visible>rect]:stroke-[4]"
    >
      <rect
        x={x}
        y={y}
        width={W}
        height={H}
        rx={14}
        fill="var(--color-card)"
        stroke={STATE_VAR[n.state]}
        strokeWidth={2.5}
      />
      <rect x={x} y={y} width={8} height={H} rx={4} fill={STATE_VAR[n.state]} />
      <text x={x + 22} y={y + 30} fontSize={18} fontWeight={700} fill="var(--color-foreground)">
        {name}
      </text>
      <text
        x={x + 22}
        y={y + 54}
        fontSize={13}
        fill={n.state === "none" ? "var(--color-muted-foreground)" : STATE_VAR[n.state]}
        fontWeight={700}
      >
        {word}
      </text>
      <text x={x + 22} y={y + 76} fontSize={12} fill="var(--color-muted-foreground)">
        {n.state === "closed"
          ? t("pipeline.what.publication")
          : n.lastRunAt
            ? formatDateTime(n.lastRunAt)
            : t("pipeline.never")}
      </text>
      <text x={x + 22} y={y + 94} fontSize={12} fill="var(--color-muted-foreground)">
        {n.state === "closed" || n.state === "none"
          ? ""
          : t("pipeline.short", { runs: n.runs24h, errors: n.errors24h })}
      </text>
    </a>
  );
}

export function PipelineDiagram({
  figures,
  onOpen,
}: {
  figures: readonly NodeFigures[];
  onOpen: (stage: Stage) => void;
}) {
  return (
    <svg
      viewBox="0 0 960 420"
      role="group"
      aria-label={t("pipeline.diagram")}
      className="hidden h-auto w-full md:block"
      data-testid="flow-diagram"
    >
      <defs>
        <marker
          id="flow-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--color-border-strong)" />
        </marker>
      </defs>
      {arrows()}
      {figures.map((n, i) => (
        <Node
          key={n.stage}
          n={n}
          slot={SLOT[i] as { col: number; row: number }}
          onOpen={() => onOpen(n.stage)}
        />
      ))}
    </svg>
  );
}

export function PipelineList({
  figures,
  onOpen,
}: {
  figures: readonly NodeFigures[];
  onOpen: (stage: Stage) => void;
}) {
  return (
    <ol className="space-y-2 md:hidden" aria-label={t("pipeline.list")} data-testid="flow-list">
      {figures.map((n, i) => (
        <li key={n.stage}>
          <a
            href={STAGE_LINK[n.stage].to}
            onClick={(e) => {
              e.preventDefault();
              onOpen(n.stage);
            }}
            data-testid={`flow-item-${n.stage}`}
            data-state={n.state}
            className="surface-panel flex min-h-14 items-start gap-3 rounded-card border-l-4 p-3"
            style={{ borderLeftColor: STATE_VAR[n.state] }}
          >
            <span className="numeric mt-0.5 w-5 shrink-0 text-caption text-muted-foreground">
              {i + 1}
            </span>
            <span className="min-w-0 flex-1 space-y-0.5">
              <span className="flex flex-wrap items-center gap-x-2 text-sm font-semibold">
                {t(STAGE_NAME[n.stage])}
                <span
                  className={cn(
                    "inline-flex items-center gap-1 text-xs font-bold",
                    STATE_TEXT[n.state],
                  )}
                >
                  <StateIcon state={n.state} className="h-3.5 w-3.5" />
                  {t(STATE_WORD[n.state])}
                </span>
              </span>
              <span className="block text-caption text-muted-foreground">
                {t(STAGE_WHAT[n.stage])}
              </span>
              <span className="block text-caption text-muted-foreground">{lastLine(n)}</span>
              {countsLine(n) ? (
                <span className="block text-caption text-muted-foreground">{countsLine(n)}</span>
              ) : null}
              {n.worstJob ? (
                <span className="block text-caption text-muted-foreground">
                  {t("pipeline.worst", { job: n.worstJob })}
                </span>
              ) : null}
            </span>
          </a>
        </li>
      ))}
    </ol>
  );
}

export function PipelineFlow() {
  const navigate = useNavigate();
  const jobs = useQuery({
    queryKey: ["admin", "pipeline", "jobs"],
    queryFn: v1.jobs,
    refetchInterval: REFRESH_MS,
  });
  const ai = useQuery({
    queryKey: ["admin", "pipeline", "ai"],
    queryFn: v1.aiStatus,
    refetchInterval: REFRESH_MS,
  });
  const open = (stage: Stage) => {
    const link = STAGE_LINK[stage];
    void navigate(link.hash ? { to: link.to as never, hash: link.hash } : { to: link.to as never });
  };
  const rows = jobs.data?.data ?? [];
  const figures =
    jobs.isSuccess || jobs.data
      ? flowFigures(rows, ai.data?.data?.last_runs ?? [], Date.now())
      : null;
  const strays = unmapped(rows);
  return (
    <section
      aria-labelledby="pipeline-title"
      className="surface-panel space-y-3 rounded-card p-4"
      data-testid="pipeline-flow"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <h2 id="pipeline-title" className="text-title">
            {t("pipeline.title")}
          </h2>
          <p className="max-w-3xl text-sm text-muted-foreground">{t("pipeline.intro")}</p>
        </div>
        <button
          type="button"
          onClick={() => {
            void jobs.refetch();
            void ai.refetch();
          }}
          aria-label={t("pipeline.refresh")}
          className="tap relative rounded-md border border-border-strong p-2 hover:bg-elevated"
        >
          <RefreshCw
            aria-hidden
            className={cn("h-4 w-4", (jobs.isFetching || ai.isFetching) && "animate-spin")}
          />
        </button>
      </div>
      {jobs.isError && !figures ? (
        <p
          className="flex items-center gap-2 text-sm text-negative"
          role="alert"
          data-testid="flow-failed"
        >
          <AlertTriangle aria-hidden className="h-4 w-4" />
          {t("pipeline.failed")}
        </p>
      ) : !figures ? (
        <p className="text-sm text-muted-foreground">{t("pipeline.loading")}</p>
      ) : (
        <>
          <PipelineDiagram figures={figures} onOpen={open} />
          <PipelineList figures={figures} onOpen={open} />
          {strays.length ? (
            <p className="text-caption text-muted-foreground" data-testid="flow-unmapped">
              {t("pipeline.unmapped", { jobs: strays.join(", ") })}
            </p>
          ) : null}
          <p className="text-caption text-muted-foreground">
            {t("pipeline.refreshed", { time: formatTime(jobs.dataUpdatedAt) })}
          </p>
        </>
      )}
    </section>
  );
}
