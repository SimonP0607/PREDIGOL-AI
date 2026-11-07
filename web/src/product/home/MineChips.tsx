/**
 * On a general card of the day's picks: why it is also the reader's (plan de Inicio, 3.4) - «Tu equipo», «Tu jugador», «Tu liga»,
 * «Tu mercado» - as a chip each, and with a tap the sentence. The general layer is the same for everyone: the chip is the only
 * thing that tells a reader their favourites are in it, so the card is never taken out of PrediGol's layer and never repeated.
 */
import { hintProps } from "@/components/system/tapHint";
import { t } from "@/lib/i18n";
import type { RelatedPick } from "@/lib/api/v1/types_me_today";
import { marketName } from "@/product/shared/markets";
import { mineReasons } from "./related";
import { namesText } from "./why";

export function MineChips({ related }: { related: RelatedPick }) {
  const reasons = mineReasons(related, marketName(related.market_key));
  if (reasons.length === 0) return null;
  return (
    <div className="mb-1.5 flex min-w-0 flex-wrap items-center gap-1.5" data-testid="mine-chips">
      {reasons.map((r) => (
        <span
          key={r.kind}
          {...hintProps(t(`home.mine.${r.kind}Help`, { names: namesText(r.names) }))}
          data-testid="mine-chip"
          data-kind={r.kind}
          className="min-w-0 max-w-full truncate rounded-full border border-primary/30 bg-primary/10 px-2 py-px text-micro font-medium text-primary"
        >
          {t(`home.mine.${r.kind}`)}
        </span>
      ))}
    </div>
  );
}
