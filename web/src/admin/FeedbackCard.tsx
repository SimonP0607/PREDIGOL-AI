/**
 * What readers think of PrediGol, for the owner (plan UX, B6 and section 40): the monthly survey with its n - the mean,
 * the share of 4 and 5 (the CSAT), each score's count, the low answers and the closes -, «¿Te sirvió?» per kind of thing
 * read, the newest comments with their score and date (never who wrote them) and how many readers the survey puts EN
 * RIESGO (2 or less in the last 30 days: support looks after them, B11). With few answers it says so: a CSAT of nine
 * answers is not a trend. NPS waits for more than about 100 answers a quarter (section 40).
 *
 * The opinion improves the product and never enters the models.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, MessageSquareHeart } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { FeedbackOverview } from "@/lib/api/v1/types_feedback";
import { t } from "@/lib/i18n";
import { fmtInt, localFixed, localPct } from "@/lib/i18n/format";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/product/shared/States";
import { PERIODS, SMALL_SAMPLE, csat } from "./feedbackFigures";

function Figure({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="rounded-md border border-border p-3" data-testid={testId}>
      <p className="text-caption text-muted-foreground">{label}</p>
      <p className="numeric font-display text-xl font-semibold">{value}</p>
    </div>
  );
}

export function FeedbackView({ o }: { o: FeedbackOverview }) {
  const n = o.survey.n;
  const share = csat(o);
  return (
    <div className="space-y-5" data-testid="feedback-overview">
      <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="feedback-state">
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 font-semibold",
            o.enabled
              ? "border-positive/40 bg-positive-soft text-positive"
              : "border-warning/40 bg-warning-soft text-warning",
          )}
        >
          {t(o.enabled ? "admin.product.feedback.on" : "admin.product.feedback.off")}
        </span>
        <span className="text-muted-foreground">
          {t("admin.product.feedback.since", { date: formatDateTime(o.since) })}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Figure label={t("admin.product.feedback.n")} value={fmtInt(n)} testId="feedback-n" />
        <Figure
          label={t("admin.product.feedback.mean")}
          value={o.survey.mean === null ? "—" : localFixed(o.survey.mean, 1)}
          testId="feedback-mean"
        />
        <Figure
          label={t("admin.product.feedback.csat")}
          value={share === null ? "—" : localPct(share, 0)}
          testId="feedback-csat"
        />
        <Figure label={t("admin.product.feedback.low")} value={fmtInt(o.survey.low)} />
        <Figure label={t("admin.product.feedback.skipped")} value={fmtInt(o.survey.skipped)} />
        <Figure
          label={t("admin.product.feedback.atRisk")}
          value={fmtInt(o.at_risk)}
          testId="feedback-at-risk"
        />
      </div>
      {n === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="feedback-empty">
          {t("admin.product.feedback.empty")}
        </p>
      ) : n < SMALL_SAMPLE ? (
        <p className="text-caption text-warning" data-testid="feedback-small">
          {t("admin.product.feedback.small", { n: fmtInt(n), min: SMALL_SAMPLE })}
        </p>
      ) : null}

      {n > 0 ? (
        <section aria-labelledby="feedback-scores" className="space-y-2">
          <h3 id="feedback-scores" className="text-sm font-semibold">
            {t("admin.product.feedback.scores")}
          </h3>
          <ul className="space-y-1.5" data-testid="feedback-scores">
            {(["5", "4", "3", "2", "1"] as const).map((score) => {
              const count = o.survey.scores[score] ?? 0;
              return (
                <li key={score} className="flex items-center gap-2 text-sm" data-score={score}>
                  <span className="numeric w-4 shrink-0 text-right font-semibold">{score}</span>
                  <span
                    aria-hidden
                    className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-muted"
                  >
                    <span
                      className="block h-full rounded-full bg-primary"
                      style={{ width: `${(count / n) * 100}%` }}
                    />
                  </span>
                  <span className="numeric w-24 shrink-0 text-right text-muted-foreground">
                    {fmtInt(count)} · {localPct(count / n, 0)}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="feedback-votes" className="space-y-2">
        <h3 id="feedback-votes" className="text-sm font-semibold">
          {t("admin.product.feedback.votes")}
        </h3>
        {o.votes.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("admin.product.feedback.noVotes")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="feedback-votes">
              <thead>
                <tr className="text-left text-caption text-muted-foreground">
                  <th className="py-1.5 pr-3 font-medium">
                    {t("admin.product.feedback.subjectCol")}
                  </th>
                  <th className="py-1.5 pr-3 text-right font-medium">
                    {t("admin.product.feedback.yes")}
                  </th>
                  <th className="py-1.5 pr-3 text-right font-medium">
                    {t("admin.product.feedback.no")}
                  </th>
                  <th className="py-1.5 text-right font-medium">
                    {t("admin.product.feedback.yesShare")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {o.votes.map((v) => (
                  <tr key={v.subject} className="border-t border-border" data-subject={v.subject}>
                    <td className="py-1.5 pr-3">
                      {t(`admin.product.feedback.subject.${v.subject}`)}
                    </td>
                    <td className="numeric py-1.5 pr-3 text-right">{fmtInt(v.yes)}</td>
                    <td className="numeric py-1.5 pr-3 text-right">{fmtInt(v.no)}</td>
                    <td className="numeric py-1.5 text-right">
                      {v.yes + v.no > 0 ? localPct(v.yes / (v.yes + v.no), 0) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="feedback-comments" className="space-y-2">
        <h3 id="feedback-comments" className="text-sm font-semibold">
          {t("admin.product.feedback.comments")}
        </h3>
        {o.comments.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("admin.product.feedback.noComments")}</p>
        ) : (
          <ul className="space-y-2" data-testid="feedback-comments">
            {o.comments.map((c, i) => (
              <li
                key={`${c.at}-${i}`}
                className="rounded-md border border-border p-3"
                data-testid="feedback-comment"
              >
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground">
                  <span className="numeric rounded-full border border-border-strong px-1.5 font-semibold text-foreground">
                    {c.score}
                  </span>
                  <span>{formatDateTime(c.at)}</span>
                  {c.trigger ? (
                    <span>· {t(`admin.product.feedback.trigger.${c.trigger}`)}</span>
                  ) : null}
                </p>
                <p className="mt-1 whitespace-pre-line break-words text-sm">{c.comment}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
      <p className="text-caption text-subtle-foreground">{t("admin.product.feedback.nps")}</p>
    </div>
  );
}

/** The card of /admin/product: the period (30, 90 or 365 days) and the figures. */
export function FeedbackCard() {
  const [days, setDays] = useState<(typeof PERIODS)[number]>(90);
  const q = useQuery({
    queryKey: ["admin", "product", "feedback", days],
    queryFn: () => v1.feedbackOverview(days),
  });
  return (
    <section
      aria-labelledby="feedback-title"
      className="space-y-4 rounded-xl border border-border bg-card p-4"
      data-testid="feedback-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2
          id="feedback-title"
          className="flex items-center gap-2 font-display text-base font-semibold"
        >
          <MessageSquareHeart aria-hidden className="h-4 w-4 text-primary" />
          {t("admin.product.feedback.title")}
        </h2>
        <div role="group" aria-label={t("admin.product.feedback.period")} className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={days === p}
              onClick={() => setDays(p)}
              data-testid={`feedback-days-${p}`}
              className={cn(
                "tap relative rounded-md border px-2.5 py-1 text-xs font-semibold",
                days === p
                  ? "border-primary bg-primary/15 text-foreground"
                  : "border-border-strong text-muted-foreground hover:bg-elevated",
              )}
            >
              {t("admin.product.feedback.days", { n: p })}
            </button>
          ))}
        </div>
      </div>
      {q.isPending ? (
        <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <FeedbackView o={q.data} />
      )}
    </section>
  );
}
