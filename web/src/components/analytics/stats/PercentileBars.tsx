/**
 * Percentile bars (plan EA, catalogue n.º 5; V1·1, V2·1): each figure's value, a bar as long as its percentile in the league and the
 * league's median marked - FBref's form, the one that reads best. A «less is better» figure keeps its own percentile in the text and
 * its colour says whether that is good. Every row carries its sample in its accessible name; a missing value says why.
 */
import { t } from "@/lib/i18n";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import type { StatFigure } from "@/lib/api/v1/types_stats";
import { cn } from "@/lib/utils";
import { figName, figValue, goodness, missingText, num, percentileText } from "./format";

export function PercentileBars({ figures, testId }: { figures: StatFigure[]; testId?: string }) {
  return (
    <ul className="space-y-2.5" data-testid={testId}>
      {figures.map((f) => {
        const good = goodness(f);
        const p = isMissing(f.percentile) ? null : f.percentile;
        const label = t("stats.figureHelp", {
          name: figName(f.key),
          value: figValue(f),
          unit: t(`stats.unit.${f.unit}`),
          pct: p ?? "—",
          league: isMissing(f.league_value) ? "—" : num(f.league_value),
          n: f.matches_with_data,
        });
        return (
          <li
            key={f.key}
            className="grid grid-cols-[minmax(0,7.5rem)_3.25rem_minmax(0,1fr)_2.5rem] items-center gap-2"
            aria-label={label}
          >
            <span className="truncate text-caption text-foreground-soft">{figName(f.key)}</span>
            <span className="numeric text-right text-sm font-semibold">{figValue(f)}</span>
            {isMissing(f.value) ? (
              <span className="col-span-2 text-caption text-subtle-foreground">
                {missingText(f.value)}
              </span>
            ) : (
              <>
                <span className="relative h-3 rounded-full bg-elevated" aria-hidden>
                  {p !== null ? (
                    <span
                      className={cn(
                        "absolute inset-y-0 left-0 rounded-full",
                        f.better === "neutral"
                          ? "bg-muted-foreground"
                          : good !== null && good >= 60
                            ? "bg-primary"
                            : "bg-primary-dim",
                      )}
                      style={{ width: `${Math.max(3, p)}%` }}
                    />
                  ) : null}
                  <span
                    className="absolute -top-0.5 h-4 w-0.5 bg-foreground-soft/70"
                    style={{ left: "50%" }}
                  />
                </span>
                <span className="numeric text-right text-caption text-subtle-foreground">
                  {p === null && isMissing(f.percentile) ? "—" : percentileText(f.percentile)}
                </span>
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}
