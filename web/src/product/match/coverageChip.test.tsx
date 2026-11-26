/// <reference types="bun" />
/**
 * Plan PM, lámina I04 (UX-243): the chip «Cobertura X» in the Match Center's head and the link to the competition's own table. The
 * chip says what C-16 says of the competition and nothing when it is silent or its switches are off; the link points at the
 * competition's page.
 */
import { describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { renderToStaticMarkup } from "react-dom/server";
import type { CompetitionAvailability } from "@/lib/api/v1/types_availability";
import { setLocale } from "@/lib/i18n";
import { CompetitionTableLinkTo } from "./ContextBlocks";
import { CoverageChipOf, MatchCoverageChip } from "./MatchCoverageChip";

setLocale("es");

const summary = (level: CompetitionAvailability["summary"], label: string) =>
  ({
    competition_id: 271,
    name: "NB I",
    country: "Hungary",
    tier: 1,
    summary: level,
    summary_label: label,
    families: [],
    seasons: [],
  }) as CompetitionAvailability;

describe("the chip «Cobertura X» of the Match Center's head", () => {
  test("says the level of the competition as its own page writes it", () => {
    const html = renderToStaticMarkup(<CoverageChipOf summary={summary("B", "B*")} />);
    expect(html).toContain('data-testid="match-coverage-chip"');
    expect(html).toContain('data-level="B"');
    expect(html).toContain("Cobertura B*");
    expect(html).toContain("cobertura suficiente");
  });

  test("a level D competition says so, with its letter", () => {
    const html = renderToStaticMarkup(<CoverageChipOf summary={summary("D", "D")} />);
    expect(html).toContain('data-level="D"');
    expect(html).toContain("Cobertura D");
  });

  test("draws nothing while C-16 has not answered", () => {
    expect(renderToStaticMarkup(<CoverageChipOf summary={null} />)).toBe("");
  });

  test("draws nothing, and asks nothing, while the switches are off", () => {
    const client = new QueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <MatchCoverageChip competitionId={271} />
      </QueryClientProvider>,
    );
    expect(html).toBe("");
    expect(
      client
        .getQueryCache()
        .getAll()
        .every((q) => q.state.fetchStatus === "idle"),
    ).toBe(true);
  });
});

describe("the link to the competition's table", () => {
  test("goes to the competition's page", async () => {
    const router = createRouter({
      routeTree: createRootRoute({
        component: () => <CompetitionTableLinkTo competitionId={271} />,
      }),
      history: createMemoryHistory({ initialEntries: ["/"] }),
    });
    await router.load();
    const html = renderToStaticMarkup(<RouterProvider router={router} />);
    expect(html).toContain("competition-table-link");
    expect(html).toContain("Tabla completa de la competición");
  });
});
