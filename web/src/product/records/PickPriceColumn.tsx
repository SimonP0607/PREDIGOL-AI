/**
 * The price of a pick of the day (plan AP-K05, decision D4): the price now in big with its hour, the one of publication small
 * beside it, and - only when the expected value at the price now is not positive - «A este precio ya no hay valor». An old
 * price never passes as the current one. See `pickPrice.ts`.
 */
import { t } from "@/lib/i18n";
import { formatOdds, localFixed } from "@/lib/i18n/format";
import type { DailyItem } from "@/lib/api/v1/types_records";
import { Freshness, OddsPill } from "@/product/shared/Bits";
import { PriceNowLine } from "@/product/shared/PriceNowLine";
import { pickPrice } from "./pickPrice";

export function PickPriceColumn({
  item,
  settled,
  compact,
}: {
  item: Pick<DailyItem, "odds" | "p_model" | "price_now">;
  settled: boolean;
  compact: boolean;
}) {
  const price = pickPrice(item);
  return (
    <>
      <OddsPill odds={price.shown} best={!settled} size={compact ? "md" : "lg"} />
      <span className="text-caption text-muted-foreground" data-testid="pick-reference-odds">
        {price.current ? t("records.card.priceCurrent") : t("records.card.referenceOdds")}
      </span>
      {price.current && price.now ? (
        <>
          <span
            className="numeric text-right text-caption text-muted-foreground"
            data-testid="pick-published"
          >
            {t("records.card.published", { odds: formatOdds(price.published) })}
            {price.delta ? (
              <>
                {" · "}
                <span
                  aria-label={t(price.delta > 0 ? "records.card.up" : "records.card.down", {
                    delta: localFixed(Math.abs(price.delta), 2),
                  })}
                >
                  {price.delta > 0 ? "▲" : "▼"} {localFixed(Math.abs(price.delta), 2)}
                </span>
              </>
            ) : null}
          </span>
          <Freshness
            at={price.now.as_of}
            level={price.now.freshness}
            hint={false}
            className="justify-end"
          />
          {price.noValue ? (
            <span
              className="max-w-[10rem] text-right text-caption text-warning"
              data-testid="pick-no-value"
            >
              {t("records.card.noValueNow")}
            </span>
          ) : null}
        </>
      ) : (
        <PriceNowLine now={item.price_now} />
      )}
    </>
  );
}
