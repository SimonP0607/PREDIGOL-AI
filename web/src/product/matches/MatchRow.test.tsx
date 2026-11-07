/// <reference types="bun" />
/**
 * A row of the list (plan Partidos, P6): the whole row opens the match, and «N casas» is a link of its own to the
 * match's Mercados - beside the row's link, never inside it (valid HTML) -, with its words written, not only in a
 * hover text. The applied filters and the empty states' buttons reach 44 px.
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
import type { MatchSummary } from "@/lib/api/v1/types";
import { setLocale } from "@/lib/i18n";
import { AppliedFilters } from "./Filters";
import { MatchRow } from "./MatchRow";
import type { MatchItem } from "./model";

afterAll(() => setLocale("es"));

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/matches"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function item(bookmakers: number, group: MatchItem["group"] = "scheduled"): MatchItem {
  return {
    group,
    live: null,
    match: {
      id: 70,
      provider_fixture_id: 70,
      kickoff_at: "2026-11-07T18:00:00Z",
      status_short: group === "postponed" ? "PST" : "NS",
      status_group: group === "postponed" ? "postponed" : "scheduled",
      round: null,
      competition: {
        id: 140,
        name: "La Liga",
        country: "Spain",
        provider_league_id: 140,
        season: 2026,
        competition_type: "domestic_league",
        is_tracked: true,
        priority_group: 1,
      },
      home: { id: 1, name: "Real Betis", provider_team_id: 543 },
      away: { id: 2, name: "Sevilla", provider_team_id: 536 },
      score: null,
      odds: {
        snapshots: 3,
        bookmakers,
        markets: 5,
        first_captured_at: null,
        last_captured_at: null,
        near_close_snapshots: 0,
      },
      predictions: 0,
      awaiting_result: false,
    } as MatchSummary,
  };
}

describe("a row of the list", () => {
  test("«N casas» opens Mercados, beside the row's link: no link inside a link", async () => {
    setLocale("es");
    const out = await html(<MatchRow item={item(8)} />);
    const anchors = out.match(/<a\b[^>]*>[\s\S]*?<\/a>/g) ?? [];
    expect(anchors).toHaveLength(2);
    for (const a of anchors) expect(a.slice(2)).not.toContain("<a ");
    const [row, chip] = anchors as [string, string];
    expect(row).toContain('href="/matches/70"');
    expect(row).toContain('data-testid="match-row"');
    expect(row).toContain("Real Betis");
    expect(chip).toContain('href="/matches/70#markets"');
    expect(chip).toContain('data-testid="match-odds"');
    // its words in the page, the screen reader told what it counts and where it goes
    expect(chip).toContain("8 casas");
    expect(chip).toContain("Cuotas de 8 casas de apuestas");
    expect(chip).toContain("Ver sus cuotas en Mercados");
    expect(chip).toContain("tap ");
  });

  test("no chip without bookmakers; a postponed match still says so inside the row's link", async () => {
    setLocale("es");
    const out = await html(<MatchRow item={item(0, "postponed")} />);
    expect(out.match(/<a\b/g)).toHaveLength(1);
    expect(out).not.toContain("match-odds");
    const row = /<a\b[^>]*>[\s\S]*?<\/a>/.exec(out)?.[0] ?? "";
    expect(row).toMatch(/sr-only">Aplazado</);
  });

  test("in English too", async () => {
    setLocale("en");
    const out = await html(<MatchRow item={item(1)} />);
    expect(out).toContain("1 book");
    expect(out).toContain("See its odds in Markets");
  });
});

describe("the filters on", () => {
  test("a chip with «×» each, and «Limpiar»", () => {
    setLocale("es");
    const out = renderToStaticMarkup(
      <AppliedFilters
        filters={[
          { key: "country", label: "España", onRemove: () => {} },
          { key: "query", label: "«betis»", onRemove: () => {} },
        ]}
        onClear={() => {}}
        showClear
      />,
    );
    expect(out).toContain('data-testid="applied-country"');
    expect(out).toContain('aria-label="Quitar filtro: España"');
    expect(out).toContain('data-testid="applied-query"');
    expect(out).toMatch(/data-testid="matches-clear"[^>]*>Limpiar</);
    // 44 px on a touch screen: the chips' and the button's reach
    expect(out.match(/tap-y/g)?.length).toBe(3);
  });

  test("nothing while the list is the whole day", () => {
    expect(
      renderToStaticMarkup(<AppliedFilters filters={[]} onClear={() => {}} showClear={false} />),
    ).toBe("");
  });
});
