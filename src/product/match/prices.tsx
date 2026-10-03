/**
 * Prices on the Match Center: the best price per selection across bookmakers before the
 * match, and the in-play price (withdrawn and suspended states shown as such).
 */
import type { ReactNode } from "react";
import { Lock, Radio, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtLine, fmtOdds } from "@/lib/i18n/format";
import { OddsPill } from "@/product/shared/Bits";
import { marketName } from "@/product/shared/markets";
import type { MatchCtx } from "./context";
import {
  ageLevel,
  latestCapture,
  liveMarkets,
  marketBoards,
  tileLabel,
  type BestPrice,
  type LivePrice,
} from "./model";
import { Block, CenterSection, FreshnessLabel, MoreButton, SectionNote } from "./ui";

/** One selection, stacked: label, best price, who offers it (and how many quote it). */
export function PriceTile({
  label,
  price,
  showBooks = false,
}: {
  label: string;
  price: BestPrice | null;
  showBooks?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col items-center gap-1.5 rounded-lg border border-border bg-elevated/40 px-1.5 py-2.5 text-center">
      <span className="line-clamp-2 min-h-8 w-full break-words text-xs leading-4 text-muted-foreground">
        {label}
      </span>
      {price ? (
        <OddsPill odds={price.odds} />
      ) : (
        <span className="numeric py-1 text-sm text-subtle-foreground">—</span>
      )}
      <span className="w-full truncate text-caption text-subtle-foreground">
        {price ? price.bookmaker : t("match.prices.noPrice")}
      </span>
      {showBooks && price ? (
        <span className="-mt-1 text-[0.65rem] text-subtle-foreground">
          {t("match.markets.books", { count: price.books })}
        </span>
      ) : null}
    </div>
  );
}

/** One selection on a line row: price, then bookmaker and how many quote it. */
export function PriceInline({ price, prefix }: { price: BestPrice | null; prefix?: ReactNode }) {
  if (!price) return <span className="numeric text-sm text-subtle-foreground">—</span>;
  return (
    <div className="flex min-w-0 flex-col items-start gap-0.5">
      <span className="flex items-center gap-1.5">
        {prefix}
        <OddsPill odds={price.odds} size="sm" />
      </span>
      <span className="max-w-full truncate text-[0.65rem] text-subtle-foreground">
        {price.bookmaker} · {t("match.markets.books", { count: price.books })}
      </span>
    </div>
  );
}

type LiveState = "open" | "suspended" | "withdrawn";

function liveState(price: LivePrice | null): LiveState {
  if (!price || price.odds === null) return "withdrawn";
  return price.suspended ? "suspended" : "open";
}

/** An in-play price: open, locked while suspended, or withdrawn for now. */
export function LiveOdds({ price, size = "md" }: { price: LivePrice | null; size?: "sm" | "md" }) {
  const state = liveState(price);
  if (state === "open") return <OddsPill odds={price?.odds} size={size} />;
  if (state === "suspended") {
    return (
      <span
        title={t("match.liveOdds.suspendedHelp")}
        className={cn(
          "numeric inline-flex items-center justify-center gap-1 rounded-md border border-warning/40 bg-warning-soft font-semibold text-warning",
          size === "sm" ? "min-w-[3rem] px-1.5 py-0.5 text-xs" : "min-w-[3.5rem] px-2 py-1 text-sm",
        )}
      >
        <Lock aria-hidden className="h-3 w-3" />
        <span className="opacity-70">{fmtOdds(price?.odds)}</span>
        <span className="sr-only">{t("match.liveOdds.suspended")}</span>
      </span>
    );
  }
  return (
    <span
      title={t("match.liveOdds.withdrawnHelp")}
      className={cn(
        "inline-flex items-center justify-center rounded-md border border-dashed border-border-strong text-subtle-foreground",
        size === "sm"
          ? "min-w-[3rem] px-1.5 py-0.5 text-[0.7rem]"
          : "min-w-[3.5rem] px-2 py-1 text-xs",
      )}
    >
      {t("match.liveOdds.withdrawn")}
    </span>
  );
}

export function LiveTile({ label, price }: { label: string; price: LivePrice | null }) {
  const state = liveState(price);
  return (
    <div className="flex min-w-0 flex-col items-center gap-1.5 rounded-lg border border-border bg-elevated/40 px-1.5 py-2.5 text-center">
      <span className="line-clamp-2 min-h-8 w-full break-words text-xs leading-4 text-muted-foreground">
        {label}
      </span>
      <LiveOdds price={price} />
      <span className="w-full truncate text-caption text-subtle-foreground">
        {state === "suspended"
          ? t("match.liveOdds.suspended")
          : state === "open" && price?.minute !== null && price?.minute !== undefined
            ? t("match.liveOdds.atMinute", { minute: price.minute })
            : " "}
      </span>
    </div>
  );
}

function TileRow({ title, children, cols }: { title: string; children: ReactNode; cols: 2 | 3 }) {
  return (
    <div>
      <h3 className="mb-1.5 text-label text-subtle-foreground">{title}</h3>
      <div className={cn("grid gap-2", cols === 3 ? "grid-cols-3" : "grid-cols-2")}>{children}</div>
    </div>
  );
}

/** Before kick-off on the summary: 1X2, over/under 2.5 and both-teams-score at their best price. */
export function QuickPricesBlock({ ctx }: { ctx: MatchCtx }) {
  const { markets, match: m } = ctx;
  const sides = { home: m.home.name, away: m.away.name };
  const quotes = markets.status === "ok" ? markets.data : [];
  const boards = marketBoards(quotes, "prematch");
  const one = boards.find((b) => b.market === "1X2")?.rows[0];
  const ou = boards.find((b) => b.market === "OU")?.rows.find((r) => r.line === 2.5);
  const btts = boards.find((b) => b.market === "BTTS")?.rows[0];
  const updated = latestCapture(quotes, "prematch");
  const books = new Set(quotes.filter((q) => q.source === "prematch").map((q) => q.bookmaker_id))
    .size;
  const nothing = !one && !ou && !btts;

  return (
    <Block
      title={t("match.prices.title")}
      icon={<TrendingUp />}
      right={updated ? <FreshnessLabel at={updated} level={ageLevel(updated, 60, 360)} /> : null}
    >
      {nothing ? (
        <SectionNote status={markets.status === "ok" ? "empty" : markets.status}>
          {t("match.prices.none")}
        </SectionNote>
      ) : (
        <div className="space-y-3.5">
          {one ? (
            <TileRow title={marketName("1X2")} cols={3}>
              {one.cells.map((c, i) => (
                <PriceTile
                  key={i}
                  label={tileLabel("1X2", ["Home", "Draw", "Away"][i] ?? "", null, sides)}
                  price={c}
                />
              ))}
            </TileRow>
          ) : null}
          {ou ? (
            <TileRow title={t("match.prices.ou25", { line: fmtLine(2.5) })} cols={2}>
              {ou.cells.map((c, i) => (
                <PriceTile
                  key={i}
                  label={tileLabel("OU", i === 0 ? "Over" : "Under", 2.5, sides)}
                  price={c}
                />
              ))}
            </TileRow>
          ) : null}
          {btts ? (
            <TileRow title={marketName("BTTS")} cols={2}>
              {btts.cells.map((c, i) => (
                <PriceTile
                  key={i}
                  label={tileLabel("BTTS", i === 0 ? "Yes" : "No", null, sides)}
                  price={c}
                />
              ))}
            </TileRow>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-border/70 pt-2">
            <span className="text-caption text-subtle-foreground">
              {t("match.prices.bestOf", { count: books })}
            </span>
            <MoreButton onClick={() => ctx.goTo("markets")}>
              {t("match.prices.allMarkets")}
            </MoreButton>
          </div>
        </div>
      )}
    </Block>
  );
}

/** While the match is played: 1X2 and the main over/under line, in play. */
export function LiveOddsBlock({ ctx }: { ctx: MatchCtx }) {
  const { match: m, center } = ctx;
  const sides = { home: m.home.name, away: m.away.name };
  const quotes = center.data?.live_odds.status === "ok" ? center.data.live_odds.data : [];
  const mk = liveMarkets(quotes);
  const at = mk.reduce<string | null>(
    (acc, x) => (x.at && (!acc || x.at > acc) ? x.at : acc),
    null,
  );

  return (
    <Block
      title={t("match.liveOdds.title")}
      icon={<Radio />}
      right={at ? <FreshnessLabel at={at} level={ageLevel(at, 3, 10)} /> : null}
    >
      <CenterSection center={center} pick={(c) => c.live_odds}>
        {() => {
          const one = mk.find((x) => x.market === "1X2")?.rows[0];
          const ouMarket = mk.find((x) => x.market === "OU");
          const ou = ouMarket ? ouMarket.rows[ouMarket.main] : undefined;
          if (!one && !ou) return <SectionNote>{t("match.liveOdds.none")}</SectionNote>;
          return (
            <div className="space-y-3.5">
              {one ? (
                <TileRow title={marketName("1X2")} cols={3}>
                  {one.cells.map((c, i) => (
                    <LiveTile
                      key={i}
                      label={tileLabel("1X2", ["Home", "Draw", "Away"][i] ?? "", null, sides)}
                      price={c}
                    />
                  ))}
                </TileRow>
              ) : null}
              {ou && ou.line !== null ? (
                <TileRow title={t("match.liveOdds.ouMain", { line: fmtLine(ou.line) })} cols={2}>
                  {ou.cells.map((c, i) => (
                    <LiveTile
                      key={i}
                      label={tileLabel("OU", i === 0 ? "Over" : "Under", ou.line, sides)}
                      price={c}
                    />
                  ))}
                </TileRow>
              ) : null}
              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-border/70 pt-2">
                <span className="text-caption text-subtle-foreground">
                  {t("match.liveOdds.note")}
                </span>
                <MoreButton onClick={() => ctx.goTo("markets")}>
                  {t("match.liveOdds.more")}
                </MoreButton>
              </div>
            </div>
          );
        }}
      </CenterSection>
    </Block>
  );
}
