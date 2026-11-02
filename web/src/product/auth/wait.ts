/**
 * How long to wait before trying again, in words (plan UX, A1, defect F01): the sign-in page always said "60 s",
 * whatever the lock really was (15 minutes, doubling with every further block of failures up to a day). The API sends
 * the seconds left, rounded up (Retry-After and error.retry_after); this says them in minutes, and in hours and
 * minutes from an hour on.
 */
import { t } from "@/lib/i18n";
import { fmtInt } from "@/lib/i18n/format";

export function waitText(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds <= 0)
    return t("errors.wait.unknown");
  if (seconds < 60) return t("errors.wait.lessThanMinute");
  // The API rounds the seconds up by one (never "0"): a fresh 15-minute lock answers 901 and is said "15 minutos".
  const minutes = Math.max(1, Math.ceil((seconds - 1) / 60));
  if (minutes < 60) return t("errors.wait.minutes", { count: minutes, n: fmtInt(minutes) });
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (rest === 0) return t("errors.wait.hours", { count: hours, n: fmtInt(hours) });
  return t("errors.wait.hoursMinutes", { h: fmtInt(hours), m: fmtInt(rest) });
}

/** "Demasiados intentos. Espera 15 minutos y vuelve a probar." */
export function tooManyAttempts(seconds: number | null): string {
  return t("errors.code.too_many_attempts", { wait: waitText(seconds) });
}
