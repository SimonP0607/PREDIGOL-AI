/**
 * The guides (plan UX-050 to UX-054; plan «Bienvenida y recorrido», section 12), in the browser against the API, on
 * accounts the test makes and deletes at the end:
 *
 * * the welcome tour's four buttons (Empezar, Siguiente, Atrás, Finalizar), and that it does not come back - not on a
 *   reload and not in another browser of the same account;
 * * «Saltar» on the welcome card leaves Inicio's own guide (the one the tour covers) skipped too: the reader who said no
 *   once is not asked again on the next visit (UX-073);
 * * two skips in a row stop the automatic guides of that session; the «?» still brings any back;
 * * every guide, step by step, at the sizes of the plan (320x568, 390x844, 768x1024, 1024x768, 1440x900, 844x390, and
 *   the iPhone 13 in WebKit): the card inside the screen, not over its element, the tab bar or the parlay button, no
 *   sideways scroll, and axe (WCAG 2.2 A and AA) on the card.
 *
 * Not here, because the registry makes them unreachable today: a guide seeded at an older version showing once more
 * (every guide is at version 1 with reshowFrom 1; the rule is in guides.test.ts), and the survey and the notices' offer
 * waiting for a guide (they need the feedback and push stacks; see feedback.spec.ts and push).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { consents, guidesDone, owner, remove, signIn, account, todaysTeam } from "./readers";
import { L, assertClean, settle, skipWelcome, watch } from "./support";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const t = L.es;
const MORE = [
  "general",
  "home",
  "matches",
  "live",
  "match",
  "picks",
  "parlays",
  "odds",
  "my_picks",
  "profile",
];

const card = (page: Page) => page.getByTestId("guide-card");

/** Waits until the card has moved to its place (the page scrolls to the element, the card measures it). */
async function placed(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((done) => {
        requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(done, 120)));
      }),
  );
}

/** What is wrong with the card on screen right now: out of the screen, over its element, over the tab bar or the slip. */
async function problems(page: Page, label: string): Promise<string[]> {
  const found = await page.evaluate(
    ({ nav }) => {
      const out: string[] = [];
      const box = (el: Element | null) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 ? r : null;
      };
      const meet = (a: DOMRect, b: DOMRect) =>
        a.left < b.right - 1 &&
        a.right > b.left + 1 &&
        a.top < b.bottom - 1 &&
        a.bottom > b.top + 1;
      const c = box(document.querySelector('[data-testid="guide-card"]'));
      if (!c) return ["no card"];
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      if (c.left < -0.5 || c.top < -0.5 || c.right > vw + 0.5 || c.bottom > vh + 0.5)
        out.push(
          `the card leaves the screen (${[c.left, c.top, c.right, c.bottom].map(Math.round)} in ${vw}x${vh})`,
        );
      const ring = box(document.querySelector('[data-testid="guide-ring"]'));
      // a phone held sideways (390 px high) has no room for both: the card may brush the foot of the ringed block, by 24 px
      // at most (its text stays whole; the ring has 4 px of margin of its own)
      const brush =
        vh < 500 && Math.min(c.bottom, ring?.bottom ?? 0) - Math.max(c.top, ring?.top ?? 0) <= 24;
      if (ring && meet(c, ring) && !brush) {
        // docked below 1024 px: an element taller than the free band above the card is shown from its top, the card over
        // its lower part; any other is wholly above the card. From 1024 px the card sits beside the element.
        const head = Math.max(0, box(document.querySelector("header"))?.bottom ?? 0);
        const free = vw >= 1024 ? vh - head - c.height - 24 : c.top - head - 16;
        if (ring.height + 8 <= free) out.push("the card covers the element it points at");
        else if (ring.top < head - 8 || c.top - ring.top < 40)
          out.push("the card hides the start of a tall element it points at");
      }
      for (const bar of Array.from(document.querySelectorAll(`nav[aria-label="${nav}"]`))) {
        const r = box(bar);
        if (r && getComputedStyle(bar.closest("header") ?? bar).position !== "static" && meet(c, r))
          out.push("the card covers the navigation bar");
      }
      const slip = box(document.querySelector('[data-testid="slip-open"]'));
      if (slip && meet(c, slip)) out.push("the card covers the parlay button");
      const de = document.documentElement;
      if (de.scrollWidth > de.clientWidth) out.push("the page scrolls sideways");
      return out;
    },
    { nav: t.nav.mainNavigation },
  );
  return found.map((p) => `${label}: ${p}`);
}

/** Goes through the open guide step by step, checking every step; ends with Finalizar (or where there is no more). */
async function walk(page: Page, label: string, bad: string[]): Promise<number> {
  const open = card(page);
  await expect(open, `${label}: the guide opens`).toBeVisible();
  let steps = 0;
  for (let n = 0; n < 9; n++) {
    await placed(page);
    steps += 1;
    const wrong = await problems(page, `${label} #${n}`);
    if (wrong.length > 0)
      await page.screenshot({
        path: test.info().outputPath(`${label}-${n}.png`),
      });
    bad.push(...wrong);
    const axe = await new AxeBuilder({ page })
      .withTags(WCAG)
      .include('[data-testid="guide-card"]')
      .analyze();
    for (const v of axe.violations)
      bad.push(
        `${label} #${n}: axe ${v.id} (${v.impact}): ${v.nodes.map((x) => x.target.join(" ")).join(", ")}`,
      );
    const finish = open.getByTestId("guide-finish");
    if (await finish.count()) {
      await finish.click();
      await expect(open).toHaveCount(0);
      return steps;
    }
    const step = await open.getAttribute("data-step");
    const go = (await open.getByTestId("guide-start").count())
      ? open.getByTestId("guide-start")
      : open.getByTestId("guide-next");
    if (!(await go.count())) break;
    await go.click();
    await expect(async () => {
      if ((await open.count()) === 0) return;
      expect(await open.getAttribute("data-step")).not.toBe(step);
    }).toPass({ timeout: 10_000 });
  }
  return steps;
}

test("the welcome tour: Empezar, Siguiente, Atrás and Finalizar, remembered on a reload and in another browser", async ({
  page,
  browser,
}) => {
  test.setTimeout(240_000);
  const admin = await owner();
  const { id, email } = await account(admin, "gtour");
  try {
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page, email);
    await skipWelcome(page.request, { guides: "keep" });
    await consents(page);
    await page.goto("/home");
    const open = card(page);
    await expect(open).toHaveAttribute("data-guide-key", "general");
    // the welcome card: Saltar and Empezar, no Atrás yet
    await expect(open.getByTestId("guide-skip")).toBeVisible();
    await expect(open.getByTestId("guide-back")).toHaveCount(0);
    await open.getByTestId("guide-start").click();
    await expect(open).toContainText(t.guides.progress.split("{")[0] ?? "");
    // step 1: no Atrás; Siguiente to step 2, where Atrás goes back to step 1
    await expect(open.getByTestId("guide-back")).toHaveCount(0);
    const first = await open.getAttribute("data-step");
    await open.getByTestId("guide-next").click();
    await expect(open).not.toHaveAttribute("data-step", first ?? "");
    await open.getByTestId("guide-back").click();
    await expect(open).toHaveAttribute("data-step", first ?? "");
    // to the last step, which says Finalizar and has no Saltar
    for (let i = 0; i < 8 && (await open.getByTestId("guide-finish").count()) === 0; i++) {
      const at = await open.getAttribute("data-step");
      await open.getByTestId("guide-next").click();
      await expect(open).not.toHaveAttribute("data-step", at ?? "");
    }
    await expect(open.getByTestId("guide-skip")).toHaveCount(0);
    await open.getByTestId("guide-finish").click();
    await expect(open).toHaveCount(0);
    await settle(page);
    await page.reload();
    await settle(page);
    await expect(card(page), "a reload: not again").toHaveCount(0);
    // another browser of the same account: not again either (the state is the account's, not the browser's)
    const other = await browser.newContext();
    try {
      const second = await other.newPage();
      await signIn(second, email);
      await second.goto("/home");
      await settle(second);
      await expect(card(second), "another browser: not again").toHaveCount(0);
    } finally {
      await other.close();
    }
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("Saltar on the welcome card leaves Inicio's own guide skipped too: no guide on the next visit; «?» still brings it", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "gskip");
  try {
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await skipWelcome(page.request, { guides: "keep" });
    await consents(page);
    await page.goto("/home");
    await expect(card(page)).toHaveAttribute("data-guide-key", "general");
    await card(page).getByTestId("guide-skip").click();
    await expect(card(page)).toHaveCount(0);
    await settle(page);
    await page.reload();
    await settle(page);
    await expect(card(page), "the next visit to Inicio: no guide").toHaveCount(0);
    await page.getByTestId("guide-help").click();
    await expect(card(page), "«?» brings Inicio's guide").toHaveAttribute("data-guide-key", "home");
    await page.keyboard.press("Escape");
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("two skips in a row stop the automatic guides of the session; «?» still brings them", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin, "gtwo");
  try {
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, email);
    await skipWelcome(page.request, { guides: "keep" });
    await guidesDone(page.request, ["general", "home", "profile"]);
    await consents(page);
    // moving by the bar's links keeps the session (a reload would start it again)
    const go = async (href: string) => {
      await page
        .locator(`nav[aria-label="${t.nav.mainNavigation}"] a[href="${href}"]:visible`)
        .first()
        .click();
      await expect(page).toHaveURL(new RegExp(`${href}$`));
    };
    await page.goto("/home");
    await settle(page);
    await go("/picks");
    await expect(card(page), "first screen: its guide").toHaveAttribute("data-guide-key", "picks");
    await page.keyboard.press("Escape");
    await expect(card(page)).toHaveCount(0);
    await go("/my-picks");
    await expect(card(page), "second screen: its guide").toHaveAttribute(
      "data-guide-key",
      "my_picks",
    );
    await page.keyboard.press("Escape");
    await expect(card(page)).toHaveCount(0);
    await go("/matches");
    // the page itself, not the one on its way out, carries the «?» that is pressed next
    await expect(page.getByTestId("matches-days")).toBeVisible();
    await settle(page);
    await expect(card(page), "after two skips: nothing by itself").toHaveCount(0);
    await page.getByTestId("guide-help").click();
    await expect(card(page), "«?» still works").toHaveAttribute("data-guide-key", "matches");
    await page.keyboard.press("Escape");
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

const SIZES: Array<[number, number]> = [
  [320, 568],
  [390, 844],
  [768, 1024],
  [1024, 768],
  [1440, 900],
  [844, 390],
];

function responsive(name: string, size: { width: number; height: number }): void {
  test(`every guide, step by step, ${name}: inside the screen, not over its element, the bar or the parlay button, axe clean`, async ({
    page,
  }) => {
    test.setTimeout(420_000);
    const admin = await owner();
    const { id, email } = await account(admin, "gsize");
    try {
      const w = watch(page, { expect401: true, expectStatus: [403] });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.setViewportSize(size);
      await signIn(page, email);
      await skipWelcome(page.request, { guides: "keep" });
      await guidesDone(page.request, MORE); // none by itself: each is brought by hand below
      await consents(page);
      const team = await todaysTeam(page.request);
      const bad: string[] = [];
      let steps = 0;
      // the welcome tour, from Ayuda > Guías
      await page.goto("/help");
      await page.getByTestId("guide-open-general").click();
      await expect(page).toHaveURL(/\/home$/);
      steps += await walk(page, "general", bad);
      const screens: Array<[string, string]> = [
        ["/home", "home"],
        ["/matches", "matches"],
        ["/live", "live"],
        [`/matches/${team.fixture}`, "match"],
        ["/picks", "picks"],
        ["/parlays", "parlays"],
        ["/odds", "odds"],
        ["/my-picks", "my_picks"],
        ["/profile", "profile"],
      ];
      for (const [path, guide] of screens) {
        await page.goto(path);
        await settle(page);
        const help = page.getByTestId("guide-help");
        if ((await help.count()) === 0) {
          bad.push(`${guide}: no «?» on ${path} (the screen is off or empty in this stack)`);
          continue;
        }
        await help.first().click();
        steps += await walk(page, guide, bad);
      }
      expect(steps, "the steps seen").toBeGreaterThan(20);
      expect(bad, "what is wrong with the guides at this size").toEqual([]);
      await assertClean(page, w);
    } finally {
      await remove(admin, id, email);
      await admin.dispose();
    }
  });
}

for (const [width, height] of SIZES) responsive(`at ${width}x${height}`, { width, height });
responsive("on an iPhone 13 (WebKit)", { width: 390, height: 844 });
