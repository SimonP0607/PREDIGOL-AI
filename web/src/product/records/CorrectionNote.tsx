/**
 * "Result corrected" (plan F0, defect 5): the provider corrected a match after a record on it was settled, so the record
 * was settled again. The card shows the current result; this note says what it had been - one line per correction, with
 * the leg it concerns - so a result never changes without a trace where the person is looking at it.
 *
 * `record` is what the card's own status is: a pick or a leg ("result": Ganado/Perdido...) or a whole parlay
 * ("parlay": Ganada/Perdida...). A correction carrying a leg number is always about a leg.
 */
import { RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { formatRelative } from "@/lib/time";
import type { ResultCorrection } from "@/lib/api/v1/types_records";

/** The latest corrections shown; the rest are counted. A record is corrected once or twice, not often. */
const SHOWN = 3;

function word(status: string, parlay: boolean): string {
  return translateOr(`records.${parlay ? "parlayStatus" : "status"}.${status}`, status);
}

export function CorrectionNote({
  corrections,
  record,
  className,
}: {
  corrections: readonly ResultCorrection[] | null | undefined;
  record: "result" | "parlay";
  className?: string | undefined;
}) {
  if (!corrections || corrections.length === 0) return null;
  const shown = corrections.slice(-SHOWN);
  const hidden = corrections.length - shown.length;
  return (
    <div
      role="note"
      data-testid="result-correction"
      title={t("records.correction.help")}
      className={cn("text-caption text-muted-foreground", className)}
    >
      <span className="inline-flex items-center gap-1 font-medium text-warning">
        <RotateCcw aria-hidden className="h-3 w-3" />
        {t("records.correction.title")}
      </span>
      <ul className="mt-0.5 space-y-0.5">
        {shown.map((c) => {
          const ofLeg = c.leg_no !== null && c.leg_no !== undefined;
          const parlay = record === "parlay" && !ofLeg;
          return (
            <li
              key={`${c.at}-${c.leg_no ?? "record"}`}
              title={translateOr(
                `records.correction.cause.${c.cause}`,
                t("records.correction.help"),
              )}
            >
              {ofLeg ? (
                <span className="font-medium">
                  {t("records.correction.leg", { n: c.leg_no })}:{" "}
                </span>
              ) : null}
              {t("records.correction.step", {
                when: formatRelative(c.at),
                from: word(c.from_status, parlay),
                to: word(c.to_status, parlay),
              })}
            </li>
          );
        })}
      </ul>
      {hidden > 0 ? <p>{t("records.correction.more", { n: hidden })}</p> : null}
    </div>
  );
}
