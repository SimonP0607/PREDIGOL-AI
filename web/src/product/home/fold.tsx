/**
 * A list that is short on a phone (plan de Inicio, 4.1): its first rows show and a «Ver N más» opens the rest; from `sm` up every
 * row shows, as before. The rows stay in the page - hidden only by the width - so nothing is fetched or counted twice, and a
 * list that fits shows no button.
 */
import { useState, type ReactNode } from "react";
import { t } from "@/lib/i18n";

export interface Fold {
  /** The class of row `i`: hidden on a phone while folded and past the kept rows. */
  row: (i: number) => string | undefined;
  /** The «Ver N más» button: only on a phone, only while there is something folded. */
  more: ReactNode;
}

export function useFold(total: number, keep: number): Fold {
  const [open, setOpen] = useState(false);
  const folded = !open && total > keep;
  return {
    row: (i) => (folded && i >= keep ? "max-sm:hidden" : undefined),
    more: folded ? (
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="fold-more"
        className="mt-1 flex min-h-11 w-full items-center justify-center rounded-lg border border-border text-sm font-medium text-primary hover:bg-elevated/60 sm:hidden"
      >
        {t("home.fold.more", { count: total - keep })}
      </button>
    ) : null,
  };
}
