/**
 * «Explícame» (plan UX, B9; section 26), in the browser against the API, on QA's example picks of B3 (seed_b3.py on the QA
 * stack with QA_PICK_STATES=1; run with E2E_EXPLAIN=1 against that stack):
 *
 *     A  QA Cóndor     published, value now, review APPROVE    -> Recomendado
 *     B  QA Puma       published, value now, review DOWNGRADE  -> Cautela
 *     S  QA Arrecife   shadow pick                             -> never a reader's
 *
 * * every pick of the list has the button; a tap lists the pick's questions and a question answers in the reader's words -
 *   «¿Por qué cautela?» says Cautela for B and «no está en cautela» for A - with «¿Te sirvió?», «Otra pregunta» and the
 *   glossary; the answer is never a guess and says «No tengo ese dato» when PrediGol lacks it;
 * * from the side at a desk and from the bottom on a 320 px phone, by finger and by keyboard (the focus goes back);
 * * opening an answer records `explain_opened` with the question - a slug, never text - once;
 * * the API: a match's three questions and the parlay's, a shadow pick is a 404 for a reader (not for the owner's preview), an
 *   unknown question is a 422, and the parlay answers in the slip's own terms.
 *
 * On a reader account the test makes and deletes.
 */
import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  request,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, skipWelcome, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const PASSWORD = "Penalty-spot-at-dusk-27"; // gitleaks:allow - a QA account's password, made and deleted here
const PHONE = { width: 320, height: 720 };
const DESK = { width: 1440, height: 900 };
const t = L.es;
const HOME_OF = { A: "QA Cóndor", B: "QA Puma", S: "QA Arrecife" } as const;
type Name = keyof typeof HOME_OF;

interface Card {
  pick_id: number;
  fixture_id: number;
  home: { name: string };
  market_key: string;
  selection: string;
  line: string | number;
}
interface Board {
  picks: Card[];
}
interface Answer {
  entity: string;
  item_id: number | null;
  intent: string;
  answered: boolean;
  lines: Array<{ say: string | null; fact: { code: string } | null }>;
  terms: string[];
  links: string[];
}

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];

async function accessible(page: Page, what: string, within?: string): Promise<void> {
  const builder = new AxeBuilder({ page }).withTags(AXE_TAGS);
  const result = await (within ? builder.include(within) : builder).analyze();
  expect(
    result.violations.map(
      (v) => `${v.id} (${v.impact ?? "?"}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    ),
    `${what}: axe, WCAG 2.2 A and AA`,
  ).toEqual([]);
}

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function account(admin: APIRequestContext): Promise<{ id: number; email: string }> {
  const email = `e2e.explain.${Date.now()}@predigol.local`;
  const created = await sendJson<{ data: { id: number } }>(admin, "POST", "/api/v1/admin/users", {
    email,
    password: PASSWORD,
    role: "USER",
    language: "es",
    timezone: "America/Bogota",
    must_change_password: false,
  });
  expect(created.status, "the owner creates the test's account").toBe(201);
  return { id: created.body.data.id, email };
}

async function remove(admin: APIRequestContext, id: number, email: string): Promise<void> {
  const r = await sendJson(admin, "POST", `/api/v1/admin/users/${id}/anonymise`, {
    confirm: email,
  });
  expect([200, 409], `the test's account ${id} is deleted`).toContain(r.status);
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
  await skipWelcome(page.request);
  await page.goto("/home");
  const gate = page.getByTestId("consent-gate");
  await expect(gate.or(page.getByTestId("home-today"))).toBeVisible({ timeout: 30_000 });
  if (await gate.isVisible()) {
    for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
      await gate.getByTestId(`consent-${kind}`).check();
    await gate.getByTestId("consent-submit").click();
    await expect(gate).toHaveCount(0);
  }
}

async function seeded(
  api: APIRequestContext,
  preview = false,
): Promise<Partial<Record<Name, Card>>> {
  const q = preview ? "&preview=shadow" : "";
  const board = await getJson<{ data: Board }>(api, `/api/v1/picks?hours=24${q}`);
  expect(board.status).toBe(200);
  const out: Partial<Record<Name, Card>> = {};
  for (const name of Object.keys(HOME_OF) as Name[]) {
    const card = board.body.data.picks.find((p) => p.home.name === HOME_OF[name]);
    if (card) out[name] = card;
  }
  expect(
    out.A ?? out.B,
    "QA's example picks are there (QA_PICK_STATES=1: seed_b3.py)",
  ).toBeTruthy();
  return out;
}

function must(cards: Partial<Record<Name, Card>>, name: Name): Card {
  const card = cards[name];
  expect(card, `${HOME_OF[name]}'s pick is listed`).toBeTruthy();
  return card!;
}

function listed(page: Page, name: Name): Locator {
  return page.getByTestId("picks-list").getByTestId("pick-card").filter({ hasText: HOME_OF[name] });
}

function recordEvents(page: Page): Array<{ name: string; props: Record<string, unknown> }> {
  const events: Array<{ name: string; props: Record<string, unknown> }> = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/api/v1/events"))
      events.push(...((req.postDataJSON() as { events?: typeof events } | null)?.events ?? []));
  });
  return events;
}

test("«Explícame» on a pick at a desk: from the side, its questions answered in words, by keyboard too", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin);
  try {
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    const events = recordEvents(page);
    await signIn(page, email);
    await seeded(page.request);
    await page.goto("/picks");
    await settle(page);

    const button = listed(page, "B").getByTestId("explain-pick");
    await expect(button).toHaveText(t.explain.button);
    await expect(button).toHaveAttribute("aria-haspopup", "dialog");
    await button.focus();
    await page.keyboard.press("Enter");
    const sheet = page.getByTestId("explain-sheet");
    await expect(sheet).toBeVisible();
    const box = (await sheet.boundingBox())!;
    expect(box.x + box.width, "from the right edge").toBeGreaterThanOrEqual(DESK.width - 1);
    expect(box.width, "a side panel, not the page").toBeLessThanOrEqual(460);

    // the questions of a pick, and nothing is asked of the API before one is chosen
    await expect(sheet.getByTestId("explain-questions").locator("button")).toHaveCount(2);
    await expect(sheet.getByTestId("explain-q-risks")).toHaveText(t.explain.question.pick.risks);
    await expect(sheet.getByTestId("explain-q-caution")).toHaveText(
      t.explain.question.pick.caution,
    );
    expect(events.filter((e) => e.name === "explain_opened")).toHaveLength(0);

    // B is in Cautela: the answer says why, and what «cautela» means
    await sheet.getByTestId("explain-q-caution").click();
    const answer = sheet.getByTestId("explain-answer");
    await expect(answer).toBeVisible();
    await expect(answer).toContainText(t.explain.say.caution_downgraded);
    await expect(answer).toContainText(t.explain.say.caution_what);
    await expect(sheet.getByTestId("explain-no-data")).toHaveCount(0);
    await expect(sheet.getByTestId("explain-terms")).toBeVisible();
    await expect(sheet.getByTestId("explain-link-glossary")).toBeVisible();
    await expect(sheet.getByTestId("helpful-vote"), "«¿Te sirvió?» ends the answer").toBeVisible();
    await expect(sheet.getByTestId("disclaimer")).toBeVisible();

    // another question of the same pick: its probability is PrediGol's, and even with value it does not always win
    await sheet.getByTestId("explain-back").click();
    await expect(sheet.getByTestId("explain-questions")).toBeVisible();
    await sheet.getByTestId("explain-q-risks").click();
    await expect(sheet.getByTestId("explain-answer")).toContainText(
      /de probabilidad de acertar: aun con valor, no siempre gana/,
    );
    await accessible(page, "the answer at a desk", '[data-testid="explain-sheet"]');

    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(button, "the focus goes back to the button").toBeFocused();

    // A is not in Cautela and says why not
    await listed(page, "A").getByTestId("explain-pick").click();
    await page.getByTestId("explain-q-caution").click();
    await expect(page.getByTestId("explain-answer")).toContainText(
      t.explain.say.caution_none_approved,
    );
    await page.keyboard.press("Escape");

    // opening an answer records the question - a slug, never text
    await expect
      .poll(
        () =>
          events
            .filter((e) => e.name === "explain_opened")
            .map((e) => e.props["what"])
            .sort(),
        { timeout: 20_000 },
      )
      .toEqual(["pick.caution", "pick.caution", "pick.risks"]);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("«Explícame» on a 320 px phone: from the bottom, questions with a 44 px target, no sideways scroll", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin);
  try {
    await page.setViewportSize(PHONE);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await seeded(page.request);
    await page.goto("/picks");
    await settle(page);
    await listed(page, "A").getByTestId("explain-pick").tap();
    const sheet = page.getByTestId("explain-sheet");
    await expect(sheet).toBeVisible();
    const box = (await sheet.boundingBox())!;
    expect(box.y + box.height, "from the bottom edge").toBeGreaterThanOrEqual(PHONE.height - 1);
    expect(box.width, "the whole width").toBeGreaterThanOrEqual(PHONE.width - 1);
    for (const q of await sheet.getByTestId("explain-questions").locator("button").all()) {
      expect((await q.boundingBox())!.height, "a finger's target").toBeGreaterThanOrEqual(44);
    }
    await sheet.getByTestId("explain-q-risks").tap();
    await expect(sheet.getByTestId("explain-answer")).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      "no sideways scroll",
    ).toBe(true);
    await accessible(page, "the answer on a phone", '[data-testid="explain-sheet"]');
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("the API: a match's questions, the parlay's, a shadow pick that never reaches a reader, an unknown question", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const admin = await owner();
  const { id, email } = await account(admin);
  try {
    await signIn(page, email);
    const api = page.request;
    const cards = await seeded(page.request);
    const all = await seeded(admin, true);
    const a = must(cards, "A");

    const noPick = await getJson<{ data: Answer }>(
      api,
      `/api/v1/explain?entity=match&id=${a.fixture_id}&intent=no_pick`,
    );
    expect(noPick.status).toBe(200);
    expect(noPick.body.data.answered).toBe(true);
    expect(noPick.body.data.lines.map((l) => l.say)).toContain("has_pick");

    for (const intent of ["forecast", "risks"]) {
      const r = await getJson<{ data: Answer }>(
        api,
        `/api/v1/explain?entity=match&id=${a.fixture_id}&intent=${intent}`,
      );
      expect(r.status, intent).toBe(200);
      expect(r.body.data.lines.length, `${intent}: always says something`).toBeGreaterThan(0);
      if (!r.body.data.answered)
        expect(
          r.body.data.lines.every((l) => l.say !== null || l.fact !== null),
          "a missing datum is said, never a guess",
        ).toBe(true);
    }

    // a question that is not the place's
    const wrong = await getJson(
      api,
      `/api/v1/explain?entity=match&id=${a.fixture_id}&intent=caution`,
    );
    expect(wrong.status).toBe(422);
    const missing = await getJson(api, "/api/v1/explain?entity=match&id=999999999&intent=risks");
    expect(missing.status).toBe(404);

    // a shadow pick never reaches a reader; the owner's preview sees it
    const shadow = must(all, "S");
    const hidden = await getJson(
      api,
      `/api/v1/explain?entity=pick&id=${shadow.pick_id}&intent=risks`,
    );
    expect(hidden.status, "a reader asking about a shadow pick").toBe(404);
    const preview = await getJson<{ data: Answer }>(
      admin,
      `/api/v1/explain?entity=pick&id=${shadow.pick_id}&intent=risks&preview=shadow`,
    );
    expect(preview.status).toBe(200);

    // the parlay: one leg is that selection's probability; the answer never invents one
    const leg = {
      fixture_id: a.fixture_id,
      market_key: a.market_key,
      selection: a.selection,
      line: a.line,
    };
    const one = await sendJson<{ data: Answer }>(api, "POST", "/api/v1/explain/parlay", {
      legs: [leg],
    });
    expect(one.status).toBe(200);
    expect(one.body.data.lines.map((l) => l.say)).toContain("parlay_single");
    const none = await sendJson(api, "POST", "/api/v1/explain/parlay", { legs: [] });
    expect([200, 422]).toContain(none.status);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});
