/**
 * An in-memory `ExplorerData` for the tests (never imported by the product): five matches of four competitions and the
 * markets of every tab, built the way the API serves them - each selection at its own line (an Asian handicap's away side at
 * -h), fair prices only where the market is exhaustive and three bookmakers or more quote it, `parlay_ok` only for the five
 * classic markets at the full time, off a quarter line, an outlier or a stale row. Its board applies the API's filters and
 * orders with the same pure functions the explorer reads (rows.ts) and pages by `pageSize`.
 */
import { classicMarket, shapeOf } from "./markets";
import type {
  BoardPages,
  BoardQuery,
  CompetitionBadge,
  Dec,
  ExplorerData,
  ExplorerFollow,
  FamiliesQuery,
  Loadable,
  MatchOddsBook,
  MovementQuery,
  OddsBoardPage,
  OddsBoardRow,
  OddsFamilies,
  OddsMarketInfo,
  OddsMovement,
  OddsSelectionPrice,
  TeamBadge,
} from "./model";
import { isQuarterLine } from "@/product/records/model";
import { sameLine, serverFilter, sortRows } from "./rows";

export const FAKE_NOW = Date.parse("2026-11-08T12:00:00Z");
const HOUR = 3_600_000;

export const COMPETITIONS: CompetitionBadge[] = [
  { id: 2, name: "UEFA Champions League", country: "World", logo_url: null, flag_url: null },
  { id: 39, name: "Premier League", country: "England", logo_url: null, flag_url: null },
  { id: 140, name: "La Liga", country: "Spain", logo_url: null, flag_url: null },
  { id: 239, name: "Primera A", country: "Colombia", logo_url: null, flag_url: null },
];

export const BOOKMAKERS = [
  { id: 8, name: "Bet365" },
  { id: 11, name: "1xBet" },
  { id: 3, name: "Betfair" },
  { id: 6, name: "Bwin" },
  { id: 16, name: "Unibet" },
  { id: 32, name: "Betano" },
  { id: 4, name: "Pinnacle" },
  { id: 27, name: "Marathonbet" },
];

const team = (id: number, name: string): TeamBadge => ({ id, name, logo_url: null });

interface FakeFixture {
  id: number;
  home: TeamBadge;
  away: TeamBadge;
  competition: number;
  hours: number;
  stale?: boolean;
  /** Its Asian handicap's home line. */
  ah: number;
  goals: number;
}

export const FIXTURES: FakeFixture[] = [
  {
    id: 7819,
    home: team(51, "Brighton"),
    away: team(55, "Brentford"),
    competition: 39,
    hours: 3,
    ah: -0.25,
    goals: 2.5,
  },
  {
    id: 7820,
    home: team(541, "Real Madrid"),
    away: team(536, "Sevilla"),
    competition: 140,
    hours: 5,
    ah: -1.5,
    goals: 3.5,
  },
  {
    id: 7821,
    home: team(1137, "Millonarios"),
    away: team(1135, "Atlético Nacional"),
    competition: 239,
    hours: 26,
    stale: true,
    ah: 0,
    goals: 2.5,
  },
  {
    id: 7822,
    home: team(42, "Arsenal"),
    away: team(40, "Liverpool"),
    competition: 39,
    hours: 30,
    ah: -0.5,
    goals: 2.5,
  },
  {
    id: 7823,
    home: team(505, "Inter"),
    away: team(529, "Barcelona"),
    competition: 2,
    hours: 50,
    ah: 0.5,
    goals: 3.5,
  },
];

function info(
  key: string,
  family: string,
  kind: string,
  periods: string[],
  extra: Partial<OddsMarketInfo> = {},
): OddsMarketInfo {
  return {
    key,
    family,
    kind,
    subject: "match",
    periods,
    has_line: ["line", "signed_line", "signed_line_3way", "player_count"].includes(kind),
    fair: !["exact_score", "player", "player_count"].includes(kind),
    parlay: false,
    fixtures: 5,
    max_books: 8,
    ...extra,
  };
}

/** The markets of the window, family by family (tax-v3 keys, the period apart). */
export const MARKETS: Record<string, OddsMarketInfo[]> = {
  result: [
    info("result.1x2", "result", "plain", ["FT"], { parlay: true }),
    info("result.draw_no_bet", "result", "plain", ["FT"]),
    info("result.asian_handicap", "result", "signed_line", ["FT"], { parlay: true }),
    info("result.european_handicap", "result", "signed_line_3way", ["FT"], { fixtures: 4 }),
    info("result.double_chance", "result", "plain", ["FT"], { parlay: true }),
  ],
  goals: [
    info("goals.total", "goals", "line", ["FT"], { parlay: true }),
    info("goals.btts", "goals", "plain", ["FT"], { parlay: true }),
    info("goals.correct_score", "goals", "exact_score", ["FT"]),
    info("goals.total.home", "goals", "line", ["FT"], { subject: "home", fixtures: 4 }),
  ],
  goals_half: [
    info("result.1x2", "goals_half", "plain", ["1H", "2H"], { fixtures: 4 }),
    info("goals.total", "goals_half", "line", ["1H"], { fixtures: 4 }),
  ],
  corners: [
    info("corners.total", "corners", "line", ["FT"], { fixtures: 5 }),
    info("corners.total", "corners", "line", ["1H"], { fixtures: 3 }),
    info("corners.asian_handicap", "corners", "signed_line", ["FT"], { fixtures: 3, max_books: 6 }),
  ],
  cards: [info("cards.total", "cards", "line", ["FT"], { fixtures: 2, max_books: 4 })],
  players: [
    info("player.anytime_scorer", "players", "player", ["FT"], {
      subject: "player",
      fixtures: 3,
      max_books: 1,
    }),
  ],
  shots: [
    info("shots.on_target", "shots", "line", ["FT"], { fixtures: 1, max_books: 1, fair: false }),
  ],
  saves: [
    info("keeper.saves", "saves", "player_count", ["FT"], {
      subject: "keeper",
      fixtures: 1,
      max_books: 1,
    }),
  ],
  timing: [info("goals.first_team_to_score", "timing", "plain", ["FT"], { fixtures: 4 })],
  other_sport: [info("other.player_singles", "other_sport", "player", ["FT"])],
};

/** A fixed pseudo-random number in [0, 1) for a key: the same data on every run. */
function noise(key: string): number {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 10_000) / 10_000;
}

const odds = (n: number) => (Math.round(n * 100) / 100).toFixed(2);

interface Draft {
  selection: string;
  player?: string;
  line: number | null;
  /** The fair probability the price is built around. */
  p: number;
}

const PLAYERS = [
  "Danny Welbeck",
  "Kaoru Mitoma",
  "João Pedro",
  "Evan Ferguson",
  "Yoane Wissa",
  "Bryan Mbeumo",
  "Ivan Toney",
  "Simon Adingra",
  "Kevin Schade",
  "Mikkel Damsgaard",
  "Pervis Estupiñán",
  "Facundo Buonanotte",
];
const SCORES = ["1:0", "2:0", "2:1", "3:0", "3:1", "0:0", "1:1", "2:2", "0:1", "0:2", "1:2", "3:2"];

/** The selections of a market at a line, with the probabilities the prices are built around. */
function drafts(m: OddsMarketInfo, f: FakeFixture, line: number | null): Draft[] {
  const shape = shapeOf(m);
  const seed = noise(`${f.id}|${m.key}`);
  switch (shape) {
    case "ah": {
      const h = line ?? 0;
      const p = Math.min(0.8, Math.max(0.2, 0.5 + h * 0.18 + (seed - 0.5) * 0.1));
      return [
        { selection: "Home", line: h, p },
        { selection: "Away", line: h === 0 ? 0 : -h, p: 1 - p },
      ];
    }
    case "eh": {
      const h = line ?? -1;
      return [
        { selection: "Home", line: h, p: 0.36 },
        { selection: "Draw", line: h, p: 0.26 },
        { selection: "Away", line: h, p: 0.38 },
      ];
    }
    case "line": {
      const l = line ?? 2.5;
      const p = Math.min(0.85, Math.max(0.15, 0.5 + (f.goals - l) * 0.12 + (seed - 0.5) * 0.1));
      return [
        { selection: "Over", line: l, p },
        { selection: "Under", line: l, p: 1 - p },
      ];
    }
    case "exact_score":
      return SCORES.map((s, i) => ({ selection: s, line: null, p: 0.12 / (1 + i * 0.35) }));
    case "player":
      return PLAYERS.map((name, i) => ({
        selection: name,
        player: name,
        line: null,
        p: 0.42 / (1 + i * 0.3),
      }));
    case "player_count":
      return [2, 3, 4].map((n) => ({
        selection: "Bart Verbruggen",
        player: "Bart Verbruggen",
        line: n,
        p: 0.7 / n,
      }));
    default: {
      if (m.key.endsWith("double_chance")) {
        return [
          { selection: "1X", line: null, p: 0.72 },
          { selection: "12", line: null, p: 0.74 },
          { selection: "X2", line: null, p: 0.54 },
        ];
      }
      if (m.key.endsWith("btts")) {
        return [
          { selection: "Yes", line: null, p: 0.55 + (seed - 0.5) * 0.1 },
          { selection: "No", line: null, p: 0.45 - (seed - 0.5) * 0.1 },
        ];
      }
      if (m.key.endsWith("draw_no_bet")) {
        return [
          { selection: "Home", line: null, p: 0.6 },
          { selection: "Away", line: null, p: 0.4 },
        ];
      }
      if (m.key.endsWith("first_team_to_score")) {
        return [
          { selection: "Home", line: null, p: 0.52 },
          { selection: "No goal", line: null, p: 0.08 },
          { selection: "Away", line: null, p: 0.4 },
        ];
      }
      const home = 0.3 + seed * 0.25;
      return [
        { selection: "Home", line: null, p: home },
        { selection: "Draw", line: null, p: 0.27 },
        { selection: "Away", line: null, p: 0.73 - home },
      ];
    }
  }
}

/** A row's lines: its main line and its neighbours (none for a market without lines). */
function linesOf(m: OddsMarketInfo, f: FakeFixture): number[] {
  const shape = shapeOf(m);
  if (shape === "ah") return [f.ah - 0.5, f.ah, f.ah + 0.5].map((l) => (l === 0 ? 0 : l));
  if (shape === "eh") return [-1, 1];
  if (shape === "line") {
    const main = m.key.startsWith("corners") ? 9.5 : m.key.startsWith("cards") ? 4.5 : f.goals;
    return [main - 1, main, main + 1];
  }
  return [];
}

function mainLine(m: OddsMarketInfo, f: FakeFixture): number | null {
  const lines = linesOf(m, f);
  return lines.length ? (lines[Math.floor(lines.length / 2)] ?? null) : null;
}

/** The fair price needs an exhaustive market and three bookmakers; an outlier is more than 25 % above it. */
function price(
  m: OddsMarketInfo,
  period: string,
  f: FakeFixture,
  d: Draft,
  now: number,
): OddsSelectionPrice {
  const single = m.max_books <= 1;
  const n = single ? 1 : 3 + Math.floor(noise(`${f.id}|${m.key}|${d.selection}|n`) * 6);
  const fairOdds = 1 / d.p;
  // The 1X2 of Arsenal-Liverpool has one bookmaker far above the market on the home side.
  const outlier =
    f.id === 7822 && m.key === "result.1x2" && period === "FT" && d.selection === "Home";
  const best = outlier
    ? fairOdds * 1.32
    : fairOdds * (0.96 + noise(`${f.id}|${m.key}|${d.selection}`) * 0.07);
  const book =
    BOOKMAKERS[Math.floor(noise(`${f.id}|${d.selection}|bk`) * BOOKMAKERS.length)] ??
    BOOKMAKERS[0]!;
  const fair = m.fair && n >= 3;
  const classic = classicMarket(m, period) !== null;
  const started = now >= FAKE_NOW + f.hours * HOUR;
  return {
    selection: d.selection,
    player: d.player ?? null,
    line: d.line === null ? null : String(d.line),
    best_odds: odds(best),
    bookmaker_id: book.id,
    n_books: n,
    fair_odds: fair ? odds(fairOdds) : null,
    price_edge: fair ? (best / fairOdds - 1).toFixed(4) : null,
    outlier,
    parlay_ok: classic && !outlier && !f.stale && !started && !isQuarterLine(d.line),
  };
}

function marketsOf(key: string, period: string): OddsMarketInfo | null {
  for (const list of Object.values(MARKETS)) {
    const m = list.find((x) => x.key === key && x.periods.includes(period));
    if (m) return m;
  }
  return null;
}

/** Every row of a board, before the filters: each match that has the market at that line. */
export function fakeRows(
  key: string,
  period: string,
  line: string,
  now: number = FAKE_NOW,
): OddsBoardRow[] {
  const m = marketsOf(key, period);
  if (!m) return [];
  const rows: OddsBoardRow[] = [];
  for (const f of FIXTURES.slice(0, m.fixtures)) {
    const lines = linesOf(m, f);
    const at = line === "main" ? mainLine(m, f) : Number(line);
    if (line !== "main" && !lines.some((l) => sameLine(l, at))) continue;
    rows.push({
      fixture_id: f.id,
      kickoff_at: new Date(FAKE_NOW + f.hours * HOUR).toISOString(),
      competition_id: f.competition,
      home: f.home,
      away: f.away,
      line: at === null ? null : String(at),
      lines: lines.map(String),
      selections: drafts(m, f, at).map((d) => price(m, period, f, d, now)),
      captured_at: new Date(FAKE_NOW - (f.stale ? 7 : 2) * HOUR).toISOString(),
      provider_update_at: new Date(FAKE_NOW - (f.stale ? 8 : 2.5) * HOUR).toISOString(),
      state: f.stale ? "stale" : "current",
    });
  }
  return rows;
}

/** One bookmaker's book of a line: the best one gets the best price, the others a little less, one misses a selection. */
export function fakeBook(fixtureId: number, family: string, now: number = FAKE_NOW): MatchOddsBook {
  const f = FIXTURES.find((x) => x.id === fixtureId) ?? (FIXTURES[0] as FakeFixture);
  const markets = (MARKETS[family] ?? []).flatMap((m) =>
    m.periods.map((period) => {
      const lines = linesOf(m, f);
      const at = lines.length ? lines : [null];
      return {
        info: m,
        period,
        main_line: mainLine(m, f) === null ? null : String(mainLine(m, f)),
        lines: at.map((l) => {
          const selections = drafts(m, f, l).map((d) => price(m, period, f, d, now));
          return {
            line: l === null ? null : String(l),
            selections,
            books: BOOKMAKERS.slice(0, m.max_books).map((b, bi) => ({
              bookmaker_id: b.id,
              odds: selections.map((s, si): Dec | null => {
                if (bi === 5 && si === 0) return null;
                if (b.id === s.bookmaker_id) return s.best_odds;
                return odds(Number(s.best_odds) * (0.93 + noise(`${b.id}|${si}`) * 0.05));
              }),
            })),
          };
        }),
      };
    }),
  );
  return {
    fixture_id: f.id,
    kickoff_at: new Date(FAKE_NOW + f.hours * HOUR).toISOString(),
    captured_at: new Date(FAKE_NOW - 2 * HOUR).toISOString(),
    provider_update_at: null,
    state: f.stale ? "stale" : "current",
    families: [{ key: family, markets }],
    bookmakers: BOOKMAKERS,
  };
}

/** The best price of each selection over the last day: the home side shortening, the away side drifting. */
export function fakeMovement(fixtureId: number, q: MovementQuery): OddsMovement {
  const rows = fakeRows(q.market, q.period, q.line ?? "main");
  const row = rows.find((r) => r.fixture_id === fixtureId);
  const available = !q.market.startsWith("player.");
  return {
    fixture_id: fixtureId,
    market: q.market,
    period: q.period,
    line: q.line,
    available,
    series: available
      ? (row?.selections ?? []).map((s, i) => ({
          selection: s.selection,
          player: s.player,
          line: s.line,
          points: [24, 12, 6, 2].map((h, k) => ({
            captured_at: new Date(FAKE_NOW - h * HOUR).toISOString(),
            best_odds: odds(Number(s.best_odds) * (1 + (i === 0 ? 0.03 : -0.03) * (3 - k))),
            bookmaker_id: s.bookmaker_id,
          })),
        }))
      : [],
    bookmakers: BOOKMAKERS,
  };
}

export function fakeFamilies(): OddsFamilies {
  return {
    window_hours: 24,
    book_enabled: true,
    generated_at: new Date(FAKE_NOW - 60_000).toISOString(),
    families: Object.entries(MARKETS).map(([key, markets]) => ({
      key,
      fixtures: Math.max(...markets.map((m) => m.fixtures)),
      markets,
    })),
  };
}

function loadable<T>(data: T | undefined, o: Partial<Loadable<T>> = {}): Loadable<T> {
  return {
    data,
    isPending: data === undefined && !o.isError,
    isError: false,
    error: null,
    isFetching: false,
    isPlaceholderData: false,
    updatedAt: data === undefined ? 0 : FAKE_NOW,
    refetch: () => undefined,
    ...o,
  };
}

export interface FakeOptions {
  /** Every hook still loading. */
  pending?: boolean;
  /** The families failed and there is nothing to show. */
  familiesError?: boolean;
  /** The board's last refresh failed: "keep" its previous pages, "empty" with nothing. */
  boardError?: "keep" | "empty";
  /** The board shows the previous answer while the new one loads. */
  placeholder?: boolean;
  /** Rows per page (the API's `limit`). */
  pageSize?: number;
  /** How many pages are loaded («Cargar más» was tapped). */
  pages?: number;
  follow?: ExplorerFollow | null;
  families?: OddsFamilies;
  now?: number;
}

export interface FakeCalls {
  families: FamiliesQuery[];
  board: BoardQuery[];
  book: Array<{ fixtureId: number; family: string; enabled: boolean }>;
  movement: Array<{ fixtureId: number; q: MovementQuery; enabled: boolean }>;
}

/** The fake data layer, and what the explorer asked of it. */
export function fakeExplorerData(o: FakeOptions = {}): ExplorerData & { calls: FakeCalls } {
  const now = o.now ?? FAKE_NOW;
  const calls: FakeCalls = { families: [], board: [], book: [], movement: [] };
  const dictionary = new Map(COMPETITIONS.map((c) => [c.id, c]));
  const rank = new Map(COMPETITIONS.map((c, i) => [c.id, i]));
  return {
    calls,
    useFamilies(q) {
      calls.families.push(q);
      if (o.familiesError) {
        return loadable<OddsFamilies>(undefined, { isError: true, error: new Error("down") });
      }
      return loadable(o.pending ? undefined : (o.families ?? fakeFamilies()));
    },
    useBoard(q, live): BoardPages {
      calls.board.push(q);
      const size = o.pageSize ?? 20;
      const all = sortRows(
        serverFilter(
          fakeRows(q.market, q.period, q.line, now),
          {
            q: q.q,
            country: q.country,
            competition: q.competition,
            bookmaker: q.bookmaker,
            oddsMin: q.odds_min,
            oddsMax: q.odds_max,
            minBooks: q.min_books,
            fairOnly: q.fair_only,
          },
          dictionary,
        ),
        q.sort,
        rank,
      );
      const loaded = Math.max(1, o.pages ?? 1);
      const pages: OddsBoardPage[] = [];
      const market = marketsOf(q.market, q.period);
      for (let i = 0; i < loaded && market; i++) {
        const rows = all.slice(i * size, (i + 1) * size);
        if (i > 0 && rows.length === 0) break;
        pages.push({
          market,
          period: q.period,
          rows,
          total: all.length,
          next_cursor: (i + 1) * size < all.length ? String(i + 1) : null,
          competitions: COMPETITIONS.filter((c) => rows.some((r) => r.competition_id === c.id)),
          bookmakers: BOOKMAKERS,
          generated_at: new Date(FAKE_NOW - 30_000).toISOString(),
        });
      }
      const data = o.pending || !live.enabled || o.boardError === "empty" ? undefined : pages;
      const last = pages[pages.length - 1];
      return {
        ...loadable(data, {
          isError: !!o.boardError,
          error: o.boardError ? new Error("refresh failed") : null,
          isPlaceholderData: !!o.placeholder,
          isFetching: !!o.placeholder,
          isPending: data === undefined && !o.boardError,
        }),
        hasNextPage: !!last?.next_cursor,
        isFetchingNextPage: false,
        fetchNextPage: () => undefined,
      };
    },
    useMatchBook(fixtureId, family, enabled) {
      calls.book.push({ fixtureId, family, enabled });
      return loadable(enabled && !o.pending ? fakeBook(fixtureId, family, now) : undefined);
    },
    useMovement(fixtureId, q, enabled) {
      calls.movement.push({ fixtureId, q, enabled });
      return loadable(enabled && !o.pending ? fakeMovement(fixtureId, q) : undefined);
    },
    useFollow() {
      return o.follow ?? null;
    },
  };
}
