/**
 * «Actualizado hh:mm» with «Pausar actualizaciones» (WCAG 2.2.2: content that updates by itself can be paused), and the
 * phone's «Mi parlay · N» bar, which opens the slip the product already has and has each change said to a screen reader.
 */
import { useContext, useEffect, useRef } from "react";
import { Layers, Pause, Play } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { SlipLeg } from "@/product/records/model";
import { SlipContext } from "@/product/records/slipContext";
import { slipAnnouncement } from "./legs";

export function StatusBar({
  updatedAt,
  paused,
  onPause,
}: {
  /** When the prices on show were served (ms); 0: nothing yet. */
  updatedAt: number;
  paused: boolean;
  onPause: (paused: boolean) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground">
      {updatedAt > 0 ? (
        <span data-testid="explorer-updated" className="numeric">
          {t("explorer.status.updated", { time: formatTime(updatedAt) })}
        </span>
      ) : null}
      <button
        type="button"
        aria-pressed={paused}
        onClick={() => onPause(!paused)}
        data-testid="explorer-pause"
        className={cn(
          "tap-y relative inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          paused
            ? "border-warning/40 bg-warning-soft text-warning"
            : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
        )}
      >
        {paused ? (
          <Play aria-hidden className="h-3.5 w-3.5" />
        ) : (
          <Pause aria-hidden className="h-3.5 w-3.5" />
        )}
        {paused ? t("explorer.status.resume") : t("explorer.status.pause")}
      </button>
    </div>
  );
}

const NO_LEGS: readonly SlipLeg[] = [];

/**
 * A phone: «Mi parlay · 3» fixed over the tab bar while the slip holds something; it opens the slip (records/SlipSheet).
 * Every leg in or out is announced through `announce` (the explorer's live region).
 */
export function ParlayBar({ announce }: { announce: (message: string) => void }) {
  const slip = useContext(SlipContext);
  const legs = slip?.legs ?? NO_LEGS;
  const before = useRef(legs);
  useEffect(() => {
    const message = slipAnnouncement(before.current, legs);
    before.current = legs;
    if (message) announce(message);
  }, [legs, announce]);
  if (!slip || legs.length === 0) return null;
  return (
    <div
      data-testid="explorer-parlay-bar"
      className="sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-30 lg:hidden short:bottom-[calc(3.25rem+env(safe-area-inset-bottom))]"
    >
      <button
        type="button"
        onClick={() => slip.setOpen(true)}
        className="flex min-h-12 w-full items-center justify-between gap-3 rounded-xl border border-gold/50 bg-card px-4 text-left shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-gold-strong">
          <Layers aria-hidden className="h-4 w-4" />
          {t("records.slip.open", { count: legs.length })}
        </span>
        <span className="text-xs font-medium text-muted-foreground">
          {t("explorer.parlay.open")}
        </span>
      </button>
    </div>
  );
}
