/**
 * ANÁLISIS PREDIGOL - up to three cards per match, computed once by PrediGol and read by every user (opening
 * this page never triggers an AI call). A card gives the market and selection, the best price and where, the
 * model's and the market's probabilities, the fair odds, the minimum odds worth taking, the edge, whether
 * PrediGol recommends it, the review's confidence, its main reason and its risks.
 *
 * Without an observed price a card says so and never calls anything value. A user sees only the cards of
 * qualified picks and the model's view of unpriced markets; the evaluation cards are the owner's preview.
 */
import { BrainCircuit, ShieldAlert } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtPct, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import { formatRelative } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { AnalysisCard, MatchAnalysis } from "@/lib/api/v1/types_ai_layer";
import { ShadowBadge } from "@/product/shared/Bits";
import { marketName, selectionLabel } from "@/product/shared/markets";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { Block } from "./ui";

const VERDICT_STYLE: Record<AnalysisCard["verdict"], string> = {
  recommended: "border-positive/40 bg-positive-soft text-positive",
  caution: "border-warning/40 bg-warning-soft text-warning",
  not_recommended: "border-negative/40 bg-negative-soft text-negative",
  no_market: "border-info/40 bg-info-soft text-info",
};

function Figure({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-caption text-subtle-foreground">{label}</dt>
      <dd className={cn("numeric text-sm", strong && "font-semibold")}>{value}</dd>
    </div>
  );
}

export function AnalysisCardView({
  card,
  home,
  away,
}: {
  card: AnalysisCard;
  home: string;
  away: string;
}) {
  const label = selectionLabel({
    market_key: card.market,
    selection: card.selection,
    line: card.line,
    home,
    away,
  });
  const noMarket = card.kind === "no_market";
  const edge = toNumber(card.edge);
  const risks = card.ai?.risks ?? [];
  const confidence = card.ai?.confidence ?? null;
  return (
    <article
      data-testid="analysis-card"
      data-verdict={card.verdict}
      className="flex h-full flex-col gap-3 rounded-xl border border-border bg-card p-3.5"
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-caption uppercase tracking-wider text-subtle-foreground">
            {marketName(card.market)}
          </div>
          <div className="truncate font-display text-[0.95rem] font-semibold">{label}</div>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide",
            VERDICT_STYLE[card.verdict],
          )}
        >
          {t(`match.analysis.verdict.${card.verdict}`)}
        </span>
      </header>

      {noMarket ? (
        <p className="rounded-md border border-info/30 bg-info-soft/50 px-2.5 py-1.5 text-caption font-medium uppercase tracking-wide text-info">
          {t("match.analysis.noMarketBanner")}
        </p>
      ) : null}

      <dl className="grid grid-cols-3 gap-x-3 gap-y-2">
        {noMarket ? null : (
          <Figure
            label={
              card.bookmaker
                ? t("match.analysis.oddsAt", { bookmaker: card.bookmaker })
                : t("match.analysis.odds")
            }
            value={fmtOdds(card.odds)}
            strong
          />
        )}
        <Figure label={t("match.analysis.model")} value={fmtPct(card.p_model)} />
        {noMarket ? null : (
          <Figure label={t("match.analysis.market")} value={fmtPct(card.p_market)} />
        )}
        <Figure label={t("match.analysis.fair")} value={fmtOdds(card.fair_odds)} />
        <Figure
          label={t("match.analysis.minimum")}
          value={fmtOdds(card.minimum_odds)}
          strong={noMarket}
        />
        {noMarket ? null : (
          <Figure
            label={t("match.analysis.edge")}
            value={edge === null ? "—" : fmtSignedPct(edge)}
          />
        )}
      </dl>

      {card.ai ? (
        <div className="space-y-1.5 border-t border-border/70 pt-2.5">
          <p className="text-xs">
            <span className="font-medium">{t(`match.analysis.decision.${card.ai.decision}`)}</span>
            {confidence !== null ? (
              <span className="text-subtle-foreground">
                {" "}
                · {t("match.analysis.confidence", { value: fmtPct(confidence) })}
              </span>
            ) : null}
          </p>
          {card.ai.reason ? (
            <p className="text-xs text-muted-foreground">{card.ai.reason}</p>
          ) : null}
          {risks.length ? (
            <ul className="space-y-0.5" aria-label={t("match.analysis.risks")}>
              {risks.map((r, i) => (
                <li key={i} className="flex gap-1.5 text-caption text-muted-foreground">
                  <ShieldAlert aria-hidden className="mt-0.5 h-3 w-3 shrink-0 text-warning" />
                  <span>{r.text}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : noMarket ? (
        <p className="text-caption text-subtle-foreground">{t("match.analysis.noMarketHelp")}</p>
      ) : (
        <p className="text-caption text-subtle-foreground">
          {t(`match.analysis.reason.${card.verdict_reason}`)}
        </p>
      )}
    </article>
  );
}

function Footer({ a }: { a: MatchAnalysis }) {
  return (
    <p
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-subtle-foreground"
      data-testid="analysis-footer"
    >
      <span className="inline-flex items-center gap-1">
        <BrainCircuit aria-hidden className="h-3 w-3" />
        {a.analyzed_by_llm ? t("match.analysis.byAi") : t("match.analysis.byRules")}
      </span>
      {a.built_at ? (
        <span>· {t("match.analysis.updated", { when: formatRelative(a.built_at) })}</span>
      ) : null}
      {a.mode === "shadow" || !a.enforced ? <span>· {t("match.analysis.shadowNote")}</span> : null}
    </p>
  );
}

export function AnalysisBlock({ ctx }: { ctx: MatchCtx }) {
  const preview = usePreviewParam();
  const q = useQuery(live.matchAnalysis(ctx.fixtureId, preview));
  const a = q.data?.data ?? null;
  const evaluation = a?.audience === "evaluation";
  const home = ctx.match.home.name;
  const away = ctx.match.away.name;
  // Line-ups come about an hour before kick-off and an unpriced market has its own cards: neither is a gap.
  const gaps = (a?.missing ?? []).filter((m) => m !== "lineups" && m !== "market");
  return (
    <Block
      title={t("match.analysis.title")}
      icon={<BrainCircuit />}
      right={evaluation ? <ShadowBadge /> : null}
      className={cn(evaluation && "border-info/40")}
    >
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
          {a.cards.length ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {a.cards.map((c) => (
                <AnalysisCardView
                  key={`${c.market}-${c.selection}-${c.line}`}
                  card={c}
                  home={home}
                  away={away}
                />
              ))}
            </div>
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
          <Footer a={a} />
        </div>
      )}
    </Block>
  );
}
