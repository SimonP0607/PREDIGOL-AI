/**
 * Two levels, never more (plan Cuotas, section 5): family tabs - seven at most and «Más» - and the market chips of the tab.
 * Pure: no React here.
 *
 * Principales · Goles · Mitades · Hándicaps · Córners · Tarjetas · Jugadores · Más. «Principales» is today's five markets and
 * the rest of the family Resultado (draw no bet, European handicap); «Hándicaps» is a VIEW that gathers the Asian and
 * European handicaps of every family, which stay in their own family too; «Más» holds shots, goalkeepers, specials, timing and
 * qualification, and fouls, offsides and tackles when they have data. Only what the window has prices for is there, each tab
 * with its number of matches.
 *
 * A market's periods (match, first half, second half) are those of every family it is filed in: tax-v3 keeps the first-half
 * total under «Mitades» and the match's under «Goles», and the reader of «Más/menos goles» switches between them in the card.
 */
import { t } from "@/lib/i18n";
import { fold } from "@/product/matches/model";
import {
  chipTitle,
  compareMarkets,
  comparePeriods,
  familyName,
  isClassic,
  isHandicap,
  marketTitle,
} from "./markets";
import type { OddsFamily, OddsMarketInfo } from "./model";

export const TAB_KEYS = [
  "main",
  "goals",
  "halves",
  "handicaps",
  "corners",
  "cards",
  "players",
  "more",
] as const;
export type TabKey = (typeof TAB_KEYS)[number];

/** «Principales», «Goles»... «Más». */
export function tabName(key: TabKey): string {
  return t(`explorer.tab.${key}`);
}

/** The id of a tab's button: the panel is labelled by it. */
export function tabId(key: TabKey): string {
  return `explorer-tab-${key}`;
}

export function isTabKey(value: unknown): value is TabKey {
  return typeof value === "string" && (TAB_KEYS as readonly string[]).includes(value);
}

/** A family's own tab; any other family (shots, goalkeepers, specials, timing, qualification...) goes to «Más». */
const OWN_TAB: Readonly<Record<string, TabKey>> = {
  result: "main",
  goals: "goals",
  goals_half: "halves",
  corners: "corners",
  cards: "cards",
  players: "players",
};

/** Not shown in this version (plan, decision 4): the provider's «other sports». */
const HIDDEN_FAMILIES = new Set(["other_sport"]);

/** «Más» lists its families in this order (its chips are grouped by family). */
const MORE_ORDER: readonly string[] = [
  "shots",
  "saves",
  "special",
  "timing",
  "advance",
  "fouls",
  "offsides",
  "tackles",
];

export function ownTab(family: string): TabKey {
  return OWN_TAB[family] ?? "more";
}

export interface PeriodOption {
  period: string;
  /** How many matches have it, when the families say so exactly (an entry with that period alone); null: not known. */
  fixtures: number | null;
}

export interface TabMarket {
  key: string;
  /** The entry this tab lists (its own family's first): what names it and says what it is. */
  info: OddsMarketInfo;
  family: string;
  /** Every entry of this key, in every family. */
  entries: OddsMarketInfo[];
  periods: PeriodOption[];
  /** The period the chip opens on: this tab's first («Mitades» opens the first half). */
  defaultPeriod: string;
  fixtures: number;
  /** Listed under its own family here: the chip does not repeat the family's name. */
  own: boolean;
}

export interface ExplorerTab {
  key: TabKey;
  fixtures: number;
  markets: TabMarket[];
}

interface Entry {
  info: OddsMarketInfo;
  family: string;
}

/** The tabs a market of this family is listed in. */
function tabsOf(entry: Entry): TabKey[] {
  const tabs: TabKey[] = [ownTab(entry.family)];
  if (isClassic(entry.info) && !tabs.includes("main")) tabs.push("main");
  if (isHandicap(entry.info)) tabs.push("handicaps");
  return tabs;
}

function periodOptions(entries: readonly OddsMarketInfo[]): PeriodOption[] {
  const known = new Map<string, number | null>();
  for (const e of entries) {
    for (const p of e.periods) {
      // A count is the entry's own only when the entry has that period alone.
      const count = e.periods.length === 1 ? e.fixtures : null;
      const held = known.get(p);
      known.set(p, count === null ? (held ?? null) : Math.max(held ?? 0, count));
    }
  }
  return [...known.keys()]
    .sort(comparePeriods)
    .map((period) => ({ period, fixtures: known.get(period) ?? null }));
}

function familyRank(tab: TabKey, family: string): number {
  if (ownTab(family) === tab) {
    const i = MORE_ORDER.indexOf(family);
    return tab === "more" ? (i < 0 ? MORE_ORDER.length : i) : 0;
  }
  return MORE_ORDER.length + 1;
}

/** The tabs of these families, in their fixed order; a tab without a market is left out. */
export function buildTabs(families: readonly OddsFamily[] | undefined): ExplorerTab[] {
  const entries: Entry[] = [];
  const familyFixtures = new Map<string, number>();
  for (const f of families ?? []) {
    if (HIDDEN_FAMILIES.has(f.key)) continue;
    familyFixtures.set(f.key, f.fixtures);
    for (const info of f.markets) entries.push({ info, family: f.key });
  }
  const byKey = new Map<string, OddsMarketInfo[]>();
  for (const e of entries) byKey.set(e.info.key, [...(byKey.get(e.info.key) ?? []), e.info]);

  const members = new Map<TabKey, Map<string, Entry[]>>();
  for (const e of entries) {
    for (const tab of tabsOf(e)) {
      const keys = members.get(tab) ?? new Map<string, Entry[]>();
      keys.set(e.info.key, [...(keys.get(e.info.key) ?? []), e]);
      members.set(tab, keys);
    }
  }

  const tabs: ExplorerTab[] = [];
  for (const key of TAB_KEYS) {
    const keys = members.get(key);
    if (!keys || keys.size === 0) continue;
    const markets: TabMarket[] = [...keys.entries()].map(([marketKey, listed]) => {
      const sorted = [...listed].sort(
        (a, b) => familyRank(key, a.family) - familyRank(key, b.family),
      );
      const first = sorted[0] as Entry;
      const periods = periodOptions(byKey.get(marketKey) ?? []);
      const ownPeriods = sorted.flatMap((e) => e.info.periods).sort(comparePeriods);
      return {
        key: marketKey,
        info: first.info,
        family: first.family,
        entries: byKey.get(marketKey) ?? [],
        periods,
        defaultPeriod: ownPeriods[0] ?? periods[0]?.period ?? "FT",
        fixtures: Math.max(0, ...listed.map((e) => e.info.fixtures)),
        own: key !== "handicaps" && key !== "more" && ownTab(first.family) === key,
      };
    });
    markets.sort((a, b) => {
      if (key === "more") {
        const d = familyRank(key, a.family) - familyRank(key, b.family);
        if (d !== 0) return d;
      }
      return compareMarkets(a.info, b.info, key === "main");
    });
    // A tab's matches: its families' own count where it has them (exact), else its busiest market's.
    const own = [...familyFixtures].filter(([f]) => ownTab(f) === key).map(([, n]) => n);
    tabs.push({ key, markets, fixtures: Math.max(0, ...own, ...markets.map((m) => m.fixtures)) });
  }
  return tabs;
}

/** The last market used in each tab (a viewer's convenience, kept in their browser). */
export type MarketMemory = Readonly<Partial<Record<TabKey, string>>>;

export function rememberMarket(memory: MarketMemory, tab: TabKey, market: string): MarketMemory {
  return memory[tab] === market ? memory : { ...memory, [tab]: market };
}

/** A memory read back from storage: only tab keys and market-shaped strings survive. */
export function readMemory(raw: unknown): MarketMemory {
  if (!raw || typeof raw !== "object") return {};
  const out: Partial<Record<TabKey, string>> = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (isTabKey(k) && typeof v === "string" && /^[a-z0-9_.]{1,80}$/.test(v)) out[k] = v;
  }
  return out;
}

/** The market a tab opens on: the one asked for, else the last one used there, else its first. */
export function marketOfTab(
  tab: ExplorerTab,
  wanted: string | null,
  memory: MarketMemory = {},
): TabMarket | null {
  const find = (key: string | null | undefined) =>
    key ? (tab.markets.find((m) => m.key === key) ?? null) : null;
  return find(wanted) ?? find(memory[tab.key]) ?? tab.markets[0] ?? null;
}

/** The period to show: the one asked for when the market has it, else the market's own first. */
export function periodOf(market: TabMarket, wanted: string | null): string {
  return wanted && market.periods.some((p) => p.period === wanted) ? wanted : market.defaultPeriod;
}

export interface ExplorerView {
  tabs: ExplorerTab[];
  tab: ExplorerTab;
  market: TabMarket;
  period: string;
  /** "main" or a decimal; always "main" for a market without lines. */
  line: string;
}

/** What is on screen for this state: a tab, market or period the window does not have falls back to the first that is. */
export function resolveView(
  tabs: ExplorerTab[],
  wanted: { tab: TabKey | null; market: string | null; period: string | null; line: string },
  memory: MarketMemory = {},
): ExplorerView | null {
  const tab = tabs.find((t) => t.key === wanted.tab) ?? tabs[0];
  if (!tab) return null;
  const market = marketOfTab(tab, wanted.market, memory);
  if (!market) return null;
  return {
    tabs,
    tab,
    market,
    period: periodOf(market, wanted.period),
    line: market.info.has_line ? wanted.line : "main",
  };
}

/** The family the match's book is asked for: the one this market is filed under for the period on show. */
export function familyFor(market: TabMarket, period: string): string {
  return market.entries.find((e) => e.periods.includes(period))?.family ?? market.family;
}

export interface MarketHit {
  tab: TabKey;
  market: TabMarket;
  title: string;
}

/**
 * The markets a search names («córners», «goleador», «hándicap»): every word of the query in the market's name, its family's
 * or its tab's, accents and case aside. One hit per market, in its own family's tab where it has one.
 */
export function searchMarkets(tabs: readonly ExplorerTab[], query: string, limit = 6): MarketHit[] {
  const words = fold(query.trim()).split(/\s+/).filter(Boolean);
  if (words.join("").length < 3) return [];
  const best = new Map<string, MarketHit>();
  for (const tab of tabs) {
    for (const market of tab.markets) {
      const title = marketTitle(market.info);
      const hay = fold(
        `${title} ${chipTitle(market.info, true)} ${familyName(market.family)} ${tabName(tab.key)}`,
      );
      if (!words.every((w) => hay.includes(w))) continue;
      const held = best.get(market.key);
      const home = ownTab(market.family) === tab.key;
      if (!held || (home && ownTab(held.market.family) !== held.tab)) {
        best.set(market.key, { tab: tab.key, market, title });
      }
    }
  }
  const place = (h: MarketHit) => {
    const tab = tabs.find((x) => x.key === h.tab);
    return TAB_KEYS.indexOf(h.tab) * 1000 + (tab ? tab.markets.indexOf(h.market) : 0);
  };
  return [...best.values()].sort((a, b) => place(a) - place(b)).slice(0, limit);
}
