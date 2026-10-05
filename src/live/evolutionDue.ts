/** Why the weekly research-V2 run is due, said in the reader's language. Pure: tested without a page. */
import { t, translateOr } from "@/lib/i18n";

/** The research-V2 due reason in the reader's language, by its stable code; the backend's English otherwise. */
export function dueReason(d: {
  v2_due: string | null;
  v2_due_code?: string | null | undefined;
  v2_due_vars?: Record<string, string> | undefined;
}): string {
  if (!d.v2_due) return "";
  if (!d.v2_due_code) return d.v2_due;
  const vars = { ...(d.v2_due_vars ?? {}) };
  if (d.v2_due_code === "new_dataset" && !vars["before"])
    vars["before"] = t("ai.evolution.noneRecorded");
  return translateOr(`ai.evolution.dueReasons.${d.v2_due_code}`, d.v2_due, vars);
}
