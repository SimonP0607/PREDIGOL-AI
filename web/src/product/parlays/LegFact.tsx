/**
 * The line of why under a leg of a recorded parlay (plan de Inicio, 2.4b): one fact of the match's reading that stands behind the
 * side the leg backs - a run without defeat, a key player out for the other side, what the side plays for - worded by the same
 * templates the match's reading uses. A leg without such a fact has no line: nothing is made up to fill it.
 */
import { Lightbulb } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReadingFact } from "@/lib/api/v1/types_reading";
import { factText } from "@/product/reading/text";

export function LegFact({
  fact,
  className,
}: {
  fact: ReadingFact | null | undefined;
  className?: string | undefined;
}) {
  const text = fact ? factText(fact) : null;
  if (!text) return null;
  return (
    <p
      data-testid="leg-fact"
      className={cn("flex items-start gap-1.5 text-caption text-muted-foreground", className)}
    >
      <Lightbulb aria-hidden className="mt-0.5 h-3 w-3 shrink-0 text-gold-strong" />
      <span className="min-w-0">{text}</span>
    </p>
  );
}
