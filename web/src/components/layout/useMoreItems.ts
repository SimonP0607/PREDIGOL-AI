/** The items of «Más» this reader sees (plan UX, A15). */
import { useAuth } from "@/lib/auth/AuthProvider";
import { moreItems, type MoreItem } from "./nav";

/** Transparencia once the owner opened it to readers (or to the owner himself, who reviews it first). */
export function useMoreItems(): MoreItem[] {
  const auth = useAuth();
  return moreItems(Boolean(auth.user?.transparency) || auth.showAdmin);
}
