/**
 * Signs every QA account in once, puts each back to the role, language and time zone
 * the suite expects, and saves its session (HttpOnly cookie) for the projects that
 * use it. Nothing is written to the database except those accounts' preferences.
 */
import { expect, request, test as setup } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { ACCOUNTS, credentials, statePath, type AccountName } from "./accounts";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const HEADERS = { "x-requested-with": "predigol" };

for (const name of Object.keys(ACCOUNTS) as AccountName[]) {
  setup(`sign in as ${name}`, async () => {
    const spec = ACCOUNTS[name];
    const ctx = await request.newContext({ baseURL: BASE, extraHTTPHeaders: HEADERS });
    const login = await ctx.post("/api/v1/auth/login", { data: credentials(name) });
    expect(login.status(), `sign-in of the ${name} QA account`).toBe(200);
    const me = (await login.json()) as { role: string };
    expect(me.role, `${name} must be ${spec.role}`).toBe(spec.role);
    const prefs = await ctx.patch("/api/v1/auth/me/preferences", {
      data: { language: spec.lang, timezone: spec.tz },
    });
    expect(prefs.status()).toBe(200);
    mkdirSync(dirname(statePath(name)), { recursive: true });
    await ctx.storageState({ path: statePath(name) });
    await ctx.dispose();
  });
}
