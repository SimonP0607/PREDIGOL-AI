/**
 * A match's state as the reader understands it.
 *
 * The fixture feed speaks in short codes ("1H", "HT"), the in-play odds feed in long
 * words ("First Half", "Halftime", "Not Started"). Both end up here as one short code
 * and a phase, so every screen shows the same thing for the same moment.
 */
import { t, translateOr } from "@/lib/i18n";

export type Phase =
  /** Not kicked off yet (or time still to be defined). */
  | "pre"
  /** Ball rolling: first/second half, extra time. */
  | "play"
  /** A break inside the match: half-time, break before extra time. */
  | "pause"
  /** Penalty shoot-out in progress. */
  | "pens"
  /** Interrupted or suspended by the referee. */
  | "stopped"
  /** Over: full time, after extra time, after penalties, awarded. */
  | "over"
  | "unknown";

const SHORT_CODES = new Set([
  "TBD",
  "NS",
  "1H",
  "HT",
  "2H",
  "ET",
  "BT",
  "P",
  "SUSP",
  "INT",
  "LIVE",
  "FT",
  "AET",
  "PEN",
  "PST",
  "CANC",
  "ABD",
  "AWD",
  "WO",
]);

const LONG_TO_SHORT: Record<string, string> = {
  "time to be defined": "TBD",
  "not started": "NS",
  "first half": "1H",
  "1st half": "1H",
  "first half, kick off": "1H",
  "kick off": "1H",
  halftime: "HT",
  "half time": "HT",
  "half-time": "HT",
  "second half": "2H",
  "2nd half": "2H",
  "second half, 2nd half started": "2H",
  "extra time": "ET",
  "break time": "BT",
  "penalty in progress": "P",
  penalties: "P",
  "match suspended": "SUSP",
  suspended: "SUSP",
  "match interrupted": "INT",
  interrupted: "INT",
  "in progress": "LIVE",
  live: "LIVE",
  "match finished": "FT",
  finished: "FT",
  "match finished after extra time": "AET",
  "match finished after penalty": "PEN",
  "match finished after penalties": "PEN",
  "match postponed": "PST",
  "match cancelled": "CANC",
  "match abandoned": "ABD",
  "technical loss": "AWD",
  walkover: "WO",
};

const PHASE: Record<string, Phase> = {
  TBD: "pre",
  NS: "pre",
  "1H": "play",
  "2H": "play",
  ET: "play",
  LIVE: "play",
  HT: "pause",
  BT: "pause",
  P: "pens",
  SUSP: "stopped",
  INT: "stopped",
  FT: "over",
  AET: "over",
  PEN: "over",
  AWD: "over",
  WO: "over",
  CANC: "over",
  ABD: "over",
};

/** "Halftime" -> "HT", "First Half" -> "1H", "2h" -> "2H"; unknown words come back upper-cased. */
export function shortStatus(raw: string | null | undefined): string {
  const s = (raw ?? "").trim();
  if (!s || s === "?") return "";
  const upper = s.toUpperCase();
  if (SHORT_CODES.has(upper)) return upper;
  return LONG_TO_SHORT[s.toLowerCase()] ?? upper;
}

export function phaseOf(short: string): Phase {
  return PHASE[short] ?? "unknown";
}

/** Being played right now, breaks included. */
export function isInPlay(short: string): boolean {
  const p = phaseOf(short);
  return p === "play" || p === "pause" || p === "pens" || p === "stopped";
}

/** 67' / 45+2' - or null when the minute is not known (or the clock has not started). */
export function minuteText(
  elapsed: number | null | undefined,
  extra: number | null | undefined,
): string | null {
  if (elapsed === null || elapsed === undefined || elapsed <= 0) return null;
  return `${elapsed}${extra ? `+${extra}` : ""}'`;
}

/** A short label for a narrow column: 67', 45+2' - or Desc. / HT, 1T / 1H... when no minute fits. */
export function liveLabel(
  status: string | null | undefined,
  elapsed: number | null | undefined,
  extra: number | null | undefined,
): string {
  const short = shortStatus(status);
  const phase = phaseOf(short);
  const clock = translateOr(`matches.clock.${short}`, t("matches.clock.LIVE"));
  if (phase === "pause" || phase === "pens" || phase === "stopped") return clock;
  return minuteText(elapsed, extra) ?? clock;
}
