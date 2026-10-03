import { Activity, Check, Clock, HelpCircle, TriangleAlert } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { DataState, Freshness } from "@/types/domain";

const config: Record<Freshness, { className: string; Icon: typeof Check }> = {
  live: {
    className: "border-info/35 bg-info-soft text-info",
    Icon: Activity,
  },
  fresh: {
    className: "border-positive/35 bg-positive-soft text-positive",
    Icon: Check,
  },
  aging: {
    className: "border-warning/35 bg-warning-soft text-warning",
    Icon: Clock,
  },
  stale: {
    className: "border-negative/35 bg-negative-soft text-negative",
    Icon: TriangleAlert,
  },
  unknown: {
    className: "border-border-strong bg-muted text-muted-foreground",
    Icon: HelpCircle,
  },
};

function freshnessLabel(f: Freshness): string {
  switch (f) {
    case "live":
      return t("admin.status.freshness.live");
    case "fresh":
      return t("admin.status.freshness.fresh");
    case "aging":
      return t("admin.status.freshness.aging");
    case "stale":
      return t("admin.status.freshness.stale");
    case "unknown":
      return t("admin.status.freshness.unknown");
  }
}

function freshnessHelp(f: Freshness): string {
  switch (f) {
    case "live":
      return t("admin.status.freshnessHelp.live");
    case "fresh":
      return t("admin.status.freshnessHelp.fresh");
    case "aging":
      return t("admin.status.freshnessHelp.aging");
    case "stale":
      return t("admin.status.freshnessHelp.stale");
    case "unknown":
      return t("admin.status.freshnessHelp.unknown");
  }
}

/** Text + icon + colour. Colour is never the only carrier of meaning. */
export function FreshnessBadge({
  freshness,
  detail,
  className,
}: {
  freshness: Freshness;
  detail?: string;
  className?: string;
}) {
  const { className: tone, Icon } = config[freshness];
  const label = freshnessLabel(freshness);
  const description = freshnessHelp(freshness);
  return (
    <span
      title={detail ?? description}
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-caption font-medium uppercase tracking-wider whitespace-nowrap",
        tone,
        className,
      )}
    >
      <Icon aria-hidden className="h-3 w-3" />
      {label}
      <span className="sr-only">{` — ${description}`}</span>
    </span>
  );
}

/** Maps the coarse DataState vocabulary onto the freshness scale. */
export function freshnessFromState(state: DataState): Freshness {
  switch (state) {
    case "healthy":
      return "fresh";
    case "warning":
      return "aging";
    case "stale":
      return "stale";
    case "failed":
      return "stale";
    default:
      return "unknown";
  }
}

export const freshnessOrder: Freshness[] = ["live", "fresh", "aging", "stale", "unknown"];
