/**
 * The legal texts and the consent gate (plan UX, A4), in the browser.
 *
 * * The three texts are public: a visitor reads them before having an account, with their version, their fingerprint
 *   (sha256), the draft notice while the lawyer has not approved them, and their contents - which fold away on a
 *   320 px phone. The notice on every screen links them.
 * * The gate, on an existing account that has accepted nothing (the owner creates it for the test and switches it off
 *   at the end; the QA API runs with FBI_CONSENT_GATE=drafts): four separate, unticked boxes with the server's own
 *   sentences, 44 px to a finger, none of the product until all four are ticked; withdrawing the processing
 *   authorisation in the profile brings back that one box. Then the profile's copy of the data (the password first)
 *   and a deletion request with its legal deadline, which the owner sees and answers.
 */
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const TEXTS = join(import.meta.dirname, "..", "..", "backend", "src", "fbi", "customer", "texts");
const t = L.es;
const PASSWORD = "E2e-consent-pass-2026"; // gitleaks:allow - the password of a QA account the test creates and switches off

interface Text {
  title: string;
  sections: Array<{ id: string }>;
}

function text(lang: "es" | "en", document: string): Text {
  return JSON.parse(readFileSync(join(TEXTS, lang, `${document}.json`), "utf8")) as Text;
}

function draft(document: string): boolean {
  const register = JSON.parse(readFileSync(join(TEXTS, "versions.json"), "utf8")) as Record<
    string,
    { versions: Array<{ draft: boolean }> }
  >;
  return register[document]?.versions.at(-1)?.draft ?? false;
}

async function axeViolations(page: Page, include?: string): Promise<string[]> {
  const builder = new AxeBuilder({ page }).withTags(WCAG);
  const result = await (include ? builder.include(include) : builder).analyze();
  return result.violations.map(
    (v) => `${v.id} (${v.impact ?? "?"}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
}

test("the legal texts are public, with their version, fingerprint and contents, in both languages", async ({
  page,
}) => {
  const w = watch(page, { expect401: true });
  await page.goto("/legal/terms");
  const article = page.getByTestId("legal-page");
  await expect(article).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(text("es", "terms").title);
  await expect(page.getByTestId("legal-draft")).toHaveCount(draft("terms") ? 1 : 0);
  await expect(page.getByTestId("legal-sha256")).toHaveText(/[0-9a-f]{64}/);
  await expect(article.locator("section[id]")).toHaveCount(text("es", "terms").sections.length);
  // a visitor's frame: a way in, nothing of the product
  await expect(page.getByTestId("public-sign-in")).toBeVisible();
  await expect(page.getByTestId("tab-home")).toHaveCount(0);
  expect(await axeViolations(page, '[data-testid="legal-page"]')).toEqual([]);
  await assertClean(page, w);

  // every text, and every section's anchor
  for (const [slug, document] of [
    ["privacy", "privacy"],
    ["responsible-gaming", "responsible_gaming"],
  ] as const) {
    await page.goto(`/legal/${slug}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(text("es", document).title);
    for (const s of text("es", document).sections) {
      await expect(page.locator(`section#${s.id}`)).toHaveCount(1);
    }
    await assertClean(page, w);
  }

  // the reader's language
  await page.goto("/legal/terms");
  await page.getByTestId("lang-en").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(text("en", "terms").title);
  await page.getByTestId("lang-es").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(text("es", "terms").title);

  // nothing else is a text
  await page.goto("/legal/cookies");
  await expect(page.getByText(t.errors.pageNotFound)).toBeVisible();
});

test("a legal text reads on a 320 px phone: no sideways scroll, the contents folded, anchors that work", async ({
  page,
}) => {
  const w = watch(page, { expect401: true });
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/legal/privacy");
  await expect(page.getByTestId("legal-page")).toBeVisible();
  const contents = page.locator("details").first();
  await expect(contents).not.toHaveAttribute("open", /.*/);
  const summary = contents.locator("summary");
  expect((await summary.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  await summary.click();
  await contents.getByRole("link", { name: /Tus derechos|derechos/i }).click();
  await expect(page).toHaveURL(/#derechos$/);
  await expect(page.locator("section#derechos")).toBeInViewport();
  await assertClean(page, w);
});

test("the notice on every screen links the three texts", async ({ browser }) => {
  const context = await browser.newContext({ storageState: statePath("user") });
  const page = await context.newPage();
  const w = watch(page);
  await page.goto("/home");
  await settle(page);
  const notice = page.getByTestId("disclaimer").first();
  await expect(notice).toContainText(t.common.disclaimer);
  await expect(notice.getByRole("link")).toHaveCount(3);
  await notice.getByRole("link", { name: t.legal.links.responsibleGaming }).click();
  await expect(page).toHaveURL(/\/legal\/responsible-gaming$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    text("es", "responsible_gaming").title,
  );
  // a signed-in reader reads it inside the product's own frame
  await expect(page.getByTestId("tab-home")).toBeVisible();
  await assertClean(page, w);
  await context.close();
});

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByTestId("login-submit").click();
}

test("the consent gate: four separate boxes before the product, a withdrawal brings back its one box, the copy of the data and a deletion request", async ({
  page,
  browser,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const email = `e2e.consent.${Date.now()}@predigol.local`;
  const created = await sendJson<{ data: { id: number } }>(admin, "POST", "/api/v1/admin/users", {
    email,
    password: PASSWORD,
    role: "USER",
    language: "es",
    timezone: "America/Bogota",
    must_change_password: false,
  });
  expect(created.status).toBe(201);
  const id = created.body.data.id;
  try {
    // 403 consent_required is the product's answer while the boxes are owed; a wrong password is refused on purpose
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);

    // 1. the gate: four boxes, none ticked, the product closed until all four are
    const gate = page.getByTestId("consent-gate");
    await expect(gate).toBeVisible();
    const state = await getJson<{
      gate: boolean;
      due: string[];
      purposes: Array<{ kind: string; statement: string; version: string }>;
    }>(page.request, "/api/v1/me/consents?lang=es");
    expect(state.body.gate, "the QA API must run with FBI_CONSENT_GATE=drafts").toBe(true);
    expect(state.body.due).toEqual(["terms", "privacy", "age_18", "risk_notice"]);
    const boxes = gate.locator('input[type="checkbox"]');
    await expect(boxes).toHaveCount(4);
    for (const p of state.body.purposes) {
      const box = gate.getByTestId(`consent-${p.kind}`);
      await expect(box).not.toBeChecked();
      // the server's own sentence, and the whole row answers a finger
      const label = gate.locator("label", { has: box });
      await expect(label).toContainText(p.statement);
      expect((await label.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
    expect(await axeViolations(page, '[data-testid="consent-gate"]')).toEqual([]);
    const submit = gate.getByTestId("consent-submit");
    await expect(submit).toBeDisabled();
    const product = await page.request.get("/api/v1/me/picks", {
      headers: { "x-requested-with": "predigol" },
    });
    expect(product.status()).toBe(403);
    for (const kind of ["terms", "privacy", "age_18"])
      await gate.getByTestId(`consent-${kind}`).check();
    await expect(submit).toBeDisabled();
    await gate.getByTestId("consent-risk_notice").check();
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(gate).toHaveCount(0);
    await expect(page.getByTestId("tab-home")).toBeVisible();
    await settle(page);
    const after = await getJson<{
      due: string[];
      history: Array<{ kind: string; granted: boolean; source: string }>;
    }>(page.request, "/api/v1/me/consents?lang=es");
    expect(after.body.due).toEqual([]);
    expect(after.body.history.map((h) => [h.kind, h.granted, h.source]).sort()).toEqual(
      [
        ["age_18", true, "gate"],
        ["privacy", true, "gate"],
        ["risk_notice", true, "gate"],
        ["terms", true, "gate"],
      ].sort(),
    );

    // 2. the profile: what was accepted and when; withdrawing the authorisation closes the product again
    await page.goto("/profile");
    const consentRow = page.getByTestId("privacy-consent-privacy");
    await expect(consentRow).toContainText(
      t.legal.privacy.accepted.split("{date}")[0]?.trim() ?? "",
    );
    await consentRow.getByTestId("privacy-withdraw").click();
    await consentRow.getByTestId("privacy-withdraw-confirm").click();
    await expect(consentRow).toContainText(
      t.legal.privacy.withdrawn.split("{date}")[0]?.trim() ?? "",
    );
    await page.goto("/home");
    await expect(gate).toBeVisible();
    await expect(gate.locator('input[type="checkbox"]')).toHaveCount(1);
    await gate.getByTestId("consent-privacy").check();
    await gate.getByTestId("consent-submit").click();
    await expect(gate).toHaveCount(0);
    await expect(page.getByTestId("tab-home")).toBeVisible();

    // 3. a copy of the data: the password first, then a file with the reader's own data
    await page.goto("/profile");
    const exportBlock = page.getByTestId("privacy-export");
    await exportBlock.getByTestId("privacy-export-start").click();
    await exportBlock.getByTestId("privacy-password").fill(PASSWORD);
    const downloading = page.waitForEvent("download");
    await exportBlock.getByTestId("privacy-export-confirm").click();
    const file = await downloading;
    expect(file.suggestedFilename()).toMatch(/^predigol-datos-\d{4}-\d{2}-\d{2}\.json$/);
    const data = JSON.parse(readFileSync(await file.path(), "utf8")) as {
      account: { email: string };
      consents: unknown[];
    };
    expect(data.account.email).toBe(email);
    expect(data.consents).toHaveLength(6);
    await expect(exportBlock).toContainText(t.legal.privacy.exported);

    // 4. a deletion request: the password again, and its legal deadline in sight
    const requests = page.getByTestId("privacy-requests");
    await requests.getByTestId("privacy-kind").selectOption("privacy_deletion");
    await requests.getByTestId("privacy-message").fill("Quiero que borren mis datos.");
    await requests.getByTestId("privacy-password").fill(PASSWORD);
    await requests.getByTestId("privacy-send").click();
    await expect(requests.getByTestId("privacy-result")).toContainText(
      t.legal.privacy.sent.split("{date}")[0]?.trim() ?? "",
    );
    const card = requests.getByTestId("privacy-request").first();
    await expect(card).toHaveAttribute("data-kind", "privacy_deletion");
    await expect(card.getByTestId("privacy-deadline")).toBeVisible();
    await assertClean(page, w);

    // 5. the owner sees it, with its deadline, and answers
    const ownerPage = await (
      await browser.newContext({ storageState: statePath("admin"), locale: "en-GB" })
    ).newPage();
    await ownerPage.goto("/admin/users");
    const list = ownerPage.getByTestId("admin-privacy-requests");
    const item = list.locator("li", { hasText: email }).first();
    await expect(item).toBeVisible();
    await item.locator("textarea").fill("Recibida: la atendemos dentro del plazo legal.");
    await item.getByRole("button", { name: L.en.legal.admin.send }).click();
    await expect(item).toContainText(L.en.legal.privacy.status.answered);
    await ownerPage.context().close();
    await page.reload();
    await expect(requests.getByTestId("privacy-request").first()).toHaveAttribute(
      "data-status",
      "answered",
    );
  } finally {
    await sendJson(admin, "PATCH", `/api/v1/admin/users/${id}`, { status: "disabled" });
    await admin.dispose();
  }
});
