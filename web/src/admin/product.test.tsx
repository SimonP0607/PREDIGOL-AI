/// <reference types="bun" />
/**
 * Plan UX, A6: the console's Product page says whether anything is measured and purged, and shows no global figure
 * below the minimum of readers. The figures themselves are checked in the browser (e2e/analytics.spec.ts).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import { EVENTS } from "@/lib/track";
import type { ProductOverview } from "@/lib/api/v1/types_events";
import { Breakdowns, SwitchState } from "./ProductPage";

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
  screens: [],
  markets: [],
  leagues: [],
  teams: [],
  lifecycle: null,
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

  test("what readers look at is listed by group, with its names in both languages and the floor said", () => {
    const o: ProductOverview = {
      ...base,
      status: "ok",
      screens: [{ key: "my_picks", label: null, events_30d: 40, subjects_30d: 22 }],
      markets: [{ key: "BTTS", label: null, events_30d: 31, subjects_30d: 21 }],
      leagues: [{ key: "7", label: "Liga BetPlay", events_30d: 90, subjects_30d: 25 }],
      teams: [],
    };
    setLocale("es");
    const es = renderToStaticMarkup(<Breakdowns o={o} />);
    expect(es).toContain("Mis picks");
    expect(es).toContain("Ambos marcan");
    expect(es).toContain("Liga BetPlay");
    expect(es).toContain("al menos 20 lectores");
    expect(es).toContain("Ninguna línea llega al mínimo de lectores.");
    setLocale("en");
    const en = renderToStaticMarkup(<Breakdowns o={o} />);
    expect(en).toContain("My picks");
    expect(en).toContain("Both teams score");
    expect(en).toContain("at least 20 readers");
    setLocale("es");
  });

  test("every screen group of the catalog and every market has its words in both languages", () => {
    const screens = (EVENTS.screen_viewed.props.screen as unknown as { enum: readonly string[] })
      .enum;
    for (const lang of ["es", "en"] as const) {
      const admin = CATALOGS[lang]["admin"] as Record<string, Record<string, unknown>>;
      const product = admin["product"] as Record<string, Record<string, string>>;
      for (const s of screens) expect(product["screen"]?.[s], `${lang} ${s}`).toBeTruthy();
      for (const m of ["1X2", "OU", "BTTS", "AH", "DC"])
        expect(product["market"]?.[m], `${lang} ${m}`).toBeTruthy();
    }
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
