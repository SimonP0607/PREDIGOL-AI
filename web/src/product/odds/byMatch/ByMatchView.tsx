/**
 * Cuotas «Por partido» (plan maestro unificado, UX-141; sheets C01, C02 and C06): every match of the window with the best
 * price of each selection of its three common markets and the bookmaker that offers it. On a desk, one table - time,
 * match, 1 X 2, over/under 2.5 and both teams to score - grouped by competition, «Mi parlay» at its side; on a phone and a
 * tablet, a card per match with the market chosen above. A price is the explorer's own: a tap adds it to «Mi parlay», a
 * green edge says PrediGol sees value in it, and «Comparar casas» opens the match's book. The explorer by families stays
 * one tap away («Por mercado»): nothing of it is removed.
 */
import { useMemo, useState, type ReactNode } from "react";
import { MatchOddsSheet } from "./MatchOdds";
import { Link } from "@tanstack/react-router";
import { Check, ChevronRight, Clock, SearchX, TrendingUp } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatOdds } from "@/lib/i18n/format";
import { formatKickoff, formatRelative, formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { CompetitionTag } from "@/components/football/Logos";
import { ScrollStrip } from "@/components/ui/ScrollStrip";
import { Segmented } from "@/components/ui/segmented";
import { Card, EmptyState, ErrorState, PageTitle, SkeletonCards } from "@/product/shared/States";
import { SlipCard } from "@/product/records/SlipCard";
import { ParlayToggle } from "../ParlayPrice";
import { useParlayLeg } from "../useParlayLeg";
import { StatusBar } from "../explorer/Status";
import { blockText, explorerLeg, priceBlock } from "../explorer/legs";
import { rowFreshness } from "../explorer/rows";
import { priceDescription, selectionLabel } from "../explorer/selections";
import type { BoardQuery, DayKey, ExplorerData, OddsSelectionPrice } from "../explorer/model";
import { DayTabs, dayLabel, nextDayWithPrices } from "../explorer/DayTabs";
import {
  BY_MATCH_MARKETS,
  competitionChips,
  filterLines,
  groupLines,
  hasValue,
  joinBoards,
  type ByMatchMarket,
  type ByMatchSort,
  type MatchCell,
  type MatchLine,
} from "./model";

function boardQuery(market: string, line: string, day: DayKey): BoardQuery {
  return {
    hours: 24, // a day names its own window: the server ignores the hours (AP-C01)
    day,
    country: null,
    competition: null,
    market,
    period: "FT",
    line,
    q: "",
    bookmaker: null,
    min_books: null,
    odds_min: null,
    odds_max: null,
    fair_only: false,
    sort: "time",
  };
}

/** The column heads of a market's prices, as the sheet names them («1», «Más 2,5», «AM sí»). */
function columnLabel(market: ByMatchMarket, i: number): string {
  return t(`odds.byMatch.columns.${market.replace(".", "_")}.${i}`);
}

export function ByMatchView({
  data,
  modeSwitch,
  now = Date.now(),
  guide = true,
  day: chosenDay,
  onDay,
}: {
  data: ExplorerData;
  /** «Por partido | Por mercado», shown under the title. */
  modeSwitch?: ReactNode;
  now?: number;
  guide?: boolean;
  /** The day, kept in the URL by the screen (`h`); alone, the view keeps it itself. */
  day?: DayKey;
  onDay?: (day: DayKey) => void;
}) {
  const [ownDay, setOwnDay] = useState<DayKey>("today");
  const day = chosenDay ?? ownDay;
  const setDay = (next: DayKey) => (onDay ? onDay(next) : setOwnDay(next));
  const [competition, setCompetition] = useState<number | null>(null);
  const [valueOnly, setValueOnly] = useState(false);
  const [sort, setSort] = useState<ByMatchSort>("time");
  const [market, setMarket] = useState<ByMatchMarket>("result.1x2");
  const [paused, setPaused] = useState(false);
  const live = { paused, enabled: true };
  // one match's markets and movement (C03, C04), in a sheet over the board
  const [opened, setOpened] = useState<MatchLine | null>(null);

  // Three boards, always in the same order (each member of ExplorerData is a hook).
  const result = data.useBoard(
    boardQuery(BY_MATCH_MARKETS[0].key, BY_MATCH_MARKETS[0].line, day),
    live,
  );
  const goals = data.useBoard(
    boardQuery(BY_MATCH_MARKETS[1].key, BY_MATCH_MARKETS[1].line, day),
    live,
  );
  const btts = data.useBoard(
    boardQuery(BY_MATCH_MARKETS[2].key, BY_MATCH_MARKETS[2].line, day),
    live,
  );
  // The matches of each day, for the tabs.
  const families = data.useFamilies({ hours: 24, day, country: null, competition: null }, live);
  const nextDay = nextDayWithPrices(day, families.data?.days);
  const boards = [result, goals, btts];

  const board = useMemo(
    () =>
      joinBoards({
        "result.1x2": result.data,
        "goals.total": goals.data,
        "goals.btts": btts.data,
      }),
    [result.data, goals.data, btts.data],
  );
  const chips = useMemo(() => competitionChips(board.lines, board.competitions), [board]);
  const lines = filterLines(board.lines, { competition, valueOnly, sort });
  const groups = groupLines(lines, sort, board.competitions);
  const pending = boards.every((b) => b.isPending);
  const failed = boards.every((b) => b.isError) && board.lines.length === 0;
  const more = boards.some((b) => b.hasNextPage);
  const loadingMore = boards.some((b) => b.isFetchingNextPage);
  const priced = board.lines.length;
  const valued = board.lines.filter((l) => l.edge !== null && l.edge > 0).length;

  return (
    <div className="space-y-4" data-testid="odds-by-match">
      <PageTitle
        {...(guide ? { guide: "odds" as const } : {})}
        title={t("nav.odds")}
        subtitle={t("odds.byMatch.subtitle", { count: board.bookmakers.size })}
        right={<StatusBar updatedAt={board.generatedAt} paused={paused} onPause={setPaused} />}
      />
      {modeSwitch}

      {/* The day, the competitions, «Solo con valor» and the order (C06's row of controls). */}
      <div className="flex flex-wrap items-center gap-2" data-testid="by-match-controls">
        <DayTabs value={day} days={families.data?.days} onChange={setDay} testId="by-match-day" />
        <ScrollStrip wrapperClassName="max-w-full" className="flex gap-2 py-1">
          {chips.slice(0, 6).map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={competition === c.id}
              onClick={() => setCompetition(competition === c.id ? null : c.id)}
              data-testid="by-match-competition"
              className={cn(
                "tap-y relative inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                competition === c.id
                  ? "border-primary/50 bg-primary-soft text-primary"
                  : "border-border text-foreground hover:border-border-strong",
              )}
            >
              <span className="numeric text-xs text-muted-foreground">{c.count}</span>
              {c.name}
            </button>
          ))}
        </ScrollStrip>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* The box is drawn; the native checkbox lies invisibly over the whole label, so a finger finds 44 px. */}
          <label className="tap-y relative inline-flex h-9 cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={valueOnly}
              onChange={(e) => setValueOnly(e.target.checked)}
              data-testid="by-match-value-only"
              className="peer absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0"
            />
            <span
              aria-hidden
              className="flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] border border-border-strong text-primary-foreground peer-checked:border-primary peer-checked:bg-primary peer-focus-visible:ring-2 peer-focus-visible:ring-ring"
            >
              {valueOnly ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
            </span>
            {t("odds.byMatch.valueOnly", { count: valued })}
          </label>
          <Segmented
            label={t("odds.byMatch.sort")}
            value={sort}
            onChange={(v) => setSort(v as ByMatchSort)}
            options={[
              { value: "time", label: t("odds.byMatch.byTime") },
              { value: "value", label: t("odds.byMatch.byValue") },
            ]}
          />
        </div>
      </div>

      {/* A phone and a tablet show one market per card: chosen here (C01). */}
      <div className="@container" data-testid="by-match-market-chips">
        <ScrollStrip wrapperClassName="@[46rem]:hidden" className="flex gap-2 py-1">
          {BY_MATCH_MARKETS.map((m) => (
            <button
              key={m.key}
              type="button"
              aria-pressed={market === m.key}
              onClick={() => setMarket(m.key)}
              className={cn(
                "tap-y relative inline-flex h-9 shrink-0 items-center rounded-full border px-3.5 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                market === m.key
                  ? "border-primary/50 bg-primary-soft text-primary"
                  : "border-border text-foreground hover:border-border-strong",
              )}
            >
              {t(`odds.byMatch.markets.${m.key.replace(".", "_")}`)}
            </button>
          ))}
        </ScrollStrip>
      </div>

      <p className="text-caption text-muted-foreground" data-testid="by-match-summary">
        {priced > 0 ? t("odds.byMatch.summary", { count: lines.length, total: priced }) : null}
      </p>

      <div className="xl:grid xl:grid-cols-[minmax(0,1fr)_20rem] xl:items-start xl:gap-6">
        <div className="min-w-0 space-y-4">
          {pending ? (
            <SkeletonCards count={4} />
          ) : failed ? (
            <ErrorState error={result.error ?? goals.error ?? btts.error} />
          ) : lines.length === 0 ? (
            <Card>
              <EmptyState
                icon={
                  priced === 0 ? (
                    <TrendingUp aria-hidden className="h-6 w-6" />
                  ) : (
                    <SearchX aria-hidden className="h-6 w-6" />
                  )
                }
                title={priced === 0 ? t("odds.byMatch.emptyTitle") : t("odds.byMatch.noneTitle")}
                body={priced === 0 ? t("odds.byMatch.emptyBody") : t("odds.byMatch.noneBody")}
                action={
                  priced === 0 && nextDay ? (
                    <button
                      type="button"
                      onClick={() => setDay(nextDay.key)}
                      data-testid="by-match-next-day"
                      className="tap-y relative inline-flex h-9 items-center rounded-full border border-border-strong px-4 text-xs font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {t("explorer.empty.nextDay", {
                        day: dayLabel(nextDay.key).toLowerCase(),
                        count: nextDay.fixtures,
                      })}
                    </button>
                  ) : undefined
                }
              />
            </Card>
          ) : (
            <Board groups={groups} market={market} board={board} now={now} onOpen={setOpened} />
          )}
          {more ? (
            <div className="flex justify-center">
              <button
                type="button"
                disabled={loadingMore}
                onClick={() => {
                  for (const b of boards) if (b.hasNextPage) b.fetchNextPage();
                }}
                data-testid="by-match-more"
                className="tap-y relative inline-flex h-10 items-center rounded-full border border-border-strong px-4 text-sm font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
              >
                {loadingMore ? t("odds.byMatch.loadingMore") : t("odds.byMatch.more")}
              </button>
            </div>
          ) : null}
          <Legend />
        </div>
        {/* «Mi parlay» at the side from 1280 px (C06); below it, the floating button opens the same parlay. */}
        <aside className="hidden xl:sticky xl:top-20 xl:block" aria-label={t("records.slip.title")}>
          <SlipCard />
        </aside>
      </div>
      {opened ? (
        <MatchOddsSheet
          open
          onOpenChange={(o) => (o ? null : setOpened(null))}
          fixtureId={opened.fixture_id}
          sides={{ home: opened.home.name, away: opened.away.name }}
          competition={board.competitions.get(opened.competition_id)?.name ?? null}
          kickoffAt={opened.kickoff_at}
        />
      ) : null}
    </div>
  );
}

function Legend() {
  return (
    <p
      className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-muted-foreground"
      data-testid="by-match-legend"
    >
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-3 rounded-[4px] border-2 border-primary" />
        {t("odds.byMatch.legend.value")}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-3 rounded-[4px] bg-primary" />
        {t("odds.byMatch.legend.inSlip")}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Clock aria-hidden className="h-3 w-3 text-warning" />
        {t("odds.byMatch.legend.stale")}
      </span>
      <span>{t("odds.byMatch.legend.btts")}</span>
    </p>
  );
}

function Board({
  groups,
  market,
  board,
  now,
  onOpen,
}: {
  groups: ReturnType<typeof groupLines>;
  market: ByMatchMarket;
  board: ReturnType<typeof joinBoards>;
  now: number;
  onOpen: (line: MatchLine) => void;
}) {
  return (
    <div className="@container">
      {/* The table of a desk (C06), from a 64 rem container. */}
      <Card as="div" className="hidden overflow-hidden @[46rem]:block" data-testid="by-match-table">
        <div
          role="row"
          className="grid grid-cols-[3.5rem_minmax(7.5rem,1fr)_repeat(7,4.25rem)] items-center gap-x-1.5 border-b border-border px-4 py-2.5 text-label text-subtle-foreground"
        >
          <span role="columnheader">{t("odds.byMatch.time")}</span>
          <span role="columnheader">{t("odds.byMatch.match")}</span>
          {BY_MATCH_MARKETS.flatMap((m) =>
            m.selections.map((_, i) => (
              <span
                key={`${m.key}-${i}`}
                role="columnheader"
                className="whitespace-nowrap text-center text-[0.6875rem] tracking-normal"
              >
                {columnLabel(m.key, i)}
              </span>
            )),
          )}
        </div>
        {groups.map((g) => (
          <section key={g.key} aria-label={g.competition?.name ?? t("odds.byMatch.all")}>
            {g.competition ? (
              <h3 className="flex items-center gap-2 border-b border-border/70 bg-foreground/[0.02] px-4 py-2 text-sm font-semibold">
                <CompetitionTag
                  name={g.competition.name}
                  logo={g.competition.logo_url}
                  flag={g.competition.flag_url}
                  country={g.competition.country}
                />
              </h3>
            ) : null}
            <ul className="divide-y divide-border/70">
              {g.lines.map((l) => (
                <TableRow
                  key={l.fixture_id}
                  line={l}
                  board={board}
                  now={now}
                  withDay={g.competition === null}
                  onOpen={onOpen}
                />
              ))}
            </ul>
          </section>
        ))}
      </Card>

      {/* A card per match on a phone and a tablet (C01). */}
      <div className="space-y-4 @[46rem]:hidden" data-testid="by-match-cards">
        {groups.map((g) => (
          <section
            key={g.key}
            className="space-y-2.5"
            aria-label={g.competition?.name ?? t("odds.byMatch.all")}
          >
            {g.competition ? (
              <h3 className="px-1 text-sm font-semibold">{g.competition.name}</h3>
            ) : null}
            {g.lines.map((l) => (
              <MatchCard
                key={l.fixture_id}
                line={l}
                market={market}
                board={board}
                now={now}
                onOpen={onOpen}
              />
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}

function matchName(line: MatchLine): string {
  return `${line.home.name} – ${line.away.name}`;
}

function StaleChip({ line, now }: { line: MatchLine; now: number }) {
  const cell = Object.values(line.cells).find((c) => c && c.row.captured_at === line.captured_at);
  const fresh = cell ? rowFreshness(cell.row, now) : null;
  if (!fresh || !line.stale) return null;
  return (
    <span
      title={fresh.title}
      data-testid="by-match-stale"
      className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-warning/40 bg-warning-soft px-2 py-0.5 text-micro font-semibold text-warning"
    >
      <Clock aria-hidden className="h-3 w-3" />
      {formatRelative(line.captured_at, now)}
    </span>
  );
}

function TableRow({
  line,
  board,
  now,
  withDay,
  onOpen,
}: {
  line: MatchLine;
  board: ReturnType<typeof joinBoards>;
  now: number;
  withDay: boolean;
  onOpen: (line: MatchLine) => void;
}) {
  return (
    <li
      data-testid="by-match-row"
      data-fixture={line.fixture_id}
      className="grid grid-cols-[3.5rem_minmax(7.5rem,1fr)_repeat(7,4.25rem)] items-center gap-x-1.5 px-4 py-3"
    >
      <span className="numeric text-sm font-semibold">
        {withDay ? formatKickoff(line.kickoff_at) : formatTime(line.kickoff_at)}
      </span>
      <div className="min-w-0 space-y-0.5">
        <Link
          to="/matches/$fixtureId"
          params={{ fixtureId: String(line.fixture_id) }}
          className="block break-words text-sm font-semibold leading-snug hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="block">{line.home.name}</span>
          <span className="block font-normal text-muted-foreground">{line.away.name}</span>
        </Link>
        <StaleChip line={line} now={now} />
        <button
          type="button"
          onClick={() => onOpen(line)}
          data-testid="by-match-markets"
          className="tap-y relative text-caption font-semibold text-primary hover:underline"
        >
          {t("odds.byMatch.sheet.open")}
        </button>
      </div>
      {BY_MATCH_MARKETS.flatMap((m) => {
        const cell = line.cells[m.key];
        return m.selections.map((_, i) => (
          <CompactPrice
            key={`${m.key}-${i}`}
            cell={cell}
            index={i}
            line={line}
            bookmakers={board.bookmakers}
            now={now}
          />
        ));
      })}
    </li>
  );
}

function MatchCard({
  line,
  market,
  board,
  now,
  onOpen,
}: {
  line: MatchLine;
  market: ByMatchMarket;
  board: ReturnType<typeof joinBoards>;
  now: number;
  onOpen: (line: MatchLine) => void;
}) {
  const spec = BY_MATCH_MARKETS.find((m) => m.key === market) ?? BY_MATCH_MARKETS[0];
  const cell = line.cells[spec.key];
  const competition = board.competitions.get(line.competition_id);
  const books = cell ? Math.max(0, ...cell.prices.map((p) => p?.n_books ?? 0)) : 0;
  return (
    <Card
      as="article"
      className="space-y-3 p-4"
      data-testid="by-match-card"
      data-fixture={line.fixture_id}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="break-words font-display text-base font-semibold leading-snug">
            {matchName(line)}
          </h4>
          <p className="text-caption text-muted-foreground">
            {competition ? `${competition.name} · ` : ""}
            <span className="numeric">{formatTime(line.kickoff_at)}</span>
          </p>
        </div>
        <StaleChip line={line} now={now} />
      </header>
      {cell ? (
        <div
          className={cn("grid gap-2", spec.selections.length === 3 ? "grid-cols-3" : "grid-cols-2")}
        >
          {spec.selections.map((_, i) => (
            <CompactPrice
              key={i}
              cell={cell}
              index={i}
              line={line}
              bookmakers={board.bookmakers}
              now={now}
              labelled
            />
          ))}
        </div>
      ) : (
        <p className="rounded-md border border-dashed border-border px-3 py-2.5 text-sm text-muted-foreground">
          {t("odds.byMatch.noMarket")}
        </p>
      )}
      <footer className="flex flex-wrap items-center justify-between gap-2 text-caption text-muted-foreground">
        <span>
          {books <= 1 && cell
            ? t("odds.byMatch.oneBook")
            : t("odds.byMatch.books", { count: books })}
        </span>
        <button
          type="button"
          onClick={() => onOpen(line)}
          data-testid="by-match-compare"
          aria-label={t("explorer.compare.toggleLabel", { match: matchName(line) })}
          className="tap-y relative inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {books <= 1 ? t("odds.byMatch.seeMarkets") : t("explorer.compare.toggle")}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </button>
      </footer>
    </Card>
  );
}

/**
 * One price: the explorer's own rule for whether it can go in «Mi parlay» (explorerLeg, priceBlock), drawn as a tile with
 * the price large and its bookmaker under it. A green edge: PrediGol sees value in it; filled: it is in «Mi parlay».
 */
function CompactPrice({
  cell,
  index,
  line,
  bookmakers,
  now,
  labelled = false,
}: {
  cell: MatchCell | undefined;
  index: number;
  line: MatchLine;
  bookmakers: ReadonlyMap<number, string>;
  now: number;
  labelled?: boolean;
}) {
  const sel: OddsSelectionPrice | null = cell?.prices[index] ?? null;
  const bookmaker = sel ? (bookmakers.get(sel.bookmaker_id) ?? "—") : null;
  const leg = cell && sel ? explorerLeg(cell.info, "FT", cell.row, sel, bookmaker) : null;
  const parlay = useParlayLeg(leg, null, { outlier: sel?.outlier });
  if (!cell || !sel) {
    return (
      <span
        aria-label={t("odds.byMatch.noPrice")}
        className="flex h-[3.25rem] items-center justify-center text-sm text-subtle-foreground"
      >
        —
      </span>
    );
  }
  const block = priceBlock(cell.info, "FT", cell.row, sel, now);
  const tappable = parlay !== null && (parlay.inSlip || (block === null && parlay.block === null));
  const sides = { home: line.home.name, away: line.away.name };
  const full = selectionLabel(cell.info, sel, cell.row.line, sides, "full");
  const description = `${matchName(line)}. ${priceDescription(full, sel, bookmaker ?? "—")}`;
  const value = hasValue(sel);
  const inSlip = !!parlay?.inSlip;
  const tile = (
    <span
      className={cn(
        "flex w-full flex-col items-start rounded-control border px-2.5 py-1.5 text-left transition-colors",
        inSlip
          ? "border-primary bg-primary text-primary-foreground"
          : value
            ? "border-primary/70 bg-primary/[0.06]"
            : "border-border bg-elevated/40",
        (cell.row.state === "stale" || sel.outlier) && !inSlip && "opacity-60",
      )}
    >
      {labelled ? (
        <span className={cn("text-micro font-semibold", inSlip ? "" : "text-muted-foreground")}>
          {columnLabel(cell.market, index)}
        </span>
      ) : null}
      <span className="numeric text-base font-bold leading-tight">{formatOdds(sel.best_odds)}</span>
      <span
        className={cn(
          "max-w-full break-words text-micro leading-[0.875rem] [overflow-wrap:anywhere]",
          inSlip ? "text-primary-foreground/85" : "text-muted-foreground",
        )}
      >
        {bookmaker}
      </span>
    </span>
  );
  return (
    <div
      data-testid="by-match-price"
      data-value={value || undefined}
      data-in-slip={inSlip || undefined}
    >
      {tappable && parlay ? (
        <ParlayToggle state={parlay} srLabel={description} className="block w-full rounded-control">
          {tile}
        </ParlayToggle>
      ) : (
        <div title={blockText(block) ?? undefined}>
          <span className="sr-only">{description}</span>
          <span aria-hidden>{tile}</span>
        </div>
      )}
    </div>
  );
}
