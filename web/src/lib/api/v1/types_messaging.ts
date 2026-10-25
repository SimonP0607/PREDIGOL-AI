/**
 * The reader's notification preferences and the owner's view of the queue of messages (plan UX, A5).
 * Mirrors backend/src/fbi/api/contracts/messaging.py.
 */

export type MessageCategory =
  "account" | "security" | "membership" | "support" | "privacy" | "legal";
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
  category: MessageCategory;
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
