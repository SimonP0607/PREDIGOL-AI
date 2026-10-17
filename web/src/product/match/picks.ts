/** The match's picks as the Picks tab and the Resumen read them. */
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { PickCard as PickCardData, StartedPick } from "@/lib/api/v1/types_product";
import type { MatchCtx } from "./context";

/** This match's qualified picks, each once, in the board's own order (value now first). */
export function matchPicks(
  board: { top: PickCardData[]; picks: PickCardData[] } | undefined,
  fixtureId: number,
): PickCardData[] {
  const seen = new Set<number>();
  const order = new Map((board?.picks ?? []).map((p, i) => [p.pick_id, i]));
  return [...(board?.top ?? []), ...(board?.picks ?? [])]
    .filter((p) => {
      if (p.fixture_id !== fixtureId || seen.has(p.pick_id)) return false;
      seen.add(p.pick_id);
      return true;
    })
    .sort((a, b) => (order.get(a.pick_id) ?? -1) - (order.get(b.pick_id) ?? -1));
}

/** Won / lost / in play / void, from the frozen pre-match picks. Half results count with their side. */
export function outcomeCounts(picks: readonly StartedPick[]) {
  const c = { won: 0, lost: 0, open: 0, void: 0 };
  for (const p of picks) {
    const r = p.result_status;
    if (r === "win" || r === "half_win") c.won += 1;
    else if (r === "loss" || r === "half_loss") c.lost += 1;
    else if (r === "void" || r === "push") c.void += 1;
    else c.open += 1;
  }
  return c;
}

export function useMatchPicks(ctx: MatchCtx) {
  const preview = usePreviewParam();
  return useQuery(live.productPicks({ hours: 168, fixture_id: Number(ctx.fixtureId) }, preview));
}
