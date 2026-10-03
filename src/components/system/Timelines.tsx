import { Link } from "@tanstack/react-router";
import { t, translateOr } from "@/lib/i18n";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { EMPTY, dateTimeOf } from "@/lib/format";
import { DataStateBadge, StatusBadge } from "@/components/primitives/StatusBadge";
import type { LineageNode, TimelineEvent, TimelineState } from "@/types/domain";

const stateTone: Record<TimelineState, string> = {
  done: "bg-positive",
  pending: "bg-border-strong",
  skipped: "bg-warning",
  failed: "bg-negative",
};

function stateLabel(state: TimelineState): string {
  switch (state) {
    case "done":
      return t("admin.status.timeline.done");
    case "pending":
      return t("admin.status.timeline.pending");
    case "skipped":
      return t("admin.status.timeline.skipped");
    case "failed":
      return t("admin.status.timeline.failed");
  }
}

/** Fixture lifecycle: discovery → capture → prediction → kickoff. */
export function EventTimeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="relative space-y-4 pl-5">
      <span aria-hidden className="absolute left-[5px] top-1.5 bottom-1.5 w-px bg-border" />
      {events.map((e) => (
        <li key={e.id} className="relative">
          <span
            aria-hidden
            className={cn(
              "absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-card",
              stateTone[e.state],
            )}
          />
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm">{e.label}</span>
            <span className="numeric text-caption text-subtle-foreground">
              {e.at ? dateTimeOf(e.at) : `${EMPTY} ${stateLabel(e.state).toLowerCase()}`}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{e.detail}</p>
        </li>
      ))}
    </ol>
  );
}

export interface AuditStep {
  id: string;
  label: string;
  detail: string;
  reference: string;
  at: string | null;
  to?: { fixtureId: string } | undefined;
}

/** Navigable provenance chain: provider → payload → … → decision. */
export function AuditTimeline({ steps }: { steps: AuditStep[] }) {
  return (
    <ol className="space-y-2">
      {steps.map((s, i) => (
        <li key={s.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span className="numeric flex h-6 w-6 shrink-0 items-center justify-center rounded border border-border bg-elevated text-[0.6rem] text-muted-foreground">
              {i + 1}
            </span>
            {i < steps.length - 1 ? (
              <span aria-hidden className="my-1 w-px flex-1 bg-border" />
            ) : null}
          </div>
          <div className="min-w-0 flex-1 rounded-md border border-border bg-elevated/40 px-3 py-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm">{s.label}</span>
              <span className="numeric text-caption text-subtle-foreground">
                {s.at ? dateTimeOf(s.at) : EMPTY}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">{s.detail}</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <span className="numeric rounded border border-border px-1.5 py-0.5 text-caption text-muted-foreground">
                {s.reference}
              </span>
              {s.to ? (
                <Link
                  to="/matches/$fixtureId"
                  params={{ fixtureId: s.to.fixtureId }}
                  className="inline-flex items-center gap-0.5 text-caption text-primary hover:underline"
                >
                  {t("admin.ui.openRecord")}
                  <ChevronRight aria-hidden className="h-3 w-3" />
                </Link>
              ) : null}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Ingestion lineage with a per-node health state. */
export function LineageChain({ nodes }: { nodes: LineageNode[] }) {
  return (
    <ol className="grid gap-2 lg:grid-cols-5">
      {nodes.map((n, i) => (
        <li
          key={n.id}
          className="relative rounded-md border border-border bg-elevated/40 px-3 py-2.5"
        >
          <div className="flex items-start justify-between gap-2">
            <span className="text-sm">{n.label}</span>
            <DataStateBadge state={n.state} />
          </div>
          <p className="mt-1 text-caption text-subtle-foreground">{n.description}</p>
          <p className="mt-1.5 text-xs text-muted-foreground">{n.detail}</p>
          {i < nodes.length - 1 ? (
            <span
              aria-hidden
              className="absolute -bottom-2 left-1/2 z-10 -translate-x-1/2 text-subtle-foreground lg:-right-2.5 lg:bottom-auto lg:left-auto lg:top-1/2 lg:-translate-y-1/2 lg:translate-x-0"
            >
              <ChevronRight className="h-3.5 w-3.5 rotate-90 lg:rotate-0" />
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function SeverityBadge({ severity }: { severity: "critical" | "high" | "medium" | "low" }) {
  const tone =
    severity === "critical"
      ? "negative"
      : severity === "high"
        ? "warning"
        : severity === "medium"
          ? "info"
          : "neutral";
  return (
    <StatusBadge tone={tone}>
      {translateOr(`admin.status.severity.${severity}`, severity)}
    </StatusBadge>
  );
}
