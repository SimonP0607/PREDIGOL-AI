/**
 * A reader's questions to PrediGol and the owner's inbox (plan UX, A14), as the API returns them. Mirrors
 * fbi.api.contracts.support. A ticket never carries a password, a token, an address or what a form held; the reader's
 * own address is on the owner's view only.
 */
import type { Iso } from "./types";

export type SupportCategory =
  "access" | "account" | "technical" | "wrong_data" | "suggestion" | "complaint";
export type TicketCategory = SupportCategory | "privacy";
export type SupportPriority = "urgent" | "high" | "medium" | "low";
export type SupportStatus = "open" | "answered" | "closed";
export type SupportChannel = "web" | "email" | "whatsapp";
export type SupportAuthor = "customer" | "owner" | "system";
export type SupportDevice = "phone" | "tablet" | "desktop";
export type FirstAnswer = "same_day" | "24h" | "48h" | "week";
export type InboxStatus = "open" | "waiting" | "answered" | "closed" | "all";

/** What the page attaches to a ticket; the server checks every key again. */
export interface SupportContext {
  /** The screen's path, without its query. */
  route?: string | null;
  /** The request id of the last error the page met (plan UX, A2). */
  request_id?: string | null;
  web_version?: string | null;
  device?: SupportDevice | null;
  /** True: the installed app; false: a browser tab. */
  pwa?: boolean | null;
  /** The match a «wrong data» report is about. */
  match_id?: number | null;
}

export interface SupportMessage {
  author: SupportAuthor;
  body: string;
  at: Iso;
  /** web: written in PrediGol; email / whatsapp: what the owner noted from a talk there. */
  channel: SupportChannel;
}

export interface SupportTicket {
  id: number;
  category: SupportCategory;
  priority: SupportPriority;
  /** open: waiting for PrediGol; answered: PrediGol answered; closed. */
  status: SupportStatus;
  opened_at: Iso;
  /** When the first answer is due (section 32); null once one came. */
  respond_by: Iso | null;
  answered: boolean;
  closed_at: Iso | null;
  /** How easy it was, 1 to 5; asked once it is closed. */
  effort: number | null;
  messages: SupportMessage[];
}

export interface SupportCategoryInfo {
  category: SupportCategory;
  priority: SupportPriority;
  first_answer: FirstAnswer;
}

export interface SupportContact {
  /** The WhatsApp Business number, digits with the country code (P7); null until the owner gives it. */
  whatsapp: string | null;
  /** The address a reader's e-mail reaches; null if none. */
  email: string | null;
}

export interface SupportState {
  /** FBI_SUPPORT: false - no new ticket or message (Ayuda, the contact and the privacy requests stay). */
  enabled: boolean;
  contact: SupportContact;
  categories: SupportCategoryInfo[];
  /** The reader's own, open first, newest first. */
  tickets: SupportTicket[];
  max_text: number;
  max_open: number;
}

export interface TicketIn {
  category: SupportCategory;
  text: string;
  context?: SupportContext;
}

export interface AdminTicket {
  id: number;
  user_id: number;
  email: string;
  display_name: string;
  /** The account's state now (deleted: nobody is left to answer). */
  account_status: string;
  /** support, or the privacy request's kind. */
  kind: string;
  category: TicketCategory;
  priority: SupportPriority;
  status: SupportStatus;
  opened_at: Iso;
  closed_at: Iso | null;
  respond_by: Iso | null;
  /** A privacy request's legal deadline (with the one extension, if used). */
  deadline: string | null;
  extended: boolean;
  first_answer_at: Iso | null;
  waiting: boolean;
  late: boolean;
  context: SupportContext | null;
  effort: number | null;
  /** The reader is AT RISK on the newest day of the lifecycle (B11): their request goes first within its priority. */
  at_risk: boolean;
  messages: SupportMessage[];
}

export interface SupportCounts {
  open: number;
  waiting: number;
  late: number;
  urgent: number;
}

export interface AdminInbox {
  counts: SupportCounts;
  tickets: AdminTicket[];
}

export interface TicketAnswerIn {
  body: string;
  status: SupportStatus;
  channel: SupportChannel;
}

export interface InboxQuery {
  status?: InboxStatus;
  category?: TicketCategory | undefined;
  priority?: SupportPriority | undefined;
}
