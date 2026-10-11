/**
 * The automatic parlay builder's form (REVIEW PREDIGOL, point 15): what the user is looking for, checked here before
 * it is asked, turned into the query - and the legs PrediGol answered with, ready for "Mi parlay".
 *
 * The filters only narrow what PrediGol's own parlay rule chooses from (the server, fbi.parlays.builder): they can
 * leave a parlay out, never let in a selection that does not pass the rule.
 */
import type { BuilderLeg, BuilderQuery, BuildReason } from "@/lib/api/v1/types_builder";
import type { MarketKey } from "@/lib/api/v1/types_records";
import { normLine, selectionKey, type SlipLeg } from "@/product/records/model";

export const BUILDER_HOURS: readonly number[] = [6, 12, 24, 48, 72];
export const BUILDER_MIN_LEGS = 2;
export const BUILDER_MAX_LEGS = 7;

export interface BuilderForm {
  hours: number;
  minLegs: number;
  maxLegs: number;
  /** None: every market. */
  markets: MarketKey[];
  /** None: every competition. */
  competitions: number[];
  /** As typed ("1,5" or "1.5"); empty: no limit. */
  minOdds: string;
  maxOdds: string;
  maxTotal: string;
}

export const DEFAULT_BUILDER: BuilderForm = {
  hours: 24,
  minLegs: 2,
  maxLegs: 4,
  markets: [],
  competitions: [],
  minOdds: "",
  maxOdds: "",
  maxTotal: "",
};

export type FormIssue = "minOdds" | "maxOdds" | "oddsOrder" | "maxTotal" | "legs";

/** A price as typed, with a comma or a point: null when empty, NaN when it is not a price at all. */
export function parsePrice(text: string): number | null {
  const s = text.trim().replace(",", ".");
  if (!s) return null;
  if (!/^\d+(\.\d+)?$/.test(s)) return Number.NaN;
  return Number(s);
}

/** What stops the form from being asked: a price that is not one (or not above 1), min above max, the legs. */
export function formIssues(f: BuilderForm): FormIssue[] {
  const out: FormIssue[] = [];
  const lo = parsePrice(f.minOdds);
  const hi = parsePrice(f.maxOdds);
  const total = parsePrice(f.maxTotal);
  if (lo !== null && (Number.isNaN(lo) || lo < 1.01 || lo > 1000)) out.push("minOdds");
  if (hi !== null && (Number.isNaN(hi) || hi < 1.01 || hi > 1000)) out.push("maxOdds");
  if (lo !== null && hi !== null && !Number.isNaN(lo) && !Number.isNaN(hi) && lo > hi) {
    out.push("oddsOrder");
  }
  if (total !== null && (Number.isNaN(total) || total <= 1 || total > 100000)) out.push("maxTotal");
  if (!(BUILDER_MIN_LEGS <= f.minLegs && f.minLegs <= f.maxLegs && f.maxLegs <= BUILDER_MAX_LEGS)) {
    out.push("legs");
  }
  return out;
}

function price(text: string): string | undefined {
  const n = parsePrice(text);
  return n === null || Number.isNaN(n) ? undefined : String(n);
}

/** The query for a valid form, its sets in a canonical order: the same request is the same cache entry. */
export function toBuilderQuery(f: BuilderForm): BuilderQuery {
  return {
    hours: f.hours,
    min_legs: f.minLegs,
    max_legs: f.maxLegs,
    market: f.markets.length ? [...new Set(f.markets)].sort() : undefined,
    competition_id: f.competitions.length
      ? [...new Set(f.competitions)].sort((a, b) => a - b)
      : undefined,
    min_odds: price(f.minOdds),
    max_odds: price(f.maxOdds),
    max_total_odds: price(f.maxTotal),
  };
}

/** Changing the minimum pulls the maximum up with it, and the other way round: never an impossible pair. */
export function withLegs(f: BuilderForm, which: "min" | "max", n: number): BuilderForm {
  const v = Math.max(BUILDER_MIN_LEGS, Math.min(BUILDER_MAX_LEGS, Math.round(n)));
  if (which === "min") return { ...f, minLegs: v, maxLegs: Math.max(f.maxLegs, v) };
  return { ...f, maxLegs: v, minLegs: Math.min(f.minLegs, v) };
}

/** Toggle one item of a multi-choice filter (none chosen means all). */
export function toggled<T>(items: readonly T[], item: T): T[] {
  return items.includes(item) ? items.filter((x) => x !== item) : [...items, item];
}

/** The answer's legs as "Mi parlay" holds them: the user can change them there before saving. */
export function builtToSlip(legs: readonly BuilderLeg[]): SlipLeg[] {
  return legs.map((l) => {
    const leg = {
      fixture_id: l.fixture_id,
      market_key: l.market_key as MarketKey,
      selection: l.selection,
      line: normLine(l.line),
      home: l.home.name,
      away: l.away.name,
      kickoff_at: l.kickoff_at,
      odds: l.odds,
      bookmaker: l.bookmaker,
      p_model: l.p_model,
    };
    return { ...leg, key: selectionKey(leg) };
  });
}

/** What the user can change when there is no parlay: the advice follows the reason. */
export function adviceFor(reason: BuildReason | null): "widen" | "filters" | "cap" | "wait" {
  switch (reason) {
    case "no_match":
      return "filters";
    case "total_odds_cap":
      return "cap";
    case "too_few_legs":
    case "no_growth":
      return "widen";
    default:
      return "wait";
  }
}

/** The legs as the save request sends them: the server prices them at the moment they are saved. */
export function legsBody(legs: readonly BuilderLeg[]) {
  return legs.map((l) => ({
    fixture_id: l.fixture_id,
    market_key: l.market_key as MarketKey,
    selection: l.selection,
    line: normLine(l.line),
  }));
}
