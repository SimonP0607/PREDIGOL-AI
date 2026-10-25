/**
 * Forecast ≠ value ≠ pick (plan UX, A3): the three questions PrediGol answers apart - what is likely, whether it is
 * well paid, and whether PrediGol recommends it. The audit found readers taking a probable result for a
 * recommendation; this says, in three steps, why one does not make the other. Each step's word opens its definition.
 */
import { useId } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import type { TermKey } from "@/lib/glossary";

const LAYERS: ReadonlyArray<readonly ["forecast" | "value" | "pick", TermKey]> = [
  ["forecast", "forecast"],
  ["value", "value"],
  ["pick", "pick"],
];

export function ExplainLayers({
  compact = false,
  className,
}: {
  /** One line per step, for a block's foot (the match page); the full card on the glossary page. */
  compact?: boolean;
  className?: string | undefined;
}) {
  const titleId = useId();
  // inside a block (compact) the heading is one level down: the block has its own h2
  const Heading = compact ? "h3" : "h2";
  return (
    <section
      aria-labelledby={titleId}
      data-testid="explain-layers"
      className={cn(
        compact ? "text-xs" : "rounded-xl border border-border bg-card p-4 sm:p-5",
        className,
      )}
    >
      <Heading
        id={titleId}
        className={cn(
          "font-display font-semibold tracking-tight",
          compact ? "text-xs text-muted-foreground" : "text-base sm:text-lg",
        )}
      >
        {t("glossary.layers.title")}
      </Heading>
      {compact ? null : (
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          {t("glossary.layers.subtitle")}
        </p>
      )}
      <ol className={cn("grid gap-2", compact ? "mt-1.5" : "mt-4 sm:grid-cols-3 sm:gap-3")}>
        {LAYERS.map(([layer, term], i) => (
          <li
            key={layer}
            className={cn(
              "relative min-w-0",
              compact ? "flex flex-wrap items-baseline gap-x-1.5" : "rounded-lg bg-elevated/60 p-3",
            )}
          >
            <span
              className={cn("font-semibold", compact ? "" : "flex items-center gap-1.5 text-sm")}
            >
              <span aria-hidden className="numeric text-subtle-foreground">
                {i + 1}.
              </span>
              <GlossaryTerm term={term}>{t(`glossary.layers.${layer}.title`)}</GlossaryTerm>
              {!compact && i < LAYERS.length - 1 ? (
                <ChevronRight
                  aria-hidden
                  className="ml-auto hidden h-4 w-4 text-subtle-foreground sm:block"
                />
              ) : null}
            </span>
            <span
              className={cn(compact ? "text-muted-foreground" : "mt-1 block text-sm font-medium")}
            >
              {t(`glossary.layers.${layer}.question`)}
            </span>
            <span
              className={cn(
                "text-muted-foreground",
                compact ? "" : "mt-1 block text-xs leading-relaxed",
              )}
            >
              {t(`glossary.layers.${layer}.body`)}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
