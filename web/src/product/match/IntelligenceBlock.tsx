/**
 * PREDIGOL INTELLIGENCE before kick-off (plan Partidos y Match Center, R1-R3): the first block of the Resumen, full width.
 *
 * ONE reading of the match - the chronicle's first stretch when there is one, otherwise the structured reading as a short
 * running text (`ReadingLeadView`) - then the picks PrediGol published for the match, only when there is one (with the
 * owner's shadow preview on, the picks in evaluation, labelled), and the way to the whole Análisis.
 *
 * What is not here, on purpose: the analysed markets' cards, the AI's «Lectura del día» and the notice of selections in
 * evaluation - they are the owner's, in Avanzado / Auditoría. A reader with no published pick sees no picks block at all.
 * The block keeps the anchor «Mi parlay» links to (`INTELLIGENCE_ID`).
 */
import { useId, type ReactNode } from "react";
import { BrainCircuit, ChevronRight } from "lucide-react";
import { t } from "@/lib/i18n";
import { ReadingLeadView } from "@/product/reading/ReadingBlock";
import { useReading, type ReadingLoad } from "@/product/reading/useReading";
import { INTELLIGENCE_ID } from "./AnalysisBlock";
import type { MatchCtx } from "./context";
import { UpcomingPicks } from "./PicksTab";

/** The block from its parts, apart from the queries so that a test can render it from fixtures. */
export function IntelligenceView({
  reading,
  picks,
  onMore,
}: {
  reading: ReadingLoad;
  /** The published picks of the match (or nothing at all when there are none). */
  picks?: ReactNode;
  onMore: () => void;
}) {
  const titleId = useId();
  return (
    <section
      id={INTELLIGENCE_ID}
      aria-labelledby={titleId}
      data-testid="intelligence-block"
      className="min-w-0 scroll-mt-20 rounded-xl border border-border bg-card"
    >
      <header className="px-4 pt-3.5">
        <h2
          id={titleId}
          className="flex items-center gap-2 font-display text-[0.95rem] font-bold uppercase tracking-[0.08em]"
        >
          <BrainCircuit aria-hidden className="h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0 break-words">{t("match.analysis.title")}</span>
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">{t("match.intelligence.subtitle")}</p>
      </header>
      <div className="space-y-4 px-4 pb-4 pt-3">
        <ReadingLeadView load={reading} />
        {picks}
        <button
          type="button"
          onClick={onMore}
          data-testid="reading-see-all"
          className="tap-y relative inline-flex min-h-9 items-center gap-1 text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {t("match.readingBlock.seeAll")}
          <ChevronRight aria-hidden className="h-4 w-4" />
        </button>
      </div>
    </section>
  );
}

export function IntelligenceBlock({ ctx }: { ctx: MatchCtx }) {
  return (
    <IntelligenceView
      reading={useReading(ctx)}
      picks={<UpcomingPicks ctx={ctx} />}
      onMore={() => ctx.goTo("analysis")}
    />
  );
}
