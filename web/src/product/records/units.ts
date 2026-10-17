/** Profit in units of one stake: +1,30 u / −1,00 u. PrediGol handles no money. */
import { t } from "@/lib/i18n";
import { DASH, localFixed, toNumber } from "@/lib/i18n/format";

export function fmtUnits(value: string | number | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return DASH;
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return t("records.units", { value: `${sign}${localFixed(Math.abs(n), 2)}` });
}
