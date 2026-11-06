/**
 * The published picks one by one (plan de cierre UX, 1.5): under the counts of «Cómo le va a PrediGol», each pick PrediGol
 * published with the price and the probability it was frozen with and how it ended, newest first, a page at a time. The list
 * is the counts' own rows - its total is the whole history's «published» - and it shows only what a reader may see: the
 * published set, never an evaluation item. A pick stays as it was published; the result is added beside it.
 *
 * `PickListView` is the pure part (a test renders it from rows); `PickListSection` reads the pages.
 */
import { useInfiniteQuery } from "@tanstack/react-query";
import { Loader2, Rows3 } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { fmtOdds, fmtPct } from "@/lib/i18n/format";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { fmtUnits } from "@/product/records/units";
import { marketName, selectionLabel } from "@/product/shared/markets";
import { ErrorState, SkeletonCards } from "@/product/shared/States";
import type { PublishedPick } from "@/lib/api/v1/types_transparency";
import { Block, Note } from "./parts";
import { intText, resultTone, scoreText } from "./model";

/** Picks per page: enough to read, few enough for a phone. */
export const PAGE_SIZE = 20;

const TONE = {
  positive: "border-positive/40 text-positive",
  negative: "border-negative/40 text-negative",
  neutral: "border-border text-muted-foreground",
} as const;

function Fact({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-caption text-muted-foreground">{label}</dt>
      <dd className="numeric text-sm font-semibold text-foreground" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

export function PublishedPickRow({ pick }: { pick: PublishedPick }) {
  const score = scoreText(pick.score_home, pick.score_away);
  return (
    <li
      className="space-y-2 rounded-lg bg-elevated/60 p-3"
      data-testid="published-pick"
      data-result={pick.result}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-sm font-semibold leading-snug">
          {pick.home} – {pick.away}
        </p>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-caption font-medium",
            TONE[resultTone(pick.result)],
          )}
          data-testid="published-pick-result"
        >
          {t(`records.status.${pick.result}`)}
        </span>
      </div>
      <p className="text-caption text-muted-foreground">
        {pick.competition}
        {" · "}
        {formatDateTime(pick.kickoff_at)}
      </p>
      <p className="text-sm">
        <span className="text-muted-foreground">{marketName(pick.market)}</span>
        {" · "}
        <span className="font-medium">
          {selectionLabel({
            market_key: pick.market,
            selection: pick.selection,
            line: pick.line,
            home: pick.home,
            away: pick.away,
          })}
        </span>
      </p>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-4">
        <Fact label={t("transparency.picks.odds")} value={fmtOdds(pick.odds)} />
        <Fact label={t("transparency.picks.said")} value={fmtPct(pick.p_model, 0)} />
        <Fact label={t("transparency.picks.market")} value={fmtPct(pick.p_market, 0)} />
        <Fact
          label={t("transparency.picks.units")}
          value={pick.units === null ? t("transparency.picks.pending") : fmtUnits(pick.units)}
        />
        {score ? <Fact label={t("transparency.picks.score")} value={score} /> : null}
      </dl>
    </li>
  );
}

export function PickListView({
  items,
  total,
  hasMore,
  loadingMore,
  onMore,
}: {
  items: readonly PublishedPick[];
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
}) {
  return (
    <Block
      id="picks"
      title={t("transparency.picks.title")}
      subtitle={t("transparency.picks.subtitle")}
      icon={<Rows3 className="h-4 w-4" />}
    >
      {items.length === 0 ? (
        <p className="text-sm" data-testid="transparency-picks-none">
          {t("transparency.picks.none")}
        </p>
      ) : (
        <>
          <ul className="space-y-2" data-testid="transparency-pick-list">
            {items.map((p, i) => (
              <PublishedPickRow
                key={`${p.kickoff_at}-${p.market}-${p.selection}-${p.home}-${i}`}
                pick={p}
              />
            ))}
          </ul>
          <p className="text-caption text-muted-foreground" data-testid="transparency-picks-shown">
            {t("transparency.picks.shown", { shown: intText(items.length), total: intText(total) })}
          </p>
          {hasMore ? (
            <button
              type="button"
              onClick={onMore}
              disabled={loadingMore}
              data-testid="transparency-picks-more"
              className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-strong px-3 py-2 text-sm font-medium hover:bg-elevated disabled:opacity-60"
            >
              {loadingMore ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
              {t("transparency.picks.more")}
            </button>
          ) : null}
        </>
      )}
      <Note>{t("transparency.picks.legend")}</Note>
    </Block>
  );
}

export function PickListSection({ preview }: { preview: "shadow" | undefined }) {
  const q = useInfiniteQuery(live.transparencyPickPages(PAGE_SIZE, preview));
  if (q.isPending) {
    return (
      <Block
        id="picks"
        title={t("transparency.picks.title")}
        subtitle={t("transparency.picks.subtitle")}
        icon={<Rows3 className="h-4 w-4" />}
      >
        <SkeletonCards count={2} />
      </Block>
    );
  }
  if (q.isError) {
    return (
      <Block
        id="picks"
        title={t("transparency.picks.title")}
        subtitle={t("transparency.picks.subtitle")}
        icon={<Rows3 className="h-4 w-4" />}
      >
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Block>
    );
  }
  const items = q.data.pages.flatMap((p) => (p.status === "ok" ? p.data : []));
  const total = q.data.pages[0]?.meta.total ?? items.length;
  return (
    <PickListView
      items={items}
      total={total}
      hasMore={q.hasNextPage}
      loadingMore={q.isFetchingNextPage}
      onMore={() => void q.fetchNextPage()}
    />
  );
}
