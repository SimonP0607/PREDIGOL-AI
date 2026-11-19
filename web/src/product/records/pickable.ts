/** What a selection needs to be saved or added to a parlay, from wherever it is shown. */
import type { PickCard } from "@/lib/api/v1/types_product";
import type { DailyItem, LegMarketKey, MarketKey } from "@/lib/api/v1/types_records";

export interface Pickable {
  fixture_id: number;
  market_key: LegMarketKey;
  selection: string;
  line: string | number;
  kickoff_at: string;
  status_group?: string | null | undefined;
  home: string;
  away: string;
  /** The price shown with it, if any. */
  odds: string | null;
  bookmaker: string | null;
  /** Set when it is one of PrediGol's picks. */
  pick_id?: number | null | undefined;
  /** PrediGol's probability for it, when the source has one: shown in "Mi parlay", never sent to a model. */
  p_model?: string | null | undefined;
  /**
   * A catalogue market's price (plan EA, EA-503): whether the server marks it parlayable now (C-14's `parlay.allowed`), and
   * its words as the page shows them. Absent on the five markets, which keep their own rules.
   */
  parlay_allowed?: boolean | undefined;
  /** Why the server does not take it (C-14's `parlay.reason`), said to the reader beside the price. */
  parlay_reason?: string | undefined;
  label?: string | undefined;
  market_label?: string | undefined;
}

export function pickableOfItem(item: DailyItem): Pickable {
  return {
    fixture_id: item.match.fixture_id,
    market_key: item.market_key as MarketKey,
    selection: item.selection,
    line: item.line,
    kickoff_at: item.match.kickoff_at,
    status_group: item.match.status_group,
    home: item.match.home.name,
    away: item.match.away.name,
    odds: item.odds,
    bookmaker: item.bookmaker,
    pick_id: item.pick_id,
    p_model: item.p_model,
  };
}

export function pickableOfCard(pick: PickCard): Pickable {
  return {
    fixture_id: pick.fixture_id,
    market_key: pick.market_key as MarketKey,
    selection: pick.selection,
    line: pick.line,
    kickoff_at: pick.kickoff_at,
    home: pick.home.name,
    away: pick.away.name,
    odds: pick.best_odds,
    bookmaker: pick.bookmaker,
    pick_id: pick.pick_id,
    p_model: pick.p_model,
  };
}
