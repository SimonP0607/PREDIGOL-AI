/**
 * Odds: the best price of every selection for the upcoming fixtures, next to the market's
 * fair (de-vigged) price. The market tabs and the time window scope everything below them.
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { BadgePercent, Clock, Info } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type { PickCard as PickCardData } from "@/lib/api/v1/types_product";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ShadowBadge } from "@/product/shared/Bits";
import { PickCard } from "@/product/shared/PickCard";
import { Card, ErrorState, PageTitle, SectionHeader, SkeletonBlock } from "@/product/shared/States";
import { MARKETS, marketShort, type MarketKey } from "@/product/shared/markets";
import { ChipGroup, ShadowToggle, type ChipOption } from "@/product/picks/Controls";
import { Highlights } from "./Highlights";
import { OddsBoard } from "./OddsBoard";

/** The API's own default window is 48 h. */
const DEFAULT_HOURS = 48;
const WIDEST = 72;
const WINDOWS: readonly number[] = [24, 48, WIDEST];
const VALUE_MAX = 6;

function tabLabel(market: MarketKey): string {
  switch (market) {
    case "1X2":
      return t("odds.tabs.1X2");
    case "OU":
      return t("odds.tabs.OU");
    case "BTTS":
      return t("odds.tabs.BTTS");
    case "AH":
      return t("odds.tabs.AH");
    case "DC":
      return t("odds.tabs.DC");
  }
}

export function OddsPage() {
  const auth = useAuth();
  const preview = usePreviewParam();
  const [market, setMarket] = useState<MarketKey>("1X2");
  const [hours, setHours] = useState<number>(DEFAULT_HOURS);
  const query = useQuery({
    ...live.bestOdds({ market, hours }, preview),
    placeholderData: keepPreviousData,
  });
  const board = query.data?.data;
  // While another tab loads, the previous board stays on screen (dimmed), drawn with the
  // market it was fetched for: a board asked for one market lists exactly that one.
  const shownMarket = board?.markets.length === 1 && board.markets[0] ? board.markets[0] : market;
  const refreshing = query.isPlaceholderData;
  const asOf = query.data?.meta.data_as_of ?? null;
  const windows: ChipOption<number>[] = WINDOWS.map((h) => ({
    value: h,
    label: t("odds.window.hours", { count: h }),
  }));

  let content;
  if (query.isPending) {
    content = <OddsSkeleton />;
  } else if (query.isError) {
    content = (
      <Card>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  } else if (board) {
    // No fixture priced at all: the board's own empty state says it once, not three times.
    const nothing = board.fixtures.length === 0 && board.highlights.length === 0;
    content = (
      <>
        {nothing ? null : <Highlights items={board.highlights} />}
        {nothing && board.value.length === 0 ? null : (
          <ValueBlock picks={board.value} shadow={board.source === "shadow_preview"} />
        )}
        <OddsBoard
          fixtures={board.fixtures}
          market={shownMarket}
          hours={board.window_hours}
          onWiden={board.window_hours < WIDEST ? () => setHours(WIDEST) : undefined}
        />
      </>
    );
  }

  return (
    <div className="space-y-6">
      <PageTitle
        title={t("nav.odds")}
        subtitle={t("odds.subtitle")}
        right={auth.showAdmin ? <ShadowToggle /> : undefined}
      />

      <div className="space-y-3">
        <MarketTabs value={market} onChange={setMarket} />
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
            <span aria-hidden className="text-label text-subtle-foreground">
              {t("odds.window.label")}
            </span>
            <ChipGroup
              label={t("odds.window.label")}
              value={hours}
              options={windows}
              onChange={setHours}
              testId="odds-window"
            />
          </div>
          {asOf ? (
            <span className="inline-flex items-center gap-1 text-caption text-muted-foreground">
              <Clock aria-hidden className="h-3 w-3" />
              {t("odds.pricesUpdated", { when: formatRelative(asOf) })}
            </span>
          ) : null}
        </div>
      </div>

      <div
        id="odds-panel"
        role="tabpanel"
        aria-labelledby={`odds-tab-${market}`}
        aria-busy={refreshing}
        className={cn("space-y-8 transition-opacity", refreshing && "opacity-60")}
      >
        {content}
      </div>
    </div>
  );
}

/** A tab bar that scrolls sideways on a phone; arrow keys move between markets. */
function MarketTabs({
  value,
  onChange,
}: {
  value: MarketKey;
  onChange: (market: MarketKey) => void;
}) {
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const bar = useRef<HTMLDivElement>(null);
  // True while some tab is hidden past the right edge: the bar fades there to say so.
  const [more, setMore] = useState(false);

  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    const update = () => setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  }, []);

  function choose(index: number, focus: boolean) {
    const m = MARKETS[index];
    const el = tabs.current[index];
    if (!m) return;
    onChange(m);
    if (focus) el?.focus();
    el?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = MARKETS.indexOf(value);
    const last = MARKETS.length - 1;
    const next =
      e.key === "ArrowRight"
        ? i === last
          ? 0
          : i + 1
        : e.key === "ArrowLeft"
          ? i === 0
            ? last
            : i - 1
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? last
              : null;
    if (next === null) return;
    e.preventDefault();
    choose(next, true);
  }

  return (
    <div
      ref={bar}
      role="tablist"
      aria-label={t("odds.marketsLabel")}
      onKeyDown={onKeyDown}
      data-testid="odds-market-tabs"
      className={cn(
        "flex gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        more && "[mask-image:linear-gradient(to_right,#000_calc(100%_-_3rem),transparent)]",
      )}
    >
      {MARKETS.map((m, i) => {
        const on = m === value;
        return (
          <button
            key={m}
            ref={(el) => {
              tabs.current[i] = el;
            }}
            id={`odds-tab-${m}`}
            type="button"
            role="tab"
            aria-selected={on}
            aria-controls="odds-panel"
            tabIndex={on ? 0 : -1}
            onClick={() => choose(i, false)}
            className={cn(
              "h-9 shrink-0 whitespace-nowrap rounded-lg px-3 text-[0.8125rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring md:flex-1 md:text-sm",
              on
                ? "bg-elevated text-foreground shadow-sm ring-1 ring-border-strong"
                : "text-muted-foreground hover:bg-elevated/50 hover:text-foreground",
            )}
          >
            <span className="md:hidden">{marketShort(m)}</span>
            <span className="hidden md:inline">{tabLabel(m)}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Qualified selections with value at today's best price; only drawn when there are some. */
function ValueBlock({ picks, shadow }: { picks: PickCardData[]; shadow: boolean }) {
  if (picks.length === 0) {
    return (
      <p
        className="flex items-center gap-1.5 text-xs text-muted-foreground"
        data-testid="odds-value-none"
      >
        <Info aria-hidden className="h-3.5 w-3.5 shrink-0" />
        {t("odds.value.none")}
      </p>
    );
  }
  return (
    <section className="space-y-3" data-testid="odds-value">
      <div className="space-y-2">
        <SectionHeader
          title={t("odds.value.title")}
          subtitle={t("odds.value.subtitle")}
          icon={<BadgePercent aria-hidden className="h-4 w-4 text-primary" />}
          action={{ label: t("odds.value.seeAll"), to: "/picks" }}
        />
        {shadow ? <ShadowBadge /> : null}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {picks.slice(0, VALUE_MAX).map((pick) => (
          <PickCard key={pick.pick_id} pick={pick} compact shadow={shadow} />
        ))}
      </div>
    </section>
  );
}

function OddsSkeleton() {
  return (
    <div className="space-y-8" aria-busy="true" aria-label={t("common.loading")}>
      <div className="space-y-3">
        <SkeletonBlock className="h-5 w-64 max-w-full" />
        <div className="flex gap-3 overflow-hidden sm:grid sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <SkeletonBlock key={i} className="h-36 w-[82%] shrink-0 sm:w-auto" />
          ))}
        </div>
      </div>
      <div className="space-y-3">
        <SkeletonBlock className="h-5 w-48" />
        {[0, 1, 2, 3].map((i) => (
          <SkeletonBlock key={i} className="h-44 lg:h-28" />
        ))}
      </div>
    </div>
  );
}
