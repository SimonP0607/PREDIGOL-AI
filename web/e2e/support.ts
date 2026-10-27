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
  "records",
  "truth",
  "ai",
  "memory",
  "glossary",
  "legal",
  "transparency",
  "onboarding",
  "support",
  "push",
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
  records: typeof import("../src/locales/es/records.json");
  truth: typeof import("../src/locales/es/truth.json");
  ai: typeof import("../src/locales/es/ai.json");
  memory: typeof import("../src/locales/es/memory.json");
  glossary: typeof import("../src/locales/es/glossary.json");
  legal: typeof import("../src/locales/es/legal.json");
  transparency: typeof import("../src/locales/es/transparency.json");
  onboarding: typeof import("../src/locales/es/onboarding.json");
  support: typeof import("../src/locales/es/support.json");
  push: typeof import("../src/locales/es/push.json");
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
    /\b(common|nav|home|picks|parlays|odds|matches|live|match|markets|admin|profile|auth|errors|system|ops|research|analytics|catalog|center|truth|records|ai|glossary|legal|transparency|onboarding|support|push)\.[a-z][\w.]+[a-z]\b/,
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
 * 401 is the expected answer, not a failure. `expectStatus`: other refusals the
 * test provokes on purpose (a reused password is a 422).
 */
export function watch(
  page: Page,
  { expect401 = false, expectStatus = [] }: { expect401?: boolean; expectStatus?: number[] } = {},
): Watch {
  const w: Watch = { problems: [] };
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (expect401 && text.includes("401")) return;
    if (expectStatus.some((s) => text.includes(`status of ${s}`))) return;
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
    // A request the page itself gave up (a navigation away, a query superseded) is not a failure: Chromium says
    // ERR_ABORTED, WebKit "Load request cancelled" (the analytics' last batch as a page is left, plan UX, A15).
    const cancelled = why.includes("ERR_ABORTED") || why.includes("Load request cancelled");
    if (isApi(req.url()) && !cancelled) {
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

/** A request that changes state, as the app makes it: same-site header, the account's cookie. */
export async function sendJson<T>(
  request: APIRequestContext,
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  data?: unknown,
): Promise<{ status: number; body: T }> {
  const res = await request.fetch(path, {
    method,
    headers: { "x-requested-with": "predigol", "content-type": "application/json" },
    ...(data === undefined ? {} : { data }),
  });
  return { status: res.status(), body: (await res.json().catch(() => null)) as T };
}

/**
 * A new account's welcome (plan UX, A13), recorded as done through the API - for the tests that are not about it: the
 * gate then sends the account where the test goes, once the page loads again.
 */
export async function skipWelcome(request: APIRequestContext): Promise<void> {
  const r = await request.fetch("/api/v1/me/onboarding", {
    method: "POST",
    headers: { "x-requested-with": "predigol", "content-type": "application/json" },
    data: {},
  });
  expect(r.status(), "the welcome recorded as done").toBe(200);
}

export async function getJson<T>(
  request: APIRequestContext,
  path: string,
): Promise<{ status: number; body: T }> {
  const res = await request.get(path, { headers: { "x-requested-with": "predigol" } });
  return { status: res.status(), body: (await res.json().catch(() => null)) as T };
}

/**
 * The controls a finger cannot hit at 44 x 44 px: the box, widened by the "tap" utilities' ::after, cut by a
 * clipping parent the control sits inside. Inline text links are exempt (WCAG 2.5.8).
 */
export async function smallTargets(page: Page, scope = "body"): Promise<string[]> {
  return page.evaluate((root) => {
    const out: string[] = [];
    const container = document.querySelector(root);
    if (!container) return out;
    const sel =
      'a[href], button, [role="tab"], input:not([type="hidden"]), select, textarea, summary, [role="switch"]';
    for (const control of Array.from(container.querySelectorAll<HTMLElement>(sel))) {
      // A native select or date field laid invisibly over its chip (opacity 0): the chip is what a finger aims at.
      const el =
        getComputedStyle(control).opacity === "0" && control.parentElement
          ? control.parentElement
          : control;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      if (!r.width || !r.height || s.visibility === "hidden" || s.display === "none") continue;
      if (el.tagName === "A" && s.display === "inline") continue;
      // A control under another layer (an open sheet's backdrop) is not in reach anyway.
      const hitTest = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (
        hitTest &&
        !el.contains(hitTest) &&
        !hitTest.contains(el) &&
        r.top >= 0 &&
        r.bottom <= innerHeight
      )
        continue;
      let top = r.top;
      let bottom = r.bottom;
      let left = r.left;
      let right = r.right;
      const a = getComputedStyle(el, "::after");
      if (
        a.content &&
        a.content !== "none" &&
        a.content !== "normal" &&
        a.position === "absolute"
      ) {
        top = Math.min(top, r.top + parseFloat(a.top));
        bottom = Math.max(bottom, r.bottom - parseFloat(a.bottom));
        left = Math.min(left, r.left + parseFloat(a.left));
        right = Math.max(right, r.right - parseFloat(a.right));
      }
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ps = getComputedStyle(p);
        if (ps.overflowX === "visible" && ps.overflowY === "visible") continue;
        const pr = p.getBoundingClientRect();
        if (r.top >= pr.top - 0.5 && r.bottom <= pr.bottom + 0.5) {
          top = Math.max(top, pr.top);
          bottom = Math.min(bottom, pr.bottom);
        }
        if (r.left >= pr.left - 0.5 && r.right <= pr.right + 0.5) {
          left = Math.max(left, pr.left);
          right = Math.min(right, pr.right);
        }
      }
      if (right - left < 43.5 || bottom - top < 43.5) {
        const name = (control.getAttribute("aria-label") ?? control.textContent ?? "")
          .trim()
          .slice(0, 40);
        out.push(
          `${el.tagName.toLowerCase()} "${name}" ${Math.round(right - left)}x${Math.round(bottom - top)}`,
        );
      }
    }
    return out;
  }, scope);
}
