/**
 * POST-MORTEMS (plan F8): the one post-mortem of every selection PrediGol looked at, whoever looked at it (the decision layer, the
 * picks and parlays users saw, the AI's reviews): the verdict on the price and the class of a loss, the price taken against its
 * close (CLV and the move of the same book, which are not the same number), the model against the market and the ten questions.
 * Reading only: the worker wrote every row once.
 */
import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { t, translateOr } from "@/lib/i18n";
import { fmtOdds } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { PickPostmortem } from "@/lib/api/v1/types_ai_layer";
import { Choice, DayInput, Note, SubTitle, Toolbar } from "./AiBits";
import {
  LOSS_CLASSES,
  POSTMORTEM_VERDICTS,
  answerView,
  bogotaDateTime,
  classTone,
  decisionLabel,
  decisionTone,
  lossClassLabel,
  orderedAnswers,
  probText,
  questionLabel,
  selectionText,
  signedText,
  toNum,
  verdictLabel,
  verdictTone,
} from "./aiModel";
import { summarize } from "./memoryText";
import { Fact } from "./shared";

export function PostmortemCard({ pm }: { pm: PickPostmortem }) {
  const answers = orderedAnswers(pm.answers);
  const clv = toNum(pm.clv);
  const move = toNum(pm.price_move);
  return (
    <li
      className="min-w-0 space-y-2.5 rounded-md border border-border bg-card p-3"
      data-testid="ai-postmortem"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium wrap-anywhere">{pm.match}</p>
          <p className="text-caption text-subtle-foreground wrap-anywhere">
            {pm.competition ?? "—"} · {bogotaDateTime(pm.kickoff_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <StatusBadge tone={verdictTone(pm.verdict)}>{verdictLabel(pm.verdict)}</StatusBadge>
          {pm.classification ? (
            <StatusBadge tone={classTone(pm.classification)}>
              {lossClassLabel(pm.classification)}
            </StatusBadge>
          ) : null}
        </div>
      </div>
      <p className="text-xs font-medium wrap-anywhere">
        {selectionText(pm.market_key, pm.selection, pm.line, pm.match)}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-caption uppercase tracking-wider text-subtle-foreground">
          {t("ai.research.postmortems.decision")}
        </span>
        <StatusBadge tone={decisionTone(pm.decision)}>
          {pm.decision ? decisionLabel(pm.decision) : t("ai.research.postmortems.noDecision")}
        </StatusBadge>
        {pm.roles.map((r) => (
          <StatusBadge key={r} dot={false}>
            {translateOr(`ai.v2.role.${r}`, r)}
          </StatusBadge>
        ))}
      </div>
      <dl className="grid max-w-3xl grid-cols-3 gap-x-3 sm:grid-cols-6">
        <Fact label={t("ai.research.postmortems.odds")} value={fmtOdds(pm.odds)} />
        <Fact label={t("ai.research.postmortems.close")} value={fmtOdds(pm.close_odds)} />
        <Fact
          label={t("ai.research.postmortems.priceMove")}
          value={
            <span
              className={cn(
                move !== null && move > 0 && "text-positive",
                move !== null && move < 0 && "text-negative",
              )}
            >
              {signedText(pm.price_move)}
            </span>
          }
        />
        <Fact
          label={t("ai.research.postmortems.clv")}
          value={
            <span
              className={cn(
                clv !== null && clv > 0 && "text-positive",
                clv !== null && clv < 0 && "text-negative",
              )}
            >
              {signedText(pm.clv)}
            </span>
          }
        />
        <Fact label={t("ai.research.postmortems.model")} value={probText(pm.p_model)} />
        <Fact label={t("ai.research.postmortems.market")} value={probText(pm.p_market)} />
      </dl>
      <p className="max-w-3xl text-caption text-subtle-foreground">
        {t("ai.research.postmortems.priceNote")}
      </p>
      {answers.length ? (
        <details className="group max-w-4xl rounded-md border border-border">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-md px-3 py-2 text-xs font-medium hover:bg-elevated/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            {t("ai.research.postmortems.questions")}
            <ChevronDown
              aria-hidden
              className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
            />
          </summary>
          <ol className="divide-y divide-border/60 border-t border-border">
            {answers.map(([question, a]) => {
              const v = answerView(question, String(a.answer ?? ""));
              return (
                <li key={question} className="space-y-1 px-3 py-2" data-question={question}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-medium">{questionLabel(question)}</span>
                    {v.chip ? <StatusBadge tone={v.tone}>{v.label}</StatusBadge> : null}
                  </div>
                  {!v.chip && v.label ? <p className="text-xs wrap-anywhere">{v.label}</p> : null}
                  {a.detail ? (
                    <p className="text-caption text-muted-foreground wrap-anywhere">{a.detail}</p>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </details>
      ) : null}
      {pm.narrative ? (
        <div className="max-w-4xl space-y-1 rounded-md border border-border bg-elevated/40 p-2.5">
          <SubTitle>{t("ai.research.postmortems.narrative")}</SubTitle>
          <p className="whitespace-pre-line text-xs leading-relaxed text-muted-foreground wrap-anywhere">
            {pm.narrative}
          </p>
        </div>
      ) : null}
    </li>
  );
}

function Summary({ rows }: { rows: PickPostmortem[] }) {
  const { verdicts, classes } = summarize(rows);
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="postmortem-summary">
      <span className="text-caption uppercase tracking-wider text-subtle-foreground">
        {t("ai.research.postmortems.verdict")}
      </span>
      {verdicts.map(([v, n]) => (
        <StatusBadge key={v} tone={verdictTone(v)}>
          {verdictLabel(v)} {n}
        </StatusBadge>
      ))}
      {classes.length ? (
        <span className="ml-2 text-caption uppercase tracking-wider text-subtle-foreground">
          {t("ai.research.postmortems.class")}
        </span>
      ) : null}
      {classes.map(([c, n]) => (
        <StatusBadge key={c} tone={classTone(c)}>
          {lossClassLabel(c)} {n}
        </StatusBadge>
      ))}
    </div>
  );
}

export function PostmortemsPanel({
  day,
  onDay,
  max,
}: {
  day: string;
  onDay: (d: string) => void;
  max: string;
}) {
  const [verdict, setVerdict] = useState("");
  const [cls, setCls] = useState("");
  const q = useLiveQuery(
    live.aiPostmortems({
      day,
      verdict: verdict || undefined,
      classification: cls || undefined,
    }),
  );
  const rows = q.data?.data ?? [];
  return (
    <div className="space-y-3" data-testid="memory-postmortems">
      <Toolbar>
        <DayInput value={day} onChange={onDay} label={t("ai.research.day")} max={max} />
        <Choice label={t("ai.research.postmortems.verdict")} value={verdict} onChange={setVerdict}>
          <option value="">{t("ai.research.postmortems.all")}</option>
          {POSTMORTEM_VERDICTS.map((v) => (
            <option key={v} value={v}>
              {verdictLabel(v)}
            </option>
          ))}
        </Choice>
        <Choice label={t("ai.research.postmortems.class")} value={cls} onChange={setCls}>
          <option value="">{t("ai.research.postmortems.all")}</option>
          {LOSS_CLASSES.map((c) => (
            <option key={c} value={c}>
              {lossClassLabel(c)}
            </option>
          ))}
        </Choice>
      </Toolbar>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={4} cols={4} /> : null}
      {q.isSuccess && rows.length === 0 ? (
        <Note>
          {verdict || cls
            ? t("ai.research.postmortems.emptyFiltered")
            : t("ai.research.postmortems.empty")}
        </Note>
      ) : null}
      {rows.length ? <Summary rows={rows} /> : null}
      {rows.length ? (
        <ul className="space-y-2" data-testid="ai-postmortems">
          {rows.map((pm) => (
            <PostmortemCard key={pm.id} pm={pm} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}
