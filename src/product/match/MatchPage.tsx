/**
 * The Match Center as the product shows it: the match at a glance, then Resumen,
 * Estadísticas, Mercados and Alineaciones - each adapted to before, during and after
 * the match. SUPER_ADMIN also gets "Avanzado / Auditoría", the research view.
 */
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, SearchX, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import { LiveApiError } from "@/lib/api/v1/client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { Card, EmptyState, ErrorState, SkeletonBlock } from "@/product/shared/States";
import { AdvancedTab } from "./AdvancedTab";
import type { MatchCtx, TabKey } from "./context";
import { LineupsTab } from "./LineupsTab";
import { MarketsTab } from "./MarketsTab";
import { MatchHeader } from "./MatchHeader";
import { liveSnapshot, matchPhase, shownScore } from "./model";
import { StatsTab } from "./StatsTab";
import { SummaryTab } from "./SummaryTab";
import { useMatchTab } from "./useMatchTab";

const USER_TABS: readonly TabKey[] = ["summary", "stats", "markets", "lineups"];
const ADMIN_TABS: readonly TabKey[] = [...USER_TABS, "advanced"];

function BackLink() {
  return (
    <Link
      to="/matches"
      className="inline-flex min-h-9 items-center gap-1 rounded-md pr-2 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <ChevronLeft aria-hidden className="h-4 w-4" />
      {t("match.back")}
    </Link>
  );
}

function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label={t("common.loading")}>
      <SkeletonBlock className="h-5 w-24" />
      <Card className="px-4 py-5 sm:px-6">
        <SkeletonBlock className="h-3 w-44" />
        <div className="mt-6 grid grid-cols-[1fr_auto_1fr] items-center gap-4">
          {[0, 1].map((i) => (
            <div key={i} className={cn("flex flex-col items-center gap-2", i === 1 && "order-3")}>
              <SkeletonBlock className="h-14 w-14 rounded-full" />
              <SkeletonBlock className="h-4 w-20" />
            </div>
          ))}
          <SkeletonBlock className="order-2 h-10 w-24" />
        </div>
      </Card>
      <SkeletonBlock className="h-11 w-full" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <SkeletonBlock className="h-72" />
        <SkeletonBlock className="h-72" />
      </div>
    </div>
  );
}

function NotFound() {
  return (
    <div className="space-y-4">
      <BackLink />
      <Card>
        <EmptyState
          icon={<SearchX aria-hidden className="h-7 w-7" />}
          title={t("match.notFound.title")}
          body={t("match.notFound.body")}
          action={
            <Link
              to="/matches"
              className="inline-flex min-h-9 items-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              {t("match.notFound.action")}
            </Link>
          }
        />
      </Card>
    </div>
  );
}

function TabBar({
  tabs,
  active,
  onSelect,
  live: isLive,
}: {
  tabs: readonly TabKey[];
  active: TabKey;
  onSelect: (tab: TabKey) => void;
  live: boolean;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  // On a phone the strip scrolls: keep the open tab in sight (the page itself does not move).
  useEffect(() => {
    const list = listRef.current;
    const tab = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!list || !tab) return;
    const l = list.getBoundingClientRect();
    const r = tab.getBoundingClientRect();
    if (r.left < l.left) list.scrollLeft -= l.left - r.left + 16;
    else if (r.right > l.right) list.scrollLeft += r.right - l.right + 16;
  }, [active]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.indexOf(active);
    const next =
      e.key === "ArrowRight"
        ? (i + 1) % tabs.length
        : e.key === "ArrowLeft"
          ? (i - 1 + tabs.length) % tabs.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? tabs.length - 1
              : -1;
    const key = tabs[next];
    if (next < 0 || !key) return;
    e.preventDefault();
    onSelect(key);
    document.getElementById(`match-tab-${key}`)?.focus();
  }

  return (
    <div className="sticky top-14 z-20 -mx-4 bg-background/90 px-4 backdrop-blur">
      <div
        ref={listRef}
        role="tablist"
        aria-label={t("match.tabs.label")}
        onKeyDown={onKeyDown}
        className="flex overflow-x-auto border-b border-border [scrollbar-width:none] sm:gap-1 [&::-webkit-scrollbar]:hidden"
      >
        {tabs.map((key) => {
          const selected = key === active;
          return (
            <button
              key={key}
              id={`match-tab-${key}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`match-panel-${key}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onSelect(key)}
              className={cn(
                "relative flex min-h-11 flex-1 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap px-2 text-[0.8125rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring sm:flex-none sm:px-3 sm:text-sm",
                selected ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {key === "advanced" ? (
                <ShieldCheck aria-hidden className="h-3.5 w-3.5 text-info" />
              ) : null}
              {t(`match.tabs.${key}`)}
              {key === "summary" && isLive ? (
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary" />
              ) : null}
              {selected ? (
                <span
                  aria-hidden
                  className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary"
                />
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function MatchPage({ fixtureId }: { fixtureId: string }) {
  const auth = useAuth();
  const valid = /^\d+$/.test(fixtureId);
  // A finished match does not change minute to minute: no polling once it is over.
  const view = useQuery({
    ...live.matchView(fixtureId),
    enabled: valid,
    refetchInterval: (q) => (q.state.data?.data.match.status_group === "finished" ? false : 60_000),
  });
  const center = useQuery({
    ...live.center(fixtureId),
    enabled: valid,
    refetchInterval: (q) => {
      const group = q.state.data?.data?.status_group;
      return group === "live" ? 30_000 : group === "finished" ? false : 120_000;
    },
  });
  const tabs = auth.showAdmin ? ADMIN_TABS : USER_TABS;
  const [tab, setTab] = useMatchTab(fixtureId, tabs);

  if (!valid) return <NotFound />;
  if (!view.data) {
    if (view.isError) {
      if (view.error instanceof LiveApiError && view.error.status === 404) return <NotFound />;
      return (
        <div className="space-y-4">
          <BackLink />
          <Card>
            <ErrorState error={view.error} onRetry={() => void view.refetch()} />
          </Card>
        </div>
      );
    }
    return <PageSkeleton />;
  }

  const { match, venue, markets } = view.data.data;
  const phase = matchPhase(match);
  const detail = center.data?.data ?? null;
  const states = detail?.live_states.status === "ok" ? detail.live_states.data : [];
  const snapshot = liveSnapshot(states);
  const ctx: MatchCtx = {
    fixtureId,
    match,
    venue,
    markets,
    phase,
    live: snapshot,
    score: shownScore(match, snapshot, phase),
    center: {
      data: detail,
      loading: center.isPending,
      // A failed refresh keeps the last good detail on screen.
      error: center.data ? null : center.isError ? center.error : null,
      status: center.data && !center.data.data ? center.data.status : null,
      retry: () => void center.refetch(),
    },
    showAdmin: auth.showAdmin,
    goTo: setTab,
  };

  let panel: ReactNode;
  switch (tab) {
    case "stats":
      panel = <StatsTab ctx={ctx} />;
      break;
    case "markets":
      panel = <MarketsTab ctx={ctx} />;
      break;
    case "lineups":
      panel = <LineupsTab ctx={ctx} />;
      break;
    case "advanced":
      panel = auth.showAdmin ? <AdvancedTab fixtureId={fixtureId} /> : null;
      break;
    default:
      panel = <SummaryTab ctx={ctx} />;
  }

  return (
    <div className="space-y-4" data-testid="match-center" data-phase={phase}>
      <BackLink />
      <MatchHeader ctx={ctx} />
      <div id="match-tabs-anchor" aria-hidden className="mb-0" />
      <TabBar tabs={tabs} active={tab} onSelect={setTab} live={phase === "live"} />
      <div
        role="tabpanel"
        id={`match-panel-${tab}`}
        aria-labelledby={`match-tab-${tab}`}
        tabIndex={0}
        className="rounded-xl focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {panel}
      </div>
    </div>
  );
}
