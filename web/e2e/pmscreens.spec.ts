/**
 * The screens of the láminas I01 to I12 (plan PM, PM-14-11 and PM-15-02; CI-022), as a reader gets them once their switches are on:
 * at 390 px in Chromium (project "pm-screens") and in WebKit, the engine of every iPhone browser ("pm-screens-webkit"). Runs only
 * when asked (E2E_PM_SCREENS=1) against a stack whose API has the plan's switches on - a QA or local stack, never production while
 * they are off there (PM-15-03 turns them on). Which match, team, player and competition to open is given, not guessed:
 *   E2E_PM_IDS='{"match_a":1884,"match_b":1904,"match_c":1994,"match_d":2084,"match_next":2174,"team":41,"player":650,
 *                "keeper":641,"competition":3}'
 * (a finished match of a competition at each level of C-16, a match to come with PrediGol's forecast, a club, a player, a keeper
 * and a competition with its reglamento coded). Each screen must load with no console error and no failed API call, fit the
 * width (no horizontal scroll), and draw the piece of its lámina; a full-page picture goes to the test's output folder
 * (<project>/<lámina>.png) - the reference a later run is compared with, by eye or pixel by pixel on the same data.
 */
import { expect, test, type Page } from "@playwright/test";
import { settle, watch } from "./support";

type Ids = Record<
  | "match_a"
  | "match_b"
  | "match_c"
  | "match_d"
  | "match_next"
  | "team"
  | "player"
  | "keeper"
  | "competition",
  number
>;

function ids(): Ids | null {
  const raw = process.env["E2E_PM_IDS"];
  if (!raw) return null;
  return JSON.parse(raw) as Ids;
}

interface Screen {
  lamina: string;
  path: (i: Ids) => string;
  /** A tab or button to press before the picture (the lámina shows that state). */
  press?: string;
  /** What must be on the page: the piece of the lámina. */
  shows?: (page: Page) => Promise<void>;
}

const SCREENS: Screen[] = [
  {
    lamina: "I01-estadisticas",
    path: (i) => `/matches/${i.match_a}#stats`,
    shows: async (p) => {
      await expect(p.getByTestId("match-viz")).toBeVisible();
      await expect(p.getByTestId("coverage-stats")).toHaveCount(0);
    },
  },
  { lamina: "I02-alineaciones-capas", path: (i) => `/matches/${i.match_a}#lineups` },
  { lamina: "I03-contexto", path: (i) => `/matches/${i.match_next}#summary` },
  { lamina: "I04-cobertura-B", path: (i) => `/matches/${i.match_b}#stats` },
  {
    lamina: "I04-cobertura-C",
    path: (i) => `/matches/${i.match_c}#stats`,
    shows: async (p) => {
      await expect(p.getByTestId("coverage-stats")).toBeVisible();
    },
  },
  {
    lamina: "I04-cobertura-D",
    path: (i) => `/matches/${i.match_d}#stats`,
    shows: async (p) => {
      await expect(p.getByTestId("coverage-stats")).toBeVisible();
      await expect(p.getByTestId("unavailable-notes")).toHaveCount(1);
    },
  },
  { lamina: "I05-equipo", path: (i) => `/teams/${i.team}` },
  { lamina: "I06-jugador-campo", path: (i) => `/players/${i.player}` },
  { lamina: "I06-jugador-portero", path: (i) => `/players/${i.keeper}` },
  {
    lamina: "I07-competicion",
    path: (i) => `/competitions/${i.competition}`,
    shows: async (p) => {
      await expect(p.getByTestId("season-tables")).toBeVisible();
    },
  },
  { lamina: "I08-directorio", path: () => "/competitions" },
  {
    lamina: "I09-probabilidad-iconos",
    path: (i) => `/matches/${i.match_next}#summary`,
    press: "Iconos",
  },
  { lamina: "I10-cronica", path: (i) => `/matches/${i.match_a}#summary` },
  { lamina: "I12-estados-sin-dato", path: (i) => `/matches/${i.match_d}#summary` },
];

test.describe("the láminas I01 to I12 on a phone", () => {
  const given = ids();
  test.skip(
    !given,
    "E2E_PM_IDS not given: the screens need their match, team, player and competition",
  );

  for (const s of SCREENS) {
    test(`${s.lamina} at 390 px`, async ({ page }, info) => {
      const w = watch(page);
      await page.goto(s.path(given!));
      await settle(page);
      if (s.press) {
        await page.getByRole("button", { name: s.press, exact: true }).first().click();
        await settle(page);
      }
      if (s.shows) await s.shows(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${s.lamina} scrolls horizontally by ${overflow}px`).toBeLessThanOrEqual(1);
      expect(w.problems, `console errors or failed API calls on ${s.lamina}`).toEqual([]);
      await page.screenshot({ path: info.outputPath(`${s.lamina}.png`), fullPage: true });
    });
  }
});
