/**
 * "Guardar" and "Agregar a parlay" for one selection, wherever it is shown: a PrediGol pick,
 * a price in the Match Center. Both stop at kick-off; a quarter line cannot go in a parlay.
 */
import type { ReactNode } from "react";
import { Bookmark, BookmarkCheck, ListPlus, ListChecks } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds } from "@/lib/i18n/format";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { selectionLabel } from "@/product/shared/markets";
import { useSavedPicks } from "./hooks";
import { hasStarted, isQuarterLine, normLine, selectionKey } from "./model";
import type { Pickable } from "./pickable";
import { useSlip } from "./slipContext";

const BUTTON =
  "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

export function SelectionActions({
  sel,
  layout = "row",
  className,
}: {
  sel: Pickable;
  layout?: "row" | "column";
  className?: string | undefined;
}) {
  const { saved, save, remove } = useSavedPicks();
  const slip = useSlip();
  const key = selectionKey(sel);
  const mine = saved.get(key);
  const inSlip = slip.has(key);
  const started = hasStarted(sel);
  const quarter = isQuarterLine(sel.line);
  const busy = save.isPending || remove.isPending;

  const onSave = () => {
    if (mine) {
      if (mine.status === "PENDING") remove.mutate(mine.id);
      return;
    }
    save.mutate({
      fixture_id: sel.fixture_id,
      market_key: sel.market_key,
      selection: sel.selection,
      line: normLine(sel.line),
      pick_id: sel.pick_id ?? null,
    });
  };
  const onParlay = () =>
    slip.toggle({
      fixture_id: sel.fixture_id,
      market_key: sel.market_key,
      selection: sel.selection,
      line: normLine(sel.line),
      home: sel.home,
      away: sel.away,
      kickoff_at: sel.kickoff_at,
      odds: sel.odds,
      bookmaker: sel.bookmaker,
      p_model: sel.p_model ?? null,
    });

  return (
    <div
      className={cn(
        "flex gap-2",
        layout === "column" ? "flex-col items-stretch" : "flex-wrap items-center",
        className,
      )}
    >
      <button
        type="button"
        data-testid="save-pick"
        aria-pressed={!!mine}
        disabled={busy || (started && !mine) || (!!mine && (started || mine.status !== "PENDING"))}
        title={
          started ? t("records.actions.started") : mine ? t("records.actions.unsave") : undefined
        }
        onClick={onSave}
        className={cn(
          BUTTON,
          mine
            ? "border-primary/50 bg-primary/12 text-primary"
            : "border-border-strong bg-card text-foreground hover:bg-elevated",
        )}
      >
        {mine ? (
          <BookmarkCheck aria-hidden className="h-3.5 w-3.5" />
        ) : (
          <Bookmark aria-hidden className="h-3.5 w-3.5" />
        )}
        {mine ? t("records.actions.saved") : t("records.actions.save")}
      </button>
      <button
        type="button"
        data-testid="add-to-parlay"
        aria-pressed={inSlip}
        disabled={(started || quarter) && !inSlip}
        title={
          quarter
            ? t("records.actions.quarterLine")
            : started
              ? t("records.actions.started")
              : inSlip
                ? t("records.actions.removeFromParlay")
                : undefined
        }
        onClick={onParlay}
        className={cn(
          BUTTON,
          inSlip
            ? "border-gold/50 bg-gold-soft text-gold-strong"
            : "border-border-strong bg-card text-foreground hover:bg-elevated",
        )}
      >
        {inSlip ? (
          <ListChecks aria-hidden className="h-3.5 w-3.5" />
        ) : (
          <ListPlus aria-hidden className="h-3.5 w-3.5" />
        )}
        {inSlip ? t("records.actions.inParlay") : t("records.actions.addToParlay")}
      </button>
    </div>
  );
}

/**
 * A price that opens a small menu: save the selection, or add it to the parlay. Used in the
 * Match Center, where every price of every market can be chosen.
 */
export function PriceMenu({ sel, children }: { sel: Pickable; children: ReactNode }) {
  const label = selectionLabel({
    market_key: sel.market_key,
    selection: sel.selection,
    line: sel.line,
    home: sel.home,
    away: sel.away,
  });
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="price-menu"
          aria-label={`${label} · ${fmtOdds(sel.odds)}`}
          className="rounded-md transition-transform hover:scale-[1.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {children}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-3" align="center" data-testid="price-menu-content">
        <p className="text-caption text-muted-foreground">{t("records.actions.choose")}</p>
        <p className="mt-1 font-display text-sm font-semibold leading-snug">{label}</p>
        {sel.odds ? (
          <p className="numeric mt-0.5 text-xs text-muted-foreground">
            {t("records.actions.priceAt", {
              odds: fmtOdds(sel.odds),
              bookmaker: sel.bookmaker ?? "—",
            })}
          </p>
        ) : null}
        <SelectionActions sel={sel} layout="column" className="mt-3" />
      </PopoverContent>
    </Popover>
  );
}
