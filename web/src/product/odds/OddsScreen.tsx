/**
 * Cuotas (plan Cuotas, UX-069): the explorer by families while the API says `odds_explorer` (FBI_ODDS_EXPLORER, in GET
 * /auth/me), the page of always otherwise. The explorer is its own chunk: a reader of the page of always never downloads it.
 */
import { lazy, Suspense } from "react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { SkeletonCards } from "@/product/shared/States";
import { OddsPage } from "./OddsPage";

const ExplorerScreen = lazy(() =>
  import("./ExplorerScreen").then((m) => ({ default: m.ExplorerScreen })),
);

export function OddsScreen() {
  const on = useAuth().user?.odds_explorer === true;
  if (!on) return <OddsPage />;
  return (
    <Suspense fallback={<SkeletonCards count={4} />}>
      <ExplorerScreen />
    </Suspense>
  );
}
