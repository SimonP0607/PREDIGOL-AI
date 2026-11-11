/**
 * «Ahora 2,07 (−10,0 %) · hace 12 min»: the price of a selection now, beside the one it was taken at (plan CUOTAS, phase 6).
 * It states a move of the price with its own hour; an old price says it is old, never passing as the current one. No verdict:
 * it is not value, not an edge, not a state, and it names no bookmaker.
 */
import type { PriceNow } from "@/lib/api/v1/types_records";
import { t } from "@/lib/i18n";
import { formatOdds, fmtSignedPct } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { Freshness } from "./Bits";

export function PriceNowLine({
  now,
  className,
}: {
  now: PriceNow | null | undefined;
  className?: string | undefined;
}) {
  if (!now) return null;
  const stale = now.freshness === "stale";
  return (
    <span
      className={cn(
        "flex flex-col items-end gap-0.5 text-caption text-muted-foreground",
        className,
      )}
      data-testid="price-now"
      data-freshness={now.freshness}
    >
      <span className="numeric">
        {t("records.priceNow.now", { odds: formatOdds(now.odds) })}
        {now.change === null ? null : (
          <>
            {" "}
            <span data-testid="price-now-change">({fmtSignedPct(now.change, 1)})</span>
          </>
        )}
      </span>
      <span className="inline-flex items-center gap-1">
        <Freshness at={now.as_of} level={now.freshness} hint={false} />
        {stale ? <span className="text-warning">{t("records.priceNow.stale")}</span> : null}
      </span>
    </span>
  );
}
