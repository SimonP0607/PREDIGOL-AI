/**
 * «Explícame» (plan UX, B9; section 26): a button on a match, a pick and the parlay being built, and a sheet with its frequent
 * questions. Tapping one asks the API (nothing is asked before) and shows the answer in the reader's words: sentences written from
 * what PrediGol already keeps - no AI, nothing made up. When PrediGol lacks the data the question needs, the sheet says «No tengo
 * ese dato» and what is missing, never a guess. Each answer ends with the words worth a tap (the glossary), the places to read
 * more, «¿Te sirvió?» and «Otra pregunta», the way to tell PrediGol what was missing (a suggestion, A14).
 *
 * Opening an answer records `explain_opened` with the question (a slug, never text); on a phone or a narrow screen the sheet
 * comes up from the bottom, at a desk from the side (the «¿Por qué este pick?» sheet's rule).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, CircleHelp, MessageSquarePlus } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type {
  ExplainEntity,
  ExplainIntent,
  Explanation,
  SlipLegBody,
} from "@/lib/api/v1/types_explain";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import { GLOSSARY_PATH, isTerm } from "@/lib/glossary";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Disclaimer } from "@/components/system/Disclaimer";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { HelpfulVote } from "@/product/feedback/HelpfulVote";
import { WhyPickButton } from "@/product/picks/WhyPick";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import { useReportProblem } from "@/product/support/report";
import { useTransparencyOpen } from "@/product/transparency/useTransparencyOpen";
import { QUESTIONS, answerLines, questionText, trackWhat, voteSubjectId } from "./text";

/** A finger, or a screen too narrow for a side panel: the sheet comes up from the bottom. */
const SHEET_QUERY = "(pointer: coarse), (max-width: 639px)";

function fromBottom(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(SHEET_QUERY).matches;
}

/** Whether this account is offered «Explícame» (the owner's FBI_EXPLAIN switch; the API answers 404 while it is off). */
function useExplainOn(): boolean {
  return useAuth().user?.explain === true;
}

export interface ExplainTarget {
  entity: ExplainEntity;
  /** The match or the pick; null for the parlay being built. */
  itemId: number | null;
  /** The parlay's legs (entity "parlay" only). */
  legs?: SlipLegBody[] | undefined;
}

export function ExplainButton({
  entity,
  itemId,
  legs,
  testId = "explain",
  className,
}: ExplainTarget & { testId?: string; className?: string | undefined }) {
  const on = useExplainOn();
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState<"bottom" | "right">("bottom");
  if (!on) return null;
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          type="button"
          data-testid={testId}
          aria-label={t("explain.buttonLabel", { what: t(`explain.about.${entity}`) })}
          onClick={() => setSide(fromBottom() ? "bottom" : "right")}
          className={cn(
            "tap-y relative inline-flex min-h-9 items-center gap-1.5 rounded-full border border-border-strong px-3 text-xs font-semibold text-foreground transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <CircleHelp aria-hidden className="h-3.5 w-3.5 shrink-0" />
          {t("explain.button")}
        </button>
      </SheetTrigger>
      <SheetContent
        side={side}
        closeLabel={t("common.close")}
        data-testid="explain-sheet"
        className={cn(
          "overflow-y-auto",
          side === "bottom"
            ? "max-h-[92dvh] px-4 pb-[calc(1.25rem+env(safe-area-inset-bottom))] pt-5"
            : "w-full px-5 py-5 sm:max-w-md",
        )}
      >
        {open ? (
          <ExplainContent
            entity={entity}
            itemId={itemId}
            legs={legs}
            onClose={() => setOpen(false)}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function ExplainContent({
  entity,
  itemId,
  legs,
  onClose,
}: ExplainTarget & { onClose: () => void }) {
  const [intent, setIntent] = useState<ExplainIntent | null>(null);
  const report = useReportProblem();
  return (
    <div className="space-y-4">
      <SheetHeader className="space-y-1 pr-8 text-left">
        <SheetTitle className="font-display text-lg leading-snug">{t("explain.title")}</SheetTitle>
        <SheetDescription className="text-sm text-muted-foreground">
          {t("explain.description")}
        </SheetDescription>
      </SheetHeader>
      {intent === null ? (
        <div className="space-y-3">
          <p className="text-sm font-medium">{t("explain.choose")}</p>
          <ul className="space-y-2" data-testid="explain-questions">
            {QUESTIONS[entity].map((q) => (
              <li key={q}>
                <button
                  type="button"
                  data-testid={`explain-q-${q}`}
                  onClick={() => setIntent(q)}
                  className="tap-y flex min-h-11 w-full items-center rounded-lg border border-border px-3 text-left text-sm font-medium hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {questionText(entity, q)}
                </button>
              </li>
            ))}
          </ul>
          {report.available ? (
            <OtherQuestion
              onOpen={() => {
                onClose();
                report.open({ category: "suggestion" });
              }}
            />
          ) : null}
        </div>
      ) : (
        <Answer
          entity={entity}
          itemId={itemId}
          legs={legs}
          intent={intent}
          onBack={() => setIntent(null)}
          onOther={
            report.available
              ? () => {
                  onClose();
                  report.open({ category: "suggestion" });
                }
              : undefined
          }
        />
      )}
      <Disclaimer className="border-t border-border pt-3 text-center text-caption text-muted-foreground" />
    </div>
  );
}

function OtherQuestion({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="space-y-1.5 border-t border-border pt-3" data-testid="explain-other">
      <p className="text-xs font-semibold text-muted-foreground">{t("explain.other.label")}</p>
      <p className="text-sm text-muted-foreground">{t("explain.other.help")}</p>
      <button
        type="button"
        data-testid="explain-other-open"
        onClick={onOpen}
        className="tap-y relative inline-flex min-h-9 items-center gap-1.5 text-sm font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <MessageSquarePlus aria-hidden className="h-4 w-4" />
        {t("explain.other.action")}
      </button>
    </div>
  );
}

function Answer({
  entity,
  itemId,
  legs,
  intent,
  onBack,
  onOther,
}: ExplainTarget & {
  intent: ExplainIntent;
  onBack: () => void;
  onOther?: (() => void) | undefined;
}) {
  const preview = usePreviewParam();
  const transparency = useTransparencyOpen();
  const matchOrPick = useQuery({
    ...live.explain(entity === "pick" ? "pick" : "match", itemId ?? 0, intent, preview),
    enabled: entity !== "parlay" && itemId !== null,
  });
  const parlay = useQuery({
    ...live.explainParlay(legs ?? []),
    enabled: entity === "parlay" && (legs?.length ?? 0) > 0,
  });
  const q = entity === "parlay" ? parlay : matchOrPick;
  const answer = q.data?.data;
  const answered = answer?.answered ?? null;
  // one record per question opened, once its answer is known (the question only, with «.missing» when a datum was lacking)
  const [seen, setSeen] = useState<string | null>(null);
  if (answered !== null) {
    const what = trackWhat(entity, intent, answered);
    if (seen !== what) {
      setSeen(what);
      track("explain_opened", { what });
    }
  }
  return (
    <div className="space-y-3" data-testid="explain-answer" data-intent={intent}>
      <button
        type="button"
        data-testid="explain-back"
        onClick={onBack}
        className="tap-y relative inline-flex min-h-9 items-center gap-1.5 text-xs font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        {t("explain.back")}
      </button>
      <h3 className="font-display text-base font-bold leading-snug">
        {questionText(entity, intent)}
      </h3>
      {q.isPending && q.fetchStatus !== "idle" ? (
        <div aria-busy="true" aria-label={t("explain.loading")} className="space-y-3">
          <SkeletonBlock className="h-16" />
          <SkeletonBlock className="h-24" />
        </div>
      ) : q.isError || !answer ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-5" />
      ) : (
        <AnswerView
          answer={answer}
          transparency={transparency}
          footer={
            <HelpfulVote subject="explain" subjectId={voteSubjectId(entity, itemId, intent)} />
          }
          onOther={onOther}
        />
      )}
    </div>
  );
}

/** The answer's sentences, its words, its places to read more; apart from the query so a test renders it from a fixture. */
export function AnswerView({
  answer,
  transparency = false,
  footer,
  onOther,
}: {
  answer: Explanation;
  /** «Cómo le va a PrediGol» is open to this account: the answer may link to it. */
  transparency?: boolean;
  footer?: React.ReactNode;
  onOther?: (() => void) | undefined;
}) {
  const lines = answerLines(answer);
  const terms = answer.terms.filter(isTerm);
  return (
    <div className="space-y-3" data-testid="explain-lines-block" data-answered={answer.answered}>
      {!answer.answered ? (
        <p
          className="rounded-lg border border-border bg-elevated/40 px-3 py-2 text-sm font-semibold"
          data-testid="explain-no-data"
        >
          {t("explain.noData")}
        </p>
      ) : null}
      {lines.length ? (
        <ul className="space-y-1.5" data-testid="explain-lines">
          {lines.map((line, i) => (
            <li key={i} className="text-sm leading-relaxed text-foreground/90">
              {line}
            </li>
          ))}
        </ul>
      ) : null}
      {terms.length ? (
        <div className="space-y-1" data-testid="explain-terms">
          <p className="text-xs font-semibold text-muted-foreground">{t("explain.terms")}</p>
          <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
            {terms.map((term) => (
              <li key={term}>
                <GlossaryTerm term={term} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {answer.links.length ? (
        <div className="space-y-1" data-testid="explain-links">
          <p className="text-xs font-semibold text-muted-foreground">{t("explain.more")}</p>
          <ul className="space-y-0.5">
            {answer.links.includes("why_pick") && answer.entity === "pick" && answer.item_id ? (
              <li>
                <WhyPickButton pickId={answer.item_id} testId="explain-why-pick" />
              </li>
            ) : null}
            {answer.links.includes("transparency") && transparency ? (
              <li>
                <Link
                  to="/transparency"
                  data-testid="explain-link-transparency"
                  className="tap-y relative inline-flex text-sm font-semibold text-primary underline-offset-2 hover:underline"
                >
                  {t("explain.links.transparency")}
                </Link>
              </li>
            ) : null}
            {answer.links.includes("glossary") ? (
              <li>
                <Link
                  to={GLOSSARY_PATH}
                  data-testid="explain-link-glossary"
                  className="tap-y relative inline-flex text-sm font-semibold text-primary underline-offset-2 hover:underline"
                >
                  {t("explain.links.glossary")}
                </Link>
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}
      {footer}
      {onOther ? <OtherQuestion onOpen={onOther} /> : null}
    </div>
  );
}
