/**
 * One market of «Mercados» before kick-off, folded (plan Partidos y Match Center, F4b: M1-M4): its name, period and
 * bookmakers in a row that opens it; inside, the main line, «Ver N líneas más» and «Ver todas las casas». Every price says
 * its bookmaker and how old it is. A price of the five settled markets is chosen the Cuotas way (parlay, bookmark); a
 * market of the catalogue that is never settled is shown only.
 */
import { useId, useState, type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtLine, fmtOdds, toNumber } from "@/lib/i18n/format";
import { formatDateTime, formatRelative } from "@/lib/time";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { Card } from "@/product/shared/States";
import type { Choose } from "./choose";
import { hiddenLines, type BookLine, type MarketView, type ViewRow } from "./marketCatalog";
import { PriceInline, PriceTile } from "./prices";
import { MoreButton } from "./ui";

/** «hace 12 min», with the exact time on hover. */
export function Age({ at }: { at: string | null | undefined }) {
  if (!at) return null;
  return (
    <span className="numeric" title={formatDateTime(at)} data-testid="price-age">
      {formatRelative(at)}
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

/** One arrow and the first price, when a bookmaker moved since we first saw it. */
function Moved({ now, first }: { now: string; first: string }) {
  const a = toNumber(now);
  const b = toNumber(first);
  if (a === null || b === null || a === b) return null;
  const up = a > b;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className="numeric inline-flex items-center gap-0.5 text-micro text-subtle-foreground"
      title={
        up
          ? t("match.books.movedUp", { odds: fmtOdds(first) })
          : t("match.books.movedDown", { odds: fmtOdds(first) })
      }
    >
      <Icon aria-hidden className="h-3 w-3" />
      {fmtOdds(first)}
    </span>
  );
}

/** The rows of a line market (over/under, handicap): the main one, or every one. */
function LinesTable({
  view,
  rows,
  choose,
}: {
  view: MarketView;
  rows: ViewRow[];
  choose: Choose | undefined;
}) {
  const mainKey = view.rows[view.main]?.key;
  const isOU = view.lines === "ou";
  return (
    <table className="w-full table-fixed">
      <thead>
        <tr className="text-caption text-subtle-foreground">
          {isOU ? (
            <th scope="col" className="w-14 pb-1.5 text-left font-medium">
              <GlossaryTerm term="line">{t("match.markets.line")}</GlossaryTerm>
            </th>
          ) : null}
          {view.columns.map((c) => (
            <th key={c.selection} scope="col" className="pb-1.5 pr-2 text-left font-medium">
              <span className="block break-words leading-tight">{c.label}</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-border/60">
        {rows.map((r) => {
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
              {view.columns.map((c, i) => {
                const price = r.cells[i] ?? null;
                return (
                  <td key={c.selection} className="py-2 pl-1 pr-2">
                    <PriceInline
                      price={price}
                      prefix={
                        isOU ? null : (
                          <LineTag value={c.selection === "Away" ? -line : line} main={isMain} />
                        )
                      }
                      choose={choose}
                      note={price ? <Age at={price.capturedAt} /> : null}
                    />
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** A market without lines: one tile per selection. */
function Tiles({ view, choose }: { view: MarketView; choose: Choose | undefined }) {
  const row = view.rows[0];
  const n = view.columns.length;
  return (
    <div className={cn("grid gap-2", n === 2 || n === 4 ? "grid-cols-2" : "grid-cols-3")}>
      {view.columns.map((c, i) => {
        const price = row?.cells[i] ?? null;
        const first = row?.notes?.[i] ?? null;
        return (
          <PriceTile
            key={c.selection}
            label={c.label}
            price={price}
            showBooks
            choose={choose}
            note={
              price ? (
                <span className="flex flex-col items-center">
                  <Age at={price.capturedAt} />
                  {first ? <span>{first}</span> : null}
                </span>
              ) : null
            }
          />
        );
      })}
    </div>
  );
}

/** Every bookmaker's price of a market (one line at a time for over/under and handicaps), the best in gold. */
function BooksTable({ view }: { view: MarketView }) {
  const [rowKey, setRowKey] = useState<string>(view.rows[view.main]?.key ?? "");
  const row = view.rows.find((r) => r.key === rowKey) ?? view.rows[view.main];
  const table: BookLine[] = row?.books ?? [];
  return (
    <div className="mt-2 space-y-2" data-testid="books-panel">
      {view.lines !== null && view.rows.length > 1 ? (
        <label className="flex items-center gap-2 text-caption text-muted-foreground">
          {t("match.books.lineLabel")}
          <select
            value={row?.key ?? ""}
            onChange={(e) => setRowKey(e.target.value)}
            className="numeric h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:h-11 pointer-coarse:px-3"
          >
            {view.rows.map((r) => (
              <option key={r.key} value={r.key}>
                {fmtLine(r.line ?? 0, view.lines === "ah")}
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
              {view.columns.map((c) => (
                <th key={c.selection} scope="col" className="pb-1 pl-2 text-right font-medium">
                  <span className="block break-words leading-tight">{c.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {table.map((r) => (
              <tr key={r.bookmaker}>
                <th
                  scope="row"
                  className="max-w-[9rem] break-words py-1.5 pr-2 text-left font-normal"
                >
                  {r.bookmaker}
                </th>
                {r.cells.map((c, i) => (
                  <td key={view.columns[i]?.selection ?? i} className="py-1.5 pl-2 text-right">
                    {c ? (
                      <span className="inline-flex flex-col items-end">
                        <span className={cn("numeric", c.best && "font-semibold text-gold-strong")}>
                          {fmtOdds(c.odds)}
                        </span>
                        {c.firstSeen ? <Moved now={c.odds} first={c.firstSeen} /> : null}
                        {c.since ? (
                          <span className="text-micro text-subtle-foreground">
                            <Age at={c.since} />
                          </span>
                        ) : null}
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

export function MarketFold({
  view,
  choose,
  defaultOpen = false,
  follow,
}: {
  view: MarketView;
  /** «Seguir» beside the market (drawn by the page: it reads the reader's account): the classic five or a catalogue market. */
  follow?: ReactNode;
  /** Before kick-off: what choosing a price saves or adds to the parlay (the five settled markets only). */
  choose?: Choose | undefined;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [allLines, setAllLines] = useState(false);
  const [books, setBooks] = useState(false);
  const bodyId = useId();
  const pick = view.parlay ? choose : undefined;
  const more = hiddenLines(view);
  const main = view.rows[view.main];
  const rows = allLines ? view.rows : main ? [main] : [];
  const bookCount = new Set(view.rows.flatMap((r) => r.books.map((b) => b.bookmaker))).size;
  let body: ReactNode = null;
  if (open) {
    body = (
      <div id={bodyId} className="px-4 pb-4 pt-1">
        {view.lines === null ? (
          <Tiles view={view} choose={pick} />
        ) : (
          <LinesTable view={view} rows={rows} choose={pick} />
        )}
        {more > 0 || bookCount > 0 ? (
          <div className="mt-1 flex flex-wrap items-center gap-x-3">
            {more > 0 ? (
              <MoreButton expanded={allLines} onClick={() => setAllLines((v) => !v)}>
                {allLines
                  ? t("match.catalog.mainLineOnly")
                  : t("match.catalog.moreLines", { count: more })}
              </MoreButton>
            ) : null}
            {bookCount > 0 ? (
              <MoreButton expanded={books} onClick={() => setBooks((v) => !v)}>
                {books ? t("match.books.hide") : t("match.books.show", { count: bookCount })}
              </MoreButton>
            ) : null}
          </div>
        ) : null}
        {books && bookCount > 0 ? <BooksTable view={view} /> : null}
      </div>
    );
  }
  return (
    <Card className="min-w-0" data-testid="market-fold">
      <div className="flex min-h-11 items-center gap-2 px-4 py-1">
        <h3 className="min-w-0 flex-1">
          <button
            type="button"
            data-fold-toggle
            aria-expanded={open}
            aria-controls={open ? bodyId : undefined}
            onClick={() => setOpen((v) => !v)}
            className="tap-y relative flex min-h-11 w-full items-center gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <ChevronDown
              aria-hidden
              className={cn(
                "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                !open && "-rotate-90",
              )}
            />
            <span className="min-w-0 break-words font-display text-[0.95rem] font-semibold leading-tight tracking-tight">
              {view.title}
            </span>
            {view.period ? (
              <span className="shrink-0 rounded-full border border-border px-1.5 text-micro text-muted-foreground">
                {view.period}
              </span>
            ) : null}
          </button>
        </h3>
        {follow}
        <span className="shrink-0 text-caption text-subtle-foreground">
          {t("match.markets.books", { count: view.books })}
        </span>
      </div>
      {body}
    </Card>
  );
}
