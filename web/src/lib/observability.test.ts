import { afterEach, describe, expect, test } from "bun:test";
import type { Breadcrumb, ErrorEvent } from "@sentry/browser";
import {
  cleanUrl,
  deviceTags,
  reportApiFailure,
  reportError,
  resetObservabilityForTests,
  scrubBreadcrumb,
  scrubEvent,
  scrubText,
  setObservedUser,
  startObservability,
  type MonitoringConfig,
} from "./observability";

// data, as a page would carry it: built from parts so no source line holds it whole
const EMAIL = "ana.perez" + "@example.com";
const TOKEN = "Zk3pQ9mX_2vLr8TnY4wB7cHs1uJd6Ef0" + "Ga5KoPiRqWe";
const NAME = "Ana " + "Pérez Gómez";
const PSEUDONYM = "0123456789abcdef0123";

function loaded(): ErrorEvent {
  return {
    type: undefined,
    message: `failed for ${EMAIL}`,
    request: {
      url: `https://predigolai.com/my-picks?token=${TOKEN}#x`,
      headers: { "User-Agent": "Mozilla/5.0 (iPhone)", Referer: `https://x/?email=${EMAIL}` },
    },
    user: { id: "42", email: EMAIL, ip_address: "203.0.113.7" },
    exception: {
      values: [
        {
          type: "TypeError",
          value: `Cannot read properties of undefined (reading '${NAME}') ${EMAIL}\nsecond line ${TOKEN}`,
          stacktrace: { frames: [{ function: "save", vars: { password: "x", email: EMAIL } }] },
        },
      ],
    },
    breadcrumbs: [
      { category: "console", message: `token ${TOKEN}` },
      { category: "ui.click", message: NAME },
      {
        type: "http",
        category: "fetch",
        data: {
          method: "GET",
          url: `/api/v1/me/picks?cursor=${TOKEN}`,
          status_code: 500,
          body: EMAIL,
        },
      },
      { category: "navigation", data: { from: `/reset?token=${TOKEN}`, to: "/home" } },
    ],
    extra: { email: EMAIL, note: `for ${EMAIL}`, nested: { password: "x", ok: "kept" } },
    tags: { route: "/my-picks", session: TOKEN },
  } as ErrorEvent;
}

describe("the filter of the web's errors (plan UX, A2)", () => {
  test("nothing personal leaves the browser", () => {
    const out = scrubEvent(loaded());
    expect(out).not.toBeNull();
    const written = JSON.stringify(out);
    for (const secret of [EMAIL, TOKEN, NAME, "Pérez", "203.0.113.7", "second line"]) {
      expect(written).not.toContain(secret);
    }
    expect(out?.user).toBeUndefined();
  });

  test("what a person needs to debug stays", () => {
    const out = scrubEvent(loaded());
    expect(out?.request).toEqual({
      url: "https://predigolai.com/my-picks",
      headers: { "User-Agent": "Mozilla/5.0 (iPhone)" },
    });
    expect(out?.exception?.values?.[0]?.value).toBe(
      "Cannot read properties of undefined (reading <value>) <email>",
    );
    expect(out?.exception?.values?.[0]?.stacktrace?.frames?.[0]).toEqual({ function: "save" });
    expect(out?.breadcrumbs?.map((c: Breadcrumb) => c.category)).toEqual(["fetch", "navigation"]);
    expect(out?.breadcrumbs?.[0]?.data).toEqual({
      method: "GET",
      status_code: 500,
      url: "/api/v1/me/picks",
    });
    expect(out?.breadcrumbs?.[1]?.data).toEqual({ from: "/reset", to: "/home" });
    expect(out?.extra).toEqual({ note: "for <email>", nested: { ok: "kept" } });
    expect(out?.tags).toEqual({ route: "/my-picks" });
  });

  test("only the account's pseudonym goes as its user", () => {
    const event = loaded();
    event.user = { id: PSEUDONYM, email: EMAIL };
    expect(scrubEvent(event)?.user).toEqual({ id: PSEUDONYM });
  });

  test("a cut never leaves half a character", () => {
    const text = "x".repeat(299) + "😀 tail";
    const out = scrubText(text);
    expect(out.length).toBe(299);
    expect(/[\uD800-\uDBFF]$/.test(out)).toBe(false);
  });

  test("a frame whose file is the page keeps no query string", () => {
    const event = {
      exception: {
        values: [
          {
            type: "Error",
            value: "x",
            stacktrace: {
              frames: [
                {
                  filename: `https://predigolai.com/reset?token=${TOKEN}`,
                  abs_path: `https://predigolai.com/x?e=${EMAIL}`,
                },
              ],
            },
          },
        ],
      },
    } as unknown as ErrorEvent;
    const frame = scrubEvent(event)?.exception?.values?.[0]?.stacktrace?.frames?.[0];
    expect(frame).toEqual({
      filename: "https://predigolai.com/reset",
      abs_path: "https://predigolai.com/x",
    });
  });

  test("text and addresses", () => {
    expect(scrubText(`a '${NAME}' b ${EMAIL}\nnext`)).toBe("a <value> b <email>");
    expect(cleanUrl(`https://u:p@predigolai.com/a/b?x=${TOKEN}#h`)).toBe(
      "https://predigolai.com/a/b",
    );
    expect(cleanUrl(`/reset/${TOKEN}?q=1`)).toBe("/reset/<token>");
    expect(scrubBreadcrumb({ category: "console", message: "x" })).toBeNull();
  });

  test("the device: its width, and the installed app or a tab", () => {
    const tab = { innerWidth: 390.4, matchMedia: () => ({ matches: false }) as MediaQueryList };
    const app = { innerWidth: 412, matchMedia: () => ({ matches: true }) as MediaQueryList };
    expect(deviceTags(tab as unknown as Window)).toEqual({ viewport: "390", display: "browser" });
    expect(deviceTags(app as unknown as Window)).toEqual({ viewport: "412", display: "app" });
  });
});

type Recorded = {
  options?: Record<string, unknown>;
  users: unknown[];
  exceptions: unknown[][];
  messages: unknown[][];
};

function fakeSdk(rec: Recorded) {
  return {
    init: (options: Record<string, unknown>) => {
      rec.options = options;
    },
    setUser: (u: unknown) => rec.users.push(u),
    captureException: (...args: unknown[]) => rec.exceptions.push(args),
    captureMessage: (...args: unknown[]) => rec.messages.push(args),
    flush: () => Promise.resolve(true),
    breadcrumbsIntegration: (o: unknown) => ({ name: "Breadcrumbs", options: o }),
  } as unknown as typeof import("@sentry/browser");
}

const ON: MonitoringConfig = {
  enabled: true,
  dsn: "https://webkey@o0.ingest.example.invalid/2",
  environment: "production",
  tunnel: "/api/v1/monitoring/envelope",
};

describe("switching reporting on", () => {
  const g = globalThis as unknown as { window?: unknown };
  afterEach(() => {
    resetObservabilityForTests();
    delete g.window;
  });

  test("off while the server says so: the SDK is not even loaded", async () => {
    g.window = {
      innerWidth: 390,
      matchMedia: () => ({ matches: false }),
      location: { pathname: "/home" },
    };
    let loaded = false;
    const on = await startObservability(
      () => Promise.resolve({ ...ON, enabled: false, dsn: null }),
      () => {
        loaded = true;
        return Promise.resolve(fakeSdk({ users: [], exceptions: [], messages: [] }));
      },
    );
    expect(on).toBe(false);
    expect(loaded).toBe(false);
    reportApiFailure({
      status: 500,
      code: "internal",
      requestId: "a1",
      method: "GET",
      path: "/home",
    });
  });

  test("on: through the tunnel, without personal data, sessions, console lines or clicks", async () => {
    g.window = {
      innerWidth: 390,
      matchMedia: () => ({ matches: false }),
      location: { pathname: "/my-picks" },
    };
    const rec: Recorded = { users: [], exceptions: [], messages: [] };
    setObservedUser(PSEUDONYM);
    expect(
      await startObservability(
        () => Promise.resolve(ON),
        () => Promise.resolve(fakeSdk(rec)),
      ),
    ).toBe(true);
    const o = rec.options ?? {};
    expect(o["dsn"]).toBe(ON.dsn);
    expect(o["tunnel"]).toBe("/api/v1/monitoring/envelope");
    expect(o["sendClientReports"]).toBe(false);
    expect(o["dataCollection"]).toMatchObject({
      userInfo: false,
      cookies: false,
      httpHeaders: { request: { allow: ["user-agent"] }, response: false },
      httpBodies: [],
      urlQueryParams: false,
      stackFrameVariables: false,
    });
    expect(o["transportOptions"]).toEqual({ headers: { "x-requested-with": "predigol" } });
    expect(o["initialScope"]).toEqual({ tags: { viewport: "390", display: "browser" } });
    const integrations = o["integrations"] as (d: { name: string }[]) => { name: string }[];
    const names = integrations(
      [
        "GlobalHandlers",
        "BrowserSession",
        "Console",
        "CultureContext",
        "Breadcrumbs",
        "Dedupe",
      ].map((name) => ({
        name,
      })),
    ).map((i) => i.name);
    expect(names).toEqual(["GlobalHandlers", "Dedupe", "Breadcrumbs"]);
    expect(rec.users).toEqual([{ id: PSEUDONYM }]);

    reportApiFailure({
      status: 404,
      code: "not_found",
      requestId: "a0",
      method: "GET",
      path: "/x",
    });
    reportApiFailure({
      status: 503,
      code: "unavailable",
      requestId: "a1b2",
      method: "GET",
      path: "/me/picks?x=1",
    });
    expect(rec.messages).toHaveLength(1);
    const [message, context] = rec.messages[0] as [string, { tags: Record<string, string> }];
    expect(message).toBe("API 503 GET /me/picks");
    expect(context.tags).toEqual({
      request_id: "a1b2",
      status: "503",
      error_code: "unavailable",
      route: "/my-picks",
    });

    reportError(new Error("boom"), "root");
    expect(rec.exceptions).toHaveLength(1);

    setObservedUser(null);
    expect(rec.users.at(-1)).toBeNull();
    setObservedUser(`${EMAIL}`);
    expect(rec.users.at(-1)).toBeNull();
  });
});
