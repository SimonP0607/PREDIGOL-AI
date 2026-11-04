/// <reference types="bun" />
/**
 * Plan UX, A4: the legal texts' addresses, the notice that links to them on every screen, and the server's own words
 * in the boxes. The gate, the profile's privacy block and the pages at 320 px are checked in the browser
 * (e2e/legal.spec.ts).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import { Disclaimer } from "@/components/system/Disclaimer";
import { dayOf, documentOfSlug, isLegalPath, LEGAL_DOCUMENTS, legalPath } from "./links";

describe("the legal texts' addresses", () => {
  test("a hyphen in the address, an underscore in the API, and nothing else is a text", () => {
    expect(legalPath("terms")).toBe("/legal/terms");
    expect(legalPath("responsible_gaming")).toBe("/legal/responsible-gaming");
    expect(legalPath("privacy", "derechos")).toBe("/legal/privacy#derechos");
    for (const d of LEGAL_DOCUMENTS) expect(documentOfSlug(legalPath(d).slice(7))).toBe(d);
    expect(documentOfSlug("responsible_gaming")).toBeNull();
    expect(documentOfSlug("cookies")).toBeNull();
    expect(isLegalPath("/legal/terms")).toBe(true);
    expect(isLegalPath("/legally")).toBe(false);
  });

  test("a version's date is the day written, in any time zone", () => {
    setLocale("es");
    expect(dayOf("2026-10-25")).toContain("25");
    expect(dayOf("2026-10-25")).toContain("2026");
    expect(dayOf("2026-01-01T00:00:00")).toContain("1");
  });
});

describe("the notice on every screen", () => {
  test("says no result is guaranteed and links the three texts, in the reader's language", () => {
    setLocale("es");
    const es = renderToStaticMarkup(<Disclaimer />);
    expect(es).toContain("no garantiza resultados");
    expect(es).toContain('href="/legal/terms"');
    expect(es).toContain('href="/legal/privacy"');
    expect(es).toContain('href="/legal/responsible-gaming"');
    expect(es).toContain(">Juego responsable</a>");
    setLocale("en");
    const en = renderToStaticMarkup(<Disclaimer />);
    expect(en).toContain(">Responsible gaming</a>");
    expect(en).toContain('aria-label="Legal texts"');
    setLocale("es");
  });
});

describe("the legal catalog", () => {
  test("every document has its name and every request kind and status its words, in both languages", () => {
    for (const lang of ["es", "en"] as const) {
      const legal = CATALOGS[lang]["legal"] as Record<string, Record<string, unknown>>;
      for (const d of LEGAL_DOCUMENTS) expect(typeof legal["doc"]?.[d]).toBe("string");
      const privacy = legal["privacy"] as Record<string, Record<string, string>>;
      for (const k of ["privacy_query", "privacy_claim", "privacy_deletion"])
        expect(privacy["kind"]?.[k]).toBeTruthy();
      for (const s of ["open", "answered", "closed"]) expect(privacy["status"]?.[s]).toBeTruthy();
      for (const s of ["gate", "profile", "activation"])
        expect(privacy["source"]?.[s]).toBeTruthy();
    }
  });
});
