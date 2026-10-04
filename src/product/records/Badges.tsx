/** Small labels of the records: a result, a parlay's state, who chose it, evaluation mode. */
import { BadgeCheck, Bookmark, FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { toNumber } from "@/lib/i18n/format";
import type { ParlayStatus, ResultStatus } from "@/lib/api/v1/types_records";
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
