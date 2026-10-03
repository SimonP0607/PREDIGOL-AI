/**
 * Home: today at a glance, top to bottom - the best value picks, the two parlays, what
 * is live, the best prices and the next matches. Every block shows only what the API
 * returned; an empty block says why in plain words.
 */
import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { Home, Parlay } from "@/lib/api/v1/types_product";
import { Card, ErrorState, SectionHeader, SkeletonBlock } from "@/product/shared/States";
import { ParlayCard } from "@/product/parlays/ParlayCard";
import { PARLAY_ICON, parlayTitle } from "@/product/parlays/parlayText";
import { BestPrices } from "./BestPrices";
import { HomeHeader } from "./HomeHeader";
import { LiveTiles } from "./LiveTiles";
import { TopPicks } from "./TopPicks";
import { UpcomingList } from "./UpcomingList";

function ParlayBlock({ parlay }: { parlay: Parlay }) {
  const Icon = PARLAY_ICON[parlay.kind];
  return (
    <section data-testid={`home-parlay-${parlay.kind}`}>
      <SectionHeader
        title={parlayTitle(parlay.kind)}
        icon={<Icon aria-hidden className="h-4 w-4 shrink-0 text-gold" />}
        action={{ label: t("home.parlays.seeDetail"), to: "/parlays" }}
      />
      <ParlayCard parlay={parlay} variant="compact" showTitle={false} className="mt-3" />
    </section>
  );
}

function HomeContent({ home }: { home: Home }) {
  return (
    <>
      <TopPicks section={home.top_picks} shadow={home.source === "shadow_preview"} />
      <div className="grid grid-cols-1 items-start gap-9 sm:gap-10 lg:grid-cols-2 lg:gap-6">
        <ParlayBlock parlay={home.daily_parlay} />
        <ParlayBlock parlay={home.multiday_parlay} />
      </div>
      <LiveTiles section={home.live} liveAt={home.data_freshness.live_at} />
      <BestPrices section={home.best_prices} />
      <UpcomingList section={home.upcoming} />
    </>
  );
}

function HomeSkeleton() {
  return (
    <div className="space-y-9 sm:space-y-10" aria-busy="true" aria-label={t("common.loading")}>
      <div>
        <SkeletonBlock className="h-5 w-56" />
        <div className="mt-3 flex gap-3 overflow-hidden md:grid md:grid-cols-2 md:gap-4 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <SkeletonBlock key={i} className="h-56 w-[86%] shrink-0 rounded-xl md:w-auto" />
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-9 lg:grid-cols-2 lg:gap-6">
        {[0, 1].map((i) => (
          <div key={i}>
            <SkeletonBlock className="h-5 w-40" />
            <SkeletonBlock className="mt-3 h-72 rounded-xl" />
          </div>
        ))}
      </div>
      <div>
        <SkeletonBlock className="h-5 w-36" />
        <div className="mt-3 grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <SkeletonBlock key={i} className="h-[5.5rem] rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  );
}

export function HomePage() {
  const preview = usePreviewParam();
  const query = useQuery(live.home(preview));
  const home = query.data?.data;
  return (
    <div className="space-y-9 sm:space-y-10" data-testid="home-page">
      <HomeHeader freshness={home?.data_freshness ?? null} loading={query.isPending} />
      {home ? (
        <HomeContent home={home} />
      ) : query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      ) : (
        <HomeSkeleton />
      )}
    </div>
  );
}
