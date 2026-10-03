/**
 * What every page must satisfy, whatever the data: no value leaked through
 * unformatted, no horizontal page scroll, nothing still loading once the
 * network is quiet, and no console error, page error or failed API call.
 *
 * The suite reads the running stack (scripts/dev-up api web); it seeds and
 * mocks nothing. Where real data is too thin to exercise a flow - no captured
 * prices yet, no picks yet - the test says so in an annotation instead of
 * pretending.
 */
import { expect, type Page, type TestInfo } from "@playwright/test";

export const API_URL = (process.env["E2E_API_URL"] ?? "http://127.0.0.1:8010").replace(/\/$/, "");

const LEAKS: ReadonlyArray<readonly [string, RegExp]> = [
  ["NaN", /\bNaN\b/],
  ["undefined", /\bundefined\b/],
  ["[object Object]", /\[object Object\]/],
  ["Infinity", /\bInfinity\b/],
];

/** An API call, whether made to the API directly or through the web server's proxy. */
function isApi(url: string): boolean {
  if (url.startsWith(API_URL)) return true;
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

export function watch(page: Page): Watch {
  const w: Watch = { problems: [] };
  page.on("console", (msg) => {
    if (msg.type() === "error") w.problems.push(`console.error: ${msg.text().slice(0, 300)}`);
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
    // A navigation cancels the previous page's fetches: that is not a failure.
    if (isApi(req.url()) && !why.includes("ERR_ABORTED")) {
      w.problems.push(`request failed: ${req.url()} ${why}`);
    }
  });
  return w;
}

/** Wait until the page's queries have answered. */
export async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0);
}

export async function assertClean(page: Page, w: Watch): Promise<void> {
  const text = await page.locator("body").innerText();
  for (const [name, re] of LEAKS) {
    expect(re.test(text), `"${name}" is rendered on ${page.url()}`).toBe(false);
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

interface Envelope<T> {
  status: string;
  data: T;
  reason?: string | null;
}

export async function api<T>(path: string): Promise<Envelope<T>> {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok && res.status !== 404) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as Envelope<T>;
}
