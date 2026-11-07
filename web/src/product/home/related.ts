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

/** The id of a pick's card in the day's picks, the target of the notice in «Para ti». */
export const pickAnchor = (rank: number): string => `pick-${rank}`;

/** The day's picks that are the reader's, by rank - for the chip on the general card and the anchor of the notice. */
export function mineByRank(
  picks: RelatedPicks | null | undefined,
): ReadonlyMap<number, RelatedPick> {
  return new Map((picks?.items ?? []).map((r) => [r.rank, r]));
}

/** Why a pick is the reader's, in the order a chip says it: their team, their player, their league, their market. */
export type MineKind = "team" | "player" | "league" | "market";

export interface MineReason {
  kind: MineKind;
  /** The team, player, league or market named (the ones that apply to this pick). */
  names: string[];
}

export function mineReasons(r: RelatedPick, marketLabel: string): MineReason[] {
  const out: MineReason[] = [];
  if (r.followed?.kind === "team") out.push({ kind: "team", names: r.followed.names });
  if (r.players && r.players.length > 0) out.push({ kind: "player", names: r.players });
  if (r.followed?.kind === "league") out.push({ kind: "league", names: r.followed.names });
  if (r.market_followed) out.push({ kind: "market", names: [marketLabel] });
  return out;
}

/** Takes the reader to a pick's card and marks it for a moment. Nothing when the card is not on the page. */
export function goToPick(rank: number): void {
  if (typeof document === "undefined") return;
  const card = document.getElementById(pickAnchor(rank));
  if (!card) return;
  card.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
  card.setAttribute("data-highlight", "true");
  window.setTimeout(() => card.removeAttribute("data-highlight"), 2500);
}
