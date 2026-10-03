import { EMPTY } from "@/lib/format";
import { formatDateTime, formatDateYear, formatRelative, zoneAbbrev } from "@/lib/time";
import type { Dec } from "@/lib/api/v1/types";

/** A decimal string from the API, for display. Null stays null. */
export function dec(value: Dec | null | undefined, digits = 2): string | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : null;
}

export function decPct(value: Dec | number | null | undefined, digits = 1): string | null {
  if (value === null || value === undefined) return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : null;
}

export function ratio(value: number | null | undefined, digits = 0): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return `${(value * 100).toFixed(digits)}%`;
}

/** Date in the reader's time zone (the name is historical: it used to be UTC). */
export function utcDate(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  return formatDateYear(iso);
}

/** Date and time in the reader's time zone, with the zone's abbreviation. */
export function utcDateTime(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  return `${formatDateTime(iso)} ${zoneAbbrev(iso)}`;
}

/** "12 min ago" / "in 3 h" relative to now, in the reader's language. */
export function relative(iso: string | null | undefined, now: number = Date.now()): string {
  return formatRelative(iso, now);
}

/** The original English-only form, kept for tests that pin its output. */
export function relativeEn(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return EMPTY;
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff);
  const m = Math.round(abs / 60_000);
  const unit =
    m < 1
      ? "just now"
      : m < 60
        ? `${m} min`
        : m < 48 * 60
          ? `${Math.round(m / 60)} h`
          : `${Math.round(m / 1440)} d`;
  if (unit === "just now") return unit;
  return diff < 0 ? `${unit} ago` : `in ${unit}`;
}

export function durationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return EMPTY;
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 60_000)} min`;
}

export function shortHash(h: string | null | undefined, n = 12): string {
  return h ? h.slice(0, n) : EMPTY;
}

export function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}
