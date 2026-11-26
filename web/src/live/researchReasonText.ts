/**
 * The words of why a research entry has its role (namespace `researchreason`, C-11 1.1, AP-A04): one phrase per code of the
 * closed list (`fbi.research.reason_codes`). They travel in the console's chunk, not in the first visit's JS. A sentence the
 * list does not know has no code: the server's own sentence is shown as it came, never a guess.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import type { ResearchEntry } from "@/lib/api/v1/types_research";
import es from "@/locales/es/researchreason.json";
import en from "@/locales/en/researchreason.json";

export const RESEARCH_REASON_CATALOG = { es, en };

let added = false;

function t(key: string): string {
  if (!added) {
    addCatalog("researchreason", RESEARCH_REASON_CATALOG);
    added = true;
  }
  return translate(key);
}

addCatalog("researchreason", RESEARCH_REASON_CATALOG);

/** The reason of an entry in the reader's language; the server's sentence when it has no code; null when it has neither. */
export function reasonText(
  entry: Pick<ResearchEntry, "role_reason" | "role_reason_code">,
): string | null {
  const code = entry.role_reason_code;
  if (code) return t(`researchreason.${code}`);
  return entry.role_reason;
}
