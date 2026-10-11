/**
 * Every market we price for the match: the best price per selection and line across
 * bookmakers before kick-off, and the in-play prices in their own group while it is played.
 *
 * REVIEW PREDIGOL, point 10: every captured price is here - each bookmaker's, with where it
 * opened - and the captures carry the Cronología's own numbers, pick filter or not. Point 6:
 * a price is chosen the Cuotas way (tap: in or out of "Mi parlay"), the bookmark saves it.
 */
import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, ChevronRight, LineChart, Radar } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtLine, fmtOdds, toNumber } from "@/lib/i18n/format";
import { live as queries } from "@/lib/api/v1/queries";
import type { MatchMarkets, SelectionQuotes } from "@/lib/api/v1/types_profile";
import { formatDateTime } from "@/lib/time";
import { marketName } from "@/product/shared/markets";
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
import { bookRows, captureLabel, openingNote } from "./books";
import { Block, CenterSection, FreshnessLabel, MoreButton, SectionNote } from "./ui";

type Sides = { home: string; away: string };

const LINE_MARKETS = new Set(["OU", "AH"]);

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
                {t("match.markets.line")}
              </th>
            ) : null}
            <th scope="col" className="pb-1.5 pr-2 text-left font-medium">
              <span className="block truncate">{isOU ? t("match.markets.over") : sides.home}</span>
            </th>
            <th scope="col" className="pb-1.5 text-left font-medium">
              <span className="block truncate">{isOU ? t("match.markets.under") : sides.away}</span>
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

function BookCard({
  board,
  sides,
  choose,
  all,
}: {
  board: MarketBoard;
  sides: Sides;
  /** Before kick-off: what choosing a price saves or adds to the parlay. */
  choose?: Choose | undefined;
  /** Every bookmaker's price, newest and first (GET /matches/{id}/markets), when loaded. */
  all: MatchMarkets | null;
}) {
  const [open, setOpen] = useState(false);
  const sels = SELECTIONS[board.market] ?? [];
  const row = board.rows[0];
  const selections = all?.selections.filter((x) => x.market_key === board.market) ?? [];
  return (
    <Block level={3} title={marketName(board.market)} right={<Books count={board.books} />}>
      {LINE_MARKETS.has(board.market) ? (
        <LinesTable<BestPrice>
          market={board.market}
          rows={board.rows}
          main={board.main}
          sides={sides}
          cell={(p, prefix) => <PriceInline price={p} prefix={prefix} choose={choose} />}
        />
      ) : (
        <div className={cn("grid gap-2", sels.length === 3 ? "grid-cols-3" : "grid-cols-2")}>
          {sels.map((sel, i) => {
            const best = row?.cells[i] ?? null;
            return (
              <PriceTile
                key={sel}
                label={tileLabel(board.market, sel, null, sides)}
                price={best}
                showBooks
                choose={choose}
                note={best ? openingNote(selections, sel, 0, best.odds) : null}
              />
            );
          })}
        </div>
      )}
      {selections.length ? (
        <div className="mt-2 border-t border-border/60 pt-1">
          <MoreButton expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? t("match.books.hide") : t("match.books.show", { count: board.books })}
          </MoreButton>
          {open ? (
            <BooksPanel market={board.market} board={board} selections={selections} sides={sides} />
          ) : null}
        </div>
      ) : null}
    </Block>
  );
}

/** One arrow and the first price, when a bookmaker moved since we first captured it. */
function Moved({ now, opening }: { now: string; opening: string }) {
  const a = toNumber(now);
  const b = toNumber(opening);
  if (a === null || b === null || a === b) return null;
  const up = a > b;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className="numeric inline-flex items-center gap-0.5 text-[0.65rem] text-subtle-foreground"
      title={
        up
          ? t("match.books.movedUp", { odds: fmtOdds(opening) })
          : t("match.books.movedDown", { odds: fmtOdds(opening) })
      }
    >
      <Icon aria-hidden className="h-3 w-3" />
      {fmtOdds(opening)}
    </span>
  );
}

/**
 * Every bookmaker's newest price for each selection of a market (one line at a time for over/under and
 * handicaps), with where it opened: the prices behind the best one above - all of them, not only the ones
 * a pick rule would keep.
 */
function BooksPanel({
  market,
  board,
  selections,
  sides,
}: {
  market: string;
  board: MarketBoard;
  selections: SelectionQuotes[];
  sides: Sides;
}) {
  const lines = board.rows.map((r) => r.line ?? 0);
  const [line, setLine] = useState<number>(board.rows[board.main]?.line ?? 0);
  const sels = SELECTIONS[market] ?? [];
  const table = bookRows(market, selections, LINE_MARKETS.has(market) ? line : 0);
  const header = (sel: string) =>
    market === "OU"
      ? sel === "Over"
        ? t("match.markets.over")
        : t("match.markets.under")
      : tileLabel(market, sel, null, sides);
  return (
    <div className="mt-2 space-y-2" data-testid="books-panel">
      {LINE_MARKETS.has(market) ? (
        <label className="flex items-center gap-2 text-caption text-muted-foreground">
          {t("match.books.lineLabel")}
          <select
            value={String(line)}
            onChange={(e) => setLine(Number(e.target.value))}
            className="numeric h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {lines.map((l) => (
              <option key={l} value={String(l)}>
                {fmtLine(l, market === "AH")}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full min-w-0 text-xs">
          <thead>
            <tr className="text-caption text-subtle-foreground">
              <th scope="col" className="pb-1 pr-2 text-left font-medium">
                {t("match.books.bookmaker")}
              </th>
              {sels.map((sel) => (
                <th key={sel} scope="col" className="pb-1 pl-2 text-right font-medium">
                  <span className="block truncate">{header(sel)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {table.map((r) => (
              <tr key={r.bookmaker}>
                <th scope="row" className="max-w-[9rem] truncate py-1.5 pr-2 text-left font-normal">
                  {r.bookmaker}
                </th>
                {r.cells.map((c, i) => (
                  <td key={sels[i] ?? i} className="py-1.5 pl-2 text-right">
                    {c ? (
                      <span className="inline-flex flex-col items-end">
                        <span className={cn("numeric", c.best && "font-semibold text-gold-strong")}>
                          {fmtOdds(c.odds)}
                        </span>
                        <Moved now={c.odds} opening={c.opening_odds} />
                      </span>
                    ) : (
                      <span className="text-subtle-foreground">—</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The captures behind these prices: when, how far from kick-off, how many quotes - the Cronología's numbers. */
function CapturesStrip({ all }: { all: MatchMarkets }) {
  const prematch = all.captures.filter((c) => c.source === "prematch");
  const books = new Set(all.selections.flatMap((s) => s.books.map((b) => b.bookmaker_id))).size;
  if (all.captures.length === 0) return null;
  return (
    <div
      className="space-y-2 rounded-lg border border-border bg-card/60 px-3 py-2.5"
      data-testid="captures-strip"
    >
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <Radar aria-hidden className="h-3.5 w-3.5 text-primary" />
        <span className="font-medium">{t("match.captures.title")}</span>
        <span className="numeric text-muted-foreground">
          {t("match.captures.summary", {
            captures: all.captures.length,
            quotes: all.quotes,
            books,
          })}
        </span>
      </p>
      <ul className="flex flex-wrap gap-1.5">
        {prematch.map((c) => (
          <li
            key={c.captured_at}
            className="numeric rounded-full border border-border-strong bg-elevated px-2 py-0.5 text-[0.7rem] text-muted-foreground"
            title={Object.entries(c.by_market)
              .map(([m, n]) => `${marketName(m)}: ${n}`)
              .join(" · ")}
          >
            {t("match.captures.chip", { when: captureLabel(c.minutes_to_ko), quotes: c.quotes })}
          </li>
        ))}
      </ul>
      <p className="text-caption text-subtle-foreground">{t("match.captures.help")}</p>
    </div>
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

/** Single-line markets in a row of three on wide screens; line markets side by side. */
function CardGrid({ items }: { items: Array<{ key: string; lines: boolean; node: ReactNode }> }) {
  const single = items.filter((x) => !x.lines);
  const lines = items.filter((x) => x.lines);
  return (
    <div className="space-y-4">
      {single.length ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {single.map((x) => (
            <div key={x.key} className="min-w-0">
              {x.node}
            </div>
          ))}
        </div>
      ) : null}
      {lines.length ? (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {lines.map((x) => (
            <div key={x.key} className="min-w-0">
              {x.node}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function LiveGroup({ ctx, sides }: { ctx: MatchCtx; sides: Sides }) {
  const quotes = ctx.markets.status === "ok" ? ctx.markets.data : [];
  const books = marketBoards(quotes, "live");
  const feed = ctx.center.data?.live_odds.status === "ok" ? ctx.center.data.live_odds.data : [];
  const inPlay = liveMarkets(feed);
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
            node: <BookCard board={b} sides={sides} all={null} />,
          }))}
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

export function MarketsTab({ ctx }: { ctx: MatchCtx }) {
  const { markets, phase, match: m } = ctx;
  const sides = { home: m.home.name, away: m.away.name };
  const quotes = markets.status === "ok" ? markets.data : [];
  const boards = marketBoards(quotes, "prematch");
  const updated = latestCapture(quotes, "prematch");
  const before = phase === "scheduled";
  const choose = priceChooser(ctx);
  const allQ = useQuery(queries.matchMarkets(ctx.fixtureId));
  const all = allQ.data?.data ?? null;

  return (
    <div className="space-y-8">
      {phase === "live" ? <LiveGroup ctx={ctx} sides={sides} /> : null}

      <section aria-labelledby="markets-pre">
        <GroupHeader
          id="markets-pre"
          title={before ? t("match.markets.prematch") : t("match.markets.prematchPlayed")}
          right={
            updated ? (
              before ? (
                <FreshnessLabel at={updated} level={ageLevel(updated, 60, 360)} />
              ) : (
                <span className="text-caption text-muted-foreground">
                  {t("match.markets.lastCapture", { when: formatDateTime(updated) })}
                </span>
              )
            ) : null
          }
        />
        {boards.length > 0 ? (
          <>
            <p className="-mt-1.5 mb-3 text-xs text-muted-foreground">
              {t("match.markets.bestHelp")} {before ? t("match.markets.chooseHelp") : null}
            </p>
            {all ? <CapturesStrip all={all} /> : null}
            <div className="mt-3">
              <CardGrid
                items={boards.map((b) => ({
                  key: b.market,
                  lines: LINE_MARKETS.has(b.market),
                  node: <BookCard board={b} sides={sides} choose={choose} all={all} />,
                }))}
              />
            </div>
          </>
        ) : (
          <SectionNote status={markets.status === "ok" ? "empty" : markets.status}>
            {t("match.markets.none")}
          </SectionNote>
        )}
      </section>

      <div className="flex justify-center">
        <Link
          to="/odds"
          className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-border-strong px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
        >
          <LineChart aria-hidden className="h-4 w-4" />
          {t("match.markets.movement")}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}
