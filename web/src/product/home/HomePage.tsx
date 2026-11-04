/**
 * Inicio (plan UX, A9 and A10; section 24): «qué hay hoy para mí» in five seconds, with or without picks. Top to bottom:
 *
 *   1  Hoy en las ligas sugeridas   today's matches, in play first, with the forecast labelled and a line of the reading
 *   2  Picks del día                the published set with its real state - or why there is none - and PrediGol's parlays
 *   3  Partidos relevantes          today's other matches with a reading (only when there are some)
 *   4  Noticias                     the confirmed or probable news of today's suggested matches (only with content)
 *   5  Qué se juega                 table or tie, rest and next match of the next suggested matches (only with content)
 *   6  Resultados                   the suggested leagues' last 48 hours
 *
 * then what is in play everywhere and the best prices, as before. Every block loads, fails and retries on its own: a
 * failure never reads as an empty list, and an empty block says why in plain words. Nothing here calls the AI.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, Layers, Radio } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { live } from "@/lib/api/v1/queries";
import { shiftDay, todayKey } from "@/lib/time";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { Envelope } from "@/lib/api/v1/types";
import type { Home } from "@/lib/api/v1/types_product";
import type { DailyBoard, ParlayRecord, RecordKind } from "@/lib/api/v1/types_records";
import { Card, ErrorState, SectionHeader, SkeletonBlock } from "@/product/shared/States";
import { PARLAY_ICON, parlayTitle } from "@/product/parlays/parlayText";
import { DailySetBlock } from "@/product/records/DailySetBlock";
import { noPickLoad } from "@/product/records/noPick";
import { ParlayRecordCard } from "@/product/records/ParlayRecordCard";
import { BestPrices } from "./BestPrices";
import { HomeHeader } from "./HomeHeader";
import { LiveTiles } from "./LiveTiles";
import { NewsBlock } from "./NewsBlock";
import { SuggestionCard } from "@/product/favorites/SuggestionCard";
import { ContextBlock, RelevantBlock, ResultsBlock, TodayBlock } from "./TodayBlocks";

type BoardQuery = UseQueryResult<Envelope<DailyBoard>>;
type HomeQuery = UseQueryResult<Envelope<Home>>;

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

function built(p: ParlayRecord | null | undefined): boolean {
  return Boolean(p && p.legs.length > 0);
}

/**
 * PrediGol's two parlays, after the day's picks. Neither built: one honest line and the way to the Parlays page (each
 * card's own empty state is there), never two empty cards in the way of the day's matches.
 */
function HomeParlays({ board }: { board: BoardQuery }) {
  const data = board.data?.data;
  if (data && !built(data.daily_parlay) && !built(data.multiday_parlay)) {
    return (
      <p
        data-empty-state
        data-testid="home-parlays-none"
        className="flex items-start gap-2.5 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
      >
        <Layers aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
        <span className="min-w-0">
          {t("home.parlaysNone")}{" "}
          <Link
            to="/parlays"
            className="tap-y relative inline-flex items-center gap-0.5 whitespace-nowrap font-medium text-primary hover:underline"
          >
            {t("home.parlaysLink")}
            <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        </span>
      </p>
    );
  }
  return (
    <div className="grid grid-cols-1 items-start gap-9 sm:gap-10 lg:grid-cols-2 lg:gap-6">
      <ParlayBlock kind="daily" board={board} />
      <ParlayBlock kind="multiday" board={board} />
    </div>
  );
}

/** What is in play everywhere and the best prices (GET /home), with their own loading and failure. */
function LiveAndPrices({ query }: { query: HomeQuery }) {
  const home = query.data?.data;
  if (home) {
    return (
      <>
        <LiveTiles section={home.live} liveAt={home.data_freshness.live_at} />
        <BestPrices section={home.best_prices} />
      </>
    );
  }
  return (
    <section data-testid="home-live">
      <SectionHeader
        title={t("home.live.title")}
        icon={<Radio aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
        action={{ label: t("common.seeAll"), to: "/live" }}
      />
      {query.isError ? (
        <Card className="mt-3">
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      ) : (
        // As the live tiles lay out: one a row on a phone (three of them stand for the list there).
        <div
          aria-busy="true"
          aria-label={t("common.loading")}
          className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2 sm:gap-3 lg:grid-cols-3"
        >
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <SkeletonBlock
              key={i}
              className={cn("h-[5.5rem] rounded-xl", i >= 3 && "hidden sm:block")}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export function HomePage() {
  const preview = usePreviewParam();
  const home = useQuery(live.home(preview));
  const today = useQuery(live.today);
  const news = useQuery(live.todayNews);
  const board = useQuery(live.daily(preview));
  const yesterday = useQuery(live.daily(preview, shiftDay(todayKey("America/Bogota"), -1)));
  const now = Date.now();
  // Yesterday's picks do not vanish at midnight while one of them is still to finish or settle.
  const openYesterday = (yesterday.data?.data?.set?.items ?? []).some(
    (i) => i.status === "PENDING",
  );
  return (
    <div className="space-y-9 sm:space-y-10" data-testid="home-page">
      <HomeHeader freshness={home.data?.data?.data_freshness ?? null} loading={home.isPending} />
      <TodayBlock query={today} now={now} suggestion={<SuggestionCard />} />
      {openYesterday ? (
        <DailySetBlock query={yesterday} variant="home" title={t("records.daily.yesterdayOpen")} />
      ) : null}
      <DailySetBlock
        query={board}
        variant="home"
        noPick={noPickLoad(today, (d) => d.no_pick.data)}
      />
      <HomeParlays board={board} />
      <RelevantBlock query={today} now={now} />
      <NewsBlock query={news} now={now} />
      <ContextBlock query={today} now={now} />
      <ResultsBlock query={today} now={now} />
      <LiveAndPrices query={home} />
    </div>
  );
}
