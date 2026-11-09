/**
 * The URL of Cuotas (plan Cuotas, UX-069): the explorer's family, market, line, filters and order as short keys, written by
 * `serializeExplorerState` and read by `parseExplorerSearch` (explorer/state.ts). The route runs in the app's first bundle,
 * so this file stays free of the explorer's code; the old page reads none of it.
 */

/** The explorer's keys, as `serializeExplorerState` writes them. */
export const ODDS_SEARCH_KEYS = [
  "f",
  "m",
  "p",
  "l",
  "h",
  "q",
  "c",
  "comp",
  "bk",
  "min",
  "max",
  "nb",
  "fair",
  "mine",
  "sort",
] as const;

export type OddsSearchKey = (typeof ODDS_SEARCH_KEYS)[number];
export type OddsSearch = Partial<Record<OddsSearchKey, string | number>>;

const NUMERIC: ReadonlySet<string> = new Set([
  "l",
  "h",
  "comp",
  "bk",
  "min",
  "max",
  "nb",
  "fair",
  "mine",
]);
const MAX_TEXT = 120;

function value(key: string, v: unknown): string | number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v !== "string" || v.length > MAX_TEXT) return null;
  const n = Number(v);
  return NUMERIC.has(key) && v.trim() !== "" && Number.isFinite(n) ? n : v;
}

/**
 * The explorer's keys and nothing else, each a word or a number: the router writes a number as `h=48`, a text that reads
 * as one as `h="48"`. Used both ways: the route's `validateSearch`, and what the explorer writes back. The explorer reads
 * the values again (`parseExplorerSearch`), so one it cannot read changes nothing, and its first choice writes a clean URL.
 */
export function validateOddsSearch(search: Readonly<Record<string, unknown>>): OddsSearch {
  const out: OddsSearch = {};
  for (const key of ODDS_SEARCH_KEYS) {
    const v = value(key, search[key]);
    if (v !== null) out[key] = v;
  }
  return out;
}
