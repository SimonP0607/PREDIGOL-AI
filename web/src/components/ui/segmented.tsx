import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The segmented control of «Noche de partido» (the system's sheet 3): one choice out of a few that fit on a line - a
 * language, a period, a format. A radio group to a screen reader and to the keyboard: one stop of Tab, the arrows (and
 * Home and End) move the choice. Each segment answers at 44 px under a finger though it looks 32 or 40.
 */
export interface SegmentedOption<T extends string> {
  value: T;
  label: React.ReactNode;
  /**
   * What a screen reader adds when the label is not words («ES» → «ES, Español»). Added after the label, never in its
   * place: the name a voice user says is the one on the screen (WCAG 2.5.3, label in name).
   */
  name?: string | undefined;
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "default",
  full = false,
  className,
  testId,
}: {
  value: T;
  onChange: (next: T) => void;
  options: ReadonlyArray<SegmentedOption<T>>;
  /** What is being chosen: the group's accessible name. */
  label: string;
  size?: "default" | "lg";
  /** As wide as its container, the segments sharing it. */
  full?: boolean;
  className?: string | undefined;
  /** `<testId>` on the group and `<testId>-<value>` on each segment. */
  testId?: string | undefined;
}) {
  const refs = React.useRef<Array<HTMLButtonElement | null>>([]);
  const chosen = options.findIndex((o) => o.value === value);
  const move = (to: number) => {
    const next = options[(to + options.length) % options.length];
    if (!next) return;
    onChange(next.value);
    refs.current[(to + options.length) % options.length]?.focus();
  };
  const onKeyDown = (event: React.KeyboardEvent, at: number) => {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") move(at + 1);
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") move(at - 1);
    else if (event.key === "Home") move(0);
    else if (event.key === "End") move(options.length - 1);
    else return;
    event.preventDefault();
  };
  return (
    <div
      role="radiogroup"
      aria-label={label}
      data-testid={testId}
      className={cn(
        "rounded-full border border-border bg-card p-[3px]",
        full ? "flex" : "inline-flex",
        className,
      )}
    >
      {options.map((option, at) => {
        const on = option.value === value;
        return (
          <button
            key={option.value}
            ref={(el) => {
              refs.current[at] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            // one stop of Tab: the chosen segment, or the first when none is
            tabIndex={on || (chosen === -1 && at === 0) ? 0 : -1}
            data-testid={testId ? `${testId}-${option.value}` : undefined}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, at)}
            className={cn(
              "tap-y motion-press relative inline-flex cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-full font-display font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
              size === "lg"
                ? "h-10 px-4 text-sm"
                : "h-8 min-w-[2.375rem] px-2.5 text-xs tracking-[0.04em]",
              full && "flex-1",
              on ? "bg-primary-soft text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
            {option.name ? <span className="sr-only">, {option.name}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
