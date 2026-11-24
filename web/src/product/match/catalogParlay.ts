/**
 * Mi parlay with the catalogue's markets (plan EA, EA-503): which prices of «Mercados» the reader can add, read from what the server
 * says of each selection (C-14's `parlay.allowed`, the same rule the server applies when a leg comes in). Nothing is redrawn: a
 * catalogue market the server takes is chosen with the same pill as the five, and says what it settles with. With
 * FBI_PARLAY_MARKETS_V2 off the server marks nothing allowed, so every catalogue market stays shown only, as it was.
 */
import type { LegMarketKey } from "@/lib/api/v1/types_records";
import type { MarketProbs } from "@/lib/api/v1/types_stats";
import { present } from "@/lib/api/v1/types_intelligence";
import type { MatrixMode } from "@/lib/api/v1/types_auth";
import type { MatchAvailability } from "@/lib/api/v1/types_availability";
import { parlayAllowed, parlayRefusal } from "@/product/shared/matrixModules";
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
  /** Why the server does not take a selection (`key|selection|line`), when it says so. */
  reasons?: ReadonlyMap<string, string>;
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

/**
 * `matrix` (PM-14-04, FBI_MATRIX_PARLAY): with `on` and C-16 answering, a selection the server takes is taken only if C-16 does not
 * refuse its whole market; off or show, `allowed` is exactly what C-14 says (the default).
 */
export function catalogParlayOf(
  data: MarketProbs | null | undefined,
  matrix?: { mode: MatrixMode; availability: MatchAvailability | null },
): CatalogParlay {
  if (!data) return NO_CATALOG_PARLAY;
  const allowed = new Set<string>();
  const settles = new Map<string, SettlesWith>();
  const reasons = new Map<string, string>();
  for (const m of data.markets.items) {
    if (!isCatalogueKey(m.key)) continue;
    let any = false;
    const verdictOf =
      matrix && matrix.mode === "on"
        ? matrix.availability?.markets.find((x) => x.key === m.key)
        : undefined;
    for (const s of m.selections) {
      if (!parlayAllowed(s.parlay.allowed, verdictOf, matrix?.mode ?? "off")) {
        reasons.set(
          selectionId(m.key, s.selection, s.line),
          s.parlay.allowed ? (parlayRefusal(verdictOf) ?? s.parlay.reason) : s.parlay.reason,
        );
        continue;
      }
      allowed.add(selectionId(m.key, s.selection, s.line));
      any = true;
    }
    const rule = present(m.rule_key);
    if (any && rule) settles.set(m.key, settlesWith(rule));
  }
  return { allowed, settles, reasons };
}

/**
 * Why a catalogue market is only for consulting (AP-P09): the reason the server gives for most of its selections, as a code
 * of `stats.parlay.*`; null when it gives none (the page then says it is only for consulting, without a motive).
 */
export function lookupReasonOf(view: MarketView, cp: CatalogParlay): string | null {
  if (!view.key || !cp.reasons) return null;
  const count = new Map<string, number>();
  for (const [id, reason] of cp.reasons) {
    if (id.startsWith(`${view.key}|`) && reason !== "ok")
      count.set(reason, (count.get(reason) ?? 0) + 1);
  }
  let best: string | null = null;
  let n = 0;
  for (const [reason, c] of count) {
    if (c > n) {
      best = reason;
      n = c;
    }
  }
  return best;
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
      parlay_reason: cp.reasons?.get(selectionId(view.key, price.selection, price.line)),
      label: line ? `${column} ${line}` : column,
      market_label: marketLabel,
    };
  };
}
