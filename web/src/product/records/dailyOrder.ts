/**
 * Orden de los picks del día (plan de correcciones UX, AP-K01; hallazgo K6 de la auditoría).
 *
 * Por defecto, «Mejores primero»: el rango de PrediGol (1 a 5), que ya llega de la API. «Por hora» y «Por valor» quedan
 * como opciones. El rango de cada tarjeta es siempre el de PrediGol, sea cual sea el orden en que se muestran.
 */
import { toNumber } from "@/lib/i18n/format";

export type DailyOrder = "best" | "time" | "value";

export const DEFAULT_DAILY_ORDER: DailyOrder = "best";

interface Orderable {
  rank: number;
  ev?: string | number | null | undefined;
  match: { kickoff_at: string };
}

export function orderDaily<T extends Orderable>(items: readonly T[], order: DailyOrder): T[] {
  const byRank = (a: T, b: T) => a.rank - b.rank;
  const copy = [...items];
  if (order === "value")
    return copy.sort(
      (a, b) => (toNumber(b.ev) ?? -Infinity) - (toNumber(a.ev) ?? -Infinity) || byRank(a, b),
    );
  if (order === "time")
    return copy.sort(
      (a, b) => Date.parse(a.match.kickoff_at) - Date.parse(b.match.kickoff_at) || byRank(a, b),
    );
  return copy.sort(byRank);
}
