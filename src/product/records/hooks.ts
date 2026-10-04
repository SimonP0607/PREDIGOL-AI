/** The signed-in user's saved picks, and saving or removing one, with a word of feedback. */
import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { t } from "@/lib/i18n";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { SavePickIn, UserPick } from "@/lib/api/v1/types_records";
import { errorMessage } from "@/product/shared/States";
import { selectionKey } from "./model";

/** Everything under ["v1", "me"]: picks, parlays, history and the slip's validation. */
export function useRefreshMine(): () => Promise<void> {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["v1", "me"] });
}

export function useSavedPicks() {
  const query = useQuery(live.myPicks);
  const refresh = useRefreshMine();
  const saved = useMemo(() => {
    const byKey = new Map<string, UserPick>();
    for (const p of query.data?.data ?? []) {
      byKey.set(
        selectionKey({
          fixture_id: p.match.fixture_id,
          market_key: p.market_key,
          selection: p.selection,
          line: p.line,
        }),
        p,
      );
    }
    return byKey;
  }, [query.data]);

  const save = useMutation({
    mutationFn: (body: SavePickIn) => v1.savePick(body),
    onSuccess: () => {
      toast.success(t("records.toast.saved"));
      void refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => v1.removePick(id),
    onSuccess: () => {
      toast(t("records.toast.unsaved"));
      void refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return { saved, save, remove, query };
}
