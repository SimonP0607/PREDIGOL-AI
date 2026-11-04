/**
 * «¿Te sirvió?» (plan UX, B6; section 40): yes or no at the end of a reading, a narrative or a pick's explanation - and of
 * an «Explícame» answer once B9 brings it - without interrupting: one line after the text. One answer per reader and
 * thing read; the last one counts and the reader can change it. With «No», the way to tell PrediGol what was missing (a
 * suggestion, A14). Nothing for the owner, for a reader with consents owed, or while FBI_FEEDBACK keeps it off.
 *
 * HelpfulVoteView draws it from what it is given (a test renders it without a session); HelpfulVote reads and saves the
 * reader's answer.
 */
import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type {
  FeedbackSubject,
  HelpfulVote as Vote,
  SurveyState,
} from "@/lib/api/v1/types_feedback";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import { useReportProblem } from "@/product/support/report";
import { useFeedbackReader } from "./moments";

/** What the question names: an analysis (the reading or its narrative), an explanation, an answer. */
const NAMED: Record<FeedbackSubject, "analysis" | "explanation" | "answer"> = {
  reading: "analysis",
  narrative: "analysis",
  explanation: "explanation",
  explain: "answer",
};

export function HelpfulVoteView({
  subject,
  value,
  pending = false,
  failed = false,
  onVote,
  onTellUs,
  className,
}: {
  subject: FeedbackSubject;
  /** The reader's answer; null: none yet. */
  value: boolean | null;
  pending?: boolean;
  failed?: boolean;
  onVote: (helpful: boolean) => void;
  /** After a «No»: open a suggestion (only while messages to PrediGol are on). */
  onTellUs?: (() => void) | undefined;
  className?: string | undefined;
}) {
  const labelId = useId();
  const choice = (helpful: boolean) => {
    const Icon = helpful ? ThumbsUp : ThumbsDown;
    const on = value === helpful;
    return (
      <button
        type="button"
        aria-pressed={on}
        disabled={pending}
        onClick={() => onVote(helpful)}
        data-testid={helpful ? "helpful-yes" : "helpful-no"}
        className={cn(
          "tap-y relative inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
          on
            ? "border-primary bg-primary/15 text-foreground"
            : "border-border-strong text-muted-foreground hover:bg-elevated",
        )}
      >
        <Icon aria-hidden className="h-4 w-4 shrink-0" />
        {t(helpful ? "support.feedback.helpful.yes" : "support.feedback.helpful.no")}
      </button>
    );
  };
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border pt-3",
        className,
      )}
      data-testid="helpful-vote"
      data-subject={subject}
      data-vote={value === null ? "none" : value ? "yes" : "no"}
    >
      <p id={labelId} className="text-sm text-muted-foreground">
        {t(`support.feedback.helpful.question.${NAMED[subject]}`)}
      </p>
      <div role="group" aria-labelledby={labelId} className="flex gap-2">
        {choice(true)}
        {choice(false)}
      </div>
      <p
        aria-live="polite"
        className="basis-full text-caption text-muted-foreground"
        data-testid="helpful-note"
      >
        {failed ? (
          <span className="text-negative">{t("support.feedback.helpful.failed")}</span>
        ) : value === true ? (
          t("support.feedback.helpful.thanks")
        ) : value === false ? (
          <>
            {t("support.feedback.helpful.thanksNo")}{" "}
            {onTellUs ? (
              <button
                type="button"
                onClick={onTellUs}
                data-testid="helpful-tell-us"
                className="tap-y relative font-semibold text-primary underline-offset-2 hover:underline"
              >
                {t("support.feedback.helpful.tellUs")}
              </button>
            ) : null}
          </>
        ) : null}
      </p>
    </div>
  );
}

/** «¿Te sirvió?» on one thing read: ``subjectId`` is the match of a reading or a narrative, the pick of an explanation. */
export function HelpfulVote({
  subject,
  subjectId,
  className,
}: {
  subject: FeedbackSubject;
  subjectId: number;
  className?: string | undefined;
}) {
  const reader = useFeedbackReader();
  const qc = useQueryClient();
  const report = useReportProblem();
  const route = useRouterState({ select: (s) => s.location.pathname });
  const survey = useQuery({ ...live.survey, enabled: reader });
  const on = reader && survey.data?.enabled === true && subjectId > 0;
  const mine = useQuery({ ...live.helpfulVote(subject, subjectId), enabled: on });
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  if (!on || !mine.data) return null;
  const key = live.helpfulVote(subject, subjectId).queryKey;
  const current = mine.data.helpful;
  const vote = async (helpful: boolean) => {
    if (pending || helpful === current) return;
    setPending(true);
    setFailed(false);
    qc.setQueryData<Vote>(key, { subject, subject_id: subjectId, helpful });
    try {
      const saved = await v1.voteHelpful({
        subject,
        subject_id: subjectId,
        helpful,
        context: { route },
      });
      qc.setQueryData<Vote>(key, saved);
      track("analysis_helpful_voted", { helpful });
    } catch (e) {
      qc.setQueryData<Vote>(key, { subject, subject_id: subjectId, helpful: current });
      if (e instanceof LiveApiError && e.code === "feedback_off") {
        // turned off meanwhile: the question goes
        qc.setQueryData<SurveyState>(live.survey.queryKey, (s) =>
          s ? { ...s, enabled: false } : s,
        );
      } else {
        setFailed(true);
      }
    } finally {
      setPending(false);
    }
  };
  return (
    <HelpfulVoteView
      subject={subject}
      value={current}
      pending={pending}
      failed={failed}
      onVote={(helpful) => void vote(helpful)}
      onTellUs={report.available ? () => report.open({ category: "suggestion" }) : undefined}
      className={className}
    />
  );
}
