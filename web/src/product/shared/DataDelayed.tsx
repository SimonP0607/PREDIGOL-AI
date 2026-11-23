/** The one sentence a reader gets when data is late (plan UX, AP-I02; thresholds in `lib/freshness.ts`). */
import { Clock } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function DataDelayed({ className, testId }: { className?: string; testId?: string }) {
  return (
    <p
      role="status"
      data-testid={testId ?? "data-delayed"}
      className={cn("inline-flex items-center gap-1.5 text-xs font-medium text-warning", className)}
    >
      <Clock aria-hidden className="h-3.5 w-3.5 shrink-0" />
      {t("common.dataDelayed")}
    </p>
  );
}
