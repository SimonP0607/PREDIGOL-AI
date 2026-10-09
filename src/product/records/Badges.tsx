/** Small labels of the records: a result, a parlay's state, who chose it, evaluation mode. */
import { BadgeCheck, Bookmark, FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { toNumber } from "@/lib/i18n/format";
import type { MatchPhase } from "@/lib/api/v1/types";
import type { ParlayStatus, ResultStatus } from "@/lib/api/v1/types_records";
import { matchPhaseOf, minuteText, shortStatus } from "@/product/matches/status";
import { parlayTone, resultTone, type Tone } from "./model";
import { fmtUnits } from "./units";

const TONE: Record<Tone, string> = {
  win: "border-positive/40 bg-positive-soft text-positive",
  loss: "border-negative/40 bg-negative-soft text-negative",
  neutral: "border-border-strong bg-muted text-muted-foreground",
  pending: "border-border-strong bg-elevated text-muted-foreground",
  live: "border-primary/40 bg-primary/10 text-primary",
};

const BADGE =
  "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold";

export function ResultBadge({
  status,
  className,
}: {
  status: ResultStatus;
  className?: string | undefined;
}) {
  return (
    <span
      data-testid="result-badge"
      data-status={status}
      className={cn(BADGE, TONE[resultTone(status)], className)}
    >
      {t(`records.status.${status}`)}
    </span>
  );
}

export function ParlayStatusBadge({
  status,
  className,
}: {
  status: ParlayStatus;
  className?: string | undefined;
}) {
  return (
    <span
      data-testid="parlay-status"
      data-status={status}
      className={cn(BADGE, TONE[parlayTone(status)], className)}
    >
      {t(`records.parlayStatus.${status}`)}
    </span>
  );
}

/**
 * What a record's match is doing while its result is still pending: "En juego · 63' · 1-0",
 * "Suspendido", "Terminado · liquidando", "Aplazado"... (fbi.core.match_state). Nothing before
 * kick-off, and nothing once the record is settled - the result badge says it then.
 */
export function MatchStateBadge({
  match,
  className,
}: {
  match: {
    kickoff_at: string;
    status_short?: string | null | undefined;
    phase?: MatchPhase | undefined;
    live_minute?: number | null | undefined;
    live_extra?: number | null | undefined;
    live_home?: number | null | undefined;
    live_away?: number | null | undefined;
  };
  className?: string | undefined;
}) {
  const phase = matchPhaseOf(match.status_short, match.kickoff_at, Date.now(), match.phase);
  if (phase === "scheduled" || phase === "unknown") return null;
  if (phase === "live") {
    const minute = minuteText(match.live_minute, match.live_extra);
    const clock =
      minute ??
      translateOr(`matches.clock.${shortStatus(match.status_short)}`, t("common.status.live"));
    const score =
      match.live_home !== null &&
      match.live_home !== undefined &&
      match.live_away !== null &&
      match.live_away !== undefined
        ? `${match.live_home}–${match.live_away}`
        : null;
    return (
      <span
        data-testid="match-state"
        data-phase={phase}
        className={cn(BADGE, TONE.live, "numeric gap-1", className)}
      >
        <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        {t("records.matchState.live")} · {clock}
        {score ? ` · ${score}` : ""}
      </span>
    );
  }
  const key = phase === "finished" ? "settling" : phase;
  return (
    <span
      data-testid="match-state"
      data-phase={phase}
      className={cn(
        BADGE,
        phase === "finished" ? TONE.pending : "border-warning/40 bg-warning/10 text-warning",
        className,
      )}
    >
      {t(`records.matchState.${key}`)}
    </span>
  );
}

/**
 * A record's result, or - while it is pending and its match has started - what the match is
 * doing (MatchStateBadge). ``hidePending``: nothing at all for a pending record of a match not
 * yet started (the compact rows).
 */
export function RecordState({
  status,
  match,
  hidePending = false,
  className,
}: {
  status: ResultStatus;
  match: Parameters<typeof MatchStateBadge>[0]["match"];
  hidePending?: boolean;
  className?: string | undefined;
}) {
  if (status === "PENDING") {
    const phase = matchPhaseOf(match.status_short, match.kickoff_at, Date.now(), match.phase);
    if (phase !== "scheduled" && phase !== "unknown") {
      return <MatchStateBadge match={match} className={className} />;
    }
    if (hidePending) return null;
  }
  return <ResultBadge status={status} className={className} />;
}

/** "PrediGol Pick" or "Guardado por mí": whose choice a record is. */
export function OriginLabel({
  origin,
  className,
}: {
  origin: "predigol" | "mine";
  className?: string | undefined;
}) {
  const Icon = origin === "predigol" ? BadgeCheck : Bookmark;
  return (
    <span
      data-testid={`origin-${origin}`}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 text-[0.7rem] font-semibold uppercase tracking-wider",
        origin === "predigol" ? "text-gold" : "text-primary",
        className,
      )}
    >
      <Icon aria-hidden className="h-3 w-3" />
      {origin === "predigol" ? t("records.labels.predigolPick") : t("records.labels.savedByMe")}
    </span>
  );
}

/** The owner's preview of the evaluation records: always labelled, never a recommendation. */
export function EvaluationBadge({ className }: { className?: string | undefined }) {
  return (
    <span
      data-testid="evaluation-badge"
      title={t("records.evaluation.body")}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-info/40 bg-info-soft px-2 py-0.5 text-[0.65rem] font-bold uppercase tracking-wider text-info",
        className,
      )}
    >
      <FlaskConical aria-hidden className="h-3 w-3" />
      {t("records.evaluation.badge")}
    </span>
  );
}

export function Units({
  value,
  className,
}: {
  value: string | number | null | undefined;
  className?: string | undefined;
}) {
  const n = toNumber(value);
  return (
    <span
      className={cn(
        "numeric font-semibold",
        n === null || n === 0 ? "text-muted-foreground" : n > 0 ? "text-positive" : "text-negative",
        className,
      )}
    >
      {fmtUnits(value)}
    </span>
  );
}
