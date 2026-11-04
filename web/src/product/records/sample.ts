/**
 * The sample of a result in Mis picks (plan UX, B5, section 30): «la rentabilidad va siempre con su muestra y su margen
 * (±20 puntos con 25 picks liquidados, ±14 con 50, ±10 con 100 y ±5 con 400). Con menos de 25 liquidados solo se muestran
 * los conteos, y por debajo de 100 se avisa de que la muestra todavía no permite concluir.»
 *
 * The server decides it (GET /me/history and /me/picks/summary: null units, ROI and hit rate below its min_sample) with
 * «Cómo le va a PrediGol»'s rule; the recap, which counts the records itself, applies the same numbers here. One wording
 * for both, so a figure and its sample read the same wherever they are shown.
 */
import { t } from "@/lib/i18n";
import { fmtInt, localFixed } from "@/lib/i18n/format";

/** Settled records from which units, ROI, hit rate and margin are shown (the server's MIN_SAMPLE). */
export const MIN_SAMPLE = 25;
/** Settled records from which the sample allows a conclusion (the server's CONCLUSIVE). */
export const CONCLUSIVE = 100;

/** One standard error of a flat-stake ROI over n settled records, a share: 1 / √n (0.20 with 25, 0.10 with 100). */
export function marginOf(n: number): number | null {
  return n > 0 ? 1 / Math.sqrt(n) : null;
}

/** Whether a result over n settled records may show its units, ROI and hit rate. */
export function enough(n: number, min: number = MIN_SAMPLE): boolean {
  return n >= min;
}

/**
 * The line under a return: the sample and its margin, or - below the minimum - how many there are and from how many the
 * figures appear. `margin` is a share (0.14 is ±14 points).
 */
export function sampleLine({
  n,
  margin,
  min = MIN_SAMPLE,
  conclusive = CONCLUSIVE,
}: {
  n: number;
  margin: number | null;
  min?: number | undefined;
  conclusive?: number | undefined;
}): string {
  if (n < min || margin === null) {
    return t("records.sample.countsOnly", { count: n, n: fmtInt(n), min: fmtInt(min) });
  }
  const pts = localFixed(margin * 100, 0);
  return n < conclusive
    ? t("records.sample.inconclusive", { count: n, n: fmtInt(n), pts })
    : t("records.sample.conclusive", { count: n, n: fmtInt(n), pts });
}
