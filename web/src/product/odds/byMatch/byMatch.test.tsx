/// <reference types="bun" />
/**
 * Cuotas «Por partido» (UX-141): three markets joined match by match from the explorer's own data, a table on a desk and a
 * card per match on a phone, value marked in words and edge, «Mi parlay» at the side, and the honest empty states.
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
import { FAKE_NOW, fakeExplorerData } from "../explorer/fake";
import { ByMatchView } from "./ByMatchView";
import { BY_MATCH_MARKETS, filterLines, groupLines, joinBoards } from "./model";

setLocale("es");
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

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({
      component: () => <SlipContext.Provider value={slip()}>{node}</SlipContext.Provider>,
    }),
    history: createMemoryHistory({ initialEntries: ["/odds"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

describe("the boards joined match by match", () => {
  test("each match gets one cell per market it has, in the sheet's column order", () => {
    const data = fakeExplorerData();
    const pages = Object.fromEntries(
      BY_MATCH_MARKETS.map((m) => [
        m.key,
        data.useBoard(
          {
            hours: 72,
            day: null,
            country: null,
            competition: null,
            market: m.key,
            period: "FT",
            line: m.line,
            q: "",
            bookmaker: null,
            min_books: null,
            odds_min: null,
            odds_max: null,
            fair_only: false,
            sort: "time",
          },
          { paused: false, enabled: true },
        ).data,
      ]),
    );
    const board = joinBoards(pages);
    expect(board.lines.length).toBeGreaterThan(0);
    const first = board.lines[0]!;
    const cell = first.cells["result.1x2"];
    expect(cell?.prices.map((p) => p?.selection ?? null)).toEqual(["Home", "Draw", "Away"]);
    // kick-off order
    const times = board.lines.map((l) => Date.parse(l.kickoff_at));
    expect([...times].sort((a, b) => a - b)).toEqual(times);
    // value first, and «Solo con valor» keeps only matches with a price above its fair one
    const valued = filterLines(board.lines, { competition: null, valueOnly: true, sort: "value" });
    expect(valued.every((l) => (l.edge ?? 0) > 0)).toBe(true);
    // one group per competition by time; one list by value
    expect(groupLines(board.lines, "time", board.competitions).length).toBeGreaterThan(0);
    expect(groupLines(valued, "value", board.competitions).length).toBeLessThanOrEqual(1);
  });

  test("a match missing from a market simply has no cell there", () => {
    const board = joinBoards({});
    expect(board.lines).toEqual([]);
    expect(board.generatedAt).toBe(0);
  });
});

describe("the view", () => {
  test("a table on a desk and a card per match, both from the same prices, with the legend and Mi parlay", async () => {
    const page = await html(<ByMatchView data={fakeExplorerData()} guide={false} now={FAKE_NOW} />);
    expect(page).toContain('data-testid="by-match-table"');
    expect(page).toContain('data-testid="by-match-cards"');
    expect(page).toContain("Más 2,5");
    expect(page).toContain("AM sí");
    expect(page).toContain("Valor según PrediGol");
    expect(page).toContain('data-testid="slip-card"');
    expect(page).toContain('data-testid="by-match-price"');
  });

  test("nothing priced: an honest empty state, never invented rows", async () => {
    const page = await html(
      <ByMatchView data={fakeExplorerData({ boardError: "empty" })} guide={false} now={FAKE_NOW} />,
    );
    expect(page).not.toContain('data-testid="by-match-row"');
  });

  test("loading: skeletons, not an empty state", async () => {
    const page = await html(
      <ByMatchView data={fakeExplorerData({ pending: true })} guide={false} now={FAKE_NOW} />,
    );
    expect(page).not.toContain("Todavía no hay precios");
  });
});

describe("the day (AP-C01)", () => {
  test("the three boards ask for the chosen day and the tabs carry each day's matches", async () => {
    const data = fakeExplorerData({ byDay: true });
    const page = await html(
      <ByMatchView data={data} guide={false} now={FAKE_NOW} day="tomorrow" />,
    );
    expect(data.calls.board.map((q) => q.day)).toEqual(["tomorrow", "tomorrow", "tomorrow"]);
    expect(data.calls.families[0]).toMatchObject({ day: "tomorrow" });
    expect(page).toContain('data-testid="by-match-day"');
    for (const word of ["Hoy", "Mañana", "Pasado mañana", ", 2 partidos", ", 1 partido"]) {
      expect(page).toContain(word);
    }
    expect(page).toContain('data-fixture="7821"');
    expect(page).not.toContain('data-fixture="7819"');
  });

  test("without a day it opens on today", async () => {
    const data = fakeExplorerData({ byDay: true });
    const page = await html(<ByMatchView data={data} guide={false} now={FAKE_NOW} />);
    expect(data.calls.board.map((q) => q.day)).toEqual(["today", "today", "today"]);
    expect(page).toContain('data-fixture="7819"');
    expect(page).not.toContain('data-fixture="7821"');
  });
});
