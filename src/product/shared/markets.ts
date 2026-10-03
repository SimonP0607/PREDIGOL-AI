/** Markets, selections and reason codes in the reader's language. */
import { t, translateOr } from "@/lib/i18n";
import { fmtLine, toNumber } from "@/lib/i18n/format";

export const MARKETS = ["1X2", "OU", "BTTS", "AH", "DC"] as const;
export type MarketKey = (typeof MARKETS)[number];

export function marketName(key: string): string {
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
  return "";
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
