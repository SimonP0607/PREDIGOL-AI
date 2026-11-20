/**
 * «Información no disponible» (plan PM, PM-14-01, lámina I12; UX-173): one component per state of `availabilityState.ts`, built on the
 * system's own pieces (`Card`, `Banner`, `StatusBadge`, `Progress`) and tokens. Every one says what happens, what still holds and,
 * when there is something to do, offers it. No screen draws a gap of its own: a block without data is not drawn as an empty card,
 * a missing figure is never a «0» nor a bare «—», and the same words are never used for two different states.
 *
 * What is drawn follows C-16 (`FBI_AVAILABILITY`, read in /auth/me as `availability`): a screen mounts these only with the switch
 * on (`useAvailabilityOn`), so nothing changes for readers while it is off.
 */
import type { ReactNode } from "react";
import { Clock, Info } from "lucide-react";
import { Banner } from "@/components/ui/banner";
import { Progress } from "@/components/ui/progress";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { t } from "@/lib/i18n";
import { localFixed, localInt } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { Card } from "./States";
import {
  groupUnavailable,
  listText,
  type AvailabilityStep,
  type Unavailable,
  type UnavailableGroup,
} from "./availabilityState";
import type { AvailabilityModule } from "@/lib/api/v1/types_availability";

/** 1 · The competition does not offer it: the section disappears and one line stays, without a card. */
export function NotOffered({
  subjects,
  className,
}: {
  subjects: readonly string[];
  className?: string | undefined;
}) {
  if (subjects.length === 0) return null;
  return (
    <p
      data-unavailable="no_existe"
      className={cn(
        "flex items-start gap-2.5 rounded-field border border-dashed border-border-strong px-3.5 py-3 text-small text-muted-foreground",
        className,
      )}
    >
      <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{t("availability.notOffered", { subjects: listText(subjects, true) })}</span>
    </p>
  );
}

/** A market PrediGol cannot settle in this competition (state 6): said once, the price stays informative. */
export function NotSettled({
  subject,
  className,
}: {
  subject: string;
  className?: string | undefined;
}) {
  return (
    <p
      data-unavailable="no_existe"
      data-step="liquidable"
      className={cn(
        "flex items-start gap-2.5 rounded-field border border-dashed border-border-strong px-3.5 py-3 text-small text-muted-foreground",
        className,
      )}
    >
      <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{t("availability.notSettled", { subject })}</span>
    </p>
  );
}

/** Level C: the block is drawn, and this note says it is partial and how partial. */
export function PartialCoverage({
  subjects,
  pct,
  className,
}: {
  subjects: readonly string[];
  /** Share of matches with the datum, 0-100. */
  pct?: number | null | undefined;
  className?: string | undefined;
}) {
  if (subjects.length === 0) return null;
  const text =
    pct === null || pct === undefined
      ? t("availability.partial.plain", { subjects: listText(subjects) })
      : t("availability.partial.pct", { subjects: listText(subjects), pct: localFixed(pct, 0) });
  return (
    <p
      data-unavailable="cobertura_parcial"
      className={cn("flex items-start gap-2 text-caption text-muted-foreground", className)}
    >
      <Info aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" />
      <span>{text}</span>
    </p>
  );
}

/** 2 · Not available yet for this match: it will come; say when and offer what can be done (a notice, for example). */
export function PendingData({
  subject,
  step = "existe",
  when,
  action,
  className,
}: {
  subject: string;
  step?: AvailabilityStep | undefined;
  /** When it usually arrives, already in words («1 h antes: hacia las 17:30»). */
  when?: string | undefined;
  /** The button the screen offers («Avisarme cuando salgan»). */
  action?: ReactNode;
  className?: string | undefined;
}) {
  const body = when
    ? t("availability.pending.when", { when })
    : t(`availability.pending.${step === "autorizada" || step === "liquidable" ? "existe" : step}`);
  return (
    <Card lift as="div" className={cn("space-y-3 p-4", className)}>
      <div data-unavailable="pendiente" data-step={step} className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-field bg-foreground/[0.05] text-foreground-soft">
          <Clock aria-hidden className="h-5 w-5" />
        </span>
        <div className="min-w-0">
          <p className="text-title text-foreground">
            {t("availability.pending.title", { subject })}
          </p>
          <p className="mt-0.5 text-small text-muted-foreground">{body}</p>
        </div>
      </div>
      {action ? <div>{action}</div> : null}
    </Card>
  );
}

/** 3 · Too few matches: the count, never a rate, and how far it is from the minimum. */
export function ThinSample({
  subject,
  n,
  min,
  icon,
  className,
}: {
  subject: string;
  n: number;
  /** The minimum the figure is shown from; without it, only the count. */
  min?: number | undefined;
  icon?: ReactNode;
  className?: string | undefined;
}) {
  const hasMin = min !== undefined && min > 0;
  const left = hasMin ? Math.max(0, min - n) : 0;
  return (
    <Card lift as="div" className={cn("space-y-3 p-4", className)}>
      <div data-unavailable="muestra_insuficiente" className="flex items-start gap-3">
        {icon ? (
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-field bg-foreground/[0.05] text-foreground-soft">
            {icon}
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="text-title text-foreground">{subject}</p>
            <StatusBadge dot={false}>{t("availability.thin.badge")}</StatusBadge>
          </div>
          <p className="mt-1 text-small text-foreground-soft">
            {hasMin
              ? t("availability.thin.body", { subject, n: localInt(n), min: localInt(min) })
              : t("availability.thin.bodyCount", { subject, n: localInt(n) })}
          </p>
        </div>
      </div>
      {hasMin ? (
        <div className="space-y-1.5">
          <div className="numeric flex justify-between text-caption text-muted-foreground">
            <span>{t("availability.thin.progress", { n: localInt(n), min: localInt(min) })}</span>
            <span>{t("availability.thin.left", { k: localInt(left) })}</span>
          </div>
          <Progress
            value={Math.min(100, (n / min) * 100)}
            aria-label={t("availability.thin.progress", { n: localInt(n), min: localInt(min) })}
            className="h-1.5 bg-foreground/[0.08]"
          />
        </div>
      ) : null}
    </Card>
  );
}

/** 4 · Under review: the datum exists but is not reliable now; it is withdrawn and said, with what still holds. */
export function UnderReview({
  subject,
  step,
  module,
  why,
  action,
  className,
}: {
  subject: string;
  step?: AvailabilityStep | undefined;
  module?: AvailabilityModule | undefined;
  /** The concrete reason, already in words («Dos fuentes no coinciden en los remates»). */
  why?: string | undefined;
  /** «Reportar un dato», when the screen offers it. */
  action?: ReactNode;
  className?: string | undefined;
}) {
  const still =
    step === "autorizada"
      ? t("availability.review.autorizada")
      : step === "reglas" && module
        ? t("availability.review.reglas", { module: t(`availability.module.${module}`) })
        : t("availability.review.other");
  return (
    <Banner tone="warning" data-unavailable="en_revision" data-step={step} className={className}>
      <p className="font-semibold">{t("availability.review.title", { subject })}</p>
      <p className="mt-0.5 text-foreground-soft">{why ? `${why} ${still}` : still}</p>
      {action ? <div className="mt-2 text-small font-semibold text-primary">{action}</div> : null}
    </Banner>
  );
}

/** The one component for a state: the screen passes C-16's state and its own words, never a gap of its own. */
export function UnavailableNotice({
  subject,
  state,
  min,
  when,
  why,
  action,
  className,
}: {
  subject: string;
  state: Unavailable | null;
  min?: number | undefined;
  when?: string | undefined;
  why?: string | undefined;
  action?: ReactNode;
  className?: string | undefined;
}) {
  if (!state) return null;
  switch (state.kind) {
    case "no_existe":
      return state.step === "liquidable" ? (
        <NotSettled subject={subject} className={className} />
      ) : (
        <NotOffered subjects={[subject]} className={className} />
      );
    case "cobertura_parcial":
      return <PartialCoverage subjects={[subject]} pct={state.pct} className={className} />;
    case "muestra_insuficiente":
      return <ThinSample subject={subject} n={state.n ?? 0} min={min} className={className} />;
    case "pendiente":
      return (
        <PendingData
          subject={subject}
          step={state.step}
          when={when}
          action={action}
          className={className}
        />
      );
    case "en_revision":
      return (
        <UnderReview
          subject={subject}
          step={state.step}
          module={state.module}
          why={why}
          action={action}
          className={className}
        />
      );
  }
}

function GroupLine({ group }: { group: UnavailableGroup }) {
  const subjects = listText(group.subjects, group.kind === "no_existe");
  switch (group.kind) {
    case "no_existe":
      return <NotOffered subjects={group.subjects} />;
    case "cobertura_parcial": {
      const pcts = group.items.map((i) => i.pct).filter((p): p is number => typeof p === "number");
      return (
        <PartialCoverage
          subjects={group.subjects}
          pct={group.subjects.length === 1 && pcts.length === 1 ? pcts[0] : null}
        />
      );
    }
    case "muestra_insuficiente":
      return (
        <p data-unavailable="muestra_insuficiente" className="text-caption text-muted-foreground">
          {t("availability.thin.group", { subjects })}
        </p>
      );
    case "pendiente":
      return (
        <p
          data-unavailable="pendiente"
          className="flex items-start gap-2 text-caption text-muted-foreground"
        >
          <Clock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{t("availability.pending.group", { subjects })}</span>
        </p>
      );
    case "en_revision":
      return (
        <Banner tone="warning" data-unavailable="en_revision" className="text-small">
          {t("availability.review.group", { subjects })}
        </Banner>
      );
  }
}

/**
 * One note per screen (the card's risk: a D league would otherwise pile a notice per block): every state once, its subjects
 * together, in the order of the five states. Empty when everything is available.
 */
export function UnavailableNotes({
  entries,
  className,
}: {
  entries: ReadonlyArray<{ subject: string; state: Unavailable | null }>;
  className?: string | undefined;
}) {
  const groups = groupUnavailable(entries);
  if (groups.length === 0) return null;
  return (
    <aside
      aria-label={t("availability.notesLabel")}
      data-testid="unavailable-notes"
      className={cn("space-y-2", className)}
    >
      {groups.map((g) => (
        <GroupLine key={g.kind} group={g} />
      ))}
    </aside>
  );
}
