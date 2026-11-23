/**
 * «Cómo leerlo» for the price-movement charts (plan Correcciones UX, AP-T03): where the best price of each selection started and where
 * it stands, in the reader's words, from the captures the server already stored (`bestPriceLines`). The change is the one the panel
 * already shows beside each chart; nothing new is computed here. Pure.
 */
import { fmtSignedPct, formatOdds, localInt } from "@/lib/i18n/format";
import type { TextReading } from "@/components/analytics/evidence";
import { t } from "@/components/analytics/stats/readText";
import type { MovePoint } from "./movement";

/** Under two captures there is no movement to read: the chart is an anecdote. */
export const MIN_CAPTURES = 2;

export interface TitledLine {
  title: string;
  points: readonly MovePoint[];
}

/** One selection: «Real Madrid: de 2,10 a 1,95 (−7,1 %) en 6 capturas». */
function one(l: TitledLine): string | null {
  const first = l.points[0];
  const last = l.points[l.points.length - 1];
  if (!first || !last) return null;
  if (l.points.length < MIN_CAPTURES)
    return t("readchart.movement.single", { title: l.title, odds: formatOdds(last.odds) });
  return t("readchart.movement.line", {
    title: l.title,
    from: formatOdds(first.odds),
    to: formatOdds(last.odds),
    change: fmtSignedPct(last.odds / first.odds - 1),
    n: localInt(l.points.length),
  });
}

/** The sentence of a set of selections (one chart each); null when no selection has a capture. */
export function movementReading(lines: readonly TitledLine[]): TextReading | null {
  const said = lines.map(one).filter((x): x is string => x !== null);
  if (said.length === 0) return null;
  const n = Math.min(...lines.filter((l) => l.points.length > 0).map((l) => l.points.length));
  const lead = n < MIN_CAPTURES ? ` ${t("readchart.movement.thin")}` : "";
  return { kind: "text", sentence: `${said.join(" ")}${lead}`, n, minSample: MIN_CAPTURES };
}
