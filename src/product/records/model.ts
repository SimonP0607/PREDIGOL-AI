/**
 * The pure rules behind the product's records on screen: which selection is which, what a
 * result means, and the parlay slip a user is assembling (one leg per match, at most ten).
 */
import type {
  HistoryGroupKey,
  MarketKey,
  ParlayStatus,
  ResultStatus,
} from "@/lib/api/v1/types_records";

export const MAX_SLIP_LEGS = 10;
export const MIN_SLIP_LEGS = 2;
export const HISTORY_GROUPS: readonly HistoryGroupKey[] = [
  "predigol_picks",
  "my_picks",
  "predigol_parlays",
  "my_parlays",
] as const;

/** "2.50" / 2.5 / "2.5" are one line: compare lines as numbers, never as text. */
export function normLine(line: string | number | null | undefined): string {
  const n = Number(line ?? 0);
  return Number.isFinite(n) ? String(n === 0 ? 0 : n) : "0";
}

export interface SelectionRef {
  fixture_id: number;
  market_key: string;
  selection: string;
  line?: string | number | null | undefined;
}

export function selectionKey(s: SelectionRef): string {
  return `${s.fixture_id}|${s.market_key}|${s.selection}|${normLine(s.line)}`;
}

/** A quarter line (.25 / .75): a half-won leg has no clean meaning inside a parlay. */
export function isQuarterLine(line: string | number | null | undefined): boolean {
  const n = Math.abs(Number(line ?? 0) * 4);
  return Number.isFinite(n) && Math.round(n) % 2 === 1;
}

export type Tone = "pending" | "win" | "loss" | "neutral" | "live";

export function resultTone(status: ResultStatus): Tone {
  if (status === "WIN" || status === "HALF_WIN") return "win";
  if (status === "LOSS" || status === "HALF_LOSS") return "loss";
  if (status === "PUSH" || status === "VOID") return "neutral";
  return "pending";
}

export function parlayTone(status: ParlayStatus): Tone {
  if (status === "WON" || status === "PARTIAL_VOID") return "win";
  if (status === "LOST") return "loss";
  if (status === "VOID") return "neutral";
  if (status === "ACTIVE") return "live";
  return "pending";
}

/** A match that has kicked off cannot be saved, edited or added any more. */
export function hasStarted(
  m: { kickoff_at: string; status_group?: string | null | undefined },
  now: number = Date.now(),
): boolean {
  if (m.status_group && m.status_group !== "scheduled") return true;
  return Date.parse(m.kickoff_at) <= now;
}

// ── the slip ────────────────────────────────────────────────────────────────

export interface SlipLeg {
  key: string;
  fixture_id: number;
  market_key: MarketKey;
  selection: string;
  line: string;
  home: string;
  away: string;
  kickoff_at: string;
  /** The best price we showed when it was added (null: none known). */
  odds: string | null;
  bookmaker: string | null;
  /** PrediGol's probability for it when it was added (null or absent: not known). Shown, never sent to a model. */
  p_model?: string | null;
}

export type SlipAction =
  | { type: "toggle"; leg: Omit<SlipLeg, "key"> }
  | { type: "remove"; key: string }
  | { type: "clear" }
  | { type: "load"; legs: SlipLeg[] };

export interface SlipChange {
  legs: SlipLeg[];
  /** What happened, for the UI to say so: added, removed, replaced (same match), full. */
  effect: "added" | "removed" | "replaced" | "full" | "cleared" | "loaded";
}

/** One leg per match: adding a second selection of a match replaces the first. */
export function slipReduce(legs: readonly SlipLeg[], action: SlipAction): SlipChange {
  switch (action.type) {
    case "toggle": {
      const key = selectionKey(action.leg);
      if (legs.some((l) => l.key === key)) {
        return { legs: legs.filter((l) => l.key !== key), effect: "removed" };
      }
      const leg: SlipLeg = { ...action.leg, line: normLine(action.leg.line), key };
      const sameMatch = legs.findIndex((l) => l.fixture_id === leg.fixture_id);
      if (sameMatch >= 0) {
        const next = [...legs];
        next[sameMatch] = leg;
        return { legs: next, effect: "replaced" };
      }
      if (legs.length >= MAX_SLIP_LEGS) return { legs: [...legs], effect: "full" };
      return { legs: [...legs, leg], effect: "added" };
    }
    case "remove":
      return { legs: legs.filter((l) => l.key !== action.key), effect: "removed" };
    case "clear":
      return { legs: [], effect: "cleared" };
    case "load":
      return { legs: action.legs.slice(0, MAX_SLIP_LEGS), effect: "loaded" };
  }
}

const MARKETS: readonly string[] = ["1X2", "OU", "BTTS", "AH", "DC"];

/** A slip read back from storage: anything malformed is dropped, never trusted. */
export function parseSlip(raw: string | null): SlipLeg[] {
  if (!raw) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(data)) return [];
  const out: SlipLeg[] = [];
  for (const x of data as Array<Record<string, unknown>>) {
    if (
      typeof x !== "object" ||
      x === null ||
      typeof x["fixture_id"] !== "number" ||
      typeof x["market_key"] !== "string" ||
      !MARKETS.includes(x["market_key"]) ||
      typeof x["selection"] !== "string" ||
      typeof x["kickoff_at"] !== "string"
    ) {
      continue;
    }
    const leg = {
      fixture_id: x["fixture_id"],
      market_key: x["market_key"] as MarketKey,
      selection: x["selection"],
      line: normLine(x["line"] as string | number | undefined),
      home: typeof x["home"] === "string" ? x["home"] : "",
      away: typeof x["away"] === "string" ? x["away"] : "",
      kickoff_at: x["kickoff_at"],
      odds: typeof x["odds"] === "string" ? x["odds"] : null,
      bookmaker: typeof x["bookmaker"] === "string" ? x["bookmaker"] : null,
      p_model: typeof x["p_model"] === "string" ? x["p_model"] : null,
    };
    out.push({ ...leg, key: selectionKey(leg) });
  }
  return slipReduce([], { type: "load", legs: dedupe(out) }).legs;
}

function dedupe(legs: SlipLeg[]): SlipLeg[] {
  const seen = new Set<number>();
  return legs.filter((l) => (seen.has(l.fixture_id) ? false : (seen.add(l.fixture_id), true)));
}

/** The combined price of the legs that have one; null when any leg has none. */
export function slipOdds(legs: readonly SlipLeg[]): number | null {
  if (legs.length === 0) return null;
  let product = 1;
  for (const l of legs) {
    const o = l.odds === null ? NaN : Number(l.odds);
    if (!Number.isFinite(o) || o <= 1) return null;
    product *= o;
  }
  return Math.round(product * 1000) / 1000;
}
