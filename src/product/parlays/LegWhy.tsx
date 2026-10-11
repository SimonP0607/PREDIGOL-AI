/**
 * Why a selection is in a parlay (REVIEW PREDIGOL, point 15): the numbers that put it there, said plainly -
 * PrediGol's probability against the market's (and its prudent end, the one the legs are chosen by), the price
 * against its fair price, how many books quote it - and what the AI review said, where the reader may see it.
 * The same block for PrediGol's own parlays (frozen when built) and for the one the builder puts together now.
 */
import type { ReactNode } from "react";
import { BrainCircuit, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtPct, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import type { Dec } from "@/lib/api/v1/types";
import type { ItemAi } from "@/lib/api/v1/types_records";
import { AiNote } from "@/product/records/AiNote";
import { fairOf } from "./why";

export interface WhyNumbers {
  p_model: Dec;
  /** The pessimistic end of the model's interval; absent where the source has none. */
  p_low?: Dec | null | undefined;
  p_market: Dec;
  odds: Dec;
  ev: Dec;
  /** Books quoting it now (the builder's legs). */
  books?: number | null | undefined;
  ai?: ItemAi | null | undefined;
}

function Line({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-start gap-1.5">
      <Check aria-hidden className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
      <span>{children}</span>
    </li>
  );
}

export function LegWhy({
  why,
  frozen,
  className,
}: {
  why: WhyNumbers;
  /** PrediGol's recorded parlay: the price it was taken at, not the price now. */
  frozen: boolean;
  className?: string | undefined;
}) {
  const { fair, edge } = fairOf(why.odds, why.p_market);
  const low = toNumber(why.p_low);
  const ev = toNumber(why.ev);
  return (
    <div className={cn("space-y-1.5", className)} data-testid="leg-why">
      <p className="text-[0.68rem] font-semibold uppercase tracking-wider text-subtle-foreground">
        {t("parlays.why.title")}
      </p>
      <ul className="space-y-1 text-caption text-muted-foreground">
        <Line>
          {low !== null
            ? t("parlays.why.model", {
                model: fmtPct(why.p_model),
                low: fmtPct(low),
                market: fmtPct(why.p_market),
              })
            : t("parlays.why.modelNoLow", {
                model: fmtPct(why.p_model),
                market: fmtPct(why.p_market),
              })}
        </Line>
        {fair !== null ? (
          <Line>
            {t("parlays.why.price", {
              odds: fmtOdds(why.odds),
              fair: fmtOdds(fair),
              edge: fmtSignedPct(edge),
            })}
          </Line>
        ) : null}
        {ev !== null ? (
          <Line>
            {t(frozen ? "parlays.why.evFrozen" : "parlays.why.evNow", { ev: fmtSignedPct(ev) })}
          </Line>
        ) : null}
        {why.books ? <Line>{t("parlays.why.books", { count: why.books })}</Line> : null}
      </ul>
      {why.ai && (why.ai.decision || why.ai.by_llm) ? (
        <div className="rounded-md border border-border/70 bg-background/40 px-2.5 py-2">
          <AiNote ai={why.ai} />
        </div>
      ) : why.ai === undefined || why.ai === null ? (
        <p className="flex items-center gap-1 text-caption text-subtle-foreground">
          <BrainCircuit aria-hidden className="h-3 w-3" />
          {t("parlays.why.noReview")}
        </p>
      ) : null}
    </div>
  );
}
