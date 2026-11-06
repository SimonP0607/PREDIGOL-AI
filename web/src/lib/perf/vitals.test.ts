/// <reference types="bun" />
/**
 * The experience's measures to Sentry (closing plan 5.3), without a browser: the sample is small and decided once, CLS
 * is the worst session window, a reading goes once when the page is hidden, the ratings are the web vitals' lines, a
 * reading carries numbers and a path and nothing of the person, a script the server no longer has is recognised, an API
 * error the reader saw goes once per reference (never an expected 401/403/404, never a 5xx again), and a service worker
 * failure says only the step. Reports asked for before the SDK is up are sent when it starts.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
  rateVital,
  reportServiceWorkerError,
  reportShownApiError,
  reportStaleModule,
  reportWebVitals,
  resetObservabilityForTests,
  startObservability,
  type MonitoringConfig,
} from "@/lib/observability";
import { isStaleModuleError } from "@/lib/staleModule";
import { ClsMeter, inSample, SAMPLE_RATE, startVitals } from "./vitals";

const EMAIL = "ana.perez" + "@example.com";
const ON: MonitoringConfig = {
  enabled: true,
  dsn: "https://browser@tunnel.predigol.invalid/1",
  environment: "production",
  tunnel: "/api/v1/monitoring/envelope",
};

describe("the sample and the meters", () => {
  test("a small share of visits, decided by one random number", () => {
    expect(SAMPLE_RATE).toBeLessThanOrEqual(0.05);
    expect(inSample(0.01)).toBe(true);
    expect(inSample(0.5)).toBe(false);
    expect(inSample(0.03, 0.03)).toBe(false);
  });

  test("CLS is the worst window of shifts, and a shift after a tap does not count", () => {
    const m = new ClsMeter();
    m.add({ value: 0.05, startTime: 100, hadRecentInput: false });
    m.add({ value: 0.04, startTime: 600, hadRecentInput: false }); // same window: 0.09
    m.add({ value: 0.5, startTime: 700, hadRecentInput: true }); // after a tap: not counted
    m.add({ value: 0.02, startTime: 9000, hadRecentInput: false }); // a new window: 0.02
    expect(m.value).toBeCloseTo(0.09, 5);
  });

  test("the ratings are the web vitals' lines", () => {
    expect(rateVital("lcp", 2500)).toBe("good");
    expect(rateVital("lcp", 3000)).toBe("needs-improvement");
    expect(rateVital("lcp", 4001)).toBe("poor");
    expect(rateVital("cls", 0.1)).toBe("good");
    expect(rateVital("cls", 0.3)).toBe("poor");
    expect(rateVital("inp", 200)).toBe("good");
    expect(rateVital("inp", 501)).toBe("poor");
  });

  test("outside the sample or without PerformanceObserver nothing is watched", () => {
    let reported = 0;
    startVitals(
      () => void (reported += 1),
      () => 0.9,
      { PerformanceObserver: class {}, document: {} } as never,
    )();
    startVitals(
      () => void (reported += 1),
      () => 0,
      { document: {} } as never,
    )();
    expect(reported).toBe(0);
  });

  test("a visit in the sample reports once, when the page is hidden", () => {
    const listeners: Record<string, () => void> = {};
    const doc = {
      visibilityState: "visible",
      addEventListener: (type: string, fn: () => void) => void (listeners[type] = fn),
      removeEventListener: () => undefined,
    };
    class FakePO {
      constructor(private cb: (l: { getEntries: () => unknown[] }) => void) {}
      observe(options: { type: string }) {
        if (options.type === "largest-contentful-paint")
          this.cb({ getEntries: () => [{ startTime: 1800 }] });
        if (options.type === "layout-shift")
          this.cb({ getEntries: () => [{ value: 0.02, startTime: 50, hadRecentInput: false }] });
        if (options.type === "event")
          this.cb({ getEntries: () => [{ interactionId: 3, duration: 120 }, { duration: 900 }] });
      }
      disconnect() {}
    }
    const got: unknown[] = [];
    startVitals(
      (v) => got.push(v),
      () => 0,
      { PerformanceObserver: FakePO, document: doc } as never,
    );
    listeners["visibilitychange"]?.();
    expect(got).toEqual([]); // still visible
    doc.visibilityState = "hidden";
    listeners["visibilitychange"]?.();
    listeners["visibilitychange"]?.();
    expect(got).toEqual([{ lcp: 1800, cls: 0.02, inp: 120 }]);
  });
});

describe("what goes to Sentry", () => {
  const g = globalThis as unknown as { window?: unknown };
  type Rec = { messages: unknown[][]; exceptions: unknown[][] };
  async function on(rec: Rec) {
    g.window = {
      innerWidth: 390,
      matchMedia: () => ({ matches: true }),
      location: { pathname: "/matches/812" },
    };
    const sdk = {
      init: () => undefined,
      setUser: () => undefined,
      captureException: (...a: unknown[]) => rec.exceptions.push(a),
      captureMessage: (...a: unknown[]) => rec.messages.push(a),
      flush: () => Promise.resolve(true),
      breadcrumbsIntegration: () => ({ name: "Breadcrumbs" }),
    } as unknown as typeof import("@sentry/browser");
    await startObservability(
      () => Promise.resolve(ON),
      () => Promise.resolve(sdk),
    );
  }
  // reports other test files left waiting (a registration that failed there) must not arrive here
  beforeEach(() => resetObservabilityForTests());
  afterEach(() => {
    resetObservabilityForTests();
    delete g.window;
  });

  test("a reading: numbers, the path, the worst rating, the device - and nothing else", async () => {
    const rec: Rec = { messages: [], exceptions: [] };
    await on(rec);
    reportWebVitals({ lcp: 3100.4, cls: 0.0123456, inp: 80 });
    const [message, options] = rec.messages[0] as [
      string,
      { level: string; tags: Record<string, string> },
    ];
    expect(message).toBe("web-vitals");
    expect(options.level).toBe("info");
    expect(options.tags).toEqual({
      kind: "web_vital",
      route: "/matches/812",
      viewport: "390",
      display: "app",
      lcp: "3100",
      inp: "80",
      cls: "0.012",
      rating: "needs-improvement",
    });
    reportWebVitals({});
    expect(rec.messages).toHaveLength(1); // nothing measured: nothing sent
  });

  test("an API error the reader saw goes once per reference; expected and server errors do not", async () => {
    const rec: Rec = { messages: [], exceptions: [] };
    await on(rec);
    reportShownApiError({ status: 422, code: "bad_input", requestId: "ab12" });
    reportShownApiError({ status: 422, code: "bad_input", requestId: "ab12" });
    reportShownApiError({ status: 404, code: "not_found", requestId: "c3" });
    reportShownApiError({ status: 403, code: "forbidden", requestId: "c4" });
    reportShownApiError({ status: 503, code: "down", requestId: "c5" });
    reportShownApiError({ status: 0, code: `x ${EMAIL}`, requestId: null });
    expect(rec.messages).toHaveLength(2);
    const [, first] = rec.messages[0] as [string, { tags: Record<string, string> }];
    expect(first.tags["request_id"]).toBe("ab12");
    expect(first.tags["shown"]).toBe("1");
    const [text, last] = rec.messages[1] as [string, { tags: Record<string, string> }];
    expect(text).toContain("unreachable");
    expect(last.tags["error_code"]).toBe("other"); // a code that is not a code is never sent as it came
    expect(JSON.stringify(rec.messages)).not.toContain(EMAIL);
  });

  test("a service worker failure names the step and nothing of the worker", async () => {
    const rec: Rec = { messages: [], exceptions: [] };
    await on(rec);
    reportServiceWorkerError("install");
    const [text, options] = rec.messages[0] as [string, { tags: Record<string, string> }];
    expect(text).toBe("service worker install failed");
    expect(options.tags).toMatchObject({ boundary: "service-worker", stage: "install" });
  });

  test("a failure before the SDK is up is sent when it starts, and only a few are kept", async () => {
    g.window = { location: { pathname: "/home" } };
    for (let i = 0; i < 9; i += 1) reportServiceWorkerError("register");
    reportStaleModule(new Error("Failed to fetch dynamically imported module: /assets/x.js"));
    const rec: Rec = { messages: [], exceptions: [] };
    await on(rec);
    expect(rec.messages).toHaveLength(5);
    expect(rec.exceptions).toHaveLength(0); // the stale module did not fit: the list is small on purpose
  });

  test("reports with the SDK off are nothing", () => {
    reportWebVitals({ lcp: 1 });
    reportShownApiError({ status: 422, code: "x", requestId: "r" });
    expect(true).toBe(true);
  });
});

describe("a script the server no longer has", () => {
  test("the browsers' words for it", () => {
    for (const m of [
      "Failed to fetch dynamically imported module: https://predigolai.com/assets/home-abc.js",
      "error loading dynamically imported module",
      "Importing a module script failed.",
      "Unable to preload CSS for /assets/x.css",
    ]) {
      expect(isStaleModuleError(new Error(m))).toBe(true);
    }
    const chunk = new Error("x");
    chunk.name = "ChunkLoadError";
    expect(isStaleModuleError(chunk)).toBe(true);
    expect(isStaleModuleError(new TypeError("Cannot read properties of undefined"))).toBe(false);
    expect(isStaleModuleError(undefined)).toBe(false);
  });
});
