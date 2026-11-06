/**
 * ANÁLISIS PREDIGOL, the structured reading (plan UX, A9; section 26): six sections - summary, context, data, market, risks
 * and PrediGol's conclusion - each a list of facts the API sends as codes with their references, written here in the reader's
 * language. No AI writes it and no visit calls one: «Lectura automática con los datos de PrediGol», with the time of its data.
 *
 * Every state shows: loading, an error with its reference and a retry, the owner having turned it off (said, not hidden) and a
 * partial reading when PrediGol has not gathered the match's context yet. The conclusion carries its caveat: a probability is
 * not a recommendation, and a PrediGol pick is published apart.
 *
 * THE CHRONICLE (A11, UX-025). When the API sends one - the story of the match written by PrediGol's AI from the match's own
 * facts and verified news, and checked sentence by sentence before it was stored - the block shows it first, in the page's
 * language: the lead, a paragraph for each side under its name, the head-to-head and what could go wrong, then the outlets of
 * the news it tells («Fuentes»). It says nothing of the forecast, the market or a pick: those stay below it, written from the
 * reading's own templates («Mercado», «Conclusión de PrediGol»). Without a chronicle, the facts: never a text the server did
 * not validate.
 *
 * THE DERIVED SECTIONS (UX-011). Besides the six, the API sends key_points, value and factors, written from the same facts
 * with no AI. This block is the six and only the six (the derived ones repeat what the six say); the Resumen's highlights
 * are where the key points and «Por qué hay valor» are read.
 */
import { useId, type ReactNode } from "react";
import { BookOpenText, ChevronRight, Sparkles, TriangleAlert } from "lucide-react";
import { getLocale, t } from "@/lib/i18n";
import { formatDateTime, formatTime, relativeDay } from "@/lib/time";
import type {
  BaseSectionKey,
  MatchReading,
  NarrativeSection,
  NarrativeSectionKey,
  ReadingFact,
  ReadingNarrative,
  ReadingSection,
} from "@/lib/api/v1/types_reading";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import { useUsefulMoment } from "@/product/feedback/moments";
import { ExplainButton } from "@/product/explain/ExplainSheet";
import { HelpfulVote } from "@/product/feedback/HelpfulVote";
import type { MatchCtx } from "@/product/match/context";
import { factText } from "./text";
import { useReading, type ReadingLoad } from "./useReading";

/** The six sections of the structured reading: the ones the full analysis shows. */
const BASE_KEYS: readonly BaseSectionKey[] = [
  "summary",
  "context",
  "data",
  "market",
  "risks",
  "conclusion",
];

function isBase(section: ReadingSection): boolean {
  return (BASE_KEYS as readonly string[]).includes(section.key);
}

/** The facts of one section of a reading, or none. */
function factsOf(reading: MatchReading, key: ReadingSection["key"]): ReadingFact[] {
  return reading.sections.find((s) => s.key === key)?.facts ?? [];
}

/** The data's time: «Con datos de las 12:30», or of a day when it is not today's. */
function dataAt(iso: string): string {
  return relativeDay(iso) === "today"
    ? t("match.readingBlock.dataAt", { time: formatTime(iso) })
    : t("match.readingBlock.dataAtDay", { date: formatDateTime(iso) });
}

/** The narrative's time: «Escrito con datos de las 12:30», or of a day. */
function writtenAt(iso: string): string {
  return relativeDay(iso) === "today"
    ? t("match.readingBlock.narrative.writtenAt", { time: formatTime(iso) })
    : t("match.readingBlock.narrative.writtenAtDay", { date: formatDateTime(iso) });
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

/** The chronicle's sections in the order they are read. */
const CHRONICLE_KEYS: readonly NarrativeSectionKey[] = ["summary", "home", "away", "h2h", "risks"];

/** The teams' names for the headings of the two sides' paragraphs (without them: «Local» and «Visitante»). */
export interface ChronicleTeams {
  home: string;
  away: string;
}

/** A paragraph of the chronicle: its sentences flow together, each keeping the references it rests on. */
function Paragraph({ section }: { section: NarrativeSection }) {
  return (
    <p className="break-words text-sm leading-relaxed text-foreground/90 sm:text-[0.95rem] sm:leading-7">
      {section.sentences.map((s, i) => (
        <span key={i} data-testid="narrative-sentence" data-refs={s.refs.join(" ")}>
          {i > 0 ? " " : ""}
          {s.text}
        </span>
      ))}
    </p>
  );
}

function chronicleTitle(key: NarrativeSectionKey, teams: ChronicleTeams | undefined): string {
  if (key === "home" || key === "away") {
    return teams?.[key] || t(`match.readingBlock.narrative.${key}`);
  }
  return key === "summary"
    ? t("match.readingBlock.sections.summary")
    : t(`match.readingBlock.narrative.${key}`);
}

function ChronicleSection({
  section,
  teams,
}: {
  section: NarrativeSection;
  teams: ChronicleTeams | undefined;
}) {
  const id = useId();
  const lead = section.key === "summary";
  return (
    <section
      aria-labelledby={id}
      data-testid={`narrative-section-${section.key}`}
      className={
        section.key === "risks"
          ? "space-y-1.5 rounded-lg border border-border bg-elevated/40 px-3 py-2.5"
          : "space-y-1.5"
      }
    >
      <h3
        id={id}
        className={
          lead
            ? "sr-only"
            : "min-w-0 break-words text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground"
        }
      >
        {chronicleTitle(section.key, teams)}
      </h3>
      <Paragraph section={section} />
    </section>
  );
}

/**
 * The chronicle in the page's language: the lead, a paragraph for each side, the head-to-head and the risks - each only when
 * the match has something to say there - then the outlets of the news it tells.
 */
export function NarrativeBody({
  narrative,
  teams,
}: {
  narrative: ReadingNarrative;
  teams?: ChronicleTeams | undefined;
}) {
  const sections = getLocale() === "es" ? narrative.es : narrative.en;
  const outlets = (narrative.sources ?? []).map((o) => o.name).filter(Boolean);
  return (
    <div className="space-y-4" data-testid="reading-narrative" data-version={narrative.version}>
      {CHRONICLE_KEYS.flatMap((key) => {
        const section = sections.find((s) => s.key === key);
        return section && section.sentences.length
          ? [<ChronicleSection key={key} section={section} teams={teams} />]
          : [];
      })}
      {outlets.length ? (
        <Note testId="narrative-sources">
          {t("match.readingBlock.narrative.sources", { names: outlets.join(", ") })}
        </Note>
      ) : null}
      <Note testId="narrative-apart">{t("match.readingBlock.narrative.apart")}</Note>
    </div>
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
  label,
}: {
  titleId: string;
  children: ReactNode;
  right?: ReactNode;
  /** The line under the title: how the reading was written. */
  label?: ReactNode;
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
          <p className="mt-0.5 text-xs text-muted-foreground" data-testid="reading-label">
            {label ?? t("match.readingBlock.label")}
          </p>
        </div>
        {right}
      </header>
      <div className="space-y-5 px-4 pb-4 pt-3">{children}</div>
    </section>
  );
}

/** Once the match is over, the way from what was read before it to what happened (plan UX, B4). */
function ToPostmatch({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid="reading-to-postmatch"
      className="tap-y relative inline-flex min-h-9 items-center gap-1 text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {t("match.postmatch.fromReading")}
      <ChevronRight aria-hidden className="h-4 w-4" />
    </button>
  );
}

/**
 * The whole reading, from an answer of the API (apart from the query so a test can render it from a fixture). ``afterMatch``:
 * the match is over, and the reading ends with the way to its Postpartido.
 */
export function ReadingView({
  load,
  afterMatch,
  footer,
  teams,
}: {
  load: ReadingLoad;
  afterMatch?: (() => void) | undefined;
  /** The end of a reading shown: «¿Te sirvió?» (plan UX, B6). */
  footer?: ReactNode;
  /** The names that head the chronicle's two paragraphs. */
  teams?: ChronicleTeams | undefined;
}) {
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
  const narrative = reading.narrative ?? null;
  if (narrative) {
    const apart = reading.sections.filter((s) => s.key === "market" || s.key === "conclusion");
    return (
      <Frame
        titleId={titleId}
        label={
          <span className="inline-flex items-start gap-1">
            <Sparkles aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
            {t("match.readingBlock.narrative.label")}
          </span>
        }
        right={
          <span
            className="shrink-0 text-right text-caption text-subtle-foreground"
            data-testid="reading-data-at"
          >
            {writtenAt(narrative.data_at)}
          </span>
        }
      >
        <NarrativeBody narrative={narrative} teams={teams} />
        {apart.map((s) => (
          <SectionView key={s.key} section={s} />
        ))}
        {footer}
        {afterMatch ? <ToPostmatch onClick={afterMatch} /> : null}
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
      {reading.sections.filter(isBase).map((s) => (
        <SectionView key={s.key} section={s} />
      ))}
      {footer}
      {afterMatch ? <ToPostmatch onClick={afterMatch} /> : null}
    </Frame>
  );
}

/**
 * The Análisis tab's block: once the match is over, it ends with the way to the Postpartido. A reading shown is a useful
 * moment (the monthly survey may follow, B6) and ends with «¿Te sirvió?» about it - the narrative's, or the facts'.
 */
export function ReadingBlock({ ctx }: { ctx: MatchCtx }) {
  const load = useReading(ctx);
  const reading =
    load.status === "success" && load.envelope.status === "ok" ? load.envelope.data : null;
  useUsefulMoment("analysis_opened", reading !== null);
  const fixtureId = Number(ctx.fixtureId);
  return (
    <div className="space-y-2">
      <ReadingView
        load={load}
        afterMatch={ctx.phase === "finished" ? () => ctx.goTo("postmatch") : undefined}
        teams={{ home: ctx.match.home.name, away: ctx.match.away.name }}
        footer={
          reading ? (
            <HelpfulVote
              subject={reading.narrative ? "narrative" : "reading"}
              subjectId={reading.fixture_id}
            />
          ) : null
        }
      />
      {Number.isInteger(fixtureId) && fixtureId > 0 ? (
        <div className="flex px-1">
          <ExplainButton entity="match" itemId={fixtureId} testId="explain-match" />
        </div>
      ) : null}
    </div>
  );
}

/** Whether a fact is already among others (the same code from the same place). */
function isIn(fact: ReadingFact, others: ReadingFact[]): boolean {
  return others.some((o) => o.code === fact.code && o.ref === fact.ref);
}

function HighlightBlock({
  title,
  testId,
  children,
}: {
  title: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <div className="mt-3 first:mt-0" data-testid={testId}>
      <h3 className="text-caption font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {title}
      </h3>
      <div className="mt-1 space-y-1">{children}</div>
    </div>
  );
}

/**
 * The top of the Resumen (plan section 25; UX-011): what the match is, the key points, why there is value when PrediGol
 * published a pick and the two main risks, with the way to the whole analysis. Each only when it has something to say; a
 * sentence is said once (the summary leaves out what the key points carry, the key points leave out the pick that «Por qué
 * hay valor» explains right under them). Nothing while the owner has turned the reading off; its own states otherwise (a
 * skeleton, an error with a retry).
 */
export function ReadingHighlightsView({
  load,
  onMore,
  afterMatch,
}: {
  load: ReadingLoad;
  onMore: () => void;
  afterMatch?: (() => void) | undefined;
}) {
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
  const keyPoints = factsOf(reading, "key_points");
  const value = sentences(factsOf(reading, "value"));
  const summary = factsOf(reading, "summary").filter((f) => !isIn(f, keyPoints));
  const points = sentences(
    keyPoints.filter((f) => !(value.length > 0 && f.code === "value_pick")),
  ).map((line) => line.fact);
  const risks = sentences(factsOf(reading, "risks")).slice(0, 2);
  const lead = sentences(summary);
  if (lead.length === 0 && points.length === 0 && value.length === 0 && risks.length === 0)
    return null;
  return (
    <section
      className="min-w-0 rounded-xl border border-border bg-card px-4 py-3.5"
      data-testid="reading-highlights"
    >
      {lead.length ? (
        <FactList facts={lead.map((l) => l.fact)} testId="reading-highlights-summary" />
      ) : null}
      {points.length ? (
        <HighlightBlock title={t("match.understand.keyPointsTitle")} testId="reading-key-points">
          <FactList facts={points} />
        </HighlightBlock>
      ) : null}
      {value.length ? (
        <HighlightBlock title={t("match.understand.valueTitle")} testId="reading-value">
          <FactList facts={value.map((v) => v.fact)} />
          <Note>{t("match.understand.valueNote")}</Note>
        </HighlightBlock>
      ) : null}
      {risks.length ? (
        <HighlightBlock title={t("match.readingBlock.risksTitle")} testId="reading-risks">
          <ul className="space-y-1" data-testid="reading-highlights-risks">
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
        </HighlightBlock>
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
      {afterMatch ? (
        <div>
          <ToPostmatch onClick={afterMatch} />
        </div>
      ) : null}
    </section>
  );
}

export function ReadingHighlights({ ctx }: { ctx: MatchCtx }) {
  return (
    <ReadingHighlightsView
      load={useReading(ctx)}
      onMore={() => ctx.goTo("analysis")}
      afterMatch={ctx.phase === "finished" ? () => ctx.goTo("postmatch") : undefined}
    />
  );
}
