import { hasKey, t } from "@/lib/i18n";

/**
 * The reader's-language text for a section's code (REVIEW 11 Oct 2026, point 8: the API's reasons are
 * English and technical). Null when the code is unknown here - the caller falls back to the API's reason.
 */
export function sectionCodeText(code: string | null | undefined): string | null {
  if (!code) return null;
  const key = `common.sectionCode.${code}`;
  return hasKey(key) || hasKey(key, "en") ? t(key) : null;
}
