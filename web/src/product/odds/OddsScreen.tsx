/**
 * Cuotas (plan Cuotas, UX-069): the explorer by families while the API says `odds_explorer` (FBI_ODDS_EXPLORER, in GET
 * /auth/me), the page of always otherwise. The explorer is its own chunk: a reader of the page of always never downloads it.
 */
import { lazy, Suspense } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronRight, Clock } from "lucide-react";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { SkeletonCards } from "@/product/shared/States";
import { OddsPage } from "./OddsPage";

const ExplorerScreen = lazy(() =>
  import("./ExplorerScreen").then((m) => ({ default: m.ExplorerScreen })),
);

/** The way to «Estado de los precios» (decision 4), only while the API says it is open (FBI_ODDS_STATUS). */
function StatusLink() {
  return (
    <p className="mt-4">
      <Link
        to="/odds/status"
        data-testid="odds-status-link"
        className="card-surface tap-y relative flex min-h-12 items-center gap-2.5 rounded-control px-3.5 py-2.5 text-sm font-semibold text-foreground hover:text-primary"
      >
        <Clock aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1">{t("odds.status.link")}</span>
        <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
      </Link>
    </p>
  );
}

export function OddsScreen() {
  const user = useAuth().user;
  const on = user?.odds_explorer === true;
  const status = user?.odds_status === true ? <StatusLink /> : null;
  if (!on)
    return (
      <>
        <OddsPage />
        {status}
      </>
    );
  return (
    <>
      <Suspense fallback={<SkeletonCards count={4} />}>
        <ExplorerScreen />
      </Suspense>
      {status}
    </>
  );
}
