/**
 * The page's first look (plan maestro UX/UI 2026, sheets T01 and T07): for the period the reader chooses, how many picks
 * PrediGol published, how they ended as one bar (won, lost, the rest) and three figures - hit rate, units and return.
 * It reads the same tallies as «Picks publicados» below and keeps their rule: under the minimum sample there are counts
 * only (a dash for the units and the return, and the sentence that says why); the hit rate always carries its sample.
 */
import { useState } from "react";
import { t } from "@/lib/i18n";
import { Segmented } from "@/components/ui/segmented";
import type { Transparency, TransparencyPeriod } from "@/lib/api/v1/types_transparency";
import { fmtUnits } from "@/product/records/units";
import { DASH } from "@/lib/i18n/format";
import { intText, pctText, roiText, sampleNote } from "./model";

const PERIODS: readonly TransparencyPeriod[] = ["7d", "30d", "all"];

export function TransparencySummary({ data }: { data: Transparency }) {
  const [period, setPeriod] = useState<TransparencyPeriod>("30d");
  const tally = data.periods.find((p) => p.period === period) ?? data.periods[0];
  if (!tally) return null;
  const won = tally.won + tally.half_won;
  const lost = tally.lost + tally.half_lost;
  const other = tally.push + tally.void;
  const decided = won + lost;
  const bar = won + lost + other;
  const note = sampleNote(tally, data.min_sample, data.conclusive);
  const tile = "min-w-0 rounded-field bg-background/40 px-3 py-2.5";
  // whole at 320 px: three short words, never cut
  const label = "text-caption font-semibold text-muted-foreground";
  return (
    <section
      aria-label={t("transparency.summary.label")}
      data-testid="transparency-summary"
      data-period={period}
      className="surface-pitch relative overflow-hidden rounded-feature p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-overline text-primary">{t("transparency.summary.published")}</p>
        <Segmented
          value={period}
          onChange={setPeriod}
          label={t("transparency.summary.period")}
          testId="transparency-summary-period"
          options={PERIODS.map((p) => ({
            value: p,
            label: t(`transparency.summary.periods.${p}`),
          }))}
        />
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-2">
        <span
          className="numeric font-display text-[3.25rem] font-bold leading-none"
          data-testid="transparency-summary-published"
        >
          {intText(tally.published)}
        </span>
        <p className="min-w-0 flex-1 basis-40 pb-1 text-sm text-muted-foreground">
          {t("transparency.summary.breakdown", {
            won,
            lost,
            other,
            pending: tally.pending,
          })}
        </p>
      </div>
      {bar > 0 ? (
        <div aria-hidden className="mt-3 flex h-2 overflow-hidden rounded-full bg-elevated">
          <span className="bg-positive" style={{ width: `${(won / bar) * 100}%` }} />
          <span className="bg-negative" style={{ width: `${(lost / bar) * 100}%` }} />
          <span className="bg-info" style={{ width: `${(other / bar) * 100}%` }} />
        </div>
      ) : null}
      <dl className="mt-4 grid grid-cols-3 gap-2">
        <div className={tile}>
          <dt className={label}>{t("transparency.summary.hit")}</dt>
          <dd className="numeric mt-1 font-display text-xl font-bold">
            {decided > 0 ? pctText(won / decided) : DASH}
          </dd>
          <dd className="text-caption text-subtle-foreground">
            {t("transparency.summary.hitSample", { count: decided })}
          </dd>
        </div>
        <div className={tile}>
          <dt className={label}>{t("transparency.summary.units")}</dt>
          <dd className="numeric mt-1 font-display text-xl font-bold">
            {tally.units === null ? DASH : fmtUnits(tally.units)}
          </dd>
        </div>
        <div className={tile}>
          <dt className="text-overline text-muted-foreground">{t("transparency.published.roi")}</dt>
          <dd className="numeric mt-1 font-display text-xl font-bold">{roiText(tally)}</dd>
        </div>
      </dl>
      {note ? (
        <p
          className="mt-3 text-caption text-muted-foreground"
          data-testid="transparency-summary-note"
        >
          {note}
        </p>
      ) : null}
    </section>
  );
}
