/** Small, shared pieces of the product screens: prices, value, freshness, match state. */
import { Clock, FlaskConical, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { formatOdds, fmtPct, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import {
  dayKey,
  formatDateTime,
  formatKickoff,
  formatRelative,
  formatTime,
  todayKey,
} from "@/lib/time";
import type { PriceFreshness, ParlayRisk } from "@/lib/api/v1/types_product";
import { termShort } from "@/lib/glossary";
import { hintProps } from "@/components/system/tapHint";
import { riskLabel } from "./markets";
import { priceVariants } from "./price";

/** A decimal price, as the system's price chip. `best` marks the selected value in PrediGol gold. */
export function OddsPill({
  odds,
  best = false,
  size = "md",
  className,
}: {
  odds: string | number | null | undefined;
  best?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string | undefined;
}) {
  return (
    <span className={cn(priceVariants({ size, tone: best ? "gold" : "plain" }), className)}>
      {formatOdds(odds)}
    </span>
  );
}

/** The neutral tag of a figure (the system's sheet 4): 24 px, a pill, the secondary text. */
export const TAG =
  "numeric inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full bg-foreground/7 px-[0.5625rem] text-xs font-semibold leading-none text-foreground-soft";

/**
 * The two questions under a pick («¿Por qué este pick?», «Explícame»), as the card's small secondary buttons: they
 * share the row and each takes a whole line on a narrow phone. Only the look of the trigger; what opens is not touched.
 */
export const ASK_BUTTON =
  "h-10 min-h-0 flex-1 basis-auto justify-center whitespace-nowrap rounded-field bg-elevated/60 px-3.5 text-[0.8125rem]";

/**
 * Expected value per unit, signed, coloured by sign. Its definition shows to a mouse and to a finger, even inside a
 * card's link (hintProps); `hint={false}` where a Hint around it already says it.
 */
export function EvBadge({
  ev,
  className,
  hint = true,
}: {
  ev: string | number | null | undefined;
  className?: string | undefined;
  hint?: boolean;
}) {
  const n = toNumber(ev);
  if (n === null)
    return (
      <span className={cn("text-caption text-subtle-foreground", className)}>
        {t("common.ev")} —
      </span>
    );
  return (
    <span
      {...(hint ? hintProps(termShort("expectedValue")) : {})}
      className={cn(
        "numeric inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full px-[0.5625rem] text-xs font-semibold leading-none",
        n > 0 ? "bg-primary-soft text-primary" : "bg-negative-soft text-negative",
        className,
      )}
    >
      {t("common.ev")} {fmtSignedPct(n)}
    </span>
  );
}

/**
 * Model probability against the market's, as the system's probability bar (sheet 4): the bar is what PrediGol
 * estimates, the mark is what the market pays. The two figures are written above it; the drawing adds nothing a
 * screen reader needs.
 */
export function ProbCompare({
  model,
  market,
  className,
}: {
  model: string | number | null | undefined;
  market: string | number | null | undefined;
  className?: string | undefined;
}) {
  const m = toNumber(model);
  const k = toNumber(market);
  // to a tenth of a point: a position on the bar, not a figure anyone reads
  const at = (v: number) => `${Math.round(Math.max(0, Math.min(1, v)) * 1000) / 10}%`;
  return (
    <div className={cn("space-y-2", className)} data-testid="prob-compare">
      <div className="flex items-baseline justify-between gap-3 text-[0.8125rem] leading-tight text-muted-foreground">
        <span>
          {t("common.modelProbability")}{" "}
          <b className="numeric font-bold text-foreground">{fmtPct(m)}</b>
        </span>
        <span className="text-right">
          {t("common.marketProbability")}{" "}
          <b className="numeric font-bold text-foreground">{fmtPct(k)}</b>
        </span>
      </div>
      <div aria-hidden className="relative h-2.5 rounded-full bg-elevated">
        {m === null ? null : (
          <span
            className="absolute inset-y-0 left-0 rounded-full bg-primary"
            style={{ width: at(m) }}
          />
        )}
        {k === null ? null : (
          <span
            className="absolute -bottom-1 -top-1 w-[2.5px] -translate-x-1/2 rounded-sm bg-foreground shadow-[0_0_0_2px_var(--card)]"
            style={{ left: at(k) }}
          />
        )}
      </div>
    </div>
  );
}

const FRESH_TONE: Record<PriceFreshness, string> = {
  fresh: "bg-positive",
  aging: "bg-warning",
  stale: "bg-warning",
  none: "bg-subtle-foreground",
};

/**
 * When a price was captured: a dot and «hace 12 min». An old price never passes as a current one (the system's rule):
 * it carries a clock and its exact hour, in the warning colour. What the level means shows to a mouse and a finger.
 */
export function Freshness({
  at,
  level,
  className,
  hint = true,
}: {
  at: string | null | undefined;
  level?: PriceFreshness | undefined;
  className?: string | undefined;
  hint?: boolean;
}) {
  const lvl: PriceFreshness = level ?? (at ? "fresh" : "none");
  const old = lvl === "stale" && !!at;
  return (
    // Two pieces that never break inside: on a narrow column the hour goes under «hace 24 h», whole.
    <span
      className={cn(
        "inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-caption",
        old ? "font-medium text-warning" : "text-muted-foreground",
        className,
      )}
      data-freshness={lvl}
      {...(hint ? hintProps(t(`common.freshnessLevel.${lvl}`)) : {})}
    >
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        {old ? (
          <Clock aria-hidden className="h-3 w-3 shrink-0" />
        ) : (
          <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", FRESH_TONE[lvl])} />
        )}
        {at ? formatRelative(at) : t("common.freshnessLevel.none")}
      </span>
      {old ? <span className="numeric whitespace-nowrap">· {exactHour(at)}</span> : null}
    </span>
  );
}

/** The hour of a capture; with its date when it is not today's. */
function exactHour(at: string): string {
  return dayKey(at) === todayKey() ? formatTime(at) : formatDateTime(at);
}

const RISK_TONE: Record<ParlayRisk, string> = {
  moderate: "border-warning/40 bg-warning-soft text-warning",
  high: "border-negative/35 bg-negative-soft text-negative",
  very_high: "border-negative/50 bg-negative-soft text-negative",
};

export function RiskBadge({
  risk,
  className,
}: {
  risk: ParlayRisk | null | undefined;
  className?: string | undefined;
}) {
  if (!risk) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-micro font-semibold",
        RISK_TONE[risk],
        className,
      )}
    >
      {riskLabel(risk)}
    </span>
  );
}

/** Shown on anything built from the admin's shadow preview: never a recommendation.
 *  `compact`: icon only below the `sm` breakpoint, so it never squeezes a card's header. */
export function ShadowBadge({
  className,
  compact = false,
}: {
  className?: string | undefined;
  compact?: boolean;
}) {
  return (
    <span
      title={t("common.source.shadowPreview")}
      aria-label={t("common.source.shadowPreview")}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-info/40 bg-info-soft px-2 py-0.5 text-micro font-bold uppercase tracking-wider text-info",
        compact && "px-1.5 sm:px-2",
        className,
      )}
    >
      <FlaskConical aria-hidden className="h-3 w-3" />
      <span className={cn(compact && "hidden sm:inline")}>
        {t("common.source.shadowPreviewShort")}
      </span>
    </span>
  );
}

const LIVE_STATUSES = new Set(["1H", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"]);
/** The odds feed names states in words; the fixture feed in short codes. Both mean the same. */
const HALF_TIME = new Set(["HT", "Halftime", "Half Time", "Break Time", "BT"]);
const NOT_STARTED = new Set(["NS", "TBD", "Not Started"]);

/** 67' with a pulsing dot while live; HT at half-time. */
export function LiveMinute({
  status,
  elapsed,
  extra,
  className,
}: {
  status: string;
  elapsed: number | null | undefined;
  extra?: number | null | undefined;
  className?: string | undefined;
}) {
  const label = HALF_TIME.has(status)
    ? t("common.status.halftime")
    : NOT_STARTED.has(status)
      ? t("common.status.scheduled")
      : elapsed !== null && elapsed !== undefined && elapsed > 0
        ? `${elapsed}${extra ? `+${extra}` : ""}'`
        : LIVE_STATUSES.has(status)
          ? t("common.status.live")
          : status;
  return (
    <span
      className={cn(
        // «Noche de partido» (the system's sheet 4): the live pill - 26 px, the action's green, Archivo
        "numeric inline-flex h-[1.625rem] items-center gap-1.5 whitespace-nowrap rounded-full bg-primary-soft px-2.5 text-[0.78125rem] font-extrabold leading-none text-primary",
        className,
      )}
    >
      <span aria-hidden className="relative flex h-2 w-2 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
      </span>
      {label}
    </span>
  );
}

/** "Hoy 18:00" with a clock icon - kick-off in the reader's zone. */
export function Kickoff({
  at,
  className,
  timeOnly = false,
}: {
  at: string;
  className?: string | undefined;
  timeOnly?: boolean;
}) {
  return (
    <span
      className={cn(
        "numeric inline-flex items-center gap-1 text-xs text-muted-foreground",
        className,
      )}
    >
      <Clock aria-hidden className="h-3 w-3" />
      {timeOnly ? formatTime(at) : formatKickoff(at)}
    </span>
  );
}

/** A small "live data" marker for blocks that refresh themselves. */
export function LiveDot({ className }: { className?: string | undefined }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-caption font-medium text-primary",
        className,
      )}
    >
      <Radio aria-hidden className="h-3 w-3" />
      {t("common.status.live")}
    </span>
  );
}
