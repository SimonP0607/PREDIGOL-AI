/**
 * The readers the guides' and the welcome's tests make and delete (plan UX, A13 and UX-051 to UX-054): an account the owner
 * creates with its password, signed in and through the consents, and the team that plays later today on the QA board.
 */
import { expect, request, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { getJson, sendJson } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
export const PASSWORD = "Mi-primer-partido-2026"; // gitleaks:allow - a QA account's password, made and deleted here

export async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

export async function account(
  admin: APIRequestContext,
  kind: string,
): Promise<{ id: number; email: string }> {
  const email = `e2e.welcome.${kind}.${Date.now()}@predigol.local`;
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

export async function remove(admin: APIRequestContext, id: number, email: string): Promise<void> {
  if (!id) return;
  const r = await sendJson(admin, "POST", `/api/v1/admin/users/${id}/anonymise`, {
    confirm: email,
  });
  expect([200, 409], `the test's account ${id} is deleted`).toContain(r.status);
}

export async function signIn(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
}

export async function consents(page: Page): Promise<void> {
  const gate = page.getByTestId("consent-gate");
  await expect(gate).toBeVisible();
  for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
    await gate.getByTestId(`consent-${kind}`).check();
  await gate.getByTestId("consent-submit").click();
  await expect(gate).toHaveCount(0);
}

interface TodayBody {
  data: {
    matches: {
      data: Array<{
        fixture_id: number;
        status_group: string;
        competition: { name: string };
        home: { id: number; name: string };
      }>;
    };
  };
}

/**
 * A team that plays later today: the home side of the QA seed's match of «QA Primera A» (seed_a9.py: «QA Bahía - QA Llano»,
 * later today in Bogotá, in a suggested league) - its name to search, its match to open.
 */
export async function todaysTeam(
  api: APIRequestContext,
): Promise<{ fixture: number; id: number; name: string }> {
  const today = await getJson<TodayBody>(api, "/api/v1/today");
  expect(today.status).toBe(200);
  const scheduled = today.body.data.matches.data.filter((m) => m.status_group === "scheduled");
  const match = scheduled.find((m) => m.competition.name === "QA Primera A") ?? scheduled[0];
  expect(match, "the QA seed puts a match later today on the board (seed_a9.py)").toBeTruthy();
  return { fixture: match?.fixture_id ?? 0, id: match?.home.id ?? 0, name: match?.home.name ?? "" };
}

/** The given guides recorded as completed (version 1) for the signed-in account: those a test is not about. */
export async function guidesDone(
  request: APIRequestContext,
  keys: readonly string[],
): Promise<void> {
  for (const guide of keys) {
    const r = await request.fetch(`/api/v1/me/guides/${guide}`, {
      method: "PUT",
      headers: { "x-requested-with": "predigol", "content-type": "application/json" },
      data: { version: 1, status: "completed", step: 0 },
    });
    expect(r.status(), `${guide} recorded as seen`).toBe(200);
  }
}
