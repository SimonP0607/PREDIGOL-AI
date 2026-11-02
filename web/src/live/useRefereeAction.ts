/** The decisions an owner takes on referees (plan F3), as one mutation: every POST, and everything read about referees read again. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
import type { RefereeActionResult } from "@/lib/api/v1/types_referees";

export type RefereeJob =
  | { kind: "merge"; keepId: number; mergeId: number; force?: boolean }
  | { kind: "reject"; id: number; otherId: number }
  | { kind: "reopen"; id: number; otherId: number }
  | { kind: "undo"; eventId: number }
  | { kind: "split"; id: number; aliasIds: number[]; name?: string }
  | { kind: "rename"; id: number; name: string | null };

function run(job: RefereeJob) {
  switch (job.kind) {
    case "merge":
      return v1.refereeMerge(job.keepId, { merge_id: job.mergeId, force: job.force });
    case "reject":
      return v1.refereeReject(job.id, { other_id: job.otherId });
    case "reopen":
      return v1.refereeReopen(job.id, { other_id: job.otherId });
    case "undo":
      return v1.refereeUndo(job.eventId);
    case "split":
      return v1.refereeSplit(job.id, { alias_ids: job.aliasIds, name: job.name });
    case "rename":
      return v1.refereeRename(job.id, { name: job.name });
  }
}

/** Every decision is a POST; when it works, everything read about referees is read again. */
export function useRefereeAction(onDone?: (result: RefereeActionResult) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ["v1", "referees"] });
      onDone?.(res.data);
    },
  });
}
