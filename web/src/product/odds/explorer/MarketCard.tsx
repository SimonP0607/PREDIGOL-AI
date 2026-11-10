/**
 * The market's card: its name, the period switch (Partido · 1.ª parte · 2.ª parte, with their matches), the line chips (the
 * main line of each match by default, the others on demand), one line on what the figures are, and the matches - by day,
 * by competition, or in one list by the widest difference with the fair price, with its caveat. «Cargar más» asks the API
 * for the next page.
 */
import { useId, useState, type ReactNode } from "react";
import { SearchX, TrendingUp } from "lucide-react";
import { t } from "@/lib/i18n";
import { fmtInt, fmtLine } from "@/lib/i18n/format";
import { formatDate, relativeDay } from "@/lib/time";
import { cn } from "@/lib/utils";
import { CompetitionTag } from "@/components/football/Logos";
import { GlossaryLink } from "@/components/system/GlossaryTerm";
import { EmptyState, ErrorState } from "@/product/shared/States";
import type { RowEnv } from "./env";
import { FixtureRow } from "./FixtureRow";
import { marketTakesParlay, priceBlock } from "./legs";
import { marketTitle, periodName, shapeOf } from "./markets";
import type { BoardPages, BoardSort, OddsBoardRow } from "./model";
import { MOTION } from "./motion";
import { groupRows, lineOptions, sameLine, type RowGroup } from "./rows";
import { RowSkeleton } from "./Skeletons";
import type { ExplorerView } from "./tabs";
import { Chip, Strip } from "./ui";

/** The day of a group: «Hoy · sáb 7 nov», «Mañana · dom 8 nov», «lun 9 nov». */
function GroupHeading({ group, env }: { group: RowGroup; env: RowEnv }) {
  if (group.kind === "competition" && group.competition !== null) {
    const c = env.competitions.get(group.competition);
    return c ? (
      <h3 className="px-1">
        <CompetitionTag
          name={c.name}
          logo={c.logo_url}
          flag={c.flag_url}
          country={c.country}
          className="text-xs font-semibold text-foreground"
        />
      </h3>
    ) : null;
  }
  if (group.kind !== "day" || !group.at) return null;
  const rel = relativeDay(group.at, undefined, env.now);
  return (
    <h3 className="flex items-baseline gap-2 px-1 font-display text-sm font-semibold">
      {rel ? (
        <>
          <span>{t(`common.day.${rel}`)}</span>
          <span className="text-xs font-normal text-muted-foreground">{formatDate(group.at)}</span>
        </>
      ) : (
        <span className="inline-block first-letter:uppercase">{formatDate(group.at)}</span>
      )}
    </h3>
  );
}

/** «Principal» and, on demand, every other line the matches on show have. */
function LineChips({
  view,
  rows,
  onLine,
}: {
  view: ExplorerView;
  rows: readonly OddsBoardRow[];
  onLine: (line: string) => void;
}) {
  const [more, setMore] = useState(view.line !== "main");
  const shape = shapeOf(view.market.info);
  const signed = shape === "ah" || shape === "eh";
  const lines = lineOptions(rows);
  if (view.line !== "main" && !lines.some((l) => sameLine(l, view.line))) {
    lines.push(Number(view.line));
    lines.sort((a, b) => a - b);
  }
  return (
    <Strip label={t("explorer.line.label")} testId="explorer-lines">
      <span aria-hidden className="shrink-0 text-label text-subtle-foreground">
        {t("explorer.line.label")}
      </span>
      <Chip on={view.line === "main"} onClick={() => onLine("main")} testId="explorer-line-main">
        {t("explorer.line.main")}
      </Chip>
      {more
        ? lines.map((l) => (
            <Chip
              key={l}
              on={view.line !== "main" && sameLine(view.line, l)}
              onClick={() => onLine(String(l))}
              testId="explorer-line"
              title={signed ? t("explorer.line.home", { line: fmtLine(l, true) }) : undefined}
            >
              <span className="numeric">{fmtLine(l, signed)}</span>
            </Chip>
          ))
        : null}
      {lines.length > 0 ? (
        <button
          type="button"
          aria-expanded={more}
          onClick={() => setMore((v) => !v)}
          data-testid="explorer-lines-more"
          className="tap-y relative inline-flex h-9 shrink-0 items-center rounded-full px-3 text-xs font-medium text-primary hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {more ? t("explorer.line.fewer") : t("explorer.line.more", { count: lines.length })}
        </button>
      ) : null}
    </Strip>
  );
}

export function MarketCard({
  view,
  sort,
  rows,
  total,
  board,
  env,
  filtered,
  hasMore,
  onPeriod,
  onLine,
  onClear,
  onWiden,
  className,
}: {
  view: ExplorerView;
  sort: BoardSort;
  /** The matches on show (the API's pages, after «Hoy» and «Mis equipos y ligas»), in the API's order. */
  rows: OddsBoardRow[];
  /** How many matches this board has (the API's count, or the client's once every page is in); null: not known. */
  total: number | null;
  board: BoardPages;
  env: RowEnv;
  /** Some filter is on. */
  filtered: boolean;
  /** «Cargar más» can bring more of the matches on show (even when none of the loaded ones passed «Hoy» or «Mis equipos»). */
  hasMore: boolean;
  onPeriod: (period: string) => void;
  onLine: (line: string) => void;
  onClear: () => void;
  /** Look further ahead (72 h), offered when nothing is priced; null at the widest window. */
  onWiden: (() => void) | null;
  className?: string | undefined;
}) {
  const titleId = useId();
  const { market, period } = view;
  const info = market.info;
  const takes = marketTakesParlay(info, period);
  const tappable =
    takes && rows.some((r) => r.selections.some((s) => !priceBlock(info, period, r, s, env.now)));
  const single = info.max_books <= 1;
  const groups = groupRows(rows, sort);

  let body;
  if (board.isPending) {
    body = (
      <ul className="divide-y divide-border/70" aria-busy="true" aria-label={t("common.loading")}>
        {[0, 1, 2, 3].map((i) => (
          <RowSkeleton key={i} />
        ))}
      </ul>
    );
  } else if (board.isError && !board.data) {
    body = <ErrorState error={board.error} onRetry={board.refetch} />;
  } else if (rows.length === 0) {
    const wrongLine = view.line !== "main";
    body = (
      <EmptyState
        icon={
          filtered ? (
            <SearchX aria-hidden className="h-6 w-6" />
          ) : (
            <TrendingUp aria-hidden className="h-6 w-6" />
          )
        }
        title={
          wrongLine
            ? t("explorer.empty.lineTitle")
            : filtered
              ? t("explorer.empty.filteredTitle")
              : t("explorer.empty.marketTitle")
        }
        body={
          hasMore
            ? t("explorer.empty.notLoadedBody")
            : wrongLine
              ? t("explorer.empty.lineBody")
              : filtered
                ? t("explorer.empty.filteredBody")
                : t("explorer.empty.marketBody")
        }
        action={
          wrongLine ? (
            <EmptyAction onClick={() => onLine("main")}>
              {t("explorer.line.backToMain")}
            </EmptyAction>
          ) : filtered ? (
            <EmptyAction onClick={onClear}>{t("explorer.filters.clear")}</EmptyAction>
          ) : onWiden ? (
            <EmptyAction onClick={onWiden}>{t("explorer.empty.widen")}</EmptyAction>
          ) : undefined
        }
      />
    );
  } else {
    body = (
      <div className="space-y-4 py-3">
        {groups.map((g) => (
          <div key={g.key} className="space-y-2">
            {g.kind === "all" ? null : (
              <div className="px-3 sm:px-4">
                <GroupHeading group={g} env={env} />
              </div>
            )}
            <ul className="divide-y divide-border/70 border-y border-border/70">
              {g.rows.map((row) => (
                <FixtureRow key={row.fixture_id} row={row} env={env} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    );
  }

  return (
    <section
      aria-labelledby={titleId}
      data-testid="explorer-card"
      data-market={market.key}
      data-period={period}
      data-line={view.line}
      className={cn("relative overflow-hidden rounded-xl border border-border bg-card", className)}
    >
      {board.isPlaceholderData ? (
        <div
          aria-hidden
          data-testid="explorer-progress"
          className="absolute inset-x-0 top-0 h-0.5 overflow-hidden"
        >
          <div
            className={cn("h-full w-full bg-primary motion-safe:animate-pulse", MOTION.progress)}
          />
        </div>
      ) : null}
      <header className="space-y-2.5 border-b border-border/70 px-3 pb-3 pt-3.5 sm:px-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h2 id={titleId} className="font-display text-base font-semibold tracking-tight">
            {marketTitle(info)}
          </h2>
          {total !== null ? (
            <span className="text-caption text-muted-foreground" data-testid="explorer-count">
              {t("explorer.count", { count: total })}
            </span>
          ) : null}
        </div>
        {market.periods.length > 1 ? (
          <Strip label={t("explorer.period.label")} testId="explorer-periods">
            {market.periods.map((p) => (
              <Chip
                key={p.period}
                on={p.period === period}
                onClick={() => onPeriod(p.period)}
                testId={`explorer-period-${p.period}`}
              >
                {periodName(p.period)}
                {p.fixtures !== null ? (
                  <>
                    <span aria-hidden className="numeric text-micro font-medium opacity-80">
                      {fmtInt(p.fixtures)}
                    </span>
                    <span className="sr-only">{t("explorer.tabCount", { count: p.fixtures })}</span>
                  </>
                ) : null}
              </Chip>
            ))}
          </Strip>
        ) : null}
        {info.has_line ? (
          <LineChips key={view.line} view={view} rows={rows} onLine={onLine} />
        ) : null}
        {/* One legend for the figures (and what a tap does): the page says it once, here, beside the prices it explains. */}
        <div className="space-y-1 text-caption text-subtle-foreground" data-guide="odds-fair">
          <p>
            {single
              ? t("explorer.note.single")
              : info.fair
                ? t("explorer.note.figures")
                : t("explorer.note.noFair")}
            {!takes ? (
              <>
                {" "}
                <span data-testid="explorer-lookup-only">{t("explorer.note.lookupOnly")}</span>
              </>
            ) : tappable ? (
              <> {t("explorer.note.tap")}</>
            ) : null}
            {!single && info.fair ? (
              <>
                {" "}
                <GlossaryLink term="fairOdds" />
              </>
            ) : null}
          </p>
          {sort === "edge" ? (
            <p data-testid="explorer-edge-caveat">{t("explorer.note.edge")}</p>
          ) : null}
        </div>
      </header>
      <div
        aria-busy={board.isPlaceholderData || undefined}
        className={cn(MOTION.dim, board.isPlaceholderData && "opacity-60")}
      >
        {body}
      </div>
      {hasMore ? (
        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 px-3 py-2.5 sm:px-4">
          <span className="text-caption text-muted-foreground">
            {total !== null
              ? t("explorer.shown", { shown: fmtInt(rows.length), total: fmtInt(total) })
              : null}
          </span>
          <button
            type="button"
            onClick={board.fetchNextPage}
            disabled={board.isFetchingNextPage}
            data-testid="explorer-load-more"
            className="tap-y relative inline-flex min-h-9 items-center rounded-full border border-border-strong px-4 text-xs font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          >
            {board.isFetchingNextPage ? t("common.loading") : t("explorer.loadMore")}
          </button>
        </footer>
      ) : null}
    </section>
  );
}

function EmptyAction({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="tap-y relative inline-flex h-9 items-center rounded-full border border-border-strong px-4 text-xs font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </button>
  );
}
