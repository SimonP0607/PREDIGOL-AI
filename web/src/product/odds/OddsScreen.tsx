/**
 * Cuotas (plan Cuotas, UX-069): the explorer by families while the API says `odds_explorer` (FBI_ODDS_EXPLORER, in GET
 * /auth/me), the page of always otherwise. The explorer is its own chunk: a reader of the page of always never downloads it.
 */
import { lazy, Suspense } from "react";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Segmented } from "@/components/ui/segmented";
import { ChevronRight, Clock } from "lucide-react";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { SkeletonCards } from "@/product/shared/States";
import { OddsPage } from "./OddsPage";
import type { DayKey } from "./explorer/model";

const ExplorerScreen = lazy(() =>
  import("./ExplorerScreen").then((m) => ({ default: m.ExplorerScreen })),
);

const ByMatchScreen = lazy(() =>
  import("./byMatch/ByMatchScreen").then((m) => ({ default: m.ByMatchScreen })),
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
  if (user?.odds_by_match !== true)
    return (
      <>
        <Suspense fallback={<SkeletonCards count={4} />}>
          <ExplorerScreen />
        </Suspense>
        {status}
      </>
    );
  return <TwoViews status={status} />;
}

type View = "partido" | "mercado";

/**
 * Cuotas with its two views (plan maestro unificado, UX-141): «Por partido» (sheets C01, C06), the default, and «Por mercado»,
 * the explorer by families as it was. The view lives in the URL (`v=mercado`), so a link and the back button keep it.
 */
function TwoViews({ status }: { status: React.ReactNode }) {
  const search = useSearch({ strict: false }) as Record<string, unknown>;
  const navigate = useNavigate();
  const view: View = search["v"] === "mercado" ? "mercado" : "partido";
  // «Hoy · Mañana · Pasado mañana» lives in the URL too (`h`, AP-C01): the same key as the explorer's, so the day survives the
  // switch between the two views.
  const day: DayKey =
    search["h"] === "tomorrow" || search["h"] === "day_after" ? search["h"] : "today";
  const modeSwitch = (
    <Segmented
      label={t("odds.byMatch.mode.label")}
      value={view}
      testId="odds-view"
      onChange={(next: View) =>
        void navigate({
          to: "/odds",
          search: {
            ...(next === "mercado" ? { v: "mercado" } : {}),
            ...(day !== "today" ? { h: day } : {}),
          },
          resetScroll: false,
        })
      }
      options={[
        { value: "partido", label: t("odds.byMatch.mode.byMatch") },
        { value: "mercado", label: t("odds.byMatch.mode.byMarket") },
      ]}
    />
  );
  return (
    <>
      <Suspense fallback={<SkeletonCards count={4} />}>
        {view === "mercado" ? (
          <ExplorerScreen modeSwitch={modeSwitch} />
        ) : (
          <ByMatchScreen
            modeSwitch={modeSwitch}
            day={day}
            onDay={(next) =>
              void navigate({
                to: "/odds",
                search: next === "today" ? {} : { h: next },
                resetScroll: false,
              })
            }
          />
        )}
      </Suspense>
      {status}
    </>
  );
}
