/**
 * The reader's account centre in one read (plan UX, B1; section 21; backend fbi/api/contracts/account.py): what each of
 * the profile's eight blocks says while folded. Each block reads its details when it opens.
 */
import type { Iso } from "./types";
import type { MembershipSummary } from "./types_membership";
import type { EmailStatus } from "./types_messaging";

export interface AccountBlock {
  /** The alias the reader chose (PATCH /auth/me/preferences changes it). */
  display_name: string;
  email: string;
  /** When the account was made; null only for a session whose account row cannot be read. */
  created_at: Iso | null;
  /** The owner's account: «Administrador», never a role's code. */
  admin: boolean;
}

export interface RegionBlock {
  language: string;
  /** IANA name; the page writes it in words. */
  timezone: string;
}

export interface FootballBlock {
  /** Leagues followed: the reader's own, or the suggested ones while none is chosen. */
  leagues: number;
  teams: number;
  /** Nothing chosen yet: the suggested ones for Colombia (A13). */
  suggested: boolean;
}

export interface NotificationsBlock {
  /** E-mail categories on, the mandatory ones included. */
  email_on: number;
  email_total: number;
  email_status: EmailStatus;
  /** Whether PrediGol sends e-mail at all now (FBI_EMAIL_SEND). */
  sending: boolean;
}

export interface PrivacyBlock {
  /** Purposes owed while the consent gate is on. */
  consents_due: string[];
  /** The reader's latest consent decision. */
  consents_at: Iso | null;
  /** Privacy requests still open. */
  open_requests: number;
  /** The nearest legal deadline among them (a date, YYYY-MM-DD). */
  next_deadline: string | null;
}

export interface SecurityBlock {
  mfa_enabled: boolean;
  /** Sessions open now, this one included. */
  sessions: number;
  last_sign_in_at: Iso | null;
  password_changed_at: Iso | null;
}

export interface HelpBlock {
  /** Messages waiting for PrediGol's answer. */
  waiting: number;
  /** Answered and not yet closed. */
  answered: number;
  /** Whether Ayuda shows a WhatsApp number (P7). */
  whatsapp: boolean;
  /** Whether the reader can write to PrediGol (FBI_SUPPORT). */
  support: boolean;
}

export interface AccountSummary {
  account: AccountBlock;
  region: RegionBlock;
  football: FootballBlock;
  notifications: NotificationsBlock;
  privacy: PrivacyBlock;
  security: SecurityBlock;
  /** null for the owner's accounts (no membership). */
  membership: MembershipSummary | null;
  help: HelpBlock;
}
