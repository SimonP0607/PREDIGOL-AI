/**
 * The help centre's questions (plan UX, A14; section 32): 25 in ES and EN, grouped as the plan lists them - getting
 * started, account and access, membership and payments, picks and parlays, my picks and settlement, notifications and
 * installing, privacy and data, responsible gambling. The words live in the catalogues (support.faq.<id>.q / .a);
 * some answers lead on to the page that does what they describe. Two answer for the notices on the devices (plan UX,
 * B7) and are shown only while the owner made them available (FAQ_NEEDS_PUSH): never a question about something a
 * reader cannot use.
 */
import { t } from "@/lib/i18n";
import { fold } from "@/lib/glossary";

export const FAQ_GROUPS = [
  { id: "start", items: ["what_is", "no_pick", "forecast_pick", "guarantee"] },
  { id: "account", items: ["cant_sign_in", "two_steps", "language_zone"] },
  { id: "membership", items: ["renew", "membership_ends", "trial"] },
  { id: "picks", items: ["what_pick", "own_selection", "parlay"] },
  { id: "settlement", items: ["when_settled", "void_half", "units"] },
  { id: "notices", items: ["emails", "push", "push_iphone", "install"] },
  { id: "privacy", items: ["my_data", "delete_account", "report_context"] },
  { id: "responsible", items: ["should_bet", "get_help"] },
] as const;

export type FaqGroup = (typeof FAQ_GROUPS)[number]["id"];
export type FaqId = (typeof FAQ_GROUPS)[number]["items"][number];

export const FAQ_IDS: readonly FaqId[] = FAQ_GROUPS.flatMap((g) => [...g.items]);

/** Where an answer leads on: the page that does what it describes (a label key of support.help.go). */
export const FAQ_LINKS: Partial<Record<FaqId, { to: string; label: string }>> = {
  forecast_pick: { to: "/help/glossary", label: "glossary" },
  two_steps: { to: "/profile", label: "profile" },
  language_zone: { to: "/profile", label: "profile" },
  renew: { to: "/profile#membership", label: "membership" },
  membership_ends: { to: "/profile#membership", label: "membership" },
  trial: { to: "/profile#membership", label: "membership" },
  void_half: { to: "/help/glossary#term-halfWon", label: "glossary" },
  when_settled: { to: "/my-picks", label: "myPicks" },
  emails: { to: "/profile#notifications", label: "notifications" },
  push: { to: "/profile#notifications", label: "notifications" },
  push_iphone: { to: "/profile#notifications", label: "notifications" },
  my_data: { to: "/profile#privacy", label: "privacy" },
  delete_account: { to: "/profile#privacy", label: "privacy" },
  should_bet: { to: "/legal/responsible-gaming", label: "responsible" },
  get_help: { to: "/legal/responsible-gaming", label: "responsible" },
};

/** The questions about the notices on the devices: shown only while notices are available (GET /me/push). */
export const FAQ_NEEDS_PUSH: ReadonlySet<FaqId> = new Set<FaqId>(["push", "push_iphone"]);

export function faqQuestion(id: FaqId): string {
  return t(`support.faq.${id}.q`);
}

export function faqAnswer(id: FaqId): string {
  return t(`support.faq.${id}.a`);
}

/** Whether a question answers a search: its question or its answer contain every word (without accents or case). */
export function faqMatches(id: FaqId, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = fold(`${faqQuestion(id)} ${faqAnswer(id)}`);
  return words.every((w) => haystack.includes(w));
}

/** The anchor of a question: /help#faq-renew opens it. */
export function faqAnchor(id: FaqId): string {
  return `faq-${id}`;
}
