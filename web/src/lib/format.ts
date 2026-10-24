import { formatDateTime, formatTime, zoneAbbrev } from "@/lib/time";
import { fmtSignedPp, localFixed, localInt, localPct } from "@/lib/i18n/format";

export const EMPTY = "—";

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return localPct(value, digits);
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return localPct(value, digits, true);
}

/** An edge (p_model - p_market) in percentage points: "+7.5 pp". A price gap or an expected value is `signedPct`. */
export function signedPp(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return fmtSignedPp(value, digits);
}

export function odds(value: number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY;
  return localFixed(value, 2);
}

export function num(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return EMPTY;
  return localFixed(value, digits);
}

export function int(value: number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY;
  return localInt(value);
}

/** HH:MM in the reader's time zone (their preference; the data itself stays UTC). */
export function timeOf(iso: string): string {
  return formatTime(iso);
}

/** "4 oct 18:00 CEST" in the reader's time zone. */
export function dateTimeOf(iso: string): string {
  return `${formatDateTime(iso)} ${zoneAbbrev(iso)}`;
}
