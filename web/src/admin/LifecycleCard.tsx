/**
 * The customers' lifecycle for the owner (plan UX, B11 and section 40): how many are in each state on the newest day
 * computed, the share who renew, who activate within a week and who come back in the second week and the second month. A
 * share of a cohort under 30 readers is not shown - «datos insuficientes» with its n - because a percentage of five people is
 * a story, not a measure. Nothing here is optimised: no message and no nudge is sent because of these figures.
 */
import type { LifecycleMetrics } from "@/lib/api/v1/types_events";
import { CUSTOMER_STATES, calendarDay, rateText } from "./lifecycleFigures";
import { t } from "@/lib/i18n";
import { fmtInt } from "@/lib/i18n/format";
import { formatDateYear } from "@/lib/time";

function Figure({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div className="rounded-md border border-border p-3" data-testid={testId}>
      <p className="text-caption text-muted-foreground">{label}</p>
      <p className="numeric font-display text-base font-semibold">{value}</p>
    </div>
  );
}

export function LifecycleView({ m }: { m: LifecycleMetrics }) {
  return (
    <div className="space-y-4" data-testid="lifecycle-overview">
      <p className="text-caption text-muted-foreground">
        {m.day
          ? t("admin.product.lifecycle.day", { date: formatDateYear(calendarDay(m.day)) })
          : t("admin.product.lifecycle.noDay")}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {CUSTOMER_STATES.map((s) => (
          <Figure
            key={s}
            testId={`lifecycle-state-${s}`}
            label={t(`admin.customers.lifecycle.state.${s}`)}
            value={fmtInt(m.states[s] ?? 0)}
          />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          testId="lifecycle-renewal"
          label={t("admin.product.lifecycle.renewal")}
          value={rateText(m.renewal_30d)}
        />
        <Figure
          testId="lifecycle-activation"
          label={t("admin.product.lifecycle.activation")}
          value={rateText(m.activation_7d)}
        />
        <Figure
          testId="lifecycle-d7"
          label={t("admin.product.lifecycle.d7")}
          value={rateText(m.retention_d7)}
        />
        <Figure
          testId="lifecycle-d30"
          label={t("admin.product.lifecycle.d30")}
          value={rateText(m.retention_d30)}
        />
      </div>
      <p className="text-caption text-muted-foreground">{t("admin.product.lifecycle.note")}</p>
    </div>
  );
}
