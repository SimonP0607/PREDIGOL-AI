import { t } from "@/lib/i18n";
import type { DailyItem } from "@/lib/api/v1/types_records";

/**
 * The lines of why under the figures: the review's own words when a decision a reader may see has them, else the rule's.
 * There is no «Nivel» any more (plan PICKS, D4): a second line only when the review names a risk.
 */
export function whyLines(item: DailyItem): string[] {
  const positive = item.ai?.decision ? item.ai.positives?.[0] : undefined;
  const risk = item.ai?.decision ? item.ai.risks?.[0] : undefined;
  const first = positive?.trim() || t("records.card.whyValue");
  const second = risk?.trim();
  return second ? [first, second] : [first];
}
