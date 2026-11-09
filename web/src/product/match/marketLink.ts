/**
 * From a market of Cuotas to the same market in the match's «Mercados» (plan Cuotas, phase 6: «Abrir partido» opens the
 * market the reader was looking at). Cuotas names a market by its `tax-v3` key and period (`goals.total`, `1H`); the
 * match's catalogue by `code.period.subject` (`goals_over_under.1H.match`) inside a category. `marketLinks.json` is the
 * table between them, made from the taxonomy (a backend test keeps it in step): only the markets the catalogue structures
 * have a row, and the others open «Mercados» without a market.
 */
import links from "./marketLinks.json";
import { CATALOG_CATEGORIES, type CatalogCategory } from "@/lib/api/v1/types_market_catalog";

export interface MarketTarget {
  /** The category chip that holds the market. */
  category: CatalogCategory;
  /** The catalogue's key of the market: what the address carries (`?m=`). */
  key: string;
}

const BY_TAX = new Map<string, MarketTarget>();
const BY_KEY = new Map<string, MarketTarget>();

for (const l of links.links) {
  const category = CATALOG_CATEGORIES.find((c) => c === l.category);
  if (!category) continue;
  const target = { category, key: l.catalog };
  BY_TAX.set(`${l.key}|${l.period}`, target);
  BY_KEY.set(l.catalog, target);
}

/** The match's market for a market of Cuotas at a period; null when the catalogue does not structure it. */
export function catalogTarget(marketKey: string, period: string): MarketTarget | null {
  return BY_TAX.get(`${marketKey}|${period}`) ?? null;
}

/** What an address names (`?m=goals_over_under.FT.match`); null for a key the catalogue does not know. */
export function targetOfKey(key: string | null | undefined): MarketTarget | null {
  return key ? (BY_KEY.get(key) ?? null) : null;
}
