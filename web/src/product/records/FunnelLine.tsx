/**
 * How a pick of the day gets here (REVIEW PREDIGOL, B1): the steps every one of them passed - valid data, market, model,
 * calibration, value, risk, PrediGol Intelligence, selection - in one line under the day's picks. A user sees the
 * steps, never the model's name (point 1).
 */
import { ChevronRight, ListFilter } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import { localDecimalText } from "@/lib/i18n/format";

const STEPS = [
  "data",
  "market",
  "model",
  "calibration",
  "value",
  "risk",
  "context",
  "selection",
] as const;
/** The daily set's risk stage (fbi.picks.daily.RISK, risk-v1). */
const MAX_ODDS = "3.00";

/**
 * As a card (sheets K01 and K08): «Cómo llega un pick del día», each step a chip and the one PrediGol Intelligence adds in
 * green, and the way to the methodology. No counts are drawn: the API does not give how many matches entered each step.
 */
export function FunnelLine() {
  return (
    <section
      className="card-surface space-y-3 rounded-card p-4"
      data-testid="daily-funnel"
      title={t("records.funnel.help")}
      aria-labelledby="daily-funnel-title"
    >
      <h3 id="daily-funnel-title" className="flex items-center gap-2 text-sm font-semibold">
        <ListFilter aria-hidden className="h-4 w-4 text-primary" />
        {t("records.funnel.label")}
      </h3>
      <ol className="flex flex-wrap items-center gap-1.5">
        {STEPS.map((s, i) => (
          <li key={s} className="flex items-center gap-1.5">
            {i > 0 ? (
              <ChevronRight aria-hidden className="h-3 w-3 shrink-0 text-subtle-foreground" />
            ) : null}
            <span
              className={
                s === "context"
                  ? "rounded-full border border-primary/40 bg-primary-soft px-2.5 py-1 text-caption font-semibold text-primary"
                  : s === "selection"
                    ? "rounded-full border border-gold/40 bg-gold-soft px-2.5 py-1 text-caption font-semibold text-gold-strong"
                    : "rounded-full bg-foreground/[0.07] px-2.5 py-1 text-caption text-foreground-soft"
              }
            >
              {t(`records.funnel.steps.${s}`, { max: localDecimalText(MAX_ODDS) })}
            </span>
          </li>
        ))}
      </ol>
      <Link
        to="/transparency/methodology"
        className="tap-y relative inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="daily-funnel-method"
      >
        {t("records.funnel.method")}
        <ChevronRight aria-hidden className="h-3.5 w-3.5" />
      </Link>
    </section>
  );
}
