/**
 * What every new chart must carry (plan PM, PM-10-06, OP-16; FE-004): its evidence level E0 to E4 (the ladder of
 * `docs/proyecto/DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md` §5.3), a reading sentence that says what it shows with its sample and
 * interval, and the accessibility review of the 14 critical checks (after Chartability, https://chartability.fizz.studio/, in our
 * own words). Pure. The figures come from the contract already computed (n, Wilson's interval, the league's value): nothing here
 * counts; it only writes them in words.
 */
import { localFixed, localInt } from "@/lib/i18n/format";
import { t } from "./evidenceText";

export const EVIDENCE_LEVELS = ["E0", "E1", "E2", "E3", "E4"] as const;
export type EvidenceLevel = (typeof EVIDENCE_LEVELS)[number];

/** The 14 critical checks, by the principle they belong to. Each one is reviewed by hand before the piece closes. */
export const CHART_CHECKS = [
  // perceivable
  "contraste",
  "alternativa_textual",
  "texto_minimo",
  "sin_parpadeo",
  "color_no_unico",
  // operable
  "teclado",
  "foco_visible",
  "instrucciones",
  // understandable
  "titulo_y_resumen",
  "incertidumbre",
  "lenguaje_llano",
  // compromising, flexible, assistive
  "tabla_equivalente",
  "zoom_y_espaciado",
  "lector_de_pantalla",
] as const;
export type ChartCheck = (typeof CHART_CHECKS)[number];

/** Checks that apply to every chart: «no aplica» is not an answer for them. */
export const ALWAYS_APPLY: readonly ChartCheck[] = [
  "contraste",
  "alternativa_textual",
  "texto_minimo",
  "color_no_unico",
  "titulo_y_resumen",
  "incertidumbre",
  "tabla_equivalente",
  "lector_de_pantalla",
];

/**
 * The review of one chart: every check answered - «ok» or, where it truly does not apply (a static chart has nothing to reach
 * by keyboard), «no_aplica» - with who reviewed it and when. A check left out does not compile; a failing one cannot be written.
 */
export interface ChartReview {
  checks: Record<ChartCheck, "ok" | "no_aplica">;
  reviewedBy: string;
  /** AAAA-MM-DD. */
  reviewedOn: string;
}

/** What is wrong with a review, in the checks' own keys: empty when it is complete. */
export function reviewProblems(review: ChartReview): string[] {
  const problems: string[] = [];
  for (const check of CHART_CHECKS) {
    const answer = review.checks[check] as string | undefined;
    if (answer !== "ok" && answer !== "no_aplica") problems.push(`${check}: sin revisar`);
    else if (answer === "no_aplica" && ALWAYS_APPLY.includes(check))
      problems.push(`${check}: siempre aplica`);
  }
  if (!review.reviewedBy.trim()) problems.push("revisor: vacío");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(review.reviewedOn)) problems.push("fecha: no es AAAA-MM-DD");
  return problems;
}

/** A proportion (k of n) with Wilson's interval as the contract gives it, in 0-1 or 0-100. */
export interface RateReading {
  kind: "rate";
  subject: string;
  k: number;
  n: number;
  /** Wilson's interval (lower, upper). */
  interval: readonly [number, number];
  league?: number | undefined;
  /** The sample a rate is shown from; under it the sentence says so and gives no rate. */
  minSample: number;
}

/** A mean per match. */
export interface MeanReading {
  kind: "mean";
  subject: string;
  value: number;
  n: number;
  league?: number | undefined;
  minSample: number;
  /** Digits of the value; 2 by default. */
  digits?: number | undefined;
}

export type Reading = RateReading | MeanReading;

function asPct(x: number): number {
  return x <= 1 ? x * 100 : x;
}

/** The level a reading supports by itself: under the minimum sample it is an anecdote (E0), whatever the chart claims. */
export function cappedLevel(level: EvidenceLevel, reading: Reading): EvidenceLevel {
  return reading.n < reading.minSample ? "E0" : level;
}

/** The reading sentence: what the chart shows, with its sample and its interval, in the reader's language. */
export function readingSentence(r: Reading): string {
  const n = localInt(r.n);
  if (r.kind === "rate") {
    if (r.n < r.minSample)
      return t("evidence.sentence.rateThin", { subject: r.subject, k: localInt(r.k), n });
    const vars = {
      subject: r.subject,
      k: localInt(r.k),
      n,
      pct: localFixed(r.n > 0 ? (100 * r.k) / r.n : 0, 0),
      lo: localFixed(asPct(r.interval[0]), 0),
      hi: localFixed(asPct(r.interval[1]), 0),
    };
    return r.league === undefined
      ? t("evidence.sentence.rate", vars)
      : t("evidence.sentence.rateLeague", { ...vars, league: localFixed(asPct(r.league), 0) });
  }
  const digits = r.digits ?? 2;
  const value = localFixed(r.value, digits);
  if (r.n < r.minSample) return t("evidence.sentence.meanThin", { subject: r.subject, value, n });
  return r.league === undefined
    ? t("evidence.sentence.mean", { subject: r.subject, value, n })
    : t("evidence.sentence.meanLeague", {
        subject: r.subject,
        value,
        n,
        league: localFixed(r.league, digits),
      });
}

export function levelTag(level: EvidenceLevel): string {
  return t(`evidence.level.${level}.tag`);
}

export function levelText(level: EvidenceLevel): string {
  return t(`evidence.level.${level}.text`);
}
