/**
 * The visible state of a pick and «¿Por qué PrediGol eligió este pick?» (plan UX, B3; section 28), in the browser against the API,
 * on QA's example picks in the four states (seed_b3.py on fbi_qa_b3s, the QA stack with QA_PICK_STATES=1: the AI's review
 * applied - FBI_AI_MODE=enforce and a shadow report whose gate passed):
 *
 *     A  QA Cóndor     published, value now, review APPROVE    -> Recomendado        the day's set n.º 1, entered as Cautela
 *     B  QA Puma       published, value now, review DOWNGRADE  -> Cautela: the owner's preview only
 *     C  QA Colibrí    published, value now, review REJECT     -> No recomendado (rejected): the owner's preview only
 *     D  QA Guadua     published, value now, no review         -> Recomendado, «Revisión de contexto aún no aplicada»
 *     E  QA Frailejón  published, best price now 1.70          -> No recomendado (no value now): the owner's preview only
 *     S  QA Arrecife   shadow pick                             -> En evaluación, the owner's preview only
 *
 * «Solo verde» (UX-002): a reader is shown RECOMMENDED picks only - in Picks, in the day's set, on a match and in its analysis.
 *
 * * Picks lists only what a reader may be recommended, the state in words with its icon, and counts the rest;
 * * every published pick answers «¿Por qué?» in five layers, the conclusion first and open, the notice last, from the side at a
 *   desk and from the bottom on a 320 px phone, by finger and by keyboard - opening it records pick_explanation_opened once;
 * * a match never shows a reader a pick in caution or not recommended; the owner's preview shows it, with its state;
 * * a shadow pick is never shown to a reader - not even its explanation (404) - and is «En evaluación» in the owner's preview.
 *
 * On a reader account the test makes and deletes. Run with E2E_PICK_STATES=1 against that stack (the seed's prices are fresh
 * three hours).
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
const HOME_OF = {
  A: "QA Cóndor",
  B: "QA Puma",
  C: "QA Colibrí",
  D: "QA Guadua",
  E: "QA Frailejón",
  S: "QA Arrecife",
} as const;
type Name = keyof typeof HOME_OF;

interface Card {
  pick_id: number;
  fixture_id: number;
  home: { name: string };
  user_status: string;
  status_reason: string;
  context_pending: boolean;
}
interface Board {
  picks: Card[];
  withheld: number;
  reason: string | null;
}

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];

/** axe (WCAG 2.2 A and AA) on the page or on one part of it: no rule broken. */
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

/** Intl writes «50 %» with a no-break space: compared as plain spaces. */
const plain = (s: string) => s.replace(/[\u00a0\u202f]/g, " ");

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function account(admin: APIRequestContext): Promise<{ id: number; email: string }> {
  const email = `e2e.states.${Date.now()}@predigol.local`;
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
  await expect(gate.or(page.getByTestId("home-page"))).toBeVisible({ timeout: 30_000 });
  if (await gate.isVisible()) {
    for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
      await gate.getByTestId(`consent-${kind}`).check();
    await gate.getByTestId("consent-submit").click();
    await expect(gate).toHaveCount(0);
  }
}

/** The seed's picks in the list this caller is given (a reader's lacks B, C, E and S; the owner's preview has them all). */
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
    "QA's example picks are there (the stack with QA_PICK_STATES=1: seed_b3.py, its prices fresh three hours)",
  ).toBeTruthy();
  return out;
}

function must(cards: Partial<Record<Name, Card>>, name: Name): Card {
  const card = cards[name];
  expect(card, `${HOME_OF[name]}'s pick is listed`).toBeTruthy();
  return card!;
}

async function matchBoard(
  api: APIRequestContext,
  fixtureId: number,
  preview = false,
): Promise<Board> {
  const q = preview ? "&preview=shadow" : "";
  const r = await getJson<{ data: Board }>(
    api,
    `/api/v1/picks?fixture_id=${fixtureId}&hours=168${q}`,
  );
  expect(r.status).toBe(200);
  return r.body.data;
}

/** The match's pick as the owner's preview shows it (a reader is shown it only while it is RECOMMENDED). */
async function matchCard(api: APIRequestContext, fixtureId: number): Promise<Card> {
  const [card] = (await matchBoard(api, fixtureId, true)).picks;
  expect(card, `the owner's preview of the match ${fixtureId} shows its pick`).toBeTruthy();
  return card!;
}

/** The fixture of each seeded match, found through the owner's preview (which lists every pick, the shadow one too). */
async function fixtures(admin: APIRequestContext): Promise<Record<Name, number>> {
  const all = await seeded(admin, true);
  const out = {} as Record<Name, number>;
  for (const name of Object.keys(HOME_OF) as Name[]) out[name] = must(all, name).fixture_id;
  return out;
}

function listed(page: Page, name: Name): Locator {
  return page.getByTestId("picks-list").getByTestId("pick-card").filter({ hasText: HOME_OF[name] });
}

async function expectState(
  scope: Locator,
  status: string,
  reason: string,
  words: string,
): Promise<void> {
  const badge = scope.getByTestId("pick-status").first();
  await expect(badge).toHaveAttribute("data-status", status);
  await expect(badge).toHaveAttribute("data-reason", reason);
  await expect(badge).toContainText(words);
  await expect(
    badge.locator("svg").first(),
    "an icon beside the words, never colour alone",
  ).toBeVisible();
}

/** pick_explanation_opened as the page sends it (the product events' batch). */
function recordEvents(page: Page): Array<{ name: string; props: Record<string, unknown> }> {
  const events: Array<{ name: string; props: Record<string, unknown> }> = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/api/v1/events"))
      events.push(...((req.postDataJSON() as { events?: typeof events } | null)?.events ?? []));
  });
  return events;
}

async function layersInOrder(sheet: Locator): Promise<void> {
  const ids = await sheet
    .locator('[data-testid^="why-layer-"]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(ids).toEqual([
    "why-layer-conclusion",
    "why-layer-context",
    "why-layer-market",
    "why-layer-risks",
    "why-layer-how",
  ]);
  for (const layer of ["context", "market", "risks", "how"])
    await expect(sheet.getByTestId(`why-layer-${layer}`), `${layer}: folded`).not.toHaveAttribute(
      "open",
      "",
    );
  await expect(sheet.getByTestId("why-layer-conclusion")).toBeVisible();
}

test("Picks lists only what a reader may be recommended, the state in words, and counts the rest", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin);
  try {
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    const api = await seeded(page.request);
    expect(api.B, "a pick in caution is not in a reader's list (UX-002)").toBeUndefined();
    expect(api.C, "a rejected pick is not in a reader's list").toBeUndefined();
    expect(api.E, "a pick without value now is not in a reader's list").toBeUndefined();
    expect(api.S, "a shadow pick never reaches a reader").toBeUndefined();

    await page.goto("/picks");
    await settle(page);
    await expectState(listed(page, "A"), "RECOMMENDED", "approved", t.picks.status.RECOMMENDED);
    await expectState(listed(page, "D"), "RECOMMENDED", "not_reviewed", t.picks.status.RECOMMENDED);
    await expect(
      listed(page, "D").getByTestId("pick-status-pending"),
      "a recommendation the review has not looked at says so",
    ).toHaveText(t.picks.status.contextPending);
    await expect(listed(page, "A").getByTestId("pick-status-pending")).toHaveCount(0);
    for (const name of ["B", "C", "E", "S"] as const)
      await expect(listed(page, name)).toHaveCount(0);
    await expect(
      page
        .getByTestId("picks-list")
        .locator('[data-testid="pick-status"]:not([data-status="RECOMMENDED"])'),
      "nothing but «Recomendado» in a reader's list",
    ).toHaveCount(0);
    await expect(page.getByTestId("picks-withheld")).toHaveText(
      t.picks.withheld_other.replace("{count}", "3"),
    );

    // The day's set shows a reader the picks that entered it green: A entered with the review applied then (Cautela) and is
    // not shown; D, as the value rule left it, is.
    await expect(page.getByTestId("daily-item").filter({ hasText: HOME_OF.A })).toHaveCount(0);
    const dayD = page.getByTestId("daily-item").filter({ hasText: HOME_OF.D });
    await expectState(dayD, "RECOMMENDED", "value", t.picks.status.RECOMMENDED);
    await accessible(page, "Picks with its states");
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("«¿Por qué este pick?» at a desk: from the side, five layers, the conclusion open, the notice last, by keyboard too", async ({
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
    const api = await seeded(page.request);
    await page.goto("/picks");
    await settle(page);
    const button = listed(page, "A").getByTestId("why-pick");
    await expect(button).toHaveText(t.picks.why.open);
    await button.focus();
    await page.keyboard.press("Enter");
    const sheet = page.getByTestId("why-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByTestId("why-explanation")).toBeVisible();
    const box = (await sheet.boundingBox())!;
    expect(box.x + box.width, "from the right edge").toBeGreaterThanOrEqual(DESK.width - 1);
    expect(box.height, "the whole height").toBeGreaterThanOrEqual(DESK.height - 1);
    expect(box.width, "a side panel, not the page").toBeLessThanOrEqual(460);

    await expect(sheet.getByTestId("why-status")).toHaveAttribute("data-status", "RECOMMENDED");
    await expect(sheet.getByTestId("why-status-reason")).toContainText(
      t.picks.status.reason.approved,
    );
    await expect(
      sheet.getByTestId("why-day"),
      "it entered the day's set as Cautela, which a reader is not shown (UX-002)",
    ).toHaveCount(0);
    await layersInOrder(sheet);
    expect(plain(await sheet.getByTestId("why-layer-conclusion").innerText())).toContain(
      `PrediGol espera «Gana ${HOME_OF.A}»: le da un 50 % de probabilidad; el mercado, sin su margen, un 43 %.`,
    );
    await sheet.getByTestId("why-layer-market").locator("summary").click();
    const market = sheet.getByTestId("why-market");
    await expect(market).toBeVisible();
    await expect(market).toContainText("Mejor cuota ahora: 2,30");
    await expect(market).toContainText(t.picks.why.market.valueNow);
    await sheet.getByTestId("why-layer-how").locator("summary").click();
    await expect(sheet.getByTestId("why-how-steps").locator("li")).toHaveCount(5);
    await expect(sheet.getByTestId("why-how")).toHaveText(t.picks.why.how.listPick);
    await expect(sheet.getByTestId("disclaimer")).toBeVisible();
    await accessible(page, "the explanation at a desk", '[data-testid="why-sheet"]');
    const order = await sheet.evaluate((root) => {
      const how = root.querySelector('[data-testid="why-layer-how"]');
      const notice = root.querySelector('[data-testid="disclaimer"]');
      return how && notice ? how.compareDocumentPosition(notice) : 0;
    });
    expect(order & 4, "the notice closes the explanation").toBe(4);

    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(button, "the focus goes back to the button").toBeFocused();
    await expect
      .poll(() => events.filter((e) => e.name === "pick_explanation_opened").map((e) => e.props), {
        timeout: 20_000,
      })
      .toEqual([{ pick_id: must(api, "A").pick_id }]);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("on a 320 px phone: the states and the button inside the screen, the explanation from the bottom with 44 px rows", async ({
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
    const cards = page.getByTestId("picks-list").getByTestId("pick-card");
    await expect(cards.first()).toBeVisible();
    for (const card of await cards.all()) {
      for (const id of ["pick-status", "why-pick"]) {
        const b = await card.getByTestId(id).first().boundingBox();
        expect(b, `${id} on the card`).not.toBeNull();
        expect(b!.x + b!.width, `${id}: inside the screen`).toBeLessThanOrEqual(PHONE.width);
      }
    }
    const over = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(over, "nothing sideways").toBeLessThanOrEqual(1);

    await listed(page, "A").getByTestId("why-pick").click();
    const sheet = page.getByTestId("why-sheet");
    await expect(sheet.getByTestId("why-explanation")).toBeVisible();
    const box = (await sheet.boundingBox())!;
    expect(box.y + box.height, "from the bottom").toBeGreaterThanOrEqual(PHONE.height - 1);
    expect(box.y, "a sheet, not the whole screen").toBeGreaterThan(0);
    expect(box.width).toBeLessThanOrEqual(PHONE.width);
    await layersInOrder(sheet);
    for (const layer of ["context", "market", "risks", "how"]) {
      const row = await sheet.getByTestId(`why-layer-${layer}`).locator("summary").boundingBox();
      expect(row!.height, `${layer}: a 44 px row`).toBeGreaterThanOrEqual(44);
    }
    await sheet.getByTestId("why-layer-risks").locator("summary").click();
    await sheet.getByTestId("disclaimer").scrollIntoViewIfNeeded();
    await expect(sheet.getByTestId("disclaimer")).toBeVisible();
    const inner = await sheet.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(inner, "nothing sideways inside the sheet").toBeLessThanOrEqual(1);
    await accessible(page, "the explanation on a 320 px phone", '[data-testid="why-sheet"]');
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("a match never shows a reader a pick that is not green; the owner's preview shows it, with its state", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin);
  const ownerCtx = await browser.newContext({ storageState: statePath("admin"), viewport: DESK });
  try {
    const where = await fixtures(admin);
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true, expectStatus: [403, 404] });
    await signIn(page, email);

    // B (caution), C (rejected by the applied review) and E (no value now): their own match does not show a reader the pick,
    // nor its analysis the card; the owner's preview shows each with its state.
    const expected = {
      B: ["CAUTION", "downgraded"],
      C: ["NOT_RECOMMENDED", "rejected"],
      E: ["NOT_RECOMMENDED", "no_value_now"],
    } as const;
    for (const name of ["B", "C", "E"] as const) {
      const board = await matchBoard(page.request, where[name]);
      expect(board.picks, `${HOME_OF[name]}: not shown to a reader on its match`).toEqual([]);
      expect(board.withheld).toBe(1);
      const card = await matchCard(admin, where[name]);
      expect([card.user_status, card.status_reason]).toEqual([...expected[name]]);
      const analysis = await getJson<{ data: { cards: Card[] } | null }>(
        page.request,
        `/api/v1/matches/${where[name]}/analysis`,
      );
      expect(analysis.status).toBe(200);
      expect(
        (analysis.body.data?.cards ?? []).filter(
          (x) => x.user_status && x.user_status !== "RECOMMENDED",
        ),
        `${HOME_OF[name]}: no analysis card a reader gets is in caution or not recommended`,
      ).toEqual([]);
    }
    const c = await matchCard(admin, where.C);
    await page.goto(`/matches/${where.C}`);
    await settle(page);
    await expect(page.getByTestId("match-picks")).toHaveCount(0);
    await expect(page.getByTestId("analysis-verdict")).toHaveCount(0);

    // S: a reader never learns that a shadow pick exists.
    const shadowId = must(await seeded(admin, true), "S").pick_id;
    const hidden = await getJson(page.request, `/api/v1/picks/${shadowId}/explanation`);
    expect(hidden.status, "a reader asking for a shadow pick's explanation").toBe(404);
    const peek = await getJson(
      page.request,
      `/api/v1/picks/${shadowId}/explanation?preview=shadow`,
    );
    expect([403, 404], "nor through the preview").toContain(peek.status);
    const published = await getJson<{ data: Card }>(
      page.request,
      `/api/v1/picks/${c.pick_id}/explanation`,
    );
    expect(published.status, "every published pick answers «¿por qué?», whatever its state").toBe(
      200,
    );
    expect(published.body.data.user_status).toBe("NOT_RECOMMENDED");
    await assertClean(page, w);

    // The owner's preview: B in caution, with the applied review's risks inside «Riesgos».
    const ob = await ownerCtx.newPage();
    await ob.addInitScript(() => window.sessionStorage.setItem("predigol.shadowPreview", "1"));
    await ob.goto("/picks");
    await settle(ob);
    await listed(ob, "B").getByTestId("why-pick").click();
    const bSheet = ob.getByTestId("why-sheet");
    await expect(bSheet.getByTestId("why-status")).toHaveAttribute("data-status", "CAUTION");
    await bSheet.getByTestId("why-layer-risks").locator("summary").click();
    await expect(bSheet.getByTestId("why-review-risks")).toContainText(
      "QA: el rival llega descansado y con su once completo",
    );
    await ob.close();

    // The owner's preview: S is «En evaluación» - never a recommendation - and says why.
    const op = await ownerCtx.newPage();
    await op.addInitScript(() => window.sessionStorage.setItem("predigol.shadowPreview", "1"));
    await op.goto("/picks");
    await settle(op);
    // the owner's account reads the product in its own language (the QA owner's is English)
    const ownerText = (await op.locator("html").getAttribute("lang"))?.startsWith("en")
      ? L.en
      : L.es;
    const s = listed(op, "S");
    await expectState(s, "EVALUATION", "evaluation", ownerText.picks.status.EVALUATION);
    await s.getByTestId("why-pick").click();
    const ownerSheet = op.getByTestId("why-sheet");
    await expect(ownerSheet.getByTestId("why-status")).toHaveAttribute("data-status", "EVALUATION");
    await ownerSheet.getByTestId("why-layer-how").locator("summary").click();
    await expect(ownerSheet.getByTestId("why-how")).toHaveText(ownerText.picks.why.how.evaluation);
  } finally {
    await ownerCtx.close();
    await remove(admin, id, email);
    await admin.dispose();
  }
});
