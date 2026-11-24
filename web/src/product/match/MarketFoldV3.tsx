/**
 * AP-P08 (FBI_MARKETS_V3): one market of «Mercados» as a bookmaker lays it out. Folded, its name and period; open, its
 * selections in rows - «Más de 2,5 ··· 1,98», the bookmaker of the best price and how old it is under the name, the price
 * itself (the same SelectablePrice, so Mi parlay is called exactly as before) on the right -, «Comparar casas» a tap away and,
 * under the market, what PrediGol says in one line (marketMarks). No «Seguir» on the row: «Personalizar mercados» does it.
 */
import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { t as t3 } from "./marketsV3Text";
import { fmtLine } from "@/lib/i18n/format";
import { live } from "@/lib/api/v1/queries";
import { useStatsSwitches } from "@/lib/auth/AuthProvider";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { Card } from "@/product/shared/States";
import type { Choose } from "./choose";
import { hiddenLines, type MarketView, type ViewRow } from "./marketCatalog";
import { markLine, type MarkLine } from "./marketMarks";
import { Age, BooksTable } from "./MarketFold";
import { PriceRow } from "./prices";
import { MoreButton } from "./ui";

/** «Más de 2,5», «Valencia +0,5»: a selection of a row, with its line when the market has lines. */
function rowLabel(view: MarketView, selection: string, label: string, line: number | null): string {
  if (view.lines === "ou" && line !== null) return `${label} ${fmtLine(line)}`;
  if (view.lines === "ah" && line !== null) {
    return `${label} ${fmtLine(selection === "Away" ? -line : line, true)}`;
  }
  return label;
}

function Rows({
  view,
  rows,
  choose,
}: {
  view: MarketView;
  rows: ViewRow[];
  choose: Choose | undefined;
}) {
  return (
    <>
      {rows.map((r) => (
        <li key={r.key} className="list-none" data-testid="market-row-group" data-line={r.line}>
          <ul className="m-0 p-0">
            {view.columns.map((c, i) => (
              <PriceRow
                key={c.selection}
                label={rowLabel(view, c.selection, c.label, r.line)}
                price={r.cells[i] ?? null}
                choose={choose}
                note={r.cells[i] ? <Age at={r.cells[i]?.capturedAt} /> : null}
              />
            ))}
          </ul>
        </li>
      ))}
    </>
  );
}

/** «PrediGol 57 % · Casas 51 % · Últimos 20: 7 veces», with «Estimación preliminar» when the model is not calibrated. */
export function MarksLine({ line }: { line: MarkLine }) {
  const parts = [
    line.model !== null ? t3("marketsv3.model", { pct: line.model }) : null,
    line.houses !== null ? t3("marketsv3.houses", { pct: line.houses }) : null,
    line.history ? t3("marketsv3.history", { n: line.history.n, count: line.history.hits }) : null,
  ].filter((x): x is string => x !== null);
  return (
    <p
      className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground"
      data-testid="market-marks"
    >
      <span className="numeric">
        <span className="text-foreground-soft">{line.selection}:</span> {parts.join(" · ")}
      </span>
      {line.preliminary ? (
        <GlossaryTerm term="calibrated">
          <span className="rounded-full border border-border px-1.5 text-micro">
            {t3("marketsv3.preliminary")}
          </span>
        </GlossaryTerm>
      ) : null}
    </p>
  );
}

function useMarkLine(fixtureId: string, view: MarketView): MarkLine | null {
  const { probs, owner } = useStatsSwitches();
  const q = useQuery({ ...live.matchMarketProbs(fixtureId, owner), enabled: probs });
  const marks = q.data?.data.markets.items;
  if (!marks) return null;
  const labelOf = (selection: string, line: number | null) => {
    const col = view.columns.find((c) => c.selection === selection);
    return rowLabel(view, selection, col?.label ?? selection, line);
  };
  return markLine(view, marks, labelOf);
}

export function MarketFoldV3({
  view,
  fixtureId,
  choose,
  defaultOpen = false,
}: {
  view: MarketView;
  fixtureId: string;
  /** What choosing a price saves or adds to the parlay (the markets the server settles only). */
  choose?: Choose | undefined;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [allLines, setAllLines] = useState(false);
  const [books, setBooks] = useState(false);
  const bodyId = useId();
  const pick = view.parlay || view.catalogParlay ? choose : undefined;
  const marks = useMarkLine(fixtureId, view);
  const more = hiddenLines(view);
  const main = view.rows[view.main];
  const rows = allLines ? view.rows : main ? [main] : [];
  const bookCount = new Set(view.rows.flatMap((r) => r.books.map((b) => b.bookmaker))).size;
  return (
    <Card className="min-w-0" data-testid="market-fold" data-v3>
      <h3>
        <button
          type="button"
          data-fold-toggle
          aria-expanded={open}
          aria-controls={open ? bodyId : undefined}
          onClick={() => setOpen((v) => !v)}
          className="tap-y relative flex min-h-11 w-full items-center gap-2 rounded-md px-4 py-1 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <span className="min-w-0 flex-1 break-words font-display text-[0.95rem] font-semibold leading-tight tracking-tight">
            {view.title}
          </span>
          {view.period ? (
            <span className="shrink-0 rounded-full border border-border px-1.5 text-micro text-muted-foreground">
              {view.period}
            </span>
          ) : null}
          <ChevronDown
            aria-hidden
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-180",
            )}
          />
        </button>
      </h3>
      {open ? (
        <div id={bodyId} className="px-4 pb-3">
          {view.catalogParlay ? (
            <p className="mb-1 text-micro text-subtle-foreground" data-testid="market-settles">
              {t(`stats.settlesWith.${view.catalogParlay}`)}
            </p>
          ) : null}
          <ul className="m-0 p-0" data-testid="market-rows">
            <Rows view={view} rows={rows} choose={pick} />
          </ul>
          {marks ? <MarksLine line={marks} /> : null}
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
                {books ? t3("marketsv3.hideBooks") : t3("marketsv3.compare")}
              </MoreButton>
            ) : null}
          </div>
          {books && bookCount > 0 ? <BooksTable view={view} /> : null}
        </div>
      ) : null}
    </Card>
  );
}
