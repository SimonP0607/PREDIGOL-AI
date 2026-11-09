/**
 * The market a link from Cuotas names (`/matches/7820?m=goals_over_under.FT.match#markets`): «Mercados» opens on its
 * category with that market open. A key the catalogue does not know is no target, and the tab opens as it always does.
 */
import { useRouterState } from "@tanstack/react-router";
import { targetOfKey, type MarketTarget } from "./marketLink";

export function useMarketTarget(): MarketTarget | null {
  const searchStr = useRouterState({ select: (s) => s.location.searchStr });
  return targetOfKey(new URLSearchParams(searchStr).get("m"));
}
