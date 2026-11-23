/**
 * Percentile bars (plan EA, catalogue n.º 5; V1·1, V2·1; AP-T03): each figure's value, a bar as long as its place in the league
 * (always «more is better»: a figure where less is better is turned round) and the league's middle marked - FBref's form, the one
 * that reads best. The place is said in words under the bar («mejor que el 63 % de su liga»), never as «p63». Every row carries its
 * sample in its accessible name; a missing value says why.
 */
import { t } from "@/lib/i18n";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import type { StatFigure } from "@/lib/api/v1/types_stats";
import { cn } from "@/lib/utils";
import { figName, figValue, goodness, missingText, num } from "./format";
import { placeInWords } from "./howToRead";

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
          <li key={f.key} className="space-y-1" aria-label={label}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate text-small text-foreground-soft">
                {figName(f.key)}
              </span>
              <span className="numeric text-sm font-semibold">{figValue(f)}</span>
            </div>
            {isMissing(f.value) ? (
              <p className="text-small text-subtle-foreground">{missingText(f.value)}</p>
            ) : (
              <>
                <span className="relative block h-3 rounded-full bg-elevated" aria-hidden>
                  {good !== null ? (
                    <span
                      className={cn(
                        "absolute inset-y-0 left-0 rounded-full",
                        f.better === "neutral"
                          ? "bg-muted-foreground"
                          : good !== null && good >= 60
                            ? "bg-primary"
                            : "bg-primary-dim",
                      )}
                      style={{ width: `${Math.max(3, good)}%` }}
                    />
                  ) : null}
                  <span
                    className="absolute -top-0.5 h-4 w-0.5 bg-foreground-soft/70"
                    style={{ left: "50%" }}
                  />
                </span>
                <p className="text-small text-subtle-foreground">
                  {good === null ? "—" : placeInWords(good)}
                </p>
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}
