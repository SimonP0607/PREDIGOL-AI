/**
 * What every page must satisfy, whatever the data: no value leaked through
 * unformatted, no horizontal page scroll, nothing still loading once the network
 * is quiet, and no console error, page error or failed API call.
 *
 * The suite reads the running stack (scripts/dev-up api web) and signs in with
 * the QA accounts (e2e/accounts.ts). It seeds and mocks nothing: where real data
 * is too thin to exercise a step, the test says so in an annotation.
 */
import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * The UI catalogs, read from disk (Node's ESM loader would want import attributes for
 * JSON); typed from the Spanish files, which have exactly the keys of the English ones.
 */
const NAMESPACES = [
  "admin",
  "auth",
  "common",
  "errors",
  "home",
  "live",
  "markets",
  "match",
  "matches",
  "nav",
  "odds",
  "parlays",
  "picks",
  "profile",
  "truth",
] as const;
interface Catalogs {
  admin: typeof import("../src/locales/es/admin.json");
  auth: typeof import("../src/locales/es/auth.json");
  common: typeof import("../src/locales/es/common.json");
  errors: typeof import("../src/locales/es/errors.json");
  home: typeof import("../src/locales/es/home.json");
  live: typeof import("../src/locales/es/live.json");
  markets: typeof import("../src/locales/es/markets.json");
  match: typeof import("../src/locales/es/match.json");
  matches: typeof import("../src/locales/es/matches.json");
  nav: typeof import("../src/locales/es/nav.json");
  odds: typeof import("../src/locales/es/odds.json");
  parlays: typeof import("../src/locales/es/parlays.json");
  picks: typeof import("../src/locales/es/picks.json");
  profile: typeof import("../src/locales/es/profile.json");
  truth: typeof import("../src/locales/es/truth.json");
}

function catalogs(lang: "es" | "en"): Catalogs {
  const dir = join(import.meta.dirname, "..", "src", "locales", lang);
  return Object.fromEntries(
    NAMESPACES.map((ns) => [
      ns,
      JSON.parse(readFileSync(join(dir, `${ns}.json`), "utf8")) as unknown,
    ]),
  ) as unknown as Catalogs;
}

export const L = { es: catalogs("es"), en: catalogs("en") } as const;
export type Lang = keyof typeof L;

const LEAKS: ReadonlyArray<readonly [string, RegExp]> = [
  ["NaN", /\bNaN\b/],
  ["undefined", /\bundefined\b/],
  ["[object Object]", /\[object Object\]/],
  ["Infinity", /\bInfinity\b/],
  [
    "an untranslated key",
    /\b(common|nav|home|picks|parlays|odds|matches|live|match|markets|admin|profile|auth|errors|system|ops|research|analytics|catalog|center|truth)\.[a-z][\w.]+[a-z]\b/,
  ],
];

function isApi(url: string): boolean {
  try {
    const path = new URL(url).pathname;
    return path.startsWith("/api/v1") || path === "/health";
  } catch {
    return false;
  }
}

export interface Watch {
  problems: string[];
}

/**
 * `expect401`: the sign-in screen asks /auth/me before anyone is signed in; that
 * 401 is the expected answer, not a failure.
 */
export function watch(page: Page, { expect401 = false }: { expect401?: boolean } = {}): Watch {
  const w: Watch = { problems: [] };
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (expect401 && text.includes("401")) return;
    w.problems.push(`console.error: ${text.slice(0, 300)}`);
  });
  page.on("pageerror", (err) => w.problems.push(`pageerror: ${err.message.slice(0, 300)}`));
  page.on("response", (res) => {
    const status = res.status();
    if (status === 429) {
      w.problems.push(`429 ${res.url()} - raise FBI_API_RATE_LIMIT on the API for an E2E run`);
    } else if (status >= 500 && isApi(res.url())) {
      w.problems.push(`HTTP ${status} ${res.url()}`);
    }
  });
  page.on("requestfailed", (req) => {
    const why = req.failure()?.errorText ?? "";
    if (isApi(req.url()) && !why.includes("ERR_ABORTED")) {
      w.problems.push(`request failed: ${req.url()} ${why}`);
    }
  });
  return w;
}

/** Wait until the page's queries have answered and no skeleton is left. */
export async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 20_000 });
}

export async function assertClean(page: Page, w: Watch): Promise<void> {
  const text = await page.locator("body").innerText();
  for (const [name, re] of LEAKS) {
    const m = re.exec(text);
    expect(m, `"${name}" is rendered on ${page.url()}: ${m?.[0] ?? ""}`).toBeNull();
  }
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `${page.url()} scrolls horizontally by ${overflow}px`).toBeLessThanOrEqual(1);
  expect(w.problems, `console errors, page errors or failed API calls on ${page.url()}`).toEqual(
    [],
  );
}

/** Say, in the report, that real data did not allow a step - never fake it. */
export function note(info: TestInfo, description: string): void {
  info.annotations.push({ type: "data", description });
}

export async function getJson<T>(
  request: APIRequestContext,
  path: string,
): Promise<{ status: number; body: T }> {
  const res = await request.get(path, { headers: { "x-requested-with": "predigol" } });
  return { status: res.status(), body: (await res.json().catch(() => null)) as T };
}
