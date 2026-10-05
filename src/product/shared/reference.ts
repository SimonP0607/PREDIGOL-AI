/** Pure helpers for the provider's reference lists (top lists, round calendar, provenance lines). */
import type { Leader, LeaderListName, Provenance, SeasonRound } from "@/lib/api/v1/types_center";

/** The figure a top list ranks by. */
export function leaderFigure(kind: LeaderListName, r: Leader): number | null {
  if (kind === "topscorers") return r.goals;
  if (kind === "topassists") return r.assists;
  if (kind === "topyellowcards") return r.yellow_cards;
  return r.red_cards;
}

/** Whether the provider's season rating of a leader counts matches it did not rate (sent as 0) as 0. */
export function ratingCountsUnrated(r: Leader): boolean {
  return r.unrated_matches > 0;
}

/** A round's first and last date (the provider lists every day a match of the round is played). */
export function roundSpan(r: SeasonRound): [string, string] | null {
  if (!r.dates.length) return null;
  const sorted = [...r.dates].sort();
  return [sorted[0] ?? "", sorted[sorted.length - 1] ?? ""];
}

/** The parts of a provenance line, in order: source, payload, fetched, asked. */
export function provenanceParts(p: Provenance): { key: string; value: string }[] {
  const out = [{ key: "source", value: p.source }];
  if (p.payload_hash) out.push({ key: "payload", value: p.payload_hash.slice(0, 12) });
  if (p.observed_at) out.push({ key: "fetched", value: p.observed_at });
  if (p.checked_at) out.push({ key: "asked", value: p.checked_at });
  return out;
}

/** Seasons as the provider lists them, newest first: "2026–2022" when consecutive, else "2026, 2024, 2021". */
export function careerSpan(seasons: number[]): string {
  const ys = [...new Set(seasons)].sort((a, b) => b - a);
  if (ys.length === 0) return "";
  const consecutive = ys.every((y, i) => i === 0 || (ys[i - 1] ?? y) - y === 1);
  if (consecutive && ys.length > 2) return `${ys[0]}–${ys[ys.length - 1]}`;
  return ys.join(", ");
}
