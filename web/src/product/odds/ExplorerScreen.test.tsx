/// <reference types="bun" />
/**
 * Cuotas with the explorer on (plan Cuotas, UX-069): the route's search is the explorer's state - a link with a family, a
 * market, a line, a window and an order opens the explorer there and asks the API for that board -, a link without any
 * opens the first family with prices, and the guide of the screen rests on the explorer's tabs and fair-price line.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import { SlipContext, type SlipValue } from "@/product/records/slipContext";
import { FAKE_NOW, fakeExplorerData } from "./explorer/fake";
import { validateOddsSearch } from "./oddsSearch";
import { ExplorerScreen } from "./ExplorerScreen";

setLocale("es");
afterAll(() => setLocale("es"));

const SLIP: SlipValue = {
  legs: [],
  has: () => false,
  toggle: () => undefined,
  remove: () => undefined,
  clear: () => undefined,
  load: () => undefined,
  undo: null,
  restore: () => undefined,
  open: false,
  setOpen: () => undefined,
};

async function screen(url: string) {
  const data = fakeExplorerData();
  const root = createRootRoute({
    component: () => (
      <SlipContext.Provider value={SLIP}>
        <Outlet />
      </SlipContext.Provider>
    ),
  });
  const odds = createRoute({
    getParentRoute: () => root,
    path: "/odds",
    validateSearch: validateOddsSearch,
    component: () => <ExplorerScreen data={data} guide={false} now={FAKE_NOW} />,
  });
  const router = createRouter({
    routeTree: root.addChildren([odds]),
    history: createMemoryHistory({ initialEntries: [url] }),
  });
  await router.load();
  return { html: renderToStaticMarkup(<RouterProvider router={router} />), data, router };
}

describe("Cuotas with the explorer on", () => {
  test("a link with a family, a market, a line, a window and an order opens the explorer there", async () => {
    const { html, data, router } = await screen(
      "/odds?f=main&m=goals.total&l=4.5&h=48&sort=competition&nb=abc&utm_source=x",
    );
    expect(html).toContain('data-testid="odds-explorer"');
    expect(html).toMatch(/aria-selected="true"[^>]*data-testid="explorer-tab-main"/);
    expect(html).toContain('data-market="goals.total"');
    expect(html).toContain('data-line="4.5"');
    // a value the explorer cannot read («nb=abc») changes nothing
    expect(data.calls.board.at(-1)).toMatchObject({
      market: "goals.total",
      line: "4.5",
      hours: 48,
      sort: "competition",
      min_books: null,
    });
    // the route reads the explorer's keys as numbers and words
    expect(router.state.matches.at(-1)?.search).toMatchObject({
      f: "main",
      m: "goals.total",
      l: 4.5,
      h: 48,
      sort: "competition",
    });
  });

  test("a link without any: the first family with prices, its first market, the next 24 hours", async () => {
    const { html, data } = await screen("/odds");
    expect(html).toMatch(/aria-selected="true"[^>]*data-testid="explorer-tab-main"/);
    expect(data.calls.board.at(-1)).toMatchObject({
      market: "result.1x2",
      line: "main",
      hours: 24,
      sort: "time",
    });
  });

  test("the guide of Cuotas rests on the explorer: its tabs and the fair-price line", async () => {
    const { html } = await screen("/odds");
    expect(html).toMatch(/data-testid="explorer-tabs" data-guide="odds-tabs"/);
    expect(html).toContain('data-guide="odds-fair"');
    // the old page's «solo por encima de la justa» has no place here: that step is left out
    expect(html).not.toContain('data-guide="odds-above"');
  });
});
