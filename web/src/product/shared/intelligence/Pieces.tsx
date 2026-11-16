/**
 * The eight pieces that PrediGol Intelligence adds to «Noche de partido» (plan maestro unificado, section 5.3, UX-140).
 * Each extends a primitive the system already has - the 24 px tag, the banner, the timeline, the crest - and none
 * computes anything: they print what the backend's contract says, in its words, with its seal.
 */
import type { ReactNode } from "react";
import {
  Ban,
  CircleCheck,
  CircleDashed,
  CircleDot,
  Clock,
  EyeOff,
  FileCheck2,
  Flag,
  Lock,
  Megaphone,
  MessageSquareQuote,
  Newspaper,
  Radio,
  Search,
  ShieldCheck,
  Split,
  Timer,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { t } from "@/lib/i18n";
import { pct } from "@/lib/format";
import { formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { Banner } from "@/components/ui/banner";
import { TeamLogo, PlayerPhoto } from "@/components/football/Logos";
import {
  clampShare,
  type Calibration,
  type Confidence,
  type Confirmation,
  type Evaluation,
  type Lifecycle,
  type StepState,
} from "./model";

/* ------------------------------------------------------------------ LifecycleChip */

const LIFECYCLE_LOOK: Record<Lifecycle, { tone: BadgeTone; icon: LucideIcon }> = {
  detected: { tone: "neutral", icon: CircleDot },
  researching: { tone: "info", icon: Search },
  evaluating: { tone: "info", icon: CircleDashed },
  awaiting_lineups: { tone: "warning", icon: Timer },
  shadow_confirmed: { tone: "brand", icon: EyeOff },
  withdrawn: { tone: "negative", icon: Undo2 },
  discarded: { tone: "neutral", icon: Ban },
  in_play: { tone: "positive", icon: Radio },
  settled: { tone: "neutral", icon: Flag },
  evaluated: { tone: "positive", icon: FileCheck2 },
};

/** The state of a selection in its life, as the contract names it: a word and an icon, never the colour alone. */
export function LifecycleChip({
  state,
  className,
}: {
  state: Lifecycle;
  className?: string | undefined;
}) {
  const look = LIFECYCLE_LOOK[state];
  const Icon = look.icon;
  return (
    <StatusBadge tone={look.tone} dot={false} className={className}>
      <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span data-testid="lifecycle-chip" data-state={state}>
        {t(`intelligence.lifecycle.${state}`)}
      </span>
    </StatusBadge>
  );
}

/* ------------------------------------------------------------------ ConfirmationLevel */

const CONFIRMATION_LOOK: Record<Confirmation, { tone: BadgeTone; icon: LucideIcon }> = {
  official: { tone: "positive", icon: ShieldCheck },
  confirmed: { tone: "info", icon: CircleCheck },
  statement: { tone: "neutral", icon: MessageSquareQuote },
  single_source: { tone: "warning", icon: Newspaper },
  contradictory: { tone: "negative", icon: Split },
  unconfirmed: { tone: "neutral", icon: Megaphone },
};

/**
 * How sure a fact is (decision D-04): official, confirmed by two origins, a statement, one outlet, contradictory or not
 * confirmed. The last ones are never told as facts - the level is always on show next to the item.
 */
export function ConfirmationLevel({
  level,
  className,
}: {
  level: Confirmation;
  className?: string | undefined;
}) {
  const look = CONFIRMATION_LOOK[level];
  const Icon = look.icon;
  return (
    <StatusBadge tone={look.tone} dot={false} className={className}>
      <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span data-testid="confirmation-level" data-level={level}>
        {t(`intelligence.confirmation.${level}`)}
      </span>
    </StatusBadge>
  );
}

/* ------------------------------------------------------------------ ProbabilityLine */

/**
 * One outcome's probability as the contract gives it (contract rules 1 and 3): the figure, its bar and its seal -
 * calibrated or not, and when. It prints; it never computes, rounds the contract's figure another way or picks between
 * two figures.
 */
export function ProbabilityLine({
  label,
  value,
  calibration,
  at,
  confidence,
  emphasis = false,
}: {
  label: string;
  /** The contract's probability, 0 to 1. */
  value: number;
  calibration: Calibration;
  /** When the figure was computed (ISO 8601). */
  at?: string | null | undefined;
  confidence?: Confidence | null | undefined;
  /** The leading outcome of its market. */
  emphasis?: boolean;
}) {
  const share = clampShare(value);
  return (
    <div
      data-testid="probability-line"
      data-calibration={calibration}
      className="min-w-0 space-y-1.5"
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn("min-w-0 truncate text-sm", emphasis && "font-semibold")}>{label}</span>
        <span className={cn("numeric shrink-0", emphasis ? "numeric-lg" : "text-sm font-semibold")}>
          {pct(share, 0)}
        </span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
        aria-valuetext={pct(share, 0)}
        className="h-1.5 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn("h-full rounded-full", emphasis ? "bg-primary" : "bg-primary/60")}
          style={{ width: `${share * 100}%` }}
        />
      </div>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption text-muted-foreground">
        <span
          className={cn(
            "inline-flex items-center gap-1",
            calibration === "uncalibrated" && "font-semibold text-warning",
          )}
        >
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
          {t(`intelligence.calibration.${calibration}`)}
        </span>
        {at ? <span>{formatRelative(at)}</span> : null}
        {confidence ? <span>{t(`intelligence.confidence.${confidence}`)}</span> : null}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ EvaluationSteps */

export interface EvaluationStep {
  key: Evaluation;
  state: StepState;
  /** When it ran, or when it is expected (ISO 8601). */
  at?: string | null | undefined;
}

/** The four readings of a match as four tiles - the shape of «Pronóstico · Valor · Pick» (UX-137). */
export function EvaluationSteps({ steps }: { steps: readonly EvaluationStep[] }) {
  return (
    <div className="@container">
      <ol
        aria-label={t("intelligence.evaluations.title")}
        data-testid="evaluation-steps"
        className="grid grid-cols-1 gap-2 @[26rem]:grid-cols-2 @[44rem]:grid-cols-4"
      >
        {steps.map((s) => (
          <li
            key={s.key}
            data-state={s.state}
            aria-current={s.state === "current" ? "step" : undefined}
            className={cn(
              "card-surface flex min-w-0 items-center gap-3 rounded-card p-3",
              s.state === "current" && "border-primary/50",
              (s.state === "pending" || s.state === "skipped") && "opacity-75",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "numeric flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                s.state === "done" || s.state === "current"
                  ? "bg-primary-soft text-primary"
                  : "bg-foreground/[0.07] text-muted-foreground",
              )}
            >
              {s.key}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold">
                {t(`intelligence.evaluations.${s.key}`)}
              </span>
              <span className="block text-caption text-muted-foreground">
                {t(`intelligence.evaluations.state.${s.state}`)}
                {s.at ? ` · ${formatRelative(s.at)}` : ""}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ------------------------------------------------------------------ VersionHistory */

export interface Version {
  id: string;
  /** «E2 · Por novedad», as the contract names it. */
  label: string;
  at: string;
  /** What changed in this version. */
  detail?: string | null | undefined;
  state?: Lifecycle | null | undefined;
}

/**
 * Every evaluation adds a version and none is rewritten (contract rule 5): newest first, each with what changed. The
 * line and dots are the ones of the fixture's timeline.
 */
export function VersionHistory({ versions }: { versions: readonly Version[] }) {
  if (versions.length === 0) return null;
  return (
    <ol data-testid="version-history" className="relative space-y-4 pl-5">
      <span aria-hidden className="absolute bottom-1.5 left-[5px] top-1.5 w-px bg-border" />
      {versions.map((v, i) => (
        <li key={v.id} className="relative">
          <span
            aria-hidden
            className={cn(
              "absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-card",
              i === 0 ? "bg-primary" : "bg-border-strong",
            )}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="min-w-0 text-sm font-semibold">{v.label}</span>
            <span className="numeric text-caption text-subtle-foreground">
              {formatRelative(v.at)}
            </span>
          </div>
          {v.detail ? <p className="mt-0.5 text-small text-muted-foreground">{v.detail}</p> : null}
          {v.state ? <LifecycleChip state={v.state} className="mt-1.5" /> : null}
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------------ SourceLevelList */

export interface SourcedFact {
  id: string;
  text: string;
  level: Confirmation;
  /** Who said it: the outlet, the club, the league. */
  sources: readonly { name: string; url?: string | null | undefined }[];
  publishedAt?: string | null | undefined;
  /** What it brought to the reading («activó la 2.ª evaluación»). */
  contribution?: string | null | undefined;
}

/** The facts behind an analysis, grouped by how sure they are (maqueta 16) - the sources' own block, extended. */
export function SourceLevelList({ facts }: { facts: readonly SourcedFact[] }) {
  if (facts.length === 0) return null;
  const groups = new Map<Confirmation, SourcedFact[]>();
  for (const f of facts) groups.set(f.level, [...(groups.get(f.level) ?? []), f]);
  return (
    <div data-testid="source-level-list" className="space-y-5">
      {[...groups.entries()].map(([level, items]) => (
        <section
          key={level}
          aria-label={t(`intelligence.confirmation.${level}`)}
          className="space-y-2.5"
        >
          <div className="flex items-center justify-between gap-2">
            <ConfirmationLevel level={level} />
            <span className="numeric text-caption text-muted-foreground">{items.length}</span>
          </div>
          <ul className="divide-y divide-border rounded-card border border-border">
            {items.map((f) => (
              <li key={f.id} className="space-y-1 p-3">
                <p className="text-sm">{f.text}</p>
                {f.contribution ? (
                  <p className="text-small text-muted-foreground">{f.contribution}</p>
                ) : null}
                <p className="flex flex-wrap gap-x-3 gap-y-1 text-caption text-subtle-foreground">
                  {f.sources.map((s) =>
                    s.url ? (
                      <a
                        key={s.name}
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        className="font-semibold text-primary underline-offset-2 hover:underline"
                      >
                        {s.name}
                      </a>
                    ) : (
                      <span key={s.name} className="font-semibold">
                        {s.name}
                      </span>
                    ),
                  )}
                  {f.publishedAt ? (
                    <span className="inline-flex items-center gap-1">
                      <Clock aria-hidden className="h-3 w-3" />
                      {formatRelative(f.publishedAt)}
                    </span>
                  ) : null}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ PrivateBand */

/**
 * On top of every private view (plan, section 6): «Evaluación privada · no visible para usuarios». It marks; it does not
 * protect - the server only sends private data to the owner.
 */
export function PrivateBand({ children }: { children?: ReactNode }) {
  return (
    <Banner tone="warning" icon={Lock} data-testid="private-band" role="note">
      <p className="font-semibold">{t("intelligence.private.title")}</p>
      <p className="text-muted-foreground">{children ?? t("intelligence.private.body")}</p>
    </Banner>
  );
}

/* ------------------------------------------------------------------ EntityHeader */

/**
 * The head of a club, a national team or a player (maquetas 11-13), built from the match header's crest. A player never
 * gets a photo until the rights are settled: his initials stand in.
 */
export function EntityHeader({
  kind,
  name,
  logo,
  subtitle,
  facts,
  actions,
}: {
  kind: "club" | "nation" | "player";
  name: string;
  logo?: string | null | undefined;
  subtitle?: string | null | undefined;
  /** Short facts under the name: the league, the stadium, the position. */
  facts?: readonly string[] | undefined;
  /** The follow star, the bell. */
  actions?: ReactNode;
}) {
  return (
    <header
      data-testid="entity-header"
      data-kind={kind}
      className="flex min-w-0 items-center gap-4"
    >
      {kind === "player" ? (
        <PlayerPhoto src={null} name={name} size={64} className="rounded-full" />
      ) : (
        <TeamLogo src={logo} name={name} size={64} />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-label text-muted-foreground">{t(`intelligence.entity.${kind}`)}</p>
        <h1 className="font-display text-2xl font-bold leading-tight break-words md:text-3xl">
          {name}
        </h1>
        {subtitle ? <p className="text-small text-muted-foreground">{subtitle}</p> : null}
        {facts && facts.length > 0 ? (
          <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-caption text-subtle-foreground">
            {facts.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}
