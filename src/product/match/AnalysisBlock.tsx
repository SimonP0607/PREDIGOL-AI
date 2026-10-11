/**
 * PREDIGOL INTELLIGENCE - the markets PrediGol analysed for this match, computed once by PrediGol and read by
 * every user (opening this page never triggers an AI call). One full-width card per selection: the market and
 * the selection in full (never cut), the best price and where, PrediGol's and the market's probabilities, the
 * fair odds, the edge in percentage points and the minimum odds worth taking; then why and what could go
 * wrong, and a button that adds it to "Mi parlay".
 *
 * Without an observed price a card says so and never calls anything value. A user sees only the cards of
 * qualified picks and the model's view of unpriced markets. The evaluation cards, the review's words and the
 * day's reading (the L1 brief) are the owner's preview, or what an enforced review shows everyone; without them
 * every card still reads complete, from its numbers alone.
 */
import { useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BrainCircuit,
  Check,
  CircleCheck,
  Newspaper,
  Plus,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { DASH, fmtOdds, fmtPct, toNumber } from "@/lib/i18n/format";
import { formatRelative } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type {
  AiDecision,
  AnalysisCard,
  BriefView,
  CardAi,
  MatchAnalysis,
} from "@/lib/api/v1/types_ai_layer";
import { ShadowBadge } from "@/product/shared/Bits";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import { useParlayLeg } from "@/product/odds/useParlayLeg";
import type { MatchCtx } from "./context";
import {
  analysisUpdatedAt,
  briefAuthor,
  briefReason,
  cardLeg,
  cardTitle,
  claimTexts,
  injuryLine,
  ppParts,
  riskLines,
  whyLines,
  type CardMatch,
  type Sides,
} from "./intelligence";

/** The block's anchor: "Mi parlay" links here. */
export const INTELLIGENCE_ID = "predigol-intelligence";

const VERDICT_STYLE: Record<AnalysisCard["verdict"], string> = {
  recommended: "border-positive/40 bg-positive-soft text-positive",
  caution: "border-warning/40 bg-warning-soft text-warning",
  not_recommended: "border-negative/40 bg-negative-soft text-negative",
  no_market: "border-info/40 bg-info-soft text-info",
};

const VERDICT_ACCENT: Record<AnalysisCard["verdict"], string> = {
  recommended: "border-l-positive",
  caution: "border-l-warning",
  not_recommended: "border-l-negative",
  no_market: "border-l-info",
};

const DECISION_TONE: Record<AiDecision, string> = {
  APPROVE: "text-positive",
  DOWNGRADE: "text-warning",
  REJECT: "text-negative",
  ABSTAIN: "text-subtle-foreground",
};

const GOOD = "border-positive/40 bg-positive-soft text-positive";
const FAIR = "border-warning/40 bg-warning-soft text-warning";
const POOR = "border-negative/40 bg-negative-soft text-negative";
const UNCERTAINTY_TONE: Record<string, string> = { low: GOOD, medium: FAIR, high: POOR };
const QUALITY_TONE: Record<string, string> = { good: GOOD, fair: FAIR, poor: POOR };

// ── a card ──────────────────────────────────────────────────────────────────

/**
 * One figure. Its label and value are two rows of the figures grid shared with the tiles beside it
 * (a subgrid), so the values line up however many lines a label wraps to - and no label is ever cut.
 */
function Figure({
  label,
  value,
  sub,
  help,
  tone,
}: {
  label: string;
  value: ReactNode;
  /** A second line under the value: where the price is. */
  sub?: string | null | undefined;
  help?: string | undefined;
  tone?: string | undefined;
}) {
  // Six to a row from lg up, where the column is narrowest until xl: a step smaller there.
  return (
    <div
      className="row-span-2 grid min-w-0 grid-rows-subgrid gap-y-1 rounded-lg border border-border/70 bg-elevated/40 px-2.5 py-2 lg:px-2 xl:px-2.5"
      title={help}
    >
      <dt className="break-words text-caption text-subtle-foreground">{label}</dt>
      <dd className="min-w-0">
        <span
          className={cn(
            "numeric block break-words text-sm font-semibold leading-tight sm:text-base lg:text-sm xl:text-base",
            tone,
          )}
        >
          {value}
        </span>
        {sub ? (
          <span className="mt-0.5 block break-words text-caption text-muted-foreground">{sub}</span>
        ) : null}
      </dd>
    </div>
  );
}

function Figures({ card }: { card: AnalysisCard }) {
  if (card.kind === "no_market") {
    // No observed price: no best odds, no market probability, no edge - nothing to call value.
    return (
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Figure label={t("match.analysis.figure.model")} value={fmtPct(card.p_model)} />
        <Figure label={t("match.analysis.figure.fair")} value={fmtOdds(card.fair_odds)} />
        <Figure
          label={t("match.analysis.figure.minimum")}
          value={fmtOdds(card.minimum_odds)}
          help={t("match.analysis.figure.minimumHelp")}
          tone="text-info"
        />
      </dl>
    );
  }
  const edge = toNumber(card.edge);
  const pp = ppParts(edge);
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      <Figure
        label={t("match.analysis.figure.bestOdds")}
        value={fmtOdds(card.odds)}
        sub={card.bookmaker}
        tone={card.verdict === "recommended" ? "text-gold-strong" : undefined}
      />
      <Figure label={t("match.analysis.figure.model")} value={fmtPct(card.p_model)} />
      <Figure label={t("match.analysis.figure.market")} value={fmtPct(card.p_market)} />
      <Figure label={t("match.analysis.figure.fair")} value={fmtOdds(card.fair_odds)} />
      <Figure
        label={t("match.analysis.figure.edge")}
        value={
          pp ? (
            <>
              {pp.value} <span className="text-caption font-medium">{pp.unit}</span>
            </>
          ) : (
            DASH
          )
        }
        help={t("match.analysis.figure.edgeHelp")}
        tone={
          edge === null || edge === 0 ? undefined : edge > 0 ? "text-positive" : "text-negative"
        }
      />
      <Figure
        label={t("match.analysis.figure.minimum")}
        value={fmtOdds(card.minimum_odds)}
        help={t("match.analysis.figure.minimumHelp")}
      />
    </dl>
  );
}

function ReasonList({
  id,
  title,
  icon,
  tone,
  dot,
  lines,
  testId,
}: {
  id: string;
  title: string;
  icon: ReactNode;
  tone: string;
  dot: string;
  lines: string[];
  testId: string;
}) {
  return (
    <div className="min-w-0">
      <h5 id={id} className={cn("flex items-center gap-1.5 text-xs font-semibold", tone)}>
        <span aria-hidden className="shrink-0 [&>svg]:h-3.5 [&>svg]:w-3.5">
          {icon}
        </span>
        {title}
      </h5>
      <ul aria-labelledby={id} className="mt-1.5 space-y-1.5" data-testid={testId}>
        {lines.map((line, i) => (
          <li key={i} className="flex gap-2 text-[0.8125rem] leading-5 text-foreground/85">
            <span aria-hidden className={cn("mt-2 h-1.5 w-1.5 shrink-0 rounded-full", dot)} />
            <span className="min-w-0 break-words">{line}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The review's verdict on the card (owner's preview or enforced): decision, confidence, main reason. */
function ReviewLine({ ai }: { ai: CardAi }) {
  const confidence = toNumber(ai.confidence);
  return (
    <div className="mt-3 space-y-1 border-t border-border/60 pt-2.5" data-testid="analysis-review">
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
        <BrainCircuit aria-hidden className="h-3.5 w-3.5 shrink-0 text-subtle-foreground" />
        <span className={cn("font-semibold", DECISION_TONE[ai.decision])}>
          {translateOr(`match.analysis.decision.${ai.decision}`, ai.decision)}
        </span>
        {confidence !== null ? (
          <span className="text-subtle-foreground">
            · {t("match.analysis.confidence", { value: fmtPct(confidence, 0) })}
          </span>
        ) : null}
      </p>
      {ai.reason ? (
        <p className="break-words text-xs leading-5 text-muted-foreground">{ai.reason}</p>
      ) : null}
    </div>
  );
}

const PARLAY_BUTTON =
  "inline-flex min-h-10 w-full items-center justify-center gap-1.5 rounded-full border px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:w-auto";

/**
 * "Agregar a mi parlay +" for a priced selection on a non-quarter line before kick-off; "En mi parlay ✓"
 * once it is in (a tap takes it out). One leg per match: another card of this match replaces it.
 */
function ParlayButton({
  card,
  match,
  sides,
  describedBy,
}: {
  card: AnalysisCard;
  match: CardMatch;
  sides: Sides;
  describedBy: string;
}) {
  const state = useParlayLeg(cardLeg(card, match, sides), match.status_group);
  if (!state) return null;
  if (state.block !== null && !state.inSlip) {
    return state.block === "quarter" ? (
      <span className="text-caption text-subtle-foreground">
        {t("records.actions.quarterLine")}
      </span>
    ) : null;
  }
  return (
    <button
      type="button"
      data-testid="add-to-parlay"
      aria-pressed={state.inSlip}
      aria-describedby={describedBy}
      title={
        state.inSlip
          ? t("match.analysis.parlay.remove")
          : state.replaces
            ? t("match.analysis.parlay.replaces")
            : undefined
      }
      onClick={state.toggle}
      className={cn(
        PARLAY_BUTTON,
        state.inSlip
          ? "border-gold/60 bg-gold-soft text-gold-strong hover:bg-gold/20"
          : "border-border-strong bg-card text-foreground hover:bg-elevated",
      )}
    >
      {state.inSlip ? t("match.analysis.parlay.added") : t("match.analysis.parlay.add")}
      {state.inSlip ? (
        <Check aria-hidden className="h-4 w-4 shrink-0" />
      ) : (
        <Plus aria-hidden className="h-4 w-4 shrink-0" />
      )}
    </button>
  );
}

export function AnalysisCardView({
  card,
  home,
  away,
  match,
  updatedAt,
}: {
  card: AnalysisCard;
  home: string;
  away: string;
  /** The card's match: with it, the card can be added to "Mi parlay". */
  match?: CardMatch | undefined;
  /** When the analysis (or its brief) was last written. */
  updatedAt?: string | null | undefined;
}) {
  const id = useId();
  const sides = { home, away };
  const noMarket = card.kind === "no_market";
  // Why the verdict is what it is, when no review says it; the banner says it for an unpriced market.
  const verdictReason = noMarket
    ? ""
    : translateOr(`match.analysis.reason.${card.verdict_reason}`, "");
  return (
    <article
      data-testid="analysis-card"
      data-verdict={card.verdict}
      data-kind={card.kind}
      aria-labelledby={`${id}-title`}
      className={cn(
        "min-w-0 space-y-3 rounded-xl border border-l-[3px] border-border bg-card p-3.5 sm:p-4",
        VERDICT_ACCENT[card.verdict],
      )}
    >
      <header className="flex flex-col-reverse items-start gap-2 sm:flex-row sm:justify-between sm:gap-4">
        <div className="min-w-0 max-w-full sm:flex-1">
          <h3
            id={`${id}-title`}
            className="break-words font-display text-[0.95rem] font-semibold leading-snug sm:text-base"
          >
            {cardTitle(card, sides)}
          </h3>
          {verdictReason ? (
            <p className="mt-0.5 break-words text-xs text-muted-foreground">{verdictReason}</p>
          ) : null}
        </div>
        <span
          className={cn(
            "inline-flex shrink-0 items-center rounded-full border px-2.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-wider",
            VERDICT_STYLE[card.verdict],
          )}
        >
          {translateOr(`match.analysis.verdict.${card.verdict}`, card.verdict)}
        </span>
      </header>

      {noMarket ? (
        <p className="flex items-start gap-2 rounded-lg border border-info/35 bg-info-soft px-3 py-2 text-xs font-semibold text-info">
          <TriangleAlert aria-hidden className="mt-px h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">{t("match.analysis.noMarketBanner")}</span>
        </p>
      ) : null}

      <Figures card={card} />

      <section
        aria-labelledby={`${id}-area`}
        className="rounded-lg border border-border/70 bg-background/40 p-3 sm:p-3.5"
      >
        <h4 id={`${id}-area`} className="text-label text-subtle-foreground">
          {t("match.analysis.area")}
        </h4>
        <div className="mt-2.5 grid gap-4 md:grid-cols-2 md:gap-6">
          <ReasonList
            id={`${id}-why`}
            title={t("match.analysis.why.title")}
            icon={<CircleCheck />}
            tone="text-positive"
            dot="bg-positive/70"
            lines={whyLines(card)}
            testId="analysis-why"
          />
          <ReasonList
            id={`${id}-risk`}
            title={t("match.analysis.risk.title")}
            icon={<ShieldAlert />}
            tone="text-warning"
            dot="bg-warning/70"
            lines={riskLines(card)}
            testId="analysis-risks"
          />
        </div>
        {card.ai ? <ReviewLine ai={card.ai} /> : null}
      </section>

      {updatedAt || match ? (
        <footer className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border/70 pt-3">
          {updatedAt ? (
            <span className="text-caption text-subtle-foreground">
              {t("common.updated", { when: formatRelative(updatedAt) })}
            </span>
          ) : null}
          {match ? (
            <div className="w-full sm:ml-auto sm:w-auto">
              <ParlayButton card={card} match={match} sides={sides} describedBy={`${id}-title`} />
            </div>
          ) : null}
        </footer>
      ) : null}
    </article>
  );
}

// ── the day's reading (L1 brief) ────────────────────────────────────────────

function Chip({ children, tone }: { children: ReactNode; tone?: string | undefined }) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-full border px-2 py-0.5 text-[0.7rem] font-medium",
        tone ?? "border-border-strong bg-elevated text-muted-foreground",
      )}
    >
      <span className="min-w-0 break-words">{children}</span>
    </span>
  );
}

/** "Lectura del día": the economical model's (or the rules') reading of the match. Never a probability. */
function BriefPanel({ brief, sides }: { brief: BriefView; sides: Sides }) {
  const id = useId();
  const reasons: readonly string[] = brief.reasons ?? [];
  const injuries = brief.injuries ?? [];
  const changes = claimTexts(brief.changes);
  const uncertainty = brief.uncertainty
    ? translateOr(`match.analysis.brief.uncertainty.${brief.uncertainty}`, "")
    : "";
  const quality = brief.data_quality
    ? translateOr(`match.analysis.brief.quality.${brief.data_quality}`, "")
    : "";
  return (
    <section
      aria-labelledby={id}
      data-testid="analysis-brief"
      className="min-w-0 space-y-2.5 rounded-xl border border-info/30 bg-info-soft/40 p-3.5 sm:p-4"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h3
          id={id}
          className="flex items-center gap-1.5 font-display text-sm font-semibold text-info"
        >
          <Newspaper aria-hidden className="h-4 w-4 shrink-0" />
          {t("match.analysis.brief.title")}
        </h3>
        {uncertainty || quality ? (
          <div className="flex min-w-0 flex-wrap gap-1.5">
            {uncertainty ? (
              <Chip tone={UNCERTAINTY_TONE[brief.uncertainty ?? ""]}>{uncertainty}</Chip>
            ) : null}
            {quality ? <Chip tone={QUALITY_TONE[brief.data_quality ?? ""]}>{quality}</Chip> : null}
          </div>
        ) : null}
      </div>
      {brief.summary ? (
        <p className="break-words text-sm leading-relaxed text-foreground/90">{brief.summary}</p>
      ) : null}
      {reasons.length ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-caption text-subtle-foreground">
            {t("match.analysis.brief.signals")}
          </span>
          {reasons.map((r, i) => (
            <Chip key={`${r}-${i}`}>{briefReason(r)}</Chip>
          ))}
        </div>
      ) : null}
      {injuries.length || changes.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {injuries.length ? (
            <div className="min-w-0">
              <h4 className="text-caption font-semibold text-muted-foreground">
                {t("match.analysis.brief.injuries")}
              </h4>
              <ul className="mt-1 space-y-0.5 text-xs leading-5" data-testid="analysis-injuries">
                {injuries.map((x, i) => (
                  <li key={i} className="break-words">
                    {injuryLine(x, sides)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {changes.length ? (
            <div className="min-w-0">
              <h4 className="text-caption font-semibold text-muted-foreground">
                {t("match.analysis.brief.changes")}
              </h4>
              <ul className="mt-1 space-y-0.5 text-xs leading-5" data-testid="analysis-changes">
                {changes.map((c, i) => (
                  <li key={i} className="break-words">
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
      <p className="text-caption text-subtle-foreground">{briefAuthor(brief)}</p>
    </section>
  );
}

// ── the block ───────────────────────────────────────────────────────────────

function Footer({ a, updatedAt }: { a: MatchAnalysis; updatedAt: string | null }) {
  return (
    <p
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-subtle-foreground"
      data-testid="analysis-footer"
    >
      <span className="inline-flex items-center gap-1">
        <BrainCircuit aria-hidden className="h-3 w-3" />
        {a.analyzed_by_llm ? t("match.analysis.byAi") : t("match.analysis.byRules")}
      </span>
      {/* Each card says when it was updated; without cards, the footer does. */}
      {updatedAt && a.cards.length === 0 ? (
        <span>· {t("match.analysis.updated", { when: formatRelative(updatedAt) })}</span>
      ) : null}
      {a.mode === "shadow" || !a.enforced ? <span>· {t("match.analysis.shadowNote")}</span> : null}
    </p>
  );
}

/**
 * `variant="reference"` once the match is under way or over (REVIEW PREDIGOL, point 4): PrediGol Intelligence
 * no longer heads the page - the events do - and below them it reads as what it is, the day's reading written
 * before kick-off, with the analysed markets folded away.
 */
export function AnalysisBlock({
  ctx,
  variant = "full",
}: {
  ctx: MatchCtx;
  variant?: "full" | "reference";
}) {
  const preview = usePreviewParam();
  const q = useQuery(live.matchAnalysis(ctx.fixtureId, preview));
  const [showCards, setShowCards] = useState(false);
  const reference = variant === "reference";
  const a = q.data?.data ?? null;
  const evaluation = a?.audience === "evaluation";
  const home = ctx.match.home.name;
  const away = ctx.match.away.name;
  const match: CardMatch = {
    fixture_id: ctx.match.id,
    kickoff_at: ctx.match.kickoff_at,
    status_group: ctx.match.status_group,
  };
  const updatedAt = a ? analysisUpdatedAt(a) : null;
  // Line-ups come about an hour before kick-off and an unpriced market has its own cards: neither is a gap.
  const gaps = (a?.missing ?? []).filter((m) => m !== "lineups" && m !== "market");
  const titleId = `${INTELLIGENCE_ID}-title`;
  // Under the events, nothing to read is no block at all: an empty card there is only noise.
  if (reference && q.isSuccess && (!a || (!a.brief && a.cards.length === 0))) return null;
  const cardsShown = !reference || showCards;
  return (
    <section
      id={INTELLIGENCE_ID}
      aria-labelledby={titleId}
      data-testid="analysis-block"
      data-variant={variant}
      className={cn(
        "min-w-0 scroll-mt-20 rounded-xl border border-border bg-card",
        evaluation && "border-info/40",
      )}
    >
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div className="min-w-0">
          {reference ? (
            <h2
              id={titleId}
              className="flex items-center gap-2 font-display text-[0.95rem] font-semibold tracking-tight"
            >
              <Newspaper aria-hidden className="h-4 w-4 shrink-0 text-info" />
              <span className="min-w-0 break-words">{t("match.reading.title")}</span>
            </h2>
          ) : (
            <h2
              id={titleId}
              className="flex items-center gap-2 font-display text-[0.95rem] font-bold uppercase tracking-[0.08em]"
            >
              <BrainCircuit aria-hidden className="h-4 w-4 shrink-0 text-primary" />
              <span className="min-w-0 break-words">{t("match.analysis.title")}</span>
            </h2>
          )}
          <p className="mt-0.5 text-xs text-muted-foreground">
            {reference ? t("match.reading.subtitle") : t("match.analysis.subtitle")}
          </p>
        </div>
        {evaluation ? <ShadowBadge compact /> : null}
      </header>
      <div className="px-4 pb-4 pt-3">
        {q.isPending ? (
          <SkeletonBlock className="h-40" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-5" />
        ) : !a ? (
          <p className="text-sm text-muted-foreground" data-empty-state>
            {t("match.analysis.notYet")}
          </p>
        ) : (
          <div className="space-y-3">
            {a.brief ? <BriefPanel brief={a.brief} sides={{ home, away }} /> : null}
            {reference && a.cards.length ? (
              <button
                type="button"
                aria-expanded={showCards}
                onClick={() => setShowCards((v) => !v)}
                data-testid="reading-cards-toggle"
                className="inline-flex min-h-9 items-center gap-1 rounded-md px-1 text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {showCards
                  ? t("match.reading.hideCards")
                  : t("match.reading.showCards", { count: a.cards.length })}
              </button>
            ) : null}
            {a.cards.length ? (
              cardsShown ? (
                <div className="space-y-3">
                  {a.cards.map((c) => (
                    <AnalysisCardView
                      key={`${c.market}-${c.selection}-${c.line}`}
                      card={c}
                      home={home}
                      away={away}
                      match={match}
                      updatedAt={updatedAt}
                    />
                  ))}
                </div>
              ) : null
            ) : (
              <p className="text-sm text-muted-foreground" data-empty-state>
                {a.withheld > 0
                  ? t("match.analysis.inEvaluation", { count: a.withheld })
                  : t("match.analysis.none")}
              </p>
            )}
            {a.cards.length > 0 && a.withheld > 0 ? (
              <p className="text-caption text-subtle-foreground">
                {t("match.analysis.withheld", { count: a.withheld })}
              </p>
            ) : null}
            {gaps.length ? (
              <p className="text-caption text-subtle-foreground">
                {t("match.analysis.missing", {
                  blocks: gaps.map((m) => t(`match.analysis.block.${m}`)).join(", "),
                })}
              </p>
            ) : null}
            <Footer a={a} updatedAt={updatedAt} />
          </div>
        )}
      </div>
    </section>
  );
}
