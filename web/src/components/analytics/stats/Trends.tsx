/**
 * Trends (plan EA, catalogue n.º 9 and 10; V2·7): the market x context matrix - every cell n/N, its colour the deviation from the
 * league (never a recommendation) - and the streaks with their 95 % Wilson interval, so that a run of ten reads as what it is.
 */
import { t } from "@/lib/i18n";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import type { TrendColumn, TrendRow } from "@/lib/api/v1/types_stats";
import { cn } from "@/lib/utils";

/** Points of deviation from the league that colour a cell. */
const DEVIATION = 10;

function tone(row: TrendRow | undefined): string {
  if (!row || isMissing(row.deviation_pts)) return "bg-elevated text-foreground-soft";
  if (row.deviation_pts >= DEVIATION) return "bg-primary-soft text-primary";
  if (row.deviation_pts <= -DEVIATION) return "bg-negative-soft text-negative";
  return "bg-elevated text-foreground-soft";
}

export function TrendMatrix({
  columns,
  keys,
  testId,
}: {
  columns: TrendColumn[];
  keys: string[];
  testId?: string;
}) {
  const cell = (c: TrendColumn, key: string) => c.rows.find((r) => r.key === key);
  return (
    <div className="overflow-x-auto" data-testid={testId}>
      <table className="w-full min-w-[20rem] border-separate border-spacing-1 text-caption">
        <thead>
          <tr>
            <th scope="col" className="sr-only">
              {t("stats.matrixTitle")}
            </th>
            {columns.map((c) => (
              <th
                key={c.context}
                scope="col"
                className="px-1 text-center font-semibold text-muted-foreground"
              >
                {t(`stats.context.${c.context}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key}>
              <th scope="row" className="pr-2 text-left font-normal text-foreground-soft">
                {t(`stats.trend.${key}`)}
              </th>
              {columns.map((c) => {
                const r = cell(c, key);
                return (
                  <td
                    key={c.context}
                    className={cn("numeric rounded-lg px-1.5 py-2 text-center", tone(r))}
                    title={
                      r
                        ? t("stats.wilson", {
                            hits: r.hits,
                            n: r.n,
                            low: r.wilson_low,
                            high: r.wilson_high,
                          })
                        : undefined
                    }
                  >
                    {r ? `${r.hits}/${r.n}` : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 flex flex-wrap gap-3 text-caption text-muted-foreground">
        <span>
          <span aria-hidden className="text-primary">
            ■
          </span>{" "}
          {t("stats.aboveLeague")}
        </span>
        <span>
          <span aria-hidden className="text-negative">
            ■
          </span>{" "}
          {t("stats.belowLeague")}
        </span>
        <span>
          <span aria-hidden className="text-subtle-foreground">
            ■
          </span>{" "}
          {t("stats.inLeague")}
        </span>
      </p>
    </div>
  );
}

/** One frequency with its Wilson interval: the light span is the interval, the dot the observed share. */
export function WilsonRow({ label, row }: { label: string; row: TrendRow }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,9rem)_auto] items-center gap-2 text-caption">
      <span className="truncate text-foreground-soft">{label}</span>
      <span className="relative h-3 rounded-full bg-elevated" aria-hidden>
        <span
          className="absolute inset-y-0 rounded-full bg-primary-soft"
          style={{
            left: `${row.wilson_low}%`,
            width: `${Math.max(2, row.wilson_high - row.wilson_low)}%`,
          }}
        />
        <span
          className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary"
          style={{ left: `${row.pct}%` }}
        />
      </span>
      <span className="numeric text-muted-foreground">
        {t("stats.wilson", {
          hits: row.hits,
          n: row.n,
          low: row.wilson_low,
          high: row.wilson_high,
        })}
      </span>
    </div>
  );
}
