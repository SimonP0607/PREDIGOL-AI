/// <reference types="bun" />
/**
 * The explorer as a reader gets it, rendered with the in-memory data: the family tabs and market chips, the period and line
 * of the card, an Asian handicap's two sides at their own lines, a stale row dimmed and out of the parlay, a market only to
 * look at, a long market's first eight with «Ver todas», «Comparar casas» with every bookmaker's margin, «Movimiento» with
 * its arrows and words while its chart loads, the loading / failed refresh / empty states, «Pausar actualizaciones», a
 * selection in the slip, and the motion that only runs without «reduce motion».
 */
import { afterAll, beforeAll, describe, expect, setSystemTime, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import { setTimeZone } from "@/lib/time";
import type { SlipLeg } from "@/product/records/model";
import { SlipContext, type SlipValue } from "@/product/records/slipContext";
import type { RowEnv } from "./env";
import { FAKE_NOW, fakeExplorerData, fakeRows, MARKETS, type FakeOptions } from "./fake";
import { FixtureRow, PriceCell } from "./FixtureRow";
import type { OddsBoardRow } from "./model";
import { OddsExplorer } from "./OddsExplorer";
import { DEFAULT_EXPLORER_STATE, type ExplorerState } from "./state";
import { BOOKMAKERS, COMPETITIONS } from "./fake";

setLocale("es");
afterAll(() => setLocale("es"));
// Clock times here are UTC (another file may leave the zone elsewhere). The fake matches kick off on the fake day and
// the parlay asks the real clock whether a match has started, so the clock stands at FAKE_NOW.
beforeAll(() => {
  setTimeZone("UTC");
  setSystemTime(FAKE_NOW);
});
afterAll(() => setSystemTime());

function slip(legs: SlipLeg[] = []): SlipValue {
  return {
    legs,
    has: (key) => legs.some((l) => l.key === key),
    toggle: () => undefined,
    remove: () => undefined,
    clear: () => undefined,
    load: () => undefined,
    undo: null,
    restore: () => undefined,
    open: false,
    setOpen: () => undefined,
  };
}

async function html(node: ReactNode, legs: SlipLeg[] = []): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({
      component: () => <SlipContext.Provider value={slip(legs)}>{node}</SlipContext.Provider>,
    }),
    history: createMemoryHistory({ initialEntries: ["/odds"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

async function explorer(
  state: Partial<ExplorerState> = {},
  o: FakeOptions = {},
  legs: SlipLeg[] = [],
) {
  const data = fakeExplorerData(o);
  const markup = await html(
    <OddsExplorer
      data={data}
      state={{ ...DEFAULT_EXPLORER_STATE, ...state }}
      onStateChange={() => undefined}
      now={FAKE_NOW}
    />,
    legs,
  );
  return { markup, data };
}

/** The markup of each board row, in order. */
function rowsOf(markup: string): string[] {
  return markup.split('data-testid="explorer-row"').slice(1);
}

function rowOf(markup: string, fixture: number): string {
  return rowsOf(markup).find((r) => r.includes(`data-fixture="${fixture}"`)) ?? "";
}

/** The visible words of each price cell, in order. */
function cellLabels(markup: string): string[] {
  return [
    ...markup.matchAll(
      /<span class="truncate text-xs font-semibold text-foreground" title="[^"]*">([^<]*)<\/span>/g,
    ),
  ].map((m) => m[1] as string);
}

const count = (markup: string, needle: string) => markup.split(needle).length - 1;

describe("the board", () => {
  test("the family tabs with their matches, the market chips, one row per match", async () => {
    const { markup, data } = await explorer();
    for (const name of [
      "Principales",
      "Goles",
      "Mitades",
      "Hándicaps",
      "Córners",
      "Tarjetas",
      "Jugadores",
      "Más",
    ]) {
      expect(markup).toContain(`>${name}<`);
    }
    expect(markup).toContain('aria-selected="true" aria-controls="explorer-panel"');
    expect(markup).toContain('id="explorer-tab-main"');
    expect(markup).toContain("5 partidos");
    expect(markup).toContain('data-testid="explorer-market-result.1x2"');
    expect(markup).toContain('data-market="result.1x2"');
    expect(rowsOf(markup)).toHaveLength(5);
    expect(cellLabels(rowOf(markup, 7820))).toEqual(["1", "X", "2"]);
    // the API is asked for the board on show
    expect(data.calls.board.at(-1)).toMatchObject({
      market: "result.1x2",
      period: "FT",
      line: "main",
    });
    // each row's age, its own
    expect(count(markup, 'data-testid="explorer-freshness"')).toBe(5);
    expect(markup).toContain("Actualizado 11:59");
  });

  test("four figures that never mix: the best price and its bookmaker, the market's fair price and the difference, grey; no model figure", async () => {
    const { markup } = await explorer();
    const madrid = rowOf(markup, 7820);
    expect(madrid).toMatch(
      /mejor cuota \d,\d\d en \w+, entre \d casas\. Justa del mercado \d,\d\d\./,
    );
    expect(madrid).toMatch(
      /numeric text-subtle-foreground[^>]*><span class="whitespace-nowrap">justa \d,\d\d<\/span> <span class="whitespace-nowrap">· [+-]\d,\d/,
    );
    // the chip of the row's age keeps its small size beside its colour
    expect(madrid).toMatch(
      /data-testid="explorer-freshness"[^>]*class="[^"]*text-micro[^"]*text-muted-foreground/,
    );
    expect(markup).not.toMatch(/valor esperado|cuota según PrediGol|p_model/i);
    expect(markup).toContain("Cuota grande: la mejor entre las casas y su casa.");
  });

  test("«Abrir partido» leads to the match's markets, on the market the reader was looking at", async () => {
    const { markup } = await explorer();
    expect(markup).toContain('href="/matches/7819?m=result_1x2.FT.match#markets"');
  });

  test("«Abrir partido» of the goals total names the catalogue's over/under", async () => {
    const { markup } = await explorer({ tab: "main", market: "goals.total", line: "4.5" });
    const hrefs = [...markup.matchAll(/data-testid="explorer-open-match"[^>]*href="([^"]+)"/g)].map(
      (m) => m[1],
    );
    expect(hrefs.length).toBeGreaterThan(0);
    for (const h of hrefs) expect(h).toMatch(/\?m=goals_over_under\.FT\.match#markets$/);
  });
});

describe("switching family, market, period and line", () => {
  test("Córners: its chips without the family's name, the total with its two periods and their matches", async () => {
    const { markup, data } = await explorer({ tab: "corners" });
    expect(markup).toContain('id="explorer-tab-corners"');
    expect(markup).toMatch(/data-testid="explorer-market-corners.total"[^>]*>Más\/menos</);
    expect(markup).toContain('data-market="corners.total"');
    expect(markup).toMatch(
      /data-testid="explorer-period-FT"[^>]*>Partido<span aria-hidden="true"[^>]*>5</,
    );
    expect(markup).toMatch(
      /data-testid="explorer-period-1H"[^>]*>1\.ª parte<span aria-hidden="true"[^>]*>3</,
    );
    expect(data.calls.board.at(-1)).toMatchObject({ market: "corners.total", period: "FT" });
    expect(markup).toContain("Solo consulta: este mercado no entra en Mi parlay.");
    expect(markup).not.toContain('data-testid="odds-add-to-parlay"');
  });

  test("another market of the tab, another period", async () => {
    const btts = await explorer({ tab: "main", market: "goals.btts" });
    expect(btts.markup).toContain('data-market="goals.btts"');
    expect(btts.markup).toMatch(
      /data-testid="explorer-market-goals.btts" aria-pressed="true"|aria-pressed="true"[^>]*data-testid="explorer-market-goals.btts"/,
    );
    const half = await explorer({ tab: "corners", market: "corners.total", period: "1H" });
    expect(half.markup).toContain('data-period="1H"');
    expect(half.data.calls.board.at(-1)).toMatchObject({ period: "1H" });
    expect(rowsOf(half.markup)).toHaveLength(3);
    // «Mitades» opens a market on its first half
    const halves = await explorer({ tab: "halves", market: "goals.total" });
    expect(halves.markup).toContain('data-period="1H"');
  });

  test("a line: the board asked at it, its chip on with the others shown, only the matches that have it", async () => {
    const main = await explorer({ tab: "main", market: "goals.total" });
    expect(main.markup).toContain('data-testid="explorer-line-main"');
    expect(main.markup).toContain("líneas más");
    expect(count(main.markup, 'data-testid="explorer-line"')).toBe(0);
    const at = await explorer({ tab: "main", market: "goals.total", line: "4.5" });
    expect(at.data.calls.board.at(-1)).toMatchObject({ line: "4.5" });
    expect(at.markup).toContain('data-line="4.5"');
    expect(at.markup).toMatch(
      /aria-pressed="true"[^>]*data-testid="explorer-line"[^>]*><span class="numeric">4,5</,
    );
    expect(rowsOf(at.markup)).toHaveLength(2);
    expect(cellLabels(rowOf(at.markup, 7820))).toEqual(["Más 4,5", "Menos 4,5"]);
  });

  test("a line no match has: say so and offer the main line back", async () => {
    const { markup } = await explorer({ tab: "main", market: "goals.total", line: "7.5" });
    expect(markup).toContain("Ningún partido tiene esta línea");
    expect(markup).toContain("Volver a la línea principal");
  });
});

describe("an Asian handicap and the parlay", () => {
  test("«Local -0,25 · Visitante +0,25»: each side at its own line; a quarter line only to look at", async () => {
    const { markup } = await explorer({ tab: "main", market: "result.asian_handicap" });
    const brighton = rowOf(markup, 7819);
    expect(cellLabels(brighton)).toEqual(["Local -0,25", "Visitante +0,25"]);
    expect(brighton).toContain("Brentford +0,25: mejor cuota");
    expect(brighton).not.toContain('data-testid="odds-add-to-parlay"');
    expect(brighton).toContain("no van en un parlay");
    expect(cellLabels(rowOf(markup, 7820))).toEqual(["Local -1,5", "Visitante +1,5"]);
    expect(count(rowOf(markup, 7820), 'data-testid="odds-add-to-parlay"')).toBe(2);
    expect(markup).toContain("Toca una cuota para agregarla a tu parlay o quitarla.");
  });

  test("a stale row: dimmed, «Antiguo · no entra al parlay», no price of it can be tapped", async () => {
    const { markup } = await explorer({ tab: "main", market: "result.1x2" });
    const stale = rowOf(markup, 7821);
    expect(stale.startsWith(' data-fixture="7821" data-stale="true"')).toBe(true);
    expect(stale).toContain('class="min-w-0 lg:flex-none opacity-60"');
    expect(stale).toContain('data-testid="explorer-stale-note"');
    expect(stale).toContain("Antiguo · no entra al parlay");
    expect(stale).toContain("Antiguo · hace 7 h");
    expect(stale).not.toContain('data-testid="odds-add-to-parlay"');
    expect(count(stale, 'data-block="stale"')).toBe(3);
  });

  test("an outlier price: shown and flagged, never a toggle; the rest of its row still are", async () => {
    const { markup } = await explorer({ tab: "main", market: "result.1x2" });
    const arsenal = rowOf(markup, 7822);
    expect(arsenal).toContain("Precio atípico");
    expect(arsenal).toContain('data-block="outlier"');
    expect(count(arsenal, 'data-testid="odds-add-to-parlay"')).toBe(2);
  });

  test("a selection in the slip: pressed, «Quitar de mi parlay»; no second «Mi parlay» bar over the product's button", async () => {
    const rows = fakeRows("result.1x2", "FT", "main");
    const madrid = rows.find((r) => r.fixture_id === 7820)!;
    const leg: SlipLeg = {
      key: "7820|1X2|Draw|0",
      fixture_id: 7820,
      market_key: "1X2",
      selection: "Draw",
      line: "0",
      home: madrid.home.name,
      away: madrid.away.name,
      kickoff_at: madrid.kickoff_at,
      odds: madrid.selections[1]!.best_odds,
      bookmaker: "Bet365",
    };
    const { markup } = await explorer({ tab: "main", market: "result.1x2" }, {}, [leg]);
    expect(rowOf(markup, 7820)).toContain('data-in-slip="true"');
    expect(rowOf(markup, 7820)).toContain("Quitar de mi parlay");
    // the way back to the slip is the product's own button (records/SlipSheet), the same on every screen
    expect(markup).not.toContain('data-testid="explorer-parlay-bar"');
    expect(markup).not.toContain("Mi parlay · 1");
  });
});

describe("long markets", () => {
  test("eight selections, «Ver todas» and a search of its own", async () => {
    const { markup } = await explorer({ tab: "goals", market: "goals.correct_score" });
    const row = rowOf(markup, 7819);
    expect(count(row, 'data-testid="explorer-price"')).toBe(8);
    expect(row).toContain("Ver todas (12)");
    expect(row).toContain('data-testid="explorer-long-search"');
    expect(markup).toContain("Este mercado no tiene cuota justa");
  });

  test("scorers: a single bookmaker, no comparison and no fair price", async () => {
    const { markup } = await explorer({ tab: "players" });
    expect(markup).toContain("1 casa: sin comparación ni cuota justa.");
    expect(rowOf(markup, 7819)).not.toContain('data-testid="explorer-compare-toggle"');
    expect(rowOf(markup, 7819)).not.toContain("justa ");
  });
});

/** A row on its own, with the in-memory data behind its panels. */
function env(o: Partial<RowEnv> = {}): RowEnv {
  const market = MARKETS["goals"]!.find((m) => m.key === "goals.total")!;
  return {
    data: fakeExplorerData(),
    info: market,
    period: "FT",
    family: "goals",
    bookmakers: new Map(BOOKMAKERS.map((b) => [b.id, b.name])),
    competitions: new Map(COMPETITIONS.map((c) => [c.id, c])),
    now: FAKE_NOW,
    moves: new Map(),
    version: 0,
    withDay: false,
    ...o,
  };
}

const goalsRow = (): OddsBoardRow =>
  fakeRows("goals.total", "FT", "main").find((r) => r.fixture_id === 7820)!;

describe("a row's panels", () => {
  test("«Comparar casas»: every bookmaker of the line, its margin, the first column fixed, scrollable by keyboard", async () => {
    const e = env();
    const markup = await html(
      <ul>
        <FixtureRow row={goalsRow()} env={e} defaultOpen="compare" />
      </ul>,
    );
    expect(markup).toContain('data-testid="explorer-compare"');
    expect(count(markup, 'data-testid="explorer-compare-row"')).toBe(8);
    expect(markup).toContain(">Margen<");
    expect(markup).toMatch(/\d,\d\u00a0%<\/td>/);
    expect(markup).toContain('role="region"');
    expect(markup).toContain('tabindex="0"');
    expect(markup).toContain("sticky left-0");
    expect(markup).toContain('aria-expanded="true"');
    expect(markup).toContain("(mejor cuota)");
    // asked for the match's book, of the family the period is filed under
    expect((e.data as ReturnType<typeof fakeExplorerData>).calls.book).toEqual([
      { fixtureId: 7820, family: "goals", enabled: true },
    ]);
  });

  test("«Movimiento»: an arrow and words for each selection, whether or not the chart has loaded", async () => {
    const markup = await html(
      <ul>
        <FixtureRow row={goalsRow()} env={env()} defaultOpen="movement" />
      </ul>,
    );
    expect(markup).toContain('data-testid="explorer-movement"');
    expect(count(markup, 'data-testid="explorer-move-summary"')).toBe(2);
    expect(markup).toMatch(/baja desde \d,\d\d · -\d/);
    expect(markup).toMatch(/sube desde \d,\d\d · \+\d/);
    // the words come before the chart, which is its own chunk (rules.test.ts): its place holder or, once loaded, the chart
    expect(markup).toMatch(
      /explorer-move-summary[\s\S]*(data-testid="explorer-chart"|motion-safe:animate-pulse)/,
    );
  });

  test("a market without history says so", async () => {
    const scorers = fakeRows("player.anytime_scorer", "FT", "main")[0]!;
    const info = MARKETS["players"]![0]!;
    const markup = await html(
      <ul>
        <FixtureRow row={scorers} env={env({ info, family: "players" })} defaultOpen="movement" />
      </ul>,
    );
    expect(markup).toContain("Este mercado no guarda historia de precios.");
  });
});

describe("motion", () => {
  test("a price that moved: its arrow always, its one tint only without «reduce motion»", async () => {
    const row = goalsRow();
    const sel = row.selections[0]!;
    const e = env({
      moves: new Map([[`7820|${sel.selection}||${sel.line}`, "up" as const]]),
      version: 3,
    });
    const markup = await html(
      <PriceCell row={row} sel={sel} env={e} sides={{ home: "A", away: "B" }} />,
    );
    expect(markup).toContain('data-move="up"');
    expect(markup).toContain("Subió en la última actualización");
    expect(markup).toMatch(/motion-safe:animate-out[^"]*motion-reduce:hidden/);
    const still = await html(
      <PriceCell row={row} sel={sel} env={env()} sides={{ home: "A", away: "B" }} />,
    );
    expect(still).not.toContain("data-move");
  });

  test("a change of market fades in only with motion; a tapped price scales only with motion", async () => {
    const { markup } = await explorer({ tab: "main", market: "result.1x2" });
    const card = markup.match(/<section[^>]*data-testid="explorer-card"[^>]*>/)?.[0] ?? "";
    expect(card).toContain(
      "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2",
    );
    expect(card).not.toMatch(/ animate-in/);
    expect(markup).toContain("motion-safe:active:scale-[0.97]");
    // the skeleton does not shimmer with «reduce motion»
    const pending = await explorer({}, { pending: true });
    expect(pending.markup).toContain("motion-safe:animate-pulse");
    expect(pending.markup).not.toMatch(/[" ]animate-pulse/);
  });
});

describe("loading, failing, empty", () => {
  test("loading: skeletons in the shape of the cards", async () => {
    const { markup } = await explorer({}, { pending: true });
    expect(markup).toContain('data-testid="explorer-skeleton"');
    expect(count(markup, 'data-testid="explorer-row-skeleton"')).toBe(4);
  });

  test("a refresh that failed keeps the board and says so in a line", async () => {
    const { markup } = await explorer({}, { boardError: "keep" });
    expect(markup).toContain('data-testid="stale-note"');
    expect(rowsOf(markup)).toHaveLength(5);
  });

  test("a board that never loaded: the error with a retry; families that never loaded: the same", async () => {
    const board = await explorer({}, { boardError: "empty" });
    expect(board.markup).toContain('role="alert"');
    expect(rowsOf(board.markup)).toHaveLength(0);
    const families = await explorer({}, { familiesError: true });
    expect(families.markup).toContain('role="alert"');
    expect(families.markup).not.toContain('data-testid="explorer-tabs"');
  });

  test("while filters apply: the results dimmed, a progress bar, busy", async () => {
    const { markup } = await explorer({ fairOnly: true }, { placeholder: true });
    expect(markup).toContain('data-testid="explorer-progress"');
    expect(markup).toContain(
      'aria-busy="true" class="motion-safe:transition-opacity motion-safe:duration-150 opacity-60"',
    );
  });

  test("filters that leave nothing: say so and offer to clear them", async () => {
    const { markup } = await explorer({ q: "zzzz" });
    expect(markup).toContain("Ningún partido coincide con tus filtros");
    expect(markup).toContain("Borrar filtros");
  });

  test("no market in the window: offer the next 72 h; the book switched off: say so", async () => {
    const empty = await explorer(
      {},
      { families: { window_hours: 24, families: [], book_enabled: true, generated_at: "" } },
    );
    expect(empty.markup).toContain("No hay cuotas en esta ventana");
    expect(empty.markup).toContain("Ver las próximas 72 h");
    const off = await explorer(
      {},
      { families: { window_hours: 24, families: [], book_enabled: false, generated_at: "" } },
    );
    expect(off.markup).toContain("El explorador todavía no tiene precios");
  });
});

describe("controls", () => {
  test("«Pausar actualizaciones» beside «Actualizado hh:mm»; the filters in a row and in a phone's sheet", async () => {
    const { markup } = await explorer();
    expect(markup).toContain('data-testid="explorer-pause"');
    expect(markup).toContain("Pausar actualizaciones");
    expect(markup).toContain('data-testid="explorer-filters-row"');
    expect(markup).toContain('data-testid="explorer-filters-open"');
    expect(markup).toContain('data-testid="explorer-live"');
    for (const word of [
      "Hoy",
      "24 h",
      "48 h",
      "72 h",
      "País",
      "Competición",
      "Casa",
      "Mínimo de casas",
      "Rango de cuota",
      "Solo con cuota justa",
    ]) {
      expect(markup).toContain(word);
    }
    // «Mis equipos y ligas» only when the reader's teams and leagues are known
    expect(markup).not.toContain("Mis equipos y ligas");
    const mine = await explorer(
      {},
      { follow: { teams: new Set([541]), leagues: new Set<number>() } },
    );
    expect(mine.markup).toContain("Mis equipos y ligas");
  });

  test("the widest difference with the fair price: its caveat, the matches in one list", async () => {
    const { markup } = await explorer({ sort: "edge" });
    expect(markup).toContain('data-testid="explorer-edge-caveat"');
    expect(markup).toContain("compara precios, no predice resultados");
    expect(rowOf(markup, 7821)).toBe("");
  });

  test("«Hoy»: only today's matches, «Mis equipos y ligas»: only the reader's", async () => {
    const today = await explorer({ window: "today" });
    expect(rowsOf(today.markup).map((r) => r.match(/data-fixture="(\d+)"/)?.[1])).toEqual([
      "7819",
      "7820",
    ]);
    const mine = await explorer(
      { mine: true },
      { follow: { teams: new Set([541]), leagues: new Set([2]) } },
    );
    expect(rowsOf(mine.markup).map((r) => r.match(/data-fixture="(\d+)"/)?.[1])).toEqual([
      "7820",
      "7823",
    ]);
    // the client's filters are counted over what is loaded: «2 partidos», not the API's 5
    expect(today.markup).toContain('data-testid="explorer-count">2 partidos<');
  });

  test("the client's filters with more pages to come: no count yet, and «Cargar más» even when none loaded fits", async () => {
    const { markup } = await explorer(
      { mine: true },
      { pageSize: 2, follow: { teams: new Set([505]), leagues: new Set<number>() } },
    );
    expect(rowsOf(markup)).toHaveLength(0);
    expect(markup).toContain("Ninguno de los partidos cargados coincide");
    expect(markup).toContain('data-testid="explorer-load-more"');
    expect(markup).not.toContain('data-testid="explorer-count"');
  });

  test("«Cargar más» while the API has another page", async () => {
    const { markup } = await explorer({}, { pageSize: 2 });
    expect(rowsOf(markup)).toHaveLength(2);
    expect(markup).toContain('data-testid="explorer-load-more"');
    expect(markup).toContain("2 de 5");
  });

  test("in English", async () => {
    setLocale("en");
    const { markup } = await explorer({ tab: "main", market: "result.asian_handicap" });
    expect(markup).toContain(">Handicaps<");
    expect(cellLabels(rowOf(markup, 7819))).toEqual(["Home -0.25", "Away +0.25"]);
    expect(markup).toContain("Pause updates");
    setLocale("es");
  });
});
