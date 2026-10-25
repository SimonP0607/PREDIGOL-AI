import { useId, useRef, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { BookOpen } from "lucide-react";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { GLOSSARY_PATH, termAnchor, termName, termShort, type TermKey } from "@/lib/glossary";

/** A finger, or a screen too narrow for a card beside the word: the definition comes up from the bottom. */
const SHEET_QUERY = "(pointer: coarse), (max-width: 639px)";

function wantsSheet(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(SHEET_QUERY).matches;
}

/**
 * A word with its definition from the glossary (plan UX, A3). A tap, a click, Enter or Space opens it: a small card
 * beside the word on a desk, a sheet from the bottom of a phone (closed by a tap outside it, its button or Escape),
 * with the way to the whole glossary. The word stays a word - dotted underline, the reader's own text - and a
 * screen reader hears it as a button that opens a dialog.
 *
 * The same markup on the server and in the browser (no hydration mismatch): which of the two opens is decided on the
 * tap itself. Never inside a link (a card that is one link): there the figure carries the same definition as its
 * hint (hintProps(termShort(...))), as A1 left them.
 */
export function GlossaryTerm({
  term,
  children,
  className,
}: {
  term: TermKey;
  /** What reads on the screen; by default the term's own name. */
  children?: ReactNode;
  className?: string | undefined;
}) {
  const [open, setOpen] = useState<"card" | "sheet" | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const name = termName(term);
  const close = () => {
    setOpen(null);
    // the reader is back where they were: on the word (Radix gives the focus back to its own triggers only)
    requestAnimationFrame(() => button.current?.focus());
  };
  const body = (
    <>
      <p className="text-sm leading-relaxed text-foreground" data-testid="glossary-short">
        {termShort(term)}
      </p>
      <Link
        to={GLOSSARY_PATH}
        hash={termAnchor(term)}
        onClick={() => setOpen(null)}
        className="tap relative inline-flex items-center gap-1.5 self-start rounded-sm text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="glossary-more"
      >
        <BookOpen aria-hidden className="h-4 w-4" />
        {t("glossary.ui.more")}
      </Link>
    </>
  );
  return (
    <>
      <Popover open={open === "card"} onOpenChange={(next) => (next ? setOpen("card") : close())}>
        <PopoverAnchor asChild>
          <button
            ref={button}
            type="button"
            data-glossary={term}
            aria-haspopup="dialog"
            aria-expanded={open !== null}
            onClick={() => setOpen(open ? null : wantsSheet() ? "sheet" : "card")}
            className={cn(
              "tap relative cursor-help rounded-sm text-inherit underline decoration-dotted decoration-1 underline-offset-[3px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              className,
            )}
          >
            {children ?? name}
          </button>
        </PopoverAnchor>
        <PopoverContent
          role="dialog"
          aria-labelledby={titleId}
          data-testid="glossary-card"
          className="flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2.5"
          onCloseAutoFocus={(e) => e.preventDefault()}
        >
          <h2 id={titleId} className="font-display text-base font-semibold">
            {name}
          </h2>
          {body}
        </PopoverContent>
      </Popover>
      <Sheet open={open === "sheet"} onOpenChange={(next) => (next ? setOpen("sheet") : close())}>
        <SheetContent
          side="bottom"
          closeLabel={t("glossary.ui.close")}
          data-testid="glossary-sheet"
          className="max-h-[85dvh] overflow-y-auto rounded-t-2xl px-5 pb-[calc(1.5rem+env(safe-area-inset-bottom))] pt-5"
          onCloseAutoFocus={(e) => e.preventDefault()}
        >
          <SheetHeader className="pr-10 text-left">
            <SheetTitle className="font-display">{name}</SheetTitle>
            {/* the definition is the dialog's description: a screen reader says it on opening */}
            <SheetDescription className="sr-only">{termShort(term)}</SheetDescription>
          </SheetHeader>
          <div className="mt-3 flex flex-col gap-3">{body}</div>
        </SheetContent>
      </Sheet>
    </>
  );
}

/** The way to a term's entry on the glossary page («Ver en el glosario»), after a text that already explains it. */
export function GlossaryLink({
  term,
  className,
}: {
  term: TermKey;
  className?: string | undefined;
}) {
  return (
    <Link
      to={GLOSSARY_PATH}
      hash={termAnchor(term)}
      data-glossary-link={term}
      className={cn(
        "tap-y relative whitespace-nowrap rounded-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
    >
      {t("glossary.ui.more")}
    </Link>
  );
}
