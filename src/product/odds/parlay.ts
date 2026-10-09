/**
 * "Mi parlay" from a price on screen: which selections can go in, and the leg each source adds.
 *
 * A selection can be added when its market is one a parlay takes, it has a real price, its line is not a
 * quarter line (.25 / .75: a half-won leg has no clean meaning inside a parlay) and its match has not kicked
 * off. The slip itself keeps one leg per match: adding a second selection of a match replaces the first
 * (records/model.ts), so nothing here has to.
 */
import type { BestHighlight, BestMarket, BestOddsFixture } from "@/lib/api/v1/types_product";
import { toNumber } from "@/lib/i18n/format";
import { hasStarted, isQuarterLine, normLine, type SlipLeg } from "@/product/records/model";
import { MARKETS, type MarketKey } from "@/product/shared/markets";
import type { PriceSlot } from "./board";

/** A leg as it is handed to the slip (the slip gives it its key). */
export type NewLeg = Omit<SlipLeg, "key">;

/** Why a selection cannot be added now: an unknown market, no price, a quarter line, kicked off. */
export type ParlayBlock = "market" | "no_price" | "quarter" | "started";

export interface ParlayCandidate {
  market_key: string;
  odds: string | number | null | undefined;
  line: string | number | null | undefined;
  kickoff_at: string;
  status_group?: string | null | undefined;
}

export function isParlayMarket(market: string): market is MarketKey {
  return (MARKETS as readonly string[]).includes(market);
}

/** Null when the selection can be added to the parlay now; otherwise why not. */
export function parlayBlock(sel: ParlayCandidate, now: number = Date.now()): ParlayBlock | null {
  if (!isParlayMarket(sel.market_key)) return "market";
  const odds = toNumber(sel.odds);
  if (odds === null || odds <= 1) return "no_price";
  if (isQuarterLine(sel.line)) return "quarter";
  if (hasStarted({ kickoff_at: sel.kickoff_at, status_group: sel.status_group }, now)) {
    return "started";
  }
  return null;
}

/** The leg a board price adds: the best price of that selection, at the market's line. */
export function slotLeg(
  fixture: Pick<BestOddsFixture, "fixture_id" | "kickoff_at" | "home" | "away">,
  market: Pick<BestMarket, "market_key" | "line">,
  slot: PriceSlot,
): NewLeg | null {
  if (!slot.price || !isParlayMarket(market.market_key)) return null;
  return {
    fixture_id: fixture.fixture_id,
    market_key: market.market_key,
    selection: slot.selection,
    line: normLine(market.line),
    home: fixture.home.name,
    away: fixture.away.name,
    kickoff_at: fixture.kickoff_at,
    odds: slot.price.best_odds,
    bookmaker: slot.price.bookmaker,
    p_model: null,
  };
}

/** The leg a "best price against the market" card adds. */
export function highlightLeg(h: BestHighlight): NewLeg | null {
  if (!isParlayMarket(h.market_key)) return null;
  return {
    fixture_id: h.fixture_id,
    market_key: h.market_key,
    selection: h.price.selection,
    line: normLine(h.line),
    home: h.home.name,
    away: h.away.name,
    kickoff_at: h.kickoff_at,
    odds: h.price.best_odds,
    bookmaker: h.price.bookmaker,
    p_model: null,
  };
}
