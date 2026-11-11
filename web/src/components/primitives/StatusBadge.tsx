import { cva, type VariantProps } from "class-variance-authority";
import { t, translateOr } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { DataState, ModelStatus, PickStatus } from "@/types/domain";

/**
 * The tag of «Noche de partido» (plan maestro UX/UI 2026, wave 2): a 24 px pill that names a state, in the product and
 * in the console. Its colour never informs alone: the word is the state, and most carry an icon or a dot.
 */
const badge = cva(
  "inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-xs font-semibold",
  {
    variants: {
      tone: {
        neutral: "bg-foreground/[0.07] text-foreground-soft",
        positive: "bg-positive-soft text-positive",
        negative: "bg-negative-soft text-negative",
        warning: "bg-warning-soft text-warning",
        info: "bg-info-soft text-info",
        brand: "bg-primary-soft text-primary",
        // what PrediGol recommends, and the membership
        gold: "bg-gold-soft text-gold-strong",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeTone = NonNullable<VariantProps<typeof badge>["tone"]>;

export function StatusBadge({
  children,
  tone,
  dot = true,
  className,
}: {
  children: React.ReactNode;
  tone?: BadgeTone;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span className={cn(badge({ tone }), className)}>
      {dot ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-80" /> : null}
      {children}
    </span>
  );
}

const dataStateTone: Record<DataState, BadgeTone> = {
  healthy: "positive",
  warning: "warning",
  stale: "warning",
  failed: "negative",
  unknown: "neutral",
};

function dataStateLabel(state: DataState): string {
  switch (state) {
    case "healthy":
      return t("admin.status.data.healthy");
    case "warning":
      return t("admin.status.data.warning");
    case "stale":
      return t("admin.status.data.stale");
    case "failed":
      return t("admin.status.data.failed");
    case "unknown":
      return t("admin.status.data.unknown");
  }
}

export function DataStateBadge({ state, label }: { state: DataState; label?: string }) {
  return <StatusBadge tone={dataStateTone[state]}>{label ?? dataStateLabel(state)}</StatusBadge>;
}

const modelTone: Record<ModelStatus, BadgeTone> = {
  market_baseline: "info",
  validated: "positive",
  shadow: "brand",
  research: "warning",
  insufficient_data: "neutral",
  not_trained: "neutral",
};

function modelLabel(status: ModelStatus): string {
  switch (status) {
    case "market_baseline":
      return t("admin.status.model.market_baseline");
    case "validated":
      return t("admin.status.model.validated");
    case "shadow":
      return t("admin.status.model.shadow");
    case "research":
      return t("admin.status.model.research");
    case "insufficient_data":
      return t("admin.status.model.insufficient_data");
    case "not_trained":
      return t("admin.status.model.not_trained");
  }
}

export function ModelBadge({ status }: { status: ModelStatus }) {
  return <StatusBadge tone={modelTone[status]}>{modelLabel(status)}</StatusBadge>;
}

const pickTone: Record<PickStatus, BadgeTone> = {
  candidate: "info",
  shadow: "brand",
  qualified: "positive",
  published: "positive",
  settled: "neutral",
  rejected: "negative",
};

export function PickStatusBadge({ status }: { status: PickStatus }) {
  return (
    <StatusBadge tone={pickTone[status]}>
      {translateOr(`admin.status.pick.${status}`, status)}
    </StatusBadge>
  );
}
