import { Link } from "@tanstack/react-router";
import { t, translateOr } from "@/lib/i18n";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { cn } from "@/lib/utils";
import type {
  ComponentStatus,
  MatchSummary,
  RunSummary,
  Score,
  StatusGroup,
} from "@/lib/api/v1/types";

const groupTone: Record<StatusGroup, BadgeTone> = {
  scheduled: "info",
  live: "brand",
  finished: "neutral",
  postponed: "warning",
  cancelled: "negative",
};

export function StatusGroupBadge({
  match,
}: {
  match: Pick<MatchSummary, "status_group" | "status_short" | "awaiting_result">;
}) {
  if (match.awaiting_result) {
    return (
      <span title={t("admin.status.awaitingResultHelp")}>
        <StatusBadge tone="warning">{t("admin.status.awaitingResult")}</StatusBadge>
      </span>
    );
  }
  return (
    <StatusBadge tone={groupTone[match.status_group]}>
      {match.status_group === "finished" ? match.status_short : groupLabel(match.status_group)}
    </StatusBadge>
  );
}

function groupLabel(group: StatusGroup): string {
  switch (group) {
    case "scheduled":
      return t("common.status.scheduled");
    case "live":
      return t("common.status.live");
    case "finished":
      return t("common.status.finished");
    case "postponed":
      return t("common.status.postponed");
    case "cancelled":
      return t("common.status.cancelled");
  }
}

const componentTone: Record<ComponentStatus, BadgeTone> = {
  ok: "positive",
  degraded: "warning",
  down: "negative",
  unknown: "neutral",
};

export function ComponentStatusBadge({ status }: { status: ComponentStatus }) {
  return (
    <StatusBadge tone={componentTone[status]}>
      {translateOr(`admin.status.component.${status}`, status)}
    </StatusBadge>
  );
}

const runTone: Record<RunSummary["status"], BadgeTone> = {
  running: "info",
  completed: "positive",
  partial: "warning",
  failed: "negative",
  aborted: "neutral",
  interrupted: "warning",
  stale: "negative",
};

export function RunStatusBadge({ status }: { status: RunSummary["status"] }) {
  return (
    <StatusBadge tone={runTone[status]}>
      {translateOr(`admin.status.run.${status}`, status)}
    </StatusBadge>
  );
}

export function ScoreText({
  score,
  className,
}: {
  score: Score | null;
  className?: string | undefined;
}) {
  if (!score) return <span className={cn("text-subtle-foreground", className)}>–</span>;
  const extra =
    score.pen_home !== null && score.pen_away !== null
      ? ` (${score.pen_home}-${score.pen_away} p)`
      : score.et_home !== null && score.et_away !== null
        ? ` ${t("admin.status.aet")}`
        : "";
  return (
    <span className={cn("numeric font-medium", className)}>
      {score.home}–{score.away}
      {extra ? <span className="text-caption text-muted-foreground">{extra}</span> : null}
    </span>
  );
}

export function FixtureLink({
  match,
  className,
}: {
  match: MatchSummary;
  className?: string | undefined;
}) {
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(match.id) }}
      className={cn("flex min-w-0 items-center gap-1.5 hover:text-primary", className)}
    >
      <span className="truncate">{match.home.name}</span>
      <span className="shrink-0 text-subtle-foreground">{t("common.vs")}</span>
      <span className="truncate">{match.away.name}</span>
    </Link>
  );
}

export function LiveSourceNote({ children }: { children: React.ReactNode }) {
  return <p className="text-caption text-subtle-foreground">{children}</p>;
}

/** A label above a value that wraps - for values too long for a KeyValue row. */
export function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0 py-1.5">
      <dt className="text-caption uppercase tracking-wider text-subtle-foreground">{label}</dt>
      <dd className="numeric mt-0.5 text-xs text-foreground">{value}</dd>
    </div>
  );
}
