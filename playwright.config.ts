/**
 * End-to-end checks against the RUNNING stack - start it first:
 *   (backend repo) scripts/dev-up
 *   bun run test:e2e
 *
 * E2E_BASE_URL   the web app (default http://127.0.0.1:5173); the API is reached through it.
 * E2E_ACCOUNTS_DIR where the QA accounts' credential files are (default ~/.fbi), see e2e/accounts.ts.
 *
 * The suite signs in once per QA account (project "setup") and reuses the session:
 *   anon      sign-in, sign-out, redirects; RBAC over the API
 *   user-es   the product as a USER, in Spanish (America/Bogota)
 *   user-en   the product as a USER, in English (Europe/Madrid)
 *   admin     the Admin Console as SUPER_ADMIN, in English
 *   prefs     language and time-zone changes, serially, on their own account
 *   mobile    the product at 390 px
 * A full run loads a few hundred pages: the API's per-client limit must allow it
 * (dev-up sets FBI_API_RATE_LIMIT=3000).
 */
import { defineConfig, devices } from "@playwright/test";
import { statePath } from "./e2e/accounts";

const desktop = { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } };

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  workers: process.env["E2E_WORKERS"] ? Number(process.env["E2E_WORKERS"]) : 3,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "e2e-report" }]],
  outputDir: "e2e-results",
  use: {
    baseURL: process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "es-ES",
    timezoneId: "America/Bogota",
  },
  projects: [
    { name: "setup", testMatch: /global\.setup\.ts/ },
    { name: "anon", testMatch: /(auth|rbac)\.spec\.ts/, use: desktop, dependencies: ["setup"] },
    {
      name: "user-es",
      testMatch: /user\.spec\.ts/,
      metadata: { lang: "es" },
      use: { ...desktop, storageState: statePath("user") },
      dependencies: ["setup"],
    },
    {
      name: "user-en",
      testMatch: /user\.spec\.ts/,
      metadata: { lang: "en" },
      use: {
        ...desktop,
        storageState: statePath("userEn"),
        locale: "en-GB",
        timezoneId: "Europe/Madrid",
      },
      dependencies: ["setup"],
    },
    {
      name: "admin",
      testMatch: /admin\.spec\.ts/,
      use: { ...desktop, storageState: statePath("admin"), locale: "en-GB" },
      dependencies: ["setup"],
    },
    {
      name: "prefs",
      testMatch: /prefs\.spec\.ts/,
      fullyParallel: false,
      use: { ...desktop, storageState: statePath("switch") },
      dependencies: ["setup"],
    },
    {
      name: "mobile",
      testMatch: /responsive\.spec\.ts/,
      use: {
        ...devices["Pixel 7"],
        viewport: { width: 390, height: 844 },
        storageState: statePath("user"),
      },
      dependencies: ["setup"],
    },
  ],
});
