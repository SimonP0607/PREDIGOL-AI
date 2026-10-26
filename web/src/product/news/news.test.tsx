/// <reference types="bun" />
/**
 * The news cards (plan UX, A10; section 27): every status with its label and its explanation in both languages (the status
 * reads without the colour); the headline from the kind and its protagonist - a contradiction by its topic, taking neither
 * side -; the time relative, a day-only date as the source's own day, or when PrediGol saw it; PrediGol's own summary, or a
 * sentence from the card's facts when it could not be sent - never empty -, labelled «(in Spanish)» on an English page; the
 * groups of the order; and each card's seven elements, the link in a new tab without the opener, the exact sentence when
 * there is no coverage and the owner's switch said, never hidden.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { setTimeZone } from "@/lib/time";
import esMatch from "@/locales/es/match.json";
import enMatch from "@/locales/en/match.json";
import type { Envelope } from "@/lib/api/v1/types";
import type {
  MatchNews,
  NewsItem,
  NewsStatus,
  TodayNews,
  TodayNewsItem,
} from "@/lib/api/v1/types_news";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from "@tanstack/react-router";
import { NewsBlock, type TodayNewsQuery } from "@/product/home/NewsBlock";
import type { FollowReason } from "@/lib/api/v1/types_today";
import {
  groups,
  headline,
  homeNews,
  pressAbsences,
  shownInSpanish,
  summaryLang,
  statusHelp,
  statusLabel,
  summary,
  todayOnly,
  whenText,
} from "./news";
import { NewsView } from "./NewsTab";

const NOW = Date.parse("2026-10-25T18:00:00Z");
const STATUSES: NewsStatus[] = ["CONFIRMED", "PROBABLE", "CONTRADICTORY", "RUMOR", "OUTDATED"];

beforeEach(() => {
  setLocale("es");
  setTimeZone("America/Bogota");
});
afterEach(() => {
  setLocale("es");
  setTimeZone("UTC");
});

let next = 1;
function item(over: Partial<NewsItem> = {}): NewsItem {
  return {
    id: `n${next++}`,
    kind: "injury",
    status: "PROBABLE",
    relevance: "high",
    team: { id: 1, name: "Tenerife", side: "home" },
    player: "Baba Diocou",
    claims: [
      {
        text: "Según Sport, Baba Diocou es baja por lesión para este partido.",
        lang: "es",
        assertion: "out",
        sources: [
          {
            name: "sport.es",
            tier: "media",
            url: "https://www.sport.es/es/noticias/1",
            published_at: "2026-10-25T15:00:00Z",
            published_day_only: false,
          },
        ],
      },
    ],
    published_at: "2026-10-25T15:00:00Z",
    published_day_only: false,
    seen_at: "2026-10-25T16:00:00Z",
    ...over,
  };
}

function text(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/[\u00a0\u202f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function ok(items: NewsItem[]): Envelope<MatchNews | null> {
  return {
    status: items.length ? "ok" : "empty",
    data: {
      fixture_id: 7,
      items,
      counts: { CONFIRMED: 0, PROBABLE: 0, CONTRADICTORY: 0, RUMOR: 0, OUTDATED: 0 },
    },
    reason: items.length ? null : "No verified news relevant to this match.",
    meta: {},
  } as unknown as Envelope<MatchNews | null>;
}

describe("the status, in words", () => {
  test("every status has its label and its explanation, in Spanish and in English", () => {
    const es = STATUSES.map((s) => [statusLabel(s), statusHelp(s)]);
    expect(es.map(([label]) => label)).toEqual([
      "Confirmado",
      "Probable",
      "Contradictorio",
      "Rumor",
      "Desactualizado",
    ]);
    setLocale("en");
    const en = STATUSES.map((s) => [statusLabel(s), statusHelp(s)]);
    expect(en.map(([label]) => label)).toEqual([
      "Confirmed",
      "Probable",
      "Contradictory",
      "Rumour",
      "Outdated",
    ]);
    for (const [label, help] of [...es, ...en]) {
      expect(label?.length).toBeGreaterThan(3);
      expect(help?.length).toBeGreaterThan(30);
      expect(help).not.toContain("match.news");
    }
    expect(statusHelp("RUMOR")).toContain("not take it as a fact");
  });

  test("a card shows its status as text, with the explanation for a tap and for a screen reader", () => {
    const html = renderToStaticMarkup(
      <NewsView
        load={{ status: "success", envelope: ok([item({ status: "RUMOR" })]) }}
        now={NOW}
      />,
    );
    expect(html).toContain('data-status="RUMOR"');
    expect(text(html)).toContain("Rumor");
    expect(html).toContain(`data-hint="${statusHelp("RUMOR")}"`);
    expect(html).toContain('class="sr-only"');
  });
});

describe("the headline, the time and the summary", () => {
  test("the kind and its protagonist; a contradiction by its topic; the team alone; nobody", () => {
    expect(headline(item())).toBe("Baja por lesión · Baba Diocou (Tenerife)");
    const both = item({
      status: "CONTRADICTORY",
      kind: "suspension",
      claims: [
        { ...item().claims[0]!, assertion: "available" },
        { ...item().claims[0]!, assertion: "out" },
      ],
    });
    expect(headline(both)).toBe("Sanción · Baba Diocou (Tenerife)");
    expect(headline(item({ player: null }))).toBe("Baja por lesión · Tenerife");
    expect(headline(item({ player: null, team: null, kind: "news" }))).toBe("Noticia");
    setLocale("en");
    expect(headline(item())).toBe("Out injured · Baba Diocou (Tenerife)");
  });

  test("relative; a day-only date is the source's own day, never the evening before in America; or when PrediGol saw it", () => {
    expect(whenText(item(), NOW)).toBe("Publicada hace 3 h");
    const dayOnly = { published_at: "2026-10-24T00:00:00Z", published_day_only: true };
    const day = whenText(dayOnly, NOW);
    expect(day).toStartWith("Publicada el ");
    expect(day).toContain("24 oct");
    expect(day).not.toContain("23");
    expect(
      whenText(
        { published_at: null, published_day_only: false, seen_at: "2026-10-25T16:00:00Z" },
        NOW,
      ),
    ).toBe("Vista por PrediGol hace 2 h");
  });

  test("PrediGol's own summary; when it could not be sent, a sentence from the card's facts - never empty", () => {
    const own = item();
    expect(summary(own, own.claims[0]!)).toBe(
      "Según Sport, Baba Diocou es baja por lesión para este partido.",
    );
    const unsent = { ...own.claims[0]!, text: null };
    expect(summary(own, unsent)).toBe("Baba Diocou (Tenerife) no jugará, según sport.es.");
    expect(summary({ player: null, team: own.team }, unsent)).toBe(
      "Tenerife tendrá bajas, según sport.es.",
    );
    expect(summary({ player: null, team: null }, { ...unsent, sources: [] })).toBe(
      "el equipo tendrá bajas, según una fuente.",
    );
    setLocale("en");
    expect(summary(own, { ...unsent, assertion: "doubtful" })).toBe(
      "Baba Diocou (Tenerife) is doubtful, according to sport.es.",
    );
  });

  test("the card's own headline and the English summary (A11) in their language, the words of A10 otherwise", () => {
    const own = item({
      headline_es: "Baba Diocou, baja por lesión",
      headline_en: "Baba Diocou out injured",
    });
    const translated = {
      ...own.claims[0]!,
      text_en: "According to Sport, Baba Diocou is out injured.",
    };
    expect(headline(own)).toBe("Baba Diocou, baja por lesión");
    expect(summary(own, translated)).toBe(own.claims[0]!.text!);
    expect(summaryLang(translated)).toBe("es");
    setLocale("en");
    expect(headline(own)).toBe("Baba Diocou out injured");
    expect(headline(item({ headline_es: "Solo en español" }))).toBe(
      "Out injured · Baba Diocou (Tenerife)",
    );
    expect(summary(own, translated)).toBe("According to Sport, Baba Diocou is out injured.");
    expect(shownInSpanish(translated)).toBe(false);
    expect(summaryLang(translated)).toBeUndefined();
    const html = renderToStaticMarkup(
      <NewsView
        load={{
          status: "success",
          envelope: ok([{ ...own, claims: [translated] }]),
        }}
        now={NOW}
      />,
    );
    expect(text(html)).toContain("According to Sport, Baba Diocou is out injured.");
    expect(text(html)).toContain("Baba Diocou out injured");
    expect(text(html)).not.toContain("(in Spanish)");
  });

  test("the Spanish summary is labelled on an English page, and only there", () => {
    const claim = item().claims[0]!;
    expect(shownInSpanish(claim)).toBe(false);
    setLocale("en");
    expect(shownInSpanish(claim)).toBe(true);
    expect(shownInSpanish({ ...claim, text: null })).toBe(false);
    const html = renderToStaticMarkup(
      <NewsView load={{ status: "success", envelope: ok([item()]) }} now={NOW} />,
    );
    expect(text(html)).toContain("(in Spanish)");
    expect(html).toContain('lang="es"');
  });
});

describe("the order and where else they show", () => {
  test("the API's order cut into named groups: rumours and the outdated last", () => {
    const list = [
      item({ status: "CONFIRMED" }),
      item({ status: "PROBABLE" }),
      item({ status: "CONTRADICTORY" }),
      item({ status: "RUMOR" }),
      item({ status: "OUTDATED" }),
    ];
    expect(groups(list).map((g) => [g.group, g.items.length])).toEqual([
      ["verified", 2],
      ["contradictory", 1],
      ["rumor", 1],
      ["outdated", 1],
    ]);
  });

  test("Alineaciones gets the press's absences and doubts - never a rumour, an outdated item or a return", () => {
    const list = [
      item({ status: "CONFIRMED" }),
      item({ status: "RUMOR" }),
      item({ status: "OUTDATED" }),
      item({ kind: "doubtful", claims: [{ ...item().claims[0]!, assertion: "doubtful" }] }),
      item({ claims: [{ ...item().claims[0]!, assertion: "available" }] }),
      item({ kind: "lineup", claims: [{ ...item().claims[0]!, assertion: "starts" }] }),
    ];
    expect(pressAbsences(list).map((i) => [i.status, i.kind])).toEqual([
      ["CONFIRMED", "injury"],
      ["PROBABLE", "doubtful"],
    ]);
  });

  test("Inicio: today's matches in the reader's zone or in play, confirmed first, four at most", () => {
    const at = (kickoff: string, status: NewsStatus, group = "scheduled"): TodayNewsItem => ({
      match: {
        fixture_id: next++,
        kickoff_at: kickoff,
        status_group: group,
        home: "Nacional",
        away: "Millonarios",
        competition: "Liga BetPlay",
      },
      item: item({ status }),
    });
    const tonight = "2026-10-26T01:00:00Z"; // 20:00 in Bogotá, still the 25th
    const tomorrow = "2026-10-26T18:00:00Z";
    const list = [
      at(tonight, "PROBABLE"),
      at(tomorrow, "CONFIRMED"),
      at("2026-10-25T17:00:00Z", "PROBABLE", "live"),
      at(tonight, "CONFIRMED"),
      at(tonight, "PROBABLE"),
      at(tonight, "PROBABLE"),
    ];
    const shown = homeNews(list, "America/Bogota", NOW);
    expect(shown).toHaveLength(4);
    expect(shown[0]!.item.status).toBe("CONFIRMED");
    expect(shown.every((i) => i.match.kickoff_at !== tomorrow)).toBe(true);
    expect(todayOnly(list, "UTC", NOW).some((i) => i.match.kickoff_at === tonight)).toBe(false);
  });
});

describe("what the section says", () => {
  test("each card has its seven elements, and the link opens the source in a new tab without the opener", () => {
    const html = renderToStaticMarkup(
      <NewsView
        load={{ status: "success", envelope: ok([item({ status: "CONFIRMED" })]) }}
        now={NOW}
      />,
    );
    const page = text(html);
    expect(page).toContain("Baja por lesión · Baba Diocou (Tenerife)"); // headline
    expect(page).toContain("Fuente: sport.es · medio de comunicación"); // source and standing
    expect(page).toContain("Publicada hace 3 h"); // time
    expect(page).toContain("Según Sport, Baba Diocou es baja por lesión para este partido."); // own summary
    expect(page).toContain("Relevancia alta"); // relevance
    expect(page).toContain("Confirmado"); // status
    expect(page).toContain("Leer en la fuente"); // link
    expect(html).toContain('href="https://www.sport.es/es/noticias/1"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  test("a contradiction shows each claim with its own source", () => {
    const both = item({
      status: "CONTRADICTORY",
      kind: "suspension",
      claims: [
        {
          text: "Según As, Baba Diocou ya cumplió su sanción y está disponible para este partido.",
          lang: "es",
          assertion: "available",
          sources: [
            {
              name: "as.com",
              tier: "media",
              url: "https://as.com/2",
              published_at: null,
              published_day_only: false,
            },
          ],
        },
        {
          text: "Según Marca, Baba Diocou cumple sanción y no jugará este partido.",
          lang: "es",
          assertion: "out",
          sources: [
            {
              name: "marca.com",
              tier: "media",
              url: "https://www.marca.com/2",
              published_at: null,
              published_day_only: false,
            },
          ],
        },
      ],
    });
    const html = renderToStaticMarkup(
      <NewsView load={{ status: "success", envelope: ok([both]) }} now={NOW} />,
    );
    expect((html.match(/data-testid="news-claim"/g) ?? []).length).toBe(2);
    const page = text(html);
    expect(page).toContain("Disponible tras su sanción");
    expect(page).toContain("Baja por sanción");
    expect(page).toContain("Fuente: as.com · medio de comunicación");
    expect(page).toContain("Fuente: marca.com · medio de comunicación");
    expect(page).toContain("Se contradicen");
  });

  test("the rumours and the outdated fold away under verified news, and stay open when they are all there is", () => {
    const mixed = renderToStaticMarkup(
      <NewsView
        load={{
          status: "success",
          envelope: ok([
            item({ status: "PROBABLE" }),
            item({ status: "RUMOR" }),
            item({ status: "OUTDATED" }),
          ]),
        }}
        now={NOW}
      />,
    );
    expect(mixed).toMatch(/<details[^>]*data-testid="news-group-rumor"/);
    expect(mixed).toMatch(/<details[^>]*data-testid="news-group-outdated"/);
    expect(mixed).not.toMatch(/<details[^>]*open/);
    expect(mixed).toMatch(/<section[^>]*data-testid="news-group-verified"/);
    const rumours = renderToStaticMarkup(
      <NewsView
        load={{ status: "success", envelope: ok([item({ status: "RUMOR" })]) }}
        now={NOW}
      />,
    );
    expect(rumours).not.toContain("<details");
    expect(rumours).toMatch(/<section[^>]*data-testid="news-group-rumor"/);
  });

  test("no coverage: the plan's sentence, word for word; the owner's switch: said; a failure: its retry", () => {
    expect(
      text(renderToStaticMarkup(<NewsView load={{ status: "success", envelope: ok([]) }} />)),
    ).toContain("No encontramos noticias verificadas relevantes para este partido.");
    const off = {
      status: "not_available",
      data: null,
      reason: "off",
      meta: {},
    } as unknown as Envelope<MatchNews | null>;
    expect(
      text(renderToStaticMarkup(<NewsView load={{ status: "success", envelope: off }} />)),
    ).toContain("Las noticias no están disponibles en este momento.");
    const failed = text(
      renderToStaticMarkup(
        <NewsView load={{ status: "error", error: new Error("x"), retry: () => {} }} />,
      ),
    );
    expect(failed).toContain("Reintentar");
    expect(failed).not.toContain("No encontramos noticias");
  });

  test("no word of certainty or of betting in what the news say", () => {
    const VETOED_ES = /\b(valor|seguro|segura|fijo|fija|garantizad[oa]s?|apuesta|apostar)\b/i;
    const VETOED_EN = /\b(value|sure|guaranteed|lock|bet|betting)\b/i;
    const strings = (node: unknown): string[] =>
      typeof node === "string"
        ? [node]
        : node && typeof node === "object"
          ? Object.values(node).flatMap(strings)
          : [];
    for (const s of strings(esMatch.news)) expect(s).not.toMatch(VETOED_ES);
    for (const s of strings(enMatch.news)) expect(s).not.toMatch(VETOED_EN);
  });
});

describe("Home's news are the reader's (plan UX, B2)", () => {
  async function page(news: TodayNews): Promise<string> {
    const query = {
      data: { status: "ok", data: news, reason: null, meta: {} },
      dataUpdatedAt: NOW,
    } as unknown as TodayNewsQuery;
    const router = createRouter({
      routeTree: createRootRoute({ component: () => <NewsBlock query={query} now={NOW} /> }),
      history: createMemoryHistory({ initialEntries: ["/"] }),
    });
    await router.load();
    return renderToStaticMarkup(<RouterProvider router={router} />);
  }
  const tonight = "2026-10-26T01:00:00Z";
  const entry = (fixture: number, followed: FollowReason | null): TodayNewsItem => ({
    match: {
      fixture_id: fixture,
      kickoff_at: tonight,
      status_group: "scheduled",
      home: "Nacional",
      away: "Millonarios",
      competition: "Liga BetPlay",
      followed,
    },
    item: item({ status: "CONFIRMED" }),
  });

  test("their leagues and teams: their own subtitle and, on each, why its match is theirs", async () => {
    setLocale("es");
    const markup = await page({
      items: [
        entry(1, { kind: "team", names: ["Atlético Nacional"] }),
        entry(2, { kind: "league", names: ["Liga BetPlay"] }),
      ],
      suggested: false,
    });
    const shown = text(markup);
    expect(shown).toContain("de los partidos de tus ligas y equipos");
    expect(shown).toContain("Sigues a Atlético Nacional");
    expect(shown).toContain("Tu liga");
    expect(markup.match(/data-testid="home-news-why"/g)).toHaveLength(2);
  });

  test("the suggested ones (or an API from before B2): said once in the subtitle, no chip on each", async () => {
    setLocale("es");
    for (const news of [
      { items: [entry(3, { kind: "league" as const, names: ["Liga BetPlay"] })], suggested: true },
      { items: [entry(4, null)] },
    ]) {
      const markup = await page(news);
      expect(text(markup)).toContain("de los partidos de hoy de las ligas sugeridas");
      expect(markup).not.toContain('data-testid="home-news-why"');
    }
  });
});
