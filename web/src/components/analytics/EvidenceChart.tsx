/**
 * The card every NEW chart lives in (plan PM, PM-10-06, OP-16; FE-004): the advanced statistics' `ChartCard` (plan EA, EA-101) plus
 * the three things a chart may not go without - its evidence level E0-E4 as a tag, its reading sentence (visible, and the chart's
 * description for a screen reader) and its accessibility review of the 14 critical checks. `evidence`, `reading` and `review` are
 * required props, so a chart without them does not compile; `chartGuard.test.ts` makes every new chart file use this card.
 *
 * Nothing new to look at: the tag is the system's `StatusBadge`, the sentence is the card's caption type. The level shown is capped
 * by the sample (`cappedLevel`): under the minimum a chart is an anecdote (E0) whatever it claims.
 */
import { useId, type ReactNode } from "react";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { ChartCard } from "./stats/ChartCard";
import {
  cappedLevel,
  levelTag,
  levelText,
  readingSentence,
  reviewProblems,
  type ChartReview,
  type EvidenceLevel,
  type Reading,
} from "./evidence";
import { t } from "./evidenceText";

const TONE: Record<EvidenceLevel, BadgeTone> = {
  E0: "neutral",
  E1: "info",
  E2: "info",
  E3: "brand",
  E4: "positive",
};

export function EvidenceBadge({ level }: { level: EvidenceLevel }) {
  return (
    <StatusBadge tone={TONE[level]} dot={false}>
      <span aria-hidden>{levelTag(level)}</span>
      <span className="sr-only">
        {t("evidence.badgeLabel", { tag: levelTag(level), text: levelText(level) })}
      </span>
    </StatusBadge>
  );
}

export function EvidenceChart({
  title,
  subtitle,
  evidence,
  reading,
  review,
  method,
  actions,
  footer,
  children,
  className,
  testId,
}: {
  title: string;
  subtitle?: string | undefined;
  /** The level the piece earned in its protocol (DOC-007 §5.3); C-13 may carry it as `evidence_level`. */
  evidence: EvidenceLevel;
  /** The figures the sentence says, as the contract gives them. */
  reading: Reading;
  /** The hand review of the 14 checks; an incomplete one fails the piece's test (`reviewProblems`). */
  review: ChartReview;
  method?: string | undefined;
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string | undefined;
  testId?: string | undefined;
}) {
  const id = useId();
  const level = cappedLevel(evidence, reading);
  const sentence = readingSentence(reading);
  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      method={method}
      footer={footer}
      className={className}
      testId={testId}
      actions={
        <>
          <EvidenceBadge level={level} />
          {actions}
        </>
      }
    >
      <div
        data-evidence={level}
        data-review={reviewProblems(review).length === 0 ? "completa" : "incompleta"}
        className="space-y-3"
      >
        <p id={id} className="text-small text-foreground-soft">
          {sentence}
        </p>
        <figure aria-describedby={id} className="m-0">
          {children}
        </figure>
      </div>
    </ChartCard>
  );
}
