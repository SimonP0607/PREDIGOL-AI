/**
 * What a save of the favourites tells the product's analytics (plan UX, A6; 3.1): one `favorite_added` or
 * `favorite_removed` per league, team, player or market that changed - the catalog's own properties only: a kind and an id,
 * or for a market its key (it has no id). Never a name, never free text.
 */
import { track } from "@/lib/track";
import type { Change } from "./model";

function props(c: Change) {
  return c.kind === "market" ? { kind: c.kind, market: c.market } : { kind: c.kind, id: c.id };
}

export function trackChanges(changed: {
  added: readonly Change[];
  removed: readonly Change[];
}): void {
  for (const c of changed.added) track("favorite_added", props(c));
  for (const c of changed.removed) track("favorite_removed", props(c));
}
