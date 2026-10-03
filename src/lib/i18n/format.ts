/** Numbers in the reader's language: decimal odds, percentages, signed values. */
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

/** Decimal odds, two places: 2,10 in Spanish, 2.10 in English. */
export function fmtOdds(value: number | string | null | undefined): string {
  const n = num(value);
  return n === null ? DASH : nf({ minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
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

/** Thousands separators: 12,500 in English, 12.500 in Spanish. */
export function localInt(n: number): string {
  if (getLocale() === "en") return n.toLocaleString("en-US");
  return nf({}).format(n);
}
