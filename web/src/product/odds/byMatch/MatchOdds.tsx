/**
 * One match's prices, from «Cuotas · Por partido» (plan maestro unificado, UX-142; sheets C03 and C04), in a sheet:
 *
 * - «Mercados» (C03): the three markets of the board first - result, goals, both teams - each selection with its best price
 *   and the bookmaker that gives it, then every other family of the book with how many markets it holds, folded. A search
 *   narrows the markets by name. It reads the match's book in force (GET /matches/{id}/odds-book): nothing is computed.
 * - «Movimiento» (C04): one selection of the result at a time, the best price now and how much it moved since the first
 *   capture, the chart, and opening, highest, lowest and now - read from the stored history (GET /odds/fixtures/{id}/movement).
 *   Movement is information: the page says it, never a reason to bet.
 */
import { lazy, Suspense, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, LineChart, Search } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Segmented } from "@/components/ui/segmented";
import { fieldVariants } from "@/components/ui/field";
import { t } from "@/lib/i18n";
import { formatOdds, toNumber } from "@/lib/i18n/format";
import { formatKickoff } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import { bookWithMatrix, MatrixNotes, useMatrixReading } from "@/product/shared/matrixModules";
import { catalogTarget } from "@/product/match/marketLink";
import type { MatchOddsBook, OddsBookMarket, OddsMovement } from "@/lib/api/v1/types_odds_explorer";
import { familyName, marketTitle } from "../explorer/markets";
import { selectionLabel, type Sides } from "../explorer/selections";
import { movementLines, moveSummary } from "../explorer/history";
import { timeExtent } from "../movement";
import type { MovePoint } from "../movement";

const MovementChart = lazy(() => import("../explorer/MovementChart"));

/** The markets C03 opens with, in its order (the board's three). */
export const LEAD_MARKETS = ["result.1x2", "goals.total", "goals.btts"] as const;

export interface BookView {
  lead: OddsBookMarket[];
  others: { family: string; markets: OddsBookMarket[] }[];
}

/** The book in C03's order: the three lead markets (full time) first, then every other family with its markets (pure). */
export function bookView(book: MatchOddsBook | undefined, q = ""): BookView {
  const needle = q.trim().toLowerCase();
  const all = (book?.families ?? []).flatMap((f) => f.markets.map((m) => ({ family: f.key, m })));
  const match = (m: OddsBookMarket) =>
    !needle || marketTitle(m.info).toLowerCase().includes(needle);
  const lead = LEAD_MARKETS.map(
    (k) => all.find((x) => x.m.info.key === k && x.m.period === "FT")?.m,
  ).filter((m): m is OddsBookMarket => Boolean(m) && match(m!));
  const rest = new Map<string, OddsBookMarket[]>();
  for (const { family, m } of all) {
    if (lead.includes(m) || !match(m)) continue;
    rest.set(family, [...(rest.get(family) ?? []), m]);
  }
  return { lead, others: [...rest.entries()].map(([family, markets]) => ({ family, markets })) };
}

/** Opening, highest, lowest and now of one selection's best price (pure); null without points. */
export function moveFacts(
  points: readonly MovePoint[],
): { open: number; high: number; low: number; now: number } | null {
  if (points.length === 0) return null;
  const odds = points.map((p) => p.odds);
  return {
    open: odds[0]!,
    high: Math.max(...odds),
    low: Math.min(...odds),
    now: odds[odds.length - 1]!,
  };
}

function mainLine(m: OddsBookMarket) {
  const main = toNumber(m.main_line);
  return (
    m.lines.find((l) => (main === null ? l.line === null : toNumber(l.line) === main)) ?? m.lines[0]
  );
}

function MarketCard({
  m,
  sides,
  names,
}: {
  m: OddsBookMarket;
  sides: Sides;
  names: Map<number, string>;
}) {
  const line = mainLine(m);
  if (!line) return null;
  return (
    <section
      className="card-surface rounded-card p-4"
      data-testid="match-odds-market"
      data-market={m.info.key}
    >
      <h3 className="text-subheading">{marketTitle(m.info)}</h3>
      <table className="mt-2 w-full text-sm">
        <thead>
          <tr className="text-left text-label text-subtle-foreground">
            <th scope="col" className="py-1 font-medium">
              {t("odds.byMatch.sheet.selection")}
            </th>
            <th scope="col" className="py-1 text-right font-medium">
              {t("odds.byMatch.sheet.best")}
            </th>
            <th scope="col" className="py-1 pl-3 font-medium">
              {t("odds.byMatch.sheet.book")}
            </th>
          </tr>
        </thead>
        <tbody>
          {line.selections.map((s) => {
            const value = !s.outlier && (toNumber(s.price_edge) ?? 0) > 0;
            return (
              <tr
                key={`${s.selection}-${s.line ?? ""}-${s.player ?? ""}`}
                className="border-t border-border"
              >
                <th scope="row" className="py-2 pr-2 text-left font-semibold">
                  {selectionLabel(m.info, s, line.line, sides, "full")}
                </th>
                <td className="py-2 text-right">
                  <span
                    className={cn(
                      "numeric inline-flex min-w-14 justify-center rounded-control border px-2 py-1 font-bold",
                      value ? "border-positive/60 text-positive" : "border-border",
                    )}
                  >
                    {formatOdds(s.best_odds)}
                  </span>
                  {value ? <span className="sr-only"> {t("odds.byMatch.valueWord")}</span> : null}
                </td>
                <td className="truncate py-2 pl-3 text-muted-foreground">
                  {names.get(s.bookmaker_id) ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function Markets({ fixtureId, sides }: { fixtureId: number; sides: Sides }) {
  const [q, setQ] = useState("");
  const book = useQuery(live.matchOddsBook(fixtureId));
  // PM-14-04 (FBI_MATRIX_ODDS): off, nothing changes; show, a note says what C-16 says; on, the markets with no price in force are left out.
  const matrix = useMatrixReading("odds", fixtureId);
  const shown = useMemo(
    () => bookWithMatrix(book.data?.data, matrix.availability, matrix.mode),
    [book.data, matrix.availability, matrix.mode],
  );
  const view = useMemo(() => bookView(shown, q), [shown, q]);
  const titleOf = useMemo(() => {
    const byKey = new Map<string, string>();
    for (const f of book.data?.data?.families ?? [])
      for (const m of f.markets) {
        const key = catalogTarget(m.info.key, m.period)?.key;
        if (key && !byKey.has(key)) byKey.set(key, marketTitle(m.info));
      }
    return (key: string) => byKey.get(key) ?? null;
  }, [book.data]);
  const names = useMemo(
    () => new Map((book.data?.data?.bookmakers ?? []).map((b) => [b.id, b.name])),
    [book.data],
  );
  if (book.isPending) return <SkeletonBlock className="h-40" />;
  if (book.isError) return <ErrorState error={book.error} onRetry={() => void book.refetch()} />;
  const data = shown;
  if (!data || data.state === "none" || data.families.length === 0)
    return <p className="text-sm text-muted-foreground">{t("odds.byMatch.sheet.noBook")}</p>;
  return (
    <div className="space-y-3">
      <MatrixNotes module="odds" fixtureId={fixtureId} subjectOf={(m) => titleOf(m.key)} />
      <label className="relative block">
        <span className="sr-only">{t("odds.byMatch.sheet.search")}</span>
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground"
        />
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("odds.byMatch.sheet.search")}
          className={cn(fieldVariants(), "pl-9")}
          data-testid="match-odds-search"
        />
      </label>
      {view.lead.map((m) => (
        <MarketCard key={`${m.info.key}-${m.period}`} m={m} sides={sides} names={names} />
      ))}
      {view.others.length > 0 ? (
        <div
          className="card-surface divide-y divide-border rounded-card"
          data-testid="match-odds-families"
        >
          {view.others.map((f) => (
            <details key={f.family} className="group/f">
              <summary className="flex min-h-12 cursor-pointer list-none items-center gap-3 px-4 py-2.5 [&::-webkit-details-marker]:hidden">
                <span className="min-w-0 flex-1 text-sm font-semibold">{familyName(f.family)}</span>
                <span className="numeric text-caption text-muted-foreground">
                  {t("odds.byMatch.sheet.markets", { count: f.markets.length })}
                </span>
                <ChevronRight
                  aria-hidden
                  className="h-4 w-4 shrink-0 text-subtle-foreground transition-transform group-open/f:rotate-90"
                />
              </summary>
              <div className="space-y-3 px-3 pb-3">
                {f.markets.map((m) => (
                  <MarketCard key={`${m.info.key}-${m.period}`} m={m} sides={sides} names={names} />
                ))}
              </div>
            </details>
          ))}
        </div>
      ) : null}
      {view.lead.length === 0 && view.others.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("odds.byMatch.sheet.noMatch", { q })}</p>
      ) : null}
      <p className="text-caption text-muted-foreground">{t("odds.byMatch.sheet.legend")}</p>
    </div>
  );
}

const RESULT = ["Home", "Draw", "Away"] as const;

function Movement({ fixtureId, sides }: { fixtureId: number; sides: Sides }) {
  const [sel, setSel] = useState<(typeof RESULT)[number]>("Home");
  const q = useQuery(live.oddsMovement(fixtureId, { market: "result.1x2", period: "FT" }));
  const lines = useMemo(() => movementLines(q.data?.data as OddsMovement | undefined), [q.data]);
  const line = lines.find((l) => l.selection === sel);
  const points = line?.points ?? [];
  const facts = moveFacts(points);
  const sum = moveSummary(points);
  const extent = timeExtent(line ? [line] : []);
  const label = (s: string) =>
    s === "Home" ? sides.home : s === "Away" ? sides.away : t("odds.byMatch.sheet.draw");
  return (
    <div className="space-y-4" data-testid="match-odds-movement">
      <Segmented<(typeof RESULT)[number]>
        value={sel}
        onChange={setSel}
        label={t("odds.byMatch.sheet.which")}
        full
        options={RESULT.map((s, i) => ({ value: s, label: `${["1", "X", "2"][i]} · ${label(s)}` }))}
      />
      {q.isPending ? (
        <SkeletonBlock className="h-40" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !facts || !sum ? (
        <p className="text-sm text-muted-foreground">{t("explorer.movement.empty")}</p>
      ) : (
        <>
          <div className="card-surface rounded-card p-4">
            <p className="text-overline text-muted-foreground">{t("odds.byMatch.sheet.bestNow")}</p>
            <p className="mt-1 flex flex-wrap items-baseline gap-x-3">
              <span className="numeric font-display text-4xl font-bold" data-testid="movement-now">
                {formatOdds(facts.now)}
              </span>
              {sum.change !== null ? (
                <span className="numeric text-sm text-muted-foreground">
                  {t("odds.byMatch.sheet.since", {
                    change: `${facts.now - facts.open >= 0 ? "+" : "−"}${formatOdds(Math.abs(facts.now - facts.open))}`,
                  })}
                </span>
              ) : null}
            </p>
            {extent ? (
              <div className="mt-3">
                <Suspense fallback={<SkeletonBlock className="h-32" />}>
                  <MovementChart
                    lines={[{ key: sel, title: label(sel), points }]}
                    extent={extent}
                  />
                </Suspense>
              </div>
            ) : null}
          </div>
          <dl className="grid grid-cols-4 gap-2" data-testid="movement-facts">
            {(["open", "high", "low", "now"] as const).map((k) => (
              <div
                key={k}
                className={cn(
                  "rounded-control border px-2 py-2 text-center",
                  k === "now" ? "border-primary/50" : "border-border",
                )}
              >
                <dt className="text-caption text-muted-foreground">
                  {t(`odds.byMatch.sheet.facts.${k}`)}
                </dt>
                <dd className="numeric font-semibold">{formatOdds(facts[k])}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <ul className="card-surface space-y-2 rounded-card p-4 text-sm text-muted-foreground">
        <li>{t("odds.byMatch.sheet.read1")}</li>
        <li>{t("odds.byMatch.sheet.read2")}</li>
      </ul>
      <p className="text-caption text-subtle-foreground">{t("odds.byMatch.sheet.info")}</p>
    </div>
  );
}

export function MatchOddsSheet({
  open,
  onOpenChange,
  fixtureId,
  sides,
  competition,
  kickoffAt,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fixtureId: number;
  sides: Sides;
  competition: string | null;
  kickoffAt: string;
}) {
  const desk = useMediaQuery("(min-width: 768px)");
  const [view, setView] = useState<"markets" | "movement">("markets");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={desk ? "right" : "bottom"}
        closeLabel={t("common.close")}
        data-testid="match-odds-sheet"
        className={cn(
          "flex flex-col gap-4 overflow-y-auto",
          desk
            ? "w-full px-5 py-5 sm:max-w-lg"
            : "max-h-[92dvh] px-4 pb-[calc(1.25rem+env(safe-area-inset-bottom))] pt-5",
        )}
      >
        <div className="pr-10">
          <SheetTitle className="text-subheading">
            {sides.home} – {sides.away}
          </SheetTitle>
          <SheetDescription className="text-caption text-muted-foreground">
            {[competition, formatKickoff(kickoffAt)].filter(Boolean).join(" · ")}
          </SheetDescription>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Link
            to="/matches/$fixtureId"
            params={{ fixtureId: String(fixtureId) }}
            className="tap-y relative inline-flex h-10 items-center justify-center rounded-control border border-border text-sm font-semibold hover:bg-elevated"
          >
            {t("odds.byMatch.sheet.openMatch")}
          </Link>
          <button
            type="button"
            onClick={() => setView(view === "movement" ? "markets" : "movement")}
            aria-pressed={view === "movement"}
            data-testid="match-odds-movement-toggle"
            className={cn(
              "inline-flex h-10 items-center justify-center gap-1.5 rounded-control border text-sm font-semibold hover:bg-elevated",
              view === "movement" ? "border-primary/60 text-primary" : "border-border",
            )}
          >
            <LineChart aria-hidden className="h-4 w-4" />
            {view === "movement"
              ? t("odds.byMatch.sheet.marketsView")
              : t("odds.byMatch.sheet.movement")}
          </button>
        </div>
        {open ? (
          view === "markets" ? (
            <Markets fixtureId={fixtureId} sides={sides} />
          ) : (
            <Movement fixtureId={fixtureId} sides={sides} />
          )
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
