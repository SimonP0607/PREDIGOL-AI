/// <reference types="bun" />
/**
 * PLAN F8, the entities of the memory in the Admin Console, rendered: each series with the version of the memory that wrote it, how far to
 * trust it (its confidence, or "none" for a series written before memory-v4, which did not measure it), what it rests on (the matches, or
 * the decisions and the post-mortems that judged them, with the newest matches linked) and the figures of memory-v4. Both languages.
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
import { setLocale } from "@/lib/i18n";
import type { IntelMemoryRow } from "@/lib/api/v1/types_intel";
import { EntityTable } from "./MemoryEntities";

afterAll(() => setLocale("es"));

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

async function render(node: ReactNode): Promise<{ html: string; text: string }> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  const html = renderToStaticMarkup(<RouterProvider router={router} />);
  return { html, text: text(html) };
}

function row(over: Partial<IntelMemoryRow>): IntelMemoryRow {
  return {
    entity_type: "team",
    entity_id: "1",
    entity_name: "Alpha",
    aspect: "corners",
    as_of_day: "2026-10-20",
    version: "memory-v4",
    stats: {},
    delta: {},
    confidence: null,
    evidence_ref: null,
    ...over,
  };
}

/** The newest forty matches of a team: the memory keeps no more ids than that, whatever the number it rests on. */
const FORTY = Array.from({ length: 40 }, (_, i) => 900 - i);

const figures = row({
  entity_name: "Alpha",
  confidence: 0.6283,
  stats: { matches: 12, own_shrunk: 5.4, opp_shrunk: 4.1, prior: 4.8, own_rate: 6, opp_rate: 3 },
  evidence_ref: { fixtures: FORTY },
});
const decisions = row({
  entity_type: "market",
  entity_id: "OU",
  entity_name: "Over/Under",
  aspect: "decisions",
  confidence: 0.2,
  stats: { decisions: 9, wins: 5, losses: 3, voids: 1, clv_mean: 0.0123, last10: ["W", "L", "W"] },
  evidence_ref: { decisions: [11, 12, 13], postmortems: [21] },
});
const legacy = row({
  entity_name: "Beta",
  entity_id: "2",
  aspect: "market:1X2",
  version: "memory-v3",
  stats: { decisions: 4, wins: 1, losses: 2, voids: 0 },
});

describe("the entities table (F8)", () => {
  test("it names its columns: the version, the confidence and the evidence come with every series", async () => {
    setLocale("en");
    const { text: said } = await render(<EntityTable items={[figures]} />);
    for (const column of [
      "Entity",
      "Aspect",
      "As of",
      "Sample",
      "Confidence",
      "Evidence",
      "Detail",
    ])
      expect(said).toContain(column);
    expect(said).toContain("memory-v4");
  });

  test("a series shows its confidence, its sample and the figures shrunk toward its league's", async () => {
    setLocale("en");
    const { text: said } = await render(<EntityTable items={[figures]} />);
    expect(said).toMatch(/Alpha/);
    expect(said).toMatch(/63\s?%/);
    expect(said).toContain("own 5.40, rivals 4.10 per match (league 4.80)");
    expect(said).toContain(" 12 "); // the matches it rests on
  });

  test("the evidence says how many matches there are, that they are the newest ones, and links the first three", async () => {
    setLocale("en");
    const { html, text: said } = await render(<EntityTable items={[figures]} />);
    expect(said).toContain("40 matches (the newest 40)");
    const links = [...html.matchAll(/href="\/matches\/(\d+)"/g)].map((m) => m[1]);
    expect(links).toEqual(["900", "899", "898"]);
  });

  test("a market series shows the decisions and the post-mortems that judged them, its record and its mean CLV", async () => {
    setLocale("en");
    const { html, text: said } = await render(<EntityTable items={[decisions]} />);
    expect(said).toContain("3 decisions");
    expect(said).toContain("1 post-mortem");
    expect(said).not.toContain("the newest"); // fewer ids than the memory keeps: that is all of them
    expect(said).toContain("5 / 3 / 1");
    expect(said).toContain("+1.2");
    expect(said).toContain("WLW");
    expect(html).not.toContain('href="/matches/'); // decisions are not matches: nothing to link to
  });

  test("a series from before memory-v4 says it has no confidence and no evidence, and keeps its version", async () => {
    setLocale("en");
    const { html, text: said } = await render(<EntityTable items={[legacy]} />);
    expect(said).toContain("memory-v3");
    expect(said).toContain("none"); // the confidence badge
    expect(said).not.toMatch(/\d+\s?%\s*</); // never a made-up percentage
    expect(html).not.toContain("memory-evidence"); // a dash instead of the evidence block
  });

  test("each series is a row of its own, in Spanish too", async () => {
    setLocale("es");
    const { html, text: said } = await render(<EntityTable items={[figures, decisions, legacy]} />);
    expect(html.match(/<tr/g)).toHaveLength(4); // the header and three series
    expect(said).toContain("Confianza");
    expect(said).toContain("Evidencia");
    expect(said).toContain("40 partidos (las 40 más recientes)");
    expect(said).toContain("3 decisiones");
    expect(said).toContain("ninguna");
  });
});
