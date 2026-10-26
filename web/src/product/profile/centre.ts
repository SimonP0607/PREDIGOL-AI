/**
 * The account centre (plan UX, B1; section 21): the profile's eight blocks and the one line each says while folded,
 * in the reader's words - pure, so every line is tested without a page. The counts come from GET /me/account; never an
 * internal word (a role, a shadow state, a set's name).
 */
import type { AccountSummary } from "@/lib/api/v1/types_account";
import type { MembershipSummary } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { LOCALE_NAMES } from "@/lib/i18n/catalogs";
import { formatDateLong, zoneName } from "@/lib/time";
import { membershipLine } from "@/product/membership/membership";

/** The eight blocks, in the plan's order. Each is also the address of its block: /profile#privacy opens Privacidad. */
export const BLOCKS = [
  "account",
  "football",
  "region",
  "notifications",
  "privacy",
  "security",
  "membership",
  "help",
] as const;
export type BlockKey = (typeof BLOCKS)[number];

/** Addresses that already led into the profile before B1 (e-mails, Home, the console) and the block that holds them. */
const ALIASES: Record<string, BlockKey> = {
  language: "region",
  timezone: "region",
  sessions: "security",
  mfa: "security",
  password: "security",
};

/** The block an address names (#privacy, #football, #language), or null. */
export function blockOfHash(hash: string): BlockKey | null {
  const id = hash.replace(/^#/, "");
  if ((BLOCKS as readonly string[]).includes(id)) return id as BlockKey;
  return ALIASES[id] ?? null;
}

function day(iso: string | null): string {
  return iso ? formatDateLong(iso) : "";
}

/** The account's state in words: «Activa», «En prueba hasta el 7 de noviembre», «Administrador». */
export function accountState(admin: boolean, m: MembershipSummary | null): string {
  if (admin) return t("common.roleAdmin");
  if (!m) return t("profile.centre.state.active");
  switch (m.state) {
    case "none":
    case "active":
      return m.state === "active" && m.ends_at
        ? t("profile.centre.state.activeUntil", { date: day(m.ends_at) })
        : t("profile.centre.state.active");
    case "renewed":
      return t("profile.centre.state.activeUntil", { date: day(m.ends_at) });
    case "trial":
      return t("profile.centre.state.trial", { date: day(m.ends_at) });
    case "expiring":
      return m.kind === "trial"
        ? t("profile.centre.state.expiringTrial", { date: day(m.ends_at) })
        : t("profile.centre.state.expiring", { date: day(m.ends_at) });
    case "grace":
      return t("profile.centre.state.grace", { date: day(m.grace_until) });
    case "expired":
      return t("profile.centre.state.expired");
    case "suspended":
      return t("profile.centre.state.suspended");
  }
}

/** The line a folded block says. */
export function blockSummary(key: BlockKey, a: AccountSummary): string {
  switch (key) {
    case "account":
      return t("profile.centre.summary.account", {
        name: a.account.display_name,
        state: accountState(a.account.admin, a.membership),
      });
    case "football": {
      const { leagues, teams, suggested } = a.football;
      if (suggested)
        return t("profile.centre.summary.footballSuggested", { count: leagues, n: leagues });
      if (leagues === 0 && teams === 0) return t("profile.centre.summary.footballNone");
      const parts = [
        leagues > 0 ? t("profile.centre.summary.leagues", { count: leagues, n: leagues }) : null,
        teams > 0 ? t("profile.centre.summary.teams", { count: teams, n: teams }) : null,
      ].filter((p): p is string => p !== null);
      return parts.join(" · ");
    }
    case "region": {
      const language =
        LOCALE_NAMES[a.region.language as keyof typeof LOCALE_NAMES] ?? a.region.language;
      return `${language} · ${zoneName(a.region.timezone)}`;
    }
    case "notifications": {
      const n = a.notifications;
      if (n.email_status === "bounced") return t("profile.centre.summary.emailBounced");
      if (n.email_status === "complained") return t("profile.centre.summary.emailComplained");
      return t("profile.centre.summary.email", { on: n.email_on, total: n.email_total });
    }
    case "privacy": {
      const p = a.privacy;
      if (p.consents_due.length > 0)
        return t("profile.centre.summary.consentsDue", {
          count: p.consents_due.length,
          n: p.consents_due.length,
        });
      if (p.open_requests > 0)
        return p.next_deadline
          ? t("profile.centre.summary.requestsUntil", {
              count: p.open_requests,
              n: p.open_requests,
              date: day(p.next_deadline),
            })
          : t("profile.centre.summary.requests", { count: p.open_requests, n: p.open_requests });
      return t("profile.centre.summary.privacyOk");
    }
    case "security": {
      const s = a.security;
      const mfa = s.mfa_enabled
        ? t("profile.centre.summary.mfaOn")
        : t("profile.centre.summary.mfaOff");
      return `${mfa} · ${t("profile.centre.summary.sessions", { count: s.sessions, n: s.sessions })}`;
    }
    case "membership":
      return a.membership ? membershipLine(a.membership) : t("profile.centre.summary.noMembership");
    case "help": {
      const h = a.help;
      if (h.answered > 0)
        return t("profile.centre.summary.answered", { count: h.answered, n: h.answered });
      if (h.waiting > 0)
        return t("profile.centre.summary.waiting", { count: h.waiting, n: h.waiting });
      return t("profile.centre.summary.helpNone");
    }
  }
}

/** From 1024 px (the desk's top bar, plan UX A15) the blocks start open; under it, folded. */
export const DESK_QUERY = "(min-width: 64rem)";

/** Whether the blocks start open on this screen. Read on the client: the profile renders only once signed in. */
export function startsOpen(
  win: Pick<Window, "matchMedia"> | undefined = globalThis.window,
): boolean {
  try {
    return Boolean(win?.matchMedia(DESK_QUERY).matches);
  } catch {
    return false;
  }
}

export const ALIAS_MAX = 80;

/** The alias as the server will keep it, or the reason it cannot be: never empty, never longer than 80. */
export function aliasProblem(raw: string): "empty" | "long" | null {
  const value = raw.trim();
  if (!value) return "empty";
  if (value.length > ALIAS_MAX) return "long";
  return null;
}

/** What the reader's messages wait for, in words; null without open messages. */
export function messagesHint(summary: AccountSummary | undefined): string | null {
  const help = summary?.help;
  if (!help) return null;
  if (help.answered > 0)
    return t("profile.centre.summary.answered", { count: help.answered, n: help.answered });
  if (help.waiting > 0)
    return t("profile.centre.summary.waiting", { count: help.waiting, n: help.waiting });
  return null;
}
