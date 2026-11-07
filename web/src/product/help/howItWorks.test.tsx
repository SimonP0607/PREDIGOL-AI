/// <reference types="bun" />
/**
 * «Cómo funciona PrediGol» (plan de cierre UX, 1.6), without a browser: the eleven cards of the plan, each with its four
 * texts in Spanish and English; every card leads to a page that exists and to a glossary term that exists; the markets and
 * the states of a pick are the glossary's own definitions; the tour has five steps (the parlay joined it) and its last card
 * leads here; and the page says that its examples are invented.
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
import { setLocale, translate } from "@/lib/i18n";
import { isTerm, termName, termShort } from "@/lib/glossary";
import { HowItWorksPage } from "./HowItWorksPage";
import { HOW_CARDS, HOW_CARD_IDS, HOW_PATH, cardAnchor } from "./howItWorks";

afterAll(() => setLocale("es"));

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: [HOW_PATH] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

const PAGES = [
  /^\/home$/,
  /^\/matches$/,
  /^\/picks$/,
  /^\/parlays$/,
  /^\/odds$/,
  /^\/my-picks$/,
  /^\/profile$/,
];

describe("the cards", () => {
  test("the eleven of the plan, in its order, none repeated", () => {
    expect([...HOW_CARD_IDS]).toEqual([
      "home",
      "matches",
      "picks",
      "parlays",
      "odds",
      "myPicks",
      "favorites",
      "analysis",
      "probabilities",
      "markets",
      "states",
    ]);
    expect(HOW_CARDS.map((c) => c.id)).toEqual([...HOW_CARD_IDS]);
    expect(new Set(HOW_CARDS.map((c) => cardAnchor(c.id))).size).toBe(11);
  });

  test("each card has its title and its three texts in both languages, none empty", () => {
    const gaps: string[] = [];
    for (const locale of ["es", "en"] as const) {
      for (const card of HOW_CARDS) {
        for (const part of ["title", "what", "read", "example"]) {
          const id = `support.howItWorks.cards.${card.id}.${part}`;
          const text = translate(id, undefined, locale);
          if (text === id || text.trim() === "") gaps.push(`${locale} ${id}`);
        }
      }
    }
    expect(gaps).toEqual([]);
  });

  test("each card leads to a page of the app and to a term of the glossary that exists", () => {
    for (const card of HOW_CARDS) {
      expect([card.id, PAGES.some((p) => p.test(card.to))]).toEqual([card.id, true]);
      expect([card.id, isTerm(card.term)]).toEqual([card.id, true]);
      for (const shown of card.shows ?? []) expect([shown, isTerm(shown)]).toEqual([shown, true]);
    }
  });

  test("the markets of the plan and the states of a pick are shown with the glossary's definitions", () => {
    const markets = HOW_CARDS.find((c) => c.id === "markets")?.shows ?? [];
    expect(markets.map((k) => termName(k))).toEqual([
      "Resultado final (1X2)",
      "Más/Menos goles",
      "Ambos marcan",
      "Hándicap asiático",
      "Doble oportunidad",
    ]);
    const states = HOW_CARDS.find((c) => c.id === "states")?.shows ?? [];
    expect(states.map((k) => termName(k))).toEqual([
      "Recomendado",
      "Pendiente",
      "En juego",
      "Ganado",
      "Perdido",
      "Devuelto",
      "Medio ganado",
      "Medio perdido",
      "Anulado",
    ]);
    for (const k of [...markets, ...states]) expect(termShort(k).length).toBeGreaterThan(10);
  });
});

describe("the page", () => {
  test("it shows every card with its anchor, its link to the app and the note that the examples are invented", async () => {
    const page = await html(<HowItWorksPage />);
    for (const card of HOW_CARDS) {
      expect(page).toContain(`id="${cardAnchor(card.id)}"`);
      expect(page).toContain(`href="#${cardAnchor(card.id)}"`);
    }
    expect((page.match(/data-testid="how-card"/g) ?? []).length).toBe(11);
    expect((page.match(/data-testid="how-go"/g) ?? []).length).toBe(11);
    expect(page).toContain("Verlo en la app");
    expect(page).toContain("están inventados para explicar");
    expect(page).toContain("No es una casa de apuestas");
  });

  test("in English too", async () => {
    setLocale("en");
    const page = await html(<HowItWorksPage />);
    setLocale("es");
    expect(page).toContain("How PrediGol works");
    expect(page).toContain("See it in the app");
    expect(page).toContain("made up to explain");
  });

  test("a reader is never promised a result", async () => {
    const page = await html(<HowItWorksPage />);
    expect(page).toContain("ningún pronóstico garantiza un resultado");
    expect(page).not.toMatch(/ganancia segura|sin riesgo|siempre gana/i);
  });
});

describe("the welcome tour's words", () => {
  test("its entry points say five steps", () => {
    expect(translate("onboarding.welcome.about.tour")).toContain("5 pasos");
    expect(translate("support.help.more.tour")).toContain("5 pasos");
    expect(translate("guides.general.welcome.start")).toContain("5 pasos");
  });
});
