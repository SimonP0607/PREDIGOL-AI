/**
 * How a pick of the day gets here (REVIEW PREDIGOL, B1): the steps every one of them passed - valid data, market, model,
 * calibration, value, risk, PrediGol Intelligence, selection - in one line under the day's picks. A user sees the
 * steps, never the model's name (point 1).
 */
import { ChevronRight, ListFilter } from "lucide-react";
import { Fragment } from "react";
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
/** daily-set-v4's risk stage (fbi.picks.daily.RISK). */
const MAX_ODDS = "3.00";

export function FunnelLine() {
  return (
    <div
      className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-caption text-muted-foreground"
      data-testid="daily-funnel"
      title={t("records.funnel.help")}
    >
      <span className="inline-flex items-center gap-1 font-medium text-subtle-foreground">
        <ListFilter aria-hidden className="h-3 w-3" />
        {t("records.funnel.label")}:
      </span>
      {STEPS.map((s, i) => (
        <Fragment key={s}>
          {i > 0 ? (
            <ChevronRight aria-hidden className="h-3 w-3 shrink-0 text-subtle-foreground" />
          ) : null}
          <span className={s === "context" ? "font-medium text-primary" : undefined}>
            {t(`records.funnel.steps.${s}`, { max: localDecimalText(MAX_ODDS) })}
          </span>
        </Fragment>
      ))}
    </div>
  );
}
