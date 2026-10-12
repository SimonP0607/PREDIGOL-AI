/**
 * A price that adds its selection to "Mi parlay", or takes it out: a visible "+" while it can be added, gold
 * with a tick once it is in. One leg per match - the slip replaces another selection of the same match.
 */
import type { ReactNode } from "react";
import { Check, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds } from "@/lib/i18n/format";
import { isToggleable, type ParlayLegState } from "./useParlayLeg";

/** The board's price pill, with the parlay's "+" / "✓" when a tap toggles it. */
export function PricePill({
  odds,
  best = false,
  dim = false,
  state,
  className,
}: {
  odds: string | number | null | undefined;
  /** The fixture's best value: PrediGol gold. */
  best?: boolean;
  /** An outlier price: shown, never trusted. */
  dim?: boolean;
  state: ParlayLegState | null;
  className?: string | undefined;
}) {
  const inSlip = !!state?.inSlip;
  const toggleable = isToggleable(state);
  return (
    <span
      className={cn(
        "numeric inline-flex min-w-[3.5rem] items-center justify-center gap-1 rounded-md border px-2 py-1 text-sm font-semibold tabular-nums transition-colors",
        inSlip
          ? "border-gold bg-gold text-gold-foreground"
          : best
            ? "border-gold/50 bg-gold-soft text-gold-strong"
            : "border-border-strong bg-elevated text-foreground",
        dim && !inSlip && "opacity-60",
        className,
      )}
    >
      {fmtOdds(odds)}
      {toggleable ? (
        inSlip ? (
          <Check aria-hidden className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <Plus aria-hidden className="h-3.5 w-3.5 shrink-0 opacity-80" />
        )
      ) : null}
    </span>
  );
}

/** The button around a price (or a whole board cell): pressed while the selection is in the parlay. */
export function ParlayToggle({
  state,
  srLabel,
  className,
  children,
}: {
  state: ParlayLegState;
  /** What the price is, for a screen reader; the visible content is hidden from it. */
  srLabel: string;
  className?: string | undefined;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      data-testid="odds-add-to-parlay"
      aria-pressed={state.inSlip}
      title={
        state.inSlip
          ? t("odds.parlay.remove")
          : state.replaces
            ? t("odds.parlay.replaces")
            : t("odds.parlay.add")
      }
      onClick={state.toggle}
      className={cn(
        // tap: a price pill is 30 px tall; on a touch screen it answers 44 px around it.
        "tap relative cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <span className="sr-only">{`${srLabel} ${t("odds.parlay.add")}`}</span>
      {children}
    </button>
  );
}
