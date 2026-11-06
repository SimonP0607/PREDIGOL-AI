/**
 * The communiqué form of the Admin Console (closing plan 4.3): the same rules the server holds (fbi.customer.announcements.
 * validate), so the owner sees what is wrong before sending it. The server decides; this only saves a round trip.
 */
import type { AnnouncementIn, AnnouncementKind } from "@/lib/api/v1/types_announcements";

export const KINDS: readonly AnnouncementKind[] = ["maintenance", "incident", "update", "general"];
export const CRITICAL_KINDS: readonly AnnouncementKind[] = ["maintenance", "incident"];
export const TITLE_MAX = 80;
export const BODY_MAX = 600;
export const EMAIL_MAX = 200;
export const MAX_DAYS = 90;
export const PHRASE = "PUBLICAR";

export interface Form {
  kind: AnnouncementKind;
  title_es: string;
  title_en: string;
  body_es: string;
  body_en: string;
  /** ``datetime-local`` values (the owner's own clock). */
  starts: string;
  ends: string;
  to_banner: boolean;
  to_updates: boolean;
  to_telegram: boolean;
  to_email: boolean;
  critical: boolean;
}

export type Problem = "texts" | "dates" | "destination" | "updates" | "critical" | "email";

/** ``YYYY-MM-DDTHH:mm`` in local time, the value a ``datetime-local`` input takes. */
export function localInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function emptyForm(now: Date = new Date()): Form {
  return {
    kind: "general",
    title_es: "",
    title_en: "",
    body_es: "",
    body_en: "",
    starts: localInput(now),
    ends: localInput(new Date(now.getTime() + 24 * 3600 * 1000)),
    to_banner: true,
    to_updates: false,
    to_telegram: false,
    to_email: false,
    critical: false,
  };
}

export function fromAnnouncement(a: AnnouncementIn): Form {
  return {
    kind: a.kind,
    title_es: a.title_es,
    title_en: a.title_en,
    body_es: a.body_es,
    body_en: a.body_en,
    starts: localInput(new Date(a.starts_at)),
    ends: localInput(new Date(a.ends_at)),
    to_banner: a.to_banner,
    to_updates: a.to_updates,
    to_telegram: a.to_telegram,
    to_email: a.to_email,
    critical: a.critical,
  };
}

/** What changing the kind leaves valid: «Novedades» only for an update, «crítico» and e-mail only for maintenance or incident. */
export function withKind(form: Form, kind: AnnouncementKind): Form {
  const critical = CRITICAL_KINDS.includes(kind) && form.critical;
  return {
    ...form,
    kind,
    to_updates: kind === "update" && form.to_updates,
    critical,
    to_email: critical && form.to_email,
  };
}

/** The first rule the form breaks, or null. */
export function problem(form: Form): Problem | null {
  const texts: [string, number][] = [
    [form.title_es, TITLE_MAX],
    [form.title_en, TITLE_MAX],
    [form.body_es, BODY_MAX],
    [form.body_en, BODY_MAX],
  ];
  if (texts.some(([s, max]) => s.trim().length < 3 || s.trim().length > max || /[<>]/.test(s)))
    return "texts";
  const start = Date.parse(form.starts);
  const end = Date.parse(form.ends);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return "dates";
  if (end - start > MAX_DAYS * 24 * 3600 * 1000) return "dates";
  if (!(form.to_banner || form.to_updates || form.to_telegram || form.to_email))
    return "destination";
  if (form.to_updates && form.kind !== "update") return "updates";
  if (form.critical && !CRITICAL_KINDS.includes(form.kind)) return "critical";
  if (form.to_email) {
    if (!form.critical) return "email";
    if (texts.some(([s]) => s.trim().length > EMAIL_MAX)) return "email";
  }
  return null;
}

export function toBody(form: Form): AnnouncementIn {
  return {
    kind: form.kind,
    title_es: form.title_es.trim(),
    title_en: form.title_en.trim(),
    body_es: form.body_es.trim(),
    body_en: form.body_en.trim(),
    starts_at: new Date(form.starts).toISOString(),
    ends_at: new Date(form.ends).toISOString(),
    to_banner: form.to_banner,
    to_updates: form.to_updates,
    to_telegram: form.to_telegram,
    to_email: form.to_email,
    critical: form.critical,
  };
}

/** Whether the typed phrase publishes: exactly the word, case and all (the server also trims). */
export function phraseOk(typed: string): boolean {
  return typed.trim() === PHRASE;
}
