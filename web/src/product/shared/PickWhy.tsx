/**
 * The one line and the chips of a compact pick (plan de cierre UX, 2.3): why it is shown - the probability PrediGol gives
 * the selection next to the market's, the same two numbers the full card draws as bars - and what could go against it, the
 * risks the review of its context found. Both come from what is already stored with the pick: a number or a risk that is
 * missing leaves its part out, and a risk is never made up.
 */
import { t } from "@/lib/i18n";
import { fmtPct } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";

function share(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** «PrediGol le da 52 % y el mercado, 45 %.» - nothing without both numbers. */
export function PickWhyLine({
  model,
  market,
  className,
}: {
  model: string | number | null | undefined;
  market: string | number | null | undefined;
  className?: string | undefined;
}) {
  const m = share(model);
  const k = share(market);
  if (m === null || k === null) return null;
  return (
    <p
      className={cn("text-xs leading-snug text-muted-foreground", className)}
      data-testid="pick-why-line"
    >
      {t("picks.whyLine", { model: fmtPct(m, 0), market: fmtPct(k, 0) })}
    </p>
  );
}

/** The most chips a compact pick shows: the reader opens «¿Por qué?» for the rest. */
export const MAX_RISK_CHIPS = 2;

/** The risks of the review of the pick's context as chips (two at most, each in two lines at most); none without any. */
export function RiskChips({
  risks,
  className,
}: {
  risks: readonly string[] | null | undefined;
  className?: string | undefined;
}) {
  const shown = (risks ?? [])
    .map((r) => r.trim())
    .filter((r) => r.length > 0)
    .slice(0, MAX_RISK_CHIPS);
  if (shown.length === 0) return null;
  return (
    <ul
      aria-label={t("picks.riskChips")}
      className={cn("flex flex-wrap gap-1.5", className)}
      data-testid="risk-chips"
    >
      {shown.map((risk, i) => (
        <li
          key={i}
          title={risk}
          className="line-clamp-2 min-w-0 max-w-full break-words rounded-md border border-warning/40 bg-warning-soft px-2 py-0.5 text-caption leading-snug text-foreground/90"
        >
          {risk}
        </li>
      ))}
    </ul>
  );
}
