/// <reference types="bun" />
/**
 * Plan UX, A8: the membership in the reader's words - the card's sentence and the top notice for each state, with
 * the date in the reader's time zone - and the pages a limited account still opens.
 */
import { afterAll, describe, expect, test } from "bun:test";
import type { MembershipSummary } from "@/lib/api/v1/types_membership";
import { setLocale } from "@/lib/i18n";
import { setTimeZone } from "@/lib/time";
import {
  bannerText,
  isLimitedPath,
  membershipLine,
  showsDaysLeft,
  whatsappLink,
} from "./membership";

function m(over: Partial<MembershipSummary>): MembershipSummary {
  return {
    state: "trial",
    ends_at: "2026-11-07T15:00:00Z",
    grace_until: "2026-11-10T15:00:00Z",
    kind: "trial",
    days_left: 13,
    limited: false,
    will_not_renew: false,
    ...over,
  };
}

describe("the membership in words", () => {
  afterAll(() => setLocale("es"));

  test("the card says each state with its date, in the reader's zone", () => {
    setLocale("es");
    setTimeZone("America/Bogota");
    expect(membershipLine(m({}))).toBe("En prueba hasta el sábado, 7 de noviembre.");
    expect(membershipLine(m({ state: "active", kind: "paid" }))).toContain(
      "Activa hasta el sábado, 7 de noviembre",
    );
    expect(membershipLine(m({ state: "expiring", kind: "trial" }))).toContain("Tu prueba termina");
    expect(membershipLine(m({ state: "expiring", kind: "paid" }))).toContain(
      "Tu membresía termina",
    );
    expect(membershipLine(m({ state: "grace" }))).toContain("martes, 10 de noviembre");
    expect(membershipLine(m({ state: "renewed", kind: "paid" }))).toContain("Renovada hasta");
    expect(membershipLine(m({ state: "expired" }))).toContain("Tus datos siguen aquí");
    expect(membershipLine(m({ state: "suspended" }))).toContain("suspendida");
    expect(membershipLine(m({ state: "none", ends_at: null }))).toContain("todavía no tiene");
    setLocale("en");
    expect(membershipLine(m({}))).toBe("On trial until Saturday 7 November.");
  });

  test("the top notice: from the warning, the eve, the grace, and the limit - nothing while it runs", () => {
    setLocale("es");
    for (const state of ["trial", "active", "renewed", "none"] as const) {
      expect(bannerText(m({ state })), state).toBeNull();
    }
    expect(bannerText(m({ state: "expiring", kind: "trial", days_left: 3 }))).toContain(
      "Tu prueba termina",
    );
    expect(bannerText(m({ state: "expiring", kind: "paid", days_left: 1 }))).toBe(
      "Mañana termina tu membresía.",
    );
    expect(bannerText(m({ state: "grace" }))).toContain("hasta el martes, 10 de noviembre");
    expect(bannerText(m({ state: "expired", limited: true }))).toContain("Acceso limitado");
    expect(bannerText(m({ state: "expired", limited: false }))).not.toContain("Acceso limitado");
    expect(bannerText(m({ state: "suspended", limited: true }))).toContain("suspendida");
  });

  test("days left are said only while the cover runs", () => {
    expect(showsDaysLeft(m({}))).toBe(true);
    expect(showsDaysLeft(m({ state: "grace", days_left: 0 }))).toBe(false);
    expect(showsDaysLeft(m({ state: "none", ends_at: null, days_left: null }))).toBe(false);
  });

  test("a WhatsApp chat with the number and a first line", () => {
    expect(whatsappLink("+57 300 123 4567", "Hola, quiero renovar")).toBe(
      "https://wa.me/573001234567?text=Hola%2C%20quiero%20renovar",
    );
  });
});

describe("what a limited account still opens", () => {
  test("its profile, its saved picks, the help and the legal texts - nothing else of the product", () => {
    for (const path of ["/profile", "/my-picks/", "/help", "/help/glossary", "/legal/terms"]) {
      expect(isLimitedPath(path), path).toBe(true);
    }
    for (const path of [
      "/",
      "/home",
      "/picks",
      "/matches/10",
      "/parlays",
      "/odds",
      "/live",
      "/profiles",
    ]) {
      expect(isLimitedPath(path), path).toBe(false);
    }
  });
});
