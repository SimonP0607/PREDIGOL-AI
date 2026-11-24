/// <reference types="bun" />
/**
 * The news as stories (plan de correcciones UX, AP-N02; maqueta 09): the level in words and with a symbol in both languages, the
 * monogram instead of a picture, only plain web addresses made links, the sources by name and time, the story withdrawn at a
 * request shown as such, and never an article's text.
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
import { setTimeZone } from "@/lib/time";
import type { StoryCard, StoryDetail, StoryLevel } from "@/lib/api/v1/types_stories";
import { LevelChip, Monogram, WarningChips } from "./StoryBits";
import { StoryBody, StoryResult } from "./StoryPage";
import {
  CATEGORY_ORDER,
  categoryWord,
  headlineOf,
  initials,
  levelHelp,
  levelWord,
  monogramOf,
  safeUrl,
  sourceNames,
  sourceWhen,
  sourcesCount,
  summaryOf,
  textLang,
} from "./stories";

const NOW = Date.parse("2026-11-23T18:00:00Z");
const LEVELS: StoryLevel[] = ["oficial", "dos_origenes", "declaracion", "un_medio", "rumor"];

function card(over: Partial<StoryCard> = {}): StoryCard {
  return {
    id: "st-1",
    headline_es: "Nacional ficha a un delantero",
    summary_es: "El club confirmó la llegada.",
    category: "fichajes",
    level: "oficial",
    warnings: [],
    sources_count: 2,
    latest_at: "2026-11-23T16:00:00Z",
    sources: [
      {
        name: "Club",
        author: { missing_reason: "pendiente_derechos" } as never,
        published_at: "2026-11-23T15:00:00Z",
        published_day_only: false,
        known_at: "2026-11-23T15:10:00Z",
        url: "https://club.example/nota",
      },
      {
        name: "Diario",
        author: { missing_reason: "pendiente_derechos" } as never,
        published_at: null as never,
        published_day_only: false,
        known_at: "2026-11-23T15:30:00Z",
        url: "javascript:alert(1)",
      },
    ],
    entities: [
      {
        type: "team",
        id: 7,
        name: "Atlético Nacional",
        role: "protagonista",
        method: "plantilla",
        confidence: 1,
      },
    ],
    image: { kind: "monograma" },
    ...over,
  };
}

function detail(over: Partial<StoryDetail> = {}): StoryDetail {
  return {
    ...card(),
    essentials_es: "Nacional anunció al delantero.",
    level_explanation_es: "Lo comunicó el club.",
    match_impact: { missing_reason: "no_aplica" } as never,
    timeline: [
      { known_at: "2026-11-23T15:30:00Z", level: "un_medio", source: "Diario" },
      { known_at: "2026-11-23T15:10:00Z", level: "oficial", source: "Club" },
    ],
    related: {
      items: [{ id: "st-2", headline_es: "Otra historia", level: "rumor" }],
      count: 1,
    } as never,
    rights_notice_es: "Resumen de PrediGol.",
    ...over,
  };
}

async function render(node: React.ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => <>{node}</> }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

afterEach(() => {
  setLocale("es");
  setTimeZone("America/Bogota");
});

describe("level of confirmation", () => {
  test("every level has a word and an explanation in Spanish and English, and they differ", async () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      const words = new Set<string>();
      for (const l of [...LEVELS, null]) {
        expect(levelWord(l).length).toBeGreaterThan(0);
        expect(levelHelp(l).length).toBeGreaterThan(10);
        words.add(levelWord(l));
      }
      expect(words.size).toBe(LEVELS.length + 1);
    }
  });

  test("the chip says it in words, with its meaning, and is never only a colour", async () => {
    for (const l of LEVELS) {
      const html = await render(<LevelChip level={l} />);
      expect(html).toContain(levelWord(l));
      expect(html).toContain(levelHelp(l));
      expect(html).toContain("<svg");
      expect(html).toContain(`data-level="${l}"`);
    }
    expect(await render(<LevelChip level={null} />)).toContain("Sin nivel todavía");
  });

  test("the contradiction is a notice with its own words", async () => {
    const html = await render(<WarningChips warnings={["contradiccion", "desactualizada"]} />);
    expect(html).toContain("Las fuentes se contradicen");
    expect(html).toContain("Puede estar desactualizada");
    expect(await render(<WarningChips warnings={[]} />)).toBe("");
  });
});

describe("the monogram", () => {
  test("initials skip the particles and accents", async () => {
    expect(initials("Atlético Nacional")).toBe("AN");
    expect(initials("Junior")).toBe("JU");
    expect(initials("CD Los Millonarios")).toBe("MI");
    expect(initials("")).toBe("");
  });
  test("a story that names nobody is «PG»", async () => {
    expect(monogramOf({ entities: [] })).toBe("PG");
    expect(monogramOf(card())).toBe("AN");
    expect(await render(<Monogram card={card()} />)).toContain("AN");
  });
  test("the protagonist wins over a mention", async () => {
    const c = card({
      entities: [
        {
          type: "player",
          id: 1,
          name: "Pedro Gómez",
          role: "mencionado",
          method: "alias",
          confidence: 0.8,
        },
        {
          type: "team",
          id: 2,
          name: "Junior",
          role: "protagonista",
          method: "plantilla",
          confidence: 1,
        },
      ],
    });
    expect(monogramOf(c)).toBe("JU");
  });
});

describe("words and links", () => {
  test("only plain web addresses become links", async () => {
    expect(safeUrl("https://club.example/nota")).toBe("https://club.example/nota");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("data:text/html,x")).toBeNull();
    expect(safeUrl("no es una url")).toBeNull();
  });
  test("headline and summary: PrediGol's own, or null, never a source's", async () => {
    expect(headlineOf({ headline_es: "  Hola  " })).toBe("Hola");
    expect(
      headlineOf({ headline_es: { missing_reason: "pendiente_derechos" } as never }),
    ).toBeNull();
    expect(summaryOf({ summary_es: "" })).toBeNull();
  });
  test("sources: each outlet once, counted with its plural", async () => {
    expect(sourceNames({ sources: [...card().sources, ...card().sources] })).toEqual([
      "Club",
      "Diario",
    ]);
    expect(sourcesCount(1)).toBe("1 fuente");
    expect(sourcesCount(3)).toBe("3 fuentes");
  });
  test("when a source published, or when PrediGol saw it", async () => {
    const [a, b] = card().sources;
    expect(sourceWhen(a!, NOW)).toContain("Publicada");
    expect(sourceWhen(b!, NOW)).toContain("Vista por PrediGol");
  });
  test("categories are listed once each and named", async () => {
    expect(new Set(CATEGORY_ORDER).size).toBe(8);
    expect(categoryWord("colombia")).toBe("Fútbol colombiano");
  });
  test("an English page says the text is in Spanish", async () => {
    setLocale("en");
    expect(textLang()).toBe("es");
    setLocale("es");
    expect(textLang()).toBeUndefined();
  });
});

describe("the story page", () => {
  test("shows essentials, level, who, timeline oldest first, sources and related", async () => {
    const html = await render(<StoryBody story={detail()} />);
    expect(html).toContain("Nacional ficha a un delantero");
    expect(html).toContain("Lo esencial");
    expect(html).toContain('data-testid="story-level-section"');
    expect(html).toContain("Atlético Nacional");
    expect(html.indexOf("Club")).toBeGreaterThan(-1);
    const tl = html.slice(html.indexOf('data-testid="story-timeline"'));
    expect(tl.indexOf("Club")).toBeLessThan(tl.indexOf("Diario"));
    expect(html).toContain("Otra historia");
    expect(html).toContain("Resumen elaborado por PrediGol");
  });
  test("the source link opens in a new tab without the opener; an unsafe address is no link", async () => {
    const html = await render(<StoryBody story={detail()} />);
    expect(html.match(/Leer en la fuente/g)?.length).toBe(2); // one label + one aria-label of the safe link
    expect(html).toContain('href="https://club.example/nota"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).not.toContain("javascript:");
  });
  test("a story without a summary says so and shows no source title", async () => {
    const html = await render(
      <StoryBody
        story={detail({
          headline_es: null as never,
          summary_es: null as never,
          essentials_es: null as never,
        })}
      />,
    );
    expect(html).toContain("Historia sin titular todavía");
    expect(html).toContain("todavía");
  });
  test("a match impact links to the match only when its analysis is published", async () => {
    const impact = {
      fixture_id: 9,
      kickoff_at: "2026-11-24T20:00:00Z",
      aspect_es: "Refuerza el ataque",
      analysis_published: true,
    };
    expect(await render(<StoryBody story={detail({ match_impact: impact })} />)).toContain(
      "Ver el partido",
    );
    expect(
      await render(
        <StoryBody story={detail({ match_impact: { ...impact, analysis_published: false } })} />,
      ),
    ).toContain("todavía no se publica");
  });
  test("a story withdrawn at a request or in moderation shows nothing of itself", async () => {
    const w = await render(<StoryResult data={{ missing_reason: "retirado_por_derechos" }} />);
    expect(w).toContain("se retiró a petición");
    expect(w).not.toContain("Nacional");
    expect(await render(<StoryResult data={{ missing_reason: "pendiente_derechos" }} />)).toContain(
      "en revisión",
    );
    expect(await render(<StoryResult data={null} />)).toContain("No encontramos");
  });
  test("English page: text flagged as Spanish", async () => {
    setLocale("en");
    const html = await render(<StoryBody story={detail()} />);
    expect(html).toContain('lang="es"');
    expect(html).toContain("(in Spanish)");
  });
});
