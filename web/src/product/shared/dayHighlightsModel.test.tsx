/// <reference types="bun" />
/**
 * AP-K04 «Lo más interesante de hoy»: the criterion (what is at stake, the reader's own matches first, never the price), the label
 * «Análisis del día · no es un pick» and what the block never carries (a unit, a price, a Mi parlay button, «recomendamos»).
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import type { ReactElement } from "react";
import { setLocale } from "@/lib/i18n";
import { setTimeZone } from "@/lib/time";
import type { HomeAtStake } from "@/lib/api/v1/types_product";
import type { TodayMatch } from "@/lib/api/v1/types_today";
import { chooseHighlights, HIGHLIGHTS_MAX } from "./dayHighlightsModel";
import { DayHighlightsView } from "./DayHighlights";

beforeEach(() => {
  setLocale("es");
  setTimeZone("America/Bogota");
});
afterEach(() => {
  setLocale("es");
  setTimeZone("UTC");
});

const NOW = Date.parse("2026-11-23T15:00:00Z");

function stake(id: number, over: Partial<HomeAtStake> = {}): HomeAtStake {
  return {
    fixture_id: id,
    kickoff_at: new Date(NOW + 3 * 3600_000).toISOString(),
    competition: { id: 1, name: "LaLiga", country: "España", logo_url: null, flag_url: null },
    home: { id: id * 10, name: `Local ${id}`, logo_url: null },
    away: { id: id * 10 + 1, name: `Visita ${id}`, logo_url: null },
    reason: { code: "final", params: {} },
    ...over,
  };
}

function today(id: number, over: Partial<TodayMatch> & Record<string, unknown> = {}): TodayMatch {
  return {
    fixture_id: id,
    forecast: { outcome: "home", probability: "0.55", calibrated: true },
    followed: null,
    suggested: false,
    ...over,
  } as unknown as TodayMatch;
}

describe("how the matches are chosen", () => {
  test("the server's order, the reader's own matches first, three at most", () => {
    const stakes = [stake(1), stake(2), stake(3), stake(4), stake(5)];
    const matches = [
      today(4, { followed: { kind: "team", names: ["Local 4"] } }),
      today(3, { followed: { kind: "league", names: ["LaLiga"] } }),
    ];
    const ids = chooseHighlights(stakes, matches).map((h) => h.stake.fixture_id);
    expect(ids).toEqual([3, 4, 1]);
    expect(ids.length).toBeLessThanOrEqual(HIGHLIGHTS_MAX);
  });

  test("the suggested matches (the reader chose nothing) are not «yours»", () => {
    const out = chooseHighlights(
      [stake(1), stake(2)],
      [today(2, { followed: { kind: "league", names: ["LaLiga"] }, suggested: true })],
    );
    expect(out.map((h) => h.stake.fixture_id)).toEqual([1, 2]);
    expect(out.every((h) => !h.followed)).toBe(true);
  });

  test("it never reads the price: whatever edge or value the data carries, the choice is the same", () => {
    const plain = [stake(1), stake(2), stake(3)];
    const priced = plain.map((s, i) => ({ ...s, edge: 0.9 - i, value: 5 - i, odds: 1.5 + i }));
    const matches = [today(3), today(2, { edge: 0.5, value: 9 })];
    expect(chooseHighlights(priced, matches).map((h) => h.stake.fixture_id)).toEqual(
      chooseHighlights(plain, [today(3), today(2)]).map((h) => h.stake.fixture_id),
    );
    expect(chooseHighlights(priced.reverse(), matches).map((h) => h.stake.fixture_id)).toEqual([
      3, 2, 1,
    ]);
  });

  test("the forecast comes from /today, and a match without one says so", () => {
    const [a, b] = chooseHighlights([stake(1), stake(2)], [today(1), today(2, { forecast: null })]);
    expect(a?.forecast?.outcome).toBe("home");
    expect(b?.forecast).toBeNull();
  });
});

async function view(el: ReactElement): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => el }),
    history: createMemoryHistory({ initialEntries: ["/picks"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

const text = (html: string) =>
  html
    .replace(/<p[^>]*data-testid="day-highlights-how"[^>]*>[\s\S]*?<\/p>/, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

describe("what it shows", () => {
  const stakes = [stake(1), stake(2)];
  const matches = [
    today(1),
    today(2, {
      forecast: { outcome: "draw", probability: "0.31", calibrated: false },
      followed: { kind: "team", names: ["Local 2"] },
    }),
  ];

  test("the label says it is not a pick, with the matches, what they play for and the forecast with its seal", async () => {
    const html = await view(
      <DayHighlightsView highlights={chooseHighlights(stakes, matches)} now={NOW} />,
    );
    const page = text(html);
    expect(page).toContain("Lo más interesante de hoy");
    expect(page).toContain("Análisis del día · no es un pick");
    expect(page).toContain("Local 1");
    expect(page).toContain("Es una final.");
    expect(page).toContain("55 % gana Local 1");
    expect(page).toContain("31 % empate");
    expect(page).toContain("Estimación preliminar");
    expect(page).toContain("Tuyo");
    expect((html.match(/data-testid="day-highlight"/g) ?? []).length).toBe(2);
  });

  test("no unit, no price, no Mi parlay and never «recomendamos»", async () => {
    const page = text(
      await view(<DayHighlightsView highlights={chooseHighlights(stakes, matches)} now={NOW} />),
    );
    expect(page).not.toMatch(/unidad|cuota|parlay|recomend|apuesta|stake/i);
  });

  test("nothing to read: nothing at all", async () => {
    expect(await view(<DayHighlightsView highlights={[]} />)).not.toContain("day-highlights");
  });

  test("in English", async () => {
    setLocale("en");
    const page = text(
      await view(<DayHighlightsView highlights={chooseHighlights(stakes, matches)} now={NOW} />),
    );
    expect(page).toContain("Analysis of the day · not a pick");
    expect(page).not.toMatch(/recommend(?!ation)|odds|parlay|stake/i);
  });
});
