/** How a started pick reads in the "Ya empezaron hoy" filter (REVIEW point 14). */
import type { StartedPick } from "@/lib/api/v1/types_product";
import { isLivePhase } from "@/product/matches/status";

export type StartedState = "all" | "live" | "won" | "lost" | "other";

/** In play, won, lost, or neither yet (void, push, a match over without its result). */
export function startedState(
  p: Pick<StartedPick, "result_status" | "phase">,
): Exclude<StartedState, "all"> {
  const r = p.result_status;
  if (r === "win" || r === "half_win") return "won";
  if (r === "loss" || r === "half_loss") return "lost";
  if (r === null && isLivePhase(p.phase)) return "live";
  return "other";
}
