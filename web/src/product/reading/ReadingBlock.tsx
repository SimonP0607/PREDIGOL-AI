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
 * with no AI. This block is the six and only the six (the derived ones repeat what the six say).
 *
 * THE RESUMEN'S ONE READING (plan Partidos y Match Center, R2: `ReadingLeadView`, inside PrediGol Intelligence). The
 * chronicle's first stretch when there is one; otherwise the structured reading as a short running text - the summary with
 * its key points, how the sides arrive, the key absences, what could go wrong and the conclusion. Never both.
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
function isIn(fact: ReadingFact, others: readonly ReadingFact[]): boolean {
  return others.some((o) => o.code === fact.code && o.ref === fact.ref);
}

/** «Por qué hay valor» belongs to a published pick: the pick's own card, under the reading, says it. */
const PICK_CODES: ReadonlySet<string> = new Set(["value_pick", "value_price"]);
/** How the sides arrive and what they play for. */
const ARRIVAL_CODES: ReadonlySet<string> = new Set([
  "stakes_zone",
  "stakes_gap_up",
  "stakes_gap_down",
  "stakes_pressure",
  "first_leg",
  "tie_outlook",
  "form",
  "streak_unbeaten",
  "streak_winless",
]);
/** The verified news of the match: its key absences. */
const NEWS_CODES: ReadonlySet<string> = new Set(["key_absences"]);
/** A short text: at most this many sentences on how the sides arrive, and the two main risks. */
const MAX_ARRIVAL = 4;
const MAX_RISKS = 2;

type LeadParagraphKey = "summary" | "arrival" | "news" | "risks" | "conclusion";

interface LeadParagraph {
  key: LeadParagraphKey;
  facts: ReadingFact[];
}

/**
 * The structured reading as a short running text (plan Partidos y Match Center, R2): what the match is with its key points,
 * how the sides arrive and what they play for, the verified news (key absences), what could go wrong (two risks at most) and
 * PrediGol's conclusion - each paragraph only when it has a sentence, and each sentence said once.
 */
function leadParagraphs(reading: MatchReading): LeadParagraph[] {
  const said: ReadingFact[] = [];
  const take = (facts: readonly ReadingFact[], max = Infinity): ReadingFact[] => {
    const out: ReadingFact[] = [];
    for (const { fact } of sentences([...facts])) {
      if (out.length >= max || isIn(fact, said)) continue;
      said.push(fact);
      out.push(fact);
    }
    return out;
  };
  const keyPoints = factsOf(reading, "key_points").filter(
    (f) => !PICK_CODES.has(f.code) && !NEWS_CODES.has(f.code),
  );
  const context = [...factsOf(reading, "context"), ...factsOf(reading, "data")];
  const paragraphs: LeadParagraph[] = [
    { key: "summary", facts: take([...factsOf(reading, "summary"), ...keyPoints]) },
    {
      key: "arrival",
      facts: take(
        context.filter((f) => ARRIVAL_CODES.has(f.code)),
        MAX_ARRIVAL,
      ),
    },
    { key: "news", facts: take(context.filter((f) => NEWS_CODES.has(f.code))) },
    { key: "risks", facts: take(factsOf(reading, "risks"), MAX_RISKS) },
    {
      key: "conclusion",
      // the result PrediGol expects, once: the summary already said it
      facts: take(
        factsOf(reading, "conclusion").filter(
          (f) =>
            !PICK_CODES.has(f.code) &&
            !(
              f.code === "likely" &&
              said.some((x) => x.code === "expected_result" && x.ref === f.ref)
            ),
        ),
      ),
    },
  ];
  return paragraphs.filter((p) => p.facts.length > 0);
}

/** The facts of a paragraph flowing together, each sentence keeping its code and the place it comes from. */
function FactParagraph({ facts, lead }: { facts: ReadingFact[]; lead?: ReactNode }) {
  return (
    <p className="break-words text-sm leading-relaxed text-foreground/90">
      {lead ? <strong className="font-semibold text-foreground">{lead} </strong> : null}
      {sentences(facts).map(({ fact, text }, i) => (
        <span
          key={`${fact.code}-${i}`}
          data-testid="reading-fact"
          data-code={fact.code}
          data-ref={fact.ref}
        >
          {i > 0 ? " " : ""}
          {text}
        </span>
      ))}
    </p>
  );
}

/** The chronicle's first stretch: its lead, or the first section it has. */
function chronicleLead(narrative: ReadingNarrative): NarrativeSection | null {
  const sections = getLocale() === "es" ? narrative.es : narrative.en;
  for (const key of CHRONICLE_KEYS) {
    const found = sections.find((s) => s.key === key && s.sentences.length > 0);
    if (found) return found;
  }
  return null;
}

/**
 * ONE reading of the match, for PrediGol Intelligence in the Resumen (plan Partidos y Match Center, R2): the chronicle's
 * first stretch when the API sends one (written for the story in force: `FBI_USER_NARRATIVE` on, or the owner's preview),
 * with the time of its data; otherwise the structured reading as a short running text (`leadParagraphs`). Never both:
 * the whole of either is in Análisis. Its own states: a skeleton, an error with a retry, the owner having turned it off.
 */
export function ReadingLeadView({ load }: { load: ReadingLoad }) {
  if (load.status === "pending") {
    return (
      <div
        aria-busy="true"
        aria-label={t("common.loading")}
        className="space-y-2"
        data-testid="reading-lead"
        data-kind="loading"
      >
        <SkeletonBlock className="h-4 w-3/4" />
        <SkeletonBlock className="h-4 w-2/3" />
        <SkeletonBlock className="h-4 w-1/2" />
      </div>
    );
  }
  if (load.status === "error") {
    return (
      <div data-testid="reading-lead" data-kind="error">
        <ErrorState error={load.error} onRetry={load.retry} className="py-4" />
      </div>
    );
  }
  const reading = load.envelope.data;
  if (load.envelope.status !== "ok" || !reading) {
    return (
      <p
        className="text-sm text-muted-foreground"
        data-empty-state
        data-testid="reading-lead"
        data-kind="unavailable"
      >
        {t("match.readingBlock.unavailable")}
      </p>
    );
  }
  const narrative = reading.narrative ?? null;
  const lead = narrative ? chronicleLead(narrative) : null;
  if (narrative && lead) {
    return (
      <div className="space-y-2" data-testid="reading-lead" data-kind="narrative">
        <p
          className="inline-flex items-start gap-1 text-caption text-muted-foreground"
          data-testid="reading-label"
        >
          <Sparkles aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
          {t("match.readingBlock.narrative.label")}
        </p>
        <div data-testid="reading-narrative-lead" data-section={lead.key}>
          <Paragraph section={lead} />
        </div>
        <Note testId="reading-data-at">{writtenAt(narrative.data_at)}</Note>
      </div>
    );
  }
  const paragraphs = leadParagraphs(reading);
  const when = reading.data_at ?? reading.forecast_at;
  return (
    <div className="space-y-2.5" data-testid="reading-lead" data-kind="facts">
      <p className="text-caption text-muted-foreground" data-testid="reading-label">
        {t("match.readingBlock.label")}
      </p>
      {!reading.complete ? (
        <p
          className="flex items-start gap-2 rounded-lg border border-border bg-elevated/40 px-3 py-2 text-xs text-muted-foreground"
          data-testid="reading-partial"
        >
          <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t("match.readingBlock.incomplete")}
        </p>
      ) : null}
      {paragraphs.map((p) => (
        <div key={p.key} data-testid={`reading-lead-${p.key}`}>
          <FactParagraph
            facts={p.facts}
            lead={p.key === "risks" ? t("match.intelligence.risksLead") : undefined}
          />
        </div>
      ))}
      {paragraphs.some((p) => p.key === "conclusion") ? (
        <Note testId="reading-caveat">{t("match.readingBlock.caveat")}</Note>
      ) : null}
      {when ? <Note testId="reading-data-at">{dataAt(when)}</Note> : null}
    </div>
  );
}
