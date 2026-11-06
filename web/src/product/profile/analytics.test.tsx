/// <reference types="bun" />
/**
 * Plan de cierre UX, 1.2, without a browser: the usage statistics are an optional box of their own. The gate offers it
 * unticked beside the four it asks for - only to a reader who never answered it - and it never counts for opening the
 * gate; the Privacy block has a switch for it (off until the reader turns it on, with since when) and lists no row for
 * it; the sentence the page shows is the one the server stores; the console names it. Ticking it at the gate, turning it
 * on and off in the profile and the gate opening without it run in the browser (e2e/legal.spec.ts).
 */
import { afterAll, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale, t } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import type { ConsentPurpose, ConsentRecord, ConsentState } from "@/lib/api/v1/types_customer";
import { OptionalConsent } from "@/product/legal/OptionalConsent";
import { AnalyticsView } from "./AnalyticsSection";
import { analyticsOf, gateOptional, shownPurposes } from "./consents";

afterAll(() => setLocale("es"));

const BACKEND = join(import.meta.dir, "..", "..", "..", "..", "backend");

function serverSentence(lang: "es" | "en"): string {
  const doc = JSON.parse(
    readFileSync(join(BACKEND, "src", "fbi", "customer", "texts", lang, "privacy.json"), "utf8"),
  ) as { statements: Record<string, string> };
  return doc.statements["analytics"] ?? "";
}

function purpose(kind: ConsentPurpose["kind"], required: boolean): ConsentPurpose {
  return {
    kind,
    document: kind === "terms" || kind === "age_18" ? "terms" : "privacy",
    version: "2026-11-05-draft4",
    sha256: "a".repeat(64),
    statement: kind === "analytics" ? serverSentence("es") : `La frase de ${kind}`,
    required,
    withdrawable: kind === "privacy" || kind === "analytics",
    changes: null,
  };
}

function decision(granted: boolean, at = "2026-11-05T15:00:00Z"): ConsentRecord {
  return {
    kind: "analytics",
    granted,
    document: "privacy",
    version: "2026-11-05-draft4",
    sha256: "a".repeat(64),
    locale: "es",
    statement: serverSentence("es"),
    source: "profile",
    at,
  };
}

const FOUR = (["terms", "privacy", "age_18", "risk_notice"] as const).map((k) => purpose(k, true));

function state(over: Partial<ConsentState> = {}): ConsentState {
  return {
    gate: true,
    due: [],
    purposes: [...FOUR, purpose("analytics", false)],
    history: [],
    ...over,
  };
}

describe("what the gate offers beside the four", () => {
  test("the statistics box, only to a reader who never answered it", () => {
    expect(gateOptional(state())?.kind).toBe("analytics");
    expect(gateOptional(state({ history: [decision(true)] }))).toBeNull();
    expect(gateOptional(state({ history: [decision(false)] }))).toBeNull();
    expect(gateOptional(state({ purposes: FOUR }))).toBeNull();
    expect(gateOptional(undefined)).toBeNull();
  });

  test("it renders unticked, marked optional, with the server's own sentence and the policy it is on", () => {
    setLocale("es");
    const box = purpose("analytics", false);
    const out = renderToStaticMarkup(
      <OptionalConsent purpose={box} ticked={false} onToggle={() => undefined} />,
    );
    expect(out).toContain('data-testid="consent-optional"');
    expect(out).toContain('data-testid="consent-analytics"');
    expect(out).not.toContain("checked");
    expect(out).not.toContain("required");
    expect(out).toContain("Opcional");
    expect(out).toContain(box.statement.replaceAll("'", "&#x27;"));
    expect(out).toContain('href="/legal/privacy"');
    expect(out).toContain("min-h-11");
    const ticked = renderToStaticMarkup(
      <OptionalConsent purpose={box} ticked onToggle={() => undefined} />,
    );
    expect(ticked).toContain("checked");
  });
});

describe("the switch in the Privacy block", () => {
  test("the purpose as the consents say it, and no row for it in the list", () => {
    expect(analyticsOf(state())?.latest).toBeUndefined();
    expect(analyticsOf(state({ history: [decision(true)] }))?.latest?.granted).toBe(true);
    expect(analyticsOf(state({ purposes: FOUR }))).toBeNull();
    const kinds = (s: ConsentState) => shownPurposes(s).map((p) => p.kind);
    expect(kinds(state())).toEqual(["terms", "privacy", "age_18", "risk_notice"]);
    expect(kinds(state({ history: [decision(true)] }))).not.toContain("analytics");
  });

  test("off until the reader turns it on, and it says since when", () => {
    setLocale("es");
    const view = (s: ConsentState) => {
      const analytics = analyticsOf(s);
      if (!analytics) return "";
      return renderToStaticMarkup(
        <AnalyticsView
          analytics={analytics}
          busy={false}
          failure={null}
          onToggle={() => undefined}
        />,
      );
    };
    const fresh = view(state());
    expect(fresh).toContain('role="switch"');
    expect(fresh).toContain('aria-checked="false"');
    expect(fresh).not.toContain('data-testid="analytics-since"');
    const on = view(state({ history: [decision(true)] }));
    expect(on).toContain('aria-checked="true"');
    expect(on).toContain("Lo aceptaste el");
    const left = view(
      state({ history: [decision(false, "2026-11-06T15:00:00Z"), decision(true)] }),
    );
    expect(left).toContain('aria-checked="false"');
    expect(left).toContain("Lo retiraste el");
    expect(on).toContain("min-h-11");
  });
});

describe("the words", () => {
  test("the sentence the server stores says what it is and what it leaves out, in both languages", () => {
    const es = serverSentence("es").toLowerCase();
    expect(es).toContain("seudónimo");
    expect(es).toContain("sin mi correo");
    expect(es).toContain("retirarlo cuando quiera");
    const en = serverSentence("en").toLowerCase();
    expect(en).toContain("pseudonymous");
    expect(en).toContain("without my e-mail");
    expect(en).toContain("withdraw it whenever i like");
  });

  test("the gate, the switch and the console have their words in both languages", () => {
    for (const lang of ["es", "en"] as const) {
      setLocale(lang);
      for (const key of [
        "legal.gate.optional",
        "legal.gate.optionalHelp",
        "legal.privacy.analytics.title",
        "legal.privacy.analytics.help",
        "legal.privacy.analytics.since",
        "legal.privacy.analytics.left",
        "admin.customers.consentKinds.analytics",
      ])
        expect([lang, key, t(key) === key]).toEqual([lang, key, false]);
    }
    expect(CATALOGS.es["legal"]).toBeDefined();
  });
});
