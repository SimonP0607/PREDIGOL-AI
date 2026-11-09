/**
 * «Salud de cuotas» in the Admin Console (plan Cuotas, section 6.6): the explorer's current-price book and what feeds it -
 * the prices' age by distance to kick-off, the extractor's lag, our quota and the provider's own count, the book's size,
 * rows that fell into a DEFAULT partition and `odds_quotes` against its brake. Read-only; GET /admin/odds/health
 * (SUPER_ADMIN), measured by the API and kept a minute.
 */
import { useQuery } from "@tanstack/react-query";
import { MetricCard, Panel } from "@/components/primitives/Panel";
import { TableShell, TableSkeleton, TD, TH, THead, TRow } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { live } from "@/lib/api/v1/queries";
import type { OddsHealth } from "@/lib/api/v1/types_odds_explorer";
import { t } from "@/lib/i18n";
import { localFixed, localInt, localPct } from "@/lib/i18n/format";
import { ErrorState } from "@/product/shared/States";
import { ageText, brakeTone, horizonAgeTone, lagTone, quotaTone } from "./oddsHealth";

export function OddsHealthTab() {
  const q = useQuery({ ...live.adminOddsHealth });
  if (q.isPending) return <TableSkeleton rows={4} cols={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const h = q.data?.data;
  if (!h) return <ErrorState error={null} onRetry={() => void q.refetch()} />;
  return <OddsHealthView h={h} />;
}

export function OddsHealthView({ h }: { h: OddsHealth }) {
  return (
    <div className="space-y-4" data-testid="odds-health">
      <p className="text-sm text-muted-foreground">{t("truth.oddsHealth.subtitle")}</p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label={t("truth.oddsHealth.cards.quota")}
          value={localInt(h.quota_today)}
          hint={t(
            h.provider_requests_remaining === null
              ? "truth.oddsHealth.cards.quotaHintNoProvider"
              : "truth.oddsHealth.cards.quotaHint",
            {
              share: h.quota_limit ? localPct(h.quota_today / h.quota_limit, 0) : "—",
              limit: localInt(h.quota_limit),
              remaining: localInt(h.provider_requests_remaining ?? 0),
            },
          )}
          tone={quotaTone(h.quota_today, h.quota_limit)}
        />
        <MetricCard
          label={t("truth.oddsHealth.cards.lag")}
          value={
            h.extraction_lag_min === null
              ? "—"
              : h.extraction_lag_min === 0
                ? t("truth.oddsHealth.cards.lagCaughtUp")
                : ageText(h.extraction_lag_min)
          }
          hint={t(
            h.extraction_lag_min === null
              ? "truth.oddsHealth.cards.lagNone"
              : "truth.oddsHealth.cards.lagHint",
          )}
          tone={lagTone(h.extraction_lag_min)}
        />
        <MetricCard
          label={t("truth.oddsHealth.cards.book")}
          value={t("truth.oddsHealth.cards.bookValue", { rows: localInt(h.book_rows) })}
          hint={t("truth.oddsHealth.cards.bookHint", { mb: localFixed(h.book_mb, 1) })}
          tone={h.book_rows === 0 ? "muted" : "default"}
        />
        <MetricCard
          label={t("truth.oddsHealth.cards.quotes")}
          value={`${localFixed(h.odds_quotes_gb, 1)} / ${localFixed(h.odds_quotes_brake_gb, 0)} GB`}
          hint={t("truth.oddsHealth.cards.quotesHint")}
          tone={brakeTone(h.odds_quotes_gb, h.odds_quotes_brake_gb)}
        />
      </div>

      <Panel
        title={t("truth.oddsHealth.horizon.title")}
        subtitle={t("truth.oddsHealth.horizon.subtitle")}
        bodyClassName=""
      >
        <TableShell>
          <THead>
            <TH>{t("truth.oddsHealth.col.horizon")}</TH>
            <TH align="right">{t("truth.oddsHealth.col.fixtures")}</TH>
            <TH align="right">{t("truth.oddsHealth.col.withBook")}</TH>
            <TH align="right">{t("truth.oddsHealth.col.age")}</TH>
            <TH>{t("truth.oddsHealth.col.stale")}</TH>
          </THead>
          <tbody>
            {h.by_horizon.map((row) => {
              const tone = horizonAgeTone(row.horizon, row.median_age_min);
              return (
                <TRow key={row.horizon}>
                  <TD className="text-sm">{t(`truth.oddsHealth.horizons.${row.horizon}`)}</TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(row.fixtures)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(row.with_book)}
                  </TD>
                  <TD
                    align="right"
                    className={
                      tone === "warning" ? "numeric text-xs text-warning" : "numeric text-xs"
                    }
                  >
                    {row.median_age_min === null ? "—" : ageText(row.median_age_min)}
                  </TD>
                  <TD>
                    {row.fixtures === 0 ? (
                      <span className="text-xs text-muted-foreground">—</span>
                    ) : (
                      <StatusBadge tone={row.stale > 0 ? "warning" : "positive"}>
                        {row.stale > 0
                          ? t("truth.oddsHealth.staleSome", { count: row.stale })
                          : t("truth.oddsHealth.staleNone")}
                      </StatusBadge>
                    )}
                  </TD>
                </TRow>
              );
            })}
          </tbody>
        </TableShell>
        <p className="px-4 py-2 text-caption text-muted-foreground">
          {t("truth.oddsHealth.horizon.target")}
        </p>
      </Panel>

      <Panel title={t("truth.oddsHealth.partitions.title")} bodyClassName="px-4 py-3">
        <p
          className={
            h.default_partition_rows > 0 ? "text-sm text-negative" : "text-sm text-muted-foreground"
          }
          data-testid="odds-health-partitions"
        >
          {h.default_partition_rows > 0
            ? t("truth.oddsHealth.partitions.some", {
                rows: localInt(h.default_partition_rows),
              })
            : t("truth.oddsHealth.partitions.none")}
        </p>
      </Panel>
    </div>
  );
}
