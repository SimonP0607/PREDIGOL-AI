/**
 * Times in the reader's own time zone.
 *
 * The database and the API speak UTC; nothing here changes a stored instant. The
 * reader's IANA zone (their account preference, else what the browser reports) only
 * decides how an instant is SHOWN and which instants make up "today".
 */
import { getLocale, intlTag, translate } from "@/lib/i18n";

let zone = "UTC";

export function setTimeZone(next: string): void {
  zone = isValidTimeZone(next) ? next : "UTC";
}

export function getTimeZone(): string {
  return zone;
}

export function detectTimeZone(): string {
  try {
    const z = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return z && isValidTimeZone(z) ? z : "UTC";
  } catch {
    return "UTC";
  }
}

export function isValidTimeZone(name: string): boolean {
  if (!name) return false;
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: name });
    return true;
  } catch {
    return false;
  }
}

/** Every IANA zone the browser knows, for the profile picker. */
export function listTimeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  const zones = intl.supportedValuesOf?.("timeZone") ?? [];
  const base = zones.length
    ? zones
    : ["UTC", "Europe/Madrid", "America/Bogota", "America/New_York"];
  return base.includes("UTC") ? base : ["UTC", ...base];
}

const cache = new Map<string, Intl.DateTimeFormat>();
function dtf(options: Intl.DateTimeFormatOptions, tz: string = zone, tag: string = intlTag()) {
  const key = `${tag}|${tz}|${JSON.stringify(options)}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(tag, { timeZone: tz, ...options });
    cache.set(key, f);
  }
  return f;
}

function toDate(value: string | number | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

const DASH = "—";
function guard(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = toDate(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 18:00 */
export function formatTime(
  value: string | number | Date | null | undefined,
  tz: string = zone,
): string {
  const d = guard(value);
  return d ? dtf({ hour: "2-digit", minute: "2-digit", hourCycle: "h23" }, tz).format(d) : DASH;
}

/** sáb 4 oct / Sat 4 Oct */
export function formatDate(
  value: string | number | Date | null | undefined,
  tz: string = zone,
): string {
  const d = guard(value);
  return d ? dtf({ weekday: "short", day: "numeric", month: "short" }, tz).format(d) : DASH;
}

/** 4 oct 2026 */
export function formatDateYear(
  value: string | number | Date | null | undefined,
  tz: string = zone,
): string {
  const d = guard(value);
  return d ? dtf({ day: "numeric", month: "short", year: "numeric" }, tz).format(d) : DASH;
}

/** sábado, 4 de octubre */
export function formatDateLong(
  value: string | number | Date | null | undefined,
  tz: string = zone,
): string {
  const d = guard(value);
  return d ? dtf({ weekday: "long", day: "numeric", month: "long" }, tz).format(d) : DASH;
}

/** 4 oct 18:00 */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  tz: string = zone,
): string {
  const d = guard(value);
  return d ? `${dtf({ day: "numeric", month: "short" }, tz).format(d)} ${formatTime(d, tz)}` : DASH;
}

/** The zone's short name at that instant: CEST, GMT-5, UTC. */
export function zoneAbbrev(value: string | number | Date = Date.now(), tz: string = zone): string {
  const d = toDate(value);
  const part = dtf({ timeZoneName: "short" }, tz, "en-GB")
    .formatToParts(d)
    .find((p) => p.type === "timeZoneName");
  return part?.value ?? tz;
}

/** "YYYY-MM-DD" of the instant, in the zone. */
export function dayKey(value: string | number | Date, tz: string = zone): string {
  const parts = dtf(
    { year: "numeric", month: "2-digit", day: "2-digit" },
    tz,
    "en-CA",
  ).formatToParts(toDate(value));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function todayKey(tz: string = zone, now: number = Date.now()): string {
  return dayKey(now, tz);
}

export function shiftDay(key: string, days: number): string {
  const [y, m, d] = key.split("-").map(Number) as [number, number, number];
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return t.toISOString().slice(0, 10);
}

/** Minutes the zone is ahead of UTC at that instant (Madrid in summer: +120, Bogotá: −300). */
export function offsetMinutes(instant: number, tz: string = zone): number {
  const parts = dtf(
    {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    },
    tz,
    "en-CA",
  ).formatToParts(new Date(instant));
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? "0");
  const asUtc = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour"),
    get("minute"),
    get("second"),
  );
  return Math.round((asUtc - Math.floor(instant / 1000) * 1000) / 60_000);
}

/** The UTC instant of a local wall-clock time in the zone (DST-safe). */
export function zonedInstant(key: string, hour = 0, minute = 0, tz: string = zone): number {
  const [y, m, d] = key.split("-").map(Number) as [number, number, number];
  const guess = Date.UTC(y, m - 1, d, hour, minute);
  let instant = guess - offsetMinutes(guess, tz) * 60_000;
  // Re-check at the candidate: across a DST change the offset differs from the guess's.
  const again = guess - offsetMinutes(instant, tz) * 60_000;
  if (again !== instant) instant = again;
  return instant;
}

/** [start, end) of a local day as UTC ISO strings - what the API is asked for. */
export function dayBounds(key: string, tz: string = zone): { from: string; to: string } {
  return {
    from: new Date(zonedInstant(key, 0, 0, tz)).toISOString(),
    to: new Date(zonedInstant(shiftDay(key, 1), 0, 0, tz)).toISOString(),
  };
}

/** "today" | "tomorrow" | "yesterday" | null, in the zone. */
export function relativeDay(
  value: string | number | Date,
  tz: string = zone,
  now: number = Date.now(),
): "today" | "tomorrow" | "yesterday" | null {
  const k = dayKey(value, tz);
  const today = todayKey(tz, now);
  if (k === today) return "today";
  if (k === shiftDay(today, 1)) return "tomorrow";
  if (k === shiftDay(today, -1)) return "yesterday";
  return null;
}

/** Hoy 18:00 · Mañana 20:30 · sáb 4 oct 18:00 */
export function formatKickoff(
  value: string | null | undefined,
  tz: string = zone,
  now: number = Date.now(),
): string {
  const d = guard(value);
  if (!d) return DASH;
  const rel = relativeDay(d, tz, now);
  const day = rel ? translate(`common.day.${rel}`) : formatDate(d, tz);
  return `${day} ${formatTime(d, tz)}`;
}

/** "hace 5 min" / "en 3 h" / "5 min ago" in the reader's language. */
export function formatRelative(
  value: string | number | Date | null | undefined,
  now: number = Date.now(),
): string {
  const d = guard(value);
  if (!d) return DASH;
  const diff = d.getTime() - now;
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat(intlTag(), { numeric: "auto", style: "short" });
  if (abs < 45_000) return translate("common.justNow");
  if (abs < 3_600_000) return rtf.format(Math.round(diff / 60_000), "minute");
  if (abs < 48 * 3_600_000) return rtf.format(Math.round(diff / 3_600_000), "hour");
  return rtf.format(Math.round(diff / 86_400_000), "day");
}

export function currentLocaleTag(): string {
  return intlTag(getLocale());
}
