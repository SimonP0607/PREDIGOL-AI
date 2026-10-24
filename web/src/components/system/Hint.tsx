import type { ReactElement, ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useTapTooltip } from "./tapTooltip";

type HintProps = {
  /** The help. Empty, null or blank: there is none, and the children render untouched. */
  text: string | null | undefined;
  className?: string | undefined;
} & (
  { asChild?: false | undefined; children: ReactNode } | { asChild: true; children: ReactElement }
);

/**
 * A word of help on a short piece of text: an abbreviation, a column head, an icon, the reason a value is missing or a price
 * cannot be chosen. The native `title` attribute shows only to a mouse that rests on the element and never on a phone (the
 * mobile UX audit, plan F13). This opens on a tap, on hover and on keyboard focus, closes with a second tap or a tap
 * elsewhere, and a screen reader reads the help after the text ("PJ: Partidos jugados").
 *
 * Without help it renders its children as they are, so a value that sometimes has a reason can be wrapped every time.
 * `asChild` puts the trigger on the one element given (a cell, a pill) instead of wrapping the text in a button; that element
 * then says the help to a screen reader itself.
 */
export function Hint({ text, children, className, asChild = false }: HintProps) {
  const tap = useTapTooltip();
  const help = text?.trim();
  if (!help) return <>{children}</>;
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip {...tap.root}>
        {asChild ? (
          <TooltipTrigger asChild {...tap.trigger} tabIndex={0}>
            {children}
          </TooltipTrigger>
        ) : (
          <TooltipTrigger asChild {...tap.trigger}>
            <button
              type="button"
              className={cn(
                "tap relative cursor-help rounded-sm text-inherit underline decoration-dotted decoration-1 underline-offset-[3px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                className,
              )}
            >
              {children}
              <span className="sr-only">{`: ${help}`}</span>
            </button>
          </TooltipTrigger>
        )}
        <TooltipContent className="max-w-xs text-xs leading-relaxed">{help}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
