/** «¿Ves un dato incorrecto?» at the foot of a match (plan UX, A14; section 25): a «wrong data» ticket with the match attached. */
import { Flag } from "lucide-react";
import { t } from "@/lib/i18n";
import { useReportProblem } from "./report";

export function ReportWrongData({ matchId }: { matchId: number }) {
  const report = useReportProblem();
  if (!report.available || !Number.isInteger(matchId) || matchId <= 0) return null;
  return (
    <div className="flex justify-center pt-1">
      <button
        type="button"
        onClick={() => report.open({ category: "wrong_data", matchId })}
        data-testid="match-report"
        className="tap-y relative inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-muted-foreground hover:text-primary pointer-coarse:min-h-11"
      >
        <Flag aria-hidden className="h-3.5 w-3.5" />
        {t("support.match.report")}
      </button>
    </div>
  );
}
