/**
 * ANÁLISIS PREDIGOL, the structured reading (plan UX, A9; section 26): six sections - summary, context, data, market, risks
 * and PrediGol's conclusion - each a list of facts the API sends as codes with their references, written here in the reader's
 * language. No AI writes it and no visit calls one: «Lectura automática con los datos de PrediGol», with the time of its data.
 *
 * Every state shows: loading, an error with its reference and a retry, the owner having turned it off (said, not hidden) and a
 * partial reading when PrediGol has not gathered the match's context yet. The conclusion carries its caveat: a probability is
 * not a recommendation, and a PrediGol pick is published apart.
 */
import { useId, type ReactNode } from "react";
import { BookOpenText, ChevronRight, TriangleAlert } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatDateTime, formatTime, relativeDay } from "@/lib/time";
import type { ReadingFact, ReadingSection } from "@/lib/api/v1/types_reading";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "@/product/match/context";
import { factText } from "./text";
import { useReading, type ReadingLoad } from "./useReading";

/** The data's time: «Con datos de las 12:30», or of a day when it is not today's. */
function dataAt(iso: string): string {
  return relativeDay(iso) === "today"
    ? t("match.readingBlock.dataAt", { time: formatTime(iso) })
    : t("match.readingBlock.dataAtDay", { date: formatDateTime(iso) });
}

function sentences(facts: ReadingFact[]): Array<{ fact: ReadingFact; text: string }> {
  return facts.flatMap((fact) => {
    const text = factText(fact);
    return text ? [{ fact, text }] : [];
  });
}

function FactList({ facts, testId }: { facts: ReadingFact[]; testId?: string }) {
  const lines = sentences(facts);
  return (
    <ul className="space-y-1.5" data-testid={testId}>
      {lines.map(({ fact, text }, i) => (
        <li
          key={`${fact.code}-${i}`}
          data-testid="reading-fact"
          data-code={fact.code}
          data-ref={fact.ref}
          className="text-sm leading-relaxed text-foreground/90"
        >
          {text}
        </li>
      ))}
    </ul>
  );
}

function SectionView({ section }: { section: ReadingSection }) {
  const id = useId();
  const tableNote = section.facts.some((f) => f.code === "table_after");
  return (
    <section
      aria-labelledby={id}
      data-testid={`reading-section-${section.key}`}
      className="space-y-2"
    >
      <h3
        id={id}
        className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground"
      >
        {t(`match.readingBlock.sections.${section.key}`)}
      </h3>
      <FactList facts={section.facts} />
      {tableNote ? <Note>{t("match.facts.tableNote")}</Note> : null}
      {section.key === "market" && section.facts.some((f) => f.code !== "market_unpriced") ? (
        <Note>{t("match.readingBlock.marketNote")}</Note>
      ) : null}
      {section.key === "conclusion" ? (
        <Note testId="reading-caveat">{t("match.readingBlock.caveat")}</Note>
      ) : null}
    </section>
  );
}

function Note({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p className="text-caption leading-snug text-subtle-foreground" data-testid={testId}>
      {children}
    </p>
  );
}

function Frame({
  titleId,
  children,
  right,
}: {
  titleId: string;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <section
      aria-labelledby={titleId}
      data-testid="match-reading"
      className="min-w-0 rounded-xl border border-border bg-card"
    >
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div className="min-w-0">
          <h2
            id={titleId}
            className="flex items-center gap-2 font-display text-[0.95rem] font-bold uppercase tracking-[0.08em]"
          >
            <BookOpenText aria-hidden className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 break-words">{t("match.readingBlock.title")}</span>
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("match.readingBlock.label")}</p>
        </div>
        {right}
      </header>
      <div className="space-y-5 px-4 pb-4 pt-3">{children}</div>
    </section>
  );
}

/** The whole reading, from an answer of the API (apart from the query so a test can render it from a fixture). */
export function ReadingView({ load }: { load: ReadingLoad }) {
  const titleId = useId();
  if (load.status === "pending") {
    return (
      <Frame titleId={titleId}>
        <div aria-busy="true" aria-label={t("common.loading")} className="space-y-3">
          <SkeletonBlock className="h-4 w-3/4" />
          <SkeletonBlock className="h-4 w-2/3" />
          <SkeletonBlock className="h-24" />
        </div>
      </Frame>
    );
  }
  if (load.status === "error") {
    return (
      <Frame titleId={titleId}>
        <ErrorState error={load.error} onRetry={load.retry} className="py-5" />
      </Frame>
    );
  }
  const reading = load.envelope.data;
  if (load.envelope.status !== "ok" || !reading) {
    return (
      <Frame titleId={titleId}>
        <p
          className="text-sm text-muted-foreground"
          data-empty-state
          data-testid="reading-unavailable"
        >
          {t("match.readingBlock.unavailable")}
        </p>
      </Frame>
    );
  }
  const when = reading.data_at ?? reading.forecast_at;
  return (
    <Frame
      titleId={titleId}
      right={
        when ? (
          <span
            className="shrink-0 text-right text-caption text-subtle-foreground"
            data-testid="reading-data-at"
          >
            {dataAt(when)}
          </span>
        ) : null
      }
    >
      {!reading.complete ? (
        <p
          className="flex items-start gap-2 rounded-lg border border-border bg-elevated/40 px-3 py-2 text-xs text-muted-foreground"
          data-testid="reading-partial"
        >
          <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t("match.readingBlock.incomplete")}
        </p>
      ) : null}
      {reading.sections.map((s) => (
        <SectionView key={s.key} section={s} />
      ))}
    </Frame>
  );
}

/** The Análisis tab's block. */
export function ReadingBlock({ ctx }: { ctx: MatchCtx }) {
  return <ReadingView load={useReading(ctx)} />;
}

/**
 * The top of the Resumen (plan section 25): the reading's summary - what the match is and what is expected - and its two
 * main risks, with the way to the whole analysis. Nothing while the owner has turned the reading off; its own states
 * otherwise (a skeleton, an error with a retry).
 */
export function ReadingHighlightsView({ load, onMore }: { load: ReadingLoad; onMore: () => void }) {
  if (load.status === "pending") {
    return (
      <div
        aria-busy="true"
        aria-label={t("common.loading")}
        className="space-y-2"
        data-testid="reading-highlights"
      >
        <SkeletonBlock className="h-4 w-3/4" />
        <SkeletonBlock className="h-4 w-1/2" />
      </div>
    );
  }
  if (load.status === "error") {
    return (
      <div
        className="rounded-xl border border-border bg-card px-4"
        data-testid="reading-highlights"
      >
        <ErrorState error={load.error} onRetry={load.retry} className="py-4" />
      </div>
    );
  }
  const reading = load.envelope.data;
  if (load.envelope.status !== "ok" || !reading) return null;
  const summary = reading.sections.find((s) => s.key === "summary")?.facts ?? [];
  const risks = sentences(reading.sections.find((s) => s.key === "risks")?.facts ?? []).slice(0, 2);
  if (sentences(summary).length === 0 && risks.length === 0) return null;
  return (
    <section
      className="min-w-0 rounded-xl border border-border bg-card px-4 py-3.5"
      data-testid="reading-highlights"
    >
      <FactList facts={summary} testId="reading-highlights-summary" />
      {risks.length ? (
        <div className="mt-3">
          <h3 className="text-caption font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {t("match.readingBlock.risksTitle")}
          </h3>
          <ul className="mt-1 space-y-1" data-testid="reading-highlights-risks">
            {risks.map(({ fact, text }, i) => (
              <li
                key={`${fact.code}-${i}`}
                data-code={fact.code}
                className="text-sm text-foreground/90"
              >
                {text}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <button
        type="button"
        onClick={onMore}
        data-testid="reading-see-all"
        className="tap-y relative mt-3 inline-flex min-h-9 items-center gap-1 text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {t("match.readingBlock.seeAll")}
        <ChevronRight aria-hidden className="h-4 w-4" />
      </button>
    </section>
  );
}

export function ReadingHighlights({ ctx }: { ctx: MatchCtx }) {
  return <ReadingHighlightsView load={useReading(ctx)} onMore={() => ctx.goTo("analysis")} />;
}
