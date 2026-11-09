/**
 * Every market we price for the match: before kick-off by category (plan Partidos y Match Center, F4b: M1-M4), and the
 * in-play prices in their own group while it is played (unchanged).
 *
 * Before kick-off: a header with the bookmakers and the last update - never the captures, which are the owner's, in
 * Avanzado / Auditoría -; chips for «Destacados» (1X2, over/under 2.5, both teams score: the match's own prices, loaded with
 * it) and each category the catalogue has prices in force for, read when its chip is opened and never in the match's
 * 60-second poll; one fold per market, the first one open. The five settled markets are chosen the Cuotas way (REVIEW
 * PREDIGOL, point 6: a tap in or out of "Mi parlay", the bookmark saves it); the catalogue's other markets are shown only.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronRight, LineChart } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtLine } from "@/lib/i18n/format";
import { v1 } from "@/lib/api/v1/client";
import { live as queries } from "@/lib/api/v1/queries";
import type { MarketOrder } from "@/lib/api/v1/types_personal";
import type { CatalogCategory } from "@/lib/api/v1/types_market_catalog";
import { useAuth } from "@/lib/auth/AuthProvider";
import { hintProps } from "@/components/system/tapHint";
import { track } from "@/lib/track";
import { formatDateTime } from "@/lib/time";
import { GlossaryLink, GlossaryTerm } from "@/components/system/GlossaryTerm";
import { marketName } from "@/product/shared/markets";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import { ChipGroup } from "@/product/picks/Controls";
import type { MatchCtx } from "./context";
import {
  ageLevel,
  latestCapture,
  liveMarkets,
  marketBoards,
  SELECTIONS,
  tileLabel,
  visibleRows,
  type BestPrice,
  type LiveMarket,
  type LivePrice,
  type MarketBoard,
  type PriceRow,
} from "./model";
import { priceChooser, type Choose } from "./choose";
import { LiveOdds, LiveTile, PriceInline, PriceTile } from "./prices";
import {
  boardView,
  catalogView,
  FEATURED_OU_LINE,
  featuredBoards,
  headerBooks,
  later,
  type MarketsView,
  type MarketView,
} from "./marketCatalog";
import { MarketFold } from "./MarketFold";
import { Block, CenterSection, FreshnessLabel, MoreButton, SectionNote } from "./ui";
import { FollowCatalogMarket, FollowMarket } from "@/product/favorites/FollowExtras";
import { useFollowedCatalog } from "@/product/favorites/useFollowedCatalog";
import { followableMarket, followedFirst } from "@/product/favorites/model";
import { orderBoards, orderSentence } from "./marketOrder";
import { useMarketTarget } from "./useMarketTarget";
import { prefersReducedMotion } from "@/product/shared/motion";

type Sides = { home: string; away: string };

const LINE_MARKETS = new Set(["OU", "AH"]);

/** «Seguir» beside a market PrediGol offers to follow (closing plan 3.1); nothing for another. */
function FollowBoard({ market }: { market: string }) {
  const key = followableMarket(market);
  return key ? <FollowMarket market={key} /> : null;
}

/** «Seguir» beside a market of the catalogue that is not one of the five (CUOTAS, BE-025), by the catalogue's own key. */
function FollowCatalog({ catalogKey }: { catalogKey: string }) {
  return <FollowCatalogMarket catalogKey={catalogKey} />;
}

function Books({ count }: { count: number }) {
  return (
    <span className="text-caption text-subtle-foreground">
      {t("match.markets.books", { count })}
    </span>
  );
}

function LineTag({ value, main }: { value: number; main: boolean }) {
  return (
    <span
      className={cn(
        "numeric w-10 shrink-0 text-xs",
        main ? "font-semibold text-primary" : "text-muted-foreground",
      )}
    >
      {fmtLine(value, true)}
    </span>
  );
}

function GroupHeader({ id, title, right }: { id: string; title: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-x-3 gap-y-1">
      <h2
        id={id}
        className="flex items-center gap-2 font-display text-base font-semibold tracking-tight sm:text-lg"
      >
        {title}
      </h2>
      {right ? <div className="flex items-center gap-2">{right}</div> : null}
    </div>
  );
}

/** Rows of a line market (over/under, handicap), the main line first in view. */
function LinesTable<T>({
  market,
  rows,
  main,
  sides,
  cell,
}: {
  market: string;
  rows: Array<PriceRow<T>>;
  main: number;
  sides: Sides;
  cell: (value: T | null, prefix: ReactNode) => ReactNode;
}) {
  const [all, setAll] = useState(false);
  const shown = visibleRows(rows, main, all);
  const mainKey = rows[main]?.key;
  const isOU = market === "OU";
  return (
    <>
      <table className="w-full table-fixed">
        <thead>
          <tr className="text-caption text-subtle-foreground">
            {isOU ? (
              <th scope="col" className="w-14 pb-1.5 text-left font-medium">
                <GlossaryTerm term="line">{t("match.markets.line")}</GlossaryTerm>
              </th>
            ) : null}
            <th scope="col" className="pb-1.5 pr-2 text-left font-medium">
              <span className="block break-words leading-tight">
                {isOU ? t("match.markets.over") : sides.home}
              </span>
            </th>
            <th scope="col" className="pb-1.5 text-left font-medium">
              <span className="block break-words leading-tight">
                {isOU ? t("match.markets.under") : sides.away}
              </span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {shown.map((r) => {
            const isMain = r.key === mainKey;
            const line = r.line ?? 0;
            return (
              <tr
                key={r.key}
                className={cn(isMain && "bg-elevated/50")}
                title={isMain ? t("match.markets.mainLineHelp") : undefined}
              >
                {isOU ? (
                  <th scope="row" className="py-2 pl-1 text-left font-normal">
                    <span className={cn("numeric text-sm", isMain && "font-semibold text-primary")}>
                      {fmtLine(line)}
                    </span>
                    {isMain ? (
                      <span className="sr-only"> ({t("match.markets.mainLine")})</span>
                    ) : null}
                  </th>
                ) : null}
                <td className="py-2 pl-1 pr-2">
                  {cell(r.cells[0] ?? null, isOU ? null : <LineTag value={line} main={isMain} />)}
                </td>
                <td className="py-2">
                  {cell(r.cells[1] ?? null, isOU ? null : <LineTag value={-line} main={isMain} />)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length > shown.length || all ? (
        <MoreButton expanded={all} onClick={() => setAll((v) => !v)} className="mt-1">
          {all ? t("match.markets.mainLines") : t("match.markets.allLines", { count: rows.length })}
        </MoreButton>
      ) : null}
    </>
  );
}

/** A market's best in-play prices across bookmakers (the live group: unchanged). */
function BookCard({ board, sides }: { board: MarketBoard; sides: Sides }) {
  const sels = SELECTIONS[board.market] ?? [];
  const row = board.rows[0];
  return (
    <Block
      level={3}
      title={marketName(board.market)}
      right={
        <span className="flex items-center gap-2">
          <FollowBoard market={board.market} />
          <Books count={board.books} />
        </span>
      }
    >
      {LINE_MARKETS.has(board.market) ? (
        <LinesTable<BestPrice>
          market={board.market}
          rows={board.rows}
          main={board.main}
          sides={sides}
          cell={(p, prefix) => <PriceInline price={p} prefix={prefix} />}
        />
      ) : (
        <div className={cn("grid gap-2", sels.length === 3 ? "grid-cols-3" : "grid-cols-2")}>
          {sels.map((sel, i) => (
            <PriceTile
              key={sel}
              label={tileLabel(board.market, sel, null, sides)}
              price={row?.cells[i] ?? null}
              showBooks
            />
          ))}
        </div>
      )}
    </Block>
  );
}

function LiveCard({ market, sides }: { market: LiveMarket; sides: Sides }) {
  const sels = SELECTIONS[market.market] ?? [];
  const row = market.rows[0];
  return (
    <Block level={3} title={marketName(market.market)}>
      {LINE_MARKETS.has(market.market) ? (
        <LinesTable<LivePrice>
          market={market.market}
          rows={market.rows}
          main={market.main}
          sides={sides}
          cell={(p, prefix) => (
            <span className="flex items-center gap-1.5">
              {prefix}
              <LiveOdds price={p} size="sm" />
            </span>
          )}
        />
      ) : (
        <div className={cn("grid gap-2", sels.length === 3 ? "grid-cols-3" : "grid-cols-2")}>
          {sels.map((sel, i) => (
            <LiveTile
              key={sel}
              label={tileLabel(market.market, sel, null, sides)}
              price={row?.cells[i] ?? null}
            />
          ))}
        </div>
      )}
    </Block>
  );
}

/**
 * Single-line markets in a row of three on wide screens; line markets side by side. The order given is kept inside each
 * group, and the group of the first market comes first (the reader's own market first, plan UX, B2). A tap on any control
 * of a market (a price, its bookmakers, all its lines) is that market consulted.
 */
function CardGrid({
  items,
  onConsult,
}: {
  items: Array<{ key: string; lines: boolean; node: ReactNode }>;
  onConsult?: ((market: string) => void) | undefined;
}) {
  const single = items.filter((x) => !x.lines);
  const lines = items.filter((x) => x.lines);
  const cell = (x: { key: string; node: ReactNode }) => (
    <div
      key={x.key}
      className="min-w-0"
      data-market={x.key}
      onClickCapture={
        onConsult
          ? (e) => {
              if (e.target instanceof Element && e.target.closest("button, a, select"))
                onConsult(x.key);
            }
          : undefined
      }
    >
      {x.node}
    </div>
  );
  const singles = single.length ? (
    <div key="single" className="grid gap-4 lg:grid-cols-3">
      {single.map(cell)}
    </div>
  ) : null;
  const lined = lines.length ? (
    <div key="lines" className="grid items-start gap-4 lg:grid-cols-2">
      {lines.map(cell)}
    </div>
  ) : null;
  return (
    <div className="space-y-4" data-testid="markets-grid">
      {items[0]?.lines ? [lined, singles] : [singles, lined]}
    </div>
  );
}

/**
 * The rule said (plan UX, B2): «Primero, los mercados que más consultas: Más/Menos de goles (3) y Ambos marcan (2).» with
 * the way back to the usual order - or, while the reader keeps the usual one, the way back to theirs. Its help (a tap)
 * says what is counted and that probabilities and prices are the same for everyone.
 */
function MarketOrderNote({ order }: { order: MarketOrder }) {
  const qc = useQueryClient();
  const change = useMutation({
    mutationFn: (common: boolean) => v1.setMarketOrder(common),
    onSuccess: (view) => qc.setQueryData(queries.personal.queryKey, view),
    onError: () => toast(t("match.markets.order.failed")),
  });
  if (order.views.length === 0) return null;
  const button = (common: boolean, label: string, testId: string) => (
    <button
      type="button"
      disabled={change.isPending}
      onClick={() => change.mutate(common)}
      data-testid={testId}
      className="tap-y relative ml-1 inline-flex min-h-8 items-center font-medium text-primary hover:underline disabled:opacity-60"
    >
      {label}
    </button>
  );
  if (order.common) {
    return (
      <p
        className="mb-3 text-xs text-muted-foreground"
        data-testid="markets-order"
        data-order="usual"
      >
        {t("match.markets.order.usual")}
        {button(false, t("match.markets.order.mineButton"), "markets-order-mine")}
      </p>
    );
  }
  return (
    <p
      className="mb-3 text-xs text-muted-foreground"
      data-testid="markets-order"
      data-order="mine"
      {...hintProps(
        t("match.markets.order.help", { days: order.window_days, min: order.min_views }),
      )}
    >
      {orderSentence(order.views)}
      {button(true, t("match.markets.order.usualButton"), "markets-order-usual")}
    </p>
  );
}

/**
 * The reader's markets (GET /me/personal, plan UX, B2) and what records one consulted - once per market and visit
 * (``market_viewed``). The owner's console account keeps the usual order, and nothing of theirs is recorded anyway.
 */
function useMarketOrder(fixtureId: string) {
  const reader = useAuth().user?.role === "USER";
  const personal = useQuery({ ...queries.personal, enabled: reader });
  const order = reader && personal.data?.personalization ? personal.data.markets : null;
  const seen = useRef(new Set<string>());
  const consult = useCallback(
    (market: string) => {
      if (!reader || seen.current.has(market)) return;
      seen.current.add(market);
      track("market_viewed", { market, match_id: Number(fixtureId) });
    },
    [reader, fixtureId],
  );
  return { order, first: order?.first ?? [], consult };
}

function LiveGroup({
  ctx,
  sides,
  first,
  onConsult,
}: {
  ctx: MatchCtx;
  sides: Sides;
  first: readonly string[];
  onConsult: (market: string) => void;
}) {
  const quotes = ctx.markets.status === "ok" ? ctx.markets.data : [];
  const books = orderBoards(marketBoards(quotes, "live"), first);
  const feed = ctx.center.data?.live_odds.status === "ok" ? ctx.center.data.live_odds.data : [];
  const inPlay = orderBoards(liveMarkets(feed), first);
  const at =
    books.length > 0
      ? latestCapture(quotes, "live")
      : inPlay.reduce<string | null>((acc, x) => (x.at && (!acc || x.at > acc) ? x.at : acc), null);
  return (
    <section aria-labelledby="markets-live">
      <GroupHeader
        id="markets-live"
        title={
          <>
            <span aria-hidden className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
            </span>
            {t("match.markets.live")}
          </>
        }
        right={at ? <FreshnessLabel at={at} level={ageLevel(at, 3, 10)} /> : null}
      />
      {books.length > 0 ? (
        <CardGrid
          items={books.map((b) => ({
            key: b.market,
            lines: LINE_MARKETS.has(b.market),
            node: <BookCard board={b} sides={sides} />,
          }))}
          onConsult={onConsult}
        />
      ) : (
        <CenterSection
          center={ctx.center}
          pick={(c) => c.live_odds}
          empty={() => <SectionNote>{t("match.liveOdds.none")}</SectionNote>}
        >
          {() =>
            inPlay.length > 0 ? (
              <>
                <CardGrid
                  items={inPlay.map((m) => ({
                    key: m.market,
                    lines: LINE_MARKETS.has(m.market),
                    node: <LiveCard market={m} sides={sides} />,
                  }))}
                  onConsult={onConsult}
                />
                <p className="mt-2 text-caption text-subtle-foreground">
                  {t("match.markets.liveNote")}
                </p>
              </>
            ) : (
              <SectionNote>{t("match.liveOdds.none")}</SectionNote>
            )
          }
        </CenterSection>
      )}
    </section>
  );
}

/**
 * A list of folds, the first one open. A tap on a price, its bookmakers or its lines of one of the five is that market
 * consulted (plan UX, B2); opening or closing a fold is not.
 */
type Follow = (market: string, scope?: "catalog") => ReactNode;

const followBoard: Follow = (market, scope) =>
  scope === "catalog" ? <FollowCatalog catalogKey={market} /> : <FollowBoard market={market} />;

/** Brings the element it sits in into view, once (a smooth scroll, unless the reader asked for reduced motion). */
function ScrollIntoView() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    ref.current?.parentElement?.scrollIntoView({
      block: "start",
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, []);
  return <span ref={ref} hidden />;
}

function FoldList({
  views,
  choose,
  onConsult,
  follow,
  testId,
  target,
}: {
  views: MarketView[];
  choose?: Choose | undefined;
  onConsult?: ((market: string) => void) | undefined;
  follow: Follow;
  testId: string;
  /** The catalogue key a link from Cuotas names: that market is open and in view; the first one only without it. */
  target?: string | undefined;
}) {
  const named = target !== undefined && views.some((v) => v.key === target);
  return (
    <div className="grid items-start gap-3 lg:grid-cols-2" data-testid={testId}>
      {views.map((v, i) => (
        <div
          key={v.id}
          className={cn(
            "min-w-0 scroll-mt-28",
            named && v.key === target && "rounded-xl ring-1 ring-primary/40",
          )}
          data-market={v.id}
          data-target={named && v.key === target ? "true" : undefined}
          onClickCapture={
            onConsult && v.parlay
              ? (e) => {
                  const el = e.target instanceof Element ? e.target : null;
                  if (el?.closest("button, a, select") && !el.closest("[data-fold-toggle]"))
                    onConsult(v.parlay ?? v.id);
                }
              : undefined
          }
        >
          <MarketFold
            view={v}
            choose={choose}
            defaultOpen={named ? v.key === target : i === 0}
            follow={v.parlay ? follow(v.parlay) : v.key ? follow(v.key, "catalog") : null}
          />
          {named && v.key === target ? <ScrollIntoView /> : null}
        </div>
      ))}
    </div>
  );
}

/** One category of the catalogue, read when its chip is opened (cached by the query afterwards). */
export function CategoryPanel({
  ctx,
  category,
  sides,
  choose,
  onConsult,
  follow,
  target,
  followed = [],
}: {
  ctx: MatchCtx;
  category: CatalogCategory;
  sides: Sides;
  choose: Choose | undefined;
  onConsult: (market: string) => void;
  follow: Follow;
  /** The catalogue key a link names, when it is in this category. */
  target?: string | undefined;
  /** The catalogue markets the reader follows, in their order: they go first (only the order changes). */
  followed?: readonly string[];
}) {
  const q = useQuery(queries.matchMarketCatalog(ctx.fixtureId, category));
  if (q.isPending) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label={t("match.catalog.loading")}>
        <SkeletonBlock className="h-14" />
        <SkeletonBlock className="h-14" />
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="rounded-xl border border-border bg-card" data-testid="markets-category-error">
        <p className="px-4 pt-3 text-xs text-muted-foreground">{t("match.catalog.error")}</p>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-3" />
      </div>
    );
  }
  const views = followedFirst(
    (q.data?.data?.markets ?? []).map((m) => catalogView(m, sides)),
    followed,
  );
  if (views.length === 0)
    return <SectionNote status="empty">{t("match.catalog.empty")}</SectionNote>;
  const shownOnly = views.some((v) => v.parlay === null);
  return (
    <>
      {shownOnly ? (
        <p className="mb-3 text-xs text-muted-foreground" data-testid="markets-shown-only">
          {t("match.catalog.shownOnly")}
        </p>
      ) : null}
      <FoldList
        views={views}
        choose={choose}
        onConsult={onConsult}
        follow={follow}
        testId="markets-category"
        target={target}
      />
    </>
  );
}

/**
 * The prices before kick-off (shown in every phase: «Cuotas antes del inicio» once it has started). `order`, `first` and
 * `onConsult` are the reader's market order and what records a market consulted (useMarketOrder).
 */
export function PrematchMarkets({
  ctx,
  order,
  first,
  onConsult: consult,
  follow = followBoard,
  followed = [],
}: {
  ctx: MatchCtx;
  order: MarketOrder | null;
  first: readonly string[];
  onConsult: (market: string) => void;
  /** «Seguir» beside each of the five; it reads the reader's account (a test draws none). */
  follow?: Follow;
  /** The catalogue markets the reader follows, in their order (they go first in a category). */
  followed?: readonly string[];
}) {
  const { markets, phase, match: m } = ctx;
  const sides = { home: m.home.name, away: m.away.name };
  const quotes = markets.status === "ok" ? markets.data : [];
  const before = phase === "scheduled";
  const choose = priceChooser(ctx);
  // Every bookmaker's price of the five («Ver todas las casas» of the highlights): its own query, not the match's poll.
  const allQ = useQuery(queries.matchMarkets(ctx.fixtureId));
  const all = allQ.data?.data?.selections ?? null;
  // The categories with prices in force (no markets): when the tab opens, never in the match's poll.
  const catalogQ = useQuery(queries.matchMarketCatalog(ctx.fixtureId));
  const categories = catalogQ.data?.data?.categories ?? null;
  const resultInCatalog = catalogQ.isError
    ? false
    : categories
      ? categories.some((c) => c.key === "result")
      : null;
  const prematch = orderBoards(marketBoards(quotes, "prematch"), first);
  const featured = featuredBoards(prematch, resultInCatalog).map((b) =>
    boardView(b, all, sides, b.market === "OU" ? FEATURED_OU_LINE : undefined),
  );
  const matchBooks = new Set(
    quotes.filter((q) => q.source === "prematch").map((q) => q.bookmaker_id),
  ).size;
  const books = headerBooks(matchBooks, categories);
  const updated = later(latestCapture(quotes, "prematch"), catalogQ.data?.data?.checked_at);
  const views: MarketsView[] = [
    ...(featured.length > 0 ? (["featured"] as const) : []),
    ...(categories ?? []).map((c) => c.key),
  ];
  // A link from Cuotas names a market: its category opens first, unless the reader picks another chip.
  const linked = useMarketTarget();
  const [picked, setPicked] = useState<MarketsView | null>(null);
  const wanted: MarketsView = picked ?? linked?.category ?? "featured";
  const view = views.includes(wanted) ? wanted : (views[0] ?? "featured");

  return (
    <section aria-labelledby="markets-pre">
      <GroupHeader
        id="markets-pre"
        title={before ? t("match.markets.prematch") : t("match.markets.prematchPlayed")}
        right={
          views.length > 0 ? (
            <span
              className="flex flex-wrap items-center gap-x-2 text-caption text-muted-foreground"
              data-testid="markets-header"
            >
              {books > 0 ? <Books count={books} /> : null}
              {updated ? (
                before ? (
                  <FreshnessLabel at={updated} level={ageLevel(updated, 60, 360)} />
                ) : (
                  <span>{t("match.markets.lastCapture", { when: formatDateTime(updated) })}</span>
                )
              ) : null}
            </span>
          ) : null
        }
      />
      {views.length > 0 ? (
        <>
          <p className="-mt-1.5 mb-3 text-xs text-muted-foreground">
            {t("match.markets.bestHelp")} <GlossaryLink term="bestOdds" />{" "}
            {before ? t("match.markets.chooseHelp") : null}
          </p>
          <ChipGroup<MarketsView>
            label={t("match.catalog.categories")}
            value={view}
            onChange={setPicked}
            testId="markets-categories"
            className="mb-4"
            options={views.map((v) => ({
              value: v,
              label:
                v === "featured" ? t("match.catalog.featured") : t(`match.catalog.category.${v}`),
            }))}
          />
          {view === "featured" ? (
            <>
              {/* Plan UX, A9: every bookmaker's prices failing to load is said, with its reference and a retry - the
                    best prices come from the match itself and stay. */}
              {allQ.isError ? (
                <div
                  className="mb-3 rounded-xl border border-border bg-card"
                  data-testid="markets-all-error"
                >
                  <p className="px-4 pt-3 text-xs text-muted-foreground">
                    {t("match.markets.allError")}
                  </p>
                  <ErrorState
                    error={allQ.error}
                    onRetry={() => void allQ.refetch()}
                    className="py-3"
                  />
                </div>
              ) : null}
              {order ? <MarketOrderNote order={order} /> : null}
              <FoldList
                views={featured}
                choose={choose}
                onConsult={consult}
                follow={follow}
                testId="markets-grid"
              />
            </>
          ) : (
            <CategoryPanel
              key={view}
              ctx={ctx}
              category={view}
              sides={sides}
              choose={choose}
              onConsult={consult}
              follow={follow}
              followed={followed}
              target={picked === null && linked?.category === view ? linked.key : undefined}
            />
          )}
        </>
      ) : catalogQ.isPending ? (
        <SkeletonBlock className="h-24" />
      ) : (
        <SectionNote status={markets.status === "ok" ? "empty" : markets.status}>
          {t("match.markets.none")}
        </SectionNote>
      )}
    </section>
  );
}

export function MarketsTab({ ctx }: { ctx: MatchCtx }) {
  const sides = { home: ctx.match.home.name, away: ctx.match.away.name };
  const { order, first, consult } = useMarketOrder(ctx.fixtureId);
  const followed = useFollowedCatalog();
  return (
    <div className="space-y-8">
      {ctx.phase === "live" ? (
        <LiveGroup ctx={ctx} sides={sides} first={first} onConsult={consult} />
      ) : null}

      <PrematchMarkets
        ctx={ctx}
        order={order}
        first={first}
        onConsult={consult}
        followed={followed}
      />

      <div className="flex justify-center">
        <Link
          to="/odds"
          className="tap-y relative inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-border-strong px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
        >
          <LineChart aria-hidden className="h-4 w-4" />
          {t("match.markets.movement")}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}
