/**
 * The words of «Picks guardados» (plan UX, B5): an odds range, the counts of a tally, a signed share and the line value of a
 * saved pick. Pure: no React here.
 */
import { t } from "@/lib/i18n";
import { DASH, fmtInt, fmtPct, toNumber } from "@/lib/i18n/format";
import type { OddsBand, PicksTally } from "@/lib/api/v1/types_mypicks";

export function bandLabel(band: OddsBand): string {
  return t(`records.mine.filters.band.${band}`);
}

/** «+3,1 %» / «−2,0 %»: a share with its sign, in the reader's language; a dash without a value. */
export function signedPct(value: string | number | null): string {
  const n = toNumber(value);
  if (n === null) return DASH;
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${fmtPct(Math.abs(n), 1)}`;
}

/** «12 ganados · 10 perdidos · 2 devueltos …»: every count of a tally, the zero ones left out. */
export function countsText(x: PicksTally): string {
  const parts: string[] = [
    t("records.mine.summary.counts.won", { count: x.won, n: fmtInt(x.won) }),
    t("records.mine.summary.counts.lost", { count: x.lost, n: fmtInt(x.lost) }),
  ];
  for (const key of ["half_won", "half_lost", "push", "void", "pending"] as const) {
    if (x[key] > 0)
      parts.push(t(`records.mine.summary.counts.${key}`, { count: x[key], n: fmtInt(x[key]) }));
  }
  return parts.join(" · ");
}

/** The line value of one saved pick once its match started (clv-v1), in words: «Valor de línea +3,1 %». */
export function lineValueText(value: string | null | undefined): string | null {
  if (toNumber(value ?? null) === null) return null;
  return t("records.mine.picks.lineValue", { value: signedPct(value ?? null) });
}
