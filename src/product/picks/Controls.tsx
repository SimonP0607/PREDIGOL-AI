/** Small controls shared by the Picks and Odds pages: filter chips and the admin-only shadow switch. */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface ChipOption<T extends string | number> {
  value: T;
  label: ReactNode;
  title?: string | undefined;
}

/** A row of toggle chips where exactly one is on. */
export function ChipGroup<T extends string | number>({
  label,
  value,
  options,
  onChange,
  className,
  testId,
}: {
  /** What the group chooses, for assistive technology. */
  label: string;
  value: T;
  options: ReadonlyArray<ChipOption<T>>;
  onChange: (value: T) => void;
  className?: string | undefined;
  testId?: string | undefined;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      data-testid={testId}
      className={cn("flex flex-wrap gap-1.5", className)}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={on}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex h-9 items-center whitespace-nowrap rounded-full border px-3.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              on
                ? "border-primary/50 bg-primary/12 text-primary"
                : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export { ShadowToggle } from "@/product/shared/ShadowToggle";
