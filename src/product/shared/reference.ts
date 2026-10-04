/** Pure helpers for the provider's reference lists (top lists, round calendar, provenance lines). */
import type { Leader, LeaderListName, Provenance, SeasonRound } from "@/lib/api/v1/types_center";

/** The figure a top list ranks by. */
export function leaderFigure(kind: LeaderListName, r: Leader): number | null {
  if (kind === "topscorers") return r.goals;
  if (kind === "topassists") return r.assists;
  if (kind === "topyellowcards") return r.yellow_cards;
  return r.red_cards;
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
