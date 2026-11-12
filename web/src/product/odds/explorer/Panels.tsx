/**
 * What a row opens below itself: «Comparar casas», every bookmaker's price of the row's line with its margin (the match's
 * book, asked for only now), and «Movimiento», the best price over the stored history - its chart loaded only now too.
 */
import { lazy, Suspense, useMemo, useRef, type ReactNode } from "react";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { t } from "@/lib/i18n";
import { useScrollCue } from "@/lib/scrollCue";
import { formatOdds, fmtPct, fmtSignedPct } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { GlossaryLink } from "@/components/system/GlossaryTerm";
import { ErrorState } from "@/product/shared/States";
import { timeExtent } from "../movement";
import { bookLine, bookMarket, compareGrid, type CompareGrid as CompareGridData } from "./compare";
import type { RowEnv } from "./env";
import { movementLines, moveSummary } from "./history";
import type { OddsBoardRow } from "./model";
import { selectionLabel, type Sides } from "./selections";
import { Bone } from "./ui";

const MovementChart = lazy(() => import("./MovementChart"));

function PanelShell({
  id,
  title,
  aside,
  testId,
  children,
}: {
  id: string;
  title: string;
  aside?: ReactNode;
  testId: string;
  children: ReactNode;
}) {
  return (
    <div
      id={id}
      data-testid={testId}
      className="mt-3 rounded-lg border border-border bg-background/50 p-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h4 className="font-display text-xs font-semibold">{title}</h4>
        {aside ? <div className="text-caption text-subtle-foreground">{aside}</div> : null}
      </div>
      {children}
    </div>
  );
}

/** The grid itself: mounted once the book is in, so its scroll cue watches the table that is there. */
function CompareTable({
  grid,
  row,
  env,
  sides,
  match,
}: {
  grid: CompareGridData;
  row: OddsBoardRow;
  env: RowEnv;
  sides: Sides;
  match: string;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  useScrollCue(scroller);
  return (
    <div
      ref={scroller}
      role="region"
      aria-label={t("explorer.compare.region", { match })}
      // Focusable: a keyboard scrolls it sideways (WCAG 2.1.1); the bookmaker's column stays put, and the edge fades
      // where more columns wait (scroll-fade).
      tabIndex={0}
      className="scroll-fade mt-2 overflow-x-auto rounded-md border border-border/70 bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <table className="w-full min-w-max border-collapse text-xs">
        <caption className="sr-only">{t("explorer.compare.caption", { match })}</caption>
        <thead>
          <tr className="border-b border-border/70 text-left text-muted-foreground">
            <th scope="col" className="sticky left-0 z-10 bg-card px-2.5 py-2 font-medium">
              {t("explorer.price.bookmaker")}
            </th>
            {grid.selections.map((s, i) => (
              <th key={i} scope="col" className="px-2.5 py-2 text-right font-medium">
                <span aria-hidden>{selectionLabel(env.info, s, row.line, sides)}</span>
                <span className="sr-only">
                  {selectionLabel(env.info, s, row.line, sides, "full")}
                </span>
              </th>
            ))}
            <th scope="col" className="px-2.5 py-2 text-right font-medium">
              {t("explorer.compare.margin")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {grid.rows.map((r) => (
            <tr key={r.bookmaker_id} data-testid="explorer-compare-row">
              <th
                scope="row"
                className="sticky left-0 z-10 max-w-[9rem] truncate bg-card px-2.5 py-2 text-left font-medium"
              >
                {r.bookmaker}
              </th>
              {r.cells.map((c, i) => (
                <td
                  key={i}
                  className={cn(
                    "numeric px-2.5 py-2 text-right tabular-nums",
                    c.best ? "font-bold text-primary" : "text-foreground-soft",
                  )}
                >
                  {c.odds === null ? (
                    <>
                      <span aria-hidden>—</span>
                      <span className="sr-only">{t("explorer.compare.noPrice")}</span>
                    </>
                  ) : (
                    <span className={cn(c.best && "rounded px-1 py-0.5 ring-1 ring-primary/45")}>
                      {formatOdds(c.odds)}
                      {c.best ? (
                        <span className="sr-only"> {t("explorer.compare.best")}</span>
                      ) : null}
                    </span>
                  )}
                </td>
              ))}
              <td className="numeric px-2.5 py-2 text-right tabular-nums text-subtle-foreground">
                {r.margin === null ? "—" : fmtPct(r.margin)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Every bookmaker of the row's line, a column per selection, the first column fixed while the grid scrolls sideways. */
export function ComparePanel({
  id,
  row,
  env,
  sides,
}: {
  id: string;
  row: OddsBoardRow;
  env: RowEnv;
  sides: Sides;
}) {
  const book = env.data.useMatchBook(row.fixture_id, env.family, true);
  const line = bookLine(bookMarket(book.data, env.info.key, env.period), row.line);
  const names = book.data?.bookmakers ?? [];
  const grid = line ? compareGrid(env.info, line, names) : null;
  const match = `${row.home.name} ${t("common.vs")} ${row.away.name}`;

  let body;
  if (book.isPending) {
    body = (
      <div className="mt-3 space-y-2" aria-busy="true" aria-label={t("common.loading")}>
        {[0, 1, 2].map((i) => (
          <Bone key={i} className="h-7" />
        ))}
      </div>
    );
  } else if (book.isError && !book.data) {
    body = <ErrorState error={book.error} onRetry={book.refetch} className="py-4" />;
  } else if (!grid || grid.rows.length === 0) {
    body = <p className="mt-2 text-xs text-muted-foreground">{t("explorer.compare.empty")}</p>;
  } else {
    body = <CompareTable grid={grid} row={row} env={env} sides={sides} match={match} />;
  }

  return (
    <PanelShell
      id={id}
      testId="explorer-compare"
      title={t("explorer.compare.title")}
      aside={
        <>
          {t("explorer.compare.help")} <GlossaryLink term="margin" />
        </>
      }
    >
      {body}
    </PanelShell>
  );
}

const TREND_ICON = { up: TrendingUp, down: TrendingDown, flat: Minus } as const;

/** The best price over time: per selection, an arrow and the change in words; the charts below load on demand. */
export function MovementPanel({
  id,
  row,
  env,
  sides,
}: {
  id: string;
  row: OddsBoardRow;
  env: RowEnv;
  sides: Sides;
}) {
  const movement = env.data.useMovement(
    row.fixture_id,
    { market: env.info.key, period: env.period, line: row.line },
    true,
  );
  const lines = useMemo(
    () => movementLines(movement.data).filter((l) => l.points.length > 0),
    [movement.data],
  );
  const extent = timeExtent(lines);

  let body;
  if (movement.isPending) {
    body = <Bone className="mt-3 h-24" />;
  } else if (movement.isError && !movement.data) {
    body = <ErrorState error={movement.error} onRetry={movement.refetch} className="py-4" />;
  } else if (movement.data && !movement.data.available) {
    body = <p className="mt-2 text-xs text-muted-foreground">{t("explorer.movement.none")}</p>;
  } else if (!extent) {
    body = <p className="mt-2 text-xs text-muted-foreground">{t("explorer.movement.empty")}</p>;
  } else {
    const titled = lines.map((l) => ({
      key: `${l.series.selection}|${l.series.line ?? ""}`,
      // the history has no player props (only the classic markets and the extracted types keep one)
      title: selectionLabel(env.info, { ...l.series, player: null }, row.line, sides),
      points: l.points,
    }));
    body = (
      <>
        <ul className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {titled.map((l) => {
            const s = moveSummary(l.points);
            if (!s) return null;
            const Icon = TREND_ICON[s.trend];
            const words =
              s.trend === "flat"
                ? t("explorer.movement.flat", { odds: formatOdds(s.first) })
                : t(`explorer.movement.${s.trend}`, {
                    odds: formatOdds(s.first),
                    change: fmtSignedPct(s.change),
                  });
            return (
              <li
                key={l.key}
                data-testid="explorer-move-summary"
                data-trend={s.trend}
                // The figures go under the name when a phone has no room for both.
                className="flex min-w-0 flex-wrap items-center justify-between gap-x-2 gap-y-0.5 rounded-md border border-border/70 bg-card px-2.5 py-1.5"
              >
                <span className="min-w-0 max-w-full truncate text-xs font-semibold">{l.title}</span>
                <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-caption text-muted-foreground">
                  <span className="numeric text-sm font-semibold text-foreground">
                    {formatOdds(s.last)}
                  </span>
                  <Icon aria-hidden className="h-3.5 w-3.5" />
                  <span className="numeric whitespace-nowrap">{words}</span>
                </span>
              </li>
            );
          })}
        </ul>
        <div className="mt-2.5">
          <Suspense fallback={<Bone className="h-24" />}>
            <MovementChart lines={titled} extent={extent} />
          </Suspense>
        </div>
      </>
    );
  }

  return (
    <PanelShell
      id={id}
      testId="explorer-movement"
      title={t("explorer.movement.title")}
      aside={t("explorer.movement.help")}
    >
      {body}
    </PanelShell>
  );
}
