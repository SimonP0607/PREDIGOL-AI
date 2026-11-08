/**
 * Mi Parlay from the explorer: the same rules as today (plan Cuotas, section 5 and decision 6). Only a price the API marks
 * `parlay_ok` can be tapped in - one of the five classic markets, for the match and the full time, not a quarter line, not
 * an outlier, its row not stale and the match not started -; every other price is «Solo consulta». The slip itself keeps one
 * leg per match. Pure.
 */
import { t } from "@/lib/i18n";
import { fmtOdds, toNumber } from "@/lib/i18n/format";
import { isQuarterLine, normLine, type SlipLeg } from "@/product/records/model";
import { selectionLabel as classicLabel } from "@/product/shared/markets";
import type { NewLeg } from "../parlay";
import { classicMarket, shapeOf } from "./markets";
import type { OddsBoardRow, OddsMarketInfo, OddsSelectionPrice } from "./model";
import { ownLine } from "./selections";

/**
 * Why a price cannot be tapped into the parlay, or null when it can: a market the parlay does not take (lookup), a stale
 * row, an outlier, a quarter line, a match under way, or the API's own refusal (server).
 */
export type PriceBlock = "lookup" | "stale" | "outlier" | "quarter" | "started" | "server";

export function priceBlock(
  info: Pick<OddsMarketInfo, "key" | "kind" | "subject" | "parlay">,
  period: string,
  row: Pick<OddsBoardRow, "kickoff_at" | "state" | "line">,
  sel: Pick<OddsSelectionPrice, "parlay_ok" | "outlier" | "line" | "selection">,
  now: number = Date.now(),
): PriceBlock | null {
  if (classicMarket(info, period) === null) return "lookup";
  if (row.state === "stale") return "stale";
  if (sel.outlier) return "outlier";
  if (isQuarterLine(ownLine(shapeOf(info), sel, row.line))) return "quarter";
  if (Date.parse(row.kickoff_at) <= now) return "started";
  return sel.parlay_ok ? null : "server";
}

/** Whether a market can put anything in the parlay at all: the card says «Solo consulta» once, not on every row. */
export function marketTakesParlay(
  info: Pick<OddsMarketInfo, "key" | "subject" | "parlay">,
  period: string,
): boolean {
  return classicMarket(info, period) !== null;
}

/** The words for a block, as a hint and for a screen reader (null: nothing to say). */
export function blockText(block: PriceBlock | null): string | null {
  switch (block) {
    case "lookup":
    case "server":
      return t("explorer.parlay.lookup");
    case "stale":
      return t("explorer.parlay.stale");
    case "outlier":
      return t("odds.parlay.outlier");
    case "quarter":
      return t("records.actions.quarterLine");
    case "started":
      return t("records.actions.started");
    default:
      return null;
  }
}

/**
 * The leg a price adds: the slip's market key, the selection at its own line (an Asian handicap's away side at -h), the
 * price on show and its bookmaker. Null for a market the parlay does not take.
 */
export function explorerLeg(
  info: Pick<OddsMarketInfo, "key" | "kind" | "subject" | "parlay">,
  period: string,
  row: Pick<OddsBoardRow, "fixture_id" | "kickoff_at" | "home" | "away" | "line">,
  sel: Pick<OddsSelectionPrice, "selection" | "line" | "best_odds">,
  bookmaker: string | null,
): NewLeg | null {
  const market = classicMarket(info, period);
  if (market === null) return null;
  const line = market === "OU" || market === "AH" ? ownLine(shapeOf(info), sel, row.line) : 0;
  return {
    fixture_id: row.fixture_id,
    market_key: market,
    selection: sel.selection,
    line: normLine(line),
    home: row.home.name,
    away: row.away.name,
    kickoff_at: row.kickoff_at,
    odds: sel.best_odds,
    bookmaker,
    p_model: null,
  };
}

/** A leg in words, as the slip names it: «Brighton -0,25 a 1,95». */
function legText(leg: SlipLeg): string {
  const label = classicLabel({
    market_key: leg.market_key,
    selection: leg.selection,
    line: toNumber(leg.line),
    home: leg.home,
    away: leg.away,
  });
  return leg.odds ? t("explorer.parlay.legAt", { label, odds: fmtOdds(leg.odds) }) : label;
}

/**
 * What a screen reader is told when the slip changes (aria-live): the selection that went in or out, and how many the
 * parlay holds now. Null when nothing changed.
 */
export function slipAnnouncement(
  before: readonly SlipLeg[],
  after: readonly SlipLeg[],
): string | null {
  const was = new Set(before.map((l) => l.key));
  const is = new Set(after.map((l) => l.key));
  const added = after.filter((l) => !was.has(l.key));
  const removed = before.filter((l) => !is.has(l.key));
  if (added.length === 0 && removed.length === 0) return null;
  const count = t("explorer.parlay.count", { count: after.length });
  if (added.length === 1 && removed.length <= 1) {
    const verb = removed.length === 1 ? "explorer.parlay.replaced" : "explorer.parlay.added";
    return `${t(verb, { leg: legText(added[0] as SlipLeg) })} ${count}`;
  }
  if (removed.length === 1 && added.length === 0) {
    return `${t("explorer.parlay.removed", { leg: legText(removed[0] as SlipLeg) })} ${count}`;
  }
  return count;
}
