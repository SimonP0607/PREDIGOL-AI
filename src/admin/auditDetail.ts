/** The detail of an audit event in the reader's language. Pure, so it is tested without a page. */
import { translateOr } from "@/lib/i18n";

/** One value of a detail, in the reader's language when the catalogue knows it (roles stay as their codes). */
function detailValue(v: unknown): string {
  const text = String(v);
  return /^[a-z_]+$/.test(text) ? translateOr(`admin.audit.values.${text}`, text) : text;
}

/** "fields: language" -> "campos: idioma"; unknown keys and values are shown as they came. */
export function detailText(detail: Record<string, unknown>): string {
  // jsonb stores keys shortest first ("to" before "from"); a change reads before -> after.
  const order = (k: string) => (k === "from" ? 0 : k === "to" ? 1 : 2);
  const entries = Object.entries(detail).sort(([a], [b]) => order(a) - order(b));
  const parts = entries.map(([k, v]) => {
    const label = translateOr(`admin.audit.keys.${k}`, k);
    const value = Array.isArray(v) ? v.map(detailValue).join(", ") : detailValue(v);
    return `${label}: ${value}`;
  });
  return parts.join(" · ");
}
