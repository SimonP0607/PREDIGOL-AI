/**
 * The detail of a pick (plan maestro UX/UI 2026, decision 3; sheet K02): a page of its own for one pick, reached from its
 * card. It composes what PrediGol already says of the pick - GET /picks/{id}/explanation, the answer behind «¿Por qué?» -
 * and nothing else: every figure is the card's, every line a template of `explanation.ts` over that answer, and a block
 * whose data is missing is not drawn. It asks no new endpoint and computes nothing of the business.
 */
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { LiveApiError } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { PickExplanation } from "@/lib/api/v1/types_explanation";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatDateTime, formatKickoff } from "@/lib/time";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import { ExplainButton } from "@/product/explain/ExplainSheet";
import { HelpfulVote } from "@/product/feedback/HelpfulVote";
import { ASK_BUTTON, OddsPill, ProbCompare } from "@/product/shared/Bits";
import { marketName } from "@/product/shared/markets";
import { EmptyState, ErrorState, SkeletonBlock } from "@/product/shared/States";
import { UserStatusBadge } from "@/product/shared/UserStatusBadge";
import { reasonText } from "@/product/shared/userStatus";
import { useTransparencyOpen } from "@/product/transparency/useTransparencyOpen";
import {
  HOW_STEPS,
  conclusionText,
  contextEmptyText,
  contextLines,
  dayText,
  howText,
  marketLines,
  riskLines,
  selectionOf,
} from "./explanation";

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} data-testid={`pick-detail-${id}`}>
      <h2 id={id} className="text-title">
        {title}
      </h2>
      <div className="card-surface mt-2 space-y-3 rounded-card p-4">{children}</div>
    </section>
  );
}

function Lines({ lines }: { lines: string[] }) {
  return (
    <ul className="space-y-2">
      {lines.map((line, i) => (
        <li key={i} className="text-sm leading-relaxed text-foreground/90">
          {line}
        </li>
      ))}
    </ul>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5">
      <dt className="shrink-0 text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right text-sm font-medium">{children}</dd>
    </div>
  );
}

function Detail({ e, pickId }: { e: PickExplanation; pickId: number }) {
  const transparency = useTransparencyOpen();
  const context = contextLines(e);
  const risks = riskLines(e);
  const day = dayText(e);
  // the gold card is the recommendation's (the rule of the pick's card): recommended, and still worth its price
  const gold = e.user_status === "RECOMMENDED" && e.market.value_now !== false;
  return (
    <>
      <article
        className={cn(
          "space-y-3 rounded-feature p-4",
          gold ? "surface-gold hairline-gold" : "card-surface",
        )}
        data-testid="pick-detail-card"
        data-status={e.user_status}
      >
        <UserStatusBadge state={e} testId="pick-detail-status" />
        <Link
          to="/matches/$fixtureId"
          params={{ fixtureId: String(e.match.fixture_id) }}
          className="tap-y relative block text-sm text-foreground-soft hover:text-foreground"
          data-testid="pick-detail-match"
        >
          <span className="font-semibold text-foreground">
            {e.match.home.name} – {e.match.away.name}
          </span>
          <span className="mt-0.5 block text-[0.8125rem] text-muted-foreground">
            {[e.match.competition.name, formatKickoff(e.match.kickoff_at)].join(" · ")}
          </span>
        </Link>
        <div className="flex items-end justify-between gap-3">
          <div className="min-w-0">
            <p className="text-overline text-muted-foreground">{marketName(e.market_key)}</p>
            <h1 className="mt-1 text-heading text-balance">{selectionOf(e)}</h1>
          </div>
          <OddsPill odds={e.market.published_odds} best={gold} size="lg" />
        </div>
        <p className="text-[0.8125rem] text-muted-foreground" data-testid="pick-detail-reason">
          {e.started ? `${t("picks.why.startedState")} ` : null}
          {reasonText(e.status_reason)}
        </p>
      </article>

      <Block id="phrase" title={t("picks.detail.phrase")}>
        <p className="text-[0.9375rem] font-medium leading-relaxed">{conclusionText(e)}</p>
      </Block>

      <Block id="value" title={t("picks.detail.value")}>
        <ProbCompare model={e.market.p_model} market={e.market.p_market} />
        <Lines lines={marketLines(e)} />
      </Block>

      <Block id="context" title={t("picks.why.layers.context")}>
        {context.length > 0 ? (
          <Lines lines={context} />
        ) : (
          <p className="text-sm text-muted-foreground">{contextEmptyText(e)}</p>
        )}
        {e.narrative ? (
          <p className="text-caption text-subtle-foreground">{t("picks.why.context.narrative")}</p>
        ) : null}
      </Block>

      {risks.length > 0 || (e.review?.risks.length ?? 0) > 0 ? (
        <Block id="risks" title={t("picks.detail.risks")}>
          {risks.length > 0 ? <Lines lines={risks} /> : null}
          {e.review && e.review.risks.length > 0 ? (
            <div className="space-y-1.5">
              <p className="text-xs font-semibold text-muted-foreground">
                {t("picks.why.risks.review")}
              </p>
              <Lines lines={e.review.risks} />
            </div>
          ) : null}
        </Block>
      ) : null}

      <Block id="how" title={t("picks.detail.how")}>
        <ol className="list-decimal space-y-1 pl-5 text-sm leading-relaxed">
          {HOW_STEPS.map((s) => (
            <li key={s}>{t(`transparency.how.steps.${s}`)}</li>
          ))}
        </ol>
        <p className="text-sm font-medium">{howText(e)}</p>
        {transparency ? (
          <Link
            to="/transparency"
            hash="how"
            className="tap-y relative inline-flex items-center gap-1 text-[0.8125rem] font-semibold text-primary underline-offset-2 hover:underline"
          >
            {t("picks.why.how.more")}
            <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        ) : null}
      </Block>

      <section aria-labelledby="sheet" data-testid="pick-detail-sheet">
        <h2 id="sheet" className="text-title">
          {t("picks.detail.sheet")}
        </h2>
        <dl className="card-surface mt-2 divide-y divide-border rounded-card px-4">
          <Fact label={t("picks.detail.market")}>{marketName(e.market_key)}</Fact>
          <Fact label={t("picks.detail.publishedOdds")}>
            <span className="numeric">
              <OddsPill odds={e.market.published_odds} size="sm" />
            </span>
          </Fact>
          <Fact label={t("picks.detail.publishedAt")}>
            <span className="numeric">{formatDateTime(e.market.published_at)}</span>
          </Fact>
          {day ? <Fact label={t("picks.detail.daySet")}>{day}</Fact> : null}
        </dl>
      </section>

      <div className="flex flex-wrap gap-2">
        <Link
          to="/matches/$fixtureId"
          params={{ fixtureId: String(e.match.fixture_id) }}
          className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "flex-1")}
          data-testid="pick-detail-open-match"
        >
          {t("picks.detail.openMatch")}
        </Link>
        <ExplainButton
          entity="pick"
          itemId={pickId}
          testId="pick-detail-explain"
          className={ASK_BUTTON}
        />
      </div>
      <HelpfulVote subject="explanation" subjectId={pickId} />
    </>
  );
}

export function PickDetailPage({ pickId }: { pickId: string }) {
  const valid = /^\d{1,15}$/.test(pickId);
  const id = valid ? Number(pickId) : 0;
  const preview = usePreviewParam();
  const q = useQuery({ ...live.pickExplanation(id, preview), enabled: valid });
  const e = q.data?.data;
  const missing =
    !valid || (q.isError && q.error instanceof LiveApiError && q.error.status === 404);
  return (
    <div className="mx-auto max-w-2xl space-y-5" data-testid="pick-detail">
      <Link
        to="/picks"
        className="tap-y relative inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft aria-hidden className="h-4 w-4" />
        {t("nav.picks")}
      </Link>
      {missing ? (
        <EmptyState title={t("picks.detail.missing")} body={t("picks.detail.missingBody")} />
      ) : q.isPending ? (
        <div aria-busy="true" aria-label={t("common.loading")} className="space-y-3">
          <SkeletonBlock className="h-40" />
          <SkeletonBlock className="h-24" />
          <SkeletonBlock className="h-40" />
        </div>
      ) : q.isError || !e ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <Detail e={e} pickId={id} />
      )}
    </div>
  );
}
