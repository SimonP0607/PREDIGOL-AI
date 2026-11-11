/** Small labels of the records: a result, a parlay's state, who chose it, evaluation mode. */
import {
  BadgeCheck,
  Ban,
  Bookmark,
  Check,
  FlaskConical,
  Hourglass,
  Undo2,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { toNumber } from "@/lib/i18n/format";
import type { MatchPhase } from "@/lib/api/v1/types";
import type { ParlayProgress, ParlayStatus, ResultStatus } from "@/lib/api/v1/types_records";
import { matchPhaseOf, minuteText, shortStatus } from "@/product/matches/status";
import { parlayOutcome, parlayTone, resultTone, type ParlayOutcome, type Tone } from "./model";
import { fmtUnits } from "./units";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import type { TermKey } from "@/lib/glossary";

/**
 * The seal of a result («Noche de partido», the system's sheet 4): a 28 px pill in Archivo. Won is the only filled one;
 * half a result is drawn as an outline of its whole; every seal says its state in words, and a result carries its icon.
 */
const TONE: Record<Tone, string> = {
  win: "bg-positive text-primary-foreground",
  loss: "bg-negative/[0.16] text-negative",
  neutral: "bg-foreground/[0.05] text-muted-foreground",
  pending: "bg-foreground/[0.07] text-foreground-soft",
  live: "text-primary ring-[1.5px] ring-inset ring-primary/55",
};

const BADGE =
  "inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 font-display text-xs font-bold";

const RESULT_SEAL: Record<ResultStatus, { tone: string; icon: LucideIcon }> = {
  PENDING: { tone: TONE.pending, icon: Hourglass },
  WIN: { tone: TONE.win, icon: Check },
  LOSS: { tone: TONE.loss, icon: X },
  PUSH: { tone: "bg-info/15 text-info", icon: Undo2 },
  VOID: { tone: TONE.neutral, icon: Ban },
  HALF_WIN: { tone: "text-positive ring-[1.5px] ring-inset ring-positive/60", icon: Check },
  HALF_LOSS: { tone: "text-negative ring-[1.5px] ring-inset ring-negative/50", icon: X },
};

/** The results a reader may not know (plan UX, A3): the badge's word opens its definition. Never inside a link: every
 * result badge sits beside a card's link, not in it. */
const RESULT_TERM: Partial<Record<ResultStatus, TermKey>> = {
  PUSH: "push",
  VOID: "void",
  HALF_WIN: "halfWon",
  HALF_LOSS: "halfLost",
};

export function ResultBadge({
  status,
  className,
}: {
  status: ResultStatus;
  className?: string | undefined;
}) {
  const term = RESULT_TERM[status];
  // an answer with a result this page does not know yet (an API ahead of the web) is drawn as its tone alone
  const seal = RESULT_SEAL[status] as (typeof RESULT_SEAL)[ResultStatus] | undefined;
  const Icon = seal?.icon;
  return (
    <span
      data-testid="result-badge"
      data-status={status}
      className={cn(BADGE, seal?.tone ?? TONE[resultTone(status)], className)}
    >
      {Icon ? <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" /> : null}
      {term ? (
        <GlossaryTerm term={term}>{t(`records.status.${status}`)}</GlossaryTerm>
      ) : (
        t(`records.status.${status}`)
      )}
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

const OUTCOME_TONE: Record<ParlayOutcome, Tone> = {
  scheduled: "pending",
  playing: "live",
  winning: "win",
  won: "win",
  lost: "loss",
  void: "neutral",
  building: "pending",
};

/** A parlay's result in one word: Por empezar, En juego, Va ganando, Ganado, Perdido - or Anulado. */
export function ParlayOutcomeBadge({
  status,
  progress,
  className,
}: {
  status: ParlayStatus;
  progress?: ParlayProgress | null | undefined;
  className?: string | undefined;
}) {
  const outcome = parlayOutcome(status, progress);
  return (
    <span
      data-testid="parlay-status"
      data-status={status}
      data-outcome={outcome}
      className={cn(BADGE, TONE[OUTCOME_TONE[outcome]], className)}
    >
      {outcome === "playing" ? (
        <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
      ) : null}
      {t(`records.outcome.${outcome}`)}
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
        className={cn(BADGE, TONE.live, "numeric", className)}
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
        phase === "finished" ? TONE.pending : "bg-warning/15 text-warning",
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
  kind = "pick",
  className,
}: {
  origin: "predigol" | "mine";
  /** A user's own record says what it is: «Tu selección» or «Tu parlay» (plan UX, A1). */
  kind?: "pick" | "parlay";
  className?: string | undefined;
}) {
  const Icon = origin === "predigol" ? BadgeCheck : Bookmark;
  return (
    <span
      data-testid={`origin-${origin}`}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 text-micro font-semibold uppercase tracking-wider",
        origin === "predigol" ? "text-gold" : "text-primary",
        className,
      )}
    >
      <Icon aria-hidden className="h-3 w-3" />
      {origin === "predigol"
        ? t("records.labels.predigolPick")
        : kind === "parlay"
          ? t("records.labels.mineParlay")
          : t("records.labels.mine")}
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
        "inline-flex h-6 shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-info-soft px-2.5 text-xs font-semibold text-info",
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
