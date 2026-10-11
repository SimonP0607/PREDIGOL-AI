/** How a pre-match profile figure reads (REVIEW PREDIGOL, point 5): null when no match carries its data. */
import { fmtPct, toNumber } from "@/lib/i18n/format";
import type { ProfileMetric, ProfileValue } from "@/lib/api/v1/types_profile";
import { fmtDecimal } from "./model";

export function profileText(
  m: Pick<ProfileMetric, "key" | "kind">,
  v: ProfileValue,
): string | null {
  if (v.n === 0) return null;
  if (m.kind === "ratio") return `${v.count ?? 0}/${v.total ?? 0}`;
  const value = toNumber(v.value);
  if (value === null) return null;
  if (m.kind === "count") return `${v.count ?? 0} (${fmtPct(value, 0)})`;
  if (m.key === "possession") return fmtPct(value / 100, 0);
  return fmtDecimal(value, 2);
}
