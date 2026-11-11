/**
 * The monthly survey (plan UX, B6; section 40): «¿Qué tan útil te resultó PrediGol este mes?» from 1 to 5, then the
 * optional «¿Qué faltó?» (1-3) or «¿Qué fue lo más útil?» (4-5), in one card at the foot of the page - over nothing the
 * reader needs, like the tour's: above the tab bar and the parlay button on a phone, bottom left at a desk. «Ahora no» or
 * the cross closes it with one tap, and then it does not come back for 30 days. Never a prize, never a nag.
 *
 * The scale is five radio buttons, each spanning its 44 px option (the report sheet's pattern): the arrow keys move along
 * it, the tab key goes on to the comment and «Enviar»; Escape closes it. It does not take the focus when it appears - the
 * reader was reading - and it is not modal.
 *
 * CsatPromptView draws it from what it is given (a test renders it without a session); CsatPrompt sends the answer.
 */
import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Loader2, MessageSquareHeart, X } from "lucide-react";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { FeedbackTrigger, SurveyState } from "@/lib/api/v1/types_feedback";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import { COMMENT_MAX, SCORES, commentQuestion } from "./survey";
import { fieldVariants } from "@/components/ui/field";

export type CsatPhase = "ask" | "sending" | "failed" | "thanks";

/** The card's frame: the tour card's place, so the two never cover the bar or the parlay button. */
const FRAME =
  "fixed inset-x-3 bottom-[calc(8.5rem+env(safe-area-inset-bottom))] z-40 mx-auto max-h-[calc(100dvh-10rem)] max-w-md overflow-y-auto rounded-xl border border-gold/40 bg-card p-4 shadow-lg short:bottom-[calc(7rem+env(safe-area-inset-bottom))] lg:bottom-6 lg:left-6 lg:right-auto lg:mx-0 lg:w-[26rem]";

export function CsatPromptView({
  phase,
  score,
  comment,
  onScore,
  onComment,
  onSend,
  onSkip,
  onClose,
}: {
  phase: CsatPhase;
  score: number | null;
  comment: string;
  onScore: (score: number) => void;
  onComment: (comment: string) => void;
  onSend: () => void;
  /** «Ahora no», the cross or Escape before an answer: not again for 30 days. */
  onSkip: () => void;
  /** After the thanks. */
  onClose: () => void;
}) {
  const titleId = useId();
  const commentId = useId();
  const hintId = useId();
  const countId = useId();
  if (phase === "thanks") {
    return (
      <div
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        data-testid="csat-prompt"
        data-phase="thanks"
        className={FRAME}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <div className="flex items-start gap-3">
          <MessageSquareHeart aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-gold" />
          <div className="min-w-0 flex-1" aria-live="polite">
            <h2 id={titleId} className="font-display text-base font-semibold">
              {t("support.feedback.survey.thanks")}
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-foreground/90">
              {t("support.feedback.survey.thanksBody")}
            </p>
          </div>
          <button
            type="button"
            aria-label={t("common.close")}
            onClick={onClose}
            data-testid="csat-done"
            className="tap relative -mr-1 -mt-1 rounded-md p-1.5 text-muted-foreground hover:bg-elevated"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-3 flex justify-end">
          <Link
            to="/updates"
            onClick={onClose}
            data-testid="csat-updates"
            className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-4 text-sm font-semibold hover:bg-elevated"
          >
            {t("support.feedback.survey.seeUpdates")}
          </Link>
        </div>
      </div>
    );
  }
  const sending = phase === "sending";
  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      data-testid="csat-prompt"
      data-phase={phase}
      className={FRAME}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !sending) onSkip();
      }}
    >
      <div className="flex items-start gap-3">
        <MessageSquareHeart aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-gold" />
        <h2
          id={titleId}
          className="min-w-0 flex-1 font-display text-base font-semibold leading-snug"
        >
          {t("support.feedback.survey.question")}
        </h2>
        <button
          type="button"
          aria-label={t("support.feedback.survey.close")}
          onClick={onSkip}
          disabled={sending}
          data-testid="csat-close"
          className="tap relative -mr-1 -mt-1 rounded-md p-1.5 text-muted-foreground hover:bg-elevated"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <form
        className="mt-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (score !== null && !sending) onSend();
        }}
      >
        <fieldset disabled={sending}>
          <legend className="sr-only">{t("support.feedback.survey.question")}</legend>
          <div className="grid grid-cols-5 gap-1.5" data-testid="csat-scale">
            {SCORES.map((n) => (
              <label
                key={n}
                data-testid={`csat-score-${n}`}
                data-checked={score === n ? "true" : undefined}
                className={cn(
                  "relative flex min-h-11 cursor-pointer items-center justify-center rounded-md border text-base font-semibold numeric transition-colors focus-within:ring-2 focus-within:ring-ring",
                  score === n
                    ? "border-primary bg-primary/15 text-foreground"
                    : "border-border-strong text-muted-foreground hover:bg-elevated",
                )}
              >
                <input
                  type="radio"
                  name="csat-score"
                  value={n}
                  checked={score === n}
                  onChange={() => onScore(n)}
                  className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                />
                <span aria-hidden>{n}</span>
                <span className="sr-only">
                  {t("support.feedback.survey.scaleItem", {
                    n,
                    label: t(`support.feedback.survey.scale.${n}`),
                  })}
                </span>
              </label>
            ))}
          </div>
          <div
            aria-hidden
            className="mt-1 flex justify-between gap-2 text-caption text-muted-foreground"
          >
            <span>{t("support.feedback.survey.scale.1")}</span>
            <span>{t("support.feedback.survey.scale.5")}</span>
          </div>
          {score !== null ? (
            <div className="mt-3 flex flex-col gap-1.5" data-testid="csat-comment-block">
              <label htmlFor={commentId} className="text-sm font-semibold">
                {t(`support.feedback.survey.comment.${commentQuestion(score)}`)}{" "}
                <span className="font-normal text-muted-foreground">
                  {t("support.feedback.survey.optional")}
                </span>
              </label>
              <textarea
                id={commentId}
                rows={3}
                maxLength={COMMENT_MAX}
                value={comment}
                onChange={(e) => onComment(e.target.value)}
                aria-describedby={`${hintId} ${countId}`}
                data-testid="csat-comment"
                className={fieldVariants({ size: "area" })}
              />
              <div className="flex items-start justify-between gap-3 text-caption text-subtle-foreground">
                <p id={hintId}>{t("support.feedback.survey.noPersonal")}</p>
                <p id={countId} className="numeric shrink-0">
                  {t("support.report.counter", { count: comment.length, max: COMMENT_MAX })}
                </p>
              </div>
            </div>
          ) : null}
        </fieldset>
        {phase === "failed" ? (
          <p role="alert" className="mt-2 text-sm text-negative" data-testid="csat-error">
            {t("support.feedback.survey.failed")}
          </p>
        ) : null}
        <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={onSkip}
            disabled={sending}
            data-testid="csat-skip"
            className="inline-flex min-h-11 items-center rounded-md px-3 text-sm font-medium text-muted-foreground hover:bg-elevated"
          >
            {t("support.feedback.survey.notNow")}
          </button>
          <button
            type="submit"
            disabled={score === null || sending}
            data-testid="csat-send"
            className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {sending ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
            {t("support.feedback.survey.send")}
          </button>
        </div>
        <p className="mt-2 text-caption text-subtle-foreground">
          {t("support.feedback.survey.note")}
        </p>
      </form>
    </div>
  );
}

/** The survey, answered or closed against the API. ``onDone`` takes it off the screen. */
export function CsatPrompt({
  trigger,
  route,
  onEngage,
  onDone,
}: {
  trigger: FeedbackTrigger;
  /** The page of the useful moment (its path only). */
  route: string;
  /** The reader chose a score: the card stays until they send or close it. */
  onEngage?: (() => void) | undefined;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [phase, setPhase] = useState<CsatPhase>("ask");
  const [score, setScore] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const context = { trigger, route };
  // whatever the answer, the survey is not owed any more: the state is read again next time it is asked
  const settled = () => {
    qc.setQueryData<SurveyState>(live.survey.queryKey, (s) => (s ? { ...s, due: false } : s));
    void qc.invalidateQueries({ queryKey: live.survey.queryKey, refetchType: "none" });
  };
  const send = async () => {
    if (score === null) return;
    setPhase("sending");
    try {
      const text = comment.trim();
      await v1.answerSurvey({ score, comment: text ? text : null, context });
      track("feedback_submitted", { score });
      settled();
      setPhase("thanks");
    } catch (e) {
      // answered from another tab or turned off meanwhile: nothing left to ask
      if (e instanceof LiveApiError && (e.code === "survey_not_due" || e.code === "feedback_off")) {
        settled();
        onDone();
        return;
      }
      setPhase("failed");
    }
  };
  const skip = () => {
    settled();
    onDone();
    void v1.skipSurvey(context).catch(() => undefined);
  };
  return (
    <CsatPromptView
      phase={phase}
      score={score}
      comment={comment}
      onScore={(n) => {
        setScore(n);
        onEngage?.();
        if (phase === "failed") setPhase("ask");
      }}
      onComment={setComment}
      onSend={() => void send()}
      onSkip={skip}
      onClose={onDone}
    />
  );
}
