/// <reference types="bun" />
/**
 * Plan UX AP-I02 (D16): Inicio does not say «Datos en vivo actualizados hace 2 min» on every visit. A reader hears of it only when
 * what is in play is late (more than 5 minutes); the administrator always sees the hour of the reading.
 */
import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLocale } from "@/lib/i18n";
import { HomeFreshness } from "./HomeHeader";

const realNow = Date.now;
const NOW = Date.parse("2026-11-23T20:00:00Z");
beforeAll(() => {
  Date.now = () => NOW;
  setLocale("es");
});
afterAll(() => {
  Date.now = realNow;
});

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({
      component: () => <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
    }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

const ago = (minutes: number) => ({ live_at: new Date(NOW - minutes * 60_000).toISOString() });

describe("Inicio's freshness line", () => {
  test("a reader with fresh live data sees no line at all", async () => {
    const out = await html(
      <HomeFreshness freshness={ago(2)} inPlay admin={false} loading={false} />,
    );
    expect(out).not.toContain("home-freshness");
    expect(out).not.toContain("Datos en vivo");
  });

  test("a reader is told when what is in play is more than 5 minutes late", async () => {
    const out = await html(
      <HomeFreshness freshness={ago(9)} inPlay admin={false} loading={false} />,
    );
    expect(out).toContain('data-testid="home-freshness"');
    expect(out).toContain("Los datos van con retraso; los estamos actualizando.");
  });

  test("with nothing in play the age of the last live reading means nothing to a reader", async () => {
    const out = await html(
      <HomeFreshness freshness={ago(300)} inPlay={false} admin={false} loading={false} />,
    );
    expect(out).not.toContain("home-freshness");
  });

  test("the administrator always sees the hour of the reading", async () => {
    const out = await html(
      <HomeFreshness freshness={ago(2)} inPlay={false} admin loading={false} />,
    );
    expect(out).toContain('data-testid="home-freshness"');
    expect(out).toContain("Datos en vivo de las");
  });

  test("the administrator is told too when there is no reading", async () => {
    const out = await html(
      <HomeFreshness freshness={{ live_at: null }} inPlay={false} admin loading={false} />,
    );
    expect(out).toContain("Sin datos en vivo recientes");
  });

  test("while loading nothing is claimed", async () => {
    const out = await html(<HomeFreshness freshness={null} inPlay={false} admin loading />);
    expect(out).not.toContain("home-freshness");
  });
});
