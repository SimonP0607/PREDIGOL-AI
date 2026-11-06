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
 *   journey   the real test's sixteen steps on one invited account at 390 px (plan UX, A16), from the invitation's
 *             e-mail to the recovery; journey-webkit, the same in WebKit. Needs self-service and the QA messenger
 *             (QA_SELF_SERVICE=1 QA_MESSENGER=1, E2E_MAIL_SINK); skipped otherwise
 *   profile   the account centre's eight blocks (plan UX, B1), at 320 px and at a desk, on its own accounts
 *   pwa       manifest, service worker and offline page (E2E_PWA=1, production build only)
 *   prod-smoke  read-only checks of a deployed site, no sign-in (E2E_PROD_SMOKE=1, E2E_BASE_URL=the site)
 * Two measurements run only when asked, and never fail on what they measure:
 *   states    the visible state of a pick and «¿Por qué este pick?» on QA's example picks (E2E_PICK_STATES=1, the QA
 *             stack with QA_PICK_STATES=1: seed_b3.py and the AI's review applied)
 *   postmatch the Postpartido of QA's finished match with its picks explained (E2E_POSTMATCH=1, the QA stack with
 *             QA_POSTMATCH=1: seed_b4.py; E2E_DATABASE_URL for the reader's saved picks)
 *   mypicks   Mis picks completo on a reader with more than 600 saved picks: «Todo» page by page, the filters, totals and
 *             breakdown against SQL, the sample, the line value and the CSV (E2E_MYPICKS=1, the QA stack with
 *             QA_MYPICKS=1: seed_b5.py; E2E_DATABASE_URL for the readers' saved picks)
 *   feedback  the monthly survey (once in 30 days, never after an error, by keyboard, at 320 px), «¿Te sirvió?» saved with
 *             its context, Novedades and /admin/product (E2E_FEEDBACK=1, the QA stack with QA_PICK_STATES=1;
 *             E2E_DATABASE_URL for the readers' answers; E2E_FEEDBACK_OFF=1 against FBI_FEEDBACK=0)
 *   notifications  the notices on the devices: the profile's block, the offer, the bell, the install guide and the test
 *             notice to a stand-in push service (E2E_PUSH=1, the QA stack with QA_PUSH=1 QA_MESSENGER=1, one worker;
 *             E2E_PUSH_OFF=1 against the stack without the VAPID key)
 *   a11y      axe-core on the sign-in page and the product, WCAG 2.2 A/AA; critical and serious fail (E2E_A11Y=1)
 *   perf      LCP and CLS of Inicio, a match and Picks on a phone (E2E_PERF=1; closing plan 5.2)
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
      // observability.spec.ts: the console's error-reporting tests (plan UX, A2), skipped without E2E_SENTRY_SINK;
      // customers.spec.ts: the customer's card and the audit page's fixes (plan UX, B10)
      testMatch: /(admin|observability|customers)\.spec\.ts/,
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
      // The welcome, the favourites, the hints and the tour (plan UX, A13), on accounts the test makes: timed from the
      // invitation's link with self-service on (E2E_MAIL_SINK), from the sign-in otherwise; E2E_DATABASE_URL for the
      // account from before A13.
      name: "onboarding",
      testMatch: /onboarding\.spec\.ts/,
      use: desktop,
      dependencies: ["setup"],
    },
    {
      // Help and support (plan UX, A14; gate G10): Ayuda, a ticket with its context answered in the console's Soporte,
      // from an error and from a match, the sheet at 320 px, the readers kept apart - on accounts the test makes.
      name: "support",
      testMatch: /support\.spec\.ts/,
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
      // The real test's journey (plan UX, A16; section 45): one invited account through the sixteen steps, on a phone -
      // Android's engine here, an iPhone's in journey-webkit. Its own account, made and deleted by the test.
      name: "journey",
      testMatch: /journey\.spec\.ts/,
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } },
      dependencies: ["setup"],
    },
    {
      name: "journey-webkit",
      testMatch: /journey\.spec\.ts/,
      use: { ...devices["iPhone 13"], viewport: { width: 390, height: 844 } },
      dependencies: ["setup"],
    },
    {
      // The account centre (plan UX, B1): the eight blocks on a 320 px phone and at a desk, by finger and by keyboard,
      // on accounts the test makes and deletes.
      name: "profile",
      testMatch: /profile\.spec\.ts/,
      use: desktop,
      dependencies: ["setup"],
    },
    {
      // Personalisation (plan UX, B2): two accounts with different favourites, the reasons at 320 px, the markets in the
      // reader's order and the suggestion - on accounts the test makes and deletes.
      name: "personal",
      testMatch: /personal\.spec\.ts/,
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
    ...(process.env["E2E_PICK_STATES"]
      ? [
          // The visible state of a pick and «¿Por qué este pick?» (plan UX, B3): QA's example picks in the four states
          // (seed_b3.py on fbi_qa_b3s, the QA stack with QA_PICK_STATES=1 - the AI's review applied), at a desk and on a
          // 320 px phone, on a reader account the test makes and deletes.
          {
            name: "states",
            testMatch: /pickstates\.spec\.ts/,
            use: desktop,
            dependencies: ["setup"],
          },
        ]
      : []),
    ...(process.env["E2E_EXPLAIN"]
      ? [
          // «Explícame» (plan UX, B9): the frequent questions of a pick, a match and the parlay answered from what PrediGol
          // already keeps - on QA's example picks of B3 (the stack with QA_PICK_STATES=1), at a desk and on a 320 px phone, on
          // a reader account the test makes and deletes.
          {
            name: "explain",
            testMatch: /explain\.spec\.ts/,
            use: desktop,
            dependencies: ["setup"],
          },
        ]
      : []),
    ...(process.env["E2E_POSTMATCH"]
      ? [
          // Postpartido (plan UX, B4): QA's finished match with its published picks settled and explained (seed_b4.py on
          // fbi_qa_b4p, the QA stack with QA_POSTMATCH=1) and a reader's saved picks written by the test (E2E_DATABASE_URL).
          {
            name: "postmatch",
            testMatch: /postmatch\.spec\.ts/,
            use: desktop,
            dependencies: ["setup"],
          },
        ]
      : []),
    ...(process.env["E2E_MYPICKS"]
      ? [
          // Mis picks completo (plan UX, B5): QA's world of 330 finished matches (seed_b5.py on fbi_qa_relm, the QA stack with
          // QA_MYPICKS=1) and two readers the test makes, with their saved picks written into the QA database (E2E_DATABASE_URL).
          {
            name: "mypicks",
            testMatch: /mypicks\.spec\.ts/,
            use: desktop,
            dependencies: ["setup"],
          },
        ]
      : []),
    ...(process.env["E2E_FEEDBACK"] || process.env["E2E_FEEDBACK_OFF"]
      ? [
          // What readers think (plan UX, B6): the monthly survey, «¿Te sirvió?», Novedades and the owner's view, on readers
          // the test makes (aged past their first week in the QA database, E2E_DATABASE_URL); the QA stack with
          // QA_PICK_STATES=1 for an explanation to vote on. E2E_FEEDBACK_OFF=1 against FBI_FEEDBACK=0.
          {
            name: "feedback",
            testMatch: /feedback\.spec\.ts/,
            use: desktop,
            dependencies: ["setup"],
          },
        ]
      : []),
    ...(process.env["E2E_PUSH"] || process.env["E2E_PUSH_OFF"]
      ? [
          // The notices on the readers' devices (plan UX, B7): the profile's block, the offer after a moment, the bell, the
          // install guide, the test notice through the QA messenger to a stand-in push service (127.0.0.1:9996), the owner's
          // card - with the browser's permission and subscription simulated. The QA stack with QA_PUSH=1 QA_MESSENGER=1 and
          // E2E_DATABASE_URL, one worker; E2E_PUSH_OFF=1 against the stack without the VAPID key.
          {
            name: "notifications",
            testMatch: /notifications\.spec\.ts/,
            use: desktop,
            dependencies: ["setup"],
          },
        ]
      : []),
    ...(process.env["E2E_DIGEST"] || process.env["E2E_DIGEST_OFF"]
      ? [
          // Email opcional (plan UX, B8): the weekly summary's box in the profile, the summary through the QA messenger
          // (E2E_MAIL_SINK) by its own sender with the one-click headers, and the leaving link's page - on readers the
          // test makes, every decision checked in the QA database (E2E_DATABASE_URL). The QA stack with QA_DIGEST=1
          // QA_MESSENGER=1; E2E_DIGEST_OFF=1 against the stack without QA_DIGEST: nothing offered, as in production.
          {
            name: "digest",
            testMatch: /digest\.spec\.ts/,
            use: desktop,
            dependencies: ["setup"],
          },
        ]
      : []),
    ...(process.env["E2E_PERF"]
      ? [
          {
            name: "perf",
            testMatch: /perf\.spec\.ts/,
            use: { ...devices["Pixel 7"], storageState: statePath("phone") },
            dependencies: ["setup"],
          },
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
