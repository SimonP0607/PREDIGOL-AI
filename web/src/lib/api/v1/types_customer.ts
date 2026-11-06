/**
 * The legal texts, a reader's consents, the export of their own data and their privacy requests (plan UX, A4).
 * Mirrors backend/src/fbi/api/contracts/customer.py.
 */

export type LegalDocumentName = "terms" | "privacy" | "responsible_gaming";
/**
 * The four the gate asks for and two optional ones, never ticked beforehand and never asked for by the gate: the weekly
 * summary by e-mail (plan UX, B8), offered only while it can reach the reader, and the usage statistics under a pseudonym
 * (plan de cierre UX, 1.2), always offered.
 */
export type ConsentKind =
  "terms" | "privacy" | "age_18" | "risk_notice" | "marketing_email" | "analytics";
export type PrivacyRequestKind = "privacy_query" | "privacy_claim" | "privacy_deletion";
export type TicketStatus = "open" | "answered" | "closed";

export interface LegalBlock {
  p?: string | null;
  ul?: string[] | null;
}

export interface LegalSection {
  /** Stable across languages and versions: the page's anchor. */
  id: string;
  title: string;
  blocks: LegalBlock[];
}

export interface LegalVersion {
  version: string;
  date: string;
  draft: boolean;
  /** True: every reader had to accept this version again. */
  material: boolean;
  changes: string;
  sha256: string;
}

export interface LegalDocument {
  document: LegalDocumentName;
  locale: "es" | "en";
  version: string;
  date: string;
  /** Pending the lawyer's written OK: the page says it is not in force yet. */
  draft: boolean;
  title: string;
  summary: string;
  sections: LegalSection[];
  sha256: string;
  /** Every version, newest first. */
  history: LegalVersion[];
}

export interface ConsentPurpose {
  kind: ConsentKind;
  document: LegalDocumentName;
  /** The current version of its document: the one a decision must name. */
  version: string;
  sha256: string;
  /** The box's sentence, in the requested language. */
  statement: string;
  required: boolean;
  withdrawable: boolean;
  /** When the reader accepted an older version a material change replaced: what changed. */
  changes?: string | null;
}

export interface ConsentRecord {
  kind: string;
  granted: boolean;
  document: string;
  version: string;
  sha256: string;
  locale: string;
  statement: string;
  source: string;
  at: string;
}

export interface ConsentState {
  gate: boolean;
  due: ConsentKind[];
  purposes: ConsentPurpose[];
  /** Every decision, newest first. */
  history: ConsentRecord[];
}

export interface ConsentDecision {
  kind: ConsentKind;
  granted: boolean;
  version: string;
}

export interface ConsentsIn {
  decisions: ConsentDecision[];
  locale: "es" | "en";
  /** activation: the gate shown right after /activate (plan UX, A7); the server keeps it only within the hour. */
  source?: "gate" | "profile" | "activation";
}

export interface ReauthIn {
  password: string;
  code?: string | null;
}

export interface PrivacyRequestIn {
  kind: PrivacyRequestKind;
  message: string;
  password?: string | null;
  code?: string | null;
}

export interface TicketMessage {
  author: "customer" | "owner" | "system";
  body: string;
  at: string;
}

export interface PrivacyRequest {
  id: number;
  kind: PrivacyRequestKind;
  status: TicketStatus;
  opened_at: string;
  due_on: string | null;
  extended_to: string | null;
  /** extended_to when the one extension was used, due_on otherwise. */
  deadline: string | null;
  closed_at: string | null;
  messages: TicketMessage[];
}

export interface AdminPrivacyRequest extends PrivacyRequest {
  user_id: number;
  email: string;
}

export interface PrivacyAnswerIn {
  body: string;
  status?: TicketStatus;
  extend?: boolean;
}

/** The export: everything PrediGol keeps about the reader, as one JSON document. */
export type ExportDocument = Record<string, unknown>;
