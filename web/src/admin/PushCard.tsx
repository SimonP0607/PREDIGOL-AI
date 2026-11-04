/**
 * The readers' notices on their devices, for the owner (plan UX, B7; section 34): whether they are available (FBI_PUSH and
 * PrediGol's VAPID key, P12), how many readers receive them and on which browsers, and a week of notices by category -
 * sent and dropped - with the devices their push service dropped (404 or 410). Counts, never who. Notices sent is an
 * anti-metric (section 23): it is shown to see the noise, never to push it up.
 */
import { useQuery } from "@tanstack/react-query";
import { BellRing, Loader2 } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { PushOverview } from "@/lib/api/v1/types_push";
import { t } from "@/lib/i18n";
import { fmtInt } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/product/shared/States";

export function PushView({ o }: { o: PushOverview }) {
  const devices = o.devices.reduce((sum, d) => sum + d.devices, 0);
  return (
    <div className="space-y-4" data-testid="push-overview">
      <span
        className={cn(
          "inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold",
          o.available
            ? "border-positive/40 bg-positive-soft text-positive"
            : "border-warning/40 bg-warning-soft text-warning",
        )}
        data-testid="push-available"
      >
        {t(o.available ? "admin.product.push.on" : "admin.product.push.off")}
      </span>
      <div className="grid grid-cols-3 gap-3">
        {[
          ["readers", o.readers],
          ["devices", devices],
          ["gone", o.gone],
        ].map(([key, value]) => (
          <div
            key={key}
            className="rounded-md border border-border p-3"
            data-testid={`push-${key}`}
          >
            <p className="text-caption text-muted-foreground">{t(`admin.product.push.${key}`)}</p>
            <p className="numeric font-display text-xl font-semibold">{fmtInt(Number(value))}</p>
          </div>
        ))}
      </div>
      {o.devices.length > 0 ? (
        <section className="space-y-1">
          <h3 className="text-sm font-medium">{t("admin.product.push.byBrowser")}</h3>
          <ul className="text-sm" data-testid="push-browsers">
            {o.devices.map((d) => (
              <li key={`${d.family}-${d.system}`} className="flex justify-between gap-3 py-0.5">
                <span>
                  {t("push.profile.device", {
                    browser: t(`push.profile.families.${d.family}`),
                    system: t(`push.profile.systems.${d.system}`),
                  })}
                </span>
                <span className="numeric">{fmtInt(d.devices)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section className="space-y-1">
        <h3 className="text-sm font-medium">{t("admin.product.push.week")}</h3>
        {o.notices.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="push-no-notices">
            {t("admin.product.push.none")}
          </p>
        ) : (
          <table className="w-full text-sm" data-testid="push-notices">
            <thead>
              <tr className="text-left text-caption text-muted-foreground">
                <th className="py-1 font-medium">{t("admin.product.push.category")}</th>
                <th className="py-1 text-right font-medium">{t("admin.product.push.sent")}</th>
                <th className="py-1 text-right font-medium">{t("admin.product.push.dropped")}</th>
              </tr>
            </thead>
            <tbody>
              {o.notices.map((n) => (
                <tr key={n.category} className="border-t border-border">
                  <td className="py-1">{t(`admin.product.push.categories.${n.category}`)}</td>
                  <td className="numeric py-1 text-right">{fmtInt(n.sent)}</td>
                  <td className="numeric py-1 text-right">{fmtInt(n.dropped)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <p className="text-caption text-subtle-foreground">{t("admin.product.push.note")}</p>
    </div>
  );
}

export function PushCard() {
  const q = useQuery({ queryKey: ["admin", "product", "push"], queryFn: v1.pushOverview });
  return (
    <section
      aria-labelledby="push-title"
      className="space-y-4 rounded-xl border border-border bg-card p-4"
      data-testid="push-card"
    >
      <h2 id="push-title" className="flex items-center gap-2 font-display text-base font-semibold">
        <BellRing aria-hidden className="h-4 w-4 text-primary" />
        {t("admin.product.push.title")}
      </h2>
      {q.isPending ? (
        <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <PushView o={q.data} />
      )}
    </section>
  );
}
