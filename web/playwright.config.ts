/**
 * End-to-end checks against the RUNNING stack - start it first:
 *   (backend repo) scripts/dev-up
 *   bun run test:e2e
 *
 * E2E_BASE_URL   the web app (default http://127.0.0.1:5173); the API is reached through it.
 * E2E_ACCOUNTS_DIR where the QA accounts' credential files are (default ~/.fbi), see e2e/accounts.ts.
 *
 * The suite signs in once per QA account (project "setup") and reuses the session:
 *   anon      sign-in, sign-out, redirects; RBAC over the API; the server-function path (R02)
 *   user-es   the product as a USER, in Spanish (America/Bogota), and the glossary at a desk
 *   user-en   the product as a USER, in English (Europe/Madrid)
 *   admin     the Admin Console as SUPER_ADMIN, in English
 *   security  two-step verification: set-up, recovery codes, required password, codes; the owner's resets
 *   prefs     language and time-zone changes, serially, on their own account
 *   mobile    the product at 390 px, and the glossary under a finger (its own reader, "phone")
 *   mobile-webkit  the phone checks at 320, 390 and 430 px in WebKit, the engine of every iPhone browser
 *   membership  the trial, the owner's renewal and the limit of an ended membership (plan UX, A8)
 *   account   getting in without the owner (plan UX, A7): invitation, activation, recovery, unlocking. With the QA
 *             API's self-service off it checks that nothing is offered; on (QA_SELF_SERVICE=1 QA_MESSENGER=1), the
 *             e-mails' links, read from the QA messenger's folder (E2E_MAIL_SINK)
 *   pwa       manifest, service worker and offline page (E2E_PWA=1, production build only)
 *   prod-smoke  read-only checks of a deployed site, no sign-in (E2E_PROD_SMOKE=1, E2E_BASE_URL=the site)
 * Two measurements run only when asked, and never fail on what they measure:
 *   a11y      axe-core on the sign-in page and the product, WCAG 2.2 A/AA (E2E_A11Y=1)
 *   screens   reference screenshots of the product at 320/360/390/412/430 px (E2E_SCREENS=1)
 * A full run loads a few hundred pages: the API's per-client limit must allow it
 * (dev-up sets FBI_API_RATE_LIMIT=3000). The web must run in live mode (web/.env.example:
 * VITE_DATA_MODE=live and VITE_API_BASE_URL set to the web's own origin): without the API address the
 * app shows its demo adapter and the Admin Console's modules are scaffolds.
 */
import { defineConfig, devices } from "@playwright/test";
import { statePath } from "./e2e/accounts";

const desktop = { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } };

// The pwa project cuts the service worker's own network (e2e/pwa.spec.ts): Playwright routes a worker's requests
// only with this switch, and it must be set before the browser starts.
if (process.env["E2E_PWA"]) process.env["PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS"] ??= "1";

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
    {
      name: "anon",
      testMatch: /(auth|rbac|serverfn)\.spec\.ts/,
      use: desktop,
      dependencies: ["setup"],
    },
    {
      name: "user-es",
      // glossary.spec.ts: the one glossary at a desk (plan UX, A3); analytics.spec.ts: a journey's events (A6)
      testMatch: /(user|glossary|analytics)\.spec\.ts/,
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
      // observability.spec.ts: the console's error-reporting tests (plan UX, A2), skipped without E2E_SENTRY_SINK
      testMatch: /(admin|observability)\.spec\.ts/,
      use: { ...desktop, storageState: statePath("admin"), locale: "en-GB" },
      dependencies: ["setup"],
    },
    {
      // Two-step verification and the staged sign-in, the legal texts and the consent gate (plan UX, A4), and the
      // messages to readers (A5), each on an account the test creates and switches off.
      name: "security",
      testMatch: /(security|legal|messaging)\.spec\.ts/,
      use: desktop,
      dependencies: ["setup"],
    },
    {
      name: "account",
      testMatch: /account\.spec\.ts/,
      use: desktop,
      dependencies: ["setup"],
    },
    {
      // The membership (plan UX, A8): from the trial to the renewal, and the limit (QA_MEMBERSHIP_ENFORCE=1 and
      // E2E_DATABASE_URL, which writes a trial that has ended).
      name: "membership",
      testMatch: /membership\.spec\.ts/,
      use: desktop,
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
      // The installable app (manifest, service worker, offline page). Needs a PRODUCTION build: the dev server
      // never registers the worker. Run with E2E_PWA=1 against the deployed stack (deploy/vps).
      name: "pwa",
      testMatch: /pwa\.spec\.ts/,
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } },
    },
    {
      name: "mobile",
      // glossary.spec.ts: the one glossary under a finger (plan UX, A3)
      testMatch: /(responsive|glossary)\.spec\.ts/,
      use: {
        ...devices["Pixel 7"],
        viewport: { width: 390, height: 844 },
        storageState: statePath("phone"),
      },
      dependencies: ["setup"],
    },
    {
      // Every iPhone browser draws with WebKit: the phone checks of responsive.spec.ts at the narrowest, the most
      // common and the widest iPhone widths (320, 390, 430 px) - every page fits with the whole tab bar, team
      // names are whole, and controls answer a finger.
      name: "mobile-webkit",
      testMatch: /responsive\.spec\.ts/,
      grep: /\b(320|390|430) px (touch )?phone\b/,
      use: {
        ...devices["iPhone 13"],
        viewport: { width: 390, height: 844 },
        storageState: statePath("phone"),
      },
      dependencies: ["setup"],
    },
    ...(process.env["E2E_PROD_SMOKE"]
      ? [
          // Read-only checks of a deployed site (plan UX, A2): E2E_BASE_URL=https://predigolai.com E2E_PROD_SMOKE=1.
          // No sign-in, no account, nothing written.
          { name: "prod-smoke", testMatch: /prod-smoke\.spec\.ts/, use: desktop },
        ]
      : []),
    ...(process.env["E2E_A11Y"]
      ? [{ name: "a11y", testMatch: /a11y\.spec\.ts/, use: desktop, dependencies: ["setup"] }]
      : []),
    ...(process.env["E2E_SCREENS"]
      ? [
          {
            name: "screens",
            testMatch: /screens\.spec\.ts/,
            use: { ...devices["Pixel 7"], storageState: statePath("phone") },
            dependencies: ["setup"],
          },
        ]
      : []),
  ],
});
