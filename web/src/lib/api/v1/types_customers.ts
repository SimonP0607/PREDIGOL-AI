/**
 * The customer's card for the owner (plan UX, B10), as the API returns it. Mirrors fbi.api.contracts.customers. The card
 * holds no IP, no token and no loose click: the use is counts of days.
 */
import type { Iso } from "./types";
import type { MembershipSummary } from "./types_membership";

export type CustomerView =
  "all" | "expiring" | "inactive" | "tickets" | "errors" | "at_risk" | "invited";
/** Where a customer stands on the newest day the lifecycle computed (plan UX, B11). */
export type LifecycleState =
  "invited" | "activated" | "habitual" | "at_risk" | "expiring" | "renewed" | "expired";
export const CUSTOMER_VIEWS: readonly CustomerView[] = [
  "all",
  "expiring",
  "inactive",
  "tickets",
  "errors",
  "at_risk",
  "invited",
];
export type CustomerStatus = "active" | "disabled" | "invited";

export interface CustomerRow {
  id: number;
  email: string;
  display_name: string | null;
  status: CustomerStatus;
  created_at: Iso;
  last_seen_at: Iso | null;
  membership: MembershipSummary | null;
  open_tickets: number;
  errors_24h: number;
  active_days_7: number;
  last_csat: number | null;
  /** Null before the first calculation. */
  lifecycle: LifecycleState | null;
  /** Why, as codes of a closed list. */
  lifecycle_reasons: string[];
}

export interface CustomerList {
  view: CustomerView;
  items: CustomerRow[];
  total: number;
  views: Array<{ view: CustomerView; count: number }>;
  limit: number;
  offset: number;
}

export interface CustomerIdentity {
  id: number;
  email: string;
  display_name: string | null;
  status: CustomerStatus;
  language: string;
  timezone: string;
  created_at: Iso;
  last_login_at: Iso | null;
  last_seen_at: Iso | null;
  mfa_enabled: boolean;
  open_sessions: number;
}

export interface CustomerUsage {
  active_days_7: number;
  active_days_30: number;
  matches_viewed_30: number;
  picks_opened_30: number;
  picks_saved: number;
  parlays_saved: number;
  errors_24h: number;
  /** False: nothing is recorded for them, so the counts are zero for lack of measure, not of use. */
  measured: boolean;
}

export interface CustomerDevice {
  id: number;
  family: string;
  system: string;
  installed: boolean;
  created_at: Iso;
  last_ok_at: Iso | null;
}

export interface CustomerNotifications {
  email_status: "ok" | "bounced" | "complained";
  email_status_at: Iso | null;
  email_off: string[];
  push_off: string[];
  devices: CustomerDevice[];
  sent_30: number;
  failed_30: number;
  bounced_30: number;
  suppressed_30: number;
}

export interface CustomerConsent {
  kind: string;
  granted: boolean;
  version: string;
  at: Iso;
}

export interface CustomerTicket {
  id: number;
  kind: string;
  category: string;
  status: string;
  opened_at: Iso;
  closed_at: Iso | null;
  messages: number;
  late: boolean;
}

export interface CustomerFeedback {
  kind: string;
  score: number | null;
  helpful: boolean | null;
  subject: string | null;
  created_at: Iso;
}

export interface CustomerFeedbackSummary {
  last_csat: number | null;
  last_csat_at: Iso | null;
  survey_answers: number;
  helpful_yes: number;
  helpful_no: number;
  recent: CustomerFeedback[];
}

export interface CustomerNote {
  id: number;
  at: Iso;
  author: string | null;
  note: string;
}

export interface LifecycleChange {
  day: string;
  state: LifecycleState;
  reasons: string[];
}

export interface Customer {
  identity: CustomerIdentity;
  membership: MembershipSummary | null;
  suspended_reason: string | null;
  usage: CustomerUsage;
  notifications: CustomerNotifications;
  consents: CustomerConsent[];
  consents_due: string[];
  tickets: CustomerTicket[];
  feedback: CustomerFeedbackSummary;
  notes: CustomerNote[];
  privacy_requests_open: number;
  /** Their newest state and why. */
  lifecycle: LifecycleChange | null;
  /** Their changes of state, newest first. */
  lifecycle_history: LifecycleChange[];
}

export interface ConsentRecord {
  kind: string;
  granted: boolean;
  document: string;
  version: string;
  sha256: string;
  locale: string;
  source: string;
  at: Iso;
}

export interface TicketReview {
  id: number;
  kind: string;
  category: string;
  status: string;
  opened_at: Iso;
  due_on: string | null;
  closed_at: Iso | null;
  effort: number | null;
  messages: Array<{ author: string; body: string; at: Iso }>;
}

export interface AuditActionCount {
  action: string;
  count: number;
}
