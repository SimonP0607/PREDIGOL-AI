/** Numbers in the reader's language: decimal odds, percentages, signed values. */
import { getDisplay, type OddsFormat } from "@/lib/display";
import { getLocale, intlTag } from "./index";

export const DASH = "—";

const cache = new Map<string, Intl.NumberFormat>();
function nf(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${intlTag()}|${JSON.stringify(options)}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(intlTag(), options);
    cache.set(key, f);
  }
  return f;
}

function num(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * How a price is written: the reader's setting (plan maestro UX/UI 2026, decision 8), decimal unless they chose another.
 * Here, and nowhere else: a format changes how a price is written, never the price, its probability or anything
 * computed from it - every calculation and everything sent to the API stays in decimal.
 */
export type { OddsFormat } from "@/lib/display";

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

/** 2.05 -> «+105», 1.50 -> «−200»: what 100 wins, or what wins 100. */
function american(decimal: number): string {
  if (decimal <= 1) return DASH;
  const value = decimal >= 2 ? Math.round((decimal - 1) * 100) : -Math.round(100 / (decimal - 1));
  return `${value < 0 ? "−" : "+"}${Math.abs(value)}`;
}

/** 2.05 -> «21/20», 3.50 -> «5/2»: the profit over the stake, from the price to two places. */
function fractional(decimal: number): string {
  if (decimal <= 1) return DASH;
  const cents = Math.round((decimal - 1) * 100);
  const d = gcd(cents, 100);
  return `${cents / d}/${100 / d}`;
}

/**
 * The one formatter of a price (plan maestro UX/UI 2026, PR-09): every price on a screen, of the product or of the
 * console, is written by it, in the reader's format. Decimal, two places: 2,10 in Spanish, 2.10 in English; American:
 * +110; fractional: 11/10; «—» for no price.
 */
export function formatOdds(
  value: number | string | null | undefined,
  format: OddsFormat = getDisplay().odds_format,
): string {
  const n = num(value);
  if (n === null) return DASH;
  switch (format) {
    case "american":
      return american(n);
    case "fractional":
      return fractional(n);
    case "decimal":
      return nf({ minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
  }
}

/** A probability or ratio as a percentage: 0.523 -> 52,3 %. */
export function fmtPct(value: number | string | null | undefined, digits = 1): string {
  const n = num(value);
  return n === null
    ? DASH
    : nf({ style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(
        n,
      );
}

/** Signed percentage: +4,5 % / −2,1 %. */
export function fmtSignedPct(value: number | string | null | undefined, digits = 1): string {
  const n = num(value);
  return n === null
    ? DASH
    : nf({
        style: "percent",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
        signDisplay: "exceptZero",
      }).format(n);
}

/**
 * A difference between two probabilities - the edge, p_model - p_market - in percentage points, signed: 0.0745 -> "+7,5 pp".
 * It is not "7,5 %" (that reads as 7,5 % more likely, or as a return on the stake): a gap of a PRICE (price_edge) or the
 * expected value is relative and stays a percentage (`fmtSignedPct`). The unit is kept with the figure by a no-break space.
 */
export function fmtSignedPp(value: number | string | null | undefined, digits = 1): string {
  const n = num(value);
  if (n === null) return DASH;
  // 0.0745 * 100 is 7.4499... in binary: settle the product first so a half rounds up, as on paper.
  const points = Number((n * 100).toFixed(6));
  const figure = nf({
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: "exceptZero",
  }).format(points);
  return `${figure}\u00a0pp`;
}

export function fmtInt(value: number | string | null | undefined): string {
  const n = num(value);
  return n === null ? DASH : nf({ maximumFractionDigits: 0 }).format(n);
}

/** A handicap or total line: +0,5 / −1 / 2,5. `signed` for handicaps. */
export function fmtLine(value: number | string | null | undefined, signed = false): string {
  const n = num(value);
  if (n === null) return DASH;
  return nf({
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
    signDisplay: signed ? "exceptZero" : "auto",
  }).format(n);
}

export function toNumber(value: number | string | null | undefined): number | null {
  return num(value);
}

/*
 * The Admin Console's research tables format with Number#toFixed. These keep that exact
 * English output and give Spanish its own separators (2,10 · 52,3 % · 12.500).
 */

/** Like `n.toFixed(digits)`, in the reader's language. No thousands grouping. */
export function localFixed(n: number, digits: number): string {
  if (getLocale() === "en") return n.toFixed(digits);
  return nf({
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  }).format(n);
}

/** `${(fraction * 100).toFixed(digits)}%` in English; "52,3 %" in Spanish. */
export function localPct(fraction: number, digits: number, signed = false): string {
  if (getLocale() === "en") {
    return `${signed && fraction > 0 ? "+" : ""}${(fraction * 100).toFixed(digits)}%`;
  }
  return nf({
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    ...(signed ? { signDisplay: "exceptZero" as const } : {}),
  }).format(fraction);
}

/** A decimal the API sent as text ("29.85"): as is in English, "29,85" in Spanish. */
export function localDecimalText(text: string): string {
  return getLocale() === "en" ? text : text.replace(".", ",");
}

/** Thousands separators: 12,500 in English, 12.500 in Spanish. */
export function localInt(n: number): string {
  if (getLocale() === "en") return n.toLocaleString("en-US");
  return nf({}).format(n);
}

/**
 * A script that is not the Latin one: Arabic, Cyrillic, Hebrew, Han, Thai... A reader of PrediGol reads Spanish or
 * English; a sentence of the server written in another script is not for them.
 */
const FOREIGN_SCRIPT = /(?=\p{L})(?!\p{Script=Latin})./u;

/** A claim the server marks, or words that mark it, as a rumour: it never reaches a reader (plan AP-T02, C-02 1.1). */
const RUMOUR = /\b(?:rumou?rs?|rumou?red|rumores?|rumorea(?:n|ron)?)\b/i;

/**
 * A decimal with a point inside a sentence («0.473», «73.7 %»): Spanish writes «0,473» and «73,7 %». Left alone: a
 * version or a date («1.2.3»), a number glued to letters, and a group of exactly three digits after a non-zero integer
 * («4.000» is a thousands separator in Spanish, not a decimal).
 */
const POINT_DECIMAL = /(?<![\w.,])(\d{1,3})\.(\d{1,4})(?![\w]|\.\d|,\d)/g;

/**
 * A text the server wrote for a reader (a pick's reason, a risk, a note), made safe for this screen (AP-T02):
 *   - null when it is a rumour or is written in a script the reader does not read: it is not drawn, the structured
 *     reasons the screen already has take its place (PickWhy);
 *   - decimals with a point rewritten in the reader's format (Spanish: comma). English text is left as it is.
 * The definitive fix is the contract (C-02 1.1): the text arrives in the reader's language, without rumours or raw numbers.
 */
export function localizeServerText(text: string | null | undefined): string | null {
  const raw = (text ?? "").trim();
  if (!raw) return null;
  if (FOREIGN_SCRIPT.test(raw) || RUMOUR.test(raw)) return null;
  if (getLocale() === "en") return raw;
  return raw.replace(POINT_DECIMAL, (m, whole: string, frac: string) =>
    frac.length === 3 && whole !== "0" ? m : `${whole},${frac}`,
  );
}

/** The server's lines for a reader, each through `localizeServerText`; the ones that must not be drawn are left out. */
export function readerLines(lines: readonly string[] | null | undefined): string[] {
  return (lines ?? [])
    .map((line) => localizeServerText(line))
    .filter((line): line is string => line !== null);
}
