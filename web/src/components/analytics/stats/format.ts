/**
 * Words and numbers of the advanced statistics (plan EA): how a figure, a missing value or a percentile reads. Pure.
 */
import { t } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";
import { isMissing, type Maybe, type Missing } from "@/lib/api/v1/types_intelligence";
import type { StatFigure } from "@/lib/api/v1/types_stats";

/** A number in the reader's language, or the dash for a value that is not there. */
export function num(v: Maybe<number> | null | undefined, digits = 2): string {
  if (v === null || v === undefined || isMissing(v)) return "—";
  return localFixed(v, digits);
}

export function pct(v: Maybe<number> | null | undefined, digits = 0): string {
  if (v === null || v === undefined || isMissing(v)) return "—";
  return `${localFixed(v, digits)} %`;
}

/** Why a value is missing, in words. */
export function missingText(m: Missing): string {
  if (m.missing_reason === "muestra_insuficiente")
    return t("stats.missing.muestra_insuficiente", {
      sample: m.sample ?? 0,
      min: m.min_sample ?? 0,
    });
  if (m.missing_reason === "sin_cobertura") return t("stats.missing.sin_cobertura");
  if (m.missing_reason === "no_entregado") return t("stats.missing.no_entregado");
  return t("stats.missing.sin_datos");
}

export function figName(key: string): string {
  return t(`stats.fig.${key}`);
}

/** The figure's value with its unit's digits: a proportion with one decimal, a rate with two. */
export function figValue(f: StatFigure): string {
  if (isMissing(f.value)) return "—";
  return f.unit === "porcentaje" ? pct(f.value, 1) : num(f.value, 2);
}

/** The percentile oriented so that higher is better (a «less is better» figure turns round); null when there is none. */
export function goodness(f: StatFigure): number | null {
  if (isMissing(f.percentile)) return null;
  return f.better === "menos" ? 100 - f.percentile : f.percentile;
}

export function percentileText(p: Maybe<number>): string {
  return isMissing(p) ? "—" : t("stats.percentile", { n: p });
}

/** Number of matches in words. */
export function sampleText(n: number): string {
  return t("stats.sample", { n });
}
