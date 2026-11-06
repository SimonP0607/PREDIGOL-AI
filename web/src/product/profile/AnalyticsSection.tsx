/**
 * The usage statistics, in the reader's Privacy block (plan de cierre UX, 1.2): a switch that starts off and carries the
 * sentence of the processing policy the decision records - which the reader can turn on or off at any moment. While it
 * is off nothing of the reader's use is recorded, even when the owner has the statistics on (FBI_PRODUCT_EVENTS=consent).
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Loader2 } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import { t, useI18n } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/product/shared/States";
import { analyticsOf, type OptionalState } from "./consents";

export function AnalyticsView({
  analytics,
  busy,
  failure,
  onToggle,
}: {
  analytics: OptionalState;
  busy: boolean;
  failure: string | null;
  onToggle: () => void;
}) {
  const { purpose, latest } = analytics;
  const on = latest?.granted === true;
  return (
    <section className="mt-3 space-y-2" data-testid="analytics">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <BarChart3 aria-hidden className="h-4 w-4 text-primary" />
        {t("legal.privacy.analytics.title")}
      </h3>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        disabled={busy}
        onClick={onToggle}
        data-testid="analytics-switch"
        className="flex min-h-11 w-full items-center justify-between gap-3 rounded-md py-2 text-left hover:bg-elevated/60 disabled:opacity-60"
      >
        <span className="min-w-0 space-y-0.5">
          <span className="block text-sm">{purpose.statement}</span>
          <span className="block text-xs text-muted-foreground">
            {t("legal.privacy.analytics.help")}
          </span>
          {latest ? (
            <span
              className="block text-caption text-muted-foreground"
              data-testid="analytics-since"
            >
              {t(
                latest.granted ? "legal.privacy.analytics.since" : "legal.privacy.analytics.left",
                { date: formatDateTime(latest.at) },
              )}
            </span>
          ) : null}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          <span className="sr-only">
            {on ? t("profile.notifications.on") : t("profile.notifications.off")}
          </span>
          <span
            aria-hidden
            className={cn(
              "relative inline-flex h-6 w-11 items-center rounded-full border-2 border-transparent transition-colors",
              on ? "bg-primary" : "bg-input",
            )}
          >
            <span
              className={cn(
                "block h-5 w-5 rounded-full bg-background shadow transition-transform",
                on ? "translate-x-5" : "translate-x-0",
              )}
            />
          </span>
        </span>
      </button>
      {failure ? (
        <p role="alert" className="text-xs text-negative">
          {failure}
        </p>
      ) : null}
    </section>
  );
}

export function AnalyticsSection() {
  const qc = useQueryClient();
  const { locale } = useI18n();
  const state = useQuery({
    queryKey: ["me", "consents", locale],
    queryFn: () => v1.myConsents(locale),
  });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const analytics = analyticsOf(state.data);
  // Not listed - or the consents could not be read: the rows above show the error.
  if (!analytics) return null;
  const on = analytics.latest?.granted === true;

  async function toggle() {
    if (!analytics) return;
    setBusy(true);
    setFailure(null);
    try {
      const next = await v1.decideConsents({
        decisions: [
          { kind: analytics.purpose.kind, granted: !on, version: analytics.purpose.version },
        ],
        locale,
        source: "profile",
      });
      qc.setQueryData(["me", "consents", locale], next);
      await qc.invalidateQueries({ queryKey: ["me", "consents"] });
    } catch (err) {
      setFailure(errorMessage(err));
      await qc.invalidateQueries({ queryKey: ["me", "consents"] });
    } finally {
      setBusy(false);
    }
  }

  return (
    <AnalyticsView
      analytics={analytics}
      busy={busy}
      failure={failure}
      onToggle={() => void toggle()}
    />
  );
}
