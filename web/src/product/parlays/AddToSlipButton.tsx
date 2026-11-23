/**
 * «Añadir a Mi parlay» under a parlay PrediGol recorded (plan AP-L03): the legs that are still to be played go into the
 * reader's slip beside what is already there, and the slip opens. It says what it left out and why. Shown only while at
 * least one leg can still be added. Mi parlay is called as it is: its own context, no second slip.
 */
import { Layers } from "lucide-react";
import { toast } from "sonner";
import { t } from "@/lib/i18n";
import type { ParlayRecord } from "@/lib/api/v1/types_records";
import { track } from "@/lib/track";
import { useSlip } from "@/product/records/slipContext";
import { addable, mergeParlay } from "./addToSlip";

export function AddToSlipButton({ parlay }: { parlay: ParlayRecord | null }) {
  const slip = useSlip();
  if (!parlay || parlay.legs.length === 0) return null;
  if (addable(slip.legs, parlay.legs) === 0) return null;
  const add = () => {
    const merge = mergeParlay(slip.legs, parlay.legs);
    if (merge.added === 0) return;
    slip.load(merge.legs);
    slip.setOpen(true);
    track("slip_leg_added", { legs: merge.legs.length });
    const left = merge.started + merge.sameMatch + merge.unsupported + merge.full;
    toast.success(
      left > 0
        ? t("parlays.addToSlip.addedSome", { count: merge.added, left })
        : t("parlays.addToSlip.added", { count: merge.added }),
    );
  };
  return (
    <div className="border-t border-gold/20 px-4 py-3 sm:px-5">
      <button
        type="button"
        onClick={add}
        data-testid="parlay-add-to-slip"
        className="inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-full border border-gold/50 bg-gold-soft px-4 text-sm font-semibold text-gold-strong transition-colors hover:bg-gold-soft/70 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      >
        <Layers aria-hidden className="h-4 w-4" />
        {t("parlays.addToSlip.button")}
      </button>
    </div>
  );
}
