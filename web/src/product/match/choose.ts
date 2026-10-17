/** Choosing a shown price in the Match Center: the selection it stands for, before kick-off only. */
import type { Pickable } from "@/product/records/pickable";
import type { MatchCtx } from "./context";
import type { BestPrice } from "./model";

/**
 * What choosing a price saves or adds to the parlay; absent once the match is under way. Every price of the
 * Match Center is chosen the same way, the Cuotas board's (REVIEW PREDIGOL, points 6 and 18).
 */
export type Choose = (price: BestPrice) => Pickable;

/** Before kick-off: the selection a shown best price stands for. */
export function priceChooser(ctx: MatchCtx): Choose | undefined {
  if (ctx.phase !== "scheduled") return undefined;
  const m = ctx.match;
  return (p) => ({
    fixture_id: m.id,
    market_key: p.market as Pickable["market_key"],
    selection: p.selection,
    line: p.line,
    kickoff_at: m.kickoff_at,
    status_group: m.status_group,
    home: m.home.name,
    away: m.away.name,
    odds: p.odds,
    bookmaker: p.bookmaker,
  });
}
