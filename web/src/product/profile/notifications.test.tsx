/// <reference types="bun" />
/**
 * Plan UX, A5: the profile's Notifications block and the console's queue of messages, as they read. The toggles,
 * the queue and the link a message leads to are checked in the browser (e2e/messaging.spec.ts).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import type {
  MessageCategory,
  NotificationPreferences,
  OutboxSummary,
} from "@/lib/api/v1/types_messaging";
import { QueueState } from "@/admin/MessagesPage";
import { STATUSES, templateName } from "@/admin/messages";
import { NotificationsView } from "./NotificationsPanel";

const CATEGORIES: readonly MessageCategory[] = [
  "account",
  "security",
  "membership",
  "support",
  "service",
  "privacy",
  "legal",
];
const LOCKED = new Set<MessageCategory>(["account", "security", "privacy", "legal"]);

function prefs(over: Partial<NotificationPreferences> = {}): NotificationPreferences {
  return {
    email: CATEGORIES.map((c) => ({ category: c, on: c !== "membership", locked: LOCKED.has(c) })),
    email_status: "ok",
    email_status_at: null,
    ...over,
  };
}

function view(p: NotificationPreferences): string {
  return renderToStaticMarkup(
    <NotificationsView prefs={p} busy={null} failure={null} onToggle={() => undefined} />,
  );
}

describe("the profile's notifications", () => {
  test("the optional categories are switches; the others say they always arrive", () => {
    setLocale("es");
    const html = view(prefs());
    expect(html.match(/role="switch"/g)?.length).toBe(3);
    expect(html).toContain('aria-checked="false"'); // membership, off
    expect(html).toContain('aria-checked="true"'); // support and service, on
    expect(html).toContain("Avisos del servicio");
    expect(html.match(/>Siempre</g)?.length).toBe(4);
    expect(html).not.toContain("notify-email-status");
  });

  test("a bounce or a complaint is said, in the reader's language", () => {
    setLocale("es");
    expect(
      view(prefs({ email_status: "bounced", email_status_at: "2026-10-27T15:00:00Z" })),
    ).toContain("Tu correo rebota");
    setLocale("en");
    expect(view(prefs({ email_status: "complained" }))).toContain(
      "You marked one of our e-mails as spam",
    );
    setLocale("es");
  });

  test("every category and state has its words in both languages", () => {
    for (const lang of ["es", "en"] as const) {
      const profile = CATALOGS[lang]["profile"] as Record<string, Record<string, unknown>>;
      const n = profile["notifications"] as Record<string, Record<string, string>>;
      for (const c of CATEGORIES) {
        expect(n["category"]?.[c]).toBeTruthy();
        expect(n["categoryHelp"]?.[c]).toBeTruthy();
      }
      for (const s of ["bounced", "complained"]) expect(n["status"]?.[s]).toBeTruthy();
    }
  });
});

describe("the console's queue", () => {
  const summary: OutboxSummary = {
    sending: false,
    provider: false,
    daily_cap: 90,
    sent_today: 0,
    counts: { queued: 2, sent: 0, failed: 0, bounced: 0, complained: 0, suppressed: 0 },
    messages: [],
  };

  test("says whether anything leaves, and why not", () => {
    setLocale("es");
    const off = renderToStaticMarkup(<QueueState summary={summary} />);
    expect(off).toContain("Envío apagado");
    expect(off).toContain("Falta la clave o el remitente de Resend.");
    expect(off).toContain("0 de 90");
    const on = renderToStaticMarkup(
      <QueueState summary={{ ...summary, sending: true, provider: true }} />,
    );
    expect(on).toContain("Envío encendido");
    expect(on).not.toContain("Falta la clave");
  });

  test("every status and template has its words, and an unknown template shows its name", () => {
    for (const lang of ["es", "en"] as const) {
      setLocale(lang);
      const admin = CATALOGS[lang]["admin"] as Record<string, Record<string, unknown>>;
      const messages = admin["messages"] as Record<string, Record<string, string>>;
      for (const s of STATUSES) expect(messages["status"]?.[s]).toBeTruthy();
      for (const name of ["privacy_request_received", "privacy_request_answered", "legal_change"])
        expect(templateName(name)).not.toBe(name);
      expect(templateName("a_template_from_tomorrow")).toBe("a_template_from_tomorrow");
    }
    setLocale("es");
  });
});
