/**
 * Filters on a phone and a tablet (plan UX, A15, section 36: «menús y filtros: hojas que suben desde abajo, con la
 * acción principal al alcance del pulgar»): a «Filtros» button that says how many are on, and a sheet that comes up
 * from the bottom with the controls and, under the thumb, «Ver N ...» and «Borrar filtros». A change applies at once -
 * the list behind the sheet is already the filtered one, and «Ver N» says how long it is.
 *
 * From 1024 px a page shows the same controls in its own row and this button is not there (section 37: at a desk the
 * sheets become the page's own panels). A control drawn in both places must not carry a fixed id: each copy takes its
 * own (useId), so a label always names the field beside it.
 */
import { useState, type ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

export function FilterSheet({
  active,
  onReset,
  showLabel,
  testId,
  title,
  className,
  guide,
  children,
}: {
  /** How many filters are on (shown on the button and in the sheet). */
  active: number;
  /** «Borrar filtros»: every filter of this sheet back to its default. */
  onReset: () => void;
  /** «Ver 12 partidos»: closes the sheet; the list is already filtered. */
  showLabel?: string | undefined;
  /** The base of the test ids: `${testId}-open`, `-sheet`, `-count`, `-reset` and `-show`. */
  testId: string;
  title?: string | undefined;
  className?: string | undefined;
  /** Where a screen's guide rests below 1024 px, when what it points at is inside this sheet (`data-guide`, UX-070). */
  guide?: string | undefined;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const on = active > 0;
  return (
    // The button is the sheet's own trigger: it says it opens a dialog and whether it is open, and the focus comes back
    // to it when the sheet closes.
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          type="button"
          data-testid={`${testId}-open`}
          data-guide={guide}
          className={cn(
            "tap-y relative inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[0.8125rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden",
            on
              ? "border-primary/45 bg-primary/12 text-primary"
              : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
            className,
          )}
        >
          <SlidersHorizontal aria-hidden className="h-4 w-4" />
          {t("common.filters.open")}
          {on ? (
            <>
              <span
                aria-hidden
                data-testid={`${testId}-count`}
                className="numeric inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-xs font-semibold text-primary-foreground"
              >
                {active}
              </span>
              <span className="sr-only">{t("common.filters.active", { count: active })}</span>
            </>
          ) : null}
        </button>
      </SheetTrigger>
      <SheetContent
        side="bottom"
        closeLabel={t("common.close")}
        data-testid={`${testId}-sheet`}
        className="mx-auto flex max-h-[88dvh] max-w-2xl flex-col gap-0 rounded-t-2xl p-0 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]"
      >
        <SheetHeader className="px-4 pb-1 pr-14 pt-4 text-left">
          <SheetTitle className="font-display text-base">
            {title ?? t("common.filters.title")}
          </SheetTitle>
          <SheetDescription className="text-caption">
            {on ? t("common.filters.active", { count: active }) : t("common.filters.description")}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">{children}</div>
        {/* Under the thumb: the main action wider, on the right. */}
        <div className="flex gap-2 border-t border-border px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3">
          <button
            type="button"
            onClick={onReset}
            disabled={!on}
            data-testid={`${testId}-reset`}
            className="min-h-11 flex-1 rounded-lg border border-border-strong px-3 text-sm font-medium transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            {t("common.filters.reset")}
          </button>
          <button
            type="button"
            onClick={() => setOpen(false)}
            data-testid={`${testId}-show`}
            className="min-h-11 flex-[2] rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {showLabel ?? t("common.filters.show")}
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

/**
 * A control of a sheet with its name written above it (in a row of the page the control carries its own). A grid, not a
 * flex column: the pickers grow with flex-1 in the page's row, and in a column that would squeeze them to their text.
 */
export function SheetField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid min-w-0 gap-1.5">
      <span aria-hidden className="text-sm font-medium text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}
