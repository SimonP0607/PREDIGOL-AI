/** A followed player's state as Inicio says it: the state as the data has it, and why when it is an absence. */
import { t } from "@/lib/i18n";
import type { WatchedPlayer } from "@/lib/api/v1/types_me_today";
import { absenceReason } from "@/product/match/model";

/** «Titular», «Baja · Lesión», «Aún sin alineación ni bajas»: the reason is the provider's, classified as the match's «Bajas» do. */
export function stateText(p: Pick<WatchedPlayer, "state" | "reason">): string {
  const label = t(`home.players.state.${p.state}`);
  if ((p.state === "absent" || p.state === "doubtful") && p.reason) {
    return `${label} · ${t(`match.absences.reason.${absenceReason(p.reason)}`)}`;
  }
  return label;
}
