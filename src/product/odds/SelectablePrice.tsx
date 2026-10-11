/**
 * One price, chosen everywhere the way the Cuotas board does it (REVIEW PREDIGOL, points 6 and 18): a tap
 * puts the selection in "Mi parlay" - the pill turns gold with a tick - and another tap takes it out. Where
 * there is room, a bookmark beside it saves the selection to "Mis picks". Before kick-off only; a quarter
 * line never goes in a parlay (it can still be saved). One component, so every module behaves the same.
 */
import { Bookmark, BookmarkCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds } from "@/lib/i18n/format";
import { useSavedPicks } from "@/product/records/hooks";
import { hasStarted, normLine, selectionKey } from "@/product/records/model";
import type { Pickable } from "@/product/records/pickable";
import { selectionLabel } from "@/product/shared/markets";
import { pickableLeg } from "./parlay";
import { ParlayToggle, PricePill } from "./ParlayPrice";
import { blockedText, isToggleable, useParlayLeg } from "./useParlayLeg";

const SMALL = "min-w-[3rem] px-1.5 py-0.5 text-xs";

export function SelectablePrice({
  sel,
  best = false,
  size = "md",
  save = false,
  className,
}: {
  sel: Pickable;
  /** The best value on show: PrediGol gold. */
  best?: boolean;
  size?: "sm" | "md";
  /** Show "Guardar" beside the price (where there is room). */
  save?: boolean;
  className?: string | undefined;
}) {
  const parlay = useParlayLeg(pickableLeg(sel), sel.status_group);
  const label = selectionLabel({
    market_key: sel.market_key,
    selection: sel.selection,
    line: sel.line,
    home: sel.home,
    away: sel.away,
  });
  const description = `${label} · ${t("records.actions.priceAt", {
    odds: fmtOdds(sel.odds),
    bookmaker: sel.bookmaker ?? "—",
  })}`;
  const blocked = blockedText(parlay);
  const pill = (
    <PricePill
      odds={sel.odds}
      best={best}
      state={parlay}
      className={cn(size === "sm" && SMALL, parlay?.inSlip && "animate-in zoom-in-90 duration-200")}
    />
  );
  return (
    <span
      className={cn("inline-flex items-center gap-1", className)}
      data-testid="selectable-price"
      data-in-slip={parlay?.inSlip || undefined}
    >
      {parlay && isToggleable(parlay) ? (
        <ParlayToggle
          state={parlay}
          srLabel={description}
          className="rounded-md transition-transform active:scale-95"
        >
          {pill}
        </ParlayToggle>
      ) : (
        <span title={blocked ?? undefined}>
          <span className="sr-only">{blocked ? `${description} ${blocked}` : description}</span>
          <span aria-hidden>{pill}</span>
        </span>
      )}
      {save ? <SaveToggle sel={sel} label={label} /> : null}
    </span>
  );
}

/** A card's price row (Picks, the match's Picks tab): a word of help, and the price chosen the Cuotas way. */
export function SelectablePriceRow({ sel }: { sel: Pickable }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="min-w-0 text-caption text-muted-foreground">{t("picks.priceHelp")}</span>
      <SelectablePrice sel={sel} save className="shrink-0" />
    </div>
  );
}

/** "Guardar" as an icon beside a price: in "Mis picks" (filled) or not; nothing to save once it kicked off. */
function SaveToggle({ sel, label }: { sel: Pickable; label: string }) {
  const { saved, save, remove } = useSavedPicks();
  const mine = saved.get(selectionKey(sel));
  const started = hasStarted(sel);
  if (started && !mine) return null;
  const busy = save.isPending || remove.isPending;
  const locked = !!mine && (started || mine.status !== "PENDING");
  const onClick = () => {
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
  return (
    <button
      type="button"
      data-testid="save-pick"
      aria-pressed={!!mine}
      aria-label={`${mine ? t("records.actions.unsave") : t("records.actions.save")}: ${label}`}
      title={mine ? t("records.actions.saved") : t("records.actions.save")}
      disabled={busy || locked}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
        mine
          ? "border-primary/50 bg-primary/12 text-primary"
          : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
      )}
    >
      {mine ? (
        <BookmarkCheck aria-hidden className="h-3.5 w-3.5" />
      ) : (
        <Bookmark aria-hidden className="h-3.5 w-3.5" />
      )}
    </button>
  );
}
