/**
 * The judgements of «Salud de cuotas» (plan Cuotas, section 6.6), pure. The thresholds are the plan's acceptance criteria:
 * the daily quota under 45 % of the plan, prices of the last six hours a median of 70 minutes old or less, no row in a
 * DEFAULT partition, `odds_quotes` under its brake.
 */
import { t } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";

export type Tone = "default" | "positive" | "negative" | "warning" | "muted";

/** The plan's ceiling for the day (a share of our daily budget). */
export const QUOTA_TARGET = 0.45;
/** The plan's target for the prices of matches that start within six hours. */
export const NEAR_AGE_TARGET_MIN = 70;

export function quotaTone(used: number, limit: number): Tone {
  if (!limit) return "muted";
  const share = used / limit;
  return share >= 0.9 ? "negative" : share > QUOTA_TARGET ? "warning" : "default";
}

/** The extractor behind by an hour is worth a look; by three, something stopped. */
export function lagTone(minutes: number | null): Tone {
  if (minutes === null) return "muted";
  return minutes > 180 ? "negative" : minutes > 60 ? "warning" : "default";
}

export function brakeTone(gb: number, brake: number): Tone {
  if (!brake) return "muted";
  return gb >= brake ? "negative" : gb >= brake * 0.8 ? "warning" : "default";
}

/** Only the last six hours have a target (the plan's 70 minutes); the farther horizons are shown, not judged. */
export function horizonAgeTone(horizon: string, medianMinutes: number | null): Tone {
  if (horizon !== "0-6h" || medianMinutes === null) return "default";
  return medianMinutes > NEAR_AGE_TARGET_MIN ? "warning" : "positive";
}

/** «45 min», «3 h 20 min», «26 h». */
export function ageText(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return t("truth.oddsHealth.age.minutes", { n: localInt(m) });
  const hours = Math.floor(m / 60);
  const rest = m % 60;
  if (hours >= 10 || rest === 0) return t("truth.oddsHealth.age.hours", { n: localInt(hours) });
  return t("truth.oddsHealth.age.hoursMinutes", { h: localInt(hours), m: localInt(rest) });
}
