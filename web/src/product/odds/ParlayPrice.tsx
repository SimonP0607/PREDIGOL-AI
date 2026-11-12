/**
 * A price that adds its selection to "Mi parlay", or takes it out: a visible "+" while it can be added, gold
 * with a tick once it is in. One leg per match - the slip replaces another selection of the same match.
 */
import type { ReactNode } from "react";
import { Check, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatOdds } from "@/lib/i18n/format";
import { priceVariants, type PriceSize } from "@/product/shared/price";
import { isToggleable, parlayActionText, type ParlayLegState } from "./useParlayLeg";

/** The board's price pill, with the parlay's "+" / "✓" when a tap toggles it. */
export function PricePill({
  odds,
  best = false,
  dim = false,
  size = "md",
  state,
  className,
}: {
  odds: string | number | null | undefined;
  /** The fixture's best value: PrediGol gold. */
  best?: boolean;
  /** An outlier price: shown, never trusted. */
  dim?: boolean;
  size?: PriceSize;
  state: ParlayLegState | null;
  className?: string | undefined;
}) {
  const inSlip = !!state?.inSlip;
  const toggleable = isToggleable(state);
  return (
    <span
      className={cn(
        priceVariants({ size, tone: inSlip ? "chosen" : best ? "gold" : "plain" }),
        dim && !inSlip && "opacity-60",
        className,
      )}
    >
      {formatOdds(odds)}
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

/**
 * The button around a price (or a whole board cell): pressed while the selection is in the parlay. Its name, for a screen
 * reader as for a pointer's title, says what a tap does now - «Quitar de mi parlay» once it is in.
 */
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
  const action = parlayActionText(state);
  return (
    <button
      type="button"
      data-testid="odds-add-to-parlay"
      aria-pressed={state.inSlip}
      title={action}
      onClick={state.toggle}
      className={cn(
        // tap: a price chip is 32 or 40 px tall; on a touch screen it answers 44 px around it.
        "tap relative cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <span className="sr-only">{`${srLabel} ${action}`}</span>
      {children}
    </button>
  );
}
