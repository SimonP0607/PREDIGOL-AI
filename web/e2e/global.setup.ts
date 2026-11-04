/**
 * Signs every QA account in once, puts each back to the role, language and time zone
 * the suite expects, and saves its session (HttpOnly cookie) for the projects that
 * use it. Nothing is written to the database except those accounts' preferences and,
 * with the consent gate on, their acceptance of the current legal texts (plan UX, A4).
 */
import { expect, request, test as setup } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { ACCOUNTS, credentials, statePath, totpSecret, type AccountName } from "./accounts";
import { nextCode } from "./totp";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const HEADERS = { "x-requested-with": "predigol" };

for (const name of Object.keys(ACCOUNTS) as AccountName[]) {
  setup(`sign in as ${name}`, async () => {
    const spec = ACCOUNTS[name];
    const ctx = await request.newContext({ baseURL: BASE, extraHTTPHeaders: HEADERS });
    const login = await ctx.post("/api/v1/auth/login", { data: credentials(name) });
    expect(login.status(), `sign-in of the ${name} QA account`).toBe(200);
    let me = (await login.json()) as { role: string; stage?: string };
    expect(me.role, `${name} must be ${spec.role}`).toBe(spec.role);
    if (me.stage === "mfa") {
      const secret = totpSecret(name);
      expect(
        secret,
        `${name} uses a second factor: give the suite its secret (e2e/accounts.ts)`,
      ).toBeTruthy();
      const verified = await ctx.post("/api/v1/auth/mfa/verify", {
        data: { code: nextCode(secret ?? "") },
      });
      expect(verified.status(), `second factor of the ${name} QA account`).toBe(200);
      me = (await verified.json()) as { role: string; stage?: string };
    }
    expect(
      me.stage ?? "full",
      `${name} must finish signing in (enroll it: python -m scripts.accounts mfa-enroll ...)`,
    ).toBe("full");
    const prefs = await ctx.patch("/api/v1/auth/me/preferences", {
      data: { language: spec.lang, timezone: spec.tz },
    });
    expect(prefs.status()).toBe(200);
    // With the consent gate on (plan UX, A4; the QA API runs with FBI_CONSENT_GATE=drafts), a QA account accepts the
    // current texts once, as a reader would at the gate - so the suite reads the product, not the gate. The gate
    // itself is legal.spec.ts's, on an account of its own.
    const who = (await (await ctx.get("/api/v1/auth/me")).json()) as { consents_due?: string[] };
    if (who.consents_due?.length) {
      const state = (await (await ctx.get(`/api/v1/me/consents?lang=${spec.lang}`)).json()) as {
        purposes: Array<{ kind: string; version: string }>;
      };
      const accepted = await ctx.post("/api/v1/me/consents", {
        data: {
          decisions: state.purposes
            .filter((p) => who.consents_due?.includes(p.kind))
            .map((p) => ({ kind: p.kind, granted: true, version: p.version })),
          locale: spec.lang,
          source: "gate",
        },
      });
      expect(accepted.status(), `${name} accepts the current texts`).toBe(200);
    }
    mkdirSync(dirname(statePath(name)), { recursive: true });
    await ctx.storageState({ path: statePath(name) });
    await ctx.dispose();
  });
}
