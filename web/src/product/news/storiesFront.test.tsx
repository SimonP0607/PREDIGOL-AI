/// <reference types="bun" />
/**
 * The front page and the search of the news as stories (plan de correcciones UX, AP-N01 and AP-N03; maquetas 08 and 10): the
 * address holds every filter and drops what is invalid; the front lists the lead, the last hour, the teams one follows, the
 * featured ones and the topics with their counts; the search shows its facets, its applied filters (each removable) and the
 * stories - never an article's text.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import type { SearchHit, StoryCard, StoryFront, StorySearch } from "@/lib/api/v1/types_stories";
import { FrontView, SearchView } from "./StoriesPage";
import { StoryCardView, StoryHitView, byline } from "./StoryCardView";
import {
  isFront,
  parseStoriesSearch,
  storiesQuery,
  without,
  type StoriesSearchParams,
} from "./storiesSearch";

const NOW = Date.parse("2026-11-23T18:00:00Z");

function card(id: string, over: Partial<StoryCard> = {}): StoryCard {
  return {
    id,
    headline_es: `Titular ${id}`,
    summary_es: `Resumen ${id}`,
    category: "colombia",
    level: "un_medio",
    warnings: [],
    sources_count: 2,
    latest_at: "2026-11-23T16:00:00Z",
    sources: [
      {
        name: "Diario",
        author: null as never,
        published_at: "2026-11-23T15:00:00Z",
        published_day_only: false,
        known_at: "2026-11-23T15:10:00Z",
        url: "https://d.example/x",
      },
      {
        name: "Radio",
        author: null as never,
        published_at: null as never,
        published_day_only: false,
        known_at: "2026-11-23T15:30:00Z",
        url: "https://r.example/x",
      },
    ],
    entities: [
      {
        type: "team",
        id: 1,
        name: "Junior",
        role: "protagonista",
        method: "plantilla",
        confidence: 1,
      },
    ],
    image: { kind: "monograma" },
    ...over,
  };
}
const list = <T,>(items: T[]) => ({ items, count: items.length }) as never;

function front(over: Partial<StoryFront> = {}): StoryFront {
  return {
    lead_story: card("st-lead", { level: "oficial" }),
    breaking: list([card("st-b1"), card("st-b2")]),
    mine: list([]),
    featured: list([card("st-f1")]),
    counts: [
      { category: "colombia", n: 5 },
      { category: "fichajes", n: 2 },
    ],
    window_hours: 48,
    order_version: "v1",
    ...over,
  };
}

async function render(node: React.ReactNode, qc = new QueryClient()): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({
      component: () => <QueryClientProvider client={qc}>{node}</QueryClientProvider>,
    }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

afterEach(() => setLocale("es"));

describe("the address", () => {
  test("keeps what is valid and drops the rest", () => {
    expect(
      parseStoriesSearch({
        q: "  nacional  ",
        team: "12",
        player: "x",
        competition: -3,
        country: "co",
        since: "2026-11-01",
        until: "mañana",
        category: "fichajes",
        level: "inventado",
        mine: "true",
        sort: "relevante",
      }),
    ).toEqual({
      q: "nacional",
      team: 12,
      country: "CO",
      since: "2026-11-01",
      category: "fichajes",
      mine: true,
      sort: "relevante",
    });
  });
  test("an empty address is the front page; anything else is a search", () => {
    expect(isFront(parseStoriesSearch({}))).toBe(true);
    expect(isFront(parseStoriesSearch({ q: "a" }))).toBe(false);
    expect(isFront(parseStoriesSearch({ level: "rumor" }))).toBe(false);
  });
  test("the API's query: whole days, twenty at a time, the page's offset", () => {
    const s: StoriesSearchParams = {
      q: "junior",
      since: "2026-11-01",
      until: "2026-11-02",
      mine: true,
    };
    expect(storiesQuery(s)).toEqual({
      q: "junior",
      since: "2026-11-01T00:00:00Z",
      until: "2026-11-02T23:59:59Z",
      mine: true,
      limit: 20,
    });
    expect(storiesQuery({}, 40).offset).toBe(40);
  });
  test("removing a filter leaves the others", () => {
    expect(without({ q: "a", level: "rumor" }, "q")).toEqual({ level: "rumor" });
  });
});

describe("the cards", () => {
  test("byline: who, how many, when", () => {
    expect(byline(card("st-1"), NOW)).toContain("Según Diario · Radio");
    expect(byline(card("st-1"), NOW)).toContain("2 fuentes");
  });
  test("a card leads to its story and shows level, monogram and PrediGol's words", async () => {
    const html = await render(
      <ul>
        <StoryCardView card={card("st-9")} now={NOW} />
      </ul>,
    );
    expect(html).toContain('href="/news/st-9"');
    expect(html).toContain("Titular st-9");
    expect(html).toContain("Resumen st-9");
    expect(html).toContain("Un medio");
    expect(html).toContain("JU");
  });
  test("a card with no summary shows no source text", async () => {
    const html = await render(
      <ul>
        <StoryCardView
          card={card("st-9", { summary_es: null as never, headline_es: null as never })}
          now={NOW}
        />
      </ul>,
    );
    expect(html).toContain("Historia sin titular todavía");
    expect(html).not.toContain("Resumen");
  });
  test("a hit shows its level and its source count", async () => {
    const hit: SearchHit = {
      story_id: "st-4",
      headline_es: "Hallazgo",
      level: "rumor",
      category: "fichajes",
      sources_count: 1,
      latest_at: "2026-11-23T10:00:00Z",
    };
    const html = await render(
      <ul>
        <StoryHitView hit={hit} now={NOW} />
      </ul>,
    );
    expect(html).toContain("Rumor");
    expect(html).toContain("1 fuente");
  });
});

describe("the front page", () => {
  test("lead, last hour, featured and the topics with their counts", async () => {
    const html = await render(<FrontView front={front()} go={() => {}} now={NOW} />);
    for (const id of [
      "stories-lead",
      "stories-breaking",
      "stories-mine",
      "stories-featured",
      "stories-topics",
    ]) {
      expect(html).toContain(`data-testid="${id}"`);
    }
    expect(html).toContain("Titular st-lead");
    expect(html).toContain("Historias de las últimas 48 horas");
    expect(html).toMatch(/stories-topic-colombia[\s\S]*?Fútbol colombiano[\s\S]*?>5</);
    expect(html).toContain("Sigue equipos y jugadores");
  });
  test("a topic with no stories cannot be opened", async () => {
    const html = await render(<FrontView front={front()} go={() => {}} now={NOW} />);
    expect(html).toMatch(
      /stories-topic-selecciones"[^>]*disabled|disabled=""[^>]*stories-topic-selecciones/,
    );
  });
  test("«Tus equipos» lists the stories of what one follows", async () => {
    const html = await render(
      <FrontView front={front({ mine: list([card("st-m1")]) })} go={() => {}} now={NOW} />,
    );
    expect(html).toContain("Titular st-m1");
    expect(html).not.toContain("Sigue equipos y jugadores");
  });
  test("with nothing to show it says so, never an empty page", async () => {
    const html = await render(
      <FrontView
        front={front({
          lead_story: { missing_reason: "sin_datos" } as never,
          breaking: list([]),
          featured: list([]),
        })}
        go={() => {}}
      />,
    );
    expect(html).toContain("Todavía no hay historias en las últimas 48 horas");
  });
});

describe("the search", () => {
  function primed(search: StoriesSearchParams, s: Partial<StorySearch> = {}) {
    const qc = new QueryClient();
    const body: StorySearch = {
      query: search.q ?? "",
      normalized: search.q ?? "",
      sort: "reciente",
      filters_applied: [{ name: "category", value: "fichajes" }],
      facets: { category: [{ code: "fichajes", n: 3 }], level: [{ code: "rumor", n: 1 }] },
      results: list([
        {
          story_id: "st-1",
          headline_es: "Uno",
          level: "rumor",
          category: "fichajes",
          sources_count: 1,
          latest_at: "2026-11-23T10:00:00Z",
        },
      ]),
      total: 3,
      next_offset: 20,
      ...s,
    };
    qc.setQueryData(["v1", "stories", "search", search], {
      pages: [{ data: { view: "busqueda", search: body } }],
      pageParams: [0],
    });
    return qc;
  }
  test("facets with their counts, the applied filters, the total and a «ver más»", async () => {
    const search: StoriesSearchParams = { category: "fichajes" };
    const html = await render(<SearchView search={search} go={() => {}} />, primed(search));
    expect(html).toContain('data-testid="stories-applied"');
    expect(html).toContain("Quitar el filtro Tema");
    expect(html).toContain("3 historias");
    expect(html).toContain("Uno");
    expect(html).toContain('data-testid="stories-more"');
    expect(html).toMatch(/stories-category-fichajes[\s\S]*?>3</);
  });
  test("a search the server normalised says what it looked for", async () => {
    const search: StoriesSearchParams = { q: "atletico" };
    const html = await render(
      <SearchView search={search} go={() => {}} />,
      primed(search, { normalized: "atlético" }),
    );
    expect(html).toContain("Buscamos: atlético");
  });
  test("no results: it says so and offers to clear the filters", async () => {
    const search: StoriesSearchParams = { q: "zzz" };
    const html = await render(
      <SearchView search={search} go={() => {}} />,
      primed(search, { results: list([]), total: 0, filters_applied: [] }),
    );
    expect(html).toContain("No encontramos historias con estos filtros");
    expect(html).toContain("Quitar los filtros");
  });
  test("English", async () => {
    setLocale("en");
    const search: StoriesSearchParams = { category: "fichajes" };
    const html = await render(<SearchView search={search} go={() => {}} />, primed(search));
    expect(html).toContain("3 stories");
    expect(html).toContain("Only what I follow");
  });
});
