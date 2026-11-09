/** «Actualizado hh:mm» with «Pausar actualizaciones» (WCAG 2.2.2: content that updates by itself can be paused). */
import { Pause, Play } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";

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
