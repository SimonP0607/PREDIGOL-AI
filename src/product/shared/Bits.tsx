/** Small, shared pieces of the product screens: prices, value, freshness, match state. */
import { Clock, FlaskConical, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtPct, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import { formatKickoff, formatRelative, formatTime } from "@/lib/time";
import type { PriceFreshness, ParlayRisk } from "@/lib/api/v1/types_product";
import { riskLabel } from "./markets";

/** A decimal price. `best` marks the selected value in PrediGol gold. */
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
    <span
      className={cn(
        "numeric inline-flex items-center justify-center rounded-md border font-semibold tabular-nums",
        size === "sm" && "min-w-[3rem] px-1.5 py-0.5 text-xs",
        size === "md" && "min-w-[3.5rem] px-2 py-1 text-sm",
        size === "lg" && "min-w-[4.5rem] px-3 py-1.5 text-lg",
        best
          ? "border-gold/50 bg-gold-soft text-gold-strong"
          : "border-border-strong bg-elevated text-foreground",
        className,
      )}
    >
      {fmtOdds(odds)}
    </span>
  );
}

/** Expected value per unit, signed, coloured by sign. */
export function EvBadge({
  ev,
  className,
}: {
  ev: string | number | null | undefined;
  className?: string | undefined;
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
      title={t("common.evLong")}
      className={cn(
        "numeric inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.7rem] font-semibold",
        n > 0 ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative",
        className,
      )}
    >
      {t("common.ev")} {fmtSignedPct(n)}
    </span>
  );
}

/** Model probability against the market's, as two thin bars. */
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
  const row = (label: string, v: number | null, tone: string) => (
    <div className="flex items-center gap-2">
      <span className="w-[5.5rem] shrink-0 text-caption text-muted-foreground">{label}</span>
      <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <span
          className={cn("absolute inset-y-0 left-0 rounded-full", tone)}
          style={{ width: `${Math.max(0, Math.min(1, v ?? 0)) * 100}%` }}
        />
      </span>
      <span className="numeric w-12 shrink-0 text-right text-xs">{fmtPct(v)}</span>
    </div>
  );
  return (
    <div className={cn("space-y-1", className)}>
      {row(t("common.modelProbability"), m, "bg-primary")}
      {row(t("common.marketProbability"), k, "bg-info")}
    </div>
  );
}

const FRESH_TONE: Record<PriceFreshness, string> = {
  fresh: "bg-positive",
  aging: "bg-warning",
  stale: "bg-negative",
  none: "bg-subtle-foreground",
};

/** A dot and "hace 12 min" for when a price was captured. */
export function Freshness({
  at,
  level,
  className,
}: {
  at: string | null | undefined;
  level?: PriceFreshness | undefined;
  className?: string | undefined;
}) {
  const lvl: PriceFreshness = level ?? (at ? "fresh" : "none");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-caption text-muted-foreground",
        className,
      )}
      title={t(`common.freshnessLevel.${lvl}`)}
    >
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", FRESH_TONE[lvl])} />
      {at ? formatRelative(at) : t("common.freshnessLevel.none")}
    </span>
  );
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
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold",
        RISK_TONE[risk],
        className,
      )}
    >
      {riskLabel(risk)}
    </span>
  );
}

/** Shown on anything built from the admin's shadow preview: never a recommendation. */
export function ShadowBadge({ className }: { className?: string | undefined }) {
  return (
    <span
      title={t("common.source.shadowPreview")}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-info/40 bg-info-soft px-2 py-0.5 text-[0.65rem] font-bold uppercase tracking-wider text-info",
        className,
      )}
    >
      <FlaskConical aria-hidden className="h-3 w-3" />
      {t("common.source.shadowPreviewShort")}
    </span>
  );
}

const LIVE_STATUSES = new Set(["1H", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"]);

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
  const label =
    status === "HT"
      ? t("common.status.halftime")
      : elapsed !== null && elapsed !== undefined
        ? `${elapsed}${extra ? `+${extra}` : ""}'`
        : LIVE_STATUSES.has(status)
          ? t("common.status.live")
          : status;
  return (
    <span
      className={cn(
        "numeric inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-xs font-semibold text-primary",
        className,
      )}
    >
      <span aria-hidden className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
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
