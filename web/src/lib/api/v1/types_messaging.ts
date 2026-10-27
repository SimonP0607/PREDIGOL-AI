/**
 * The reader's notification preferences, the owner's view of the queue of messages (plan UX, A5) and the one-click
 * leaving of the weekly summary (B8). Mirrors backend/src/fbi/api/contracts/messaging.py.
 */

/** The account's e-mails: what the reader's choices speak of. */
export type MessageCategory =
  "account" | "security" | "membership" | "support" | "privacy" | "legal";
/** What the queue holds: the account's e-mails and commercial e-mail (plan UX, B8: the weekly summary, with consent). */
export type OutboxCategory = MessageCategory | "marketing";
export type EmailStatus = "ok" | "bounced" | "complained";
export type MessageStatus = "queued" | "sent" | "failed" | "bounced" | "complained" | "suppressed";

export interface EmailCategory {
  category: MessageCategory;
  on: boolean;
  /** Always sent: the account, its security, privacy requests and legal changes. */
  locked: boolean;
}

export interface NotificationPreferences {
  email: EmailCategory[];
  /** ok, or why e-mail stopped: a hard bounce or a complaint. */
  email_status: EmailStatus;
  email_status_at: string | null;
}

export interface NotificationPreferencesIn {
  email: Partial<Record<MessageCategory, boolean>>;
}

export interface OutboxMessage {
  id: number;
  user_id: number;
  user_email: string;
  category: OutboxCategory;
  template: string;
  locale: "es" | "en";
  status: MessageStatus;
  attempts: number;
  created_at: string;
  /** Only while queued. */
  next_attempt_at: string | null;
  sent_at: string | null;
  /** A short code: the provider's status and error name, never its text. */
  last_error: string | null;
}

export interface OutboxSummary {
  /** FBI_EMAIL_SEND: off, messages wait in the queue. */
  sending: boolean;
  /** The provider's key and sender are set (never shown). */
  provider: boolean;
  daily_cap: number;
  sent_today: number;
  /** Messages of the last 7 days by status. */
  counts: Record<MessageStatus, number>;
  messages: OutboxMessage[];
}

export interface OutboxPreview {
  subject: string;
  text: string;
  html: string;
  /** Where the message's button leads. */
  link: string | null;
}

/** The page the weekly summary's link opens (plan UX, B8). */
export interface UnsubscribeResult {
  /** True when this tap withdrew the consent; false when the reader had already left (nothing changed). */
  left: boolean;
}
