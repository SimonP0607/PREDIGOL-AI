/** Whether «Más» carries the dot of Novedades (plan UX, B6): an entry newer than the last one this reader saw. */
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { useAuth } from "@/lib/auth/AuthProvider";
import { hasUnread } from "@/product/updates/updates";

export function useUpdatesUnread(): boolean {
  const auth = useAuth();
  const signedIn = auth.status === "signed-in" && (auth.user?.consents_due ?? []).length === 0;
  const seen = useQuery({ ...live.updatesSeen, enabled: signedIn });
  return signedIn && seen.isSuccess && hasUnread(seen.data.last_seen);
}
