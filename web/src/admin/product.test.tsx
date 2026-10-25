/// <reference types="bun" />
/**
 * Plan UX, A6: the console's Product page says whether anything is measured and purged, and shows no global figure
 * below the minimum of readers. The figures themselves are checked in the browser (e2e/analytics.spec.ts).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import type { ProductOverview } from "@/lib/api/v1/types_events";
import { SwitchState } from "./ProductPage";

const base: ProductOverview = {
  mode: "off",
  purge: "dry",
  min_subjects: 20,
  status: "insufficient_data",
  active_30d: 3,
  active: {},
  usage: [],
  funnel: [],
  devices: {},
  days_active_per_week: null,
  errors_per_active: null,
  dau_mau: null,
};

describe("the console's Product page", () => {
  test("says the switch and the purge, in the owner's language", () => {
    setLocale("es");
    const off = renderToStaticMarkup(<SwitchState o={base} />);
    expect(off).toContain("Medición apagada");
    expect(off).toContain("Purga en ensayo");
    setLocale("en");
    expect(
      renderToStaticMarkup(<SwitchState o={{ ...base, mode: "on", purge: "on" }} />),
    ).toContain("Measuring on");
    setLocale("es");
  });

  test("every mode, purge, step and device has its words in both languages", () => {
    for (const lang of ["es", "en"] as const) {
      const admin = CATALOGS[lang]["admin"] as Record<string, Record<string, unknown>>;
      const product = admin["product"] as Record<string, Record<string, string>>;
      for (const m of ["off", "on", "consent"]) expect(product["mode"]?.[m]).toBeTruthy();
      for (const p of ["off", "dry", "on"]) expect(product["purge"]?.[p]).toBeTruthy();
      for (const s of ["activated", "onboarding_started", "onboarding_completed", "first_value"])
        expect(product["step"]?.[s]).toBeTruthy();
      for (const d of ["phone", "tablet", "desktop", "unknown"])
        expect(product["device"]?.[d]).toBeTruthy();
    }
  });
});
