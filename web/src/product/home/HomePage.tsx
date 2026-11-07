/**
 * Inicio (plan UX, A9 and A10; section 24; closing plan 3.2): «qué hay hoy para mí» in five seconds, with or without picks, in
 * two layers - each a landmark named by its band:
 *
 *   Para ti    only once the reader chose a league, a team, a player or a market (GET /me/today): their next matches, their
 *              news, their players (starter, bench, left out, missing or doubtful), what is at stake, the day's picks that are
 *              theirs - or that none is -, their notices and their results (./ParaTi)
 *   PrediGol   the same for everyone, whatever they follow; nothing of the product is hidden. Top to bottom:
 *
 *     1  Hoy en las ligas sugeridas   today's matches, in play first, with the forecast labelled and a line of the reading
 *     2  Picks del día                the published set with its real state - or why there is none - and PrediGol's parlays
 *     3  Partidos relevantes          the matches in play with a reason the server chose (final, second leg, a fight for the
 *                                     title / Europe / relegation / promotion, a comeback) - only when there are some
 *     4  Noticias                     the confirmed or probable news of today's suggested matches (only with content)
 *     5  Qué se juega                 the matches of the next 36 hours with something at stake, one sentence each (only
 *                                     with content)
 *     6  En vivo, Últimos resultados  what else is in play, and the last 24 hours' results
 *
 *   Blocks 1 and 4 are the reader's own - and sit in «Para ti», with their own «Qué se juega» - once they chose leagues or
 *   teams; the suggested ones are PrediGol's and are never called «tuyas». Without favourites, a discreet
 *   «Elige tus favoritos» opens the PrediGol layer. Every block loads, fails and retries on its own: a failure never reads as
 *   an empty list, and an empty block says why in plain words. Nothing here calls the AI.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { ChevronRight, Layers, Radio } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { live } from "@/lib/api/v1/queries";
import { shiftDay, todayKey } from "@/lib/time";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import type { Envelope } from "@/lib/api/v1/types";
import type { Home } from "@/lib/api/v1/types_product";
import type { DailyBoard, ParlayRecord, RecordKind } from "@/lib/api/v1/types_records";
import { Card, ErrorState, SectionHeader, SkeletonBlock } from "@/product/shared/States";
import { PARLAY_ICON, parlayTitle } from "@/product/parlays/parlayText";
import { KindSwitch, kindVisibility } from "@/product/parlays/KindSwitch";
import { DailySetBlock } from "@/product/records/DailySetBlock";
import { noPickLoad } from "@/product/records/noPick";
import { ParlayRecordCard } from "@/product/records/ParlayRecordCard";
import { HomeHeader } from "./HomeHeader";
import { LiveTiles } from "./LiveTiles";
import { NewsBlock } from "./NewsBlock";
import { SuggestionCard } from "@/product/favorites/SuggestionCard";
import { ContextBlock, TodayBlock } from "./TodayBlocks";
import { AtStakeBlock, RelevantNowBlock } from "./HomeStakes";
import { ResultsBlock } from "./ResultsBlock";
import { layersOf } from "./layers";
import { ChoosePrompt, ForYouEdit, ForYouPart, Layer } from "./ParaTi";

type BoardQuery = UseQueryResult<Envelope<DailyBoard>>;
type HomeQuery = UseQueryResult<Envelope<Home>>;

function ParlayBlock({
  kind,
  board,
  active,
}: {
  kind: RecordKind;
  board: BoardQuery;
  /** The kind a phone has open (./KindSwitch): the other one waits, hidden, and shows from md up. */
  active: RecordKind;
}) {
  const Icon = PARLAY_ICON[kind];
  const data = board.data?.data;
  return (
    <section data-testid={`home-parlay-${kind}`} className={kindVisibility(kind, active)}>
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
  const [active, setActive] = useState<RecordKind>("daily");
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
      <KindSwitch active={active} onChange={setActive} className="-mb-5" />
      <ParlayBlock kind="daily" board={board} active={active} />
      <ParlayBlock kind="multiday" board={board} active={active} />
    </div>
  );
}

/** What is in play everywhere (GET /home), with its own loading and failure. */
function LiveNow({ query }: { query: HomeQuery }) {
  const home = query.data?.data;
  if (home) {
    return (
      <LiveTiles
        section={home.live}
        liveAt={home.data_freshness.live_at}
        elsewhere={(home.relevant?.data.length ?? 0) > 0}
      />
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

/**
 * Coming back to the app (a PWA from the background, a tab left open) reloads what Inicio shows once it is older than the
 * client's 15 s (plan Inicio, 1.4, F9): the router turns focus reloads off for the rest of the app, Inicio asks for them.
 */
const ON_RETURN = { refetchOnWindowFocus: true } as const;

export function HomePage() {
  const preview = usePreviewParam();
  const reader = useAuth().user?.role === "USER";
  const home = useQuery({ ...live.home(preview), ...ON_RETURN });
  const today = useQuery({ ...live.today, ...ON_RETURN });
  const news = useQuery({ ...live.todayNews, ...ON_RETURN });
  const me = useQuery({ ...live.meToday, ...ON_RETURN, enabled: reader });
  const board = useQuery({ ...live.daily(preview), ...ON_RETURN });
  const yesterday = useQuery({
    ...live.daily(preview, shiftDay(todayKey("America/Bogota"), -1)),
    ...ON_RETURN,
  });
  const now = Date.now();
  // Yesterday's picks do not vanish at midnight while one of them is still to finish or settle.
  const openYesterday = (yesterday.data?.data?.set?.items ?? []).some(
    (i) => i.status === "PENDING",
  );
  // Two layers (closing plan 3.2): «Para ti» only once the reader chose something; PrediGol is the same for everyone. The
  // leagues and the team suggested until they choose are PrediGol's, labelled as suggested - never «tuyas».
  const layers = layersOf(me.data, today.data?.data);
  const teams = layers.mine && (today.data?.data?.following?.teams.length ?? 0) > 0;
  const common = { query: today, now } as const;
  return (
    <div className="space-y-9 sm:space-y-10" data-testid="home-page">
      <HomeHeader freshness={home.data?.data?.data_freshness ?? null} loading={home.isPending} />
      {layers.forYou ? (
        <Layer
          id="for-you"
          title={t("home.layers.forYou")}
          hint={t("home.layers.forYouHint")}
          tone="primary"
          action={<ForYouEdit />}
        >
          {layers.mine ? (
            <TodayBlock {...common} suggestion={<SuggestionCard />} choose={false} />
          ) : null}
          {layers.mine ? <NewsBlock query={news} now={now} /> : null}
          <ForYouPart part="players" query={me} board={board} teams={teams} now={now} />
          {layers.mine ? <ContextBlock {...common} /> : null}
          <ForYouPart part="picks" query={me} board={board} teams={teams} now={now} />
          <ForYouPart part="notices" query={me} board={board} teams={teams} now={now} />
        </Layer>
      ) : null}
      <Layer
        id="predigol"
        title={t("home.layers.predigol")}
        hint={t("home.layers.predigolHint")}
        tone="gold"
      >
        {layers.prompt && reader ? <ChoosePrompt /> : null}
        {layers.mine ? null : (
          <TodayBlock
            {...common}
            suggestion={<SuggestionCard />}
            choose={!(layers.prompt && reader)}
          />
        )}
        {openYesterday ? (
          <DailySetBlock
            query={yesterday}
            variant="home"
            title={t("records.daily.yesterdayOpen")}
          />
        ) : null}
        <DailySetBlock
          query={board}
          variant="home"
          noPick={noPickLoad(today, (d) => d.no_pick.data)}
        />
        <HomeParlays board={board} />
        <RelevantNowBlock query={home} />
        {layers.mine ? null : <NewsBlock query={news} now={now} />}
        <AtStakeBlock query={home} now={now} />
        <LiveNow query={home} />
        <ResultsBlock query={home} now={now} />
      </Layer>
    </div>
  );
}
