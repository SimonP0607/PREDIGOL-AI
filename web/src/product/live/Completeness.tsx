/**
 * How much we can show of a live match, as a small signal meter. Tap (or hover on a
 * desktop) for the list of what is available: score, minute, events, statistics...
 */
import { Check, Minus } from "lucide-react";
import type { LiveCompleteness } from "@/lib/api/v1/types_center";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { SIGNALS, completenessBars, type Level, type Signal } from "./model";

function signalLabel(signal: Signal): string {
  switch (signal) {
    case "score":
      return t("live.signal.score");
    case "minute":
      return t("live.signal.minute");
    case "events":
      return t("live.signal.events");
    case "stats":
      return t("live.signal.stats");
    case "lineups":
      return t("live.signal.lineups");
    case "players":
      return t("live.signal.players");
    case "live_odds":
      return t("live.signal.live_odds");
    case "markets":
      return t("live.signal.markets");
  }
}

function levelLabel(level: Level): string {
  switch (level) {
    case "rich":
      return t("live.completeness.rich");
    case "partial":
      return t("live.completeness.partial");
    case "basic":
      return t("live.completeness.basic");
  }
}

export function Completeness({
  data,
  className,
}: {
  data: LiveCompleteness;
  className?: string | undefined;
}) {
  const bars = completenessBars(data.score);
  const available = SIGNALS.filter((s) => data.signals[s]);
  const summary = t("live.completeness.label", {
    count: available.length,
    total: SIGNALS.length,
  });
  const list = available.map(signalLabel).join(", ");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={summary}
          title={list ? `${t("live.completeness.title")}: ${list}` : summary}
          data-testid="completeness"
          className={cn(
            "tap relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            className,
          )}
        >
          <span aria-hidden className="flex h-3.5 items-end gap-[2px]">
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className={cn(
                  "w-[3px] rounded-[1px]",
                  i < bars ? "bg-primary" : "bg-border-strong",
                )}
                style={{ height: `${40 + i * 20}%` }}
              />
            ))}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-3">
        <p className="text-xs font-semibold">{t("live.completeness.title")}</p>
        <p className="mt-0.5 text-caption text-muted-foreground">{levelLabel(data.level)}</p>
        <ul className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5 text-caption">
          {SIGNALS.map((s) => {
            const on = data.signals[s];
            return (
              <li
                key={s}
                className={cn(
                  "flex items-center gap-1.5",
                  on ? "text-foreground" : "text-subtle-foreground",
                )}
              >
                {on ? (
                  <Check aria-hidden className="h-3 w-3 shrink-0 text-primary" />
                ) : (
                  <Minus aria-hidden className="h-3 w-3 shrink-0" />
                )}
                <span className="min-w-0 break-words leading-tight">{signalLabel(s)}</span>
                <span className="sr-only">
                  {on ? t("live.completeness.available") : t("live.completeness.missing")}
                </span>
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
