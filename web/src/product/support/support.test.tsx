/// <reference types="bun" />
/**
 * Help and support on the page (plan UX, A14), without a browser: what a ticket carries besides the reader's words (the
 * path without its query, a one-use link's page by its name, the last error's reference only when recent, the device,
 * the installed app, the match) and never anything else; the help centre's 20 to 30 questions in both languages and the
 * accent-blind search; the categories in the order and with the words of section 32; every error offering «Reportar un
 * problema» once the sheet is available. The browser half is e2e/support.spec.ts.
 */
import { afterAll, afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { LiveApiError, lastApiError, resetLastApiError, v1 } from "@/lib/api/v1/client";
import { setLocale, t } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import { ErrorState } from "@/product/shared/States";
import { FAQ_GROUPS, FAQ_IDS, FAQ_LINKS, faqAnchor, faqMatches } from "@/product/help/faq";
import { buildContext, deviceClass, routeOf } from "./context";
import { CATEGORIES, MAX_OPEN, MAX_TEXT, ReportContext } from "./report";

afterAll(() => setLocale("es"));

const realFetch = globalThis.fetch;
const scope = globalThis as { window?: unknown };
afterEach(() => {
  globalThis.fetch = realFetch;
  delete scope.window;
  resetLastApiError();
});

/** The API answers ``status`` with ``body`` - in a page of our own origin, as the client expects. */
function answering(status: number, body: unknown): void {
  scope.window = { location: { origin: "https://predigol.test" }, dispatchEvent: () => true };
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    })) as unknown as typeof fetch;
}

function fakeWindow(pathname: string, width = 390, standalone = false) {
  return {
    innerWidth: width,
    location: { pathname },
    matchMedia: (q: string) =>
      ({ matches: standalone && q.includes("standalone") }) as MediaQueryList,
  };
}

describe("the context of a ticket", () => {
  test("the device's class by the product's breakpoints", () => {
    expect([320, 639, 640, 1023, 1024, 1440].map(deviceClass)).toEqual([
      "phone",
      "phone",
      "tablet",
      "tablet",
      "desktop",
      "desktop",
    ]);
  });

  test("the path without its query or fragment, and a one-use link's page by its name alone", () => {
    expect(routeOf("/matches/1414")).toBe("/matches/1414");
    expect(routeOf("/reset-password?token=abc")).toBe("/reset-password");
    expect(routeOf("/reset-password/abc123")).toBe("/reset-password");
    expect(routeOf("/activate#token=x")).toBe("/activate");
    expect(routeOf("/unlock/zz")).toBe("/unlock");
    expect(routeOf("/unsubscribe#t=1x20000xabc")).toBe("/unsubscribe");
    expect(routeOf("/legal/t%C3%A9rminos")).toBe("/legal/tC3A9rminos");
    expect(routeOf("matches")).toBeNull();
    expect(routeOf(`/${"a".repeat(300)}`)?.length).toBe(200);
  });

  test("what goes: the screen, the device, the installed app, the version, the match - nothing else", () => {
    const c = buildContext({ matchId: 1414 }, fakeWindow("/matches/1414", 390, true));
    expect(c).toEqual({
      device: "phone",
      route: "/matches/1414",
      web_version: "dev",
      pwa: true,
      match_id: 1414,
    });
    const desk = buildContext({ matchId: 0 }, fakeWindow("/home", 1440));
    expect(desk).toEqual({ device: "desktop", route: "/home", web_version: "dev", pwa: false });
    expect(Object.keys(buildContext({}, fakeWindow("/picks"))).sort()).toEqual([
      "device",
      "pwa",
      "route",
      "web_version",
    ]);
  });

  test("the error's own reference, else the last one the page met in the last half hour", async () => {
    expect(buildContext({ requestId: "abc123def456" }, fakeWindow("/home")).request_id).toBe(
      "abc123def456",
    );
    expect(
      buildContext({ requestId: "not-an-id!" }, fakeWindow("/home")).request_id,
    ).toBeUndefined();
    answering(500, { error: { code: "internal" }, request_id: "a1b2c3d4e5f6" });
    await expect(v1.mySupport()).rejects.toBeInstanceOf(LiveApiError);
    expect(lastApiError()).toBe("a1b2c3d4e5f6");
    expect(buildContext({}, fakeWindow("/home")).request_id).toBe("a1b2c3d4e5f6");
    expect(lastApiError(Date.now() + 31 * 60 * 1000)).toBeNull();
  });

  test("a sign-in that is simply over is not «the last error»", async () => {
    answering(401, { error: { code: "unauthenticated" }, request_id: "zz9" });
    await expect(v1.mySupport()).rejects.toBeInstanceOf(LiveApiError);
    expect(lastApiError()).toBeNull();
  });
});

describe("the help centre", () => {
  test("20 to 30 questions in the plan's eight groups, each with its words in both languages", () => {
    expect(FAQ_IDS.length).toBeGreaterThanOrEqual(20);
    expect(FAQ_IDS.length).toBeLessThanOrEqual(30);
    expect(new Set(FAQ_IDS).size).toBe(FAQ_IDS.length);
    expect(FAQ_GROUPS.map((g) => g.id)).toEqual([
      "start",
      "account",
      "membership",
      "picks",
      "settlement",
      "notices",
      "privacy",
      "responsible",
    ]);
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const id of FAQ_IDS) {
        expect(t(`support.faq.${id}.q`)).not.toBe(`support.faq.${id}.q`);
        expect(t(`support.faq.${id}.a`).length).toBeGreaterThan(60);
      }
      for (const g of FAQ_GROUPS)
        expect(t(`support.help.groups.${g.id}`)).not.toContain("support.");
    }
    setLocale("es");
  });

  test("the search ignores accents and case and needs every word", () => {
    setLocale("es");
    expect(FAQ_IDS.filter((id) => faqMatches(id, "contrasena"))).toContain("cant_sign_in");
    expect(FAQ_IDS.filter((id) => faqMatches(id, "RENUEVO membresía"))).toEqual(["renew"]);
    expect(FAQ_IDS.filter((id) => faqMatches(id, "combinada riesgo"))).toEqual(["parlay"]);
    expect(FAQ_IDS.filter((id) => faqMatches(id, "zzzz"))).toEqual([]);
    expect(FAQ_IDS.filter((id) => faqMatches(id, "  "))).toHaveLength(FAQ_IDS.length);
    setLocale("en");
    expect(FAQ_IDS.filter((id) => faqMatches(id, "password"))).toContain("cant_sign_in");
    setLocale("es");
    expect(faqAnchor("renew")).toBe("faq-renew");
  });

  test("an answer leads only to pages that exist", () => {
    const pages = [
      /^\/help\/glossary(#term-[A-Za-z]+)?$/,
      /^\/profile(#(membership|notifications|privacy))?$/,
      /^\/my-picks$/,
      /^\/legal\/responsible-gaming$/,
    ];
    for (const [id, link] of Object.entries(FAQ_LINKS)) {
      expect(pages.some((p) => p.test(link.to))).toBe(true);
      expect(t(`support.help.go.${link.label}`)).not.toContain("support.");
      expect(FAQ_IDS).toContain(id as (typeof FAQ_IDS)[number]);
    }
  });
});

describe("the sheet's categories", () => {
  test("the order and the limits of section 32, with their words in both languages", () => {
    expect(CATEGORIES).toEqual([
      "access",
      "account",
      "technical",
      "wrong_data",
      "suggestion",
      "complaint",
    ]);
    expect([MAX_TEXT, MAX_OPEN]).toEqual([2000, 3]);
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const c of CATEGORIES) {
        expect(t(`support.report.category.${c}.label`)).not.toContain("support.");
        expect(t(`support.report.category.${c}.hint`)).not.toContain("support.");
        expect(t(`support.admin.category.${c}`)).not.toContain("support.");
      }
    }
    setLocale("es");
    expect(t("support.report.category.access.hint")).toContain("hoy");
  });

  test("every refusal of the support routes has the reader's words", () => {
    const codes = [
      "too_many_open",
      "too_many_tickets",
      "ticket_closed",
      "thread_full",
      "not_closed",
      "already_rated",
      "invalid_context",
      "use_privacy_request",
      "privacy_request",
      "not_available",
      "invalid_effort",
      "unknown_category",
    ];
    for (const locale of ["es", "en"] as const) {
      const errors = (CATALOGS[locale]["errors"] as { code: Record<string, string> }).code;
      for (const code of codes) expect(errors[code]).toBeTruthy();
    }
  });
});

describe("an error offers «Reportar un problema»", () => {
  test("once the sheet is available, with the error's own reference; never on the owner's console", () => {
    setLocale("es");
    const error = new LiveApiError("boom", 500, "internal", "rid123");
    const offered: unknown[] = [];
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <ReportContext.Provider value={{ available: true, open: (o) => offered.push(o) }}>
          <ErrorState error={error} />
        </ReportContext.Provider>
      </QueryClientProvider>,
    );
    expect(html).toContain('data-testid="error-report"');
    expect(html).toContain("Reportar un problema");
    const none = renderToStaticMarkup(<ErrorState error={error} />);
    expect(none).not.toContain("error-report");
  });
});
