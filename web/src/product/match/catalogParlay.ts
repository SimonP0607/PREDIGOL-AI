/**
 * Mi parlay with the catalogue's markets (plan EA, EA-503): which prices of «Mercados» the reader can add, read from what the server
 * says of each selection (C-14's `parlay.allowed`, the same rule the server applies when a leg comes in). Nothing is redrawn: a
 * catalogue market the server takes is chosen with the same pill as the five, and says what it settles with. With
 * FBI_PARLAY_MARKETS_V2 off the server marks nothing allowed, so every catalogue market stays shown only, as it was.
 */
import type { LegMarketKey } from "@/lib/api/v1/types_records";
import type { MarketProbs } from "@/lib/api/v1/types_stats";
import { present } from "@/lib/api/v1/types_intelligence";
import { fmtLine } from "@/lib/i18n/format";
import { normLine } from "@/product/records/model";
import { isCatalogueKey } from "@/product/shared/markets";
import type { Choose } from "./choose";
import { periodLabel, type MarketView } from "./marketCatalog";

export type SettlesWith = "score" | "stats" | "player";

export interface CatalogParlay {
  /** `key|selection|line` of every selection the server takes now. */
  allowed: ReadonlySet<string>;
  /** What each market (by key) settles with, from its rule (IA-070). */
  settles: ReadonlyMap<string, SettlesWith>;
}

export const NO_CATALOG_PARLAY: CatalogParlay = { allowed: new Set(), settles: new Map() };

export function selectionId(key: string, selection: string, line: number | string): string {
  return `${key}|${selection}|${normLine(line)}`;
}

/** A rule's key names what settles it: the score (goals, result), a player's line, or the match's statistics. */
export function settlesWith(ruleKey: string): SettlesWith {
  if (ruleKey.startsWith("goals") || ruleKey.startsWith("result")) return "score";
  if (ruleKey.startsWith("player")) return "player";
  return "stats";
}

export function catalogParlayOf(data: MarketProbs | null | undefined): CatalogParlay {
  if (!data) return NO_CATALOG_PARLAY;
  const allowed = new Set<string>();
  const settles = new Map<string, SettlesWith>();
  for (const m of data.markets.items) {
    if (!isCatalogueKey(m.key)) continue;
    let any = false;
    for (const s of m.selections) {
      if (!s.parlay.allowed) continue;
      allowed.add(selectionId(m.key, s.selection, s.line));
      any = true;
    }
    const rule = present(m.rule_key);
    if (any && rule) settles.set(m.key, settlesWith(rule));
  }
  return { allowed, settles };
}

/** The views of a category, a catalogue market the server takes marked so (the five keep theirs). */
export function withCatalogParlay(views: MarketView[], cp: CatalogParlay): MarketView[] {
  if (cp.allowed.size === 0) return views;
  return views.map((v) => {
    if (v.parlay !== null || !v.key) return v;
    const settles = cp.settles.get(v.key);
    const any = [...cp.allowed].some((id) => id.startsWith(`${v.key}|`));
    return any && settles ? { ...v, catalogParlay: settles } : v;
  });
}

/**
 * Choosing a price of a catalogue market the server takes: the selection under the catalogue's key, whether the server takes
 * that one now, and the words the page shows for it (they go with the leg to the slip). Other views keep `choose` as it is.
 */
export function catalogChooser(
  choose: Choose | undefined,
  view: MarketView,
  cp: CatalogParlay,
): Choose | undefined {
  if (!choose || !view.catalogParlay) return choose;
  const marketLabel =
    view.period && view.period !== periodLabel("FT")
      ? `${view.title} · ${view.period}`
      : view.title;
  return (price) => {
    const column =
      view.columns.find((c) => c.selection === price.selection)?.label ?? price.selection;
    const line =
      view.lines === null || price.line === 0 ? "" : fmtLine(price.line, view.lines === "ah");
    return {
      ...choose(price),
      market_key: view.key as LegMarketKey,
      parlay_allowed: cp.allowed.has(selectionId(view.key, price.selection, price.line)),
      label: line ? `${column} ${line}` : column,
      market_label: marketLabel,
    };
  };
}
