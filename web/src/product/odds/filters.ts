/**
 * The Cuotas page's filters (REVIEW PREDIGOL, point 17): the module is there for one thing - the best price of every
 * selection against its fair price, whatever the picks - so the reader narrows it by what they look for: a team or a
 * competition's name, a country, a competition, only the prices above fair, and the order (by kick-off, or the
 * widest margin over fair first). Pure: no React here.
 */
import type { BestOddsFixture } from "@/lib/api/v1/types_product";
import { toNumber } from "@/lib/i18n/format";
import { countryLabel } from "@/product/matches/country";
import { fold } from "@/product/matches/model";

export type OddsSort = "time" | "edge";

export interface OddsFilters {
  /** A team's or a competition's name, every word; accents do not matter. */
  query: string;
  country: string | null;
  competition: number | null;
  /** Only the matches with a price above its fair price in the chosen market (outliers do not count). */
  aboveFair: boolean;
  sort: OddsSort;
}

export const NO_ODDS_FILTERS: OddsFilters = {
  query: "",
  country: null,
  competition: null,
  aboveFair: false,
  sort: "time",
};

export const WORLD = "world";

export function countryOf(f: Pick<BestOddsFixture, "competition">): string {
  const name = (f.competition.country ?? "").trim();
  return !name || name.toLowerCase() === "world" ? WORLD : name.toLowerCase();
}

/** The widest margin over fair among the market's selections (an outlier never counts); null without one. */
export function bestEdge(f: BestOddsFixture, market: string): number | null {
  const m = f.markets.find((x) => x.market_key === market);
  if (!m) return null;
  let best: number | null = null;
  for (const s of m.selections) {
    if (s.outlier) continue;
    const e = toNumber(s.price_edge);
    if (e !== null && (best === null || e > best)) best = e;
  }
  return best;
}

export function matchesQuery(f: BestOddsFixture, query: string): boolean {
  const q = fold(query.trim());
  if (!q) return true;
  const hay = fold(`${f.home.name} ${f.away.name} ${f.competition.name}`);
  return q.split(/\s+/).every((w) => hay.includes(w));
}

export function inOddsFilters(f: BestOddsFixture, market: string, x: OddsFilters): boolean {
  if (!f.markets.some((m) => m.market_key === market)) return false;
  if (x.country !== null && countryOf(f) !== x.country) return false;
  if (x.competition !== null && f.competition.id !== x.competition) return false;
  if (x.aboveFair) {
    const e = bestEdge(f, market);
    if (e === null || e <= 0) return false;
  }
  return matchesQuery(f, x.query);
}

/** By kick-off; or the widest margin over fair first (none last), then by kick-off. */
export function sortFixtures(
  list: readonly BestOddsFixture[],
  market: string,
  sort: OddsSort,
): BestOddsFixture[] {
  const time = (a: BestOddsFixture, b: BestOddsFixture) =>
    Date.parse(a.kickoff_at) - Date.parse(b.kickoff_at) || a.fixture_id - b.fixture_id;
  if (sort === "time") return [...list].sort(time);
  return [...list].sort((a, b) => {
    const ea = bestEdge(a, market);
    const eb = bestEdge(b, market);
    if (ea === null && eb === null) return time(a, b);
    if (ea === null) return 1;
    if (eb === null) return -1;
    return eb - ea || time(a, b);
  });
}

export interface Option<K> {
  key: K;
  label: string;
  count: number;
}

/** The countries on the board (the market's matches), by name; international last. */
export function countryOptions(
  fixtures: readonly BestOddsFixture[],
  market: string,
  locale: string,
  worldLabel: string,
): Option<string>[] {
  const by = new Map<string, Option<string>>();
  for (const f of fixtures) {
    if (!f.markets.some((m) => m.market_key === market)) continue;
    const key = countryOf(f);
    const known = by.get(key);
    if (known) known.count += 1;
    else
      by.set(key, {
        key,
        label:
          key === WORLD
            ? worldLabel
            : (countryLabel(f.competition.country, null) ?? f.competition.country ?? key),
        count: 1,
      });
  }
  return [...by.values()].sort(
    (a, b) =>
      Number(a.key === WORLD) - Number(b.key === WORLD) || a.label.localeCompare(b.label, locale),
  );
}

/** The competitions on the board (of the chosen country, when there is one), by name. */
export function competitionOptions(
  fixtures: readonly BestOddsFixture[],
  market: string,
  country: string | null,
  locale: string,
): Option<number>[] {
  const by = new Map<number, Option<number>>();
  for (const f of fixtures) {
    if (!f.markets.some((m) => m.market_key === market)) continue;
    if (country !== null && countryOf(f) !== country) continue;
    const known = by.get(f.competition.id);
    if (known) known.count += 1;
    else by.set(f.competition.id, { key: f.competition.id, label: f.competition.name, count: 1 });
  }
  return [...by.values()].sort((a, b) => a.label.localeCompare(b.label, locale));
}
