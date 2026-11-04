/**
 * Where each legal text lives (plan UX, A4): /legal/terms, /legal/privacy and /legal/responsible-gaming. The API names
 * the documents with an underscore; the addresses use a hyphen.
 */
import type { LegalDocumentName } from "@/lib/api/v1/types_customer";
import { formatDateYear } from "@/lib/time";

export const LEGAL_DOCUMENTS: readonly LegalDocumentName[] = [
  "terms",
  "privacy",
  "responsible_gaming",
];

const SLUGS: Readonly<Record<LegalDocumentName, string>> = {
  terms: "terms",
  privacy: "privacy",
  responsible_gaming: "responsible-gaming",
};

export function legalPath(document: LegalDocumentName, anchor?: string): string {
  return `/legal/${SLUGS[document]}${anchor ? `#${anchor}` : ""}`;
}

/** The document an address names, or null for any other address. */
export function documentOfSlug(slug: string): LegalDocumentName | null {
  const found = LEGAL_DOCUMENTS.find((d) => SLUGS[d] === slug);
  return found ?? null;
}

export function isLegalPath(pathname: string): boolean {
  return pathname.startsWith("/legal/");
}

/** A calendar day (a version's date, a deadline): shown as written, never moved by a time zone. */
export function dayOf(iso: string): string {
  return formatDateYear(`${iso.slice(0, 10)}T12:00:00Z`, "UTC");
}
