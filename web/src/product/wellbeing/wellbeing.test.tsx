/// <reference types="bun" />
/**
 * «Solo fútbol» and the pause (plan PM, PM-14-07): outside a signed-in reader who chose it, nothing changes; for one who did, every
 * address that is a price leaves the bars and no price is drawn.
 */
import { describe, expect, test } from "bun:test";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { OddsPill } from "@/product/shared/Bits";
import { WellbeingSettings } from "@/product/profile/WellbeingSettings";
import {
  barNav,
  deskExtras,
  isPriceAddress,
  moreItems,
  NAV_V1,
  PRICE_ADDRESSES,
  type NavFlags,
} from "@/components/layout/nav";
import { WellbeingPage } from "./WellbeingPage";

setLocale("es");
const QUIET: NavFlags = { ...NAV_V1, noPrices: true };
const V2: NavFlags = { v2: true, news: true, profiles: true };
const V2_QUIET: NavFlags = { ...V2, noPrices: true };

const addresses = (items: readonly { to: string }[]) => items.map((i) => i.to);

describe("the bars of a reader who sees no price", () => {
  test("the addresses that are a price are known", () => {
    for (const a of PRICE_ADDRESSES) expect(isPriceAddress(a)).toBe(true);
    expect(isPriceAddress("/odds/12")).toBe(true);
    expect(isPriceAddress("/picks/")).toBe(true);
    for (const a of ["/home", "/matches", "/matches/7", "/news", "/profile", "/help", "/oddsy"])
      expect(isPriceAddress(a)).toBe(false);
  });

  test("with the choice off the bars are what they always were", () => {
    expect(addresses(barNav(NAV_V1))).toContain("/picks");
    expect(addresses(barNav(V2))).toContain("/picks");
    expect(addresses(moreItems(true, true, NAV_V1))).toContain("/odds");
    expect(deskExtras(NAV_V1).map((x) => x.item.to)).toContain("/odds");
  });

  test.each([
    ["the bar of always", QUIET],
    ["the unified bar", V2_QUIET],
  ])("%s holds no address that is a price", (_name, flags) => {
    for (const list of [
      addresses(barNav(flags)),
      addresses(moreItems(true, true, flags)),
      deskExtras(flags).map((x) => x.item.to),
    ]) {
      expect(list.filter((to) => isPriceAddress(to))).toEqual([]);
    }
    expect(addresses(barNav(flags))).toContain("/matches");
    expect(addresses(moreItems(true, true, flags))).toContain("/profile");
  });
});

describe("what is drawn", () => {
  test("a price is drawn outside the choice (a component alone, nothing chosen)", () => {
    expect(renderToStaticMarkup(<OddsPill odds="2.10" />)).toContain("2");
  });

  test("the settings draw nothing while the owner has not opened the choice", () => {
    expect(renderToStaticMarkup(<WellbeingSettings />)).toBe("");
  });

  test("the page says why, and where football and the choice are", async () => {
    const router = createRouter({
      routeTree: createRootRoute({ component: () => <WellbeingPage /> }),
      history: createMemoryHistory({ initialEntries: ["/"] }),
    });
    await router.load();
    const html = renderToStaticMarkup(<RouterProvider router={router} />);
    expect(html).toContain('data-testid="wellbeing-page"');
    expect(html).toContain('href="/matches"');
    expect(html).toContain('href="/profile"');
    expect(html.replace(/<[^>]+>/g, " ")).toContain("solo fútbol");
  });
});
