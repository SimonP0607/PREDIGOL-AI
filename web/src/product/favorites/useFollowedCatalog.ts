/**
 * The catalogue markets the reader follows, in their order (CUOTAS, BE-025): the ones a match's «Mercados» lists first.
 * None for anyone but a reader, or while personalisation is off (the common view); only the order changes.
 */
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { useAuth } from "@/lib/auth/AuthProvider";

export function useFollowedCatalog(): readonly string[] {
  const reader = useAuth().user?.role === "USER";
  const favorites = useQuery({ ...live.favorites, enabled: reader });
  const view = favorites.data;
  return reader && view?.personalization ? (view.catalog_markets ?? []) : [];
}
