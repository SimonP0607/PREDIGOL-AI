/**
 * Home: today at a glance, top to bottom - the day's picks and the two parlays as PrediGol
 * recorded them (they stay after kick-off, with their results), what is live, the best
 * prices and the next matches. Every block shows only what the API returned; an empty
 * block says why in plain words.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { live } from "@/lib/api/v1/queries";
import { shiftDay, todayKey } from "@/lib/time";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { Envelope } from "@/lib/api/v1/types";
import type { Home } from "@/lib/api/v1/types_product";
import type { DailyBoard, RecordKind } from "@/lib/api/v1/types_records";
import { Card, ErrorState, SectionHeader, SkeletonBlock } from "@/product/shared/States";
import { PARLAY_ICON, parlayTitle } from "@/product/parlays/parlayText";
import { DailySetBlock } from "@/product/records/DailySetBlock";
import { ParlayRecordCard } from "@/product/records/ParlayRecordCard";
import { BestPrices } from "./BestPrices";
import { HomeHeader } from "./HomeHeader";
import { LiveTiles } from "./LiveTiles";
import { UpcomingList } from "./UpcomingList";

type BoardQuery = UseQueryResult<Envelope<DailyBoard>>;

function ParlayBlock({ kind, board }: { kind: RecordKind; board: BoardQuery }) {
  const Icon = PARLAY_ICON[kind];
  const data = board.data?.data;
  return (
    <section data-testid={`home-parlay-${kind}`}>
      <SectionHeader
        title={parlayTitle(kind)}
        icon={<Icon aria-hidden className="h-4 w-4 shrink-0 text-gold" />}
        action={{ label: t("home.parlays.seeDetail"), to: "/parlays" }}
      />
      {data ? (
        <ParlayRecordCard
          kind={kind}
          parlay={kind === "daily" ? data.daily_parlay : data.multiday_parlay}
          evaluation={data.evaluation_mode}
          variant="compact"
          showTitle={false}
          className="mt-3"
        />
      ) : board.isError ? (
        <Card className="mt-3">
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        </Card>
      ) : (
        <SkeletonBlock className="mt-3 h-72 rounded-xl" />
      )}
    </section>
  );
}

function HomeContent({
  home,
  board,
  yesterday,
}: {
  home: Home;
  board: BoardQuery;
  yesterday: BoardQuery;
}) {
  // Yesterday's picks do not vanish at midnight while one of them is still to finish or settle.
  const openYesterday = (yesterday.data?.data?.set?.items ?? []).some(
    (i) => i.status === "PENDING",
  );
  return (
    <>
      {openYesterday ? (
        <DailySetBlock query={yesterday} variant="home" title={t("records.daily.yesterdayOpen")} />
      ) : null}
      <DailySetBlock query={board} variant="home" />
      <div className="grid grid-cols-1 items-start gap-9 sm:gap-10 lg:grid-cols-2 lg:gap-6">
        <ParlayBlock kind="daily" board={board} />
        <ParlayBlock kind="multiday" board={board} />
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
        {/* As the live tiles lay out: one a row on a phone (three of them stand for the list there). */}
        <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2 sm:gap-3 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <SkeletonBlock
              key={i}
              className={cn("h-[5.5rem] rounded-xl", i >= 3 && "hidden sm:block")}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function HomePage() {
  const preview = usePreviewParam();
  const query = useQuery(live.home(preview));
  const board = useQuery(live.daily(preview));
  const yesterday = useQuery(live.daily(preview, shiftDay(todayKey("America/Bogota"), -1)));
  const home = query.data?.data;
  return (
    <div className="space-y-9 sm:space-y-10" data-testid="home-page">
      <HomeHeader freshness={home?.data_freshness ?? null} loading={query.isPending} />
      {home ? (
        <HomeContent home={home} board={board} yesterday={yesterday} />
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
