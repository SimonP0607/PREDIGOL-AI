/// <reference types="bun" />
/**
 * The stories of a match (plan de correcciones UX, AP-N04; contrato C-06 `partido`): the window it covers, its cards with their
 * level, a way to each team's other stories; with no stories it draws nothing (the Noticias tab then keeps its cards).
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import type { MatchStories, StoryCard } from "@/lib/api/v1/types_stories";
import { MatchStoriesView } from "./MatchStories";

const NOW = Date.parse("2026-11-23T18:00:00Z");
const teams = [
  { id: 1, name: "Junior" },
  { id: 2, name: "Nacional" },
];
const card = (id: string): StoryCard => ({
  id,
  headline_es: `Titular ${id}`,
  summary_es: "Resumen",
  category: "bajas_y_sanciones",
  level: "dos_origenes",
  warnings: ["contradiccion"],
  sources_count: 2,
  latest_at: "2026-11-23T16:00:00Z",
  sources: [],
  entities: [],
  image: { kind: "monograma" },
});
const data = (n: number): MatchStories => ({
  fixture_id: 9,
  kickoff_at: "2026-11-25T00:00:00Z",
  window_from: "2026-11-18T00:00:00Z",
  stories: { items: Array.from({ length: n }, (_, i) => card(`st-${i}`)), count: n } as never,
});

async function render(node: React.ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => <>{node}</> }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

afterEach(() => setLocale("es"));

describe("the stories of a match", () => {
  test("title, window, count, level and the notice of a contradiction", async () => {
    const html = await render(<MatchStoriesView data={data(2)} teams={teams} now={NOW} />);
    expect(html).toContain("Historias del partido");
    expect(html).toContain("Desde el");
    expect(html).toContain("2 historias");
    expect(html).toContain("Dos orígenes");
    expect(html).toContain("Las fuentes se contradicen");
    expect(html).toContain('href="/news/st-0"');
  });
  test("a way to the other stories of each team", async () => {
    const html = await render(<MatchStoriesView data={data(1)} teams={teams} now={NOW} />);
    expect(html).toContain("Más historias de Junior");
    expect(html).toContain("Más historias de Nacional");
    expect(html).toContain("team=1");
  });
  test("with no stories it draws nothing", async () => {
    expect(await render(<MatchStoriesView data={data(0)} teams={teams} />)).toBe("");
  });
  test("English, one story", async () => {
    setLocale("en");
    const html = await render(<MatchStoriesView data={data(1)} teams={teams} now={NOW} />);
    expect(html).toContain("Match stories");
    expect(html).toContain("1 story");
  });
});
