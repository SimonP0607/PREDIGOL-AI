import { t } from "@/lib/i18n";
import type { DailyItem } from "@/lib/api/v1/types_records";
import { localizeServerText } from "@/lib/i18n/format";

/**
 * The lines of why under the figures: the review's own words when a decision a reader may see has them, else the rule's.
 * There is no «Nivel» any more (plan PICKS, D4): a second line only when the review names a risk.
 */
export function whyLines(item: DailyItem): string[] {
  // AP-K05: each line passes the guard of the server's texts (AP-T02: no rumour, no other script, decimals in the reader's
  // format), and a positive that only repeats the two figures already on the card's line («Modelo 73.7 % frente a mercado
  // 66.6 %») is not drawn a second time: the rule's sentence takes its place.
  const positive = item.ai?.decision ? readerLine(item.ai.positives?.[0]) : null;
  const risk = item.ai?.decision ? readerLine(item.ai.risks?.[0]) : null;
  const first = positive && !restatesFigures(positive) ? positive : t("records.card.whyValue");
  return risk ? [first, risk] : [first];
}

function readerLine(text: string | undefined): string | null {
  return localizeServerText(text);
}

/** A sentence with two percentages or more is the figures again, not a reason. */
export function restatesFigures(text: string): boolean {
  return (text.match(/\d+(?:[.,]\d+)?\s?%/g) ?? []).length >= 2;
}
