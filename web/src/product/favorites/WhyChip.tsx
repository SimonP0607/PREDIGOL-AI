/**
 * Why an element is shown to the reader (plan UX, A13 and B2; section 38: «siempre explicable»): «Sigues a Nacional»,
 * «Tu liga» or «Sugerida» - one line that truncates rather than break a card at 320 px - and, with a tap, the whole
 * sentence («Te mostramos este partido porque sigues a Atlético Nacional»).
 */
import { hintProps } from "@/components/system/tapHint";
import { cn } from "@/lib/utils";
import { whyText, type Why } from "@/product/home/why";

export function WhyChip({
  why,
  testId = "today-why",
  className,
}: {
  why: Why;
  testId?: string;
  className?: string;
}) {
  const { label, help } = whyText(why);
  return (
    <span
      {...hintProps(help)}
      data-testid={testId}
      data-why={why.kind}
      className={cn(
        "min-w-0 max-w-full truncate rounded-full border border-primary/30 bg-primary/10 px-2 py-px font-medium text-primary",
        className,
      )}
    >
      {label}
    </span>
  );
}
