import { formatDateTime, formatTime, zoneAbbrev } from "@/lib/time";

export const EMPTY = "—";

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return `${(value * 100).toFixed(digits)}%`;
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  const s = (value * 100).toFixed(digits);
  return `${value > 0 ? "+" : ""}${s}%`;
}

export function odds(value: number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY;
  return value.toFixed(2);
}

export function num(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return EMPTY;
  return value.toFixed(digits);
}

export function int(value: number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY;
  return value.toLocaleString("en-US");
}

/** HH:MM in the reader's time zone (their preference; the data itself stays UTC). */
export function timeOf(iso: string): string {
  return formatTime(iso);
}

/** "4 oct 18:00 CEST" in the reader's time zone. */
export function dateTimeOf(iso: string): string {
  return `${formatDateTime(iso)} ${zoneAbbrev(iso)}`;
}
