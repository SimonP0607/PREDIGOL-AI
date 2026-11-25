/**
 * "Mi parlay" from a price on screen: which selections can go in, and the leg each source adds.
 *
 * A selection can be added when its market is one a parlay takes, it has a real price that is not an outlier
 * (more than 25 % above fair: one book's stale or mistaken quote - the server refuses it too), its line is not a
 * quarter line (.25 / .75: a half-won leg has no clean meaning inside a parlay) and its match has not kicked
 * off. The slip itself keeps one leg per match: adding a second selection of a match replaces the first
 * (records/model.ts), so nothing here has to.
 */
import { toNumber } from "@/lib/i18n/format";
import { hasStarted, isQuarterLine, normLine, type SlipLeg } from "@/product/records/model";
import type { Pickable } from "@/product/records/pickable";
import { isCatalogueKey, MARKETS, type MarketKey } from "@/product/shared/markets";

/** A leg as it is handed to the slip (the slip gives it its key). */
export type NewLeg = Omit<SlipLeg, "key">;

/** Why a selection cannot be added now: an unknown market (or a catalogue one the server does not mark parlayable), no price, an outlier price, a quarter line, kicked off. */
export type ParlayBlock = "market" | "no_price" | "outlier" | "quarter" | "started";

export interface ParlayCandidate {
  market_key: string;
  odds: string | number | null | undefined;
  line: string | number | null | undefined;
  kickoff_at: string;
  status_group?: string | null | undefined;
  /** The price is flagged an outlier (`BestPrice.outlier`): shown, never added. */
  outlier?: boolean | null | undefined;
  /** A catalogue market's selection: the server marks it parlayable now (C-14). Without it, a catalogue market is never added. */
  parlay_allowed?: boolean | null | undefined;
}

export function isParlayMarket(market: string): market is MarketKey {
  return (MARKETS as readonly string[]).includes(market);
}

/** Null when the selection can be added to the parlay now; otherwise why not. */
export function parlayBlock(sel: ParlayCandidate, now: number = Date.now()): ParlayBlock | null {
  const catalogue = isCatalogueKey(sel.market_key) && sel.parlay_allowed === true;
  if (!isParlayMarket(sel.market_key) && !catalogue) return "market";
  const odds = toNumber(sel.odds);
  if (odds === null || odds <= 1) return "no_price";
  if (sel.outlier) return "outlier";
  if (isQuarterLine(sel.line)) return "quarter";
  if (hasStarted({ kickoff_at: sel.kickoff_at, status_group: sel.status_group }, now)) {
    return "started";
  }
  return null;
}

/** The leg a shown price adds to the slip; null without a price. */
export function pickableLeg(sel: Pickable): NewLeg | null {
  if (!sel.odds) return null;
  return {
    fixture_id: sel.fixture_id,
    market_key: sel.market_key,
    selection: sel.selection,
    line: normLine(sel.line),
    home: sel.home,
    away: sel.away,
    kickoff_at: sel.kickoff_at,
    odds: sel.odds,
    bookmaker: sel.bookmaker,
    p_model: sel.p_model ?? null,
    ...(sel.label ? { label: sel.label } : {}),
    ...(sel.market_label ? { market_label: sel.market_label } : {}),
  };
}
