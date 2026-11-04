/** A match's news, loaded for the signed-in view (plan UX, A10): Noticias and the press's absences in Alineaciones share it. */
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import type { Envelope } from "@/lib/api/v1/types";
import type { MatchNews } from "@/lib/api/v1/types_news";

export type NewsLoad =
  | { status: "pending" }
  | { status: "error"; error: unknown; retry?: () => void }
  | { status: "success"; envelope: Envelope<MatchNews | null> };

export function useNews(fixtureId: string): NewsLoad {
  const q = useQuery(live.matchNews(fixtureId));
  if (q.isPending) return { status: "pending" };
  if (q.isError) return { status: "error", error: q.error, retry: () => void q.refetch() };
  return { status: "success", envelope: q.data };
}
