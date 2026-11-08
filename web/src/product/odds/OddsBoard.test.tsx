/// <reference types="bun" />
/**
 * The Cuotas board as a reader gets it (plan Cuotas, ola 0): an Asian handicap's two prices each at their own signed line
 * (E1), an outlier price that never goes in the parlay (E2), a row as old as its oldest price (E3), a quarter line only to
 * look at and no promise of a tap there (E14), the empty highlights that say the filters hid them (E6) and a price toggle
 * whose name says what a tap does now (E7).
 */
import { afterAll, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import type { BestMarket, BestOddsFixture, BestPrice } from "@/lib/api/v1/types_product";
import { setLocale } from "@/lib/i18n";
import { formatRelative } from "@/lib/time";
import type { SlipLeg } from "@/product/records/model";
import { SlipContext, type SlipValue } from "@/product/records/slipContext";
import { Highlights } from "./Highlights";
import { OddsBoard } from "./OddsBoard";
import { ParlayToggle } from "./ParlayPrice";

setLocale("es");
afterAll(() => setLocale("es"));

const KICKOFF = new Date(Date.now() + 6 * 3_600_000).toISOString();
const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

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

function price(selection: string, best_odds: string, extra: Partial<BestPrice> = {}): BestPrice {
  return {
    selection,
    best_odds,
    bookmaker: "Pinnacle",
    p_fair: "0.5",
    fair_odds: "2.000",
    price_edge: "-0.02",
    n_bookmakers: 8,
    as_of: ago(10),
    ...extra,
  };
}

function fixture(market: BestMarket, id = 7819): BestOddsFixture {
  return {
    fixture_id: id,
    kickoff_at: KICKOFF,
    competition: {
      id: 39,
      name: "Premier League",
      country: "England",
      logo_url: null,
      flag_url: null,
    },
    home: { id: 51, name: "Brighton", logo_url: null },
    away: { id: 55, name: "Brentford", logo_url: null },
    markets: [market],
    as_of: ago(2),
  };
}

/** The visible text of every board cell, in order. */
function cellLabels(markup: string): string[] {
  return [
    ...markup.matchAll(
      /<span class="truncate text-xs font-semibold text-foreground">([^<]*)<\/span>/g,
    ),
  ].map((m) => m[1] as string);
}

describe("an Asian handicap row (E1)", () => {
  test("each side at its own signed line: 1 -0,25 beside 2 +0,25", async () => {
    const ah = fixture({
      market_key: "AH",
      line: "-0.50",
      selections: [price("Home", "1.95"), price("Away", "1.92")],
    });
    const markup = await html(<OddsBoard fixtures={[ah]} market="AH" hours={24} />);
    expect(cellLabels(markup)).toEqual(["1 -0,5", "2 +0,5"]);
    expect(markup).toContain("Brentford +0,5: 1,92 en Pinnacle");
  });
});

describe("a quarter line is only to look at (E14)", () => {
  const quarter = fixture({
    market_key: "AH",
    line: "-0.25",
    selections: [price("Home", "1.67"), price("Away", "2.45")],
  });
  const half = fixture(
    { market_key: "AH", line: "-0.50", selections: [price("Home", "1.95"), price("Away", "1.92")] },
    7820,
  );

  test("its row says «Solo consulta», no price on it is a toggle, and the board promises no tap", async () => {
    const markup = await html(<OddsBoard fixtures={[quarter]} market="AH" hours={24} />);
    expect(cellLabels(markup)).toEqual(["1 -0,25", "2 +0,25"]);
    expect(markup).toContain('data-testid="odds-lookup-only"');
    expect(markup).toContain(">Solo consulta<");
    expect(markup).not.toContain('data-testid="odds-add-to-parlay"');
    expect(markup).toContain("no van en un parlay");
    expect(markup).not.toContain("Toca una cuota");
  });

  test("beside rows that can be added, the help stays and only the quarter row is marked", async () => {
    const markup = await html(<OddsBoard fixtures={[quarter, half]} market="AH" hours={24} />);
    expect(markup).toContain("Toca una cuota para agregarla a tu parlay o quitarla.");
    expect(markup.match(/data-testid="odds-lookup-only"/g)).toHaveLength(1);
    expect(markup.match(/data-testid="odds-add-to-parlay"/g)).toHaveLength(2);
  });
});

describe("an outlier price (E2)", () => {
  test("is shown, flagged and never a toggle; the other prices of its row still are", async () => {
    const row = fixture({
      market_key: "1X2",
      line: "0.00",
      selections: [
        price("Home", "3.40", { price_edge: "0.32", outlier: true }),
        price("Draw", "3.30"),
        price("Away", "2.60"),
      ],
    });
    const markup = await html(<OddsBoard fixtures={[row]} market="1X2" hours={24} />);
    expect(markup).toContain("Precio atípico");
    expect(markup).toContain("Los precios atípicos no van en un parlay");
    expect(markup.match(/data-testid="odds-add-to-parlay"/g)).toHaveLength(2);
  });
});

describe("a row's age (E3)", () => {
  test("is the age of its OLDEST price, not the fixture's newest", async () => {
    const row = fixture({
      market_key: "OU",
      line: "2.5",
      selections: [
        price("Over", "1.90", { as_of: ago(5) }),
        price("Under", "1.95", { as_of: ago(130) }),
      ],
    });
    const markup = await html(<OddsBoard fixtures={[row]} market="OU" hours={24} />);
    expect(markup).toContain(formatRelative(ago(130)));
    expect(markup).not.toContain(`>${formatRelative(row.as_of)}<`);
  });
});

describe("the highlights (E6)", () => {
  test("say the filters hid them, not that there are none", async () => {
    expect(await html(<Highlights items={[]} filteredOut />)).toContain(
      "Ningún destacado con estos filtros.",
    );
    expect(await html(<Highlights items={[]} />)).toContain(
      "Todavía no hay precios por encima del mercado.",
    );
  });
});

describe("a price toggle (E7)", () => {
  const state = (inSlip: boolean) => ({
    inSlip,
    block: null,
    replaces: false,
    toggle: () => undefined,
  });

  test("a screen reader hears «Quitar de mi parlay» once the selection is in", () => {
    const inside = renderToStaticMarkup(
      <ParlayToggle state={state(true)} srLabel="Brighton -0,25: 1,67">
        1,67
      </ParlayToggle>,
    );
    expect(inside).toContain('aria-pressed="true"');
    expect(inside).toContain(
      '<span class="sr-only">Brighton -0,25: 1,67 Quitar de mi parlay</span>',
    );
    const outside = renderToStaticMarkup(
      <ParlayToggle state={state(false)} srLabel="Brighton -0,25: 1,67">
        1,67
      </ParlayToggle>,
    );
    expect(outside).toContain(
      '<span class="sr-only">Brighton -0,25: 1,67 Agregar a mi parlay</span>',
    );
  });
});
