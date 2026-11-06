/** The day's picks that are the reader's (closing plan 3.2): the cards Inicio already shows, picked out by rank. */
import type { RelatedPick, RelatedPicks } from "@/lib/api/v1/types_me_today";
import type { DailyItem } from "@/lib/api/v1/types_records";

export interface RelatedCard {
  related: RelatedPick;
  item: DailyItem;
}

/**
 * Each related pick with the card of the day's set it points at. The API names a pick by its rank and its match; a card the board
 * no longer has under that rank and match (the set moved on between two reads) is left out - never made up, never another's.
 */
export function relatedCards(picks: RelatedPicks, items: readonly DailyItem[]): RelatedCard[] {
  const byRank = new Map(items.map((i) => [i.rank, i]));
  return picks.items.flatMap((related) => {
    const item = byRank.get(related.rank);
    return item && item.match.fixture_id === related.fixture_id ? [{ related, item }] : [];
  });
}
