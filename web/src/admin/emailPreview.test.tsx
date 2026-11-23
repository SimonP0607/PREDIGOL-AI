/// <reference types="bun" />
/**
 * Plan de correcciones UX, AP-M02: the e-mail preview's frame is isolated (no script, no forms, no same-origin access), the
 * language and the width are the owner's choice, and each answer to «Enviarme una prueba» says what happened.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { LiveApiError } from "@/lib/api/v1/client";
import { setLocale } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import { EmailFrame, testMessage } from "./EmailPreview";
import { EMAIL_PREVIEW_CATALOG, t } from "./emailText";
import { PREVIEW_TEMPLATES, templateName } from "./messages";

describe("the e-mail preview", () => {
  test("the frame forbids everything: an empty sandbox, no referrer, the width of the chosen device", () => {
    const phone = renderToStaticMarkup(<EmailFrame html="<p>hola</p>" title="x" device="phone" />);
    expect(phone).toContain('sandbox=""');
    expect(phone).toContain('referrerPolicy="no-referrer"');
    expect(phone).toContain("width:375px");
    const desktop = renderToStaticMarkup(<EmailFrame html="<p>hola</p>" title="x" />);
    expect(desktop).toContain("width:640px");
    expect(desktop).not.toContain("allow-scripts");
    expect(desktop).not.toContain("allow-same-origin");
  });

  test("every previewable template is listed once", () => {
    expect(new Set(PREVIEW_TEMPLATES).size).toBe(PREVIEW_TEMPLATES.length);
    expect(PREVIEW_TEMPLATES.length).toBe(26);
    for (const name of PREVIEW_TEMPLATES) expect(templateName(name).length).toBeGreaterThan(0);
  });

  test("the answers to a test say what happened, in both languages", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      const limit = testMessage(new LiveApiError("x", 429, "test_limit", null));
      const refused = testMessage(new LiveApiError("x", 422, "test_unavailable", null));
      const other = testMessage(new Error("boom"));
      expect(new Set([limit, refused, other]).size).toBe(3);
      expect(limit).toBe(t("emailpreview.limit"));
    }
    setLocale("es");
  });

  test("the words exist in Spanish and English with the same keys", () => {
    const flat = (o: Record<string, unknown>): string[] => Object.keys(o).sort();
    expect(flat(EMAIL_PREVIEW_CATALOG.es)).toEqual(flat(EMAIL_PREVIEW_CATALOG.en));
    expect(CATALOGS.es).toBeDefined();
  });
});
