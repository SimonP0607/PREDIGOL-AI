/** Markets, selections and reason codes in the reader's language. */
import { t, translateOr } from "@/lib/i18n";
import { fmtLine, toNumber } from "@/lib/i18n/format";
import type { CatalogueMarketKey } from "@/lib/api/v1/types_records";

export const MARKETS = ["1X2", "OU", "BTTS", "AH", "DC"] as const;
export type MarketKey = (typeof MARKETS)[number];

const CATALOGUE_KEY = /^[a-z0-9_]{3,48}\.(FT|1H|2H)\.(match|home|away)$/;

/** A market of the catalogue of prices by its stable key («corners_over_under.FT.match»): the server's own pattern. */
export function isCatalogueKey(key: string): key is CatalogueMarketKey {
  return CATALOGUE_KEY.test(key);
}

/** The name of a catalogue market read back without its page (a saved parlay): the catalogue's words, its half if not 90'. */
function catalogueName(key: string): string {
  const [code = "", period = "FT", subject = "match"] = key.split(".");
  const name = translateOr(`match.catalog.market.${code}`, t("match.catalog.market.other"));
  const half = period === "FT" ? "" : ` · ${translateOr(`match.catalog.period.${period}`, period)}`;
  const side = subject === "match" ? "" : ` · ${t(`common.${subject}`)}`;
  return `${name}${side}${half}`;
}

export function marketName(key: string): string {
  if (isCatalogueKey(key)) return catalogueName(key);
  return translateOr(`markets.name.${key}`, key);
}

export function marketShort(key: string): string {
  return translateOr(`markets.short.${key}`, key);
}

function lineText(market: string, line: string | number | null | undefined): string {
  const n = toNumber(line);
  if (n === null) return "";
  if (market === "AH") return fmtLine(n, true);
  if (market === "OU") return fmtLine(n);
  if (isCatalogueKey(market) && n !== 0) return fmtLine(n, market.includes("handicap"));
  return "";
}

/** A selection of a catalogue market read back without its page: the plain words of the provider's few answers. */
function catalogueWord(selection: string, home: string, away: string): string {
  if (selection === "Over") return t("match.markets.over");
  if (selection === "Under") return t("match.markets.under");
  if (selection === "Home") return home;
  if (selection === "Away") return away;
  if (selection === "Draw") return t("common.draw");
  if (selection === "Yes") return t("common.yes");
  if (selection === "No") return t("common.no");
  return selection;
}

/**
 * "Gana Real Madrid", "Más de 2,5 goles", "Ambos marcan: Sí", "Barcelona −0,5", "Real Madrid o empate".
 * `short` gives the compact board form: "1", "X", "Más 2,5", "1 −0,5", "1X".
 */
export function selectionLabel(
  q: {
    market_key: string;
    selection: string;
    line?: string | number | null | undefined;
    home?: string | undefined;
    away?: string | undefined;
  },
  short = false,
): string {
  const line = lineText(q.market_key, q.line);
  const vars = {
    line,
    home: q.home ?? t("common.home"),
    away: q.away ?? t("common.away"),
  };
  if (isCatalogueKey(q.market_key)) {
    const word = catalogueWord(q.selection, vars.home, vars.away);
    return line ? `${word} ${line}` : word;
  }
  const key = `markets.${short ? "selectionShort" : "selection"}.${q.market_key}.${q.selection}`;
  const fallback = line ? `${q.selection} ${line}` : q.selection;
  return translateOr(key, fallback, vars);
}

/** Why a selection did not pass the value gate. */
export function gateReason(code: string | null | undefined): string {
  return code ? translateOr(`markets.gate.${code}`, code) : "";
}

/** Why a block is empty (no_qualified_picks, no_value_now, ...). */
export function emptyReason(code: string | null | undefined): string {
  return code ? translateOr(`markets.reason.${code}`, code) : "";
}

export function riskLabel(risk: string | null | undefined): string {
  return risk ? translateOr(`markets.risk.${risk}`, risk) : "";
}
