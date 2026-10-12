import { Info } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { glossaryText, type GlossaryKey } from "@/lib/glossary";
import { t } from "@/lib/i18n";
import { useTapTooltip } from "./tapTooltip";

/** Metric label with an accessible definition from the shared glossary. */
export function InfoTip({
  term,
  children,
  className,
}: {
  term: GlossaryKey;
  children?: React.ReactNode;
  className?: string;
}) {
  const text = glossaryText(term);
  // A non-text label (an element) cannot be spelled out: the definition alone names it.
  const name =
    children === undefined || children === null
      ? term
      : typeof children === "string" || typeof children === "number"
        ? String(children)
        : null;
  const tap = useTapTooltip();
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip {...tap.root}>
        <TooltipTrigger asChild>
          <button
            type="button"
            {...tap.trigger}
            aria-label={
              name === null
                ? t("admin.ui.infoTipNoTerm", { text })
                : t("admin.ui.infoTip", { term: name, text })
            }
            className={cn(
              "tap relative inline-flex items-center gap-1 rounded text-inherit focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              className,
            )}
          >
            {children}
            <Info aria-hidden className="h-3 w-3 shrink-0 opacity-50" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-xs leading-relaxed">{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/** Column header variant: keeps the table header typography intact. */
export function MetricLabel({ term, children }: { term: GlossaryKey; children: React.ReactNode }) {
  return (
    <InfoTip term={term} className="text-label font-semibold text-subtle-foreground">
      {children}
    </InfoTip>
  );
}
