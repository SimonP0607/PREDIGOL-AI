import { t } from "@/lib/i18n";
import type { DailyItem } from "@/lib/api/v1/types_records";
import type { PickLevel } from "./model";

/** The two lines of why under the figures: the review's own words when a decision a reader may see has them, else the rule's. */
export function whyLines(item: DailyItem, level: PickLevel | null): string[] {
  const positive = item.ai?.decision ? item.ai.positives?.[0] : undefined;
  const risk = item.ai?.decision ? item.ai.risks?.[0] : undefined;
  const first = positive?.trim() || t("records.card.whyValue");
  const second =
    risk?.trim() ||
    (level === "high"
      ? t("records.card.whyHigh")
      : level === "medium"
        ? t("records.card.whyMedium")
        : "");
  return second ? [first, second] : [first];
}
