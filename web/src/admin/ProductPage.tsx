/**
 * Product analytics (plan UX, A6 and section 39): activation, habit, usage by function, devices and errors, from the
 * readers' events of the closed catalog. Global figures only with enough readers active in 30 days (20 by default):
 * below that, the page says how many there are and nothing else. The owner and the synthetic account are never
 * counted. Anti-metrics - time in the app, picks saved per reader, notices sent - are not shown to be optimised. Under
 * them, what readers think (B6): the monthly survey with its n, «¿Te sirvió?» and the comments.
 */
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { v1 } from "@/lib/api/v1/client";
import type { ProductOverview } from "@/lib/api/v1/types_events";
import { t, translateOr } from "@/lib/i18n";
import { fmtInt } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { Card, ErrorState } from "@/product/shared/States";
import { FeedbackCard } from "./FeedbackCard";
import { PushCard } from "./PushCard";

function Figure({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="rounded-md border border-border p-3" data-testid={testId}>
      <p className="text-caption text-muted-foreground">{label}</p>
      <p className="numeric font-display text-xl font-semibold">{value}</p>
    </div>
  );
}

export function SwitchState({ o }: { o: ProductOverview }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="product-state">
      <span
        className={cn(
          "rounded-full border px-2 py-0.5 font-semibold",
          o.mode === "off"
            ? "border-warning/40 bg-warning-soft text-warning"
            : "border-positive/40 bg-positive-soft text-positive",
        )}
      >
        {t(`admin.product.mode.${o.mode}`)}
      </span>
      <span className="text-muted-foreground">{t(`admin.product.purge.${o.purge}`)}</span>
    </div>
  );
}

function Body({ o }: { o: ProductOverview }) {
  if (o.status !== "ok") {
    return (
      <p className="text-sm text-muted-foreground" data-testid="product-insufficient">
        {o.status === "empty"
          ? t("admin.product.empty")
          : t("admin.product.insufficient", { n: o.active_30d, min: o.min_subjects })}
      </p>
    );
  }
  const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : String(v));
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure label={t("admin.product.active.d1")} value={fmtInt(o.active["d1"] ?? 0)} />
        <Figure label={t("admin.product.active.d7")} value={fmtInt(o.active["d7"] ?? 0)} />
        <Figure label={t("admin.product.active.d30")} value={fmtInt(o.active["d30"] ?? 0)} />
        <Figure label={t("admin.product.daysPerWeek")} value={num(o.days_active_per_week)} />
        <Figure label={t("admin.product.errorsPerActive")} value={num(o.errors_per_active)} />
        <Figure label={t("admin.product.dauMau")} value={num(o.dau_mau)} />
      </div>
      <section aria-labelledby="product-funnel">
        <h3 id="product-funnel" className="mb-2 text-sm font-semibold">
          {t("admin.product.funnel")}
        </h3>
        <ol className="space-y-1 text-sm" data-testid="product-funnel">
          {o.funnel.map((f) => (
            <li key={f.step} className="flex justify-between gap-3 border-b border-border py-1">
              <span>{t(`admin.product.step.${f.step}`)}</span>
              <span className="numeric">{fmtInt(f.subjects)}</span>
            </li>
          ))}
        </ol>
      </section>
      <section aria-labelledby="product-devices">
        <h3 id="product-devices" className="mb-2 text-sm font-semibold">
          {t("admin.product.devices")}
        </h3>
        <p className="text-sm" data-testid="product-devices">
          {Object.entries(o.devices)
            .map(([d, n]) => `${translateOr(`admin.product.device.${d}`, d)} ${fmtInt(n)}`)
            .join(" · ") || "—"}
        </p>
      </section>
      <section aria-labelledby="product-usage">
        <h3 id="product-usage" className="mb-2 text-sm font-semibold">
          {t("admin.product.usage")}
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] text-sm" data-testid="product-usage">
            <thead>
              <tr className="text-left text-caption text-muted-foreground">
                <th className="py-1 pr-3 font-medium">{t("admin.product.event")}</th>
                <th className="py-1 pr-3 text-right font-medium">{t("admin.product.events7")}</th>
                <th className="py-1 pr-3 text-right font-medium">{t("admin.product.readers7")}</th>
                <th className="py-1 pr-3 text-right font-medium">{t("admin.product.events30")}</th>
                <th className="py-1 text-right font-medium">{t("admin.product.readers30")}</th>
              </tr>
            </thead>
            <tbody>
              {o.usage.map((u) => (
                <tr key={u.name} className="border-t border-border" data-event={u.name}>
                  <td className="py-1 pr-3 font-mono text-xs">{u.name}</td>
                  <td className="numeric py-1 pr-3 text-right">{fmtInt(u.events_7d)}</td>
                  <td className="numeric py-1 pr-3 text-right">{fmtInt(u.subjects_7d)}</td>
                  <td className="numeric py-1 pr-3 text-right">{fmtInt(u.events_30d)}</td>
                  <td className="numeric py-1 text-right">{fmtInt(u.subjects_30d)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <p className="text-caption text-muted-foreground">{t("admin.product.antiMetrics")}</p>
    </div>
  );
}

export function ProductPage() {
  const q = useQuery({ queryKey: ["admin", "product"], queryFn: v1.productOverview });
  return (
    <div className="space-y-5">
      <PageHeader
        title={t("admin.pages.product.title")}
        description={t("admin.pages.product.description")}
        actions={
          <button
            type="button"
            onClick={() => void q.refetch()}
            aria-label={t("common.retry")}
            className="tap relative rounded-md border border-border-strong p-2 hover:bg-elevated"
          >
            <RefreshCw aria-hidden className={cn("h-4 w-4", q.isFetching && "animate-spin")} />
          </button>
        }
      />
      <Card className="space-y-4 p-4" as="div">
        <h2 className="flex items-center gap-2 font-display text-base font-semibold">
          <BarChart3 aria-hidden className="h-4 w-4 text-primary" />
          {t("admin.product.title")}
        </h2>
        {q.isPending ? (
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : (
          <>
            <SwitchState o={q.data} />
            <Body o={q.data} />
          </>
        )}
      </Card>
      {/* What readers think of PrediGol: the monthly survey, «¿Te sirvió?» and the comments (plan UX, B6). */}
      <FeedbackCard />
      {/* The readers' notices on their devices: available or not, devices and a week of notices (plan UX, B7). */}
      <PushCard />
    </div>
  );
}
