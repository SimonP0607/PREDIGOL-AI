/** The structured reading of a match, loaded for the signed-in view (a reader's, or the Admin Console's preview). */
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { Envelope } from "@/lib/api/v1/types";
import type { MatchReading } from "@/lib/api/v1/types_reading";
import type { MatchCtx } from "@/product/match/context";

export type ReadingLoad =
  | { status: "pending" }
  | { status: "error"; error: unknown; retry?: () => void }
  | { status: "success"; envelope: Envelope<MatchReading | null> };

export function useReading(ctx: Pick<MatchCtx, "fixtureId">): ReadingLoad {
  const preview = usePreviewParam();
  const q = useQuery(live.matchReading(ctx.fixtureId, preview));
  if (q.isPending) return { status: "pending" };
  if (q.isError) return { status: "error", error: q.error, retry: () => void q.refetch() };
  return { status: "success", envelope: q.data };
}
